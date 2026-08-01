"""カート(Cart/CartItem)のドメインモデル。AWS非依存。

キー設計(PK=CART#<sessionId>, SK=ITEM#<productId>#<temperature>#<size>)は
docs/architecture.md §6.1 を参照。
"""

from __future__ import annotations

from datetime import timedelta
from typing import cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, computed_field
from pydantic.alias_generators import to_camel

from domain.menu.models import Category, Size, Temperature, Variant

# キー設計の定数(adapters/cart_repository.py で使い回し、重複を防ぐ)。
CART_PARTITION_KEY_PREFIX = "CART#"
ITEM_SORT_KEY_PREFIX = "ITEM#"

# 1明細あたりの数量上限(docs/architecture.md §7.2)。カート全体の合計数量には上限を設けない。
MAX_QUANTITY_PER_ITEM = 10

# カート明細のTTL(docs/architecture.md §6.1)。追加/更新のたびに現在時刻から再計算し延長する。
CART_ITEM_TTL = timedelta(hours=24)


class CartItem(BaseModel):
    """DynamoDBのITEM行に対応する内部表現。`itemId`/`lineTotal`は保存せず導出する。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    product_id: str
    category: Category
    name: str
    variant: Variant
    quantity: int = Field(ge=1, le=MAX_QUANTITY_PER_ITEM)
    unit_price: int
    added_at: str
    updated_at: str
    expires_at: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def item_id(self) -> str:
        return f"{self.product_id}#{self.variant.to_key_segment()}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def line_total(self) -> int:
        return self.quantity * self.unit_price


class Cart(BaseModel):
    """docs/architecture.md §7.2 の Cart 契約に対応。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    session_id: str
    items: list[CartItem]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def subtotal(self) -> int:
        return sum(item.line_total for item in self.items)


class AddItemInput(BaseModel):
    """POST /cart/{sessionId}/items のリクエストボディ。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    product_id: str
    category: Category
    variant: Variant
    quantity: int = Field(ge=1, le=MAX_QUANTITY_PER_ITEM)


class UpdateQuantityInput(BaseModel):
    """PUT /cart/{sessionId}/items/{itemId} のリクエストボディ。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    quantity: int = Field(ge=1, le=MAX_QUANTITY_PER_ITEM)


def parse_item_id(item_id: str) -> tuple[str, Variant]:
    """itemId(`<productId>#<temperature>#<size>`)をproductIdとVariantに分解する。

    CartItem.item_id の逆変換。形式が不正な場合はValueErrorを送出する
    (呼び出し側でVALIDATION_ERRORへ変換する)。
    """
    parts = item_id.split("#")
    if len(parts) != 3:
        raise ValueError(f"malformed itemId: {item_id!r}")
    product_id, temperature, size = parts
    try:
        # 実際の値検証はpydantic(Variant)がランタイムで行う。ここでのcastは
        # 「不正ならValidationErrorで弾かれる」ことを前提にした型上のヒントに過ぎない。
        variant = Variant(
            temperature=cast(Temperature, temperature), size=cast(Size, size)
        )
    except ValidationError as exc:
        raise ValueError(f"malformed itemId: {item_id!r}") from exc
    return product_id, variant
