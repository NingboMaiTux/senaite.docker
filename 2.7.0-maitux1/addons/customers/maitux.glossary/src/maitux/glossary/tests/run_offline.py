# -*- coding: utf-8 -*-
"""离线自检 —— 不需要 Zope，也不需要连站点。

用法（Python 2 或 3 均可）::

    python src/maitux/glossary/tests/run_offline.py

检查：

  1. **语法**：编译本包全部 .py（只编译不写 .pyc）
  2. **XML**：全部 .zcml / .xml 是否 well-formed
  3. **profile**：registerProfile 声明的目录与 metadata.xml（规则 R4）
  4. **确定性 ID**：同键同 ID、`_` 歧义、CJK 关键字
  5. **同步计划**：R1 追加 / R2 不改 / R3 状态对称重算
  6. **新行默认值**：zh、en **必须为空**（人工填写，不从站点回填）

容器位置、Setup 菜单收录等运行期行为由部署后的验收用例覆盖（README §7）。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE_ROOT = os.path.abspath(os.path.join(HERE, os.pardir))
ADDON_ROOT = os.path.abspath(os.path.join(PACKAGE_ROOT, os.pardir,
                                          os.pardir, os.pardir))
SRC_ROOT = os.path.abspath(os.path.join(PACKAGE_ROOT, os.pardir, os.pardir))
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)


class Results(object):

    def __init__(self):
        self.passed = 0
        self.failed = []

    def check(self, name, condition, detail=u""):
        if condition:
            self.passed += 1
            print("  ok    %s" % name)
        else:
            self.failed.append((name, detail))
            print("  FAIL  %s %s" % (name, detail))
        return bool(condition)

    def report(self):
        total = self.passed + len(self.failed)
        print("")
        print("%d/%d passed" % (self.passed, total))
        for name, detail in self.failed:
            print("  FAILED: %s %s" % (name, detail))
        return 0 if not self.failed else 1


def iter_files(root, extensions):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "__pycache__", "build", "dist")]
        for name in sorted(filenames):
            if name.endswith(extensions):
                yield os.path.join(dirpath, name)


def check_syntax(results):
    print("[1] syntax")
    files = list(iter_files(PACKAGE_ROOT, (".py",)))
    for path in files:
        rel = os.path.relpath(path, ADDON_ROOT)
        try:
            with open(path, "rb") as handle:
                source = handle.read()
            compile(source, path, "exec")
            results.check("compile %s" % rel, True)
        except Exception as exc:
            results.check("compile %s" % rel, False, u"-> %s" % exc)
    print("  (%d python files)" % len(files))


def check_xml(results):
    print("[2] xml")
    try:
        import xml.etree.ElementTree as ET
    except ImportError:  # pragma: no cover
        print("  (skipped: no ElementTree)")
        return
    files = list(iter_files(PACKAGE_ROOT, (".zcml", ".xml")))
    for path in files:
        rel = os.path.relpath(path, ADDON_ROOT)
        try:
            ET.parse(path)
            results.check("parse %s" % rel, True)
        except Exception as exc:
            results.check("parse %s" % rel, False, u"-> %s" % exc)
    print("  (%d xml files)" % len(files))


def check_profiles(results):
    """R4：registerProfile 声明的每个目录必须存在且含 metadata.xml。"""
    print("[3] profiles (rule R4)")
    profiles = os.path.join(PACKAGE_ROOT, "profiles")
    for name in sorted(os.listdir(profiles)):
        directory = os.path.join(profiles, name)
        if not os.path.isdir(directory):
            continue
        metadata = os.path.join(directory, "metadata.xml")
        results.check("profiles/%s/metadata.xml exists" % name,
                      os.path.isfile(metadata))
    results.check("profiles/uninstall exists (R4b: normal addon)",
                  os.path.isdir(os.path.join(profiles, "uninstall")))

    with open(os.path.join(PACKAGE_ROOT, "configure.zcml"), "rb") as handle:
        content = handle.read().decode("utf-8")
    for name in ("default", "uninstall"):
        results.check("configure.zcml registers profile '%s'" % name,
                      u'name="%s"' % name in content)
    # 移除的字段不应再出现在 schema 里（注释里提到不算）
    with open(os.path.join(PACKAGE_ROOT, "interfaces.py"), "rb") as handle:
        interfaces = handle.read().decode("utf-8")
    results.check("translation_status field removed from the schema",
                  u"translation_status = schema.Choice" not in interfaces)


def check_keys(results):
    print("[4] deterministic row id")
    from maitux.glossary.keys import make_entry_id

    first = make_entry_id(u"imp_specificity", u"imp_main_name_ref")
    second = make_entry_id(u"imp_specificity", u"imp_main_name_ref")
    results.check("same key -> same id", first == second, u"%s" % first)
    results.check("id is slug + hash", first.startswith(u"imp_specificity-"),
                  u"%s" % first)

    other = make_entry_id(u"imp_specificity", u"imp_name")
    results.check("different calc keyword -> different id", first != other)

    # 歧义坑：keyword 里合法包含 "_"，纯拼接会撞
    a = make_entry_id(u"a__b", u"c")
    b = make_entry_id(u"a", u"b__c")
    results.check("no ambiguity for '_' in keywords", a != b,
                  u"%s vs %s" % (a, b))

    # \w 在 unicode 下包含 CJK -> keyword 理论上可以含中文
    cjk = make_entry_id(u"专属性", u"imp_name")
    results.check("cjk keyword tolerated", bool(cjk) and u"-" in cjk,
                  u"%s" % cjk)


def check_seed(results):
    print("[5] new row defaults (zh/en empty, no site back-fill)")
    from maitux.glossary.sync.core import make_seed

    seed = make_seed((u"imp_chrom", u"imp_name"),
                     {"category": u"有关物质",
                      "service_title": u"有关物质-色谱",
                      "site_title": u"物质名称"})
    results.check("zh is empty by default", seed["zh"] == u"", seed.get("zh"))
    results.check("en is empty by default", seed["en"] == u"", seed.get("en"))
    results.check("site Field title is NOT copied into zh",
                  seed["zh"] != u"物质名称")
    results.check("category comes from the site",
                  seed["category"] == u"有关物质", seed.get("category"))
    results.check("analysis_keyword set", seed["analysis_keyword"] == u"imp_chrom")
    results.check("calc_keyword set", seed["calc_keyword"] == u"imp_name")
    results.check("new row starts active", seed["sync_state"] == u"active")
    results.check("no translation_status field any more",
                  u"translation_status" not in seed)


def check_plan(results):
    print("[6] sync plan (rules R1-R3)")
    from maitux.glossary.sync.core import build_plan

    as_kw = u"imp_linearity"
    calc_kw = u"imp_name"
    key = (as_kw, calc_kw)
    new_key = (u"imp_sys_suit", calc_kw)

    site_keys = {
        key: {"category": u"有关物质", "service_title": u"线性",
              "site_title": u"物质名称"},
        new_key: {"category": u"系统适用性", "service_title": u"系统适用性",
                  "site_title": u"物质名称"},
    }

    # R1: 表里没有 -> 新增（zh/en 为空）
    table = {key: {"sync_state": u"active", "zh": u"甲", "en": u"A"}}
    plan = build_plan(site_keys, table)
    results.check("R1 new key is created", plan.created == 1)
    results.check("R1 new key is the right one", plan.to_create[0][0] == new_key)
    seed = plan.to_create[0][1]
    results.check("R1 seeded zh is empty", seed["zh"] == u"", seed.get("zh"))
    results.check("R1 seeded en is empty", seed["en"] == u"", seed.get("en"))
    results.check("existing row stays untouched (unchanged=1)",
                  plan.unchanged == 1)

    # R3: 站点上没了 -> 未激活
    gone = (u"imp_gone", u"imp_name")
    table_gone = {gone: {"sync_state": u"active", "zh": u"x", "en": u""}}
    plan = build_plan({}, table_gone)
    results.check("R3 disappeared active row is deactivated",
                  plan.to_deactivate == [gone])
    results.check("R3 nothing is created or activated for it",
                  plan.created == 0 and plan.activated == 0)

    # R3: 已经是未激活且仍然不在站点上 -> 不再动它（幂等）
    table_inactive = {gone: {"sync_state": u"inactive", "zh": u"x", "en": u""}}
    plan = build_plan({}, table_inactive)
    results.check("R3 already inactive stays untouched",
                  plan.deactivated == 0 and plan.unchanged == 0)

    # R3: 重新出现 -> 对称恢复活跃
    plan = build_plan({gone: {"category": u"", "site_title": u"x"}},
                      table_inactive)
    results.check("R3 reappearing row is reactivated",
                  plan.to_activate == [gone])

    # R2: 已有的 key 完全不动；人工填的 zh 与站点不同只报告
    table_diff = {key: {"sync_state": u"active", "zh": u"表里的名字", "en": u""}}
    plan = build_plan({key: {"category": u"", "site_title": u"站点改过的名字"}},
                      table_diff)
    results.check("R2 existing row is not rewritten",
                  plan.created == 0 and len(plan.zh_mismatch) == 1)
    results.check("R2 zh mismatch carries both values",
                  plan.zh_mismatch[0][1] == u"表里的名字"
                  and plan.zh_mismatch[0][2] == u"站点改过的名字")

    # 空 zh 不算差异（默认就是空的）
    table_empty = {key: {"sync_state": u"active", "zh": u"", "en": u""}}
    plan = build_plan({key: {"category": u"", "site_title": u"物质名称"}},
                      table_empty)
    results.check("empty zh is not reported as a mismatch",
                  plan.zh_mismatch == [])

    # 非法状态值：报告出来并归一到活跃
    table_dirty = {key: {"sync_state": u"", "zh": u"", "en": u""}}
    plan = build_plan({key: {"category": u"", "site_title": u""}}, table_dirty)
    results.check("dirty sync_state is reported", len(plan.dirty_states) == 1)
    results.check("dirty sync_state is normalised to active",
                  plan.to_activate == [key])

    summary = plan.summary()
    results.check("summary has the documented shape",
                  summary == u"+0 new, 0 deactivated, 1 reactivated, 0 unchanged",
                  summary)


def check_listing_columns(results):
    print("[7] listing configuration (static)")
    with open(os.path.join(PACKAGE_ROOT, "browser", "listing.py"), "rb") as fh:
        source = fh.read().decode("utf-8")
    results.check("listing sets self.icon (viewlet icon fix)",
                  u"self.icon = LISTING_ICON" in source)
    results.check("refresh action registered in context_actions",
                  u"@@\" + SYNC_VIEW_NAME" in source or u"SYNC_VIEW_NAME" in source)
    results.check("search covers service_title", u"service_title" in source)
    results.check("no translation_status column",
                  u"translation_status" not in source)
    # autosave 会让"每次单元格变化"都发一个 set_fields，而本表保存要按
    # calc keyword 批量写同一批对象 -> 并发提交冲突 -> ConflictError 500。
    # 必须保持"手动保存"（改动入队，点 Save 才发请求）。
    # 注意只禁止**列定义**里设置它（注释里会提到这个词，不做全文否定）。
    results.check("no column enables autosave",
                  u'"autosave": True' not in source)
    with open(os.path.join(PACKAGE_ROOT, "datamanagers", "glossaryentry.py"),
              "rb") as fh:
        dm_source = fh.read().decode("utf-8")
    results.check("datamanager skips writes whose value did not change",
                  u"unchanged += 1" in dm_source)
    # core 的 ajax_set_fields 把空列表当"保存失败"并抛 500，
    # 所以"没有实际改动"的保存也必须回报一行。
    results.check("datamanager never returns an empty list",
                  u"return [self.context]" in dm_source)
    with open(os.path.join(PACKAGE_ROOT, "browser", "sync.py"), "rb") as fh:
        sync_source = fh.read().decode("utf-8")
    results.check("manual sync view exists", u"class GlossarySyncView" in sync_source)

    # 列头/筛选必须走 self.label(...)（按界面语言翻译）；裸 _(...) 会退回
    # core 的序列化路径 -- 那里不认界面语言，切英文后列头仍是中文。
    results.check("all column titles go through self.label()",
                  u'"title": self.label(_(' in source)
    results.check("no bare Message left as a column title",
                  u'"title": _(' not in source)
    results.check("listing follows the UI language (I18N_LANGUAGE / LANGUAGE)",
                  u"I18N_LANGUAGE" in source and u"language_from_request" in source)

    # 勾选行即保存：注入脚本 + 资源 + 视图件注册都要在
    js_path = os.path.join(PACKAGE_ROOT, "browser", "static",
                           "glossary_listing.js")
    results.check("row-tick save script exists", os.path.isfile(js_path))
    if os.path.isfile(js_path):
        with open(js_path, "rb") as fh:
            js = fh.read().decode("utf-8")
        results.check("script clicks the core Save button",
                      u"ajax_save_selection" in js)
        results.check("script only reacts to row checkboxes",
                      u'name="uids:list"' in js and u"tbody" in js)
    with open(os.path.join(PACKAGE_ROOT, "browser", "configure.zcml"),
              "rb") as fh:
        zcml = fh.read().decode("utf-8")
    results.check("static resource directory registered",
                  u'name="maitux.glossary"' in zcml
                  and u'directory="static"' in zcml)
    results.check("assets viewlet registered for the listing",
                  u"maitux.glossary.listing_assets" in zcml
                  and u"IAboveListingTable" in zcml)


def _install_api_stub(portal):
    """给 utils.py 装一个最小的 ``bika.lims.api`` 替身（离线自检用）。

    utils.py 只用到 ``api.get_portal`` / ``api.get_portal_type``，用假模块就能
    把"容器到底在哪个位置被找到"这段**真实逻辑**跑一遍，而不是只 grep 源码。
    """
    import types

    bika = sys.modules.get("bika") or types.ModuleType("bika")
    lims = sys.modules.get("bika.lims") or types.ModuleType("bika.lims")
    api_stub = types.ModuleType("bika.lims.api")
    api_stub.get_portal = lambda: portal
    api_stub.get_portal_type = lambda obj: getattr(obj, "portal_type", None)
    lims.api = api_stub
    bika.lims = lims
    sys.modules["bika"] = bika
    sys.modules["bika.lims"] = lims
    sys.modules["bika.lims.api"] = api_stub


class FakeFolder(object):
    """够用的 ObjectManager 替身：只取直接子对象（同 _getOb，不走 acquisition）。"""

    def __init__(self, portal_type, **children):
        self.portal_type = portal_type
        self._children = children

    def _getOb(self, child_id, default=None):
        return self._children.get(child_id, default)


def check_container_lookup(results):
    """容器定位：setup 优先、站点根兜底；读容器只允许走 get_container()。

    这一组就是 v1 -> v2（容器从站点根搬到 portal.setup）那次漏改的回归测试：
    当时 get_container() 还在站点根找，于是「从站点刷新」按钮报
    「未找到关键词对照表容器」，而列表页看起来一切正常。
    """
    print("[8] container lookup (setup folder first, site root as legacy)")
    from maitux.glossary.config import CONTAINER_TYPE
    from maitux.glossary.config import FOLDER_ID
    from maitux.glossary.config import SETUP_FOLDER_ID

    def folder(portal_type, **children):
        return FakeFolder(portal_type, **children)

    container = folder(CONTAINER_TYPE)
    setup = folder("Setup", **{FOLDER_ID: container})
    portal = folder("Plone Site", **{SETUP_FOLDER_ID: setup})
    _install_api_stub(portal)

    from maitux.glossary.utils import get_container

    results.check("container under portal.setup is found",
                  get_container(portal) is container)

    # v1 遗留：容器还在站点根（迁移还没跑）
    legacy = folder(CONTAINER_TYPE)
    legacy_portal = folder("Plone Site", **{FOLDER_ID: legacy})
    results.check("legacy container at the site root is still found",
                  get_container(legacy_portal) is legacy)

    # 两处都有 -> setup 里的优先
    root_twin = folder(CONTAINER_TYPE)
    both = folder("Plone Site",
                  **{FOLDER_ID: root_twin, SETUP_FOLDER_ID: setup})
    results.check("setup wins when both locations exist",
                  get_container(both) is container)

    # 类型不对不算命中，会继续往下找
    wrong = folder("Folder")
    wrong_setup = folder("Setup", **{FOLDER_ID: wrong})
    mixed = folder("Plone Site",
                   **{FOLDER_ID: legacy, SETUP_FOLDER_ID: wrong_setup})
    results.check("wrong portal_type under setup is skipped, root used",
                  get_container(mixed) is legacy)

    results.check("nothing anywhere -> None",
                  get_container(folder("Plone Site")) is None)
    results.check("wrong portal_type only -> None",
                  get_container(folder("Plone Site",
                                       **{SETUP_FOLDER_ID: wrong_setup}))
                  is None)

    # 静态约束：除 setuphandlers 外，任何地方都不许自己去站点根摸容器
    offenders = []
    stale_status = []
    for path in iter_files(PACKAGE_ROOT, (".py",)):
        rel = os.path.relpath(path, PACKAGE_ROOT).replace(os.sep, "/")
        if rel.startswith("tests/"):
            continue
        with open(path, "rb") as handle:
            source = handle.read().decode("utf-8")
        if "portal._getOb(FOLDER_ID" in source and rel != "setuphandlers.py":
            offenders.append(rel)
        if "translation_status" in source and rel != "interfaces.py":
            stale_status.append(rel)
    results.check("only setuphandlers touches the container at the site root",
                  not offenders, u"%s" % offenders)
    results.check("no stale translation_status references left in code",
                  not stale_status, u"%s" % stale_status)

    with open(os.path.join(PACKAGE_ROOT, "browser", "sync.py"), "rb") as fh:
        sync_source = fh.read().decode("utf-8")
    results.check("manual refresh resolves the container via get_container()",
                  "get_container()" in sync_source)


def check_translations(results):
    """翻译完整性：.po / .mo / 代码里的 msgid 三者必须一致。

    实现只有一份（``tools/verify_po.py``），这里只是调用 —— 免得"工具改了、
    测试没跟上"或者反过来。这一组专盯**静默失效**：.po 改了没重编译 .mo，
    界面上继续用旧译文，而且不报任何错。
    """
    print("[9] translations (.po vs .mo vs code msgids)")
    tools_dir = os.path.join(ADDON_ROOT, "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    try:
        import verify_po
    except Exception as exc:
        results.check("tools/verify_po.py importable", False, u"-> %s" % exc)
        return

    problems = verify_po.check()
    results.check("po / mo / code msgids are consistent",
                  not problems, u"-> %s" % (problems[:4],))
    results.check("no empty msgstr",
                  not [p for p in problems if p[0] == "empty_msgstr"])
    results.check(".mo is not stale (recompiled after .po changes)",
                  not [p for p in problems if p[0] == "stale_mo"])
    results.check("every msgid used in code exists in the .po",
                  not [p for p in problems if p[0] == "missing_in_po"])

    # 校验器自身不能空转
    msgids = verify_po.collect_code_msgids(verify_po.PACKAGE_ROOT)
    results.check("checker really found msgids in the code",
                  len(msgids) >= 20, u"found=%d" % len(msgids))
    po = verify_po.parse_po(os.path.join(
        verify_po.LOCALES_ROOT, "zh_CN", "LC_MESSAGES", "maitux.glossary.po"))
    results.check("checker parsed a multi-line msgid from the .po",
                  any(u"editable in place" in key for key in po))


def main():
    results = Results()
    check_syntax(results)
    check_xml(results)
    check_profiles(results)
    check_keys(results)
    check_seed(results)
    check_plan(results)
    check_listing_columns(results)
    check_container_lookup(results)
    check_translations(results)
    return results.report()


if __name__ == "__main__":
    sys.exit(main())
