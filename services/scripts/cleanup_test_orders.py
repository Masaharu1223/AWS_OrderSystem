"""dev環境に残ったテスト注文を「キャンセル済み」にして、店員画面のキューから外す(手動の保守ツール)。

なぜ必要か:
    負荷テスト(load_test_peak.py)や手動の動作確認で作った注文は、誰も調理を進めないため
    「待ち(WAITING)」のまま店員画面のゾーンキューに残り続ける。2026-11-10時点で store-01 に
    227件たまっていた(tasks/todo.md §37)。

何をするか:
    指定した店舗のゾーンキュー(GSI2)にいる明細のうち、指定日より前に作られたものを探し、
    アプリ本来のキャンセル処理(OrderRepository.cancel_order)と同じ項目を書き換える。
      - 明細(LINE): status=CANCELLED、updatedAt を更新、GSI2キーを削除(=キューから外れる)
      - 注文ヘッダ(META): その注文の明細が全部CANCELLEDになったときだけ、
        derivedStatus=CANCELLED・GSI1PK=STORE#<店舗>#CANCELLED に更新する
    データは削除しない(後から何があったか追えるようにするため)。

本来のキャンセルとの違い:
    お客様のキャンセルは「全明細が待ち」のときだけ許されるが、このツールは調理中(PREPARING)の
    明細もキャンセル済みにする。テストデータの片付け専用なので、本番(prod)では実行できない。

安全策:
    - 何も指定しなければ dry-run(対象の件数を表示するだけで、何も書き換えない)
    - `--execute` を付けたときだけ書き換える
    - 書き換えは「まだ待ち/調理中のままなら」という条件付き。実行中に誰かが状態を進めた明細は
      上書きせずにスキップする

使い方(servicesディレクトリから実行、事前に `pip install -e ".[dev,load-test]"`):
    # まずdry-run(対象の件数を表示するだけ)
    python scripts/cleanup_test_orders.py --stage dev \
        --store-id store-01 --created-before 2026-11-10
    # 件数を確認してから、同じ引数に --execute を付けて実行する

pytest・scripts/verify.sh には含めない(実AWSへ書き込む手動ツールのため)。
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

# services/src をimportパスに追加する(このスクリプトはpytestのpythonpath設定の対象外のため)。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from load_test_peak import ZONES, resolve_table_name  # noqa: E402

from adapters.order_repository import OrderRepository  # noqa: E402
from domain.order.models import (  # noqa: E402
    ORDER_LINE_SORT_KEY_PREFIX,
    ORDER_META_SORT_KEY,
    ORDER_PARTITION_KEY_PREFIX,
    OrderLine,
)


def find_stale_lines(
    repository: OrderRepository, store_id: str, created_before: str
) -> list[OrderLine]:
    """店舗の全ゾーンのキューから、`created_before`(YYYY-MM-DD、UTC)より前に作られた明細を集める。

    createdAtは"2026-10-02T12:34:56Z"形式の文字列なので、日付文字列との文字列比較で
    「その日の0時(UTC)より前か」を判定できる("2026-11-10T..." は "2026-11-10" より大きい)。
    キュー(GSI2)には待ち/調理中の明細しか入っていないため、状態での絞り込みは不要。
    """
    stale: list[OrderLine] = []
    for zone in ZONES:
        for line in repository.list_zone_lines(store_id, zone):
            if line.created_at < created_before:
                stale.append(line)
    return stale


def cancel_line(table: Any, line: OrderLine, timestamp: str) -> bool:
    """明細1件をキャンセル済みにしてキューから外す。状態が変わっていてスキップした場合はFalse。"""
    try:
        table.update_item(
            Key={
                "PK": f"{ORDER_PARTITION_KEY_PREFIX}{line.order_id}",
                "SK": f"{ORDER_LINE_SORT_KEY_PREFIX}{line.line_id}",
            },
            UpdateExpression="SET #status = :cancelled, updatedAt = :now REMOVE GSI2PK, GSI2SK",
            ConditionExpression="#status IN (:waiting, :preparing)",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":cancelled": "CANCELLED",
                ":waiting": "WAITING",
                ":preparing": "PREPARING",
                ":now": timestamp,
            },
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise
    return True


def cancel_meta_if_all_lines_cancelled(
    table: Any, order_id: str, store_id: str, timestamp: str
) -> bool:
    """注文の明細が全部CANCELLEDなら、注文ヘッダ(META)もキャンセル済みにする。更新したらTrue。

    明細の状態は強整合読みで確かめる(直前の書き換えを確実に反映した状態で判定するため)。
    """
    response = table.query(
        KeyConditionExpression=Key("PK").eq(f"{ORDER_PARTITION_KEY_PREFIX}{order_id}")
        & Key("SK").begins_with(ORDER_LINE_SORT_KEY_PREFIX),
        ConsistentRead=True,
    )
    statuses = [item["status"] for item in response.get("Items", [])]
    if not statuses or any(status != "CANCELLED" for status in statuses):
        return False
    table.update_item(
        Key={"PK": f"{ORDER_PARTITION_KEY_PREFIX}{order_id}", "SK": ORDER_META_SORT_KEY},
        UpdateExpression="SET derivedStatus = :cancelled, updatedAt = :now, GSI1PK = :gsi1pk",
        ExpressionAttributeValues={
            ":cancelled": "CANCELLED",
            ":now": timestamp,
            ":gsi1pk": f"STORE#{store_id}#CANCELLED",
        },
    )
    return True


def print_summary(lines: list[OrderLine]) -> None:
    """対象の明細を、作成日・状態・ゾーン別の件数で表示する(dry-runで中身を確かめるため)。"""
    order_count = len({line.order_id for line in lines})
    print(f"対象: 明細 {len(lines)} 件 / 注文 {order_count} 件")
    by_day = Counter(line.created_at[:10] for line in lines)
    print("  作成日別: " + ", ".join(f"{day}={n}" for day, n in sorted(by_day.items())))
    by_status = Counter(line.status for line in lines)
    print("  状態別:   " + ", ".join(f"{status}={n}" for status, n in sorted(by_status.items())))
    by_zone = Counter(line.zone for line in lines)
    print("  ゾーン別: " + ", ".join(f"{zone}={n}" for zone, n in sorted(by_zone.items())))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # 本番データを誤って書き換えないよう、devだけを受け付ける。
    parser.add_argument("--stage", choices=["dev"], required=True)
    parser.add_argument("--store-id", required=True)
    parser.add_argument(
        "--created-before",
        required=True,
        help="この日付(YYYY-MM-DD、UTC)の0時より前に作られた明細を対象にする",
    )
    parser.add_argument(
        "--execute", action="store_true", help="指定したときだけ実際に書き換える(既定はdry-run)"
    )
    args = parser.parse_args()
    date.fromisoformat(args.created_before)  # 形式が不正ならここでエラーにする
    return args


def main() -> None:
    args = parse_args()
    table_name = resolve_table_name(args.stage)
    repository = OrderRepository(table_name)
    table = boto3.resource("dynamodb").Table(table_name)

    lines = find_stale_lines(repository, args.store_id, args.created_before)
    print(f"テーブル: {table_name} / 店舗: {args.store_id} / {args.created_before} より前")
    print_summary(lines)

    if not args.execute:
        print("\ndry-run のため何も書き換えていません。実行するには --execute を付けてください。")
        return

    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines_by_order: dict[str, list[OrderLine]] = defaultdict(list)
    for line in lines:
        lines_by_order[line.order_id].append(line)

    cancelled_lines = skipped_lines = cancelled_orders = 0
    for order_id, order_lines in lines_by_order.items():
        for line in order_lines:
            if cancel_line(table, line, timestamp):
                cancelled_lines += 1
            else:
                skipped_lines += 1
        if cancel_meta_if_all_lines_cancelled(table, order_id, args.store_id, timestamp):
            cancelled_orders += 1

    print(
        f"\n完了: 明細 {cancelled_lines} 件をキャンセル済みにしました"
        f"(スキップ {skipped_lines} 件)。注文ヘッダ {cancelled_orders} 件を更新しました。"
    )


if __name__ == "__main__":
    main()
