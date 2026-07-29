"""menu-fn: メニュー一覧・商品詳細のHTTP Lambdaハンドラ(外殻。薄く保つ)。"""

from __future__ import annotations

from typing import Any

from aws_lambda_powertools import Logger
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

from adapters.errors import build_error, not_found
from adapters.http import json_response
from adapters.menu_repository import MenuRepository
from config import get_config
from domain.menu.service import build_menu_response

logger = Logger()

# コールドスタート時に1回だけ生成し、ウォーム実行間で使い回す(boto3リソースの再生成を避ける)。
_repository = MenuRepository(get_config().table_name)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", "")
    route_key = event.get("routeKey", "")

    try:
        if route_key == "GET /menu":
            products = _repository.list_products()
            menu = build_menu_response(products)
            return json_response(200, menu.model_dump(by_alias=True))

        if route_key == "GET /menu/{productId}":
            product_id = (event.get("pathParameters") or {}).get("productId")
            product = _repository.get_product(product_id) if product_id else None
            if product is None:
                status, body = not_found(f"product {product_id} not found", request_id)
                return json_response(status, body)
            return json_response(200, product.model_dump(by_alias=True))

        status, body = not_found("route not found", request_id)
        return json_response(status, body)

    except (ClientError, BotoCoreError, ValidationError):
        # DynamoDBの一時エラーや契約外データによる例外を、共通エラーエンベロープに変換する
        # (docs/architecture.md §5.1)。クライアントには内部詳細を渡さず、詳細はログのみに残す。
        logger.exception("menu-fn: unhandled error", extra={"routeKey": route_key})
        status, body = build_error("INTERNAL", "internal server error", request_id)
        return json_response(status, body)
