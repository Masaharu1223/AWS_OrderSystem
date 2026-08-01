import boto3
from moto import mock_aws

from adapters.cart_repository import CartRepository
from domain.cart.models import CartItem
from domain.menu.models import Variant

_TABLE_NAME = "test-mobile-order-table"
_SESSION_ID = "sess-abc"


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


def _item(**overrides: object) -> CartItem:
    kwargs: dict[str, object] = {
        "productId": "prod-001",
        "category": "espresso",
        "name": "カフェラテ",
        "variant": Variant(temperature="iced", size="M"),
        "quantity": 2,
        "unitPrice": 500,
        "addedAt": "2026-08-01T10:00:00Z",
        "updatedAt": "2026-08-01T10:00:00Z",
        "expiresAt": 1785886400,
    }
    kwargs.update(overrides)
    return CartItem(**kwargs)


@mock_aws
def test_put_item_then_list_items_round_trips() -> None:
    _create_table()
    repo = CartRepository(_TABLE_NAME)

    repo.put_item(_SESSION_ID, _item())
    items = repo.list_items(_SESSION_ID)

    assert len(items) == 1
    assert items[0].product_id == "prod-001"
    assert items[0].quantity == 2
    assert items[0].item_id == "prod-001#iced#M"


@mock_aws
def test_put_item_does_not_persist_computed_fields() -> None:
    _create_table()
    repo = CartRepository(_TABLE_NAME)
    repo.put_item(_SESSION_ID, _item())

    table = boto3.resource("dynamodb").Table(_TABLE_NAME)
    raw = table.get_item(Key={"PK": "CART#sess-abc", "SK": "ITEM#prod-001#iced#M"})["Item"]

    assert "itemId" not in raw
    assert "lineTotal" not in raw


@mock_aws
def test_same_product_different_variant_are_separate_items() -> None:
    _create_table()
    repo = CartRepository(_TABLE_NAME)

    repo.put_item(_SESSION_ID, _item(variant=Variant(temperature="hot", size="S")))
    repo.put_item(_SESSION_ID, _item(variant=Variant(temperature="iced", size="M")))

    items = repo.list_items(_SESSION_ID)
    assert {i.item_id for i in items} == {"prod-001#hot#S", "prod-001#iced#M"}


@mock_aws
def test_list_items_returns_empty_list_for_unknown_session() -> None:
    _create_table()
    repo = CartRepository(_TABLE_NAME)

    assert repo.list_items("sess-never-used") == []


@mock_aws
def test_get_item_returns_none_when_missing() -> None:
    _create_table()
    repo = CartRepository(_TABLE_NAME)

    result = repo.get_item(_SESSION_ID, "prod-001", Variant(temperature="hot", size="S"))
    assert result is None


@mock_aws
def test_get_item_returns_existing_item() -> None:
    _create_table()
    repo = CartRepository(_TABLE_NAME)
    repo.put_item(_SESSION_ID, _item())

    result = repo.get_item(_SESSION_ID, "prod-001", Variant(temperature="iced", size="M"))
    assert result is not None
    assert result.quantity == 2


@mock_aws
def test_update_quantity_updates_existing_item() -> None:
    _create_table()
    repo = CartRepository(_TABLE_NAME)
    repo.put_item(_SESSION_ID, _item())

    updated = repo.update_quantity(
        _SESSION_ID,
        "prod-001",
        Variant(temperature="iced", size="M"),
        quantity=5,
        updated_at="2026-08-01T12:00:00Z",
        expires_at=1785900000,
    )

    assert updated is not None
    assert updated.quantity == 5
    assert updated.updated_at == "2026-08-01T12:00:00Z"
    assert updated.expires_at == 1785900000
    # 更新対象外のフィールドは保持される
    assert updated.added_at == "2026-08-01T10:00:00Z"
    assert updated.unit_price == 500


@mock_aws
def test_update_quantity_returns_none_when_item_missing() -> None:
    _create_table()
    repo = CartRepository(_TABLE_NAME)

    result = repo.update_quantity(
        _SESSION_ID,
        "prod-001",
        Variant(temperature="hot", size="S"),
        quantity=3,
        updated_at="2026-08-01T12:00:00Z",
        expires_at=1785900000,
    )
    assert result is None


@mock_aws
def test_update_quantity_does_not_create_new_item() -> None:
    _create_table()
    repo = CartRepository(_TABLE_NAME)

    repo.update_quantity(
        _SESSION_ID,
        "prod-001",
        Variant(temperature="hot", size="S"),
        quantity=3,
        updated_at="2026-08-01T12:00:00Z",
        expires_at=1785900000,
    )

    assert repo.list_items(_SESSION_ID) == []


@mock_aws
def test_delete_item_removes_and_returns_it() -> None:
    _create_table()
    repo = CartRepository(_TABLE_NAME)
    repo.put_item(_SESSION_ID, _item())

    deleted = repo.delete_item(_SESSION_ID, "prod-001", Variant(temperature="iced", size="M"))

    assert deleted is not None
    assert deleted.product_id == "prod-001"
    assert repo.list_items(_SESSION_ID) == []


@mock_aws
def test_delete_item_returns_none_when_missing() -> None:
    _create_table()
    repo = CartRepository(_TABLE_NAME)

    result = repo.delete_item(_SESSION_ID, "prod-001", Variant(temperature="hot", size="S"))
    assert result is None
