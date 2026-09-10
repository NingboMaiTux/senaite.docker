# -*- coding: utf-8 -*-
"""门禁（baseline / 不新增 ERROR）自测。

为什么必须有：基线机制的失效方式是**静默的、而且是往松的方向**——
一旦 split_by_baseline 或指纹算法出点问题，最可能的表现不是报错，
而是「什么都不拦了还显示 ✔ 通过」。那比没有门禁更危险：所有人都以为有人在看。

所以这里逐条钉死门禁的语义：

  1  无基线                       → 拦（exit 1）
  2  基线只盖住一部分             → 仍拦剩下那部分
  3  基线盖住全部                 → 通过（exit 0）
  4  基线条目已不再出现（包还在）  → 报「已消失」，提示重写
 4c  基线条目对应的包整个没扫到    → 单独报，**不**说成「修好了」
  5  --no-baseline（严格模式）    → 无视基线，照拦
  6  --write-baseline 后重跑      → 通过
  7  --write-baseline 带 --addon  → 拒绝执行（exit 2）
  8  基线只记 ERROR，不记 WARN    → WARN 不影响门禁
  9  同一 (包,码,路径) 出现两次而基线只记 1 次 → 多出来的那次仍拦
 10  单包扫描 + 全量基线           → **不许**出现任何「已修好」建议
 11  单包扫描、范围内真修好了       → 仍要报「已消失」（别一刀切屏蔽掉）
 12  重写基线                       → 范围外条目、note、`_纪律` 都保住

第 10 条是 2026-09-10 的实测事故：`--addon maitux.calcenhance` 只扫 1 个包，
却拿全量基线做差异判断，于是把 maitux.instrument_acquisition 的 E17
（那条 R14 泄漏其实一直在）报成「说明修好了，请重写基线把它剔掉」。
照那句提示重写，就会把别人的既有欠账一起抹掉 —— 正是提示自己警告的
"基线烂成免死金牌"。所以"范围"这一层必须有自测钉住。

跑法（宿主 Python 3）：
    python selftest_gate.py
退出码 0 = 全过。fixture 造在系统临时目录，跑完即删。
"""
from __future__ import print_function

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LINT = os.path.join(HERE, "lint_addon.py")

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 触发 E06_PY2_MISSING_CODING：有中文、前两行无 coding 声明
BAD_PY = u"""from zope.interface import Interface


# 这行是中文注释，Py2 import 时直接 SyntaxError
X = 1
"""

GOOD_PY = u"""# -*- coding: utf-8 -*-
from zope.interface import Interface


# 中文注释，但有 coding 声明，合法
X = 1
"""

# 触发 W07b_BYTES_CJK（WARN，不该影响门禁）
WARN_PY = u"""# -*- coding: utf-8 -*-

MSG = "中文字节串"
"""

ZCML = u"""<configure
    xmlns="http://namespaces.zope.org/zope"
    i18n_domain="pkg.thing">
  <include package="senaite.core.permissions" />
  <genericsetup:registerProfile
      xmlns:genericsetup="http://namespaces.zope.org/genericsetup"
      name="default" title="pkg.thing"
      directory="profiles/default"
      provides="Products.GenericSetup.interfaces.EXTENSION"
      />
</configure>
"""


def write(path, text):
    d = os.path.dirname(path)
    if not os.path.isdir(d):
        os.makedirs(d)
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def make_pkg(root, name, files):
    """files: {相对代码目录的文件名: 内容}"""
    base = os.path.join(root, "customers", name)
    code = os.path.join(base, "src", "pkg", name.split(".")[-1])
    write(os.path.join(base, "setup.py"),
          u"from setuptools import setup\nsetup(name='pkg.%s')\n"
          % name.split(".")[-1])
    write(os.path.join(base, "src", "pkg", "__init__.py"), u"")
    write(os.path.join(code, "__init__.py"), u"")
    write(os.path.join(code, "configure.zcml"), ZCML)
    for prof in ("default", "uninstall"):
        write(os.path.join(code, "profiles", prof, "metadata.xml"),
              u'<?xml version="1.0"?>\n'
              u'<metadata><version>1</version></metadata>\n')
    for fn, content in files.items():
        write(os.path.join(code, fn), content)
    return name


def run(root, extra=None, baseline=None):
    """跑 lint，返回 (exit_code, stdout)。"""
    cmd = [sys.executable, LINT, "--addons-root", root]
    if baseline:
        cmd += ["--baseline", baseline]
    cmd += (extra or [])
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT)
    out, _ = p.communicate()
    return p.returncode, out.decode("utf-8", "replace")


def make_baseline(path, entries, extras=None):
    """entries: [(addon, code, path)]；extras: 额外的顶层字段"""
    data = {
        "recorded": "2026-01-01",
        "entries": [{"addon": a, "code": c, "path": p,
                     "count": 1, "level": "ERROR", "note": "selftest"}
                    for a, c, p in entries],
    }
    data.update(extras or {})
    write(path, json.dumps(data, ensure_ascii=False, indent=2))


P_DEBT = "pkg.debt"
P_NEW = "pkg.new"
P_CLEAN = "pkg.clean"
DEBT_KEY = (P_DEBT, "E06_PY2_MISSING_CODING", "src/pkg/debt/bad.py")
NEW_KEY = (P_NEW, "E06_PY2_MISSING_CODING", "src/pkg/new/bad.py")

RESULTS = []


def check(name, cond, detail=u""):
    RESULTS.append((name, bool(cond), detail))
    print(u"%-4s %s%s" % ("PASS" if cond else "FAIL", name,
                          u"" if cond else u"   ← " + detail))


def main():
    root = tempfile.mkdtemp(prefix="lint_gate_")
    try:
        make_pkg(root, P_DEBT, {"bad.py": BAD_PY})
        make_pkg(root, P_NEW, {"bad.py": BAD_PY})
        make_pkg(root, P_CLEAN, {"ok.py": GOOD_PY, "warn.py": WARN_PY})
        bl = os.path.join(root, "bl.json")

        # 1 无基线 → 拦
        rc, out = run(root, baseline=os.path.join(root, "nope.json"))
        check(u"1 无基线时拦下", rc == 1, u"exit=%d" % rc)
        check(u"1b 无基线时措辞不谎称「本次新增」",
              u"无法区分既有欠账与本次新增" in out)

        # 2 基线只盖一部分 → 仍拦另一部分
        make_baseline(bl, [DEBT_KEY])
        rc, out = run(root, baseline=bl)
        check(u"2 基线只盖 debt 时仍拦 new", rc == 1, u"exit=%d" % rc)
        check(u"2b 被盖住的不再计入新增",
              u"新增 1 条 ERROR" in out, u"输出未显示恰好 1 条新增")
        check(u"2c 欠账仍被打印出来（不消失在视野里）",
              u"基线抑制了 1 条既有 ERROR" in out)

        # 3 基线盖住全部 → 通过
        make_baseline(bl, [DEBT_KEY, NEW_KEY])
        rc, out = run(root, baseline=bl)
        check(u"3 基线盖住全部时通过", rc == 0, u"exit=%d" % rc)
        check(u"3b 通过时仍列出 2 条欠账",
              u"基线抑制了 2 条既有 ERROR" in out)

        # 4 基线条目已消失（包在扫描范围内、那一条没了）→ 报「已消失」
        make_baseline(bl, [DEBT_KEY, NEW_KEY,
                           (P_DEBT, "E06_PY2_MISSING_CODING",
                            "src/pkg/debt/vanished.py")])
        rc, out = run(root, baseline=bl)
        check(u"4 基线里已消失的条目被报出来",
              u"已经不再出现" in out and u"vanished.py" in out)
        check(u"4b 已消失的条目不影响判定", rc == 0, u"exit=%d" % rc)

        # 4c 包整个没扫到是另一回事，措辞不能混成"修好了"：
        #    真实成因往往是 R5d —— 目录缺 setup.py 被整包跳过，
        #    那时候包还在、问题也还在，只是工具看不见它。
        make_baseline(bl, [DEBT_KEY, NEW_KEY,
                           ("pkg.gone", "E06_PY2_MISSING_CODING",
                            "src/pkg/gone/x.py")])
        rc, out = run(root, baseline=bl)
        check(u"4c 包没扫到时单独报，不说成「修好了」",
              u"压根没扫到" in out and u"pkg.gone" in out
              and u"已经不再出现" not in out, u"输出：\n%s" % out)
        check(u"4d 没扫到的条目也不影响判定", rc == 0, u"exit=%d" % rc)

        # 5 --no-baseline 严格模式 → 无视基线照拦
        rc, out = run(root, extra=["--no-baseline"], baseline=bl)
        check(u"5 --no-baseline 无视基线照拦", rc == 1, u"exit=%d" % rc)

        # 6 --write-baseline 后重跑 → 通过
        bl2 = os.path.join(root, "written.json")
        rc, out = run(root, extra=["--write-baseline", bl2])
        check(u"6 --write-baseline 退出码为 0", rc == 0, u"exit=%d" % rc)
        check(u"6b 写出的基线含两条 ERROR",
              os.path.isfile(bl2) and
              len(json.load(io.open(bl2, encoding="utf-8"))["entries"]) == 2)
        rc, out = run(root, baseline=bl2)
        check(u"6c 用写出的基线重跑即通过", rc == 0, u"exit=%d" % rc)

        # 6d 写出的基线不该混入 WARN
        got_codes = set(e["code"] for e in
                        json.load(io.open(bl2, encoding="utf-8"))["entries"])
        check(u"6d 写出的基线只含 ERROR，不含 WARN",
              not any(c.startswith("W") for c in got_codes),
              u"混入了 %s" % sorted(got_codes))

        # 7 --write-baseline 带 --addon → 拒绝
        rc, out = run(root, extra=["--write-baseline", bl2,
                                   "--addon", P_DEBT])
        check(u"7 --write-baseline 带 --addon 被拒绝",
              rc == 2 and u"拒绝执行" in out, u"exit=%d" % rc)

        # 8 WARN 不影响门禁（clean 包只有 WARN）
        make_baseline(bl, [DEBT_KEY, NEW_KEY])
        rc, out = run(root, baseline=bl)
        check(u"8 只有 WARN 的包不影响门禁",
              rc == 0 and u"W07b_BYTES_CJK" in out,
              u"exit=%d，输出里有没有那条 WARN 也要确认" % rc)

        # 9 同键出现两次、基线只记 1 次 → 多出的那次仍拦
        make_pkg(root, "pkg.twice", {"bad.py": BAD_PY, "bad2.py": BAD_PY})
        make_baseline(bl, [DEBT_KEY, NEW_KEY,
                           ("pkg.twice", "E06_PY2_MISSING_CODING",
                            "src/pkg/twice/bad.py")])
        rc, out = run(root, baseline=bl)
        check(u"9 同码不同文件各自独立计数（bad2.py 仍被拦）",
              rc == 1, u"exit=%d" % rc)

        # 10 单包扫描 + 全量基线 → 一条「已修好」都不许有
        #    这是本自测最要紧的一条：范围外的包这次压根没跑过检查，
        #    "没扫到" 不等于 "修好了"。
        make_baseline(bl, [DEBT_KEY, NEW_KEY])
        rc, out = run(root, extra=["--addon", P_CLEAN], baseline=bl)
        check(u"10 单包扫描不产生任何「已修好」建议",
              u"已经不再出现" not in out,
              u"输出里仍有「已经不再出现」：\n%s" % out)
        check(u"10b 范围外的包名不出现在建议里",
              P_DEBT not in out and P_NEW not in out,
              u"范围外的包被点名了")
        check(u"10c 明确交代范围外的条目没参与判断",
              u"既不算「已修好」也不建议重写" in out)
        check(u"10d 单包扫描仍照常判定", rc == 0, u"exit=%d" % rc)

        # 11 反向：范围**内**真修好了，还得照报 —— 别用"一律不报"糊过去
        make_baseline(bl, [(P_CLEAN, "E06_PY2_MISSING_CODING",
                            "src/pkg/clean/gone.py")])
        rc, out = run(root, extra=["--addon", P_CLEAN], baseline=bl)
        check(u"11 范围内已修好的条目仍报「已消失」",
              u"已经不再出现" in out and u"gone.py" in out,
              u"范围过滤把该报的也吃掉了")
        check(u"11b 单包扫描下不再叫人就地重写基线",
              u"重写要全量扫描" in out)

        # 12 重写基线：范围外条目 / note / 顶层 _纪律 都得留住
        bl3 = os.path.join(root, "merge.json")
        make_baseline(bl3, [DEBT_KEY,
                            ("pkg.gone", "E06_PY2_MISSING_CODING",
                             "src/pkg/gone/x.py")],
                      extras={"_纪律": "别把这段冲掉"})
        rc, out = run(root, extra=["--write-baseline", bl3])
        data = json.load(io.open(bl3, encoding="utf-8"))
        keys = set((e["addon"], e["code"], e["path"]) for e in data["entries"])
        check(u"12 重写基线保留范围外的既有条目",
              ("pkg.gone", "E06_PY2_MISSING_CODING",
               "src/pkg/gone/x.py") in keys,
              u"pkg.gone 被抹了：%s" % sorted(keys))
        check(u"12b 重写时点明保留了几条", u"保留 1 条范围外" in out)
        notes = dict(((e["addon"], e["code"], e["path"]), e.get("note"))
                     for e in data["entries"])
        check(u"12c 人工填的 note 被带过来", notes.get(DEBT_KEY) == "selftest",
              u"note 丢了：%r" % (notes.get(DEBT_KEY),))
        check(u"12d 顶层 _纪律 没被冲掉",
              data.get("_纪律") == "别把这段冲掉")
        check(u"12e 范围内的包照常重写（twice 的两条都在）",
              len([1 for a, c, p in keys if a == "pkg.twice"]) == 2,
              u"范围内条目没写全：%s" % sorted(keys))

        ok = sum(1 for _n, c, _d in RESULTS if c)
        print(u"\n%d/%d passed" % (ok, len(RESULTS)))
        return 0 if ok == len(RESULTS) else 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
