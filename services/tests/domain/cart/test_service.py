from datetime import UTC, datetime

import pytest

from domain.cart.models import MAX_QUANTITY_PER_ITEM
from domain.cart.service import build_item
from domain.menu.models import Product, Variant

NOW = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)


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


def test_build_item_computes_price_and_timestamps() -> None:
    product = _product()
    variant = Variant(temperature="iced", size="M")

    item = build_item(product, variant, quantity=2, now=NOW)

    assert item.product_id == "prod-001"
    assert item.category == "espresso"
    assert item.quantity == 2
    assert item.unit_price == 500  # 450 + 50(M)
    assert item.added_at == "2026-08-01T10:00:00Z"
    assert item.updated_at == "2026-08-01T10:00:00Z"
    assert item.expires_at == int(datetime(2026, 8, 2, 10, 0, 0, tzinfo=UTC).timestamp())


def test_build_item_without_existing_starts_quantity_from_request() -> None:
    product = _product()
    variant = Variant(temperature="hot", size="S")

    item = build_item(product, variant, quantity=3, now=NOW, existing=None)

    assert item.quantity == 3


def test_build_item_with_existing_merges_quantity_and_keeps_added_at() -> None:
    product = _product()
    variant = Variant(temperature="hot", size="S")
    existing = build_item(product, variant, quantity=2, now=NOW)

    later = datetime(2026, 8, 1, 11, 0, 0, tzinfo=UTC)
    merged = build_item(product, variant, quantity=3, now=later, existing=existing)

    assert merged.quantity == 5
    assert merged.added_at == existing.added_at  # 初回追加時刻は保持される
    assert merged.updated_at == "2026-08-01T11:00:00Z"


def test_build_item_rejects_when_merged_quantity_exceeds_max() -> None:
    product = _product()
    variant = Variant(temperature="hot", size="S")
    existing = build_item(product, variant, quantity=8, now=NOW)

    with pytest.raises(ValueError, match="exceeds maximum"):
        build_item(product, variant, quantity=3, now=NOW, existing=existing)


def test_build_item_allows_exactly_max_quantity() -> None:
    product = _product()
    variant = Variant(temperature="hot", size="S")

    item = build_item(product, variant, quantity=MAX_QUANTITY_PER_ITEM, now=NOW)

    assert item.quantity == MAX_QUANTITY_PER_ITEM


def test_build_item_rejects_unavailable_product() -> None:
    product = _product(available=False)
    variant = Variant(temperature="hot", size="S")

    with pytest.raises(ValueError, match="not available"):
        build_item(product, variant, quantity=1, now=NOW)


def test_build_item_rejects_disallowed_variant() -> None:
    product = _product(allowIced=False)
    variant = Variant(temperature="iced", size="S")

    with pytest.raises(ValueError, match="does not allow iced"):
        build_item(product, variant, quantity=1, now=NOW)


def test_build_item_different_variant_does_not_merge() -> None:
    # 同一商品でも温度・サイズが違えば別明細として扱う(existingを渡さない=別のSK)
    product = _product()
    hot_s = build_item(product, Variant(temperature="hot", size="S"), quantity=1, now=NOW)
    iced_m = build_item(product, Variant(temperature="iced", size="M"), quantity=1, now=NOW)

    assert hot_s.item_id != iced_m.item_id
    assert hot_s.quantity == 1
    assert iced_m.quantity == 1
