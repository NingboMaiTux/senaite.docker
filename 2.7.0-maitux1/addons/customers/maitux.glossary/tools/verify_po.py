# -*- coding: utf-8 -*-
"""翻译完整性校验（全量，Python 2 / 3 通用）。

三类问题，都是"静默失效"型的 —— 不报错，界面上就是不对：

1. **.po 改了没重编译 .mo**：界面继续用旧译文（改完 .po 必须重跑
   ``tools/compile_mo.py``；容器和宿主都没有 msgfmt，所以是本包自己生成的）。
2. **.po 里有空 msgstr**：该条目等于没翻译。
3. **代码里用了、.po 里却没有的 msgid**：新加的文案永远翻不出来。

本模块既可以直接跑，也被 ``src/maitux/glossary/tests/run_offline.py`` 第 9 组
调用 —— 只维护这一份实现。

用法::

    python tools/verify_po.py          # 人读的输出，有问题退出码 1
"""
import ast
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_ROOT = os.path.abspath(os.path.join(HERE, os.pardir))
PACKAGE_ROOT = os.path.join(ADDON_ROOT, "src", "maitux", "glossary")
LOCALES_ROOT = os.path.join(PACKAGE_ROOT, "locales")
DOMAIN = "maitux.glossary"
LANGUAGES = ("zh_CN",)

try:  # py2
    text_type = unicode  # noqa: F821
    string_types = (str, unicode)  # noqa: F821
except NameError:  # py3
    text_type = str
    string_types = (str,)

#: 这些 msgid 允许"翻出来还是原文"（界面上的字段名/占位符）
IDENTITY_OK = (u"zh", u"en")


def to_unicode(value):
    if value is None:
        return u""
    if isinstance(value, text_type):
        return value
    try:
        return value.decode("utf-8")
    except Exception:
        return value.decode("latin-1", "replace")


def _unquote(line):
    """去掉 .po 行的首尾引号并解开常见转义。"""
    line = line.strip()
    if len(line) >= 2 and line[0] == '"' and line[-1] == '"':
        line = line[1:-1]
    return (line.replace(u'\\"', u'"').replace(u"\\n", u"\n")
                .replace(u"\\t", u"\t").replace(u"\\\\", u"\\"))


def parse_po(path):
    """把 .po 读成 ``{msgid: msgstr}``（跨行 msgid/msgstr 都能拼回来）。"""
    entries = {}
    msgid = None
    msgstr = None
    mode = None
    with io.open(path, encoding="utf-8") as handle:
        content = handle.read()
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(u"msgid_plural"):
            mode = None  # 本包不用复数形式
            continue
        if line.startswith(u"msgid "):
            if msgid is not None and msgstr is not None:
                entries[msgid] = msgstr
            msgid = _unquote(line[len(u"msgid "):])
            msgstr = u""
            mode = "id"
        elif line.startswith(u"msgstr "):
            msgstr = _unquote(line[len(u"msgstr "):])
            mode = "str"
        elif line.startswith(u'"'):
            chunk = _unquote(line)
            if mode == "id" and msgid is not None:
                msgid += chunk
            elif mode == "str" and msgstr is not None:
                msgstr += chunk
    if msgid is not None and msgstr is not None:
        entries[msgid] = msgstr
    return entries


def parse_mo(path):
    """把 .mo 读成 ``{msgid: msgstr}``（空 msgid = 元数据头，跳过）。"""
    import gettext
    with open(path, "rb") as handle:
        catalog = gettext.GNUTranslations(handle)._catalog
    out = {}
    for key, value in catalog.items():
        key = to_unicode(key)
        if not key:
            continue
        out[key] = to_unicode(value)
    return out


def literal_string(node):
    """取 AST 字面量字符串（py2 的 ast.Str / py3 的 ast.Constant 都认）。

    相邻字符串字面量的隐式拼接由解析器完成，所以跨行写的 msgid 也会被拼好。
    """
    name = node.__class__.__name__
    if name == "Str":                              # py <= 3.7
        return to_unicode(node.s)
    if name == "Constant":                         # py >= 3.8
        value = node.value
        if isinstance(value, string_types):
            return to_unicode(value)
    return None


def collect_code_msgids(package_root):
    """扫包内所有 .py，收集 ``_(u"...")`` 里的字面量 msgid。"""
    msgids = set()
    for dirpath, dirnames, filenames in os.walk(package_root):
        dirnames[:] = [d for d in dirnames
                       if d not in ("__pycache__", "build", "dist")]
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            with open(path, "rb") as handle:
                source = handle.read()
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                fname = getattr(func, "id", None) or getattr(func, "attr", None)
                if fname not in ("_", "_t"):
                    continue
                if not node.args:
                    continue
                value = literal_string(node.args[0])
                if value:
                    msgids.add(value)
    return msgids


def check(locales_root=None, package_root=None, languages=LANGUAGES):
    """返回问题清单（空 = 全部通过）。

    :returns: ``[(code, detail), ...]``，code 取值：``stale_mo`` /
              ``empty_msgstr`` / ``missing_in_po`` / ``missing_po_or_mo``
    """
    locales_root = locales_root or LOCALES_ROOT
    package_root = package_root or PACKAGE_ROOT
    problems = []

    code_msgids = collect_code_msgids(package_root)

    for language in languages:
        po_path = os.path.join(locales_root, language, "LC_MESSAGES",
                               "%s.po" % DOMAIN)
        mo_path = os.path.join(locales_root, language, "LC_MESSAGES",
                               "%s.mo" % DOMAIN)
        if not os.path.isfile(po_path):
            problems.append(("missing_po_or_mo", u"%s 不存在" % po_path))
            continue
        if not os.path.isfile(mo_path):
            problems.append(("missing_po_or_mo",
                             u"%s 不存在（跑 tools/compile_mo.py）" % mo_path))
            continue

        po = parse_po(po_path)
        mo = parse_mo(mo_path)

        for msgid, msgstr in sorted(po.items()):
            if not msgid:
                continue
            if not msgstr.strip() and msgid not in IDENTITY_OK:
                problems.append(("empty_msgstr", u"%s: msgid %r 没翻译" % (
                    language, msgid[:60])))
                continue
            if msgid not in mo:
                problems.append(("stale_mo", u"%s: %r 在 .mo 里没有 —— "
                                 u".po 改了没重编译 .mo" % (
                                     language, msgid[:60])))
            elif mo[msgid] != msgstr:
                problems.append(("stale_mo", u"%s: %r 的 .mo 译文与 .po 不一致"
                                 u"（.mo=%r / .po=%r）—— 需要重编译" % (
                                     language, msgid[:40], mo[msgid][:40],
                                     msgstr[:40])))

        for msgid in sorted(code_msgids):
            if msgid not in po:
                problems.append(("missing_in_po", u"%s: 代码里用了 %r，"
                                 u".po 里没有" % (language, msgid[:60])))

    return problems


def _write(line):
    """按 utf-8 写 stdout（py2 的 stdout 是 ASCII，直接写中文会 UnicodeEncodeError）。"""
    sys.stdout.write((line if line.endswith(u"\n") else line + u"\n")
                     .encode("utf-8"))


def main():
    problems = check()
    for code, detail in problems:
        _write(u"  %-16s %s" % (code, detail))
    if problems:
        _write(u"%d problem(s)" % len(problems))
        return 1
    _write(u"translations OK (.po / .mo / code msgids 三者一致)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
