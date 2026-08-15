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
_HANDOVER_PARAMETER_NAME = "/mobile-order/test/handover-api-key"
_HANDOVER_API_KEY = "correct-secret"
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


def _put_handover_parameter() -> None:
    boto3.client("ssm").put_parameter(
        Name=_HANDOVER_PARAMETER_NAME, Value=_HANDOVER_API_KEY, Type="SecureString"
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
    # handlers.store はコールドスタート最適化のためモジュールレベルでRepository・
    # HandoverAuthenticator(SSM GetParameter)を生成する。モックした環境に束縛し直すため、
    # 環境変数設定・SSMパラメータ投入後にreloadする。
    monkeypatch.setenv("TABLE_NAME", _TABLE_NAME)
    monkeypatch.setenv("HANDOVER_API_KEY_PARAMETER_NAME", _HANDOVER_PARAMETER_NAME)
    import handlers.store as module

    importlib.reload(module)
    return module


def _get_zone_lines_event(store_id: str, zone: str) -> dict[str, Any]:
    return {
        "routeKey": "GET /stores/{storeId}/zones/{zone}/lines",
        "pathParameters": {"storeId": store_id, "zone": zone},
    }


def _update_status_event(
    order_id: str, line_id: str, from_status: str, to_status: str
) -> dict[str, Any]:
    return {
        "routeKey": "PATCH /orders/{orderId}/lines/{lineId}/status",
        "pathParameters": {"orderId": order_id, "lineId": line_id},
        "body": json.dumps({"fromStatus": from_status, "toStatus": to_status}),
    }


def _handover_event(order_id: str, line_id: str, api_key: str | None) -> dict[str, Any]:
    headers = {"x-api-key": api_key} if api_key is not None else {}
    return {
        "routeKey": "PATCH /orders/{orderId}/lines/{lineId}/handover",
        "pathParameters": {"orderId": order_id, "lineId": line_id},
        "headers": headers,
    }


# --- GET /stores/{storeId}/zones/{zone}/lines ---


@mock_aws
def test_get_zone_lines_returns_empty_list_with_10s_poll_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    _put_handover_parameter()
    store_handler = _reload_handler(monkeypatch)

    response = store_handler.handler(_get_zone_lines_event(_STORE_ID, "A"), _CONTEXT)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body == {"lines": [], "pollAfterSeconds": 10}


@mock_aws
def test_get_zone_lines_returns_lines_ordered_by_queue_seq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    _put_handover_parameter()
    _create_order(
        _order(
            [
                _line(lineId="001", orderId="ord-a", zone="A", queueSeq=20),
                _line(lineId="002", orderId="ord-a", zone="A", queueSeq=10),
            ],
            orderId="ord-a",
        ),
        "key-a",
    )
    store_handler = _reload_handler(monkeypatch)

    response = store_handler.handler(_get_zone_lines_event(_STORE_ID, "A"), _CONTEXT)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert [line["lineId"] for line in body["lines"]] == ["002", "001"]
    assert body["lines"][0]["orderNumber"] == 42
    assert body["pollAfterSeconds"] == 3


# --- PATCH /orders/{orderId}/lines/{lineId}/status ---


@mock_aws
def test_update_line_status_waiting_to_preparing_returns_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    _put_handover_parameter()
    _create_order(
        _order([_line(lineId="001", orderId="ord-b", zone="A")], orderId="ord-b"), "key-b"
    )
    store_handler = _reload_handler(monkeypatch)

    response = store_handler.handler(
        _update_status_event("ord-b", "001", "WAITING", "PREPARING"), _CONTEXT
    )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["status"] == "PREPARING"
    assert body["preparedAt"] is not None


@mock_aws
def test_update_line_status_rejects_disallowed_transition_with_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    _put_handover_parameter()
    _create_order(
        _order([_line(lineId="001", orderId="ord-c", zone="A")], orderId="ord-c"), "key-c"
    )
    store_handler = _reload_handler(monkeypatch)

    # WAITING→READYはいきなり飛ばす変化で許可されない(domain層のバリデーションで弾く)。
    response = store_handler.handler(
        _update_status_event("ord-c", "001", "WAITING", "READY"), _CONTEXT
    )

    assert response["statusCode"] == 409


@mock_aws
def test_update_line_status_returns_409_when_from_status_does_not_match_actual(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table()
    _put_handover_parameter()
    _create_order(
        _order([_line(lineId="001", orderId="ord-d", zone="A")], orderId="ord-d"), "key-d"
    )
    store_handler = _reload_handler(monkeypatch)

    # 実際はWAITINGなのにPREPARINGからの遷移だと主張する(二重スワイプ・競合の再現)。
    response = store_handler.handler(
        _update_status_event("ord-d", "001", "PREPARING", "READY"), _CONTEXT
    )

    assert response["statusCode"] == 409


# --- PATCH /orders/{orderId}/lines/{lineId}/handover ---


@mock_aws
def test_handover_line_without_api_key_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    _put_handover_parameter()
    _create_order(
        _order([_line(lineId="001", orderId="ord-e", zone="A")], orderId="ord-e"), "key-e"
    )
    store_handler = _reload_handler(monkeypatch)

    response = store_handler.handler(_handover_event("ord-e", "001", None), _CONTEXT)

    assert response["statusCode"] == 401


@mock_aws
def test_handover_line_with_wrong_api_key_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    _put_handover_parameter()
    _create_order(
        _order([_line(lineId="001", orderId="ord-f", zone="A")], orderId="ord-f"), "key-f"
    )
    store_handler = _reload_handler(monkeypatch)

    response = store_handler.handler(_handover_event("ord-f", "001", "wrong-secret"), _CONTEXT)

    assert response["statusCode"] == 401


@mock_aws
def test_handover_line_ready_to_handed_over_returns_200(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    _put_handover_parameter()
    _create_order(
        _order([_line(lineId="001", orderId="ord-g", zone="A")], orderId="ord-g"), "key-g"
    )
    store_handler = _reload_handler(monkeypatch)
    store_handler.handler(_update_status_event("ord-g", "001", "WAITING", "PREPARING"), _CONTEXT)
    store_handler.handler(_update_status_event("ord-g", "001", "PREPARING", "READY"), _CONTEXT)

    response = store_handler.handler(_handover_event("ord-g", "001", _HANDOVER_API_KEY), _CONTEXT)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["status"] == "HANDED_OVER"
    assert body["handedOverAt"] is not None


@mock_aws
def test_handover_line_when_not_ready_returns_409(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    _put_handover_parameter()
    _create_order(
        _order([_line(lineId="001", orderId="ord-h", zone="A")], orderId="ord-h"), "key-h"
    )
    store_handler = _reload_handler(monkeypatch)

    # まだWAITINGのまま(READYになっていない)状態で受渡検知が来た、誤検知のケース。
    response = store_handler.handler(_handover_event("ord-h", "001", _HANDOVER_API_KEY), _CONTEXT)

    assert response["statusCode"] == 409


# --- 未知ルート ---


@mock_aws
def test_unknown_route_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    _put_handover_parameter()
    store_handler = _reload_handler(monkeypatch)

    response = store_handler.handler({"routeKey": "GET /unknown"}, _CONTEXT)

    assert response["statusCode"] == 404
