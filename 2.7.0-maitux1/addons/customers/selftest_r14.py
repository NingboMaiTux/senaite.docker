# -*- coding: utf-8 -*-
"""R14（E17/W17）合成用例自测 —— 对应 SKILL.md「加新规则铁律」第 4 条。

为什么必须有：R14 的判定有三条收窄条件，而"真实包不误报"只能证明**当前**
21 个包恰好不触发，证明不了边界判对了。摸底时初版规则打 17 处、其中 15 处
是误报，三条收窄条件各自负责干掉一类：

  ① 包必须自己声明过 browser layer  → c03
  ② for= 里出现 layer 算已门控        → c04 / c07
  ③ 只认指向外来内容接口的           → c06（for="*"）/ c08（自有内容接口）

外加运行时门控（c02）与嵌套 zcml 深度遍历（c09）两个必须成立的行为。

跑法（宿主 Python 3）：
    python selftest_r14.py
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

# Windows 控制台默认 GBK，用例说明里的中文会成乱码（只影响可读性，不影响判定）
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

LAYER_PY = u"""# -*- coding: utf-8 -*-
from senaite.core.interfaces import ISenaiteCore


class IMyPkgLayer(ISenaiteCore):
    \"\"\"browser layer\"\"\"
"""

FACTORY_PLAIN = u"""# -*- coding: utf-8 -*-


class ListingViewAdapter(object):
    def __init__(self, view, context):
        self.view = view
        self.context = context

    def before_render(self):
        self.view.show_select_column = True

    def folder_item(self, obj, item, index):
        return item
"""

FACTORY_GATED = u"""# -*- coding: utf-8 -*-
from mypkg.thing.interfaces import IMyPkgLayer


class ListingViewAdapter(object):
    def __init__(self, view, context):
        self.view = view
        self.context = context

    def before_render(self):
        if not IMyPkgLayer.providedBy(self.view.request):
            return
        self.view.show_select_column = True

    def folder_item(self, obj, item, index):
        return item
"""

SUB_UNGATED = u"""  <subscriber
      for="senaite.app.listing.interfaces.IListingView
           senaite.core.interfaces.IWorksheets"
      factory="mypkg.thing.adapter.ListingViewAdapter"
      provides="senaite.app.listing.interfaces.IListingViewAdapter"
      />
"""

SUB_LAYER_IN_FOR = u"""  <subscriber
      for="senaite.app.listing.interfaces.IListingView
           mypkg.thing.interfaces.IMyPkgLayer"
      factory="mypkg.thing.adapter.ListingViewAdapter"
      provides="senaite.app.listing.interfaces.IListingViewAdapter"
      />
"""

ADP_FOREIGN_REQ = u"""  <adapter
      name="workflow_action_thing"
      for="senaite.core.interfaces.IWorksheets
           zope.publisher.interfaces.browser.IBrowserRequest"
      factory="mypkg.thing.adapter.WFAdapter"
      provides="bika.lims.interfaces.IWorkflowActionAdapter"
      permission="zope.Public" />
"""

ADP_STAR = u"""  <adapter
      name="workflow_action_thing"
      for="*"
      factory="mypkg.thing.adapter.WFAdapter"
      provides="bika.lims.interfaces.IWorkflowActionAdapter"
      permission="zope.Public" />
"""

ADP_LAYER_IN_FOR = u"""  <adapter
      name="workflow_action_thing"
      for="senaite.core.interfaces.IWorksheets
           mypkg.thing.interfaces.IMyPkgLayer"
      factory="mypkg.thing.adapter.WFAdapter"
      provides="bika.lims.interfaces.IWorkflowActionAdapter"
      permission="zope.Public" />
"""

ADP_OWN_CONTENT = u"""  <adapter
      name="workflow_action_thing"
      for="mypkg.thing.interfaces.IMyOwnContent
           zope.publisher.interfaces.browser.IBrowserRequest"
      factory="mypkg.thing.adapter.WFAdapter"
      provides="bika.lims.interfaces.IWorkflowActionAdapter"
      permission="zope.Public" />
"""

PAGE_ONLY = u"""  <browser:page
      name="thing_view"
      for="senaite.core.interfaces.IWorksheet"
      class="mypkg.thing.adapter.SomeView"
      permission="zope.Public"
      layer="mypkg.thing.interfaces.IMyPkgLayer"
      />
"""


def zcml(body):
    return (u'<configure\n'
            u'    xmlns="http://namespaces.zope.org/zope"\n'
            u'    xmlns:browser="http://namespaces.zope.org/browser"\n'
            u'    i18n_domain="mypkg.thing">\n\n'
            u'  <include package="senaite.core.permissions" />\n\n'
            + body +
            u'\n  <genericsetup:registerProfile\n'
            u'      xmlns:genericsetup='
            u'"http://namespaces.zope.org/genericsetup"\n'
            u'      name="default" title="mypkg.thing"\n'
            u'      directory="profiles/default"\n'
            u'      provides="Products.GenericSetup.interfaces.EXTENSION"\n'
            u'      />\n'
            u'</configure>\n')


def write(path, text):
    d = os.path.dirname(path)
    if not os.path.isdir(d):
        os.makedirs(d)
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def make_case(root, name, body, with_layer=True, gated_factory=False,
              nested=False):
    """造一个最小的、能被 lint 收录的 fixture addon。"""
    base = os.path.join(root, "customers", name)
    code = os.path.join(base, "src", "mypkg", "thing")
    write(os.path.join(base, "setup.py"),
          u"from setuptools import setup\nsetup(name='mypkg.thing')\n")
    write(os.path.join(base, "src", "mypkg", "__init__.py"), u"")
    write(os.path.join(code, "__init__.py"), u"")
    write(os.path.join(code, "adapter.py"),
          FACTORY_GATED if gated_factory else FACTORY_PLAIN)
    if with_layer:
        write(os.path.join(code, "interfaces.py"), LAYER_PY)
    for prof in ("default", "uninstall"):
        write(os.path.join(code, "profiles", prof, "metadata.xml"),
              u'<?xml version="1.0"?>\n'
              u'<metadata><version>1</version></metadata>\n')
    if nested:
        # 顶层留空，注册藏在深层目录 —— 验证遍历深度
        write(os.path.join(code, "configure.zcml"), zcml(u""))
        write(os.path.join(code, "browser", "deep", "configure.zcml"),
              zcml(body))
    else:
        write(os.path.join(code, "configure.zcml"), zcml(body))


CASES = [
    # (用例名, 期望的 R14 码集合, 构造参数, 这一例在验什么)
    ("c01_ui_ungated", {"E17_UI_INJECTION_UNGATED"},
     dict(body=SUB_UNGATED),
     u"事故本体：UI 注入订阅者两条门控都没走"),
    ("c02_ui_runtime_gated", set(),
     dict(body=SUB_UNGATED, gated_factory=True),
     u"工厂里判了 layer → 运行时门控成立，不报"),
    ("c03_ui_no_layer", set(),
     dict(body=SUB_UNGATED, with_layer=False),
     u"收窄①：包没声明 layer，无从门控，不报"),
    ("c04_ui_layer_in_for", set(),
     dict(body=SUB_LAYER_IN_FOR),
     u"收窄②：layer 写在 for= 里算已门控"),
    ("c05_adp_foreign_req", {"W17_FOREIGN_ADAPTER_UNGATED"},
     dict(body=ADP_FOREIGN_REQ),
     u"外来内容 + 任意请求 → WARN"),
    ("c06_adp_star", set(),
     dict(body=ADP_STAR),
     u'收窄③：for="*" 配自有动作名不报'),
    ("c07_adp_layer_in_for", set(),
     dict(body=ADP_LAYER_IN_FOR),
     u"收窄②对 adapter 同样成立"),
    ("c08_adp_own_content", set(),
     dict(body=ADP_OWN_CONTENT),
     u"收窄③：for 指向自有内容接口不报"),
    ("c09_ui_nested_zcml", {"E17_UI_INJECTION_UNGATED"},
     dict(body=SUB_UNGATED, nested=True),
     u"深层 zcml 也要扫到（事故那处就在 browser/worksheet/ 下）"),
    ("c10_page_only", set(),
     dict(body=PAGE_ONLY),
     u"只有 browser:page 时不打扰"),
]


def main():
    root = tempfile.mkdtemp(prefix="lint_r14_")
    try:
        for name, _exp, kw, _why in CASES:
            make_case(root, name, **kw)
        out_json = os.path.join(root, "report.json")
        with open(os.devnull, "w") as devnull:
            subprocess.call(
                [sys.executable, LINT, "--addons-root", root,
                 "--json", out_json],
                stdout=devnull, stderr=subprocess.STDOUT)
        with io.open(out_json, encoding="utf-8") as fh:
            data = json.load(fh)
        findings = data["findings"] if isinstance(data, dict) else data

        got = {}
        for f in findings:
            if f.get("rule") == "R14":
                got.setdefault(f["addon"], set()).add(f["code"])

        ok = 0
        for name, expected, _kw, why in CASES:
            actual = got.get(name, set())
            passed = actual == expected
            ok += 1 if passed else 0
            print(u"%-4s %-22s %s" % ("PASS" if passed else "FAIL", name, why))
            if not passed:
                print(u"       expect=%s  got=%s"
                      % (",".join(sorted(expected)) or "-",
                         ",".join(sorted(actual)) or "-"))
        print(u"\n%d/%d passed" % (ok, len(CASES)))
        return 0 if ok == len(CASES) else 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
