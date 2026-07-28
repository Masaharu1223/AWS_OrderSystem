"""商品メニューのシード投入(冪等)。

テーブルの物理名はCloudFormationスタックから動的解決するため、
CDK側にCfnOutputを追加する等のインフラ変更は不要。

使い方(servicesディレクトリから実行):
    python scripts/seed_menu.py --stage dev
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import boto3

# services/src をimportパスに追加する(このスクリプトはpytestのpythonpath設定の対象外のため)。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from domain.menu.models import (  # noqa: E402
    MENU_PARTITION_KEY,
    PRODUCT_SORT_KEY_PREFIX,
    Product,
)

STACK_NAME_TEMPLATE = "MobileOrder-{stage}-Stateful"

PRODUCTS: list[dict[str, Any]] = [
    {
        "productId": "prod-001",
        "category": "espresso",
        "name": "カフェラテ",
        "basePrice": 450,
        "sizeDelta": {"S": 0, "M": 50, "L": 100},
        "allowHot": True,
        "allowIced": True,
        "available": True,
        "displayOrder": 1,
    },
    {
        "productId": "prod-002",
        "category": "espresso",
        "name": "カプチーノ",
        "basePrice": 430,
        "sizeDelta": {"S": 0, "M": 50, "L": 100},
        "allowHot": True,
        "allowIced": False,
        "available": True,
        "displayOrder": 2,
    },
    {
        "productId": "prod-003",
        "category": "espresso",
        "name": "アメリカーノ",
        "basePrice": 380,
        "sizeDelta": {"S": 0, "M": 50, "L": 100},
        "allowHot": True,
        "allowIced": True,
        "available": True,
        "displayOrder": 3,
    },
    {
        "productId": "prod-014",
        "category": "tea",
        "name": "紅茶",
        "basePrice": 380,
        "sizeDelta": {"S": 0, "M": 50},
        "allowHot": True,
        "allowIced": True,
        "available": True,
        "displayOrder": 1,
    },
    {
        "productId": "prod-015",
        "category": "tea",
        "name": "ジャスミンティー",
        "basePrice": 380,
        "sizeDelta": {"S": 0, "M": 50},
        "allowHot": True,
        "allowIced": True,
        "available": True,
        "displayOrder": 2,
    },
    {
        "productId": "prod-020",
        "category": "frappe",
        "name": "キャラメルフラペチーノ",
        "basePrice": 520,
        "sizeDelta": {"S": 0, "M": 80},
        "allowHot": False,
        "allowIced": True,
        "available": True,
        "displayOrder": 1,
    },
]


def resolve_table_name(stage: str) -> str:
    stack_name = STACK_NAME_TEMPLATE.format(stage=stage)
    cfn = boto3.client("cloudformation")
    resources = cfn.describe_stack_resources(StackName=stack_name)["StackResources"]
    tables = [r for r in resources if r["ResourceType"] == "AWS::DynamoDB::Table"]
    if len(tables) != 1:
        raise RuntimeError(
            f"expected exactly 1 AWS::DynamoDB::Table in stack {stack_name}, "
            f"found {len(tables)}"
        )
    physical_id = tables[0]["PhysicalResourceId"]
    if not isinstance(physical_id, str):
        raise RuntimeError(f"unexpected PhysicalResourceId type: {type(physical_id)!r}")
    return physical_id


def seed(table_name: str) -> None:
    table = boto3.resource("dynamodb").Table(table_name)
    for raw in PRODUCTS:
        # 事前にドメインモデルでバリデーションし、不正なシードデータを投入前に検出する。
        product = Product(**raw)
        item = {
            "PK": MENU_PARTITION_KEY,
            "SK": f"{PRODUCT_SORT_KEY_PREFIX}{product.product_id}",
            **product.model_dump(by_alias=True),
        }
        table.put_item(Item=item)
        print(f"seeded: {product.product_id} ({product.category})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed menu products into MobileOrderTable")
    parser.add_argument("--stage", choices=["dev", "prod"], required=True)
    args = parser.parse_args()

    table_name = resolve_table_name(args.stage)
    print(f"target table: {table_name}")
    seed(table_name)


if __name__ == "__main__":
    main()
