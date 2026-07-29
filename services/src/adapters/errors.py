"""共通エラーエンベロープ(docs/architecture.md §5.1)。

全HTTP Lambda共通で {"error": {"code", "message", "requestId"}} 形式を返す。
"""

from __future__ import annotations

from typing import Literal, TypedDict

ErrorCode = Literal[
    "VALIDATION_ERROR",
    "UNAUTHORIZED",
    "NOT_FOUND",
    "CONFLICT",
    "TOO_MANY_REQUESTS",
    "INTERNAL",
]

_STATUS_BY_CODE: dict[ErrorCode, int] = {
    "VALIDATION_ERROR": 400,
    "UNAUTHORIZED": 401,
    "NOT_FOUND": 404,
    "CONFLICT": 409,
    "TOO_MANY_REQUESTS": 429,
    "INTERNAL": 500,
}


class _ErrorDetail(TypedDict):
    code: ErrorCode
    message: str
    requestId: str


class ErrorBody(TypedDict):
    error: _ErrorDetail


def build_error(code: ErrorCode, message: str, request_id: str) -> tuple[int, ErrorBody]:
    """エラーコードからHTTPステータスとエラーエンベロープを組み立てる。"""
    body: ErrorBody = {
        "error": {"code": code, "message": message, "requestId": request_id}
    }
    return _STATUS_BY_CODE[code], body


def not_found(message: str, request_id: str) -> tuple[int, ErrorBody]:
    return build_error("NOT_FOUND", message, request_id)
