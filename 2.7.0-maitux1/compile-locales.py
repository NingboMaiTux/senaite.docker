# -*- coding: utf-8 -*-
"""把给定目录下所有 add-on 的 .po 编译成 .mo（纯标准库，Py2/Py3 通用）

用法
----
    python compile-locales.py /opt/addons/common            # 编译缺的/过期的
    python compile-locales.py /opt/addons/customers --force # 全部重编
    python compile-locales.py /opt/addons/common --strict   # 有失败就退出 1

在本仓库里跑在两个地方，两处都必要，缺一不可：

1. **Dockerfile 构建时**，对 ``/opt/addons/common``。
   common 是 ``COPY`` 进镜像的，构建时编译好就固化在层里，运行时不用管。
   这里用 ``--strict``：构建阶段出问题就该让 build 红掉。

2. **docker-entrypoint.sh 启动时**，对 ``/opt/addons/customers``。
   customers 在 compose 里是 bind mount（docker-compose.yml:106、145），
   **运行时会把镜像里那份整个盖掉**——所以构建时编译它毫无意义，必须等挂载
   生效之后、在容器里重新编译一遍，结果会写回宿主机的工作区。
   这里**不**用 ``--strict``：翻译编不出来顶多界面显示英文，不该把容器拖死。

为什么需要这个脚本
------------------
本环境没有开启 zope.i18n 的自动编译（``zope_i18n_compile_mo_files`` 在
compose / Dockerfile / buildout 里都没设），启动时不会从 .po 重建 .mo。
而 .mo 是编译产物、在 .gitignore 里（customers 那边是 bind mount，容器里
重编译会写回工作区，跟着 git 走的话 ``git status`` 常年脏）。

两件事凑一起的后果是：**干净 clone 出来 build，docker build 成功、容器正常
起来、日志一行错都不报，所有 add-on 的中文标签静默地全变英文。** 2026-09-21
查出来的。本脚本就是为了堵这个洞——.mo 本来就是构建产物，本来就该由构建
和启动流程自己生成，不该指望人记得手动跑。

为什么不用 msgfmt
-----------------
容器和开发机都不保证装了 gettext 工具链。GNU 的 .mo 格式本身很简单，自己
生成比引入新依赖划算。实现与各包 ``tools/compile_mo.py`` 同源。

注意：本脚本按 .po 所在目录原地编译，**不做语言别名复制**（zh / zh-cn /
zh_CN 各自有各自的 .po，各编各的）。别名铺设是各包自己脚本的事。
"""
from __future__ import print_function

import array
import os
import re
import struct
import sys

_ESCAPES = re.compile(r"\\(.)")
_REPLACEMENTS = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


def _unquote(text):
    text = text.strip()
    if text.startswith('"'):
        text = text[1:]
    if text.endswith('"'):
        text = text[:-1]
    return _ESCAPES.sub(
        lambda m: _REPLACEMENTS.get(m.group(1), m.group(1)), text)


def parse_po(path):
    """返回 {msgid: msgstr}。只处理简单结构，不做复数形式"""
    messages = {}
    state = {"msgid": None, "msgstr": "", "mode": None}

    def flush():
        if state["msgid"] is not None and state["msgstr"]:
            messages[state["msgid"]] = state["msgstr"]

    with open(path, "rb") as handle:
        for raw in handle:
            line = raw.decode("utf-8").rstrip("\r\n").strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("msgid "):
                flush()
                state["msgid"] = _unquote(line[6:])
                state["msgstr"] = ""
                state["mode"] = "id"
            elif line.startswith("msgstr "):
                state["msgstr"] = _unquote(line[7:])
                state["mode"] = "str"
            elif line.startswith('"'):
                chunk = _unquote(line)
                if state["mode"] == "id":
                    state["msgid"] = (state["msgid"] or "") + chunk
                elif state["mode"] == "str":
                    state["msgstr"] = (state["msgstr"] or "") + chunk
        flush()
    return messages


def write_mo(messages, path):
    """按 GNU gettext 的 .mo 二进制格式写出。空 msgid 是元数据头，要保留"""
    keys = sorted(messages.keys())
    offsets = []
    ids = strs = b""
    for key in keys:
        encoded_id = key.encode("utf-8")
        encoded_str = messages[key].encode("utf-8")
        offsets.append((len(ids), len(encoded_id),
                        len(strs), len(encoded_str)))
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

    table = array.array("i", koffsets + voffsets)
    output = struct.pack("Iiiiiii", 0x950412DE, 0, count,
                         7 * 4, 7 * 4 + count * 8, 0, 0)
    output += table.tostring() if hasattr(table, "tostring") \
        else table.tobytes()
    output += ids + strs

    with open(path, "wb") as handle:
        handle.write(output)


def iter_po_files(root):
    """root 下所有 locales/<lang>/LC_MESSAGES/*.po"""
    for dirpath, _dirnames, filenames in os.walk(root):
        if os.path.basename(dirpath) != "LC_MESSAGES":
            continue
        for name in sorted(filenames):
            if name.endswith(".po"):
                yield os.path.join(dirpath, name)


def needs_rebuild(po_path, mo_path, force):
    if force or not os.path.exists(mo_path):
        return True
    try:
        return os.path.getmtime(po_path) > os.path.getmtime(mo_path)
    except OSError:
        return True


def main(argv):
    roots = [a for a in argv if not a.startswith("-")]
    force = "--force" in argv
    strict = "--strict" in argv
    if not roots:
        print("用法: compile-locales.py <目录> [<目录>...] "
              "[--force] [--strict]")
        return 2

    built = skipped = failed = 0
    for root in roots:
        if not os.path.isdir(root):
            # 不算错：common / customers 都可能是空的或不存在
            print("[locales] 跳过（目录不存在）: %s" % root)
            continue
        for po_path in iter_po_files(root):
            mo_path = po_path[:-3] + ".mo"
            if not needs_rebuild(po_path, mo_path, force):
                skipped += 1
                continue
            try:
                messages = parse_po(po_path)
                write_mo(messages, mo_path)
                built += 1
                print("[locales] %s (%d 条)"
                      % (os.path.relpath(mo_path, root), len(messages)))
            except Exception as exc:
                failed += 1
                # 单个包的翻译编不出来不该拖死其它包，更不该拖死容器启动
                print("[locales] 失败 %s: %s: %s"
                      % (po_path, exc.__class__.__name__, exc),
                      file=sys.stderr)

    print("[locales] 编译 %d，跳过 %d（已是最新），失败 %d"
          % (built, skipped, failed))
    if failed and strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
