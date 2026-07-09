"""极简路由：method + 路径模板 → handler。

路径模板支持 {name} 占位符，如 /api/companies/{code}。
匹配后把占位符解析成 dict 传给 handler。保持零依赖，不引入框架。
"""

from __future__ import annotations

import re
from typing import Callable, Optional

# handler(params: dict, query: dict, body: dict|None) -> Result
Handler = Callable[..., object]


class Route:
    __slots__ = ("method", "regex", "param_names", "handler")

    def __init__(self, method: str, template: str, handler: Handler) -> None:
        self.method = method.upper()
        self.handler = handler
        self.param_names: list[str] = re.findall(r"\{(\w+)\}", template)
        # /api/sites/{code} → ^/api/sites/(?P<code>[^/]+)$
        pattern = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", template)
        self.regex = re.compile("^" + pattern + "$")


class Router:
    def __init__(self) -> None:
        self._routes: list[Route] = []

    def add(self, method: str, template: str, handler: Handler) -> None:
        self._routes.append(Route(method, template, handler))

    def get(self, template: str, handler: Handler) -> None:
        self.add("GET", template, handler)

    def post(self, template: str, handler: Handler) -> None:
        self.add("POST", template, handler)

    def put(self, template: str, handler: Handler) -> None:
        self.add("PUT", template, handler)

    def delete(self, template: str, handler: Handler) -> None:
        self.add("DELETE", template, handler)

    def match(self, method: str, path: str) -> Optional[tuple[Handler, dict]]:
        """返回 (handler, path_params) 或 None（未匹配）。"""
        for route in self._routes:
            if route.method != method.upper():
                continue
            m = route.regex.match(path)
            if m:
                return route.handler, m.groupdict()
        return None

    def path_exists(self, path: str) -> bool:
        """路径存在但方法不符时用于返回 405 而非 404。"""
        return any(r.regex.match(path) for r in self._routes)
