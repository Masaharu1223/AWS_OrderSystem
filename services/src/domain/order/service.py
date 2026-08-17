"""注文確定のビジネスロジック。AWS非依存。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from domain.cart.models import CartItem
from domain.fulfillment.models import Zone
from domain.menu.models import Category, Product, Size
from domain.menu.pricing import resolve_unit_price, validate_variant
from domain.order.models import MAX_LINES_PER_ORDER, ZONE_BY_CATEGORY_SIZE, Order, OrderLine


def resolve_zone(category: Category, size: Size) -> Zone:
    """商品カテゴリ・サイズから担当ゾーンを引く(docs/requirements.md §7.1・§7.2)。"""
    return ZONE_BY_CATEGORY_SIZE[(category, size)]


def build_order(
    cart_items: Sequence[CartItem],
    products: Mapping[str, Product],
    store_id: str,
    order_id: str,
    order_number: int,
    zone_seq_ends: Mapping[Zone, int],
    now: datetime,
) -> Order:
    """カートから注文(Order)を組み立てる。docs/architecture.md §7.3ステップ1・2に対応する純粋関数。

    `products`は`cart_items`に含まれる`productId`を全て解決できるマッピング済みの前提
    (呼び出し側=adapters層が事前にDynamoDBから一括取得しておく)。
    価格はカート保存時のスナップショットを信用せず、ここで`domain/menu/pricing`を使って
    もう一度再計算する(注文確定を「最後の砦」の価格チェックにするため)。
    `zone_seq_ends`は、呼び出し側がゾーンごとに原子カウンタを予約済みで確定した
    「そのゾーンに割り当てるqueueSeqブロックの末尾の値」。ここでは値を新規発行せず、
    受け取ったブロック[end-n+1, end]をカート順(=lineId昇順)に割り当てるだけ。
    カートが空、または明細数が上限(20件)を超える場合はValueErrorを送出する
    (呼び出し側でVALIDATION_ERRORへ変換する)。
    """
    if not cart_items:
        raise ValueError("cart is empty")
    if len(cart_items) > MAX_LINES_PER_ORDER:
        raise ValueError(f"too many lines (max {MAX_LINES_PER_ORDER})")

    timestamp = _format_timestamp(now)

    # 1周目: 明細ごとにvariant再検証・価格再計算・ゾーン確定を行い、ゾーンごとの明細数を数える。
    # (queueSeqはゾーン単位の連番のため、先に各ゾーンの件数が分からないと割り当てられない)
    resolved: list[tuple[str, CartItem, int, Zone]] = []
    zone_counts: dict[Zone, int] = {}
    for index, cart_item in enumerate(cart_items, start=1):
        product = products[cart_item.product_id]
        validate_variant(product, cart_item.variant)
        if not product.available:
            raise ValueError(f"product {cart_item.product_id!r} is not available")
        unit_price = resolve_unit_price(product, cart_item.variant)
        zone = resolve_zone(cart_item.category, cart_item.variant.size)
        zone_counts[zone] = zone_counts.get(zone, 0) + 1
        resolved.append((f"{index:03d}", cart_item, unit_price, zone))

    # 2周目: ゾーンごとの予約済みブロック[end-n+1, end]の先頭から、カート順に割り当てる。
    zone_next_seq = {
        zone: zone_seq_ends[zone] - count + 1 for zone, count in zone_counts.items()
    }
    lines: list[OrderLine] = []
    for line_id, cart_item, unit_price, zone in resolved:
        queue_seq = zone_next_seq[zone]
        zone_next_seq[zone] += 1
        lines.append(
            OrderLine(
                line_id=line_id,
                order_id=order_id,
                order_number=order_number,
                product_id=cart_item.product_id,
                name=cart_item.name,
                category=cart_item.category,
                variant=cart_item.variant,
                quantity=cart_item.quantity,
                unit_price=unit_price,
                zone=zone,
                status="WAITING",
                queue_seq=queue_seq,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )

    return Order(
        order_id=order_id,
        order_number=order_number,
        store_id=store_id,
        lines=lines,
        created_at=timestamp,
    )


def _format_timestamp(now: datetime) -> str:
    """DynamoDBに保存するISO8601形式のタイムスタンプ文字列を組み立てる。"""
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")
