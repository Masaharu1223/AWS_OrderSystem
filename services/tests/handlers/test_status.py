import importlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import boto3
import pytest
from moto import mock_aws

from adapters.order_repository import OrderRepository
from domain.order.models import Order, OrderLine

_TABLE_NAME = "test-table"
_STORE_ID = "store-01"
_CONTEXT = SimpleNamespace(aws_request_id="req-123")


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


def _create_order(order: Order, idempotency_key: str) -> None:
    repo = OrderRepository(_TABLE_NAME)
    repo.create_order(
        order,
        idempotency_key=idempotency_key,
        session_id="sess-setup",
        cart_keys=[],
        now=datetime(2026, 7, 12, 12, 0, 0, tzinfo=UTC),
    )


def _reload_handler(monkeypatch: pytest.MonkeyPatch) -> Any:
    # handlers.status はコールドスタート最適化のためモジュールレベルでRepositoryを生成する。
    # モックしたテーブルに対して束縛し直すため、TABLE_NAME設定後にreloadする。
    monkeypatch.setenv("TABLE_NAME", _TABLE_NAME)
    import handlers.status as module

    importlib.reload(module)
    return module


def _get_status_event(order_id: str) -> dict[str, Any]:
    return {"routeKey": "GET /orders/{orderId}", "pathParameters": {"orderId": order_id}}


def _get_queue_position_event(order_id: str) -> dict[str, Any]:
    return {
        "routeKey": "GET /orders/{orderId}/queue-position",
        "pathParameters": {"orderId": order_id},
    }


# --- GET /orders/{orderId} ---


@mock_aws
def test_get_order_status_returns_404_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    status_handler = _reload_handler(monkeypatch)

    response = status_handler.handler(_get_status_event("does-not-exist"), _CONTEXT)

    assert response["statusCode"] == 404


@mock_aws
def test_get_order_status_returns_200_with_fallback_wait_minutes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    _create_order(_order([_line(lineId="001", zone="A", queueSeq=1)]), "key-1")
    status_handler = _reload_handler(monkeypatch)

    response = status_handler.handler(_get_status_event("ord-xyz"), _CONTEXT)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["orderId"] == "ord-xyz"
    assert body["orderNumber"] == 42
    assert body["status"] == "STORE_ACCEPTED"
    line = body["lines"][0]
    assert line["position"] == 1  # 自分より前に誰もいない
    # ZONESTAT未存在のZone Aフォールバック: ceil(1*25/60)=1 + 3(安全マージン) = 4
    assert line["estimatedWaitMinutes"] == 4
    assert body["estimatedReadyMinutes"] == 4
    assert body["pollAfterSeconds"] == 5


@mock_aws
def test_get_order_status_uses_zonestat_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    table = boto3.resource("dynamodb").Table(_TABLE_NAME)
    table.put_item(
        Item={
            "PK": f"ZONESTAT#{_STORE_ID}#A",
            "SK": "STAT",
            "sumSeconds": 120,
            "sampleCount": 4,  # 平均30秒/明細
        }
    )
    _create_order(_order([_line(lineId="001", zone="A", queueSeq=1)]), "key-2")
    status_handler = _reload_handler(monkeypatch)

    response = status_handler.handler(_get_status_event("ord-xyz"), _CONTEXT)

    body = json.loads(response["body"])
    # 平均30秒 × position1 = 30秒 → 切り上げで1分(フォールバックの4分は使われない)
    assert body["lines"][0]["estimatedWaitMinutes"] == 1


@mock_aws
def test_get_order_status_position_counts_lines_ahead_in_same_zone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    _create_order(
        _order([_line(lineId="001", zone="B", queueSeq=10)], orderId="ord-first"), "key-3"
    )
    _create_order(
        _order([_line(lineId="001", zone="B", queueSeq=20)], orderId="ord-second"), "key-4"
    )
    status_handler = _reload_handler(monkeypatch)

    response = status_handler.handler(_get_status_event("ord-second"), _CONTEXT)

    body = json.loads(response["body"])
    assert body["lines"][0]["position"] == 2  # 自分より前(queueSeq=10)が1件


@mock_aws
def test_get_order_status_all_lines_inactive_skips_position_and_stops_polling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    _create_order(
        _order([_line(lineId="001", zone="A", status="HANDED_OVER", queueSeq=1)]), "key-5"
    )
    status_handler = _reload_handler(monkeypatch)

    response = status_handler.handler(_get_status_event("ord-xyz"), _CONTEXT)

    body = json.loads(response["body"])
    assert body["status"] == "HANDED_OVER"
    assert body["lines"][0]["position"] is None
    assert body["lines"][0]["estimatedWaitMinutes"] == 0
    assert body["estimatedReadyMinutes"] == 0
    assert body["pollAfterSeconds"] is None


# --- GET /orders/{orderId}/queue-position ---


@mock_aws
def test_get_queue_position_returns_404_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    status_handler = _reload_handler(monkeypatch)

    response = status_handler.handler(_get_queue_position_event("does-not-exist"), _CONTEXT)

    assert response["statusCode"] == 404


@mock_aws
def test_get_queue_position_returns_200_with_order_status_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    _create_order(_order([_line(lineId="001", zone="A", queueSeq=1)]), "key-6")
    status_handler = _reload_handler(monkeypatch)

    response = status_handler.handler(_get_queue_position_event("ord-xyz"), _CONTEXT)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["orderId"] == "ord-xyz"
    assert body["orderStatus"] == "STORE_ACCEPTED"
    assert "status" not in body
    assert "name" not in body["lines"][0]
    assert "quantity" not in body["lines"][0]


# --- 未知のルート ---


@mock_aws
def test_unknown_route_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    status_handler = _reload_handler(monkeypatch)

    response = status_handler.handler({"routeKey": "GET /unknown"}, _CONTEXT)

    assert response["statusCode"] == 404
