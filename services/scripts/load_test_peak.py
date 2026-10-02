"""想定ピーク負荷の再現テスト(実AWS dev環境専用の手動検証スクリプト)。

docs/requirements.md が明記する想定負荷(最大同時接続100人、ピークでも注文は
1秒あたり1件未満)を実際のAPI Gateway/Lambda/DynamoDBに対して再現し、エラー率・
レイテンシ・ゾーン別カウンタ(queueSeq)の重複有無を確認する。

スタッフ側API(店員の進捗操作)は呼ばない。投入した注文は全てWAITINGのまま残る
(お客さんがアプリで待ち続ける状況の再現が目的で、製造フロー全体の再現ではない)。

pytest・scripts/verify.sh には含めない(実AWSへ書き込む手動検証ツールのため)。

使い方(servicesディレクトリから実行、事前に `pip install -e ".[dev,load-test]"`):
    python scripts/load_test_peak.py --stage dev --orders 5   # まず小規模で動作確認
    python scripts/load_test_peak.py --stage dev              # 既定100件(想定ピーク再現)
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import random
import statistics
import sys
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import boto3
import httpx

# services/src をimportパスに追加する(このスクリプトはpytestのpythonpath設定の対象外のため)。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from adapters.order_repository import OrderRepository  # noqa: E402
from domain.fulfillment.models import Zone  # noqa: E402

STATEFUL_STACK_NAME_TEMPLATE = "MobileOrder-{stage}-Stateful"
APP_STACK_NAME_TEMPLATE = "MobileOrder-{stage}-App"
ZONES: tuple[Zone, ...] = ("A", "B", "C", "D")


def resolve_table_name(stage: str) -> str:
    """StatefulスタックからDynamoDBテーブルの物理名を解決する(seed_menu.pyと同じパターン)。"""
    stack_name = STATEFUL_STACK_NAME_TEMPLATE.format(stage=stage)
    cfn = boto3.client("cloudformation")
    resources = cfn.describe_stack_resources(StackName=stack_name)["StackResources"]
    tables = [r for r in resources if r["ResourceType"] == "AWS::DynamoDB::Table"]
    if len(tables) != 1:
        raise RuntimeError(
            f"expected exactly 1 AWS::DynamoDB::Table in stack {stack_name}, found {len(tables)}"
        )
    physical_id = tables[0]["PhysicalResourceId"]
    if not isinstance(physical_id, str):
        raise RuntimeError(f"unexpected PhysicalResourceId type: {type(physical_id)!r}")
    return physical_id


def resolve_http_api_url(stage: str) -> str:
    """AppスタックのCFN Outputsから、公開HTTP APIのベースURLを解決する。"""
    stack_name = APP_STACK_NAME_TEMPLATE.format(stage=stage)
    cfn = boto3.client("cloudformation")
    outputs = cfn.describe_stacks(StackName=stack_name)["Stacks"][0]["Outputs"]
    for output in outputs:
        if output["OutputKey"] == "HttpApiUrl":
            return str(output["OutputValue"])
    raise RuntimeError(f"HttpApiUrl output not found in stack {stack_name}")


@dataclass
class CatalogEntry:
    """負荷生成用に選べる1つの有効な(商品, カテゴリ, 温度, サイズ)の組。"""

    product_id: str
    category: str
    temperature: str
    size: str


def build_item_catalog(menu_json: dict[str, Any]) -> list[CatalogEntry]:
    """GET /menuのレスポンスから、カート追加に使える有効な組み合わせを全て列挙する。

    available=False の商品は除外する。温度はallowHot/allowIcedで、サイズはsizeDeltaの
    キーで絞り込む(services/src/domain/menu/models.py のProduct定義に準拠)。
    """
    entries: list[CatalogEntry] = []
    for category_group in menu_json["categories"]:
        for product in category_group["products"]:
            if not product["available"]:
                continue
            temperatures = []
            if product["allowHot"]:
                temperatures.append("hot")
            if product["allowIced"]:
                temperatures.append("iced")
            for temperature in temperatures:
                for size in product["sizeDelta"]:
                    entries.append(
                        CatalogEntry(
                            product_id=product["productId"],
                            category=product["category"],
                            temperature=temperature,
                            size=size,
                        )
                    )
    if not entries:
        raise RuntimeError(
            "menu catalog is empty; run `python scripts/seed_menu.py --stage <stage>` first"
        )
    return entries


@dataclass
class RequestResult:
    """1回のHTTPリクエストの計測結果。"""

    endpoint: str
    status_code: int | None
    latency_ms: float
    error: str | None


@dataclass
class SessionResult:
    """1セッション(カート作成〜注文〜ポーリング)全体の結果。"""

    session_id: str
    order_id: str | None = None
    order_number: int | None = None
    success: bool = False
    failure_reason: str | None = None
    poll_count: int = 0


class MetricsCollector:
    """全セッション共通の計測値を集約する(asyncioの単一スレッド実行なのでロック不要)。"""

    def __init__(self) -> None:
        self.results: list[RequestResult] = []
        self.active_sessions = 0
        self.peak_active_sessions = 0

    def record(self, result: RequestResult) -> None:
        self.results.append(result)

    def session_started(self) -> None:
        self.active_sessions += 1
        self.peak_active_sessions = max(self.peak_active_sessions, self.active_sessions)

    def session_finished(self) -> None:
        self.active_sessions -= 1


async def _request(
    client: httpx.AsyncClient,
    metrics: MetricsCollector,
    semaphore: asyncio.Semaphore,
    endpoint_label: str,
    method: str,
    url: str,
    **kwargs: Any,
) -> httpx.Response | None:
    """1回のHTTPリクエストを送り、計測・例外処理を一元化する共通ヘルパー。"""
    async with semaphore:
        start = time.monotonic()
        try:
            response = await client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            latency_ms = (time.monotonic() - start) * 1000
            metrics.record(RequestResult(endpoint_label, None, latency_ms, str(exc)))
            return None
        latency_ms = (time.monotonic() - start) * 1000
        metrics.record(RequestResult(endpoint_label, response.status_code, latency_ms, None))
        return response


async def run_session(
    base_url: str,
    catalog: list[CatalogEntry],
    args: argparse.Namespace,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    metrics: MetricsCollector,
    rng: random.Random,
) -> SessionResult:
    """1人のお客さんの操作(カート追加→注文確定→ステータス確認)を再現する。

    個別セッションの失敗は例外を外へ伝播させず、SessionResultに記録して返す
    (TaskGroup全体を中断させないため)。
    """
    session_id = str(uuid.uuid4())
    result = SessionResult(session_id=session_id)
    metrics.session_started()
    try:
        item_count = rng.randint(args.items_per_order_min, args.items_per_order_max)
        for _ in range(item_count):
            entry = rng.choice(catalog)
            response = await _request(
                client,
                metrics,
                semaphore,
                "POST /cart/{sessionId}/items",
                "POST",
                f"{base_url}/cart/{session_id}/items",
                json={
                    "productId": entry.product_id,
                    "category": entry.category,
                    "variant": {"temperature": entry.temperature, "size": entry.size},
                    "quantity": rng.randint(1, 2),
                },
            )
            if response is None or response.status_code >= 400:
                status = response.status_code if response is not None else None
                result.failure_reason = f"cart item add failed (status={status})"
                return result
            think_time = rng.uniform(args.think_time_min_seconds, args.think_time_max_seconds)
            await asyncio.sleep(think_time)

        order_response = await _request(
            client,
            metrics,
            semaphore,
            "POST /orders",
            "POST",
            f"{base_url}/orders",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={"sessionId": session_id, "storeId": args.store_id},
        )
        if order_response is None or order_response.status_code != 201:
            status = order_response.status_code if order_response is not None else None
            result.failure_reason = f"order creation failed (status={status})"
            return result

        order_body = order_response.json()
        result.order_id = order_body["orderId"]
        result.order_number = order_body["orderNumber"]
        result.success = True

        await _poll_order_status(base_url, result, args, client, semaphore, metrics)
        return result
    except Exception as exc:
        result.failure_reason = f"unexpected error: {exc!r}"
        return result
    finally:
        metrics.session_finished()


async def _poll_order_status(
    base_url: str,
    result: SessionResult,
    args: argparse.Namespace,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    metrics: MetricsCollector,
) -> None:
    """注文確定後、`pollAfterSeconds`に従ってステータスを確認し続ける(poll_duration_secondsで打ち切り)。"""
    deadline = time.monotonic() + args.poll_duration_seconds
    poll_after_seconds = 5.0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        await asyncio.sleep(min(poll_after_seconds, remaining))
        if time.monotonic() >= deadline:
            return

        status_response = await _request(
            client,
            metrics,
            semaphore,
            "GET /orders/{orderId}",
            "GET",
            f"{base_url}/orders/{result.order_id}",
        )
        result.poll_count += 1
        if status_response is None or status_response.status_code != 200:
            continue
        next_poll = status_response.json().get("pollAfterSeconds")
        if next_poll is None:
            return  # HANDED_OVER/CANCELLEDなど、ポーリング終了を示す
        poll_after_seconds = float(next_poll)


async def _progress_reporter(metrics: MetricsCollector, interval: float = 5.0) -> None:
    """一定間隔で同時接続数・累計リクエスト数を標準出力へ記録する(ランプアップ/プラトー/ドレインの可視化用)。"""
    start = time.monotonic()
    while True:
        await asyncio.sleep(interval)
        elapsed = time.monotonic() - start
        print(
            f"[t={elapsed:5.1f}s] active_sessions={metrics.active_sessions} "
            f"peak={metrics.peak_active_sessions} total_requests={len(metrics.results)}"
        )


async def run_load(
    args: argparse.Namespace, base_url: str, catalog: list[CatalogEntry]
) -> tuple[list[SessionResult], MetricsCollector]:
    """`order_interval`おきにセッションを起動し、全セッションの完了を待つ。"""
    metrics = MetricsCollector()
    semaphore = asyncio.Semaphore(args.max_inflight_requests)
    rng = random.Random(args.seed)
    limits = httpx.Limits(
        max_connections=args.max_inflight_requests,
        max_keepalive_connections=args.max_inflight_requests,
    )
    timeout = httpx.Timeout(args.request_timeout_seconds)

    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        reporter = asyncio.create_task(_progress_reporter(metrics))
        tasks: list[asyncio.Task[SessionResult]] = []
        async with asyncio.TaskGroup() as tg:
            for index in range(args.orders):
                tasks.append(
                    tg.create_task(
                        run_session(base_url, catalog, args, client, semaphore, metrics, rng)
                    )
                )
                if index < args.orders - 1:
                    await asyncio.sleep(args.order_interval)
        reporter.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reporter

    return [task.result() for task in tasks], metrics


def summarize_metrics(results: list[SessionResult], metrics: MetricsCollector) -> str:
    """エンドポイント別のステータス分布とレイテンシ分布を文字列レポートにまとめる。"""
    lines: list[str] = ["== エンドポイント別結果 =="]
    by_endpoint: dict[str, list[RequestResult]] = {}
    for item in metrics.results:
        by_endpoint.setdefault(item.endpoint, []).append(item)

    for endpoint, items in sorted(by_endpoint.items()):
        status_counts = Counter(item.status_code for item in items)
        latencies = sorted(item.latency_ms for item in items if item.status_code is not None)
        lines.append(f"- {endpoint}: {dict(status_counts)}")
        if len(latencies) >= 2:
            quantiles = statistics.quantiles(latencies, n=100, method="inclusive")
            p50, p95, p99 = quantiles[49], quantiles[94], quantiles[98]
            lines.append(
                f"    latency(ms): p50={p50:.1f} p95={p95:.1f} p99={p99:.1f} "
                f"min={min(latencies):.1f} max={max(latencies):.1f} n={len(latencies)}"
            )
        elif latencies:
            lines.append(f"    latency(ms): {latencies[0]:.1f} (n=1)")

    succeeded = [r for r in results if r.success]
    failed = [r for r in results if not r.success]
    lines.append("")
    lines.append("== セッション結果 ==")
    lines.append(f"- 成功: {len(succeeded)}/{len(results)}")
    lines.append(f"- 観測された同時接続ピーク: {metrics.peak_active_sessions}")
    if failed:
        lines.append("- 失敗したセッション:")
        for r in failed:
            lines.append(f"    session_id={r.session_id} reason={r.failure_reason}")

    return "\n".join(lines)


@dataclass
class ConsistencyReport:
    """GSI2のqueueSeq重複チェック結果(docs/architecture.md §6.3の不変条件を検証する)。"""

    duplicates: dict[str, list[int]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.duplicates


def verify_gsi2_consistency(table_name: str, store_id: str) -> ConsistencyReport:
    """各ゾーンのGSI2をQueryし、queueSeqの重複(発生してはならない不変条件)を検出する。

    既存のOrderRepository.list_zone_lines()(店員向けゾーン一覧と同じQueryパターン)を
    そのまま再利用する。
    """
    repository = OrderRepository(table_name)
    report = ConsistencyReport()
    for zone in ZONES:
        lines = repository.list_zone_lines(store_id, zone)
        seq_counts = Counter(line.queue_seq for line in lines)
        duplicated = sorted(seq for seq, count in seq_counts.items() if count > 1)
        if duplicated:
            report.duplicates[zone] = duplicated
    return report


def parse_args() -> argparse.Namespace:
    """CLI引数を解析し、負荷パラメータの整合性(order_intervalの下限等)を検証する。"""
    parser = argparse.ArgumentParser(
        description=(
            "想定ピーク負荷(最大同時接続100人、注文は1秒あたり1件未満)を"
            "実AWS dev環境で再現する(docs/requirements.md参照)"
        )
    )
    parser.add_argument("--stage", choices=["dev"], required=True)
    parser.add_argument("--api-url", default=None, help="省略時はCFN Outputsから自動解決する")
    parser.add_argument("--store-id", default="store-01")
    parser.add_argument("--orders", type=int, default=100)
    parser.add_argument("--order-interval", type=float, default=1.2)
    parser.add_argument("--poll-duration-seconds", type=float, default=None)
    parser.add_argument("--items-per-order-min", type=int, default=1)
    parser.add_argument("--items-per-order-max", type=int, default=3)
    parser.add_argument("--think-time-min-seconds", type=float, default=0.2)
    parser.add_argument("--think-time-max-seconds", type=float, default=1.5)
    parser.add_argument("--max-inflight-requests", type=int, default=50)
    parser.add_argument("--request-timeout-seconds", type=float, default=10.0)
    parser.add_argument("--verification-delay-seconds", type=float, default=5.0)
    parser.add_argument("--skip-consistency-check", action="store_true")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--output-json", type=Path, default=None)
    args = parser.parse_args()

    if args.order_interval <= 1.0:
        parser.error(
            "--order-interval must be > 1.0 seconds to keep the order rate under "
            "the documented peak assumption (< 1 order/sec, docs/requirements.md)"
        )
    if args.poll_duration_seconds is None:
        args.poll_duration_seconds = args.orders * args.order_interval + 30

    return args


def _build_report_dict(
    results: list[SessionResult],
    metrics: MetricsCollector,
    consistency_report: ConsistencyReport | None,
) -> dict[str, Any]:
    """`--output-json`用に、結果をJSONシリアライズ可能な辞書へまとめる。

    `requests`には1リクエストごとの生のレイテンシ値を含める(集計値のp50/p95/p99だけでは
    分布の形〔二峰性など〕が分からないため、実測ヒストグラムを後から作れるようにする)。
    """
    by_endpoint: dict[str, Counter[int | None]] = {}
    for item in metrics.results:
        by_endpoint.setdefault(item.endpoint, Counter())[item.status_code] += 1

    return {
        "sessions": {
            "total": len(results),
            "succeeded": sum(1 for r in results if r.success),
            "peak_active_sessions": metrics.peak_active_sessions,
        },
        "endpoints": {
            endpoint: {str(status): count for status, count in counts.items()}
            for endpoint, counts in by_endpoint.items()
        },
        "requests": [
            {
                "endpoint": item.endpoint,
                "status_code": item.status_code,
                "latency_ms": round(item.latency_ms, 2),
                "error": item.error,
            }
            for item in metrics.results
        ],
        "failures": [
            {"session_id": r.session_id, "reason": r.failure_reason}
            for r in results
            if not r.success
        ],
        "gsi2_consistency": (
            None if consistency_report is None else consistency_report.duplicates
        ),
    }


def main() -> None:
    args = parse_args()
    api_url = args.api_url or resolve_http_api_url(args.stage)
    print(f"target API: {api_url}")
    print(
        f"plan: orders={args.orders} order_interval={args.order_interval}s "
        f"poll_duration_seconds={args.poll_duration_seconds:.1f}s"
    )

    menu_response = httpx.get(f"{api_url}/menu", timeout=args.request_timeout_seconds)
    menu_response.raise_for_status()
    catalog = build_item_catalog(menu_response.json())
    print(f"menu catalog: {len(catalog)} valid (product, variant) combinations")

    started_at = time.monotonic()
    results, metrics = asyncio.run(run_load(args, api_url, catalog))
    elapsed = time.monotonic() - started_at
    print(f"\nload generation finished in {elapsed:.1f}s")
    print(summarize_metrics(results, metrics))

    exit_code = 0
    if any(not r.success for r in results):
        exit_code = 1

    consistency_report: ConsistencyReport | None = None
    if not args.skip_consistency_check:
        print(
            f"\nwaiting {args.verification_delay_seconds}s before the GSI2 consistency check "
            "(GSI reads are eventually consistent)..."
        )
        time.sleep(args.verification_delay_seconds)
        table_name = resolve_table_name(args.stage)
        consistency_report = verify_gsi2_consistency(table_name, args.store_id)
        print("\n== GSI2 queueSeq 重複チェック ==")
        if consistency_report.ok:
            print("OK: 重複は見つかりませんでした")
        else:
            exit_code = 1
            for zone, seqs in consistency_report.duplicates.items():
                print(f"NG: zone={zone} の重複queueSeq: {seqs}")

    if args.output_json is not None:
        report = _build_report_dict(results, metrics, consistency_report)
        args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"\nJSONレポートを書き込みました: {args.output_json}")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
