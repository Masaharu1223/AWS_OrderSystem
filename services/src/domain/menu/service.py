"""GET /menu のレスポンス整形ロジック。AWS非依存。"""

from __future__ import annotations

from pydantic import BaseModel

from domain.menu.models import MENU_CATEGORIES, Product


class MenuCategory(BaseModel):
    category: str
    products: list[Product]


class MenuResponse(BaseModel):
    categories: list[MenuCategory]


def _sort_key(product: Product) -> tuple[float, str]:
    order = product.display_order if product.display_order is not None else float("inf")
    return (order, product.product_id)


def build_menu_response(products: list[Product]) -> MenuResponse:
    grouped: dict[str, list[Product]] = {category: [] for category in MENU_CATEGORIES}
    for product in products:
        grouped[product.category].append(product)

    categories = [
        MenuCategory(category=category, products=sorted(grouped[category], key=_sort_key))
        for category in MENU_CATEGORIES
        if grouped[category]
    ]
    return MenuResponse(categories=categories)
