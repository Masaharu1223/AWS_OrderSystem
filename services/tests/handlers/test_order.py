import importlib
import json
from types import SimpleNamespace
from typing import Any

import boto3
import pytest
from moto import mock_aws

from adapters.cart_repository import CartRepository
from domain.cart.models import CartItem

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
    # handlers.order はコールドスタート最適化のためモジュールレベルでRepositoryを生成する。
    # モックしたテーブルに対して束縛し直すため、TABLE_NAME設定後にreloadする。
    monkeypatch.setenv("TABLE_NAME", _TABLE_NAME)
    import handlers.order as module

    importlib.reload(module)
    return module


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
def test_create_order_returns_201_with_zone_and_queue_seq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    _put_product(**_LATTE)
    _put_cart_item(_SESSION_ID, "prod-001", "espresso", "カフェラテ", "hot", "L")
    order_handler = _reload_handler(monkeypatch)

    response = order_handler.handler(_create_order_event(), _CONTEXT)

    assert response["statusCode"] == 201
    body = json.loads(response["body"])
    assert body["storeId"] == _STORE_ID
    assert body["status"] == "STORE_ACCEPTED"
    assert len(body["lines"]) == 1
    line = body["lines"][0]
    assert line["zone"] == "A"  # espresso×L
    assert line["queueSeq"] == 1
    assert line["status"] == "WAITING"
    assert line["unitPrice"] == 550  # 450 + 100(L)、カートのスナップショット(999)は使わない


@mock_aws
def test_create_order_multi_zone_assigns_independent_queue_seq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    _put_product(**_LATTE)
    _put_product(**_TEA)
    _put_cart_item(_SESSION_ID, "prod-001", "espresso", "カフェラテ", "hot", "L")
    _put_cart_item(_SESSION_ID, "prod-014", "tea", "紅茶", "hot", "M")
    order_handler = _reload_handler(monkeypatch)

    response = order_handler.handler(_create_order_event(), _CONTEXT)

    assert response["statusCode"] == 201
    body = json.loads(response["body"])
    zones = {line["zone"] for line in body["lines"]}
    assert zones == {"A", "D"}  # espresso×L→A、tea×M→D


@mock_aws
def test_create_order_deletes_cart_items(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    _put_product(**_LATTE)
    _put_cart_item(_SESSION_ID, "prod-001", "espresso", "カフェラテ", "hot", "L")
    order_handler = _reload_handler(monkeypatch)

    order_handler.handler(_create_order_event(), _CONTEXT)

    cart_repo = CartRepository(_TABLE_NAME)
    assert cart_repo.list_items(_SESSION_ID) == []


@mock_aws
def test_create_order_retry_with_same_idempotency_key_returns_same_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    _put_product(**_LATTE)
    _put_cart_item(_SESSION_ID, "prod-001", "espresso", "カフェラテ", "hot", "L")
    order_handler = _reload_handler(monkeypatch)

    first = order_handler.handler(_create_order_event(idempotency_key="dup-key"), _CONTEXT)
    # 2回目はカートが既に空だが、冪等キー一致の事前チェックで弾かれ空チェックまで進まない
    second = order_handler.handler(_create_order_event(idempotency_key="dup-key"), _CONTEXT)

    assert first["statusCode"] == 201
    assert second["statusCode"] == 201
    assert json.loads(first["body"])["orderId"] == json.loads(second["body"])["orderId"]


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
    _put_product(**_LATTE)
    _put_cart_item(_SESSION_ID, "prod-001", "espresso", "カフェラテ", "hot", "L")
    order_handler = _reload_handler(monkeypatch)
    created = order_handler.handler(_create_order_event(), _CONTEXT)
    order_id = json.loads(created["body"])["orderId"]

    response = order_handler.handler(_cancel_order_event(order_id), _CONTEXT)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["status"] == "CANCELLED"
    assert all(line["status"] == "CANCELLED" for line in body["lines"])


@mock_aws
def test_cancel_order_returns_409_when_a_line_is_not_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    _put_product(**_LATTE)
    _put_cart_item(_SESSION_ID, "prod-001", "espresso", "カフェラテ", "hot", "L")
    order_handler = _reload_handler(monkeypatch)
    created = order_handler.handler(_create_order_event(), _CONTEXT)
    order_id = json.loads(created["body"])["orderId"]

    table = boto3.resource("dynamodb").Table(_TABLE_NAME)
    table.update_item(
        Key={"PK": f"ORDER#{order_id}", "SK": "LINE#001"},
        UpdateExpression="SET #s = :preparing",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":preparing": "PREPARING"},
    )

    response = order_handler.handler(_cancel_order_event(order_id), _CONTEXT)

    assert response["statusCode"] == 409
    assert json.loads(response["body"])["error"]["code"] == "CONFLICT"


@mock_aws
def test_cancel_order_returns_404_when_order_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    order_handler = _reload_handler(monkeypatch)

    response = order_handler.handler(_cancel_order_event("does-not-exist"), _CONTEXT)

    assert response["statusCode"] == 404


# --- 未知のルート ---


@mock_aws
def test_unknown_route_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    order_handler = _reload_handler(monkeypatch)

    response = order_handler.handler({"routeKey": "GET /unknown"}, _CONTEXT)

    assert response["statusCode"] == 404
