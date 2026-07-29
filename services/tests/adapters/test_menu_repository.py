from typing import Any

import boto3
from moto import mock_aws

from adapters.menu_repository import MenuRepository

_TABLE_NAME = "test-mobile-order-table"


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
    "sizeDelta": {"S": 0, "M": 50},
    "allowHot": True,
    "allowIced": True,
    "available": True,
}


@mock_aws
def test_list_products_returns_all_menu_items() -> None:
    _create_table()
    _put_product(**_LATTE)
    _put_product(**_TEA)

    repo = MenuRepository(_TABLE_NAME)
    products = repo.list_products()

    assert {p.product_id for p in products} == {"prod-001", "prod-014"}


@mock_aws
def test_get_product_returns_product_when_exists() -> None:
    _create_table()
    _put_product(**_LATTE)

    repo = MenuRepository(_TABLE_NAME)
    product = repo.get_product("prod-001")

    assert product is not None
    assert product.name == "カフェラテ"
    assert product.size_delta == {"S": 0, "M": 50, "L": 100}


@mock_aws
def test_get_product_returns_none_when_missing() -> None:
    _create_table()

    repo = MenuRepository(_TABLE_NAME)
    product = repo.get_product("does-not-exist")

    assert product is None
