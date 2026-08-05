from datetime import UTC, datetime

import pytest

from domain.cart.models import CartItem
from domain.menu.models import Product
from domain.order.models import MAX_LINES_PER_ORDER
from domain.order.service import build_order, resolve_zone

NOW = datetime(2026, 7, 12, 12, 0, 0, tzinfo=UTC)


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


def _cart_item(**overrides: object) -> CartItem:
    kwargs: dict[str, object] = {
        "productId": "prod-001",
        "category": "espresso",
        "name": "カフェラテ",
        "variant": {"temperature": "hot", "size": "L"},
        "quantity": 1,
        # カート保存時のスナップショットとしてわざと商品マスタと異なる値にしておき、
        # build_order()が再計算した値(商品マスタ基準)で上書きされることを検証する。
        "unitPrice": 1,
        "addedAt": "2026-07-12T11:00:00Z",
        "updatedAt": "2026-07-12T11:00:00Z",
        "expiresAt": 9999999999,
    }
    kwargs.update(overrides)
    return CartItem(**kwargs)


def test_resolve_zone_covers_espresso_sizes() -> None:
    assert resolve_zone("espresso", "L") == "A"
    assert resolve_zone("espresso", "M") == "B"
    assert resolve_zone("espresso", "S") == "C"


def test_resolve_zone_non_espresso_goes_to_zone_d() -> None:
    assert resolve_zone("tea", "S") == "D"
    assert resolve_zone("frappe", "M") == "D"


def test_build_order_multi_zone_matches_architecture_example() -> None:
    # docs/architecture.md §6.4: ラテL(Zone A)+紅茶M(Zone D)、queueSeq=1542/880の例をそのまま再現。
    latte = _cart_item(
        productId="prod-001",
        category="espresso",
        name="カフェラテ",
        variant={"temperature": "hot", "size": "L"},
    )
    tea = _cart_item(
        productId="prod-014",
        category="tea",
        name="紅茶",
        variant={"temperature": "hot", "size": "M"},
    )
    products = {
        "prod-001": _product(productId="prod-001", category="espresso", basePrice=450),
        "prod-014": _product(
            productId="prod-014",
            category="tea",
            name="紅茶",
            basePrice=380,
            sizeDelta={"S": 0, "M": 40},
        ),
    }

    order = build_order(
        cart_items=[latte, tea],
        products=products,
        store_id="store-01",
        order_id="ord-xyz",
        order_number=42,
        zone_seq_ends={"A": 1542, "D": 880},
        now=NOW,
    )

    assert order.order_id == "ord-xyz"
    assert order.order_number == 42
    assert order.status == "STORE_ACCEPTED"
    assert len(order.lines) == 2

    line1, line2 = order.lines
    assert line1.line_id == "001"
    assert line1.zone == "A"
    assert line1.queue_seq == 1542
    assert line1.unit_price == 550  # 450 + 100(L)、カートのスナップショット(1)は使わない
    assert line1.status == "WAITING"

    assert line2.line_id == "002"
    assert line2.zone == "D"
    assert line2.queue_seq == 880
    assert line2.unit_price == 420  # 380 + 40(M)

    assert order.total_price == 970  # 550 + 420


def test_build_order_assigns_sequential_queue_seq_within_same_zone() -> None:
    # 同じゾーン(B: エスプレッソ×M)に2明細。カート順にブロック末尾から昇順で割り当てる。
    latte_m = _cart_item(
        productId="prod-001",
        category="espresso",
        variant={"temperature": "hot", "size": "M"},
    )
    cappuccino_m = _cart_item(
        productId="prod-002",
        category="espresso",
        name="カプチーノ",
        variant={"temperature": "hot", "size": "M"},
    )
    products = {
        "prod-001": _product(productId="prod-001"),
        "prod-002": _product(productId="prod-002", name="カプチーノ", basePrice=430),
    }

    order = build_order(
        cart_items=[latte_m, cappuccino_m],
        products=products,
        store_id="store-01",
        order_id="ord-abc",
        order_number=1,
        zone_seq_ends={"B": 100},
        now=NOW,
    )

    assert [line.queue_seq for line in order.lines] == [99, 100]
    assert [line.zone for line in order.lines] == ["B", "B"]


def test_build_order_rejects_empty_cart() -> None:
    with pytest.raises(ValueError, match="empty"):
        build_order(
            cart_items=[],
            products={},
            store_id="store-01",
            order_id="ord-xyz",
            order_number=1,
            zone_seq_ends={},
            now=NOW,
        )


def test_build_order_rejects_too_many_lines() -> None:
    count = MAX_LINES_PER_ORDER + 1
    cart_items = [_cart_item(productId=f"prod-{i:03d}") for i in range(count)]
    products = {f"prod-{i:03d}": _product(productId=f"prod-{i:03d}") for i in range(count)}

    with pytest.raises(ValueError, match="too many lines"):
        build_order(
            cart_items=cart_items,
            products=products,
            store_id="store-01",
            order_id="ord-xyz",
            order_number=1,
            zone_seq_ends={"A": MAX_LINES_PER_ORDER + 1},
            now=NOW,
        )


def test_build_order_allows_exactly_max_lines() -> None:
    count = MAX_LINES_PER_ORDER
    cart_items = [_cart_item(productId=f"prod-{i:03d}") for i in range(count)]
    products = {f"prod-{i:03d}": _product(productId=f"prod-{i:03d}") for i in range(count)}

    order = build_order(
        cart_items=cart_items,
        products=products,
        store_id="store-01",
        order_id="ord-xyz",
        order_number=1,
        zone_seq_ends={"A": MAX_LINES_PER_ORDER},
        now=NOW,
    )

    assert len(order.lines) == MAX_LINES_PER_ORDER
    assert order.lines[-1].line_id == f"{MAX_LINES_PER_ORDER:03d}"


def test_build_order_rejects_unavailable_product() -> None:
    # 確定時の最終防御(architecture.md §7.3): カート追加後に品切れになったケースを弾く。
    item = _cart_item()
    products = {"prod-001": _product(available=False)}

    with pytest.raises(ValueError, match="not available"):
        build_order(
            cart_items=[item],
            products=products,
            store_id="store-01",
            order_id="ord-xyz",
            order_number=1,
            zone_seq_ends={"A": 1},
            now=NOW,
        )


def test_build_order_rejects_disallowed_variant() -> None:
    item = _cart_item(variant={"temperature": "iced", "size": "L"})
    products = {"prod-001": _product(allowIced=False)}

    with pytest.raises(ValueError, match="does not allow iced"):
        build_order(
            cart_items=[item],
            products=products,
            store_id="store-01",
            order_id="ord-xyz",
            order_number=1,
            zone_seq_ends={"A": 1},
            now=NOW,
        )


def test_build_order_sets_created_at_and_updated_at_from_now() -> None:
    item = _cart_item()
    products = {"prod-001": _product()}

    order = build_order(
        cart_items=[item],
        products=products,
        store_id="store-01",
        order_id="ord-xyz",
        order_number=1,
        zone_seq_ends={"A": 1},
        now=NOW,
    )

    assert order.created_at == "2026-07-12T12:00:00Z"
    assert order.lines[0].created_at == "2026-07-12T12:00:00Z"
    assert order.lines[0].updated_at == "2026-07-12T12:00:00Z"
