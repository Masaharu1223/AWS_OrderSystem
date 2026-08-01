"""商品価格の算出・variant検証。AWS非依存。

温度/サイズの許可判定は Product(allow_hot/allow_iced/size_delta)を単一の情報源とし、
ここではその値を参照するだけでルールを複製しない(docs/architecture.md §7.2)。
"""

from __future__ import annotations

from domain.menu.models import Product, Variant


def validate_variant(product: Product, variant: Variant) -> None:
    """商品に対して指定のvariant(温度・サイズ)が選択可能かを検証する。

    不正な場合はValueErrorを送出する(呼び出し側でVALIDATION_ERRORへ変換する)。
    """
    if variant.temperature == "hot" and not product.allow_hot:
        raise ValueError(f"product {product.product_id!r} does not allow hot")
    if variant.temperature == "iced" and not product.allow_iced:
        raise ValueError(f"product {product.product_id!r} does not allow iced")
    if variant.size not in product.size_delta:
        raise ValueError(
            f"product {product.product_id!r} does not offer size {variant.size!r}"
        )


def resolve_unit_price(product: Product, variant: Variant) -> int:
    """商品とvariantから単価(基本価格+サイズ差分)を算出する。

    呼び出し前に validate_variant() でサイズの存在を確認しておくこと
    (未確認のまま呼ぶと size_delta の KeyError になりうる)。
    """
    return product.base_price + product.size_delta[variant.size]
