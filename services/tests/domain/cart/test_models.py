import pytest
from pydantic import ValidationError

from domain.cart.models import Cart, CartItem, parse_item_id
from domain.menu.models import Variant


def _item(**overrides: object) -> CartItem:
    kwargs: dict[str, object] = {
        "productId": "prod-001",
        "category": "espresso",
        "name": "カフェラテ",
        "variant": Variant(temperature="iced", size="M"),
        "quantity": 2,
        "unitPrice": 500,
        "addedAt": "2026-08-01T10:00:00Z",
        "updatedAt": "2026-08-01T10:00:00Z",
        "expiresAt": 1785886400,
    }
    kwargs.update(overrides)
    return CartItem(**kwargs)


def test_item_id_derived_from_product_id_and_variant() -> None:
    item = _item()
    assert item.item_id == "prod-001#iced#M"


def test_line_total_derived_from_quantity_and_unit_price() -> None:
    item = _item(quantity=3, unitPrice=500)
    assert item.line_total == 1500


def test_same_product_different_variant_yields_different_item_id() -> None:
    hot_s = _item(variant=Variant(temperature="hot", size="S"))
    iced_m = _item(variant=Variant(temperature="iced", size="M"))
    assert hot_s.item_id != iced_m.item_id


def test_quantity_above_max_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _item(quantity=11)


def test_quantity_zero_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _item(quantity=0)


def test_cart_subtotal_sums_line_totals() -> None:
    cart = Cart(
        sessionId="sess-abc",
        items=[
            _item(variant=Variant(temperature="hot", size="S"), quantity=1, unitPrice=450),
            _item(variant=Variant(temperature="iced", size="M"), quantity=2, unitPrice=500),
        ],
    )
    assert cart.subtotal == 1450


def test_empty_cart_subtotal_is_zero() -> None:
    cart = Cart(sessionId="sess-abc", items=[])
    assert cart.subtotal == 0


def test_cart_serialization_uses_camel_case_and_includes_computed_fields() -> None:
    cart = Cart(sessionId="sess-abc", items=[_item()])
    dumped = cart.model_dump(by_alias=True)
    assert dumped["sessionId"] == "sess-abc"
    assert dumped["subtotal"] == 1000
    assert dumped["items"][0]["itemId"] == "prod-001#iced#M"
    assert dumped["items"][0]["lineTotal"] == 1000


def test_parse_item_id_round_trips_with_item_id_property() -> None:
    item = _item(variant=Variant(temperature="iced", size="M"))
    product_id, variant = parse_item_id(item.item_id)
    assert product_id == "prod-001"
    assert variant == Variant(temperature="iced", size="M")


@pytest.mark.parametrize(
    "item_id",
    [
        "prod-001",  # セグメント不足
        "prod-001#iced",  # セグメント不足
        "prod-001#iced#M#extra",  # セグメント過剰
        "prod-001#lukewarm#M",  # 不正な温度
        "prod-001#iced#XL",  # 不正なサイズ
    ],
)
def test_parse_item_id_rejects_malformed_input(item_id: str) -> None:
    with pytest.raises(ValueError, match="malformed itemId"):
        parse_item_id(item_id)
