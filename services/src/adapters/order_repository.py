"""DynamoDB MobileOrderTable への注文(Order/OrderLine)アクセス。

order-fn(注文確定・キャンセル)とstatus-fn(ポーリング)の両方が使う。同じORDER#<orderId>配下
(META/LINE)・ZONESEQ#/ORDERNUM#/IDEMPOTENCY#/ZONESTAT#アイテムを読み書きするため、
menu-fn/cart-fnのように機能ごとにリポジトリを分ける理由が無い(docs/architecture.md §6.1)。

キー設計:
  注文ヘッダ(META)   PK=ORDER#<orderId>              SK=META
  明細(LINE)         PK=ORDER#<orderId>              SK=LINE#<lineId>
  ゾーン採番カウンタ  PK=ZONESEQ#<storeId>#<zone>     SK=COUNTER
  注文番号カウンタ    PK=ORDERNUM#<storeId>#<date>    SK=COUNTER
  ゾーン統計          PK=ZONESTAT#<storeId>#<zone>    SK=STAT
  冪等キー            PK=IDEMPOTENCY#<key>            SK=IDEMPOTENCY#<key>(PK/SK同値)
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError

from domain.cart.models import CART_PARTITION_KEY_PREFIX
from domain.fulfillment.models import Zone
from domain.order.models import (
    ORDER_LINE_SORT_KEY_PREFIX,
    ORDER_META_SORT_KEY,
    ORDER_PARTITION_KEY_PREFIX,
    Order,
    OrderLine,
)

# IDEMPOTENCYアイテムのTTL。計画の小さな決定#2: カート明細と同じ24時間を踏襲する。
_IDEMPOTENCY_TTL = timedelta(hours=24)

# GSI2("ゾーン別製造キュー")のインデックス名。docs/architecture.md §6.3。
_GSI2_INDEX_NAME = "GSI2"

_serializer = TypeSerializer()
_deserializer = TypeDeserializer()


@dataclass(frozen=True)
class IdempotencyRecord:
    """`IDEMPOTENCY#<key>`アイテムの中身。get_idempotency_record()の戻り値。"""

    order_id: str
    session_id: str


class IdempotencyConflict(Exception):
    """create_order()のTransactWriteItemsが冪等キー衝突で中断したときに送出する。

    ALL_OLDから取得した既存の注文の`orderId`/`sessionId`を保持する。呼び出し側
    (handlers/order.py)がsessionIdを照合し、一致すれば`get_order()`で既存注文を返し、
    不一致なら409にする(get_idempotency_record()の事前チェックと同じ判定をここでも使う)。
    """

    def __init__(self, order_id: str, session_id: str) -> None:
        super().__init__(f"idempotency conflict: order {order_id!r} already exists")
        self.order_id = order_id
        self.session_id = session_id


class OrderNotFoundError(Exception):
    """cancel_order()が存在しないorderIdを指定されたときに送出する(呼び出し側で404に変換)。"""

    def __init__(self, order_id: str) -> None:
        super().__init__(f"order {order_id!r} not found")
        self.order_id = order_id


class OrderNotCancellableError(Exception):
    """cancel_order()で1明細でもWAITING以外だった場合に送出する(呼び出し側で409に変換)。"""

    def __init__(self, order_id: str) -> None:
        super().__init__(f"order {order_id!r} is not cancellable (not all lines WAITING)")
        self.order_id = order_id


class OrderRepository:
    def __init__(self, table_name: str) -> None:
        self._table_name = table_name
        self._table = boto3.resource("dynamodb").Table(table_name)
        # TransactWriteItemsはTableリソースには無く低レベルclientのみが持つAPIのため、
        # create_order/cancel_orderだけこちらを使う(値は手動でAttributeValue形式に変換する)。
        # `self._table.meta.client`(resourceから借用したclient)ではなく独立したclientを使う:
        # resource用に登録されたアイテム変換ハンドラが低レベル専用のTransactWriteItemsにも
        # 干渉してしまい、実AWSでは問題無いがmotoでは`TypeError: unhashable type: 'dict'`を
        # 誤って返す現象を確認したため。
        self._client = boto3.client("dynamodb")

    def get_idempotency_record(self, key: str) -> IdempotencyRecord | None:
        """`Idempotency-Key`ヘッダの事前チェック用(architecture.md §7.3 ステップ0)。

        書き込み直後の別リクエストでも確実に見えるよう強整合読み(ConsistentRead)で読む。
        """
        pk = _idempotency_key(key)
        response = self._table.get_item(Key={"PK": pk, "SK": pk}, ConsistentRead=True)
        raw_item = response.get("Item")
        if raw_item is None:
            return None
        item = cast(dict[str, Any], raw_item)
        return IdempotencyRecord(order_id=str(item["orderId"]), session_id=str(item["sessionId"]))

    def reserve_zone_sequence(self, store_id: str, zone: Zone, count: int) -> int:
        """ゾーン別カウンタを`count`件ぶん予約し、確保したブロックの終端値を返す。

        戻り値`v`から`[v-count+1, v]`が今回の予約ブロック(architecture.md §7.3 ステップ2)。
        """
        response = self._table.update_item(
            Key={"PK": f"ZONESEQ#{store_id}#{zone}", "SK": "COUNTER"},
            UpdateExpression="ADD seq :count",
            ExpressionAttributeValues={":count": count},
            ReturnValues="UPDATED_NEW",
        )
        return int(cast(Any, response["Attributes"]["seq"]))

    def reserve_order_number(self, store_id: str, date: str) -> int:
        """店舗・日付単位の注文番号カウンタを1つ進め、新しい注文番号を返す(ステップ3)。

        `date`は`yyyy-mm-dd`形式(呼び出し側でnowから整形して渡す)。
        """
        response = self._table.update_item(
            Key={"PK": f"ORDERNUM#{store_id}#{date}", "SK": "COUNTER"},
            UpdateExpression="ADD seq :one",
            ExpressionAttributeValues={":one": 1},
            ReturnValues="UPDATED_NEW",
        )
        return int(cast(Any, response["Attributes"]["seq"]))

    def create_order(
        self,
        order: Order,
        idempotency_key: str,
        session_id: str,
        cart_keys: Sequence[str],
        now: datetime,
    ) -> Order:
        """注文を1回のTransactWriteItemsで確定する(architecture.md §7.3 ステップ4)。

        `order`はdomain.order.service.build_order()が組み立てた完成形(zone/queueSeq確定済み)。
        `cart_keys`は削除するカート明細のSK一覧(例: `ITEM#prod-001#hot#L`)。同一トランザクションで
        カートも削除することで「注文成立+カート残存」による重複再注文を防ぐ(§7.3)。

        冪等キーが衝突した場合(同時リクエストがステップ0の事前チェックをすり抜けた稀なレース)は
        IdempotencyConflictを送出する。成功時は書き込んだ`order`をそのまま返す
        (直後に読み直す追加のGetItemは行わない。同じデータのため不要)。
        """
        idempotency_pk = _idempotency_key(idempotency_key)
        expires_at = int((now + _IDEMPOTENCY_TTL).timestamp())
        cart_pk = f"{CART_PARTITION_KEY_PREFIX}{session_id}"

        transact_items: list[dict[str, Any]] = [
            {
                "Put": {
                    "TableName": self._table_name,
                    "Item": _serialize(
                        {
                            "PK": idempotency_pk,
                            "SK": idempotency_pk,
                            "orderId": order.order_id,
                            "sessionId": session_id,
                            "expiresAt": expires_at,
                        }
                    ),
                    "ConditionExpression": "attribute_not_exists(PK)",
                    "ReturnValuesOnConditionCheckFailure": "ALL_OLD",
                }
            },
            {"Put": {"TableName": self._table_name, "Item": _serialize(_build_meta_item(order))}},
        ]
        for line in order.lines:
            line_item = _build_line_item(order.order_id, order.store_id, line)
            transact_items.append(
                {"Put": {"TableName": self._table_name, "Item": _serialize(line_item)}}
            )
        for sort_key in cart_keys:
            transact_items.append(
                {
                    "Delete": {
                        "TableName": self._table_name,
                        "Key": _serialize({"PK": cart_pk, "SK": sort_key}),
                    }
                }
            )

        try:
            self._client.transact_write_items(TransactItems=cast(Any, transact_items))
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "TransactionCanceledException":
                conflict = _extract_idempotency_conflict(exc)
                if conflict is not None:
                    raise IdempotencyConflict(*conflict) from exc
            raise

        return order

    def get_order(self, order_id: str) -> Order | None:
        """注文をMETA+LINE群から組み立てて返す。存在しなければNone。

        `status`/`totalPrice`はOrderの`@computed_field`が明細から都度導出するため、
        ここではMETAの`derivedStatus`/`totalPrice`は読まない(§6.2、直接書き込み対象ではないため)。
        """
        pk = _order_partition_key(order_id)
        meta_response = self._table.get_item(Key={"PK": pk, "SK": ORDER_META_SORT_KEY})
        raw_meta_item = meta_response.get("Item")
        if raw_meta_item is None:
            return None
        meta_item = cast(dict[str, Any], raw_meta_item)

        return Order(
            order_id=order_id,
            order_number=int(meta_item["orderNumber"]),
            store_id=str(meta_item["storeId"]),
            lines=self._list_lines(order_id),
            created_at=str(meta_item["createdAt"]),
        )

    def cancel_order(self, order_id: str, now: datetime) -> Order:
        """全明細WAITINGの場合のみキャンセルする(requirements.md §4.5)。

        1明細でもWAITING以外ならTransactWriteItems全体が失敗し、OrderNotCancellableErrorを送出する
        (ConditionExpressionで「全明細WAITINGかどうか」を原子的に強制する、architecture.md §7.3)。
        """
        order = self.get_order(order_id)
        if order is None:
            raise OrderNotFoundError(order_id)

        pk = _order_partition_key(order_id)
        timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        transact_items: list[dict[str, Any]] = [
            {
                "Update": {
                    "TableName": self._table_name,
                    "Key": _serialize(
                        {"PK": pk, "SK": f"{ORDER_LINE_SORT_KEY_PREFIX}{line.line_id}"}
                    ),
                    "UpdateExpression": (
                        "SET #status = :cancelled, updatedAt = :now REMOVE GSI2PK, GSI2SK"
                    ),
                    "ConditionExpression": "#status = :waiting",
                    "ExpressionAttributeNames": {"#status": "status"},
                    "ExpressionAttributeValues": _serialize(
                        {":cancelled": "CANCELLED", ":waiting": "WAITING", ":now": timestamp}
                    ),
                }
            }
            for line in order.lines
        ]
        transact_items.append(
            {
                "Update": {
                    "TableName": self._table_name,
                    "Key": _serialize({"PK": pk, "SK": ORDER_META_SORT_KEY}),
                    "UpdateExpression": (
                        "SET derivedStatus = :cancelled, updatedAt = :now, GSI1PK = :gsi1pk"
                    ),
                    "ExpressionAttributeValues": _serialize(
                        {
                            ":cancelled": "CANCELLED",
                            ":now": timestamp,
                            ":gsi1pk": f"STORE#{order.store_id}#CANCELLED",
                        }
                    ),
                }
            }
        )

        try:
            self._client.transact_write_items(TransactItems=cast(Any, transact_items))
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "TransactionCanceledException":
                raise OrderNotCancellableError(order_id) from exc
            raise

        cancelled = self.get_order(order_id)
        if cancelled is None:
            raise RuntimeError(f"order {order_id!r} disappeared immediately after cancel")
        return cancelled

    def count_ahead_in_zone(self, store_id: str, zone: Zone, queue_seq: int) -> int:
        """AP-Z2: 自分より前(queueSeqが小さい)の明細数を数える。位置は呼び出し側で`+1`する。"""
        condition = Key("GSI2PK").eq(f"ZONE#{store_id}#{zone}") & Key("GSI2SK").lt(queue_seq)
        total = 0
        exclusive_start_key: dict[str, Any] | None = None
        while True:
            kwargs: dict[str, Any] = {
                "IndexName": _GSI2_INDEX_NAME,
                "KeyConditionExpression": condition,
                "Select": "COUNT",
            }
            if exclusive_start_key is not None:
                kwargs["ExclusiveStartKey"] = exclusive_start_key
            response = self._table.query(**kwargs)
            total += int(response["Count"])
            exclusive_start_key = response.get("LastEvaluatedKey")
            if exclusive_start_key is None:
                break
        return total

    def get_zone_stat(self, store_id: str, zone: Zone) -> tuple[int, int] | None:
        """ZONESTATの`(sumSeconds, sampleCount)`を読む。書き込みはstore-fn(将来スライス)が行う。"""
        response = self._table.get_item(Key={"PK": f"ZONESTAT#{store_id}#{zone}", "SK": "STAT"})
        raw_item = response.get("Item")
        if raw_item is None:
            return None
        item = cast(dict[str, Any], raw_item)
        return int(item["sumSeconds"]), int(item["sampleCount"])

    def _list_lines(self, order_id: str) -> list[OrderLine]:
        items: list[dict[str, Any]] = []
        condition = Key("PK").eq(_order_partition_key(order_id)) & Key("SK").begins_with(
            ORDER_LINE_SORT_KEY_PREFIX
        )
        exclusive_start_key: dict[str, Any] | None = None

        while True:
            if exclusive_start_key is None:
                response = self._table.query(KeyConditionExpression=condition)
            else:
                response = self._table.query(
                    KeyConditionExpression=condition,
                    ExclusiveStartKey=exclusive_start_key,
                )
            items.extend(response.get("Items", []))
            exclusive_start_key = response.get("LastEvaluatedKey")
            if exclusive_start_key is None:
                break

        return [OrderLine(**item) for item in items]


def _order_partition_key(order_id: str) -> str:
    return f"{ORDER_PARTITION_KEY_PREFIX}{order_id}"


def _idempotency_key(key: str) -> str:
    return f"IDEMPOTENCY#{key}"


def _build_meta_item(order: Order) -> dict[str, Any]:
    return {
        "PK": _order_partition_key(order.order_id),
        "SK": ORDER_META_SORT_KEY,
        "orderNumber": order.order_number,
        "storeId": order.store_id,
        "derivedStatus": order.status,
        "totalPrice": order.total_price,
        "lineCount": len(order.lines),
        "createdAt": order.created_at,
        "updatedAt": order.created_at,
        "GSI1PK": f"STORE#{order.store_id}#{order.status}",
        "GSI1SK": order.created_at,
    }


def _build_line_item(order_id: str, store_id: str, line: OrderLine) -> dict[str, Any]:
    item: dict[str, Any] = {
        "PK": _order_partition_key(order_id),
        "SK": f"{ORDER_LINE_SORT_KEY_PREFIX}{line.line_id}",
        **line.model_dump(by_alias=True, exclude={"line_total"}),
    }
    item["GSI2PK"] = f"ZONE#{store_id}#{line.zone}"
    item["GSI2SK"] = line.queue_seq
    return item


def _serialize(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """低レベルclientのTransactWriteItemsが要求するAttributeValue形式に変換する。

    Tableリソース(高レベルAPI)はネイティブなPython型をそのまま受け付けるが、
    TransactWriteItemsはTableリソースには無く低レベルclientにしか無いAPIのため、
    こちらだけ手動でシリアライズが必要になる。
    """
    return {key: _serializer.serialize(value) for key, value in mapping.items()}


def _extract_idempotency_conflict(exc: ClientError) -> tuple[str, str] | None:
    """TransactionCanceledExceptionのCancellationReasonsから既存注文の情報を取り出す。

    IDEMPOTENCY Putは常にtransact_itemsの先頭(index 0)に置いているため、そこだけ見ればよい。
    """
    reasons = exc.response.get("CancellationReasons")
    if not reasons:
        return None
    first = reasons[0]
    if first.get("Code") != "ConditionalCheckFailed":
        return None
    raw_item = first.get("Item")
    if not raw_item:
        return None
    typed_item = cast(dict[str, Any], raw_item)
    item = {key: _deserializer.deserialize(value) for key, value in typed_item.items()}
    return str(item["orderId"]), str(item["sessionId"])
