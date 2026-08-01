import pytest

from domain.menu.models import Product, Variant
from domain.menu.pricing import resolve_unit_price, validate_variant


def _product(**overrides: object) -> Product:
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
    return Product(**kwargs)


@pytest.mark.parametrize(
    ("size", "expected"),
    [("S", 450), ("M", 500), ("L", 550)],
)
def test_resolve_unit_price(size: str, expected: int) -> None:
    product = _product()
    variant = Variant(temperature="hot", size=size)
    assert resolve_unit_price(product, variant) == expected


def test_validate_variant_allows_hot_and_iced_when_both_permitted() -> None:
    product = _product(allowHot=True, allowIced=True)
    validate_variant(product, Variant(temperature="hot", size="S"))
    validate_variant(product, Variant(temperature="iced", size="S"))


def test_validate_variant_rejects_hot_when_not_allowed() -> None:
    product = _product(allowHot=False, allowIced=True)
    with pytest.raises(ValueError, match="does not allow hot"):
        validate_variant(product, Variant(temperature="hot", size="S"))


def test_validate_variant_rejects_iced_when_not_allowed() -> None:
    product = _product(allowHot=True, allowIced=False)
    with pytest.raises(ValueError, match="does not allow iced"):
        validate_variant(product, Variant(temperature="iced", size="S"))


def test_validate_variant_rejects_size_not_offered() -> None:
    # tea カテゴリは S/M のみ(Lを持たない)
    product = _product(category="tea", sizeDelta={"S": 0, "M": 50})
    with pytest.raises(ValueError, match="does not offer size"):
        validate_variant(product, Variant(temperature="hot", size="L"))


def test_variant_to_key_segment() -> None:
    variant = Variant(temperature="iced", size="M")
    assert variant.to_key_segment() == "iced#M"
