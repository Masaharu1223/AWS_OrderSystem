"""order-fn: 注文確定・キャンセルのHTTP Lambdaハンドラ(外殻。薄く保つ)。"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from aws_lambda_powertools import Logger
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

from adapters.cart_repository import CartRepository
from adapters.errors import build_error, not_found
from adapters.http import json_response
from adapters.menu_repository import MenuRepository
from adapters.order_repository import (
    IdempotencyConflict,
    OrderNotCancellableError,
    OrderNotFoundError,
    OrderRepository,
)
from adapters.payment.base import PaymentProviderError
from adapters.payment.factory import get_payment_provider
from config import get_config
from domain.menu.models import Product
from domain.menu.pricing import resolve_unit_price, validate_variant
from domain.order.models import MAX_LINES_PER_ORDER, CreateOrderInput, PendingOrderLineSnapshot

logger = Logger()

# コールドスタート時に1回だけ生成し、ウォーム実行間で使い回す(boto3リソースの再生成を避ける)。
_order_repository = OrderRepository(get_config().table_name)
_cart_repository = CartRepository(get_config().table_name)
_menu_repository = MenuRepository(get_config().table_name)
_payment_provider = get_payment_provider()


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", "")
    route_key = event.get("routeKey", "")

    try:
        if route_key == "POST /orders":
            return _handle_create_order(event, request_id)

        if route_key == "PATCH /orders/{orderId}/cancel":
            return _handle_cancel_order(event, request_id)

        status, body = not_found("route not found", request_id)
        return json_response(status, body)

    except (ClientError, BotoCoreError, ValidationError, KeyError):
        # DynamoDBの一時エラーや契約外データによる例外を、共通エラーエンベロープに変換する
        # (docs/architecture.md §5.1)。クライアント入力由来のValidationErrorは各ハンドラ内で
        # 個別に捕捉して400へ変換しているため、ここに届くのはDB由来のものだけ。
        # KeyError: PENDING_PAYMENT段階の注文(orderNumber未採番)にcancel_order()が
        # 呼ばれた場合、get_order()がこのキー欠落で例外化する。PENDING_PAYMENT段階の
        # キャンセル対応は今回のスコープ外のため、クラッシュさせず500で止める安全弁として扱う
        # (将来Issue化して404/409へ整理する)。
        logger.exception("order-fn: unhandled error", extra={"routeKey": route_key})
        status, body = build_error("INTERNAL", "internal server error", request_id)
        return json_response(status, body)


def _handle_create_order(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    idempotency_key = _get_header(event, "Idempotency-Key")
    if not idempotency_key:
        status, body = build_error(
            "VALIDATION_ERROR", "Idempotency-Key header is required", request_id
        )
        return json_response(status, body)

    try:
        input_ = CreateOrderInput.model_validate_json(event.get("body") or "{}")
    except ValidationError as exc:
        status, body = build_error("VALIDATION_ERROR", str(exc), request_id)
        return json_response(status, body)

    # ステップ0: 冪等キーの事前チェック(強整合読み)。ヒットすればカウンタに触れずに終了する
    # (architecture.md §7.3)。
    existing_record = _order_repository.get_idempotency_record(idempotency_key)
    if existing_record is not None:
        return _respond_with_existing_order(
            existing_record.order_id, existing_record.session_id, input_.session_id, request_id
        )

    # ステップ1: 検証・明細生成。上限超過はここでカウンタを1件も消費せずに弾く。
    cart_items = _cart_repository.list_items(input_.session_id)
    if not cart_items:
        status, body = build_error("VALIDATION_ERROR", "cart is empty", request_id)
        return json_response(status, body)
    if len(cart_items) > MAX_LINES_PER_ORDER:
        status, body = build_error(
            "VALIDATION_ERROR", f"too many lines (max {MAX_LINES_PER_ORDER})", request_id
        )
        return json_response(status, body)

    products: dict[str, Product] = {}
    for cart_item in cart_items:
        if cart_item.product_id in products:
            continue
        product = _menu_repository.get_product(cart_item.product_id)
        if product is None:
            status, body = not_found(f"product {cart_item.product_id} not found", request_id)
            return json_response(status, body)
        products[cart_item.product_id] = product

    # ステップ2: variant再検証・価格再計算(決済金額の確定)。ゾーン採番・明細作成は
    # まだ行わない(決済が終わるまで、どのゾーンで何を作るか決めない設計。§12.1)。
    # カート保存時のスナップショットを信用せず、ここでも再計算する(従来build_order()が
    # 担っていた「最後の砦の価格チェック」の前半を、決済前のこの時点に前倒しする)。
    total_price = 0
    for cart_item in cart_items:
        product = products[cart_item.product_id]
        try:
            validate_variant(product, cart_item.variant)
        except ValueError as exc:
            status, body = build_error("VALIDATION_ERROR", str(exc), request_id)
            return json_response(status, body)
        if not product.available:
            status, body = build_error(
                "VALIDATION_ERROR",
                f"product {cart_item.product_id!r} is not available",
                request_id,
            )
            return json_response(status, body)
        total_price += resolve_unit_price(product, cart_item.variant) * cart_item.quantity

    pending_lines = [
        PendingOrderLineSnapshot(
            line_id=f"{index:03d}",
            product_id=cart_item.product_id,
            name=cart_item.name,
            category=cart_item.category,
            variant=cart_item.variant,
            quantity=cart_item.quantity,
        )
        for index, cart_item in enumerate(cart_items, start=1)
    ]

    # ステップ3: 仮注文(PENDING_PAYMENT)を作成する。注文番号・ゾーン別queueSeqは
    # 決済成功後にstatus-fnが初めて確定する(欠番にしない。未決済で終わった注文のために
    # 番号を消費しないため)。
    now = datetime.now(UTC)
    order_id = str(uuid.uuid4())
    try:
        pending = _order_repository.create_pending_payment_order(
            order_id=order_id,
            store_id=input_.store_id,
            session_id=input_.session_id,
            idempotency_key=idempotency_key,
            lines=pending_lines,
            total_price=total_price,
            now=now,
        )
    except IdempotencyConflict as exc:
        # 事前チェック(ステップ0)をすり抜けた稀なレース。既に他リクエストが確定させた注文を返す。
        return _respond_with_existing_order(
            exc.order_id, exc.session_id, input_.session_id, request_id
        )

    # ステップ4: 決済プロバイダにチェックアウトURLを発行してもらう。
    # ここで失敗しても注文はPENDING_PAYMENTのまま残るが、欠番と同じく実害はないと判断している
    # (docs/requirements.md §12.1.1の実装計画で明記済みの既知のトレードオフ)。
    try:
        checkout_url = _payment_provider.create_payment(order_id, total_price)
    except PaymentProviderError:
        logger.exception("order-fn: payment provider error", extra={"orderId": order_id})
        status, body = build_error("INTERNAL", "failed to create payment", request_id)
        return json_response(status, body)
    _order_repository.set_checkout_url(order_id, checkout_url, now)

    response = pending.model_copy(update={"checkout_url": checkout_url})
    return json_response(201, response.model_dump(by_alias=True))


def _handle_cancel_order(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    order_id = (event.get("pathParameters") or {}).get("orderId", "")
    now = datetime.now(UTC)

    try:
        cancelled = _order_repository.cancel_order(order_id, now)
    except OrderNotFoundError:
        status, body = not_found(f"order {order_id} not found", request_id)
        return json_response(status, body)
    except OrderNotCancellableError:
        status, body = build_error(
            "CONFLICT", "order is not cancellable (not all lines WAITING)", request_id
        )
        return json_response(status, body)

    return json_response(200, cancelled.model_dump(by_alias=True))


def _respond_with_existing_order(
    order_id: str, existing_session_id: str, request_session_id: str, request_id: str
) -> dict[str, Any]:
    """冪等キーがヒットした場合の共通処理。

    sessionIdが一致すれば既存注文を201で返す(クライアントからは新規作成と区別が付かなくてよい)。
    不一致なら、他セッションの注文内容が漏洩しないよう409で拒否する(architecture.md §7.3)。
    get_order_or_pending()を使うため、既存注文がPENDING_PAYMENT段階でもOrderが確定済みでも
    同じ経路で正しく返せる。
    """
    if existing_session_id != request_session_id:
        status, body = build_error(
            "CONFLICT", "idempotency key already used by a different session", request_id
        )
        return json_response(status, body)

    existing = _order_repository.get_order_or_pending(order_id)
    if existing is None:
        # IDEMPOTENCYレコードはあるのに注文本体が無い状態。TransactWriteItemsで両方同時に
        # 書き込んでいるため理論上起こらないはずのデータ不整合であり、隠さずそのまま伝播させる。
        raise RuntimeError(f"idempotency record exists but order {order_id!r} is missing")
    return json_response(201, existing.model_dump(by_alias=True))


def _get_header(event: Mapping[str, Any], name: str) -> str | None:
    """大文字小文字を区別せずヘッダを取得する。

    HTTP API(v2)は通常ヘッダ名を小文字化して渡すが、テストや将来の統合方式変更に備えて
    ここで正規化しておく。
    """
    headers = event.get("headers") or {}
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return str(value)
    return None
