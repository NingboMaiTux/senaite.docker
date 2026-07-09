"""轻量模板引擎（自研，零依赖，避免引入 Jinja2）。

语法：
    {{ variable }}            变量替换
    {{#condition}}...{{/condition}}   条件块（变量为真时保留内容）
    {{^condition}}...{{/condition}}   反条件块（变量为假时保留内容）

用于渲染 Addon 固定骨架模板（.tmpl 文件）。
"""

from __future__ import annotations

import os
import re

_VAR_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_COND_RE = re.compile(r"\{\{#(\w+)\}\}(.*?)\{\{/\1\}\}", re.DOTALL)
_NOTCOND_RE = re.compile(r"\{\{\^(\w+)\}\}(.*?)\{\{/\1\}\}", re.DOTALL)


def render_string(template: str, variables: dict) -> str:
    """渲染模板字符串。条件块先处理（可含变量），再替换变量。"""

    def cond_sub(m: "re.Match") -> str:
        key, inner = m.group(1), m.group(2)
        return inner if variables.get(key) else ""

    def notcond_sub(m: "re.Match") -> str:
        key, inner = m.group(1), m.group(2)
        return "" if variables.get(key) else inner

    text = _COND_RE.sub(cond_sub, template)
    text = _NOTCOND_RE.sub(notcond_sub, text)

    def var_sub(m: "re.Match") -> str:
        return str(variables.get(m.group(1), ""))

    return _VAR_RE.sub(var_sub, text)


class TemplateEngine:
    """从模板目录加载 .tmpl 文件并渲染（带缓存）。"""

    def __init__(self, template_dir: str) -> None:
        self._dir = template_dir
        self._cache: dict[str, str] = {}

    def load(self, name: str) -> str:
        if name not in self._cache:
            path = os.path.join(self._dir, name)
            with open(path, "r", encoding="utf-8") as handle:
                self._cache[name] = handle.read()
        return self._cache[name]

    def render(self, name: str, variables: dict) -> str:
        return render_string(self.load(name), variables)
