import importlib
from types import SimpleNamespace
from typing import Any

import boto3
import pytest
from moto import mock_aws

_TABLE_NAME = "test-table"

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
    # handlers.menu はコールドスタート最適化のためモジュールレベルでRepositoryを生成する。
    # モックしたテーブルに対して束縛し直すため、TABLE_NAME設定後にreloadする。
    monkeypatch.setenv("TABLE_NAME", _TABLE_NAME)
    import handlers.menu as module

    importlib.reload(module)
    return module


@mock_aws
def test_get_menu_returns_200_with_categorized_products(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    _put_product(**_LATTE)
    menu_handler = _reload_handler(monkeypatch)

    response = menu_handler.handler(
        {"routeKey": "GET /menu"}, SimpleNamespace(aws_request_id="req-123")
    )

    assert response["statusCode"] == 200


@mock_aws
def test_get_menu_product_returns_200_when_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    _put_product(**_LATTE)
    menu_handler = _reload_handler(monkeypatch)

    response = menu_handler.handler(
        {"routeKey": "GET /menu/{productId}", "pathParameters": {"productId": "prod-001"}},
        SimpleNamespace(aws_request_id="req-123"),
    )

    assert response["statusCode"] == 200


@mock_aws
def test_get_menu_product_returns_404_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    menu_handler = _reload_handler(monkeypatch)

    response = menu_handler.handler(
        {"routeKey": "GET /menu/{productId}", "pathParameters": {"productId": "nope"}},
        SimpleNamespace(aws_request_id="req-123"),
    )

    assert response["statusCode"] == 404


@mock_aws
def test_unknown_route_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _create_table()
    menu_handler = _reload_handler(monkeypatch)

    response = menu_handler.handler(
        {"routeKey": "GET /unknown"}, SimpleNamespace(aws_request_id="req-123")
    )

    assert response["statusCode"] == 404


def test_import_fails_fast_when_table_name_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    # このテストは最後に実行される想定(reload失敗時、モジュールの_repositoryは
    # 直前の成功状態のまま残るため、後続テストのreloadに影響しない前提に依存しない)。
    monkeypatch.delenv("TABLE_NAME", raising=False)
    import handlers.menu as module

    with pytest.raises(RuntimeError):
        importlib.reload(module)
