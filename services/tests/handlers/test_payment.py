import importlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import boto3
import pytest
from moto import mock_aws

from adapters.order_repository import OrderRepository
from domain.order.models import PendingOrderLineSnapshot

_TABLE_NAME = "test-table"
_STORE_ID = "store-01"
_SESSION_ID = "sess-pay"
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


def _put_product(**attrs: Any) -> None:
    table = boto3.resource("dynamodb").Table(_TABLE_NAME)
    table.put_item(Item={"PK": "MENU", "SK": f"PROD#{attrs['productId']}", **attrs})


def _put_cart_item(session_id: str, sort_key: str) -> None:
    table = boto3.resource("dynamodb").Table(_TABLE_NAME)
    table.put_item(
        Item={"PK": f"CART#{session_id}", "SK": sort_key, "productId": "prod-001", "quantity": 1}
    )


def _create_pending_order(order_id: str = "ord-pay1") -> None:
    repo = OrderRepository(_TABLE_NAME)
    repo.create_pending_payment_order(
        order_id=order_id,
        store_id=_STORE_ID,
        session_id=_SESSION_ID,
        idempotency_key=f"key-{order_id}",
        lines=[
            PendingOrderLineSnapshot(
                lineId="001",
                productId="prod-001",
                name="カフェラテ",
                category="espresso",
                variant={"temperature": "hot", "size": "L"},
                quantity=1,
            )
        ],
        total_price=550,
        now=datetime(2026, 7, 12, 12, 0, 0, tzinfo=UTC),
    )


def _reload_handler(monkeypatch: pytest.MonkeyPatch) -> Any:
    # handlers.payment はコールドスタート最適化のためモジュールレベルでRepository・決済
    # プロバイダを生成する。モックしたテーブルに対して束縛し直すため、環境変数設定後にreloadする。
    monkeypatch.setenv("TABLE_NAME", _TABLE_NAME)
    monkeypatch.setenv("PAYMENT_PROVIDER", "fake")
    import handlers.payment as module

    importlib.reload(module)
    return module


def _webhook_event(body: dict[str, Any], *, valid_signature: bool = True) -> dict[str, Any]:
    headers = {"x-fake-signature": "valid" if valid_signature else "invalid"}
    return {
        "routeKey": "POST /payments/webhook",
        "body": json.dumps(body),
        "headers": headers,
    }


# --- 署名・通知の検証 ---


@mock_aws
def test_webhook_returns_401_on_invalid_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    payment_handler = _reload_handler(monkeypatch)
    event = _webhook_event(
        {"orderId": "ord-pay1", "outcome": "succeeded"}, valid_signature=False
    )

    response = payment_handler.handler(event, _CONTEXT)

    assert response["statusCode"] == 401


@mock_aws
def test_webhook_returns_200_on_malformed_body(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    payment_handler = _reload_handler(monkeypatch)
    event = {
        "routeKey": "POST /payments/webhook",
        "body": "not json",
        "headers": {"x-fake-signature": "valid"},
    }

    response = payment_handler.handler(event, _CONTEXT)

    # プロバイダ側の再送ループを避けるため、未知の通知でも200で受信確認する。
    assert response["statusCode"] == 200


@mock_aws
def test_webhook_returns_200_when_order_does_not_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    payment_handler = _reload_handler(monkeypatch)
    event = _webhook_event({"orderId": "does-not-exist", "outcome": "succeeded"})

    response = payment_handler.handler(event, _CONTEXT)

    assert response["statusCode"] == 200


# --- 支払い成功 ---


@mock_aws
def test_webhook_success_finalizes_order_and_consumes_cart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    _put_product(
        productId="prod-001",
        category="espresso",
        name="カフェラテ",
        basePrice=450,
        sizeDelta={"S": 0, "M": 50, "L": 100},
        allowHot=True,
        allowIced=True,
        available=True,
    )
    _put_cart_item(_SESSION_ID, "ITEM#prod-001#hot#L")
    _create_pending_order("ord-pay2")
    payment_handler = _reload_handler(monkeypatch)
    event = _webhook_event({"orderId": "ord-pay2", "outcome": "succeeded"})

    response = payment_handler.handler(event, _CONTEXT)

    assert response["statusCode"] == 200
    order_repository = OrderRepository(_TABLE_NAME)
    fetched = order_repository.get_order_or_pending("ord-pay2")
    from domain.order.models import Order

    assert isinstance(fetched, Order)
    assert fetched.status == "STORE_ACCEPTED"
    assert len(fetched.lines) == 1
    assert fetched.lines[0].zone == "A"  # espresso×L
    assert fetched.lines[0].queue_seq == 1

    # 注文が成立した今この瞬間に初めてカートが消費される。
    table = boto3.resource("dynamodb").Table(_TABLE_NAME)
    cart_response = table.get_item(Key={"PK": f"CART#{_SESSION_ID}", "SK": "ITEM#prod-001#hot#L"})
    assert "Item" not in cart_response


@mock_aws
def test_webhook_success_is_idempotent_on_duplicate_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    _put_product(
        productId="prod-001",
        category="espresso",
        name="カフェラテ",
        basePrice=450,
        sizeDelta={"S": 0, "M": 50, "L": 100},
        allowHot=True,
        allowIced=True,
        available=True,
    )
    _create_pending_order("ord-pay3")
    payment_handler = _reload_handler(monkeypatch)
    event = _webhook_event({"orderId": "ord-pay3", "outcome": "succeeded"})

    first = payment_handler.handler(event, _CONTEXT)
    second = payment_handler.handler(event, _CONTEXT)

    assert first["statusCode"] == 200
    assert second["statusCode"] == 200  # 二重配信でもエラーにはならない

    order_repository = OrderRepository(_TABLE_NAME)
    from domain.order.models import Order

    fetched = order_repository.get_order_or_pending("ord-pay3")
    assert isinstance(fetched, Order)
    # ゾーン採番が2回走っていないこと(queueSeqが2重に進んでいない)を、別注文で確認する。
    assert order_repository.reserve_zone_sequence(_STORE_ID, "A", 1) == 2  # 1件目の次


# --- 支払い失敗 ---


@mock_aws
def test_webhook_failure_marks_payment_failed_and_keeps_cart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    _put_cart_item(_SESSION_ID, "ITEM#prod-001#hot#L")
    _create_pending_order("ord-pay4")
    payment_handler = _reload_handler(monkeypatch)
    event = _webhook_event({"orderId": "ord-pay4", "outcome": "failed"})

    response = payment_handler.handler(event, _CONTEXT)

    assert response["statusCode"] == 200
    order_repository = OrderRepository(_TABLE_NAME)
    from domain.order.models import PendingPaymentOrder

    fetched = order_repository.get_order_or_pending("ord-pay4")
    assert isinstance(fetched, PendingPaymentOrder)
    assert fetched.status == "PAYMENT_FAILED"

    # 再決済できるよう、カートは消費されずに残る。
    table = boto3.resource("dynamodb").Table(_TABLE_NAME)
    cart_response = table.get_item(Key={"PK": f"CART#{_SESSION_ID}", "SK": "ITEM#prod-001#hot#L"})
    assert "Item" in cart_response


@mock_aws
def test_webhook_failure_is_idempotent_on_duplicate_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    _create_pending_order("ord-pay5")
    payment_handler = _reload_handler(monkeypatch)
    event = _webhook_event({"orderId": "ord-pay5", "outcome": "failed"})

    first = payment_handler.handler(event, _CONTEXT)
    second = payment_handler.handler(event, _CONTEXT)

    assert first["statusCode"] == 200
    assert second["statusCode"] == 200


# --- 未知のルート ---


@mock_aws
def test_unknown_route_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    payment_handler = _reload_handler(monkeypatch)

    response = payment_handler.handler({"routeKey": "GET /unknown"}, _CONTEXT)

    assert response["statusCode"] == 404
