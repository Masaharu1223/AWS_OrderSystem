"""store-fn: 店員向けゾーン一覧・状態更新・受渡検知のHTTP Lambdaハンドラ(外殻。薄く保つ)。

ゾーン一覧・状態更新の2ルートはCognito JWTオーソライザーがAPI Gateway側で認証を済ませてから
このLambdaを呼ぶため、ハンドラ内で認証チェックは行わない(cart-fn/order-fnと同じ考え方)。
受渡検知エンドポイントだけは別認証(x-api-key、adapters/handover_auth.py)のため、
ここでハンドラが自分でチェックする(docs/architecture.md §7.5)。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from aws_lambda_powertools import Logger
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic.alias_generators import to_camel

from adapters.errors import build_error, not_found
from adapters.handover_auth import HandoverAuthenticator
from adapters.http import json_response
from adapters.order_repository import LineTransitionConflictError, OrderRepository
from config import get_config, get_handover_api_key_parameter_name
from domain.fulfillment.models import LineStatus, Zone
from domain.fulfillment.service import is_allowed_line_status_transition
from domain.store.models import LineHandoverResponse, LineStatusUpdateResponse
from domain.store.service import build_zone_lines_response

logger = Logger()

# コールドスタート時に1回だけ生成し、ウォーム実行間で使い回す(boto3リソースの再生成を避ける)。
_order_repository = OrderRepository(get_config().table_name)
_handover_authenticator = HandoverAuthenticator(get_handover_api_key_parameter_name())


class _LineStatusUpdateInput(BaseModel):
    """PATCH /orders/{orderId}/lines/{lineId}/status のリクエストボディ。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    from_status: LineStatus
    to_status: LineStatus


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", "")
    route_key = event.get("routeKey", "")

    try:
        if route_key == "GET /stores/{storeId}/zones/{zone}/lines":
            return _handle_get_zone_lines(event)

        if route_key == "PATCH /orders/{orderId}/lines/{lineId}/status":
            return _handle_update_line_status(event, request_id)

        if route_key == "PATCH /orders/{orderId}/lines/{lineId}/handover":
            return _handle_handover_line(event, request_id)

        status, body = not_found("route not found", request_id)
        return json_response(status, body)

    except (ClientError, BotoCoreError, ValidationError):
        # DynamoDBの一時エラーや契約外データによる例外を、共通エラーエンベロープに変換する
        # (docs/architecture.md §5.1)。クライアント入力由来のValidationErrorは各ハンドラ内で
        # 個別に捕捉して400へ変換しているため、ここに届くのはDB由来のものだけ。
        logger.exception("store-fn: unhandled error", extra={"routeKey": route_key})
        status, body = build_error("INTERNAL", "internal server error", request_id)
        return json_response(status, body)


def _handle_get_zone_lines(event: dict[str, Any]) -> dict[str, Any]:
    path_params = event.get("pathParameters") or {}
    store_id = path_params.get("storeId", "")
    # ゾーン名の実行時バリデーションはしない(計画の決定#8): 間違った値でQueryしても
    # 「該当なし=空の一覧」が返るだけで実害が無いため。
    zone = cast(Zone, path_params.get("zone", ""))

    lines = _order_repository.list_zone_lines(store_id, zone)
    response = build_zone_lines_response(lines)
    return json_response(200, response.model_dump(by_alias=True))


def _handle_update_line_status(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    path_params = event.get("pathParameters") or {}
    order_id = path_params.get("orderId", "")
    line_id = path_params.get("lineId", "")

    try:
        input_ = _LineStatusUpdateInput.model_validate_json(event.get("body") or "{}")
    except ValidationError as exc:
        status, body = build_error("VALIDATION_ERROR", str(exc), request_id)
        return json_response(status, body)

    if not is_allowed_line_status_transition(input_.from_status, input_.to_status):
        status, body = build_error(
            "CONFLICT",
            f"{input_.from_status} -> {input_.to_status} is not an allowed transition",
            request_id,
        )
        return json_response(status, body)

    now = datetime.now(UTC)
    try:
        line = _order_repository.update_line_status(
            order_id, line_id, input_.from_status, input_.to_status, now
        )
    except LineTransitionConflictError:
        status, body = build_error("CONFLICT", "line is not in the expected status", request_id)
        return json_response(status, body)

    response = LineStatusUpdateResponse(
        order_id=line.order_id,
        line_id=line.line_id,
        zone=line.zone,
        status=line.status,
        prepared_at=line.prepared_at,
        ready_at=line.ready_at,
    )
    return json_response(200, response.model_dump(by_alias=True))


def _handle_handover_line(event: dict[str, Any], request_id: str) -> dict[str, Any]:
    if not _handover_authenticator.verify(_get_header(event, "x-api-key")):
        status, body = build_error("UNAUTHORIZED", "invalid or missing x-api-key", request_id)
        return json_response(status, body)

    path_params = event.get("pathParameters") or {}
    order_id = path_params.get("orderId", "")
    line_id = path_params.get("lineId", "")
    now = datetime.now(UTC)

    try:
        line = _order_repository.handover_line(order_id, line_id, now)
    except LineTransitionConflictError:
        status, body = build_error("CONFLICT", "line is not READY", request_id)
        return json_response(status, body)

    response = LineHandoverResponse(
        order_id=line.order_id,
        line_id=line.line_id,
        zone=line.zone,
        status=line.status,
        handed_over_at=cast(str, line.handed_over_at),
    )
    return json_response(200, response.model_dump(by_alias=True))


def _get_header(event: dict[str, Any], name: str) -> str | None:
    """大文字小文字を区別せずヘッダを取得する(handlers/order.pyと同じパターン)。"""
    headers = event.get("headers") or {}
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return str(value)
    return None
