"""Result 模式：统一的成功/失败返回，避免异常在服务层泛滥。

设计文档 6.1 将 Result 列为标准模式：成功携带 value，失败携带
message + code + suggestion（可选），供上层直接映射到 API 响应。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, Optional, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class ResultError:
    """失败明细，字段与 API 错误对象对齐（见 web/response.py）。"""

    code: str
    message: str
    suggestion: str = ""
    details: Optional[dict] = None


class Result(Generic[T]):
    """成功或失败二选一的容器。

    用法：
        return Result.success(company)
        return Result.failure("公司不存在", code=errors.NOT_FOUND)
    """

    __slots__ = ("_value", "_error")

    def __init__(self, value: Optional[T], error: Optional[ResultError]) -> None:
        self._value = value
        self._error = error

    # ── 构造 ──
    @classmethod
    def success(cls, value: T) -> "Result[T]":
        return cls(value, None)

    @classmethod
    def failure(
        cls,
        message: str,
        code: str = "INTERNAL_ERROR",
        suggestion: str = "",
        details: Optional[dict] = None,
    ) -> "Result[Any]":
        return cls(None, ResultError(code, message, suggestion, details))

    # ── 查询 ──
    def is_success(self) -> bool:
        return self._error is None

    def is_failure(self) -> bool:
        return self._error is not None

    @property
    def value(self) -> Optional[T]:
        return self._value

    @property
    def error(self) -> Optional[ResultError]:
        return self._error
