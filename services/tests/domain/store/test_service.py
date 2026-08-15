from typing import Any

from domain.order.models import OrderLine
from domain.store.service import build_zone_lines_response


def _line(**overrides: Any) -> OrderLine:
    kwargs: dict[str, Any] = {
        "lineId": "001",
        "orderId": "ord-xyz",
        "orderNumber": 42,
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


def test_build_zone_lines_response_maps_order_line_fields() -> None:
    line = _line()

    response = build_zone_lines_response([line])

    assert len(response.lines) == 1
    zone_line = response.lines[0]
    assert zone_line.order_id == "ord-xyz"
    assert zone_line.order_number == 42
    assert zone_line.line_id == "001"
    assert zone_line.zone == "A"
    assert zone_line.product_id == "prod-001"
    assert zone_line.name == "カフェラテ"
    assert zone_line.variant.size == "L"
    assert zone_line.quantity == 1
    assert zone_line.status == "WAITING"
    assert zone_line.queue_seq == 1542
    assert zone_line.created_at == "2026-07-12T12:00:00Z"


def test_build_zone_lines_response_preserves_input_order() -> None:
    # docs/architecture.md §7.5: adapters層がGSI2をqueueSeq昇順でQuery済みの前提。
    # ここでは並び替えはせず、受け取った順をそのまま反映することだけを確認する。
    first = _line(lineId="001", queueSeq=10)
    second = _line(lineId="002", queueSeq=20)

    response = build_zone_lines_response([first, second])

    assert [line.line_id for line in response.lines] == ["001", "002"]


def test_build_zone_lines_response_poll_after_seconds_when_queued() -> None:
    response = build_zone_lines_response([_line()])
    assert response.poll_after_seconds == 3


def test_build_zone_lines_response_poll_after_seconds_when_empty() -> None:
    response = build_zone_lines_response([])
    assert response.lines == []
    assert response.poll_after_seconds == 10
