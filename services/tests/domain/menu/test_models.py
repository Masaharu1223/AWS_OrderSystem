import pytest
from pydantic import ValidationError

from domain.menu.models import MENU_CATEGORIES, Product


def _base_kwargs(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "productId": "prod-001",
        "category": "espresso",
        "name": "カフェラテ",
        "basePrice": 450,
        "sizeDelta": {"S": 0, "M": 50, "L": 100},
        "allowHot": True,
        "allowIced": True,
        "available": True,
    }
    kwargs.update(overrides)
    return kwargs


def test_menu_categories_order() -> None:
    assert MENU_CATEGORIES == ("espresso", "tea", "frappe")


@pytest.mark.parametrize(
    ("category", "size_delta"),
    [
        ("espresso", {"S": 0, "M": 50, "L": 100}),
        ("tea", {"S": 0, "M": 50}),
        ("frappe", {"S": 0, "M": 80}),
    ],
)
def test_valid_size_delta(category: str, size_delta: dict[str, int]) -> None:
    product = Product(**_base_kwargs(category=category, sizeDelta=size_delta))
    assert product.category == category


@pytest.mark.parametrize(
    ("category", "size_delta"),
    [
        ("espresso", {"S": 0, "M": 50}),  # Lが無い
        ("tea", {"S": 0, "M": 50, "L": 100}),  # 非espressoにLがある
        ("frappe", {"S": 0}),  # Mが無い
    ],
)
def test_invalid_size_delta(category: str, size_delta: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        Product(**_base_kwargs(category=category, sizeDelta=size_delta))


def test_display_order_optional() -> None:
    product = Product(**_base_kwargs())
    assert product.display_order is None


def test_construction_from_dynamodb_like_item_ignores_keys() -> None:
    item = _base_kwargs()
    item["PK"] = "MENU"
    item["SK"] = "PROD#prod-001"
    product = Product(**item)
    assert product.product_id == "prod-001"


def test_serialization_uses_camel_case() -> None:
    product = Product(**_base_kwargs())
    dumped = product.model_dump(by_alias=True)
    assert dumped["productId"] == "prod-001"
    assert dumped["basePrice"] == 450
    assert dumped["sizeDelta"] == {"S": 0, "M": 50, "L": 100}
    assert "product_id" not in dumped
