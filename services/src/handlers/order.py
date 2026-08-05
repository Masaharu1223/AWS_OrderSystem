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
from config import get_config
from domain.cart.models import ITEM_SORT_KEY_PREFIX
from domain.fulfillment.models import Zone
from domain.menu.models import Product
from domain.order.models import MAX_LINES_PER_ORDER, CreateOrderInput
from domain.order.service import build_order, resolve_zone

logger = Logger()

# コールドスタート時に1回だけ生成し、ウォーム実行間で使い回す(boto3リソースの再生成を避ける)。
_order_repository = OrderRepository(get_config().table_name)
_cart_repository = CartRepository(get_config().table_name)
_menu_repository = MenuRepository(get_config().table_name)


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

    except (ClientError, BotoCoreError, ValidationError):
        # DynamoDBの一時エラーや契約外データによる例外を、共通エラーエンベロープに変換する
        # (docs/architecture.md §5.1)。クライアント入力由来のValidationErrorは各ハンドラ内で
        # 個別に捕捉して400へ変換しているため、ここに届くのはDB由来のものだけ。
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

    # ステップ2: ゾーン別カウンタ予約。zoneはcategory+sizeだけで決まるため、商品情報は不要。
    zone_counts: dict[Zone, int] = {}
    for cart_item in cart_items:
        zone = resolve_zone(cart_item.category, cart_item.variant.size)
        zone_counts[zone] = zone_counts.get(zone, 0) + 1

    now = datetime.now(UTC)
    zone_seq_ends = {
        zone: _order_repository.reserve_zone_sequence(input_.store_id, zone, count)
        for zone, count in zone_counts.items()
    }

    # ステップ3: 注文番号予約。
    order_number = _order_repository.reserve_order_number(
        input_.store_id, now.strftime("%Y-%m-%d")
    )
    order_id = str(uuid.uuid4())

    try:
        order = build_order(
            cart_items=cart_items,
            products=products,
            store_id=input_.store_id,
            order_id=order_id,
            order_number=order_number,
            zone_seq_ends=zone_seq_ends,
            now=now,
        )
    except ValueError as exc:
        # ここで失敗すると予約済みのゾーン別カウンタ・注文番号は欠番になるが、実害はなく許容する
        # (architecture.md §6.3の欠番許容の原則)。
        status, body = build_error("VALIDATION_ERROR", str(exc), request_id)
        return json_response(status, body)

    # ステップ4: 全書き込み(TransactWriteItems)。カート明細も同一トランザクションで削除する。
    cart_keys = [f"{ITEM_SORT_KEY_PREFIX}{item.item_id}" for item in cart_items]
    try:
        created = _order_repository.create_order(
            order,
            idempotency_key=idempotency_key,
            session_id=input_.session_id,
            cart_keys=cart_keys,
            now=now,
        )
    except IdempotencyConflict as exc:
        # 事前チェック(ステップ0)をすり抜けた稀なレース。既に他リクエストが確定させた注文を返す。
        return _respond_with_existing_order(
            exc.order_id, exc.session_id, input_.session_id, request_id
        )

    return json_response(201, created.model_dump(by_alias=True))


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
    """
    if existing_session_id != request_session_id:
        status, body = build_error(
            "CONFLICT", "idempotency key already used by a different session", request_id
        )
        return json_response(status, body)

    existing_order = _order_repository.get_order(order_id)
    if existing_order is None:
        # IDEMPOTENCYレコードはあるのに注文本体が無い状態。TransactWriteItemsで両方同時に
        # 書き込んでいるため理論上起こらないはずのデータ不整合であり、隠さずそのまま伝播させる。
        raise RuntimeError(f"idempotency record exists but order {order_id!r} is missing")
    return json_response(201, existing_order.model_dump(by_alias=True))


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
