"""商品(Product)のドメインモデル。AWS非依存。

キー設計(PK=MENU固定, SK=PROD#<productId>)は docs/architecture.md §6.1 を参照。
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic.alias_generators import to_camel

# MENU_CATEGORIES は Category の Literal から導出する(値のドリフトを防ぐため単一の情報源にする)。
Category = Literal["espresso", "tea", "frappe"]
MENU_CATEGORIES: tuple[Category, ...] = get_args(Category)

# キー設計の定数(adapters/menu_repository.py, scripts/seed_menu.py で使い回し、重複を防ぐ)。
MENU_PARTITION_KEY = "MENU"
PRODUCT_SORT_KEY_PREFIX = "PROD#"

Size = Literal["S", "M", "L"]
_ESPRESSO_SIZES: frozenset[Size] = frozenset({"S", "M", "L"})
_NON_ESPRESSO_SIZES: frozenset[Size] = frozenset({"S", "M"})


class Product(BaseModel):
    """docs/architecture.md §7.1 の Product 契約に対応。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    product_id: str
    category: Category
    name: str
    base_price: int
    size_delta: dict[Size, int]
    allow_hot: bool
    allow_iced: bool
    available: bool
    display_order: int | None = None

    @model_validator(mode="after")
    def _validate_size_delta(self) -> Product:
        keys = frozenset(self.size_delta.keys())
        expected = _ESPRESSO_SIZES if self.category == "espresso" else _NON_ESPRESSO_SIZES
        if keys != expected:
            raise ValueError(
                f"category={self.category!r} requires sizeDelta keys "
                f"{sorted(expected)}, got {sorted(keys)}"
            )
        return self


# cart-fn/order-fn が注文時に選択する温度・サイズの組み合わせ(docs/architecture.md §7.2)。
# 許可される組み合わせの判定は Product(allow_hot/allow_iced/size_delta)を単一の情報源とし、
# ここでは別のルールを持たない(domain/menu/pricing.py 参照)。
Temperature = Literal["hot", "iced"]


class Variant(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    temperature: Temperature
    size: Size

    def to_key_segment(self) -> str:
        """DynamoDBのSK/itemIdで使う `<temperature>#<size>` 形式。"""
        return f"{self.temperature}#{self.size}"
