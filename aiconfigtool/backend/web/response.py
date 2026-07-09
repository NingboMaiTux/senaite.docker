"""统一响应格式（技术设计文档 7.2）。

成功: {"success": true,  "data": ..., "error": null, "meta": {...}}
失败: {"success": false, "data": null, "error": {code,message,...}, "meta": {...}}
"""

from __future__ import annotations

import time
from typing import Any, Optional

from shared.result import Result, ResultError


def _meta(request_id: str, started_at: float) -> dict:
    return {
        "request_id": request_id,
        "duration_ms": int((time.monotonic() - started_at) * 1000),
    }


def success_body(data: Any, request_id: str, started_at: float) -> dict:
    return {
        "success": True,
        "data": data,
        "error": None,
        "meta": _meta(request_id, started_at),
    }


def error_body(err: ResultError, request_id: str, started_at: float) -> dict:
    return {
        "success": False,
        "data": None,
        "error": {
            "code": err.code,
            "message": err.message,
            "details": err.details or {},
            "suggestion": err.suggestion,
        },
        "meta": _meta(request_id, started_at),
    }


def body_from_result(
    result: Result, request_id: str, started_at: float
) -> dict:
    """把服务层 Result 直接转成响应体。"""
    if result.is_success():
        return success_body(result.value, request_id, started_at)
    err: Optional[ResultError] = result.error
    assert err is not None
    return error_body(err, request_id, started_at)
