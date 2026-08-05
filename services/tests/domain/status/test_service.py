import pytest

from domain.fulfillment.models import OrderStatus, Zone
from domain.order.models import Order, OrderLine
from domain.status.service import (
    build_order_status,
    build_queue_position,
    compute_poll_after_seconds,
)


def _line(**overrides: object) -> OrderLine:
    kwargs: dict[str, object] = {
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
    return OrderLine(**kwargs)


def _order(lines: list[OrderLine], **overrides: object) -> Order:
    kwargs: dict[str, object] = {
        "orderId": "ord-xyz",
        "orderNumber": 42,
        "storeId": "store-01",
        "lines": lines,
        "createdAt": "2026-07-12T12:00:00Z",
    }
    kwargs.update(overrides)
    return Order(**kwargs)


# --- compute_poll_after_seconds: docs/requirements.md §9.1・architecture.md §7.4 の目安表 ---


@pytest.mark.parametrize(
    ("status", "max_position", "any_preparing", "expected"),
    [
        ("HANDED_OVER", None, False, None),
        ("CANCELLED", None, False, None),
        ("HANDED_OVER", 10, True, None),  # 終了状態はposition/any_preparingに関わらずNone
        ("READY_PICKUP", None, False, 10),
        ("READY_PICKUP", 99, True, 10),  # READY_PICKUPは他の条件に関わらず10秒固定
        ("STORE_ACCEPTED", 5, False, 15),  # 全明細WAITINGかつ最大position>=5
        ("STORE_ACCEPTED", 4, False, 5),  # position<=4なら5秒
        ("STORE_ACCEPTED", None, False, 5),  # position情報が無ければ混雑判定できないので5秒
        ("PREPARING", 10, True, 5),  # いずれかがPREPARING中なら5秒(positionに関わらず)
        ("PREPARING", 10, False, 15),  # 表に無い組み合わせ(§14.11由来)でも同じ閾値ロジックを適用
    ],
)
def test_compute_poll_after_seconds(
    status: OrderStatus, max_position: int | None, any_preparing: bool, expected: int | None
) -> None:
    assert compute_poll_after_seconds(status, max_position, any_preparing) == expected


# --- build_order_status / build_queue_position ---


def test_build_order_status_matches_architecture_example() -> None:
    # docs/architecture.md §7.4のOrderStatus JSON例(ラテ完成/紅茶製造中)をそのまま再現する。
    latte = _line(
        lineId="001",
        name="カフェラテ",
        zone="A",
        status="READY",
        quantity=1,
    )
    tea = _line(
        lineId="002",
        productId="prod-014",
        name="紅茶",
        category="tea",
        variant={"temperature": "hot", "size": "M"},
        zone="D",
        status="PREPARING",
        quantity=1,
        queueSeq=880,
        updatedAt="2026-07-12T12:05:00Z",
    )
    order = _order([latte, tea])

    response = build_order_status(
        order,
        positions={"001": None, "002": 1},
        zone_avg_seconds={"D": 30.0},  # ceil(30*1/60) = 1分 になるよう調整
    )

    assert response.order_id == "ord-xyz"
    assert response.order_number == 42
    assert response.status == "PREPARING"
    assert response.updated_at == "2026-07-12T12:05:00Z"  # 明細のうち最新のupdatedAt

    line1, line2 = response.lines
    assert line1.position is None
    assert line1.estimated_wait_minutes == 0
    assert line2.position == 1
    assert line2.estimated_wait_minutes == 1

    assert response.estimated_ready_minutes == 1
    assert response.poll_after_seconds == 5  # 紅茶がPREPARING中のため


def test_build_order_status_falls_back_when_zonestat_missing_zone_d() -> None:
    tea = _line(
        lineId="001",
        productId="prod-014",
        name="紅茶",
        category="tea",
        variant={"temperature": "hot", "size": "M"},
        zone="D",
        status="WAITING",
        queueSeq=5,
    )
    order = _order([tea])

    response = build_order_status(order, positions={"001": 3}, zone_avg_seconds={})

    # 計画の小さな決定#3: ZONESTAT未存在のZone Dはpositionに関わらず固定4分。
    assert response.lines[0].estimated_wait_minutes == 4
    assert response.estimated_ready_minutes == 4


@pytest.mark.parametrize(
    ("position", "expected_minutes"),
    [
        (1, 4),  # ceil(1*25/60)=1 + 3(安全マージン) = 4
        (5, 6),  # ceil(5*25/60)=3 + 3 = 6
        (10, 8),  # ceil(10*25/60)=5 + 3 = 8
    ],
)
def test_build_order_status_falls_back_when_zonestat_missing_zone_a(
    position: int, expected_minutes: int
) -> None:
    latte = _line(lineId="001", zone="A", status="WAITING")
    order = _order([latte])

    response = build_order_status(order, positions={"001": position}, zone_avg_seconds={})

    assert response.lines[0].estimated_wait_minutes == expected_minutes


def test_build_order_status_uses_zonestat_average_when_present() -> None:
    latte = _line(lineId="001", zone="A", status="WAITING")
    order = _order([latte])

    # 平均40秒/明細 × position3 = 120秒 = ちょうど2分(切り上げ不要)
    response = build_order_status(order, positions={"001": 3}, zone_avg_seconds={"A": 40.0})

    assert response.lines[0].estimated_wait_minutes == 2


def test_build_order_status_rounds_up_fractional_minutes() -> None:
    latte = _line(lineId="001", zone="A", status="WAITING")
    order = _order([latte])

    # 平均50秒 × position1 = 50秒 → 切り上げで1分(計画の小さな決定#5)
    response = build_order_status(order, positions={"001": 1}, zone_avg_seconds={"A": 50.0})

    assert response.lines[0].estimated_wait_minutes == 1


def test_build_order_status_all_inactive_skips_position_and_poll_stops() -> None:
    latte = _line(lineId="001", zone="A", status="HANDED_OVER")
    order = _order([latte])

    response = build_order_status(order, positions={"001": None}, zone_avg_seconds={})

    assert response.status == "HANDED_OVER"
    assert response.lines[0].position is None
    assert response.lines[0].estimated_wait_minutes == 0
    assert response.estimated_ready_minutes == 0
    assert response.poll_after_seconds is None


def test_build_queue_position_uses_order_status_field_name() -> None:
    latte = _line(lineId="001", zone="A", status="WAITING")
    order = _order([latte])

    response = build_queue_position(order, positions={"001": 2}, zone_avg_seconds={})

    assert response.order_id == "ord-xyz"
    assert response.order_status == "STORE_ACCEPTED"
    assert response.lines[0].line_id == "001"
    assert response.lines[0].position == 2
    # QueuePositionLineはname/quantityを持たないモデル(docs/architecture.md §7.4)。
    assert not hasattr(response.lines[0], "name")
    assert not hasattr(response.lines[0], "quantity")


def test_build_queue_position_matches_build_order_status_calculations() -> None:
    latte = _line(lineId="001", zone="A", status="PREPARING")
    tea = _line(
        lineId="002",
        productId="prod-014",
        category="tea",
        variant={"temperature": "hot", "size": "M"},
        zone="D",
        status="WAITING",
        queueSeq=5,
    )
    order = _order([latte, tea])
    positions: dict[str, int | None] = {"001": 1, "002": 2}
    zone_avg_seconds: dict[Zone, float] = {"A": 40.0, "D": 30.0}

    status_response = build_order_status(order, positions, zone_avg_seconds)
    queue_response = build_queue_position(order, positions, zone_avg_seconds)

    assert [line.estimated_wait_minutes for line in status_response.lines] == [
        line.estimated_wait_minutes for line in queue_response.lines
    ]
    assert status_response.estimated_ready_minutes == queue_response.estimated_ready_minutes
    assert status_response.poll_after_seconds == queue_response.poll_after_seconds
    assert status_response.status == queue_response.order_status
