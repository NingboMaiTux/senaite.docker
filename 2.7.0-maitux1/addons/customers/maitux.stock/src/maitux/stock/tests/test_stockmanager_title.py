# -*- coding: utf-8 -*-
import os
import sys
import types
import unittest


# 中文注释：标题存的是**英文 msgid**，运行时按语言翻译：
#   英文站 -> "Stock Inventory"（locales/en 同义条目）
#   中文站 -> "库存管理"（locales/zh*/ 条目）
# 所以这里断言常量是英文 msgid，另外单独断言中文目录里有对应译文。
EXPECTED_TITLE = u"Stock Inventory"
EXPECTED_ZH_TITLE = u"库存管理"
LEGACY_TITLE = u"Stockinventory"

class Namespace(object):
    """Python 2.7 下替代 types.SimpleNamespace 的最小实现。"""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def load_module_from_path(file_path, name):
    """按路径加载模块，兼容 Python 2.7（imp）与 3.x（importlib.util）。"""
    try:
        import importlib.util
    except ImportError:
        import imp
        return imp.load_source(name, file_path)

    spec = importlib.util.spec_from_file_location(name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_setuphandlers_module():
    """加载 setuphandlers 模块，并用最小桩替换外部依赖。"""
    api_module = Namespace(
        get_tool=lambda name: None,
    )

    sys.modules["bika"] = types.ModuleType("bika")
    sys.modules["bika.lims"] = types.ModuleType("bika.lims")
    sys.modules["bika.lims"].api = api_module
    sys.modules["bika.lims.api"] = api_module

    plone_api_module = types.ModuleType("plone.api")
    plone_module = types.ModuleType("plone")
    plone_module.api = plone_api_module
    sys.modules["plone"] = plone_module
    sys.modules["plone.api"] = plone_api_module

    products_module = types.ModuleType("Products")
    cmfplone_module = types.ModuleType("Products.CMFPlone")
    interfaces_module = types.ModuleType("Products.CMFPlone.interfaces")
    interfaces_module.INonInstallable = object
    sys.modules["Products"] = products_module
    sys.modules["Products.CMFPlone"] = cmfplone_module
    sys.modules["Products.CMFPlone.interfaces"] = interfaces_module

    senaite_core_module = types.ModuleType("senaite.core")
    senaite_core_module.logger = Namespace(info=lambda *args, **kwargs: None)
    sys.modules["senaite"] = types.ModuleType("senaite")
    sys.modules["senaite.core"] = senaite_core_module

    interface_module = types.ModuleType("zope.interface")
    interface_module.implementer = lambda *ifaces: (lambda cls: cls)
    sys.modules["zope"] = types.ModuleType("zope")
    sys.modules["zope.interface"] = interface_module

    maitux_module = types.ModuleType("maitux")
    stock_package = types.ModuleType("maitux.stock")
    # 中文注释：真环境里 MessageFactory 产出 zope.i18nmessageid.Message
    # （unicode 子类，文本即 msgid）；桩按同一语义返回 msgid。
    stock_package.stockMessageFactory = lambda msgid, **kwargs: msgid
    config_module = types.ModuleType("maitux.stock.config")
    config_module.PROJECTNAME = "maitux.stock"
    # 中文注释：setuphandlers 现在还会从 config 导入领用申请单的类型/工作流常量，
    # 桩模块漏了它们会 ImportError（测试直接报错，而不是断言失败）。
    config_module.USAGE_REQUEST_TYPE = "StockUsageRequest"
    config_module.USAGE_REQUEST_WORKFLOW = "senaite_stockusagerequest_workflow"
    expiry_module = types.ModuleType("maitux.stock.stockbatchexpiry")
    expiry_module.REVIEW_STATE_ACTIVE = u"active"
    expiry_module.REVIEW_STATE_DESTROYED = u"destroyed"
    expiry_module.expire_batch = lambda *args, **kwargs: False
    expiry_module.is_due_for_expiry = lambda *args, **kwargs: False
    expiry_module.set_status_value = lambda *args, **kwargs: False
    sys.modules["maitux"] = maitux_module
    sys.modules["maitux.stock"] = stock_package
    sys.modules["maitux.stock.config"] = config_module
    sys.modules["maitux.stock.stockbatchexpiry"] = expiry_module

    file_path = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "setuphandlers.py"))
    module = load_module_from_path(file_path, "test_setuphandlers_module")
    return module


def load_stockmanagerfix_module():
    """加载 stockmanagerfix 模块，并用最小桩替换外部依赖。"""
    browser_module = types.ModuleType("Products.Five.browser")
    browser_module.BrowserView = object
    sys.modules["Products"] = types.ModuleType("Products")
    sys.modules["Products.Five"] = types.ModuleType("Products.Five")
    sys.modules["Products.Five.browser"] = browser_module

    api_module = Namespace(
        get_portal_type=lambda obj: getattr(obj, "portal_type", ""),
        get_url=lambda obj: "/stockmanager",
        safe_unicode=lambda value: u"" if value is None else u"{}".format(value),
    )
    sys.modules["bika"] = types.ModuleType("bika")
    sys.modules["bika.lims"] = types.ModuleType("bika.lims")
    sys.modules["bika.lims"].api = api_module
    sys.modules["bika.lims.api"] = api_module
    sys.modules["bika.lims"].senaiteMessageFactory = lambda value: value

    file_path = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "browser", "stockmanagerfix.py"))
    module = load_module_from_path(file_path, "test_stockmanagerfix_module")
    return module


class DummyResponse(object):
    def redirect(self, url):
        return url


class DummyContext(object):
    portal_type = "StockManager"

    def __init__(self):
        self._title = u"Wrong title"
        self.plone_utils = Namespace(
            addPortalMessage=lambda *args, **kwargs: None)

    def Title(self):
        return self._title

    def setTitle(self, value):
        self._title = value

    def reindexObject(self):
        return None

    def objectIds(self):
        return []

    def get(self, key):
        return None


class TestStockManagerTitle(unittest.TestCase):

    def test_setuphandlers_title_constant_is_correct(self):
        """安装脚本里的标题常量应是英文 msgid，且不再是旧拼写。"""
        module = load_setuphandlers_module()
        self.assertEqual(module.STOCK_MANAGER_TITLE, EXPECTED_TITLE)
        self.assertNotEqual(module.STOCK_MANAGER_TITLE, LEGACY_TITLE)

    def test_stockmanager_fix_view_uses_correct_title(self):
        """修复视图应把标题刷成约定的英文 msgid（不能改回旧英文）。"""
        module = load_stockmanagerfix_module()
        context = DummyContext()
        request = Namespace(response=DummyResponse())
        view = module.StockStructureFixView()
        view.context = context
        view.request = request

        view()

        self.assertEqual(context.Title(), EXPECTED_TITLE)

    def test_stockmanager_xml_title_is_correct(self):
        """类型定义中的默认标题应是英文 msgid，且不含 Stcok 拼写错误。"""
        file_path = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "profiles", "default", "types", "StockManager.xml"))
        # 中文注释：必须按 UTF-8 读成 unicode，否则中文断言在 py3 下直接 TypeError。
        import io as _io
        with _io.open(file_path, encoding="utf-8") as handle:
            xml_text = handle.read()

        self.assertIn(EXPECTED_TITLE, xml_text)
        self.assertNotIn("Stcokinventory", xml_text)
        self.assertNotIn(LEGACY_TITLE, xml_text)

    def test_catalogs_translate_the_title(self):
        """中英双语的落点：en 目录同义、zh 目录给中文。

        只改常量为英文 msgid 是不够的 —— 没有目录条目时中文站会显示英文，
        所以这里把"目录里必须有对应译文"变成断言。
        """
        import io as _io
        base = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "locales",
            "%s", "LC_MESSAGES", "maitux.stock.po"))
        for lang, expected in (("en", EXPECTED_TITLE), ("zh_CN", EXPECTED_ZH_TITLE)):
            with _io.open(base % lang, encoding="utf-8") as handle:
                text = handle.read()
            self.assertIn(u'msgid "%s"' % EXPECTED_TITLE, text,
                          u"%s 目录缺少 msgid" % lang)
            self.assertIn(u'msgstr "%s"' % expected, text,
                          u"%s 目录缺少译文 %s" % (lang, expected))
