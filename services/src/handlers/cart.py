"""cart-fn: カートCRUDのHTTP Lambdaハンドラ(外殻。薄く保つ)。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from aws_lambda_powertools import Logger
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

from adapters.cart_repository import CartRepository
from adapters.errors import build_error, not_found
from adapters.http import empty_response, json_response
from adapters.menu_repository import MenuRepository
from config import get_config
from domain.cart.models import AddItemInput, Cart, UpdateQuantityInput, parse_item_id
from domain.cart.service import build_item, compute_expires_at, format_timestamp

logger = Logger()

# コールドスタート時に1回だけ生成し、ウォーム実行間で使い回す(boto3リソースの再生成を避ける)。
_cart_repository = CartRepository(get_config().table_name)
_menu_repository = MenuRepository(get_config().table_name)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", "")
    route_key = event.get("routeKey", "")

    try:
        if route_key == "GET /cart/{sessionId}":
            return _handle_get_cart(event)

        if route_key == "POST /cart/{sessionId}/items":
            return _handle_add_item(event, request_id)

        if route_key == "PUT /cart/{sessionId}/items/{itemId}":
            return _handle_update_quantity(event, request_id)

        if route_key == "DELETE /cart/{sessionId}/items/{itemId}":
            return _handle_delete_item(event, request_id)

        status, body = not_found("route not found", request_id)
        return json_response(status, body)

    except (ClientError, BotoCoreError, ValidationError):
        # DynamoDBの一時エラーや契約外データによる例外を、共通エラーエンベロープに変換する
        # (docs/architecture.md §5.1)。クライアント入力由来のValidationErrorは各ハンドラ内で
        # 個別に捕捉して400へ変換しているため、ここに届くのはDB由来のものだけ。
        logger.exception("cart-fn: unhandled error", extra={"routeKey": route_key})
        status, body = build_error("INTERNAL", "internal server error", request_id)
        return json_response(status, body)


def _handle_get_cart(event: dict[str, Any]) -> dict[str, Any]:
    session_id = (event.get("pathParameters") or {}).get("sessionId", "")
    items = _cart_repository.list_items(session_id)
    cart = Cart(session_id=session_id, items=items)
    return json_response(200, cart.model_dump(by_alias=True))


def _handle_add_item(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    session_id = (event.get("pathParameters") or {}).get("sessionId", "")

    try:
        input_ = AddItemInput.model_validate_json(event.get("body") or "{}")
    except ValidationError as exc:
        status, body = build_error("VALIDATION_ERROR", str(exc), request_id)
        return json_response(status, body)

    product = _menu_repository.get_product(input_.product_id)
    if product is None:
        status, body = not_found(f"product {input_.product_id} not found", request_id)
        return json_response(status, body)

    existing = _cart_repository.get_item(session_id, input_.product_id, input_.variant)
    now = datetime.now(UTC)
    try:
        item = build_item(product, input_.variant, input_.quantity, now, existing)
    except ValueError as exc:
        status, body = build_error("VALIDATION_ERROR", str(exc), request_id)
        return json_response(status, body)

    _cart_repository.put_item(session_id, item)
    cart = Cart(session_id=session_id, items=_cart_repository.list_items(session_id))
    return json_response(201, cart.model_dump(by_alias=True))


def _handle_update_quantity(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    path_params = event.get("pathParameters") or {}
    session_id = path_params.get("sessionId", "")
    item_id = path_params.get("itemId", "")

    try:
        input_ = UpdateQuantityInput.model_validate_json(event.get("body") or "{}")
    except ValidationError as exc:
        status, body = build_error("VALIDATION_ERROR", str(exc), request_id)
        return json_response(status, body)

    try:
        product_id, variant = parse_item_id(item_id)
    except ValueError as exc:
        status, body = build_error("VALIDATION_ERROR", str(exc), request_id)
        return json_response(status, body)

    now = datetime.now(UTC)
    updated = _cart_repository.update_quantity(
        session_id,
        product_id,
        variant,
        input_.quantity,
        format_timestamp(now),
        compute_expires_at(now),
    )
    if updated is None:
        status, body = not_found(f"item {item_id} not found", request_id)
        return json_response(status, body)

    cart = Cart(session_id=session_id, items=_cart_repository.list_items(session_id))
    return json_response(200, cart.model_dump(by_alias=True))


def _handle_delete_item(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    path_params = event.get("pathParameters") or {}
    session_id = path_params.get("sessionId", "")
    item_id = path_params.get("itemId", "")

    try:
        product_id, variant = parse_item_id(item_id)
    except ValueError as exc:
        status, body = build_error("VALIDATION_ERROR", str(exc), request_id)
        return json_response(status, body)

    deleted = _cart_repository.delete_item(session_id, product_id, variant)
    if deleted is None:
        status, body = not_found(f"item {item_id} not found", request_id)
        return json_response(status, body)

    return empty_response(204)
