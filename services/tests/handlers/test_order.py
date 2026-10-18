import importlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import boto3
import pytest
from moto import mock_aws

from adapters.cart_repository import CartRepository
from adapters.order_repository import OrderRepository
from domain.cart.models import CartItem
from domain.order.models import Order, OrderLine

_TABLE_NAME = "test-table"
_SESSION_ID = "sess-abc"
_STORE_ID = "store-01"
_CONTEXT = SimpleNamespace(aws_request_id="req-123")

_LATTE = {
    "productId": "prod-001",
    "category": "espresso",
    "name": "カフェラテ",
    "basePrice": 450,
    "sizeDelta": {"S": 0, "M": 50, "L": 100},
    "allowHot": True,
    "allowIced": True,
    "available": True,
}

_TEA = {
    "productId": "prod-014",
    "category": "tea",
    "name": "紅茶",
    "basePrice": 380,
    "sizeDelta": {"S": 0, "M": 40},
    "allowHot": True,
    "allowIced": True,
    "available": True,
}

_SOLD_OUT = {
    "productId": "prod-003",
    "category": "espresso",
    "name": "アメリカーノ",
    "basePrice": 380,
    "sizeDelta": {"S": 0, "M": 50, "L": 100},
    "allowHot": True,
    "allowIced": True,
    "available": False,
}


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


def _put_cart_item(
    session_id: str,
    product_id: str,
    category: str,
    name: str,
    temperature: str,
    size: str,
    quantity: int = 1,
    unit_price: int = 999,
) -> None:
    repo = CartRepository(_TABLE_NAME)
    repo.put_item(
        session_id,
        CartItem(
            productId=product_id,
            category=category,
            name=name,
            variant={"temperature": temperature, "size": size},
            quantity=quantity,
            unitPrice=unit_price,
            addedAt="2026-07-12T11:00:00Z",
            updatedAt="2026-07-12T11:00:00Z",
            expiresAt=9999999999,
        ),
    )


def _reload_handler(monkeypatch: pytest.MonkeyPatch) -> Any:
    # handlers.order はコールドスタート最適化のためモジュールレベルでRepository・決済
    # プロバイダを生成する。モックしたテーブルに対して束縛し直すため、環境変数設定後にreloadする。
    monkeypatch.setenv("TABLE_NAME", _TABLE_NAME)
    monkeypatch.setenv("PAYMENT_PROVIDER", "fake")
    import handlers.order as module

    importlib.reload(module)
    return module


def _seed_store_accepted_order(order_id: str = "ord-seed") -> None:
    """cancel系テスト用に、決済確定済み(STORE_ACCEPTED)の注文を直接書き込む。

    POST /ordersはPENDING_PAYMENTまでしか作らなくなった(payment-fnが無いと明細を
    確定できない)ため、cancel_order()のテストにはリポジトリを直接使って土台を用意する。
    """
    line = OrderLine(
        lineId="001",
        orderId=order_id,
        orderNumber=1,
        productId="prod-001",
        name="カフェラテ",
        category="espresso",
        variant={"temperature": "hot", "size": "L"},
        quantity=1,
        unitPrice=550,
        zone="A",
        status="WAITING",
        queueSeq=1,
        createdAt="2026-07-12T12:00:00Z",
        updatedAt="2026-07-12T12:00:00Z",
    )
    order = Order(
        orderId=order_id,
        orderNumber=1,
        storeId=_STORE_ID,
        lines=[line],
        createdAt="2026-07-12T12:00:00Z",
    )
    OrderRepository(_TABLE_NAME).create_order(
        order,
        idempotency_key=f"seed-{order_id}",
        session_id="sess-seed",
        cart_keys=[],
        now=datetime(2026, 7, 12, 12, 0, 0, tzinfo=UTC),
    )


def _create_order_event(
    session_id: str = _SESSION_ID,
    store_id: str = _STORE_ID,
    idempotency_key: str | None = "idem-key-1",
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "routeKey": "POST /orders",
        "body": json.dumps({"sessionId": session_id, "storeId": store_id}),
        "headers": {},
    }
    if idempotency_key is not None:
        event["headers"]["Idempotency-Key"] = idempotency_key
    return event


def _cancel_order_event(order_id: str) -> dict[str, Any]:
    return {
        "routeKey": "PATCH /orders/{orderId}/cancel",
        "pathParameters": {"orderId": order_id},
    }


# --- POST /orders ---


@mock_aws
def test_create_order_returns_400_when_idempotency_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    order_handler = _reload_handler(monkeypatch)

    response = order_handler.handler(_create_order_event(idempotency_key=None), _CONTEXT)

    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"]["code"] == "VALIDATION_ERROR"


@mock_aws
def test_create_order_returns_400_when_body_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    order_handler = _reload_handler(monkeypatch)
    event = {"routeKey": "POST /orders", "headers": {"Idempotency-Key": "k1"}, "body": "{}"}

    response = order_handler.handler(event, _CONTEXT)

    assert response["statusCode"] == 400


@mock_aws
def test_create_order_returns_400_when_cart_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    order_handler = _reload_handler(monkeypatch)

    response = order_handler.handler(_create_order_event(), _CONTEXT)

    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"]["code"] == "VALIDATION_ERROR"


@mock_aws
def test_create_order_returns_404_when_product_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    _put_cart_item(_SESSION_ID, "does-not-exist", "espresso", "謎の商品", "hot", "L")
    order_handler = _reload_handler(monkeypatch)

    response = order_handler.handler(_create_order_event(), _CONTEXT)

    assert response["statusCode"] == 404


@mock_aws
def test_create_order_returns_400_when_product_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    _put_product(**_SOLD_OUT)
    _put_cart_item(_SESSION_ID, "prod-003", "espresso", "アメリカーノ", "hot", "L")
    order_handler = _reload_handler(monkeypatch)

    response = order_handler.handler(_create_order_event(), _CONTEXT)

    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"]["code"] == "VALIDATION_ERROR"


@mock_aws
def test_create_order_returns_201_pending_payment_with_checkout_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    _put_product(**_LATTE)
    _put_cart_item(_SESSION_ID, "prod-001", "espresso", "カフェラテ", "hot", "L")
    order_handler = _reload_handler(monkeypatch)

    response = order_handler.handler(_create_order_event(), _CONTEXT)

    assert response["statusCode"] == 201
    body = json.loads(response["body"])
    assert body["status"] == "PENDING_PAYMENT"
    assert body["totalPrice"] == 550  # 450 + 100(L)、カートのスナップショット(999)は使わない
    # ゾーン採番・明細作成は決済成功後(payment-fn)まで行わない。
    assert "lines" not in body
    # FakePaymentProvider.create_payment()が返すURL(adapters/payment/fake_payment_client.py)。
    assert body["checkoutUrl"] == f"https://fake-payment.local/checkout/{body['orderId']}"


@mock_aws
def test_create_order_does_not_delete_cart_items_yet(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    _put_product(**_LATTE)
    _put_cart_item(_SESSION_ID, "prod-001", "espresso", "カフェラテ", "hot", "L")
    order_handler = _reload_handler(monkeypatch)

    order_handler.handler(_create_order_event(), _CONTEXT)

    # カートの消費は決済成功時(payment-fnのfinalize_paid_order)まで行わない。
    # 決済が失敗/中断してもお客様がカートをやり直せるようにするため。
    cart_repo = CartRepository(_TABLE_NAME)
    assert len(cart_repo.list_items(_SESSION_ID)) == 1


@mock_aws
def test_create_order_retry_with_same_idempotency_key_returns_same_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    _put_product(**_LATTE)
    _put_cart_item(_SESSION_ID, "prod-001", "espresso", "カフェラテ", "hot", "L")
    order_handler = _reload_handler(monkeypatch)

    first = order_handler.handler(_create_order_event(idempotency_key="dup-key"), _CONTEXT)
    # 2回目は冪等キー一致の事前チェックで弾かれ、カートの再検証までは進まない。
    second = order_handler.handler(_create_order_event(idempotency_key="dup-key"), _CONTEXT)

    assert first["statusCode"] == 201
    assert second["statusCode"] == 201
    assert json.loads(first["body"])["orderId"] == json.loads(second["body"])["orderId"]


@mock_aws
def test_create_order_returns_500_when_payment_provider_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    _put_product(**_LATTE)
    _put_cart_item(_SESSION_ID, "prod-001", "espresso", "カフェラテ", "hot", "L")
    order_handler = _reload_handler(monkeypatch)

    from adapters.payment.base import PaymentProviderError

    class _FailingProvider:
        def create_payment(self, order_id: str, amount_yen: int) -> str:
            raise PaymentProviderError("sandbox is down")

        def verify_and_parse_notification(self, raw_body: str, headers: Any) -> Any:
            raise NotImplementedError

    order_handler._payment_provider = _FailingProvider()
    fixed_order_id = "ord-fixed-for-test"
    monkeypatch.setattr(order_handler.uuid, "uuid4", lambda: fixed_order_id)

    response = order_handler.handler(_create_order_event(), _CONTEXT)

    assert response["statusCode"] == 500
    # 仮注文自体はPENDING_PAYMENTのまま残る(欠番と同じく実害なしとして許容する)。
    pending = order_handler._order_repository.get_order_or_pending(str(fixed_order_id))
    assert pending is not None
    assert pending.status == "PENDING_PAYMENT"
    assert pending.checkout_url is None


@mock_aws
def test_create_order_returns_409_when_idempotency_key_reused_by_different_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    _put_product(**_LATTE)
    _put_cart_item(_SESSION_ID, "prod-001", "espresso", "カフェラテ", "hot", "L")
    order_handler = _reload_handler(monkeypatch)
    order_handler.handler(
        _create_order_event(session_id=_SESSION_ID, idempotency_key="shared-key"), _CONTEXT
    )

    _put_cart_item("sess-other", "prod-001", "espresso", "カフェラテ", "hot", "L")
    response = order_handler.handler(
        _create_order_event(session_id="sess-other", idempotency_key="shared-key"), _CONTEXT
    )

    assert response["statusCode"] == 409
    assert json.loads(response["body"])["error"]["code"] == "CONFLICT"


# --- PATCH /orders/{orderId}/cancel ---


@mock_aws
def test_cancel_order_returns_200_when_all_lines_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    order_handler = _reload_handler(monkeypatch)
    _seed_store_accepted_order("ord-cancel1")

    response = order_handler.handler(_cancel_order_event("ord-cancel1"), _CONTEXT)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["status"] == "CANCELLED"
    assert all(line["status"] == "CANCELLED" for line in body["lines"])


@mock_aws
def test_cancel_order_returns_409_when_a_line_is_not_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    order_handler = _reload_handler(monkeypatch)
    _seed_store_accepted_order("ord-cancel2")

    table = boto3.resource("dynamodb").Table(_TABLE_NAME)
    table.update_item(
        Key={"PK": "ORDER#ord-cancel2", "SK": "LINE#001"},
        UpdateExpression="SET #s = :preparing",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":preparing": "PREPARING"},
    )

    response = order_handler.handler(_cancel_order_event("ord-cancel2"), _CONTEXT)

    assert response["statusCode"] == 409
    assert json.loads(response["body"])["error"]["code"] == "CONFLICT"


@mock_aws
def test_cancel_order_returns_404_when_order_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    order_handler = _reload_handler(monkeypatch)

    response = order_handler.handler(_cancel_order_event("does-not-exist"), _CONTEXT)

    assert response["statusCode"] == 404


@mock_aws
def test_cancel_order_returns_500_when_order_is_still_pending_payment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # PENDING_PAYMENT段階のキャンセル対応は未実装(スコープ外)。クラッシュはしないが
    # 現状は500を返すだけの既知の制限であることを記録しておく(docs/requirements.md §12.1.1)。
    _create_table()
    _put_product(**_LATTE)
    _put_cart_item(_SESSION_ID, "prod-001", "espresso", "カフェラテ", "hot", "L")
    order_handler = _reload_handler(monkeypatch)
    created = order_handler.handler(_create_order_event(), _CONTEXT)
    order_id = json.loads(created["body"])["orderId"]

    response = order_handler.handler(_cancel_order_event(order_id), _CONTEXT)

    assert response["statusCode"] == 500


# --- 未知のルート ---


@mock_aws
def test_unknown_route_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    order_handler = _reload_handler(monkeypatch)

    response = order_handler.handler({"routeKey": "GET /unknown"}, _CONTEXT)

    assert response["statusCode"] == 404
