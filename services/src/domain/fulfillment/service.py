"""注文ステータス導出ロジック。AWS非依存の純粋関数。"""

from __future__ import annotations

from collections.abc import Sequence

from domain.fulfillment.models import LineStatus, OrderStatus


def derive_order_status(line_statuses: Sequence[LineStatus]) -> OrderStatus:
    """全明細のステータスから、注文全体のステータスを導出する。

    docs/requirements.md §6.2の真理値表をそのまま実装する:
      - 全明細がCANCELLED                          → CANCELLED
      - 全明細がWAITING                             → STORE_ACCEPTED
      - 全明細(CANCELLEDを除く)がREADY              → READY_PICKUP
      - 全明細(CANCELLEDを除く)がHANDED_OVER        → HANDED_OVER
      - 上記いずれにも当てはまらない                 → PREPARING

    最後のPREPARINGは表に明記された「1明細以上がPREPARING/READYかつ全明細READYでない」
    だけでなく、表に無い組み合わせ(例: 1明細HANDED_OVER+別の1明細WAITING。§14.11の通り
    明細ごとに独立してカメラ検知されるため、READY_PICKUPを待たずに一部だけHANDED_OVERに
    なるケースが実際に起こりうる)も含めた総当たりの受け皿になっている
    (「全員揃っていない=進行中」という意味でPREPARINGに寄せる、ユーザー確認済みの方針)。
    """
    if all(status == "CANCELLED" for status in line_statuses):
        return "CANCELLED"

    if all(status == "WAITING" for status in line_statuses):
        return "STORE_ACCEPTED"

    # ここに到達した時点で「全明細CANCELLED」は上で弾かれているため、
    # active_lines(CANCELLEDを除いた明細)は必ず1件以上存在する。
    active_lines = [status for status in line_statuses if status != "CANCELLED"]

    if all(status == "READY" for status in active_lines):
        return "READY_PICKUP"

    if all(status == "HANDED_OVER" for status in active_lines):
        return "HANDED_OVER"

    return "PREPARING"
