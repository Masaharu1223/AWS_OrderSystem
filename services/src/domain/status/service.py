"""注文状態ポーリングのビジネスロジック。AWS非依存。

キュー位置(GSI2のCOUNT)・ゾーン別平均製造時間(ZONESTAT)はI/Oを伴うため、
このモジュールの関数はどちらも引数として受け取るだけで自分では取得しない
(adapters層がDynamoDBから読み、handlers層がこの層の関数に渡す)。
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from domain.fulfillment.models import OrderStatus, Zone
from domain.order.models import Order, OrderLine
from domain.status.models import (
    OrderStatusLine,
    OrderStatusResponse,
    QueuePositionLine,
    QueuePositionResponse,
)

# requirements.md §8.1: エスプレッソ抽出時間は学習対象から除外した固定値。
_ESPRESSO_EXTRACTION_SECONDS = 25

# ZONESTAT未存在時(store-fn未実装で実績データが無い)のestimatedWaitMinutesフォールバック値。
# 計画の小さな決定#3: Zone Dは固定4分、Zone A/B/Cはposition×抽出時間の理論値+安全マージン。
_ZONE_D_FALLBACK_MINUTES = 4
_FALLBACK_SAFETY_MARGIN_MINUTES = 3

# requirements.md §9.1・architecture.md §7.4: pollAfterSecondsの目安秒数。
_POLL_INTERVAL_CONGESTED_SECONDS = 15
_POLL_INTERVAL_ACTIVE_SECONDS = 5
_POLL_INTERVAL_READY_PICKUP_SECONDS = 10
# 「混雑」とみなす最大position(=これ以上ならCONGESTED側の間隔にする)の閾値。
_CONGESTION_POSITION_THRESHOLD = 5


def compute_poll_after_seconds(
    status: OrderStatus,
    max_position: int | None,
    any_preparing: bool,
) -> int | None:
    """次回ポーリングまでの待機秒数を決める。

    docs/requirements.md §9.1・docs/architecture.md §7.4の目安表をそのまま実装する:
      - HANDED_OVER/CANCELLED               → None(ポーリング終了の合図)
      - READY_PICKUP                        → 10秒
      - 全明細WAITING(=PREPARING中の明細が無い)かつ最大position >= 5 → 15秒
      - それ以外(position <= 4、またはいずれかがPREPARING中)        → 5秒
    """
    if status in ("HANDED_OVER", "CANCELLED"):
        return None
    if status == "READY_PICKUP":
        return _POLL_INTERVAL_READY_PICKUP_SECONDS
    if (
        not any_preparing
        and max_position is not None
        and max_position >= _CONGESTION_POSITION_THRESHOLD
    ):
        return _POLL_INTERVAL_CONGESTED_SECONDS
    return _POLL_INTERVAL_ACTIVE_SECONDS


def build_order_status(
    order: Order,
    positions: Mapping[str, int | None],
    zone_avg_seconds: Mapping[Zone, float],
) -> OrderStatusResponse:
    """GET /orders/{orderId} のレスポンスを組み立てる。"""
    line_stats, estimated_ready_minutes, poll_after_seconds = _compute_line_stats(
        order, positions, zone_avg_seconds
    )
    lines = [
        OrderStatusLine(
            line_id=line.line_id,
            name=line.name,
            zone=line.zone,
            status=line.status,
            quantity=line.quantity,
            position=position,
            estimated_wait_minutes=wait_minutes,
        )
        for line, position, wait_minutes in line_stats
    ]
    return OrderStatusResponse(
        order_id=order.order_id,
        order_number=order.order_number,
        status=order.status,
        updated_at=max(line.updated_at for line in order.lines),
        lines=lines,
        estimated_ready_minutes=estimated_ready_minutes,
        poll_after_seconds=poll_after_seconds,
    )


def build_queue_position(
    order: Order,
    positions: Mapping[str, int | None],
    zone_avg_seconds: Mapping[Zone, float],
) -> QueuePositionResponse:
    """GET /orders/{orderId}/queue-position のレスポンスを組み立てる。

    build_order_status()と同じ計算内容を使うが、フィールド名(`orderStatus`)と
    lines配列の形(`name`/`quantity`を含まない)がdocs/architecture.md §7.4の通り異なる。
    """
    line_stats, estimated_ready_minutes, poll_after_seconds = _compute_line_stats(
        order, positions, zone_avg_seconds
    )
    lines = [
        QueuePositionLine(
            line_id=line.line_id,
            zone=line.zone,
            status=line.status,
            position=position,
            estimated_wait_minutes=wait_minutes,
        )
        for line, position, wait_minutes in line_stats
    ]
    return QueuePositionResponse(
        order_id=order.order_id,
        order_status=order.status,
        lines=lines,
        estimated_ready_minutes=estimated_ready_minutes,
        poll_after_seconds=poll_after_seconds,
    )


def _compute_line_stats(
    order: Order,
    positions: Mapping[str, int | None],
    zone_avg_seconds: Mapping[Zone, float],
) -> tuple[list[tuple[OrderLine, int | None, int]], int, int | None]:
    """明細ごとの(position, estimatedWaitMinutes)と、注文全体の集計値を計算する共通ロジック。

    build_order_status/build_queue_positionはレスポンスの形だけが違い、計算内容は同一のため
    ここに一本化する。戻り値は(明細ごとの内訳, estimatedReadyMinutes, pollAfterSeconds)。
    """
    line_stats: list[tuple[OrderLine, int | None, int]] = []
    for line in order.lines:
        position = positions.get(line.line_id)
        wait_minutes = (
            0 if position is None else _estimate_wait_minutes(line.zone, position, zone_avg_seconds)
        )
        line_stats.append((line, position, wait_minutes))

    active_waits = [wait for _, position, wait in line_stats if position is not None]
    estimated_ready_minutes = max(active_waits) if active_waits else 0

    active_positions = [position for _, position, _ in line_stats if position is not None]
    max_position = max(active_positions) if active_positions else None
    any_preparing = any(line.status == "PREPARING" for line in order.lines)
    poll_after_seconds = compute_poll_after_seconds(order.status, max_position, any_preparing)

    return line_stats, estimated_ready_minutes, poll_after_seconds


def _estimate_wait_minutes(
    zone: Zone, position: int, zone_avg_seconds: Mapping[Zone, float]
) -> int:
    """1明細の待ち時間見込み(分、切り上げ)を計算する。

    docs/requirements.md §8.2: ZONESTATの移動平均(sumSeconds/sampleCount)×position。
    ZONESTATが未存在の場合は計画の小さな決定#3のフォールバックを使う。
    """
    avg_seconds = zone_avg_seconds.get(zone)
    if avg_seconds is not None:
        return math.ceil((avg_seconds * position) / 60)
    if zone == "D":
        return _ZONE_D_FALLBACK_MINUTES
    theoretical_seconds = position * _ESPRESSO_EXTRACTION_SECONDS
    return math.ceil(theoretical_seconds / 60) + _FALLBACK_SAFETY_MARGIN_MINUTES
