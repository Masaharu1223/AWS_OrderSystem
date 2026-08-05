"""明細(FulfillmentLine)・注文ステータス・ゾーンの型定義。AWS非依存。

ここで定義するLiteral型は、order-fn・status-fn・将来のstore-fnが共通で使う
「値のドリフト防止用の単一の情報源」。docs/requirements.md §6・§7.1を参照。
"""

from __future__ import annotations

from typing import Literal

# 明細(1商品分の製造進捗)のステータス。docs/requirements.md §6.1の遷移図に対応。
# WAITING → PREPARING → READY → HANDED_OVER の直線遷移、または WAITING → CANCELLED のみ。
LineStatus = Literal["WAITING", "PREPARING", "READY", "HANDED_OVER", "CANCELLED"]

# 注文全体のステータス。全明細のLineStatusから導出される値であり、直接書き込みはしない
# (docs/requirements.md §6.2)。PENDING_PAYMENT/PAYMENT_FAILEDは将来の決済導入時の予約定義で
# MVPでは明細が無い段階の状態のため、導出ロジックの対象外としてここには含めない。
OrderStatus = Literal["STORE_ACCEPTED", "PREPARING", "READY_PICKUP", "HANDED_OVER", "CANCELLED"]

# 製造ゾーン。docs/requirements.md §7.1の表(カテゴリ×サイズ→ゾーン)に対応する4区画。
Zone = Literal["A", "B", "C", "D"]
