"""カートのビジネスロジック。AWS非依存。"""

from __future__ import annotations

from datetime import datetime

from domain.cart.models import CART_ITEM_TTL, MAX_QUANTITY_PER_ITEM, CartItem
from domain.menu.models import Product, Variant
from domain.menu.pricing import resolve_unit_price, validate_variant


def build_item(
    product: Product,
    variant: Variant,
    quantity: int,
    now: datetime,
    existing: CartItem | None = None,
) -> CartItem:
    """商品をカートに追加した結果のCartItemを組み立てる。

    同一productId+variantが既にカートにある場合(existing)は数量を加算する
    (POST /items を同じ明細に対して2回呼んでも上書きではなく合算する。
    一般的な「カートに追加」のUXに合わせるための挙動)。
    variant違反・品切れ・数量上限超過の場合はValueErrorを送出する
    (呼び出し側でVALIDATION_ERRORへ変換する)。
    """
    validate_variant(product, variant)
    if not product.available:
        raise ValueError(f"product {product.product_id!r} is not available")

    total_quantity = quantity + (existing.quantity if existing is not None else 0)
    if total_quantity > MAX_QUANTITY_PER_ITEM:
        raise ValueError(f"quantity exceeds maximum ({MAX_QUANTITY_PER_ITEM})")

    added_at = existing.added_at if existing is not None else format_timestamp(now)

    return CartItem(
        product_id=product.product_id,
        category=product.category,
        name=product.name,
        variant=variant,
        quantity=total_quantity,
        unit_price=resolve_unit_price(product, variant),
        added_at=added_at,
        updated_at=format_timestamp(now),
        expires_at=compute_expires_at(now),
    )


def format_timestamp(now: datetime) -> str:
    """DynamoDBに保存するISO8601形式のタイムスタンプ文字列を組み立てる。"""
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_expires_at(now: datetime) -> int:
    """TTL属性`expiresAt`(UNIX epoch秒)を計算する。追加/更新のたびに呼び出し、期限を延長する。"""
    return int((now + CART_ITEM_TTL).timestamp())
