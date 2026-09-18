# -*- coding: utf-8 -*-
"""全局审计日志强制开启 —— 源码 / 纯逻辑回归测试

不需要 Plone，本机 Python 2.7 直接跑：

    cd <addon>/src/maitux/globalauditlog/tests
    python -m unittest test_sources

为什么值得钉这些点：本包全部动作都是「静默」的 —— 字段名写错、
`for=` 里漏了 layer、`<subscriber>` 写成 `factory=`、profile 目录名拼错，
都不会在启动期报错，而是「改了没生效」（R9 的静默失效清单）。

判定一律读**真实结构**（XML 属性、AST 调用），不靠 grep 注释 ——
本包的注释里就写着反面写法（core 的原注册、`setEnableGlobalAuditlog(False)`
的危害），拿字符串搜索会被自己的说明文字绊倒。
"""

import ast
import os
import sys
import unittest
import xml.etree.ElementTree as ET


TESTS_DIR = os.path.abspath(os.path.dirname(__file__))
PACKAGE_DIR = os.path.abspath(os.path.join(TESTS_DIR, os.pardir))
SRC_DIR = os.path.abspath(os.path.join(PACKAGE_DIR, os.pardir, os.pardir))

INTERFACES_SOURCE = os.path.join(PACKAGE_DIR, "interfaces.py")
CONFIGURE_ZCML = os.path.join(PACKAGE_DIR, "configure.zcml")
BROWSER_ZCML = os.path.join(PACKAGE_DIR, "browser", "configure.zcml")
ADAPTER_SOURCE = os.path.join(PACKAGE_DIR, "browser", "senaitesetup.py")
SUBSCRIBERS_SOURCE = os.path.join(PACKAGE_DIR, "subscribers.py")
SETUPHANDLERS_SOURCE = os.path.join(PACKAGE_DIR, "setuphandlers.py")
SITEINSTALL_SOURCE = os.path.join(PACKAGE_DIR, "siteinstall.py")
BROWSERLAYER_XML = os.path.join(
    PACKAGE_DIR, "profiles", "default", "browserlayer.xml")
DEFAULT_MARKER = os.path.join(
    PACKAGE_DIR, "profiles", "default", "maitux.globalauditlog.txt")
UNINSTALL_MARKER = os.path.join(
    PACKAGE_DIR, "profiles", "uninstall", "maitux.globalauditlog-uninstall.txt")
UNINSTALL_METADATA = os.path.join(
    PACKAGE_DIR, "profiles", "uninstall", "metadata.xml")

# siteinstall.py 只依赖标准库 + 包自身的常量，所以可以脱离 Zope 直接 import
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from maitux.globalauditlog import AUDITLOG_FIELD_NAME  # noqa: E402
from maitux.globalauditlog import AUDITLOG_FORM_FIELD  # noqa: E402
from maitux.globalauditlog import PROFILE_ID  # noqa: E402
from maitux.globalauditlog import PROJECTNAME  # noqa: E402
from maitux.globalauditlog.siteinstall import (  # noqa: E402
    is_profile_version_installed,
)


def read_source(path):
    handle = open(path, "r")
    try:
        return handle.read()
    finally:
        handle.close()


def elements_by_localname(path, localname):
    """按本地名取 ZCML 元素（照不上命名空间前缀）"""
    root = ET.parse(path).getroot()
    return [el for el in root.iter() if el.tag.split("}")[-1] == localname]


def setter_call_arguments(path, attr_name):
    """AST 扫出 `*.attr_name(...)` 的位置参数字面量

    `True` 在 Py2.7 是 ast.Name，Py3 是 ast.NameConstant，两种都收。
    """
    found = []
    for node in ast.walk(ast.parse(read_source(path))):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != attr_name:
            continue
        for arg in node.args:
            if isinstance(arg, ast.Name):
                found.append(arg.id)
            elif hasattr(ast, "NameConstant") and isinstance(
                    arg, ast.NameConstant):
                found.append(str(arg.value))
            elif isinstance(arg, ast.Num):
                found.append(str(arg.n))
    return found


class TestConstants(unittest.TestCase):
    """字段名是本包唯一「写错也不报错」的地方，必须钉住"""

    def test_profile_id_matches_project_name(self):
        self.assertEqual(PROJECTNAME, "maitux.globalauditlog")
        self.assertEqual(PROFILE_ID, "maitux.globalauditlog:default")

    def test_field_names_match_senaite_core_schema(self):
        """与 senaite.core 的 Setup schema 字段名逐字对齐

        senaite/core/content/senaitesetup.py:

            enable_global_auditlog = schema.Bool(
                title=_(u"Enable global Auditlog"), ...)

        注意是 `auditlog` 一个词，不是 `audit_log`。
        """
        self.assertEqual(AUDITLOG_FIELD_NAME, "enable_global_auditlog")
        self.assertEqual(
            AUDITLOG_FORM_FIELD, "form.widgets.enable_global_auditlog")


class TestProfileVersionPredicate(unittest.TestCase):
    """「本包装在这个站点上了吗」的判定 —— 未安装站点绝不能被改写（R14）"""

    def test_uninstalled_is_false(self):
        self.assertFalse(is_profile_version_installed("unknown"))
        self.assertFalse(is_profile_version_installed(u"unknown"))
        self.assertFalse(is_profile_version_installed(None))
        self.assertFalse(is_profile_version_installed(""))
        self.assertFalse(is_profile_version_installed([]))
        self.assertFalse(is_profile_version_installed(()))

    def test_installed_shapes_are_true(self):
        # portal_setup 实测既可能返回字符串，也可能返回版本元组
        self.assertTrue(is_profile_version_installed("1000"))
        self.assertTrue(is_profile_version_installed(u"1000"))
        self.assertTrue(is_profile_version_installed((u"1000",)))
        self.assertTrue(is_profile_version_installed([u"1000"]))

    def test_tuple_of_unknown_is_false(self):
        self.assertFalse(is_profile_version_installed((u"unknown",)))
        self.assertFalse(is_profile_version_installed([u"unknown"]))


class TestBrowserLayer(unittest.TestCase):
    """layer 必须继承 IBrowserRequest，否则适配器可能不被选中"""

    def test_layer_extends_browser_request(self):
        """请求槽上的接口必须是 core 那个 IBrowserRequest 的真子接口

        core 的注册用 IBrowserRequest，本包用 IGlobalAuditLogLayer；
        两条都会匹配同一请求，Zope 挑更具体的一条 —— 只有本层是
        IBrowserRequest 的子接口时才是「更具体」。
        """
        source = read_source(INTERFACES_SOURCE)
        self.assertIn(
            "from zope.publisher.interfaces.browser import IBrowserRequest",
            source)
        self.assertIn("from senaite.core.interfaces import ISenaiteCore", source)
        self.assertIn(
            "class IGlobalAuditLogLayer(ISenaiteCore, IBrowserRequest):",
            source)

    def test_layer_registered_in_profile(self):
        source = read_source(BROWSERLAYER_XML)
        self.assertIn('name="maitux.globalauditlog"', source)
        self.assertIn(
            'interface="maitux.globalauditlog.interfaces.IGlobalAuditLogLayer"',
            source)


class TestEditFormAdapter(unittest.TestCase):
    """设置表单适配器：隐藏 + 强制勾选，且必须 layer 门控（R14）"""

    def test_adapter_is_gated_by_own_layer(self):
        adapters = elements_by_localname(BROWSER_ZCML, "adapter")
        self.assertEqual(len(adapters), 1)
        for_ = adapters[0].get("for", "")
        self.assertIn("senaite.core.interfaces.ISetup", for_)
        self.assertIn(
            "maitux.globalauditlog.interfaces.IGlobalAuditLogLayer", for_)
        # 「外来内容 + 任意请求」这一对就是没门控，会被 R14 判 W17
        self.assertNotIn("IBrowserRequest", for_)
        self.assertIn("IGlobalAuditLogLayer", for_)
        self.assertEqual(
            adapters[0].get("provides"),
            "senaite.core.interfaces.IAjaxEditForm")
        self.assertEqual(
            adapters[0].get("factory"), ".senaitesetup.EditForm")

    def test_adapter_hides_and_forces_checkbox(self):
        source = read_source(ADAPTER_SOURCE)
        self.assertIn("from maitux.globalauditlog import AUDITLOG_FORM_FIELD",
                      source)
        self.assertIn("self.add_hide_field(AUDITLOG_FORM_FIELD)", source)
        self.assertIn("self.add_update_field(AUDITLOG_FORM_FIELD, True)",
                      source)
        # 继承 core 的适配器，core 的联动行为必须原样保留（R6）
        self.assertIn("class EditForm(BaseEditForm):", source)
        self.assertIn("super(EditForm, self).initialized(data)", source)
        self.assertIn("super(EditForm, self).modified(data)", source)

    def test_adapter_never_hardcodes_the_field_name(self):
        """控件名只能来自常量，防止两种拼法各写一遍后漂移"""
        source = read_source(ADAPTER_SOURCE)
        self.assertNotIn('"form.widgets.', source)

    def test_modified_reads_name_before_calling_base(self):
        """★ 写这个包时真的踩过：基类返回的是 `self.data`（发给前端的
        指令字典），**不是**传进去的那份 payload。所以

            data = super(EditForm, self).modified(data)
            if data.get("name") == AUDITLOG_FORM_FIELD:   # 永远不成立

        不报错，只是兜底静默失效（R9）。`name` 必须先取出来。
        """
        source = read_source(ADAPTER_SOURCE)
        body = source.split("def modified(self, data):", 1)[1]
        body = body.split("def ", 1)[0]
        self.assertEqual(body.count('data.get("name")'), 1)
        self.assertLess(
            body.index('name = data.get("name")'),
            body.index("super(EditForm, self).modified(data)"))
        self.assertIn("if name == AUDITLOG_FORM_FIELD:", body)


class TestRuntimeEnforcement(unittest.TestCase):
    """服务端兜底：未安装站点必须放行，已安装站点必须钉回 True"""

    def test_subscriber_is_registered_with_handler_not_factory(self):
        subscribers = elements_by_localname(CONFIGURE_ZCML, "subscriber")
        self.assertEqual(len(subscribers), 1)
        el = subscribers[0]
        # R15：普通函数用 handler=。写成 factory= 时 ZCML 加载期就抛
        # "TypeError: You must specify a provided interface...", 容器无限重启
        self.assertIsNone(el.get("factory"))
        self.assertIsNone(el.get("provides"))
        self.assertEqual(
            el.get("handler"),
            "maitux.globalauditlog.subscribers.on_senaite_setup_modified")
        self.assertIn("senaite.core.interfaces.ISetup", el.get("for", ""))
        self.assertIn(
            "zope.lifecycleevent.interfaces.IObjectModifiedEvent",
            el.get("for", ""))

    def test_subscriber_gates_on_site_installation(self):
        source = read_source(SUBSCRIBERS_SOURCE)
        self.assertIn("from maitux.globalauditlog.siteinstall import "
                      "is_installed_in_current_site", source)
        self.assertIn("if not is_installed_in_current_site():", source)

    def test_subscriber_only_ever_enables(self):
        self.assertEqual(
            setter_call_arguments(SUBSCRIBERS_SOURCE,
                                  "setEnableGlobalAuditlog"),
            ["True"])

    def test_siteinstall_checks_both_records(self):
        source = read_source(SITEINSTALL_SOURCE)
        self.assertIn("getLastVersionForProfile", source)
        self.assertIn("isProductInstalled", source)
        # 取不到站点按「未安装」处理：宁可不动，也不能改别人的站点
        self.assertIn("return False", source)


class TestInstallHandlers(unittest.TestCase):
    """安装/卸载 handler 与 profile 文件"""

    def test_setuphandler_enables_only_true(self):
        self.assertEqual(
            setter_call_arguments(SETUPHANDLERS_SOURCE,
                                  "setEnableGlobalAuditlog"),
            ["True"])

    def test_setuphandler_is_idempotent(self):
        source = read_source(SETUPHANDLERS_SOURCE)
        # 只在未开启时才写 —— 每次写都会触发 IObjectModifiedEvent
        self.assertIn("if setup.getEnableGlobalAuditlog():", source)

    def test_setuphandler_entrypoints(self):
        source = read_source(SETUPHANDLERS_SOURCE)
        # 包名只有一处定义（__init__.py），这里只许引用
        self.assertIn("from maitux.globalauditlog import PROJECTNAME", source)
        self.assertNotIn('PROJECTNAME = "', source)
        self.assertIn("@implementer(INonInstallable)", source)
        self.assertIn("class HiddenProfiles(object):", source)
        self.assertIn("def enable_global_auditlog():", source)
        self.assertIn("def setup_handler(context):", source)
        self.assertIn("def uninstall_handler(context):", source)
        self.assertIn("def import_various(context):", source)

    def test_profiles_are_registered_and_import_steps_bound(self):
        source = read_source(CONFIGURE_ZCML)
        self.assertIn('factory=".setuphandlers.HiddenProfiles"', source)
        self.assertIn('directory="profiles/default"', source)
        self.assertIn('directory="profiles/uninstall"', source)
        self.assertIn(
            'handler="maitux.globalauditlog.setuphandlers.setup_handler"',
            source)
        self.assertIn(
            'handler="maitux.globalauditlog.setuphandlers.uninstall_handler"',
            source)

    def test_profile_files_exist(self):
        self.assertTrue(os.path.isfile(DEFAULT_MARKER))
        self.assertTrue(os.path.isfile(UNINSTALL_MARKER))
        self.assertTrue(os.path.isfile(UNINSTALL_METADATA))
        self.assertTrue(os.path.isfile(BROWSERLAYER_XML))


if __name__ == "__main__":
    unittest.main()
