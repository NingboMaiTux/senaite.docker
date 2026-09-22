# -*- coding: utf-8 -*-
"""模板解析脚本执行器（`.py` 通道，进程内运行，不依赖 node）

★ 为什么需要它：Empower 这类 PDF 报告的 Peaks 表是"逐格文本 + 坐标"画的，
列归属（RT / Area / %Area …）必须拿到坐标才能算。原模板脚本通道只支持 `.js`
（node 子进程）且只喂版式文本；本模块提供等价的 **Python 通道**。

脚本契约（与 `.js` 的 `parse(text)` 平行）::

    def parse(payload):        # payload = pdf_text.extract_pdf() 的产物
        return {...}           # 返回值会被 JSON 序列化

只依赖标准库与 `json`，便于单测按路径直接加载。
"""

import json
import os
import tempfile

try:  # Python 2
    text_type = unicode
except NameError:  # Python 3
    text_type = str

#: 允许上传的解析脚本后缀（与 content/instrumentparsingtemplate 的 invariant 一致）
SCRIPT_SUFFIXES = (".js", ".py")


def _ensure_text(value):
    if value is None:
        return u""
    if not isinstance(value, (bytes, text_type)):
        # 异常对象等：直接取字符串表示（异常里通常没有 strip()）
        try:
            value = u"%s" % (value,)
        except Exception:
            return u""
    if isinstance(value, text_type):
        return value.strip()
    try:
        return value.strip().decode("utf-8")
    except Exception:
        try:
            return value.strip().decode("gbk")
        except Exception:
            return value.strip().decode("latin1", "replace")


def load_py_module(name, path):
    """按路径加载 Python 模块（py3 用 importlib，py2 用 imp）"""
    try:
        import importlib.util
    except ImportError:
        import imp  # py2
        return imp.load_source(name, path)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_py_parser(py_source, payload):
    """执行 Python 解析脚本，返回 **JSON 字符串**（与 `_run_js_parser` 同约定）

    执行失败时返回 `[PY ...]` 开头的提示串，调用方 `json.loads` 会失败并
    把它当作错误消息透出（保持与 JS 通道一致的错误语义）。
    """
    if not py_source:
        return u"[PY script file missing or empty]"

    source = py_source
    if isinstance(source, text_type):
        source = source.encode("utf-8")
    elif not isinstance(source, bytes):
        source = _ensure_text(source).encode("utf-8")

    # ★ py2 下脚本文件里的中文必须带编码声明，否则直接 SyntaxError；
    # 上传的脚本常常忘了写，这里在缺声明且含非 ASCII 时自动补一行。
    if b"coding" not in source[:256]:
        try:
            source.decode("ascii")
        except UnicodeDecodeError:
            source = b"# -*- coding: utf-8 -*-\n" + source

    tmp = tempfile.NamedTemporaryFile(
        prefix="senaite_py_parser_", suffix=".py", delete=False)
    module_name = "senaite_py_parser_%s" % os.path.basename(tmp.name).replace(
        ".", "_")
    try:
        tmp.write(source)
        tmp.close()
        module = load_py_module(module_name, tmp.name)
        func = getattr(module, "parse", None)
        if not callable(func):
            return u"[PY script error] no callable parse(payload) defined"
        try:
            result = func(payload)
        except Exception as exc:
            return u"[PY parse error] {}".format(_ensure_text(exc))
        if isinstance(result, (dict, list, tuple)):
            return _ensure_text(json.dumps(result, ensure_ascii=False))
        return _ensure_text(result)
    except Exception as exc:
        return u"[PY script error] {}".format(_ensure_text(exc))
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


def template_script_kind(template):
    """模板解析脚本类型：`py` / `js` / None（未上传或后缀不支持）"""
    if not template:
        return None
    script_file = getattr(template, "script_file", None)
    filename = _ensure_text(getattr(script_file, "filename", "")) \
        if script_file else u""
    name = filename.lower()
    for suffix in SCRIPT_SUFFIXES:
        if name.endswith(suffix):
            return suffix.lstrip(".")
    return None
