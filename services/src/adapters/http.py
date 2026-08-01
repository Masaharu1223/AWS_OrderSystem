"""API Gateway (HTTP API) レスポンス形式への変換ヘルパ。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def json_response(status_code: int, body: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def empty_response(status_code: int) -> dict[str, Any]:
    """本文を持たないレスポンス(例: 204 No Content)。

    RFC 7231上、204はメッセージボディを含めてはならない。json_response()は
    常にJSON本文を付与するため204には使えず、この専用ヘルパを用意した。
    """
    return {"statusCode": status_code, "headers": {}, "body": ""}
