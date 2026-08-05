"""注文状態ポーリング(status-fn)のレスポンスモデル。AWS非依存。

docs/architecture.md §7.4 の OrderStatus/QueuePosition 契約に対応。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from domain.fulfillment.models import LineStatus, OrderStatus, Zone


class OrderStatusLine(BaseModel):
    """GET /orders/{orderId} のlines配列1件分。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    line_id: str
    name: str
    zone: Zone
    status: LineStatus
    quantity: int
    position: int | None
    estimated_wait_minutes: int


class OrderStatusResponse(BaseModel):
    """GET /orders/{orderId} のレスポンス全体。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    order_id: str
    order_number: int
    status: OrderStatus
    updated_at: str
    lines: list[OrderStatusLine]
    estimated_ready_minutes: int
    poll_after_seconds: int | None


class QueuePositionLine(BaseModel):
    """GET /orders/{orderId}/queue-position のlines配列1件分(nameを含まない)。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    line_id: str
    zone: Zone
    status: LineStatus
    position: int | None
    estimated_wait_minutes: int


class QueuePositionResponse(BaseModel):
    """GET /orders/{orderId}/queue-position のレスポンス全体。

    OrderStatusResponseとほぼ同じ内容だが、注文ステータスのフィールド名が
    `orderStatus`(`status`ではない)である点がdocs/architecture.md §7.4のJSON例で異なる。
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    order_id: str
    order_status: OrderStatus
    lines: list[QueuePositionLine]
    estimated_ready_minutes: int
    poll_after_seconds: int | None
