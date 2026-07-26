"""menu-fn stub handler.

インフラ（CDK/API Gateway/Lambda配線）の疎通確認専用のスタブ。
契約通りの固定レスポンスを返すのみで、DynamoDB連携やドメインロジックは含まない
（domain/adapters層への分割は本実装スライスで行う）。
"""

import json
from typing import Any

_STUB_PRODUCT = {
    "productId": "prod-001",
    "category": "espresso",
    "name": "カフェラテ",
    "basePrice": 450,
    "sizeDelta": {"S": 0, "M": 50, "L": 100},
    "allowHot": True,
    "allowIced": True,
    "available": True,
}

_STUB_MENU_RESPONSE = {
    "categories": [
        {
            "category": "espresso",
            "products": [_STUB_PRODUCT],
        }
    ]
}


def _json_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    route_key = event.get("routeKey", "")

    if route_key == "GET /menu":
        return _json_response(200, _STUB_MENU_RESPONSE)

    if route_key == "GET /menu/{productId}":
        product_id = (event.get("pathParameters") or {}).get("productId")
        if product_id == _STUB_PRODUCT["productId"]:
            return _json_response(200, _STUB_PRODUCT)
        return _json_response(
            404,
            {
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"product {product_id} not found",
                    "requestId": getattr(context, "aws_request_id", ""),
                }
            },
        )

    return _json_response(404, {"error": {"code": "NOT_FOUND", "message": "route not found", "requestId": ""}})
