"""店員向けAPI(store-fn)のレスポンスモデル。AWS非依存。

docs/architecture.md §7.5 の LineCard / Line 契約に対応。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from domain.fulfillment.models import LineStatus, Zone
from domain.menu.models import Variant


class ZoneLine(BaseModel):
    """GET /stores/{storeId}/zones/{zone}/lines のlines配列1件分(LineCard)。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    order_id: str
    order_number: int
    line_id: str
    zone: Zone
    product_id: str
    name: str
    variant: Variant
    quantity: int
    status: LineStatus
    queue_seq: int
    created_at: str


class ZoneLinesResponse(BaseModel):
    """GET /stores/{storeId}/zones/{zone}/lines のレスポンス全体。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    lines: list[ZoneLine]
    poll_after_seconds: int


class LineStatusUpdateResponse(BaseModel):
    """PATCH /orders/{orderId}/lines/{lineId}/status のレスポンス。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    order_id: str
    line_id: str
    zone: Zone
    status: LineStatus
    prepared_at: str | None = None
    ready_at: str | None = None


class LineHandoverResponse(BaseModel):
    """PATCH /orders/{orderId}/lines/{lineId}/handover のレスポンス。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    order_id: str
    line_id: str
    zone: Zone
    status: LineStatus
    handed_over_at: str
