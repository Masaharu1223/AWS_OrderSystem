"""status-fn: 注文状態ポーリングのHTTP Lambdaハンドラ(外殻。薄く保つ)。"""

from __future__ import annotations

from typing import Any

from aws_lambda_powertools import Logger
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

from adapters.errors import build_error, not_found
from adapters.http import json_response
from adapters.order_repository import OrderRepository
from config import get_config
from domain.fulfillment.models import Zone
from domain.order.models import Order
from domain.status.service import build_order_status, build_queue_position

logger = Logger()

# コールドスタート時に1回だけ生成し、ウォーム実行間で使い回す(boto3リソースの再生成を避ける)。
_order_repository = OrderRepository(get_config().table_name)

# position算出の対象となる明細ステータス(WAITING/PREPARING)。docs/architecture.md §7.4。
_ACTIVE_LINE_STATUSES = frozenset({"WAITING", "PREPARING"})


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", "")
    route_key = event.get("routeKey", "")

    try:
        if route_key == "GET /orders/{orderId}":
            return _handle_get_order_status(event, request_id)

        if route_key == "GET /orders/{orderId}/queue-position":
            return _handle_get_queue_position(event, request_id)

        status, body = not_found("route not found", request_id)
        return json_response(status, body)

    except (ClientError, BotoCoreError, ValidationError):
        # DynamoDBの一時エラーや契約外データによる例外を、共通エラーエンベロープに変換する
        # (docs/architecture.md §5.1)。
        logger.exception("status-fn: unhandled error", extra={"routeKey": route_key})
        status, body = build_error("INTERNAL", "internal server error", request_id)
        return json_response(status, body)


def _handle_get_order_status(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    order = _load_order(event, request_id)
    if isinstance(order, dict):
        return order

    positions, zone_avg_seconds = _compute_positions_and_zone_averages(order)
    response = build_order_status(order, positions, zone_avg_seconds)
    return json_response(200, response.model_dump(by_alias=True))


def _handle_get_queue_position(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    order = _load_order(event, request_id)
    if isinstance(order, dict):
        return order

    positions, zone_avg_seconds = _compute_positions_and_zone_averages(order)
    response = build_queue_position(order, positions, zone_avg_seconds)
    return json_response(200, response.model_dump(by_alias=True))


def _load_order(event: dict[str, Any], request_id: str) -> Order | dict[str, Any]:
    """orderIdから注文を取得する。存在しなければ404レスポンス(dict)をそのまま返す。

    戻り値がOrderかdict(HTTPレスポンス)かで呼び出し側が処理を分岐する
    (cart-fn/order-fnと同じ「見つからなければ即返す」パターンをGET系2ルートで共有するための形)。
    """
    order_id = (event.get("pathParameters") or {}).get("orderId", "")
    order = _order_repository.get_order(order_id)
    if order is None:
        status, body = not_found(f"order {order_id} not found", request_id)
        return json_response(status, body)
    return order


def _compute_positions_and_zone_averages(
    order: Order,
) -> tuple[dict[str, int | None], dict[Zone, float]]:
    """明細ごとのキュー位置と、ゾーン別の平均製造時間(秒)を集める。

    全明細が非アクティブ(READY/HANDED_OVER/CANCELLED)ならGSI2へのCOUNTクエリを丸ごとスキップする
    (architecture.md §7.4の最適化。受取待ちフェーズの読み取りコストをゼロにする)。
    """
    positions: dict[str, int | None] = {line.line_id: None for line in order.lines}
    active_lines = [line for line in order.lines if line.status in _ACTIVE_LINE_STATUSES]
    if not active_lines:
        return positions, {}

    zone_avg_seconds: dict[Zone, float] = {}
    for line in active_lines:
        ahead = _order_repository.count_ahead_in_zone(order.store_id, line.zone, line.queue_seq)
        positions[line.line_id] = ahead + 1  # AP-Z2: position = count + 1

        if line.zone not in zone_avg_seconds:
            stat = _order_repository.get_zone_stat(order.store_id, line.zone)
            if stat is not None:
                sum_seconds, sample_count = stat
                if sample_count > 0:
                    zone_avg_seconds[line.zone] = sum_seconds / sample_count

    return positions, zone_avg_seconds
