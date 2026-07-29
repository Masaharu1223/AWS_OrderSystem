"""DynamoDB MobileOrderTable への商品(Product)アクセス。

キー設計: PK=MENU(固定), SK=PROD#<productId>(docs/architecture.md §6.1)。
"""

from __future__ import annotations

from typing import Any, cast

import boto3
from boto3.dynamodb.conditions import Key

from domain.menu.models import MENU_PARTITION_KEY, PRODUCT_SORT_KEY_PREFIX, Product


class MenuRepository:
    def __init__(self, table_name: str) -> None:
        self._table = boto3.resource("dynamodb").Table(table_name)

    def list_products(self) -> list[Product]:
        items: list[dict[str, Any]] = []
        condition = Key("PK").eq(MENU_PARTITION_KEY) & Key("SK").begins_with(
            PRODUCT_SORT_KEY_PREFIX
        )
        exclusive_start_key: dict[str, Any] | None = None

        while True:
            if exclusive_start_key is None:
                response = self._table.query(KeyConditionExpression=condition)
            else:
                response = self._table.query(
                    KeyConditionExpression=condition,
                    ExclusiveStartKey=exclusive_start_key,
                )
            items.extend(response.get("Items", []))
            exclusive_start_key = response.get("LastEvaluatedKey")
            if exclusive_start_key is None:
                break

        return [Product(**item) for item in items]

    def get_product(self, product_id: str) -> Product | None:
        sort_key = f"{PRODUCT_SORT_KEY_PREFIX}{product_id}"
        response = self._table.get_item(Key={"PK": MENU_PARTITION_KEY, "SK": sort_key})
        item = response.get("Item")
        return Product(**cast(dict[str, Any], item)) if item else None
