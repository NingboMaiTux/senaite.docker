# -*- coding: utf-8 -*-
"""门禁（baseline / 不新增 ERROR）自测。

为什么必须有：基线机制的失效方式是**静默的、而且是往松的方向**——
一旦 split_by_baseline 或指纹算法出点问题，最可能的表现不是报错，
而是「什么都不拦了还显示 ✔ 通过」。那比没有门禁更危险：所有人都以为有人在看。

所以这里逐条钉死门禁的语义：

  1  无基线                       → 拦（exit 1）
  2  基线只盖住一部分             → 仍拦剩下那部分
  3  基线盖住全部                 → 通过（exit 0）
  4  基线条目已不再出现           → 报「已消失」，提示重写
  5  --no-baseline（严格模式）    → 无视基线，照拦
  6  --write-baseline 后重跑      → 通过
  7  --write-baseline 带 --addon  → 拒绝执行（exit 2）
  8  基线只记 ERROR，不记 WARN    → WARN 不影响门禁
  9  同一 (包,码,路径) 出现两次而基线只记 1 次 → 多出来的那次仍拦

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


def make_baseline(path, entries):
    """entries: [(addon, code, path)]"""
    write(path, json.dumps({
        "recorded": "2026-01-01",
        "entries": [{"addon": a, "code": c, "path": p,
                     "count": 1, "level": "ERROR", "note": "selftest"}
                    for a, c, p in entries],
    }, ensure_ascii=False, indent=2))


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

        # 4 基线条目已消失 → 报「已消失」
        make_baseline(bl, [DEBT_KEY, NEW_KEY,
                           ("pkg.gone", "E06_PY2_MISSING_CODING",
                            "src/pkg/gone/x.py")])
        rc, out = run(root, baseline=bl)
        check(u"4 基线里已消失的条目被报出来",
              u"已经不再出现" in out and u"pkg.gone" in out)
        check(u"4b 已消失的条目不影响判定", rc == 0, u"exit=%d" % rc)

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

        ok = sum(1 for _n, c, _d in RESULTS if c)
        print(u"\n%d/%d passed" % (ok, len(RESULTS)))
        return 0 if ok == len(RESULTS) else 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
