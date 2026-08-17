from datetime import UTC, datetime

import boto3
import pytest
from moto import mock_aws

from adapters.order_repository import (
    IdempotencyConflict,
    LineTransitionConflictError,
    OrderNotCancellableError,
    OrderNotFoundError,
    OrderRepository,
)
from domain.order.models import Order, OrderLine

_TABLE_NAME = "test-mobile-order-table"
_STORE_ID = "store-01"
NOW = datetime(2026, 7, 12, 12, 0, 0, tzinfo=UTC)


def _create_table() -> None:
    client = boto3.client("dynamodb")
    client.create_table(
        TableName=_TABLE_NAME,
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
            {"AttributeName": "GSI2PK", "AttributeType": "S"},
            {"AttributeName": "GSI2SK", "AttributeType": "N"},
        ],
        BillingMode="PAY_PER_REQUEST",
        GlobalSecondaryIndexes=[
            {
                "IndexName": "GSI1",
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "GSI2",
                "KeySchema": [
                    {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
    )


def _line(**overrides: object) -> OrderLine:
    kwargs: dict[str, object] = {
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
        "queueSeq": 1,
        "createdAt": "2026-07-12T12:00:00Z",
        "updatedAt": "2026-07-12T12:00:00Z",
    }
    kwargs.update(overrides)
    return OrderLine(**kwargs)


def _order(lines: list[OrderLine], **overrides: object) -> Order:
    kwargs: dict[str, object] = {
        "orderId": "ord-xyz",
        "orderNumber": 42,
        "storeId": _STORE_ID,
        "lines": lines,
        "createdAt": "2026-07-12T12:00:00Z",
    }
    kwargs.update(overrides)
    return Order(**kwargs)


def _put_cart_item(session_id: str, sort_key: str) -> None:
    table = boto3.resource("dynamodb").Table(_TABLE_NAME)
    table.put_item(
        Item={
            "PK": f"CART#{session_id}",
            "SK": sort_key,
            "productId": "prod-001",
            "quantity": 1,
        }
    )


# --- get_idempotency_record ---


@mock_aws
def test_get_idempotency_record_returns_none_when_missing() -> None:
    _create_table()
    repo = OrderRepository(_TABLE_NAME)

    assert repo.get_idempotency_record("does-not-exist") is None


@mock_aws
def test_reserve_zone_sequence_accumulates_across_calls() -> None:
    _create_table()
    repo = OrderRepository(_TABLE_NAME)

    first_end = repo.reserve_zone_sequence(_STORE_ID, "A", 3)
    second_end = repo.reserve_zone_sequence(_STORE_ID, "A", 2)

    assert first_end == 3  # [1, 3]
    assert second_end == 5  # [4, 5]


@mock_aws
def test_reserve_zone_sequence_is_independent_per_zone() -> None:
    _create_table()
    repo = OrderRepository(_TABLE_NAME)

    zone_a_end = repo.reserve_zone_sequence(_STORE_ID, "A", 1)
    zone_d_end = repo.reserve_zone_sequence(_STORE_ID, "D", 1)

    assert zone_a_end == 1
    assert zone_d_end == 1


@mock_aws
def test_reserve_order_number_increments_per_store_and_date() -> None:
    _create_table()
    repo = OrderRepository(_TABLE_NAME)

    first = repo.reserve_order_number(_STORE_ID, "2026-07-12")
    second = repo.reserve_order_number(_STORE_ID, "2026-07-12")
    other_date = repo.reserve_order_number(_STORE_ID, "2026-07-13")

    assert first == 1
    assert second == 2
    assert other_date == 1  # 日付が違えば独立したカウンタ


@mock_aws
def test_create_order_writes_meta_and_lines_deletes_cart_and_records_idempotency() -> None:
    _create_table()
    repo = OrderRepository(_TABLE_NAME)
    _put_cart_item("sess-abc", "ITEM#prod-001#hot#L")
    _put_cart_item("sess-abc", "ITEM#prod-014#hot#M")

    latte = _line(lineId="001", zone="A", queueSeq=1542)
    tea = _line(
        lineId="002",
        productId="prod-014",
        name="紅茶",
        category="tea",
        variant={"temperature": "hot", "size": "M"},
        unitPrice=420,
        zone="D",
        queueSeq=880,
    )
    order = _order([latte, tea], orderId="ord-xyz", orderNumber=42)

    result = repo.create_order(
        order,
        idempotency_key="key-1",
        session_id="sess-abc",
        cart_keys=["ITEM#prod-001#hot#L", "ITEM#prod-014#hot#M"],
        now=NOW,
    )

    assert result is order
    fetched = repo.get_order("ord-xyz")
    assert fetched is not None
    assert fetched.order_number == 42
    assert fetched.status == "STORE_ACCEPTED"
    assert {line.line_id for line in fetched.lines} == {"001", "002"}

    table = boto3.resource("dynamodb").Table(_TABLE_NAME)
    line1_raw = table.get_item(Key={"PK": "ORDER#ord-xyz", "SK": "LINE#001"})["Item"]
    assert line1_raw["GSI2PK"] == "ZONE#store-01#A"
    assert line1_raw["GSI2SK"] == 1542

    # カート明細はトランザクション内で削除される(注文成立+カート残存による重複注文を防ぐ)
    cart_response = table.get_item(Key={"PK": "CART#sess-abc", "SK": "ITEM#prod-001#hot#L"})
    assert "Item" not in cart_response

    idempotency_record = repo.get_idempotency_record("key-1")
    assert idempotency_record is not None
    assert idempotency_record.order_id == "ord-xyz"
    assert idempotency_record.session_id == "sess-abc"


@mock_aws
def test_create_order_raises_idempotency_conflict_on_key_reuse() -> None:
    _create_table()
    repo = OrderRepository(_TABLE_NAME)

    first_order = _order([_line(orderId="ord-first")], orderId="ord-first")
    repo.create_order(
        first_order, idempotency_key="dup-key", session_id="sess-A", cart_keys=[], now=NOW
    )

    second_order = _order([_line(orderId="ord-second")], orderId="ord-second")
    with pytest.raises(IdempotencyConflict) as exc_info:
        repo.create_order(
            second_order, idempotency_key="dup-key", session_id="sess-B", cart_keys=[], now=NOW
        )

    assert exc_info.value.order_id == "ord-first"
    assert exc_info.value.session_id == "sess-A"
    # 衝突した2件目の注文は書き込まれていない(トランザクション全体がキャンセルされる)
    assert repo.get_order("ord-second") is None


@mock_aws
def test_get_order_returns_none_when_missing() -> None:
    _create_table()
    repo = OrderRepository(_TABLE_NAME)

    assert repo.get_order("does-not-exist") is None


@mock_aws
def test_cancel_order_cancels_all_waiting_lines_and_removes_from_gsi2() -> None:
    _create_table()
    repo = OrderRepository(_TABLE_NAME)
    order = _order(
        [
            _line(lineId="001", orderId="ord-cancel", zone="A", queueSeq=1),
            _line(lineId="002", orderId="ord-cancel", zone="A", queueSeq=2),
        ],
        orderId="ord-cancel",
    )
    repo.create_order(order, idempotency_key="key-c1", session_id="sess-c1", cart_keys=[], now=NOW)

    cancelled = repo.cancel_order("ord-cancel", now=NOW)

    assert cancelled.status == "CANCELLED"
    assert all(line.status == "CANCELLED" for line in cancelled.lines)
    # GSI2から除外されている(スパースインデックス)ため、後続の明細から見て並んでいないことになる
    assert repo.count_ahead_in_zone(_STORE_ID, "A", queue_seq=3) == 0


@mock_aws
def test_cancel_order_raises_not_cancellable_when_a_line_is_preparing() -> None:
    _create_table()
    repo = OrderRepository(_TABLE_NAME)
    order = _order(
        [
            _line(lineId="001", orderId="ord-mixed", zone="A", queueSeq=1),
            _line(lineId="002", orderId="ord-mixed", zone="A", queueSeq=2),
        ],
        orderId="ord-mixed",
    )
    repo.create_order(order, idempotency_key="key-c2", session_id="sess-c2", cart_keys=[], now=NOW)

    table = boto3.resource("dynamodb").Table(_TABLE_NAME)
    table.update_item(
        Key={"PK": "ORDER#ord-mixed", "SK": "LINE#001"},
        UpdateExpression="SET #s = :preparing",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":preparing": "PREPARING"},
    )

    with pytest.raises(OrderNotCancellableError):
        repo.cancel_order("ord-mixed", now=NOW)

    # トランザクション全体が失敗するため、他の明細(WAITING)も巻き込まれず状態は変化しない
    unchanged = repo.get_order("ord-mixed")
    assert unchanged is not None
    assert unchanged.status != "CANCELLED"
    line2 = next(line for line in unchanged.lines if line.line_id == "002")
    assert line2.status == "WAITING"


@mock_aws
def test_cancel_order_raises_not_found_for_unknown_order() -> None:
    _create_table()
    repo = OrderRepository(_TABLE_NAME)

    with pytest.raises(OrderNotFoundError):
        repo.cancel_order("does-not-exist", now=NOW)


@mock_aws
def test_count_ahead_in_zone_counts_only_smaller_queue_seq() -> None:
    _create_table()
    repo = OrderRepository(_TABLE_NAME)
    order = _order(
        [
            _line(lineId="001", orderId="ord-queue", zone="B", queueSeq=10),
            _line(lineId="002", orderId="ord-queue", zone="B", queueSeq=20),
            _line(lineId="003", orderId="ord-queue", zone="B", queueSeq=30),
        ],
        orderId="ord-queue",
    )
    repo.create_order(order, idempotency_key="key-q1", session_id="sess-q1", cart_keys=[], now=NOW)

    assert repo.count_ahead_in_zone(_STORE_ID, "B", queue_seq=25) == 2
    assert repo.count_ahead_in_zone(_STORE_ID, "B", queue_seq=10) == 0
    assert repo.count_ahead_in_zone(_STORE_ID, "B", queue_seq=31) == 3


@mock_aws
def test_count_ahead_in_zone_ignores_other_zones_and_stores() -> None:
    _create_table()
    repo = OrderRepository(_TABLE_NAME)
    order = _order(
        [_line(lineId="001", orderId="ord-other-zone", zone="A", queueSeq=5)],
        orderId="ord-other-zone",
    )
    repo.create_order(
        order, idempotency_key="key-q2", session_id="sess-q2", cart_keys=[], now=NOW
    )

    assert repo.count_ahead_in_zone(_STORE_ID, "B", queue_seq=100) == 0
    assert repo.count_ahead_in_zone("store-02", "A", queue_seq=100) == 0


@mock_aws
def test_get_zone_stat_returns_none_when_missing() -> None:
    _create_table()
    repo = OrderRepository(_TABLE_NAME)

    assert repo.get_zone_stat(_STORE_ID, "A") is None


@mock_aws
def test_get_zone_stat_returns_sum_and_count() -> None:
    _create_table()
    table = boto3.resource("dynamodb").Table(_TABLE_NAME)
    table.put_item(
        Item={
            "PK": f"ZONESTAT#{_STORE_ID}#A",
            "SK": "STAT",
            "sumSeconds": 900,
            "sampleCount": 30,
            "updatedAt": "2026-07-12T12:00:00Z",
        }
    )
    repo = OrderRepository(_TABLE_NAME)

    result = repo.get_zone_stat(_STORE_ID, "A")

    assert result == (900, 30)


# --- list_zone_lines ---


@mock_aws
def test_list_zone_lines_returns_lines_ordered_by_queue_seq() -> None:
    _create_table()
    repo = OrderRepository(_TABLE_NAME)
    order = _order(
        [
            _line(lineId="001", orderId="ord-zone", zone="A", queueSeq=20),
            _line(lineId="002", orderId="ord-zone", zone="A", queueSeq=10),
        ],
        orderId="ord-zone",
    )
    repo.create_order(order, idempotency_key="key-z1", session_id="sess-z1", cart_keys=[], now=NOW)

    lines = repo.list_zone_lines(_STORE_ID, "A")

    assert [line.queue_seq for line in lines] == [10, 20]
    assert [line.line_id for line in lines] == ["002", "001"]


@mock_aws
def test_list_zone_lines_excludes_other_zones_and_stores_and_inactive_lines() -> None:
    _create_table()
    repo = OrderRepository(_TABLE_NAME)
    order = _order(
        [_line(lineId="001", orderId="ord-zone2", zone="B", queueSeq=1)],
        orderId="ord-zone2",
    )
    repo.create_order(order, idempotency_key="key-z2", session_id="sess-z2", cart_keys=[], now=NOW)

    assert repo.list_zone_lines(_STORE_ID, "A") == []
    assert repo.list_zone_lines("store-02", "B") == []


# --- update_line_status ---


@mock_aws
def test_update_line_status_waiting_to_preparing_sets_prepared_at() -> None:
    _create_table()
    repo = OrderRepository(_TABLE_NAME)
    order = _order(
        [_line(lineId="001", orderId="ord-status1", zone="A", queueSeq=1)],
        orderId="ord-status1",
    )
    repo.create_order(order, idempotency_key="key-s1", session_id="sess-s1", cart_keys=[], now=NOW)

    updated = repo.update_line_status("ord-status1", "001", "WAITING", "PREPARING", NOW)

    assert updated.status == "PREPARING"
    assert updated.prepared_at == "2026-07-12T12:00:00Z"
    # PREPARING遷移ではGSI2からは外れない(まだ製造キューに残る)。
    assert len(repo.list_zone_lines(_STORE_ID, "A")) == 1


@mock_aws
def test_update_line_status_preparing_to_ready_removes_from_gsi2_and_records_zonestat() -> None:
    _create_table()
    repo = OrderRepository(_TABLE_NAME)
    order = _order(
        [_line(lineId="001", orderId="ord-status2", zone="A", queueSeq=1)],
        orderId="ord-status2",
    )
    repo.create_order(order, idempotency_key="key-s2", session_id="sess-s2", cart_keys=[], now=NOW)
    repo.update_line_status("ord-status2", "001", "WAITING", "PREPARING", NOW)

    ready_at = datetime(2026, 7, 12, 12, 1, 30, tzinfo=UTC)  # preparedAtの90秒後
    updated = repo.update_line_status("ord-status2", "001", "PREPARING", "READY", ready_at)

    assert updated.status == "READY"
    assert updated.ready_at == "2026-07-12T12:01:30Z"
    # READY遷移でGSI2から外れる(スパースインデックス)。
    assert repo.list_zone_lines(_STORE_ID, "A") == []
    # readyAt(12:01:30) - preparedAt(12:00:00) = 90秒がZONESTATへ加算される。
    assert repo.get_zone_stat(_STORE_ID, "A") == (90, 1)


@mock_aws
def test_update_line_status_raises_conflict_when_status_does_not_match() -> None:
    _create_table()
    repo = OrderRepository(_TABLE_NAME)
    order = _order(
        [_line(lineId="001", orderId="ord-status3", zone="A", queueSeq=1)],
        orderId="ord-status3",
    )
    repo.create_order(order, idempotency_key="key-s3", session_id="sess-s3", cart_keys=[], now=NOW)

    # 実際はWAITINGなのにPREPARINGからの遷移だと主張する不正なリクエスト。
    with pytest.raises(LineTransitionConflictError):
        repo.update_line_status("ord-status3", "001", "PREPARING", "READY", NOW)


@mock_aws
def test_update_line_status_raises_conflict_for_unknown_line() -> None:
    _create_table()
    repo = OrderRepository(_TABLE_NAME)

    with pytest.raises(LineTransitionConflictError):
        repo.update_line_status("does-not-exist", "001", "WAITING", "PREPARING", NOW)


# --- handover_line ---


@mock_aws
def test_handover_line_ready_to_handed_over() -> None:
    _create_table()
    repo = OrderRepository(_TABLE_NAME)
    order = _order(
        [_line(lineId="001", orderId="ord-handover1", zone="A", queueSeq=1)],
        orderId="ord-handover1",
    )
    repo.create_order(
        order, idempotency_key="key-h1", session_id="sess-h1", cart_keys=[], now=NOW
    )
    repo.update_line_status("ord-handover1", "001", "WAITING", "PREPARING", NOW)
    repo.update_line_status("ord-handover1", "001", "PREPARING", "READY", NOW)

    updated = repo.handover_line("ord-handover1", "001", NOW)

    assert updated.status == "HANDED_OVER"
    assert updated.handed_over_at == "2026-07-12T12:00:00Z"


@mock_aws
def test_handover_line_raises_conflict_when_not_ready() -> None:
    _create_table()
    repo = OrderRepository(_TABLE_NAME)
    order = _order(
        [_line(lineId="001", orderId="ord-handover2", zone="A", queueSeq=1)],
        orderId="ord-handover2",
    )
    repo.create_order(
        order, idempotency_key="key-h2", session_id="sess-h2", cart_keys=[], now=NOW
    )

    # まだWAITINGのまま(READYになっていない)状態で受渡検知が来た、誤検知のケース。
    with pytest.raises(LineTransitionConflictError):
        repo.handover_line("ord-handover2", "001", NOW)
