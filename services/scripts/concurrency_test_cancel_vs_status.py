"""顧客キャンセルと店員ステータス更新の同時実行テスト(Issue #57、実AWS dev環境専用の手動検証)。

同じ注文・同じ明細に対して、次の2つのAPIを「ほぼ同時」に送り、DynamoDBの条件付き書き込みが
設計どおり「どちらか一方だけ成功させる」かを確かめる。

- 顧客: `PATCH /orders/{orderId}/cancel`
  (order-fn。全明細に`status = WAITING`を条件とするTransactWriteItems)
- 店員: `PATCH /orders/{orderId}/lines/{lineId}/status` で WAITING→PREPARING
  (store-fn。`status = :from`を条件とする単発UpdateItem)

判定は2段階で行う(「データが壊れた」と「データは正しいがAPIの返事が不正確」を区別するため)。
1. DynamoDBの最終状態(強整合読み)だけを見て、どちらが勝ったかを決める
   - cancelled: 全明細CANCELLED かつ METAもCANCELLED
   - prepared : 対象明細PREPARING かつ CANCELLEDがどこにも無い
   - unchanged: 対象明細がWAITINGのまま(どちらも反映されなかった)
   - それ以外は inconsistent(データ不整合。最も重大)
2. その勝者に対して、APIの応答コードが正しいかを確かめる
   - cancelled なら キャンセル200 + 更新409、prepared なら 更新200 + キャンセル409 が正解

テスト注文は専用の店舗ID(既定`concurrency-test`)で作る。普段使う店舗(store-01)の店員画面の
ゾーンキューに、テストで調理中になった明細が混ざらないようにするため。prepared になった注文は
`concurrency-test`店舗のキューにPREPARINGのまま残るが、他の店舗には影響しない。

pytest・scripts/verify.sh には含めない(実AWSへ書き込む手動検証ツールのため)。

使い方(servicesディレクトリから実行、事前に `pip install -e ".[dev,load-test]"`):
    export STAFF_USERNAME=... STAFF_PASSWORD=...   # dev環境の店員アカウント
    python scripts/concurrency_test_cancel_vs_status.py --stage dev --trials 3    # まず小規模で
    python scripts/concurrency_test_cancel_vs_status.py --stage dev --trials 50
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import boto3
import httpx
from boto3.dynamodb.conditions import Key

# services/src をimportパスに追加する(このスクリプトはpytestのpythonpath設定の対象外のため)。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from load_test_peak import (  # noqa: E402
    STATEFUL_STACK_NAME_TEMPLATE,
    CatalogEntry,
    build_item_catalog,
    resolve_http_api_url,
    resolve_table_name,
)

from domain.order.models import (  # noqa: E402
    ORDER_LINE_SORT_KEY_PREFIX,
    ORDER_META_SORT_KEY,
    ORDER_PARTITION_KEY_PREFIX,
)

# 決済確定(auto-approveプロバイダ)待ちのポーリング上限。auto-approveは初回GETで即確定するため、
# 数回で確定しなければ環境側の問題(paymentProvider設定違いなど)とみなして打ち切る。
FINALIZE_POLL_ATTEMPTS = 5
FINALIZE_POLL_INTERVAL_SECONDS = 1.0

FinalState = Literal["cancelled", "prepared", "unchanged", "inconsistent"]
Category = Literal["ok", "api_mismatch", "data_inconsistent"]

# 最終状態ごとの「正しい応答コード」の組(キャンセル側, 更新側)。unchangedには正解が無い
# (どちらか一方は成功すべきなので、両方失敗は常にAPIの不具合扱い)。
EXPECTED_RESPONSES: dict[FinalState, tuple[int, int]] = {
    "cancelled": (200, 409),
    "prepared": (409, 200),
}


@dataclass
class TrialResult:
    """1回の試行(注文作成〜同時発火〜最終状態確認)の記録。"""

    trial: int
    order_id: str
    line_id: str
    offset_ms: float
    cancel_status: int | None
    update_status: int | None
    cancel_body: str
    update_body: str
    final_meta_status: str | None
    final_line_statuses: dict[str, str]
    final_state: FinalState
    category: Category


def resolve_staff_client_id(stage: str) -> str:
    """StatefulスタックのCFN Outputsから、店員用CognitoアプリクライアントIDを解決する。"""
    stack_name = STATEFUL_STACK_NAME_TEMPLATE.format(stage=stage)
    outputs = boto3.client("cloudformation").describe_stacks(StackName=stack_name)["Stacks"][0][
        "Outputs"
    ]
    for output in outputs:
        if output["OutputKey"] == "StaffUserPoolClientId":
            return str(output["OutputValue"])
    raise RuntimeError(f"StaffUserPoolClientId output not found in stack {stack_name}")


def fetch_staff_id_token(client_id: str) -> str:
    """環境変数の店員アカウントでCognitoにログインし、IdTokenを取得する。

    店員UI(web/src/lib/staff.ts)と同じく`Authorization: Bearer <IdToken>`で使う。
    認証方式はPR #42で一本化した`USER_PASSWORD_AUTH`。IdTokenの有効期限(既定1時間)は
    50試行程度なら十分収まるため、途中での再取得はしない。
    """
    username = os.environ.get("STAFF_USERNAME")
    password = os.environ.get("STAFF_PASSWORD")
    if not username or not password:
        raise SystemExit("環境変数 STAFF_USERNAME / STAFF_PASSWORD を設定してください")
    response = boto3.client("cognito-idp").initiate_auth(
        ClientId=client_id,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": username, "PASSWORD": password},
    )
    result = response.get("AuthenticationResult")
    if result is None:
        # NEW_PASSWORD_REQUIREDなどのチャレンジが返った場合。スクリプトでは対応しない。
        raise SystemExit(f"ログインが完了しませんでした(challenge={response.get('ChallengeName')})")
    return str(result["IdToken"])


async def prepare_waiting_order(
    client: httpx.AsyncClient, base_url: str, store_id: str, entry: CatalogEntry
) -> tuple[str, str]:
    """1品だけの注文を作り、決済確定まで進めて(orderId, lineId)を返す。

    POST /orders は決済待ち(PENDING_PAYMENT)の仮注文を作るだけなので、続けて GET /orders/{id}
    を呼び、status-fnに決済確認→確定(明細の作成、WAITING状態)をさせる(requirements.md §12.1.1)。
    """
    session_id = str(uuid.uuid4())
    cart_response = await client.post(
        f"{base_url}/cart/{session_id}/items",
        json={
            "productId": entry.product_id,
            "category": entry.category,
            "variant": {"temperature": entry.temperature, "size": entry.size},
            "quantity": 1,
        },
    )
    cart_response.raise_for_status()

    order_response = await client.post(
        f"{base_url}/orders",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"sessionId": session_id, "storeId": store_id},
    )
    if order_response.status_code != 201:
        raise RuntimeError(
            f"POST /orders failed: {order_response.status_code} {order_response.text}"
        )
    order_id = str(order_response.json()["orderId"])

    for _ in range(FINALIZE_POLL_ATTEMPTS):
        status_response = await client.get(f"{base_url}/orders/{order_id}")
        status_response.raise_for_status()
        body = status_response.json()
        lines = body.get("lines")
        if lines:  # 確定済みのレスポンスにだけ明細(lines)がある
            if any(line["status"] != "WAITING" for line in lines):
                raise RuntimeError(f"freshly finalized order {order_id} has non-WAITING lines")
            return order_id, str(lines[0]["lineId"])
        await asyncio.sleep(FINALIZE_POLL_INTERVAL_SECONDS)

    raise RuntimeError(
        f"order {order_id} was not finalized after {FINALIZE_POLL_ATTEMPTS} polls "
        "(is the dev stack deployed with paymentProvider=auto-approve?)"
    )


async def warm_connections(
    cancel_client: httpx.AsyncClient, staff_client: httpx.AsyncClient, base_url: str
) -> None:
    """同時発火の直前に、キャンセル用・店員用の両クライアントで接続を温めておく。

    片方だけが新規のTCP/TLS接続を張ると、その側だけ毎回数十ms以上遅れ、勝敗が一方に偏る
    (競合を検証したつもりで、実は片方の順序しか試していない状態になる)。両方に軽い
    GET /menu を同時に送り、どちらも使い回し可能な接続を持った状態で本番のリクエストを送る。
    """
    await asyncio.gather(
        cancel_client.get(f"{base_url}/menu"), staff_client.get(f"{base_url}/menu")
    )


async def _send_after(
    client: httpx.AsyncClient, delay_seconds: float, method: str, url: str, **kwargs: Any
) -> httpx.Response | None:
    """delay_seconds待ってから1回リクエストを送る。通信エラーはNoneで返す(試行を止めないため)。"""
    if delay_seconds > 0:
        await asyncio.sleep(delay_seconds)
    try:
        return await client.request(method, url, **kwargs)
    except httpx.HTTPError:
        return None


async def fire_race(
    cancel_client: httpx.AsyncClient,
    staff_client: httpx.AsyncClient,
    base_url: str,
    order_id: str,
    line_id: str,
    id_token: str,
    offset_ms: float,
) -> tuple[httpx.Response | None, httpx.Response | None]:
    """キャンセルと明細ステータス更新を同時に送り、(キャンセル応答, 更新応答)を返す。

    offset_msが正なら更新側を、負ならキャンセル側をその分だけ遅らせる。毎回0msだと
    経路や処理量の差で常に同じ側が先に着きがちなため、前後にずらして両方の順序を試す。
    """
    delay = abs(offset_ms) / 1000
    cancel_delay, update_delay = (0.0, delay) if offset_ms >= 0 else (delay, 0.0)
    cancel_response, update_response = await asyncio.gather(
        _send_after(cancel_client, cancel_delay, "PATCH", f"{base_url}/orders/{order_id}/cancel"),
        _send_after(
            staff_client,
            update_delay,
            "PATCH",
            f"{base_url}/orders/{order_id}/lines/{line_id}/status",
            headers={"Authorization": f"Bearer {id_token}"},
            json={"fromStatus": "WAITING", "toStatus": "PREPARING"},
        ),
    )
    return cancel_response, update_response


def read_final_state(table: Any, order_id: str) -> tuple[str | None, dict[str, str]]:
    """注文のMETAと全明細を強整合読みで取得し、(METAのderivedStatus, {lineId: status})を返す。

    OrderRepository.get_order()は結果整合読みのため使わない(書き込み直後の確認なので、
    古い値を読んで「異常なし」と誤判定するのを避けたい)。1注文はMETA+明細数件なので
    1ページに収まり、ページング(LastEvaluatedKey)は不要。
    """
    response = table.query(
        KeyConditionExpression=Key("PK").eq(f"{ORDER_PARTITION_KEY_PREFIX}{order_id}"),
        ConsistentRead=True,
    )
    meta_status: str | None = None
    line_statuses: dict[str, str] = {}
    for item in response["Items"]:
        sort_key = str(item["SK"])
        if sort_key == ORDER_META_SORT_KEY:
            meta_status = str(item.get("derivedStatus"))
        elif sort_key.startswith(ORDER_LINE_SORT_KEY_PREFIX):
            line_statuses[sort_key.removeprefix(ORDER_LINE_SORT_KEY_PREFIX)] = str(item["status"])
    return meta_status, line_statuses


def classify_final_state(
    target_line_id: str, meta_status: str | None, line_statuses: dict[str, str]
) -> FinalState:
    """DynamoDBの最終状態だけから、どちらの書き込みが反映されたかを判定する(判定の1段階目)。

    update_line_status()はMETAに触れないため、prepared/unchangedではMETAのderivedStatusは
    確定時の値のまま(CANCELLEDでなければよい)。
    """
    if meta_status is None or not line_statuses:
        return "inconsistent"
    statuses = set(line_statuses.values())
    if statuses == {"CANCELLED"} and meta_status == "CANCELLED":
        return "cancelled"
    if "CANCELLED" in statuses or meta_status == "CANCELLED":
        return "inconsistent"  # 一部だけキャンセル、またはMETAと明細の食い違い
    target_status = line_statuses.get(target_line_id)
    if target_status == "PREPARING":
        return "prepared"
    if target_status == "WAITING":
        return "unchanged"
    return "inconsistent"


def judge(
    cancel_status: int | None, update_status: int | None, final_state: FinalState
) -> Category:
    """最終状態に対して、APIの応答コードが正しかったかを判定する(判定の2段階目)。

    - data_inconsistent: データ自体が矛盾している(最も重大)
    - api_mismatch: データは正しいが、応答コードが実際の結果と合っていない
      (例: 競合で500を返した、両方409で何も反映されなかった、反映されなかった側が200を返した)
    """
    if final_state == "inconsistent":
        return "data_inconsistent"
    if EXPECTED_RESPONSES.get(final_state) == (cancel_status, update_status):
        return "ok"
    return "api_mismatch"


async def run_trials(
    args: argparse.Namespace, base_url: str, catalog: list[CatalogEntry], id_token: str, table: Any
) -> tuple[list[TrialResult], list[str]]:
    """ウォームアップ→本番試行を1件ずつ順番に実行する(試行同士は干渉させない)。

    注文の準備段階での失敗(一時的なHTTPエラーなど)は、その試行だけスキップして続行する
    (50回のうち1回の準備失敗で、それまでの結果ごと失わないため)。戻り値は
    (本番試行の結果, スキップ理由の一覧)。
    """
    rng = random.Random(args.seed)
    results: list[TrialResult] = []
    skipped: list[str] = []
    timeout = httpx.Timeout(args.request_timeout_seconds)
    # 準備用・キャンセル用・店員用でクライアント(=接続プール)を分け、同時発火する2本が
    # 互いの接続の取り合いや、準備用リクエストの影響を受けないようにする。
    async with (
        httpx.AsyncClient(timeout=timeout) as prep_client,
        httpx.AsyncClient(timeout=timeout) as cancel_client,
        httpx.AsyncClient(timeout=timeout) as staff_client,
    ):
        total = args.warmup + args.trials
        for index in range(total):
            is_warmup = index < args.warmup
            label = "warmup" if is_warmup else f"trial {index - args.warmup + 1}/{args.trials}"
            try:
                order_id, line_id = await prepare_waiting_order(
                    prep_client, base_url, args.store_id, rng.choice(catalog)
                )
                await warm_connections(cancel_client, staff_client, base_url)
            except (httpx.HTTPError, RuntimeError, KeyError) as exc:
                print(f"[{label}] SKIP 準備に失敗: {exc!r}")
                if not is_warmup:
                    skipped.append(f"{label}: {exc!r}")
                continue

            offset_ms = rng.uniform(-args.max_offset_ms, args.max_offset_ms)
            cancel_response, update_response = await fire_race(
                cancel_client, staff_client, base_url, order_id, line_id, id_token, offset_ms
            )
            meta_status, line_statuses = read_final_state(table, order_id)
            cancel_status = cancel_response.status_code if cancel_response is not None else None
            update_status = update_response.status_code if update_response is not None else None
            final_state = classify_final_state(line_id, meta_status, line_statuses)
            category = judge(cancel_status, update_status, final_state)

            print(
                f"[{label}] {category} final={final_state} offset={offset_ms:+6.1f}ms "
                f"cancel={cancel_status} update={update_status} order={order_id}"
            )
            if is_warmup:
                continue
            results.append(
                TrialResult(
                    trial=index - args.warmup + 1,
                    order_id=order_id,
                    line_id=line_id,
                    offset_ms=round(offset_ms, 1),
                    cancel_status=cancel_status,
                    update_status=update_status,
                    cancel_body=cancel_response.text if cancel_response is not None else "",
                    update_body=update_response.text if update_response is not None else "",
                    final_meta_status=meta_status,
                    final_line_statuses=line_statuses,
                    final_state=final_state,
                    category=category,
                )
            )
    return results, skipped


def summarize(results: list[TrialResult], skipped: list[str]) -> str:
    """勝敗・判定の内訳と、異常だった試行の詳細(レスポンス本文込み)を文字列にまとめる。"""
    lines = ["== 最終状態の内訳(どちらが勝ったか) =="]
    state_counts = Counter(r.final_state for r in results)
    for state, count in state_counts.most_common():
        lines.append(f"- {state}: {count}")
    if state_counts["cancelled"] == 0 or state_counts["prepared"] == 0:
        lines.append(
            "  ⚠ 片方の順序しか起きていません。両方の順序で競合を検証できていないため、"
            "--max-offset-ms を広げて再実行してください"
        )

    lines.append("")
    lines.append("== 判定の内訳 ==")
    for category, count in Counter(r.category for r in results).most_common():
        lines.append(f"- {category}: {count}")
    response_patterns = Counter(
        (r.final_state, r.cancel_status, r.update_status) for r in results if r.category != "ok"
    )
    for (state, cancel, update), count in response_patterns.most_common():
        lines.append(f"    {state} で cancel={cancel} update={update}: {count}件")

    anomalies = [r for r in results if r.category != "ok"]
    lines.append("")
    lines.append(f"== 異常の詳細: {len(anomalies)}/{len(results)} ==")
    for r in anomalies:
        lines.append(f"- trial {r.trial} [{r.category}] order={r.order_id} offset={r.offset_ms}ms")
        lines.append(f"    cancel {r.cancel_status}: {r.cancel_body}")
        lines.append(f"    update {r.update_status}: {r.update_body}")
        lines.append(f"    final meta={r.final_meta_status} lines={r.final_line_statuses}")

    if skipped:
        lines.append("")
        lines.append(f"== 準備失敗でスキップした試行: {len(skipped)} ==")
        lines.extend(f"- {reason}" for reason in skipped)
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    """CLI引数を解析する。"""
    parser = argparse.ArgumentParser(
        description="顧客キャンセルと店員ステータス更新の同時実行テスト(Issue #57、実AWS dev環境)"
    )
    parser.add_argument("--stage", choices=["dev"], required=True)
    parser.add_argument("--api-url", default=None, help="省略時はCFN Outputsから自動解決する")
    parser.add_argument("--store-id", default="concurrency-test")
    parser.add_argument("--trials", type=int, default=50)
    parser.add_argument(
        "--warmup",
        type=int,
        default=2,
        help="集計に含めない最初の試行数(Lambdaのコールドスタートによる偏りを除く)",
    )
    parser.add_argument(
        "--max-offset-ms",
        type=float,
        default=30.0,
        help="2つのリクエストの送信タイミングを、この範囲(±ms)でランダムにずらす",
    )
    parser.add_argument("--request-timeout-seconds", type=float, default=10.0)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--output-json", type=Path, default=None)
    args = parser.parse_args()
    if args.trials < 1 or args.warmup < 0 or args.max_offset_ms < 0:
        parser.error("--trials must be >= 1, --warmup and --max-offset-ms must be >= 0")
    return args


def main() -> None:
    args = parse_args()
    api_url = args.api_url or resolve_http_api_url(args.stage)
    print(f"target API: {api_url}  store_id={args.store_id}")

    id_token = fetch_staff_id_token(resolve_staff_client_id(args.stage))
    print("staff login: OK")

    menu_response = httpx.get(f"{api_url}/menu", timeout=args.request_timeout_seconds)
    menu_response.raise_for_status()
    catalog = build_item_catalog(menu_response.json())
    table = boto3.resource("dynamodb").Table(resolve_table_name(args.stage))

    started_at = time.monotonic()
    results, skipped = asyncio.run(run_trials(args, api_url, catalog, id_token, table))
    print(f"\nfinished {len(results)} trials in {time.monotonic() - started_at:.1f}s\n")
    print(summarize(results, skipped))

    if args.output_json is not None:
        report = {"trials": [asdict(r) for r in results], "skipped": skipped}
        args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"\nJSONレポートを書き込みました: {args.output_json}")

    all_ok = bool(results) and all(r.category == "ok" for r in results)
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
