"""店員向けAPI(store-fn)のビジネスロジック。AWS非依存。

GSI2のQuery自体はI/Oを伴うためadapters層が行い、ここでは結果(OrderLineの並び)を
レスポンス形へ組み立てるだけ(domain/status/serviceと同じ役割分担)。
"""

from __future__ import annotations

from collections.abc import Sequence

from domain.order.models import OrderLine
from domain.store.models import ZoneLine, ZoneLinesResponse

# docs/architecture.md §7.5: キューに明細がある間3秒、空の間10秒をサーバーが指示する
# (requirements.md §9.1)。
_POLL_INTERVAL_QUEUED_SECONDS = 3
_POLL_INTERVAL_EMPTY_SECONDS = 10


def build_zone_lines_response(lines: Sequence[OrderLine]) -> ZoneLinesResponse:
    """GET /stores/{storeId}/zones/{zone}/lines のレスポンスを組み立てる。

    `lines`はGSI2をqueueSeq昇順でQueryした結果をそのまま渡す想定(adapters層で確定済み)。
    """
    zone_lines = [
        ZoneLine(
            order_id=line.order_id,
            order_number=line.order_number,
            line_id=line.line_id,
            zone=line.zone,
            product_id=line.product_id,
            name=line.name,
            variant=line.variant,
            quantity=line.quantity,
            status=line.status,
            queue_seq=line.queue_seq,
            created_at=line.created_at,
        )
        for line in lines
    ]
    poll_after_seconds = (
        _POLL_INTERVAL_QUEUED_SECONDS if zone_lines else _POLL_INTERVAL_EMPTY_SECONDS
    )
    return ZoneLinesResponse(lines=zone_lines, poll_after_seconds=poll_after_seconds)
