"""payment-fn: 決済プロバイダからのWebhook通知を受けるHTTP Lambdaハンドラ(外殻。薄く保つ)。

決済確定前(order-fn)が担っていたゾーン採番・明細作成は、決済成功が確認できた
ここで初めて行う(docs/requirements.md §12.1・§12.1.1)。
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
from adapters.payment.base import PaymentNotificationError, PaymentSignatureError
from adapters.payment.factory import get_payment_provider
from config import get_config
from domain.fulfillment.models import Zone
from domain.order.models import PendingPaymentOrder
from domain.order.service import build_order, resolve_zone

logger = Logger()

# コールドスタート時に1回だけ生成し、ウォーム実行間で使い回す(boto3リソースの再生成を避ける)。
_order_repository = OrderRepository(get_config().table_name)
_menu_repository = MenuRepository(get_config().table_name)
_payment_provider = get_payment_provider()


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", "")
    route_key = event.get("routeKey", "")

    try:
        if route_key == "POST /payments/webhook":
            return _handle_webhook(event, request_id)

        status, body = not_found("route not found", request_id)
        return json_response(status, body)

    except (ClientError, BotoCoreError, ValidationError):
        # DynamoDBの一時エラーや契約外データによる例外を、共通エラーエンベロープに変換する
        # (docs/architecture.md §5.1)。
        logger.exception("payment-fn: unhandled error", extra={"routeKey": route_key})
        status, body = build_error("INTERNAL", "internal server error", request_id)
        return json_response(status, body)


def _handle_webhook(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    """決済プロバイダからのWebhook通知を処理する。

    レスポンスは常に200(受信確認)にする(署名検証失敗の401を除く)。決済プロバイダは
    非2xxレスポンスを再送のトリガーにするため、こちらの都合(注文が既に無い・既に確定済み・
    未知のイベント種別)による「処理しない」判断は、再送ループを避けるためすべて200で
    受け止める(docs/requirements.md §12.1.1)。
    """
    raw_body = event.get("body") or ""
    headers: dict[str, str] = event.get("headers") or {}

    try:
        result = _payment_provider.verify_and_parse_notification(raw_body, headers)
    except PaymentSignatureError:
        logger.warning("payment-fn: signature verification failed")
        status, body = build_error("UNAUTHORIZED", "invalid webhook signature", request_id)
        return json_response(status, body)
    except PaymentNotificationError:
        logger.warning("payment-fn: unrecognized notification, ignoring")
        return json_response(200, {"received": True})

    now = datetime.now(UTC)
    pending = _order_repository.get_order_or_pending(result.order_id)
    if not isinstance(pending, PendingPaymentOrder):
        # 注文が存在しない、または既に確定済み(STORE_ACCEPTED以降)。二重Webhookとして
        # 何もせず受信確認だけ返す。
        logger.info(
            "payment-fn: order not pending, ignoring notification",
            extra={"orderId": result.order_id},
        )
        return json_response(200, {"received": True})

    if result.outcome == "succeeded":
        _finalize(pending, now)
    else:
        try:
            _order_repository.mark_payment_failed(pending, now)
        except PaymentAlreadyFinalizedError:
            pass  # 同じ失敗通知の再送、または成功通知と競合した稀なケース。

    return json_response(200, {"received": True})


def _finalize(pending: PendingPaymentOrder, now: datetime) -> None:
    """決済成功時、PENDING_PAYMENT注文を確定する(ゾーン採番・明細作成・DynamoDB書込)。

    order-fnが元々1リクエストで行っていたステップ2〜4(architecture.md §7.3)を、
    決済成功が確認できたこのタイミングで実行する。
    """
    pending_lines = _order_repository.get_pending_lines(pending.order_id)
    if not pending_lines:
        # 理論上起こらないはず(PENDING_PAYMENT作成とPENDINGLINE書込は同一トランザクション)
        # だが、万一のデータ不整合で明細が無い場合は確定せずログだけ残す。
        logger.error(
            "payment-fn: no pending lines found for paid order", extra={"orderId": pending.order_id}
        )
        return

    products = {}
    for line in pending_lines:
        if line.product_id in products:
            continue
        product = _menu_repository.get_product(line.product_id)
        if product is None:
            # 決済は既に成立しているため、お金は動いている。要運用対応(手動返金)。
            logger.error(
                "payment-fn: product disappeared after payment succeeded",
                extra={"orderId": pending.order_id, "productId": line.product_id},
            )
            return
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
            "payment-fn: build_order failed after payment succeeded",
            extra={"orderId": pending.order_id},
        )
        return

    try:
        _order_repository.finalize_paid_order(pending, order, now)
    except PaymentAlreadyFinalizedError:
        pass  # 同じ成功通知の再送(二重Webhook)、または失敗通知と競合した稀なケース。
