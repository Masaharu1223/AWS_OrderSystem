"""注文(Order/OrderLine)のドメインモデル。AWS非依存。

DynamoDBのORDER#<orderId>配下(META行+LINE#<lineId>行)への対応は
docs/architecture.md §6.1・§6.4、APIレスポンス契約は§7.3を参照。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, computed_field
from pydantic.alias_generators import to_camel

from domain.fulfillment.models import LineStatus, OrderStatus, Zone
from domain.fulfillment.service import derive_order_status
from domain.menu.models import Category, Size, Variant

# 1注文あたりの明細数上限。
# docs/architecture.md §7.3: TransactWriteItemsの最大100アクションに収めるための制約。
MAX_LINES_PER_ORDER = 20

# キー設計の定数(adapters/order_repository.py で使い回し、重複を防ぐ)。
ORDER_PARTITION_KEY_PREFIX = "ORDER#"
ORDER_META_SORT_KEY = "META"
ORDER_LINE_SORT_KEY_PREFIX = "LINE#"

# カテゴリ+サイズ→ゾーンの振り分け表(docs/requirements.md §7.1・§7.2の図をそのまま辞書化)。
# order-fnが注文確定時に明細ごとにこの表を引いてzoneを確定する(resolve_zone、service.py参照)。
ZONE_BY_CATEGORY_SIZE: dict[tuple[Category, Size], Zone] = {
    ("espresso", "L"): "A",
    ("espresso", "M"): "B",
    ("espresso", "S"): "C",
    ("tea", "S"): "D",
    ("tea", "M"): "D",
    ("frappe", "S"): "D",
    ("frappe", "M"): "D",
}


class OrderLine(BaseModel):
    """DynamoDBのLINE#<lineId>行に対応する内部表現。`lineTotal`は保存せず導出する。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    line_id: str
    order_id: str
    order_number: int
    product_id: str
    name: str
    category: Category
    variant: Variant
    quantity: int = Field(ge=1)
    unit_price: int
    zone: Zone
    status: LineStatus
    queue_seq: int
    created_at: str
    updated_at: str
    prepared_at: str | None = None
    ready_at: str | None = None
    handed_over_at: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def line_total(self) -> int:
        return self.quantity * self.unit_price


class Order(BaseModel):
    """docs/architecture.md §7.3 の Order 契約に対応。

    `status`/`totalPrice`はMETA行に保存された値をそのまま返すのではなく、
    全明細(lines)から`@computed_field`で都度導出する(§6.2、直接書き込み対象ではないため)。
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    order_id: str
    order_number: int
    store_id: str
    lines: list[OrderLine]
    created_at: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> OrderStatus:
        return derive_order_status([line.status for line in self.lines])

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_price(self) -> int:
        return sum(line.line_total for line in self.lines)


class CreateOrderInput(BaseModel):
    """POST /orders のリクエストボディ。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    session_id: str
    store_id: str
