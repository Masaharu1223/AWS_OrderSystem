"""status-fn: 注文状態ポーリングのHTTP Lambdaハンドラ(外殻。薄く保つ)。

PayPay公式のWeb Cashier統合フローにはWebhook通知を受信するステップが無く、
クライアントのリダイレクト+既存のポーリング確認が推奨方式であるため
(docs/requirements.md §12.1、2026-10-18確認)、決済確認・確定の両方をここで担う。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from aws_lambda_powertools import Logger
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

from adapters.errors import build_error, not_found
from adapters.http import json_response
from adapters.menu_repository import MenuRepository
from adapters.order_repository import OrderRepository, PaymentAlreadyFinalizedError
from adapters.payment.base import PaymentProviderError
from adapters.payment.factory import get_payment_provider
from config import get_config
from domain.fulfillment.models import Zone
from domain.order.models import Order, PendingPaymentOrder
from domain.order.service import build_order, resolve_zone
from domain.status.service import (
    build_order_status,
    build_pending_order_status,
    build_queue_position,
)

logger = Logger()

# コールドスタート時に1回だけ生成し、ウォーム実行間で使い回す(boto3リソースの再生成を避ける)。
_order_repository = OrderRepository(get_config().table_name)
_menu_repository = MenuRepository(get_config().table_name)
_payment_provider = get_payment_provider()

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
    if isinstance(order, PendingPaymentOrder):
        order = _check_and_finalize_if_pending(order)
    if isinstance(order, PendingPaymentOrder):
        # 決済確定前(PENDING_PAYMENT/PAYMENT_FAILED)は明細が無いため、別の軽量な
        # レスポンス形で返す(domain/status/models.py、docs/requirements.md §12.1.1)。
        pending_response = build_pending_order_status(order)
        return json_response(200, pending_response.model_dump(by_alias=True))

    positions, zone_avg_seconds = _compute_positions_and_zone_averages(order)
    response = build_order_status(order, positions, zone_avg_seconds)
    return json_response(200, response.model_dump(by_alias=True))


def _handle_get_queue_position(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    order = _load_order(event, request_id)
    if isinstance(order, dict):
        return order
    if isinstance(order, PendingPaymentOrder):
        # 決済確定前はキュー位置という概念自体が存在しない。架空の値を作らず409で明示する。
        # (ここでは決済確認は行わない。確認は GET /orders/{orderId} 側の責務とする)
        status, body = build_error(
            "CONFLICT", "order is not yet accepted (payment pending)", request_id
        )
        return json_response(status, body)

    positions, zone_avg_seconds = _compute_positions_and_zone_averages(order)
    response = build_queue_position(order, positions, zone_avg_seconds)
    return json_response(200, response.model_dump(by_alias=True))


def _load_order(
    event: dict[str, Any], request_id: str
) -> Order | PendingPaymentOrder | dict[str, Any]:
    """orderIdから注文を取得する。存在しなければ404レスポンス(dict)をそのまま返す。

    決済確定前はPendingPaymentOrder、確定後はOrderを返す(get_order_or_pending()、
    adapters/order_repository.py参照)。戻り値の型で呼び出し側が処理を分岐する
    (cart-fn/order-fnと同じ「見つからなければ即返す」パターンをGET系2ルートで共有するための形)。
    """
    order_id = (event.get("pathParameters") or {}).get("orderId", "")
    order = _order_repository.get_order_or_pending(order_id)
    if order is None:
        status, body = not_found(f"order {order_id} not found", request_id)
        return json_response(status, body)
    return order


def _check_and_finalize_if_pending(
    pending: PendingPaymentOrder,
) -> Order | PendingPaymentOrder:
    """PENDING_PAYMENTの注文について、決済プロバイダへ確認し確定/失敗を反映する。

    PayPay公式のWeb Cashier統合フローに合わせ、Webhookではなくこのポーリング応答の
    たびに確認しに行く(docs/requirements.md §12.1)。プロバイダへの問い合わせ自体が
    失敗した場合(PaymentProviderError)は、ログのみ残しpendingのまま返す
    (次回のポーリングで自然に再試行される。ユーザー体験を壊さない)。
    """
    if pending.status != "PENDING_PAYMENT":
        return pending  # PAYMENT_FAILEDは確認済み、そのまま返す

    try:
        outcome = _payment_provider.get_payment_status(pending.order_id)
    except PaymentProviderError:
        logger.warning(
            "status-fn: payment provider check failed, will retry on next poll",
            extra={"orderId": pending.order_id},
        )
        return pending

    if outcome is None:
        return pending  # まだ未確定

    now = datetime.now(UTC)
    if outcome == "succeeded":
        order = _finalize(pending, now)
        return order if order is not None else pending

    try:
        _order_repository.mark_payment_failed(pending, now)
    except PaymentAlreadyFinalizedError:
        pass  # 同時に届いた別のポーリングリクエストが先に処理した(稀なケース)。

    refreshed = _order_repository.get_order_or_pending(pending.order_id)
    if isinstance(refreshed, PendingPaymentOrder):
        return refreshed
    return pending  # 万一取得できなかった場合のフォールバック


def _finalize(pending: PendingPaymentOrder, now: datetime) -> Order | None:
    """決済成功時、PENDING_PAYMENT注文を確定する(ゾーン採番・明細作成・DynamoDB書込)。

    order-fnが元々1リクエストで行っていたステップ2〜4(architecture.md §7.3)を、
    決済成功が確認できたこのタイミングで実行する。確定できなかった場合はNoneを返し、
    呼び出し側はpendingのまま(次回ポーリングで再試行)扱う。
    """
    pending_lines = _order_repository.get_pending_lines(pending.order_id)
    if not pending_lines:
        # 理論上起こらないはず(PENDING_PAYMENT作成とPENDINGLINE書込は同一トランザクション)
        # だが、万一のデータ不整合で明細が無い場合は確定せずログだけ残す。
        logger.error(
            "status-fn: no pending lines found for paid order", extra={"orderId": pending.order_id}
        )
        return None

    products = {}
    for line in pending_lines:
        if line.product_id in products:
            continue
        product = _menu_repository.get_product(line.product_id)
        if product is None:
            # 決済は既に成立しているため、お金は動いている。要運用対応(手動返金)。
            logger.error(
                "status-fn: product disappeared after payment succeeded",
                extra={"orderId": pending.order_id, "productId": line.product_id},
            )
            return None
        products[line.product_id] = product

    zone_counts: dict[Zone, int] = {}
    for line in pending_lines:
        zone = resolve_zone(line.category, line.variant.size)
        zone_counts[zone] = zone_counts.get(zone, 0) + 1
    zone_seq_ends = {
        zone: _order_repository.reserve_zone_sequence(pending.store_id, zone, count)
        for zone, count in zone_counts.items()
    }
    order_number = _order_repository.reserve_order_number(
        pending.store_id, now.strftime("%Y-%m-%d")
    )

    try:
        order = build_order(
            cart_items=pending_lines,
            products=products,
            store_id=pending.store_id,
            order_id=pending.order_id,
            order_number=order_number,
            zone_seq_ends=zone_seq_ends,
            now=now,
        )
    except ValueError:
        # 決済は既に成立しているため、お金は動いている。要運用対応(手動返金)。
        # 予約済みのゾーン別カウンタ・注文番号は欠番になるが実害はない(architecture.md §6.3)。
        logger.exception(
            "status-fn: build_order failed after payment succeeded",
            extra={"orderId": pending.order_id},
        )
        return None

    try:
        _order_repository.finalize_paid_order(pending, order, now)
    except PaymentAlreadyFinalizedError:
        pass  # 同時に届いた別のポーリングリクエストが先に確定させた(稀なケース)。

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
