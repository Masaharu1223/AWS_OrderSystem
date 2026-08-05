from typing import Any

from domain.order.models import ZONE_BY_CATEGORY_SIZE, CreateOrderInput, Order, OrderLine


def _base_line_kwargs(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "lineId": "001",
        "productId": "prod-001",
        "name": "カフェラテ",
        "category": "espresso",
        "variant": {"temperature": "hot", "size": "L"},
        "quantity": 1,
        "unitPrice": 560,
        "zone": "A",
        "status": "WAITING",
        "queueSeq": 1542,
        "createdAt": "2026-07-12T12:00:00Z",
        "updatedAt": "2026-07-12T12:00:00Z",
    }
    kwargs.update(overrides)
    return kwargs


def test_order_line_line_total_is_computed() -> None:
    line = OrderLine(**_base_line_kwargs(quantity=2, unitPrice=560))
    assert line.line_total == 1120


def test_order_line_ignores_dynamodb_only_keys() -> None:
    item = _base_line_kwargs()
    item["PK"] = "ORDER#ord-xyz"
    item["SK"] = "LINE#001"
    item["GSI2PK"] = "ZONE#store-01#A"
    item["GSI2SK"] = 1542
    line = OrderLine(**item)
    assert line.line_id == "001"


def test_zone_by_category_size_covers_all_valid_combinations() -> None:
    # requirements.md §7.1: espressoはS/M/Lの3ゾーン、非espressoはS/Mのみ(Dゾーンに集約)。
    assert ZONE_BY_CATEGORY_SIZE[("espresso", "L")] == "A"
    assert ZONE_BY_CATEGORY_SIZE[("espresso", "M")] == "B"
    assert ZONE_BY_CATEGORY_SIZE[("espresso", "S")] == "C"
    assert ZONE_BY_CATEGORY_SIZE[("tea", "S")] == "D"
    assert ZONE_BY_CATEGORY_SIZE[("tea", "M")] == "D"
    assert ZONE_BY_CATEGORY_SIZE[("frappe", "S")] == "D"
    assert ZONE_BY_CATEGORY_SIZE[("frappe", "M")] == "D"
    assert len(ZONE_BY_CATEGORY_SIZE) == 7


def test_order_status_and_total_price_are_derived_from_lines() -> None:
    # docs/requirements.md §6.4: ラテL(Zone A)+紅茶M(Zone D)のゾーン跨ぎの例。
    latte = OrderLine(
        **_base_line_kwargs(
            lineId="001",
            productId="prod-001",
            name="カフェラテ",
            category="espresso",
            variant={"temperature": "hot", "size": "L"},
            unitPrice=560,
            zone="A",
            status="WAITING",
            queueSeq=1542,
        )
    )
    tea = OrderLine(
        **_base_line_kwargs(
            lineId="002",
            productId="prod-014",
            name="紅茶",
            category="tea",
            variant={"temperature": "hot", "size": "M"},
            unitPrice=420,
            zone="D",
            status="WAITING",
            queueSeq=880,
        )
    )
    order = Order(
        orderId="ord-xyz",
        orderNumber=42,
        storeId="store-01",
        lines=[latte, tea],
        createdAt="2026-07-12T12:00:00Z",
    )

    assert order.status == "STORE_ACCEPTED"  # 全明細WAITING
    assert order.total_price == 980  # 560 + 420

    # 1明細だけ進んでも、もう一方が追いつくまでPREPARINGのまま(§6.4 12:04時点)。
    latte_ready = latte.model_copy(update={"status": "READY"})
    order_mid = order.model_copy(update={"lines": [latte_ready, tea]})
    assert order_mid.status == "PREPARING"

    # 両方READYになった瞬間にREADY_PICKUP。
    tea_ready = tea.model_copy(update={"status": "READY"})
    order_ready = order.model_copy(update={"lines": [latte_ready, tea_ready]})
    assert order_ready.status == "READY_PICKUP"


def test_create_order_input_parses_camel_case_body() -> None:
    body = {"sessionId": "sess-abc", "storeId": "store-01"}
    parsed = CreateOrderInput(**body)
    assert parsed.session_id == "sess-abc"
    assert parsed.store_id == "store-01"
