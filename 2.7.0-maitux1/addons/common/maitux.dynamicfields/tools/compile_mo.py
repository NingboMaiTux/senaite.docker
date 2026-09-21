# -*- coding: utf-8 -*-
"""把 locales 下的 .po 编译成 .mo（纯标准库，Py2/Py3 通用）

用法
----
    python tools/compile_mo.py            # 编译全部 .po
    python tools/compile_mo.py --check    # 只检查、不写文件

为什么自带一个而不用 gettext 工具链：容器和开发机都不保证装了 msgfmt，
引入新依赖不如自己生成——与 maitux.worksheetfields / maitux.glossary /
maitux.reviewerassignment 的同名脚本同一实现，只是路径按本包调整。

顺带做一件事：本包源里只维护 ``zh_CN``，编译时自动复制出 ``zh`` / ``zh-cn``
两份。浏览器发 ``zh-cn``、Plone 可能归一成 ``zh_CN``，三种写法都可能落到
gettext 的目录查找上——铺齐比在运行时猜便宜。

（注意：这只影响**配置页自身**的界面文案。用户建的字段标签走本包自注册的
翻译域，文案存配置库、不落 .po，改完实时生效，不需要跑这个脚本。）
"""
from __future__ import print_function

import array
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LOCALES = os.path.join(HERE, os.pardir, "src", "maitux", "dynamicfields",
                       "locales")

#: 源语言目录 -> 要额外生成的别名目录
ALIASES = {"zh_CN": ("zh", "zh-cn")}


def parse_po(path):
    """返回 {msgid: msgstr}。只处理本包用到的简单结构，不做复数形式"""
    messages = {}
    msgid = None
    msgstr = None
    mode = None

    def flush():
        if msgid is not None and msgstr:
            messages[msgid] = msgstr

    with open(path, "rb") as handle:
        for raw in handle:
            line = raw.decode("utf-8").rstrip("\r\n")
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("msgid "):
                flush()
                msgid = _unquote(stripped[6:])
                msgstr = ""
                mode = "id"
            elif stripped.startswith("msgstr "):
                msgstr = _unquote(stripped[7:])
                mode = "str"
            elif stripped.startswith('"'):
                chunk = _unquote(stripped)
                if mode == "id":
                    msgid = (msgid or "") + chunk
                elif mode == "str":
                    msgstr = (msgstr or "") + chunk
        flush()
    return messages


_ESCAPES = re.compile(r'\\(.)')
_REPLACEMENTS = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


def _unquote(text):
    text = text.strip()
    if text.startswith('"'):
        text = text[1:]
    if text.endswith('"'):
        text = text[:-1]
    return _ESCAPES.sub(lambda m: _REPLACEMENTS.get(m.group(1), m.group(1)), text)


def write_mo(messages, path):
    """按 GNU gettext 的 .mo 二进制格式写出"""
    keys = sorted(messages.keys())
    offsets = []
    ids = strs = b""
    for key in keys:
        encoded_id = key.encode("utf-8")
        encoded_str = messages[key].encode("utf-8")
        offsets.append((len(ids), len(encoded_id), len(strs), len(encoded_str)))
        ids += encoded_id + b"\x00"
        strs += encoded_str + b"\x00"

    count = len(keys)
    keystart = 7 * 4 + 16 * count
    valuestart = keystart + len(ids)
    koffsets = []
    voffsets = []
    for o1, l1, o2, l2 in offsets:
        koffsets += [l1, o1 + keystart]
        voffsets += [l2, o2 + valuestart]

    output = struct.pack(
        "Iiiiiii", 0x950412de, 0, count, 7 * 4, 7 * 4 + count * 8, 0, 0)
    output += array.array("i", koffsets + voffsets).tostring() \
        if hasattr(array.array("i", []), "tostring") \
        else array.array("i", koffsets + voffsets).tobytes()
    output += ids
    output += strs

    with open(path, "wb") as handle:
        handle.write(output)


def iter_po_files():
    for root, _dirs, files in os.walk(LOCALES):
        for name in files:
            if name.endswith(".po"):
                yield os.path.join(root, name)


def main(argv):
    check_only = "--check" in argv
    total = 0
    for po_path in iter_po_files():
        messages = parse_po(po_path)
        mo_path = po_path[:-3] + ".mo"
        print("%s -> %s (%s 条)" % (
            os.path.relpath(po_path, HERE),
            os.path.basename(mo_path), len(messages)))
        if not check_only:
            write_mo(messages, mo_path)
            _write_aliases(po_path, messages)
        total += 1
    if not total:
        print("没找到 .po 文件：%s" % LOCALES)
        return 1
    return 0


def _write_aliases(po_path, messages):
    """zh_CN 的结果同时写一份到 zh / zh-cn"""
    parts = os.path.normpath(po_path).split(os.sep)
    try:
        index = parts.index("locales")
    except ValueError:
        return
    language = parts[index + 1]
    for alias in ALIASES.get(language, ()):
        target_dir = os.path.join(LOCALES, alias, "LC_MESSAGES")
        if not os.path.isdir(target_dir):
            os.makedirs(target_dir)
        base = os.path.basename(po_path)
        with open(po_path, "rb") as src:
            data = src.read()
        with open(os.path.join(target_dir, base), "wb") as dst:
            dst.write(data)
        write_mo(messages, os.path.join(target_dir, base[:-3] + ".mo"))
        print("  别名 %s 已同步" % alias)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
