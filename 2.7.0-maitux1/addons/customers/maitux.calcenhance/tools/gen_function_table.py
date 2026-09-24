# -*- coding: utf-8 -*-
u"""README 顶部「函数总表」的生成脚本：functions.json → README.md 里两行标记之间的那一段。

总表是**生成物**，不许手改：要改一个函数的登记就改 functions.json 再重跑本脚本。
--check 只比不写，README 那一段与清单现在生成出来的不一致 → exit 1。

    python tools/gen_function_table.py            # 就地重写 README 的总表段
    python tools/gen_function_table.py --check    # 只核对（exit 0 一致 / 1 不一致 / 2 读不到或找不到标记）

路径相对本包根目录（本文件往上一级），不依赖当前目录；清单路径可用 CALCENHANCE_MANIFEST 覆盖。
Py2 / Py3 都能跑（宿主机与容器）。
只读 functions.json，**不核对它与 patches.py 是否一致** —— 那是
.claude/skills/senaite-config-guide/tools/calcfuncs.py --check 与 tests/test_function_manifest.py 的事。
"""
from __future__ import print_function

import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# CALCENHANCE_MANIFEST 覆盖清单路径（与 calcfuncs.py / 引擎自检同一约定，变异测试靠它指到副本）
MANIFEST = os.environ.get("CALCENHANCE_MANIFEST") or os.path.join(
    ROOT, "src", "maitux", "calcenhance", "functions.json")
README = os.path.join(ROOT, "README.md")

BEGIN = (u"<!-- BEGIN functions-table：由 tools/gen_function_table.py 从 "
         u"src/maitux/calcenhance/functions.json 生成，勿手改 -->")
END = u"<!-- END functions-table -->"

TABLES = ((u"scalar", u"calculated"), (u"list", u"calculatedlist"))


def _out(text):
    if sys.version_info[0] < 3:
        text = text.encode("utf-8")
    print(text)


def _die(msg, code=2):
    _out(u"ABORT：" + msg)
    sys.exit(code)


def _params(ps):
    def one(p):
        s = u"%s:%s" % (p[u"name"], p[u"kind"])
        if p.get(u"variadic"):
            s = u"*" + s
        if p.get(u"optional"):
            s = u"[" + s + u"]"
        return s

    def row(items):
        return u", ".join(one(p) for p in items) or u"（无）"

    if isinstance(ps, dict):        # D1：两表约定不同
        return u"标量：%s ／ 列表：%s" % (row(ps[u"scalar"]), row(ps[u"list"]))
    return row(ps)


def render(man):
    fns = man[u"functions"]
    public = sorted((n for n in fns if not fns[n].get(u"internal")),
                    key=lambda n: (n.lower(), n))
    internal = sorted(n for n in fns if fns[n].get(u"internal"))
    L = [BEGIN, u"",
         u"## 函数总表（引擎 %s，%d 个函数）" % (man[u"engine_version"], len(public)),
         u"",
         u"下面这张表由 `src/maitux/calcenhance/functions.json`（引擎函数清单）**生成**，"
         u"本 README 其余各节是按版本写的更新概要。",
         u"",
         u"- **机械可核**：函数名、在哪张表（✓）、数组路径 —— 与 `patches.py` 每次核对，"
         u"漂了就在流水线（`calcfuncs.py --check`）、单测（`tests/test_function_manifest.py`）"
         u"和实例日志（`function manifest mismatch`）三处报错。",
         u"- **人定、门禁核不了**：返回形状、参数、用途、since —— 出处见 "
         u"`Docs/Cal增加/maitux.calcenhance-函数清单-基线对账.md` §1b。定错了**不会报错**。",
         u"- 返回形状指函数在**列表引擎**（calculatedlist）里返回什么：" +
         u"；".join(u"`%s` %s" % (k, man[u"shape_vocab"][k])
                   for k in (u"scalar", u"column", u"elementwise", u"opaque")) + u"。",
         u"- 参数写成 `名字:kind`，`[…]` 可省、`*` 可变参；kind 见清单 `kind_vocab`。",
         u"",
         u"| 函数 | calculated | calculatedlist | 返回形状 | 数组路径 | 参数 | 用途 | since |",
         u"|---|:---:|:---:|---|:---:|---|---|---|"]
    for n in public:
        e = fns[n]
        L.append(u"| `%s` | %s | %s | %s | %s | %s | %s | %s |" % (
            n,
            u"✓" if u"scalar" in e[u"tables"] else u"",
            u"✓" if u"list" in e[u"tables"] else u"",
            e[u"shape"],
            u"✓" if e[u"array_path"] else u"",
            _params(e[u"params"]),
            u"、".join(e[u"purpose"]),
            e[u"since"]))
    if internal:
        L += [u"",
              u"另有内部名 %s：两张表里都注册了、公式作者不写它（清单里 `internal: true`），不列在上表。"
              % u"、".join(u"`%s`" % n for n in internal)]
    L += [u"", END]
    for ln in L:
        if u"|" in ln and not ln.startswith(u"|"):
            _die(u"总表说明行里出现了竖线：%s" % ln)
    return L


def main(argv):
    check = argv[1:] == ["--check"]
    if argv[1:] and not check:
        _die(u"用法：python tools/gen_function_table.py [--check]", 64)
    try:
        man = json.load(io.open(MANIFEST, encoding="utf-8"))
        raw = io.open(README, encoding="utf-8", newline="").read()
    except (IOError, OSError, ValueError) as err:
        _die(u"读不到清单或 README：%s" % err)
    nl = u"\r\n" if u"\r\n" in raw else u"\n"
    lines = raw.replace(u"\r\n", u"\n").split(u"\n")
    if lines.count(BEGIN) != 1 or lines.count(END) != 1:
        _die(u"README 里 BEGIN / END 标记应各恰 1 行（BEGIN %d / END %d）"
             % (lines.count(BEGIN), lines.count(END)))
    b, e = lines.index(BEGIN), lines.index(END)
    if e < b:
        _die(u"README 里 END 标记在 BEGIN 前面")
    old, new = lines[b:e + 1], render(man)
    if check:
        if old == new:
            _out(u"一致：README 函数总表 ↔ functions.json（%d 行）" % (len(new) - 2))
            return 0
        diff = [(i, o, n) for i, (o, n) in enumerate(zip(old, new)) if o != n]
        _out(u"不一致：README 函数总表与 functions.json 生成结果不同"
             u"（README %d 行 / 生成 %d 行，逐行不同 %d 处）—— 重跑本脚本（不带 --check）"
             % (len(old), len(new), len(diff)))
        for i, o, n in diff[:10]:
            _out(u"  README 第 %d 行\n    现在：%s\n    应为：%s" % (b + i + 1, o, n))
        return 1
    io.open(README, "w", encoding="utf-8", newline="").write(
        nl.join(lines[:b] + new + lines[e + 1:]))
    _out(u"已写入 README 函数总表（%d 个函数）" % sum(
        1 for ln in new if ln.startswith(u"| `")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
