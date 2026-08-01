"""DynamoDB MobileOrderTable へのカート(Cart/CartItem)アクセス。

キー設計: PK=CART#<sessionId>, SK=ITEM#<productId>#<temperature>#<size>
(docs/architecture.md §6.1)。
"""

from __future__ import annotations

from typing import Any, cast

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from domain.cart.models import CART_PARTITION_KEY_PREFIX, ITEM_SORT_KEY_PREFIX, CartItem
from domain.menu.models import Variant


class CartRepository:
    def __init__(self, table_name: str) -> None:
        self._table = boto3.resource("dynamodb").Table(table_name)

    def list_items(self, session_id: str) -> list[CartItem]:
        items: list[dict[str, Any]] = []
        condition = Key("PK").eq(_partition_key(session_id)) & Key("SK").begins_with(
            ITEM_SORT_KEY_PREFIX
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

        return [CartItem(**item) for item in items]

    def get_item(self, session_id: str, product_id: str, variant: Variant) -> CartItem | None:
        response = self._table.get_item(
            Key={"PK": _partition_key(session_id), "SK": _sort_key(product_id, variant)}
        )
        item = response.get("Item")
        return CartItem(**cast(dict[str, Any], item)) if item else None

    def put_item(self, session_id: str, item: CartItem) -> None:
        """新規追加、または同一productId+variantの明細を丸ごと置き換える。

        呼び出し側(domain.cart.service.build_item)が数量の合算・価格の再計算を
        済ませた完成形のCartItemを渡す想定。itemId/lineTotalは導出値のため保存しない。
        """
        dynamo_item = {
            "PK": _partition_key(session_id),
            "SK": _sort_key(item.product_id, item.variant),
            **item.model_dump(by_alias=True, exclude={"item_id", "line_total"}),
        }
        self._table.put_item(Item=dynamo_item)

    def update_quantity(
        self,
        session_id: str,
        product_id: str,
        variant: Variant,
        quantity: int,
        updated_at: str,
        expires_at: int,
    ) -> CartItem | None:
        """既存明細の数量とTTLを更新する。明細が存在しない場合はNoneを返す(404相当)。

        ConditionExpressionで存在確認する理由: UpdateItemは対象キーが無いと
        デフォルトで新規作成してしまう(productId等が欠けた壊れたアイテムになる)。
        """
        try:
            response = self._table.update_item(
                Key={"PK": _partition_key(session_id), "SK": _sort_key(product_id, variant)},
                UpdateExpression=(
                    "SET quantity = :quantity, updatedAt = :updatedAt, expiresAt = :expiresAt"
                ),
                ConditionExpression="attribute_exists(PK)",
                ExpressionAttributeValues={
                    ":quantity": quantity,
                    ":updatedAt": updated_at,
                    ":expiresAt": expires_at,
                },
                ReturnValues="ALL_NEW",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None
            raise
        return CartItem(**cast(dict[str, Any], response["Attributes"]))

    def delete_item(self, session_id: str, product_id: str, variant: Variant) -> CartItem | None:
        """明細を削除する。削除できた場合はその明細を、存在しなかった場合はNoneを返す。"""
        response = self._table.delete_item(
            Key={"PK": _partition_key(session_id), "SK": _sort_key(product_id, variant)},
            ReturnValues="ALL_OLD",
        )
        item = response.get("Attributes")
        return CartItem(**cast(dict[str, Any], item)) if item else None


def _partition_key(session_id: str) -> str:
    return f"{CART_PARTITION_KEY_PREFIX}{session_id}"


def _sort_key(product_id: str, variant: Variant) -> str:
    return f"{ITEM_SORT_KEY_PREFIX}{product_id}#{variant.to_key_segment()}"
