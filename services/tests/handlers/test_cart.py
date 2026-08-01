import importlib
import json
from types import SimpleNamespace
from typing import Any

import boto3
import pytest
from moto import mock_aws

_TABLE_NAME = "test-table"
_SESSION_ID = "sess-abc"
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

_CAPPUCCINO_NO_ICE = {
    "productId": "prod-002",
    "category": "espresso",
    "name": "カプチーノ",
    "basePrice": 430,
    "sizeDelta": {"S": 0, "M": 50, "L": 100},
    "allowHot": True,
    "allowIced": False,
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
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _put_product(**attrs: Any) -> None:
    table = boto3.resource("dynamodb").Table(_TABLE_NAME)
    table.put_item(Item={"PK": "MENU", "SK": f"PROD#{attrs['productId']}", **attrs})


def _reload_handler(monkeypatch: pytest.MonkeyPatch) -> Any:
    # handlers.cart はコールドスタート最適化のためモジュールレベルでRepositoryを生成する。
    # モックしたテーブルに対して束縛し直すため、TABLE_NAME設定後にreloadする。
    monkeypatch.setenv("TABLE_NAME", _TABLE_NAME)
    import handlers.cart as module

    importlib.reload(module)
    return module


def _add_item_event(
    session_id: str = _SESSION_ID,
    product_id: str = "prod-001",
    category: str = "espresso",
    temperature: str = "iced",
    size: str = "M",
    quantity: int = 2,
) -> dict[str, Any]:
    return {
        "routeKey": "POST /cart/{sessionId}/items",
        "pathParameters": {"sessionId": session_id},
        "body": json.dumps(
            {
                "productId": product_id,
                "category": category,
                "variant": {"temperature": temperature, "size": size},
                "quantity": quantity,
            }
        ),
    }


@mock_aws
def test_get_cart_returns_200_with_empty_cart_for_unknown_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    cart_handler = _reload_handler(monkeypatch)

    response = cart_handler.handler(
        {"routeKey": "GET /cart/{sessionId}", "pathParameters": {"sessionId": _SESSION_ID}},
        _CONTEXT,
    )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body == {"sessionId": _SESSION_ID, "items": [], "subtotal": 0}


@mock_aws
def test_add_item_returns_201_and_computes_price(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    _put_product(**_LATTE)
    cart_handler = _reload_handler(monkeypatch)

    response = cart_handler.handler(_add_item_event(quantity=2), _CONTEXT)

    assert response["statusCode"] == 201
    body = json.loads(response["body"])
    assert body["subtotal"] == 1000  # (450+50) * 2
    assert body["items"][0]["itemId"] == "prod-001#iced#M"
    assert body["items"][0]["quantity"] == 2


@mock_aws
def test_add_item_returns_404_when_product_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    cart_handler = _reload_handler(monkeypatch)

    response = cart_handler.handler(_add_item_event(product_id="does-not-exist"), _CONTEXT)

    assert response["statusCode"] == 404


@mock_aws
def test_add_item_returns_400_when_quantity_out_of_range(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    _put_product(**_LATTE)
    cart_handler = _reload_handler(monkeypatch)

    response = cart_handler.handler(_add_item_event(quantity=11), _CONTEXT)

    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"]["code"] == "VALIDATION_ERROR"


@mock_aws
def test_add_item_returns_400_when_variant_not_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    _put_product(**_CAPPUCCINO_NO_ICE)
    cart_handler = _reload_handler(monkeypatch)

    response = cart_handler.handler(
        _add_item_event(product_id="prod-002", temperature="iced"), _CONTEXT
    )

    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"]["code"] == "VALIDATION_ERROR"


@mock_aws
def test_add_item_returns_400_when_product_sold_out(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    _put_product(**_SOLD_OUT)
    cart_handler = _reload_handler(monkeypatch)

    response = cart_handler.handler(_add_item_event(product_id="prod-003"), _CONTEXT)

    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"]["code"] == "VALIDATION_ERROR"


@mock_aws
def test_add_item_twice_with_same_variant_merges_quantity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    _put_product(**_LATTE)
    cart_handler = _reload_handler(monkeypatch)

    cart_handler.handler(_add_item_event(quantity=2), _CONTEXT)
    response = cart_handler.handler(_add_item_event(quantity=3), _CONTEXT)

    assert response["statusCode"] == 201
    body = json.loads(response["body"])
    assert len(body["items"]) == 1
    assert body["items"][0]["quantity"] == 5


@mock_aws
def test_add_item_returns_400_when_merged_quantity_exceeds_max(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    _put_product(**_LATTE)
    cart_handler = _reload_handler(monkeypatch)

    cart_handler.handler(_add_item_event(quantity=8), _CONTEXT)
    response = cart_handler.handler(_add_item_event(quantity=3), _CONTEXT)

    assert response["statusCode"] == 400


@mock_aws
def test_add_item_different_variant_creates_separate_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    _put_product(**_LATTE)
    cart_handler = _reload_handler(monkeypatch)

    cart_handler.handler(_add_item_event(temperature="hot", size="S", quantity=1), _CONTEXT)
    response = cart_handler.handler(
        _add_item_event(temperature="iced", size="M", quantity=1), _CONTEXT
    )

    body = json.loads(response["body"])
    assert len(body["items"]) == 2


@mock_aws
def test_update_quantity_returns_200_and_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    _put_product(**_LATTE)
    cart_handler = _reload_handler(monkeypatch)
    cart_handler.handler(_add_item_event(quantity=2), _CONTEXT)

    response = cart_handler.handler(
        {
            "routeKey": "PUT /cart/{sessionId}/items/{itemId}",
            "pathParameters": {"sessionId": _SESSION_ID, "itemId": "prod-001#iced#M"},
            "body": json.dumps({"quantity": 5}),
        },
        _CONTEXT,
    )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["items"][0]["quantity"] == 5


@mock_aws
def test_update_quantity_returns_404_when_item_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    cart_handler = _reload_handler(monkeypatch)

    response = cart_handler.handler(
        {
            "routeKey": "PUT /cart/{sessionId}/items/{itemId}",
            "pathParameters": {"sessionId": _SESSION_ID, "itemId": "prod-001#iced#M"},
            "body": json.dumps({"quantity": 5}),
        },
        _CONTEXT,
    )

    assert response["statusCode"] == 404


@mock_aws
def test_update_quantity_returns_400_when_quantity_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    _put_product(**_LATTE)
    cart_handler = _reload_handler(monkeypatch)
    cart_handler.handler(_add_item_event(quantity=2), _CONTEXT)

    response = cart_handler.handler(
        {
            "routeKey": "PUT /cart/{sessionId}/items/{itemId}",
            "pathParameters": {"sessionId": _SESSION_ID, "itemId": "prod-001#iced#M"},
            "body": json.dumps({"quantity": 0}),
        },
        _CONTEXT,
    )

    assert response["statusCode"] == 400


@mock_aws
def test_update_quantity_returns_400_when_item_id_malformed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    cart_handler = _reload_handler(monkeypatch)

    response = cart_handler.handler(
        {
            "routeKey": "PUT /cart/{sessionId}/items/{itemId}",
            "pathParameters": {"sessionId": _SESSION_ID, "itemId": "not-a-valid-item-id"},
            "body": json.dumps({"quantity": 5}),
        },
        _CONTEXT,
    )

    assert response["statusCode"] == 400


@mock_aws
def test_delete_item_returns_204_and_removes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    _put_product(**_LATTE)
    cart_handler = _reload_handler(monkeypatch)
    cart_handler.handler(_add_item_event(quantity=2), _CONTEXT)

    response = cart_handler.handler(
        {
            "routeKey": "DELETE /cart/{sessionId}/items/{itemId}",
            "pathParameters": {"sessionId": _SESSION_ID, "itemId": "prod-001#iced#M"},
        },
        _CONTEXT,
    )

    assert response["statusCode"] == 204
    assert response["body"] == ""

    follow_up = cart_handler.handler(
        {"routeKey": "GET /cart/{sessionId}", "pathParameters": {"sessionId": _SESSION_ID}},
        _CONTEXT,
    )
    assert json.loads(follow_up["body"])["items"] == []


@mock_aws
def test_delete_item_returns_404_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    cart_handler = _reload_handler(monkeypatch)

    response = cart_handler.handler(
        {
            "routeKey": "DELETE /cart/{sessionId}/items/{itemId}",
            "pathParameters": {"sessionId": _SESSION_ID, "itemId": "prod-001#iced#M"},
        },
        _CONTEXT,
    )

    assert response["statusCode"] == 404


@mock_aws
def test_unknown_route_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    cart_handler = _reload_handler(monkeypatch)

    response = cart_handler.handler({"routeKey": "GET /unknown"}, _CONTEXT)

    assert response["statusCode"] == 404


def test_import_fails_fast_when_table_name_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TABLE_NAME", raising=False)
    import handlers.cart as module

    with pytest.raises(RuntimeError):
        importlib.reload(module)
