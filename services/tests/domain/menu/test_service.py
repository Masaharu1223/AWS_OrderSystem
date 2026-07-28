from domain.menu.models import Product
from domain.menu.service import build_menu_response

_ESPRESSO_SIZE = {"S": 0, "M": 50, "L": 100}
_OTHER_SIZE = {"S": 0, "M": 50}


def _product(
    product_id: str,
    category: str,
    size_delta: dict[str, int],
    display_order: int | None = None,
) -> Product:
    return Product(
        productId=product_id,
        category=category,
        name="dummy",
        basePrice=100,
        sizeDelta=size_delta,
        allowHot=True,
        allowIced=True,
        available=True,
        displayOrder=display_order,
    )


def test_groups_by_category_in_menu_categories_order() -> None:
    products = [
        _product("prod-tea", "tea", _OTHER_SIZE),
        _product("prod-espresso", "espresso", _ESPRESSO_SIZE),
    ]
    response = build_menu_response(products)
    assert [c.category for c in response.categories] == ["espresso", "tea"]


def test_omits_empty_categories() -> None:
    products = [_product("prod-espresso", "espresso", _ESPRESSO_SIZE)]
    response = build_menu_response(products)
    assert [c.category for c in response.categories] == ["espresso"]


def test_sorts_by_display_order_then_product_id() -> None:
    products = [
        _product("prod-b", "espresso", _ESPRESSO_SIZE, display_order=2),
        _product("prod-a", "espresso", _ESPRESSO_SIZE, display_order=1),
        _product("prod-no-order-b", "espresso", _ESPRESSO_SIZE),
        _product("prod-no-order-a", "espresso", _ESPRESSO_SIZE),
    ]
    response = build_menu_response(products)
    ids = [p.product_id for p in response.categories[0].products]
    assert ids == ["prod-a", "prod-b", "prod-no-order-a", "prod-no-order-b"]


def test_empty_products_returns_no_categories() -> None:
    response = build_menu_response([])
    assert response.categories == []
