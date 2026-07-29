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
