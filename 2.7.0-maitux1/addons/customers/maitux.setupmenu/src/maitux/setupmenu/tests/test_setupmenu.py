# -*- coding: utf-8 -*-
"""maitux.setupmenu 单元测试

轻量 stub 测试（仿 maitux.groupmanagement 模式）：不依赖 Plone 运行时，
用最小桩替换外部包后直接加载目标模块验证行为，可在 Python 2/3 下运行：

    python -m unittest maitux.setupmenu.tests.test_setupmenu

覆盖：
  - api.decide_visibility：角色过滤判定（管理员/开关/启用/角色交集）
  - menus.get_menu_id：内容对象 UID / 虚拟条目 URL / 兜底 ID
  - menus.get_all_menu_items：合并 + 去重 + 排序（含 IMenuEntryProvider）
  - menumanagement.save：表单解析与写入
  - toolbar：齿轮按钮链接（管理员 vs 非管理员）
"""

import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.abspath(os.path.join(HERE, ".."))


class _Logger(object):
    """极简 logger 桩"""
    info = staticmethod(lambda *a, **k: None)
    warn = staticmethod(lambda *a, **k: None)


def _seed_maitux():
    """注入 maitux.setupmenu.config / interfaces 桩"""
    sys.modules["maitux"] = types.ModuleType("maitux")
    sys.modules["maitux.setupmenu"] = types.ModuleType("maitux.setupmenu")
    config = types.ModuleType("maitux.setupmenu.config")
    config.PROJECTNAME = "maitux.setupmenu"
    config.INSTALLED_PROPERTY = "maitux_setupmenu_installed"
    config.BROWSER_LAYER_NAME = "maitux.setupmenu"
    config.USER_SETUP_VIEW = "@@maitux-setup"
    config.MANAGEMENT_VIEW = "@@maitux-setupmenu"
    config.HIDDEN_ROLES = ["Anonymous", "Authenticated", "Owner"]
    config.ADMIN_ROLES = ["Manager", "Site Administrator"]
    sys.modules["maitux.setupmenu.config"] = config
    interfaces = types.ModuleType("maitux.setupmenu.interfaces")
    interfaces.IMenuEntryProvider = object()
    interfaces.ISetupMenuRegistry = object()
    interfaces.IMaituxSetupMenuLayer = object()
    sys.modules["maitux.setupmenu.interfaces"] = interfaces


def _seed_third_party():
    """注入 senaite.core / bika.lims / plone / zope 依赖桩"""
    sys.modules["senaite"] = types.ModuleType("senaite")
    senaite_core = types.ModuleType("senaite.core")
    senaite_core.logger = _Logger()
    sys.modules["senaite.core"] = senaite_core
    sys.modules["senaite.core.browser"] = types.ModuleType(
        "senaite.core.browser")
    sys.modules["senaite.core.browser.viewlets"] = types.ModuleType(
        "senaite.core.browser.viewlets")
    i18n = types.ModuleType("senaite.core.i18n")
    i18n.translate = lambda msg, *a, **k: msg
    sys.modules["senaite.core.i18n"] = i18n
    permissions = types.ModuleType("senaite.core.permissions")
    permissions.ManageBika = "senaite.core: Manage Bika"
    sys.modules["senaite.core.permissions"] = permissions

    sys.modules["bika"] = types.ModuleType("bika")
    bika_lims = types.ModuleType("bika.lims")
    bika_api = types.ModuleType("bika.lims.api")
    bika_lims.api = bika_api
    sys.modules["bika.lims"] = bika_lims
    sys.modules["bika.lims.api"] = bika_api
    security = types.ModuleType("bika.lims.api.security")
    # 注意：Python 2 中 staticmethod 对象不可直接调用，桩一律用普通函数
    security.check_permission = lambda *a, **k: True
    security.get_roles = lambda *a, **k: []
    sys.modules["bika.lims.api.security"] = security

    sys.modules["plone"] = types.ModuleType("plone")
    plone_api = types.ModuleType("plone.api")
    plone_api.portal = types.ModuleType("plone.api.portal")
    plone_api.portal.show_message = lambda **k: None
    sys.modules["plone.api"] = plone_api
    # 让 ``from plone import api`` 能取到 api 属性
    sys.modules["plone"].api = plone_api

    sys.modules["plone.registry"] = types.ModuleType("plone.registry")
    registry_interfaces = types.ModuleType("plone.registry.interfaces")
    registry_interfaces.IRegistry = object()
    sys.modules["plone.registry.interfaces"] = registry_interfaces

    sys.modules["Products"] = types.ModuleType("Products")
    sys.modules["Products.Five"] = types.ModuleType("Products.Five")
    five_browser = types.ModuleType("Products.Five.browser")
    five_browser.BrowserView = type("BrowserView", (object,), {})
    sys.modules["Products.Five.browser"] = five_browser
    pagetemplatefile = types.ModuleType(
        "Products.Five.browser.pagetemplatefile")
    pagetemplatefile.ViewPageTemplateFile = lambda *a, **k: None
    sys.modules["Products.Five.browser.pagetemplatefile"] = pagetemplatefile

    zope = types.ModuleType("zope")
    zope_component = types.ModuleType("zope.component")
    zope_component.getUtility = lambda *a, **k: None
    zope_component.getUtilitiesFor = lambda *a, **k: iter([])
    sys.modules["zope"] = zope
    sys.modules["zope.component"] = zope_component


class _NS(object):
    """极简命名空间对象（兼容 Python 2/3，替代 types.SimpleNamespace）"""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def _load_module(name, relpath):
    """从 add-on 包内按相对路径加载模块（兼容 Python 2/3）

    加载后注册进 sys.modules，使模块间的 ``from maitux.setupmenu.xxx import``
    能找到目标（与真实运行一致）。
    """
    path = os.path.abspath(os.path.join(PKG, relpath))
    if sys.version_info[0] >= 3:
        import importlib.util
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    else:
        import imp
        module = imp.load_source(name, path)
    sys.modules[name] = module
    return module


class TestDecideVisibility(unittest.TestCase):
    """api.decide_visibility 纯判定逻辑"""

    @classmethod
    def setUpClass(cls):
        _seed_maitux()
        _seed_third_party()
        cls.api = _load_module("maitux.setupmenu.api", "api.py")

    def test_admin_always_visible(self):
        d = self.api.decide_visibility
        self.assertTrue(d(False, [], [], admin=True, filtering=True))
        self.assertTrue(d(True, [], ["X"], admin=True, filtering=True))

    def test_filtering_disabled_all_visible(self):
        d = self.api.decide_visibility
        self.assertTrue(d(False, [], [], admin=False, filtering=False))
        self.assertTrue(d(False, ["LabClerk"], ["LabManager"],
                          admin=False, filtering=False))

    def test_disabled_menu_hidden(self):
        d = self.api.decide_visibility
        self.assertFalse(d(False, ["LabClerk"], ["LabClerk"],
                           admin=False, filtering=True))

    def test_role_intersection(self):
        d = self.api.decide_visibility
        self.assertTrue(d(True, ["LabClerk", "LabManager"], ["LabClerk"],
                          admin=False, filtering=True))
        self.assertFalse(d(True, ["LabClerk"], ["LabManager"],
                           admin=False, filtering=True))
        self.assertFalse(d(True, [], ["LabClerk"],
                           admin=False, filtering=True))

    def test_is_admin_role_based(self):
        """is_admin 按 Manager / Site Administrator 角色判定
        （回归：曾用 ManageBika 权限判定，导致 LabClerk/LabManager 也当管理员）"""
        module = self.api
        try:
            module.get_roles = lambda user=None: ["Authenticated", "Manager"]
            self.assertTrue(module.is_admin())
            module.get_roles = lambda user=None: ["Site Administrator"]
            self.assertTrue(module.is_admin())
            # 关键回归：LabClerk / LabManager 不是管理员
            module.get_roles = lambda user=None: ["Authenticated", "LabClerk"]
            self.assertFalse(module.is_admin())
            module.get_roles = lambda user=None: ["LabManager"]
            self.assertFalse(module.is_admin())
            module.get_roles = lambda user=None: ["Authenticated", "Analyst"]
            self.assertFalse(module.is_admin())
            module.get_roles = lambda user=None: []
            self.assertFalse(module.is_admin())
        finally:
            del module.get_roles


class TestGetMenuId(unittest.TestCase):
    """menus.get_menu_id 稳定 ID 生成"""

    class _Content(object):
        def UID(self):
            return "abc123"

        def absolute_url(self):
            return "http://nohost/plone/setup/foo"

    class _Virtual(object):
        def absolute_url(self):
            return "http://nohost/plone/@@maitux-group-management"

    class _VirtualAttr(object):
        """模拟 maitux.groupmanagement 的 SetupEntry：
        Title / absolute_url 都是普通字符串属性（非方法），
        absolute_url 为完整 URL。回归：曾导致 api.get_id 抛异常。"""

        def __init__(self, title="Group Management",
                     url="http://nohost/plone/@@maitux-group-management"):
            self.Title = title
            self.absolute_url = url

        def objectIds(self):
            return []

    class _Fallback(object):
        pass

    @classmethod
    def setUpClass(cls):
        _seed_maitux()
        _seed_third_party()
        cls.menus = _load_module("maitux.setupmenu.menus", "menus.py")

    def test_content_uid(self):
        self.assertEqual(
            self.menus.get_menu_id(self._Content()), "uid:abc123")

    def test_virtual_url(self):
        self.assertEqual(
            self.menus.get_menu_id(self._Virtual()),
            "url:http://nohost/plone/@@maitux-group-management")

    def test_virtual_string_url_attr(self):
        """SetupEntry 风格：absolute_url 为字符串属性，不抛异常"""
        entry = self._VirtualAttr()
        self.assertEqual(
            self.menus.get_menu_id(entry),
            "url:http://nohost/plone/@@maitux-group-management")

    def test_fallback_id(self):
        """既无 UID 又无 URL 的未知对象：走 _safe_object_id，不调用 bika api"""
        self.assertTrue(
            self.menus.get_menu_id(self._Fallback()).startswith("id:"))


class TestGetAllMenuItems(unittest.TestCase):
    """menus.get_all_menu_items 合并/去重/排序"""

    class _Content(object):
        def __init__(self, title):
            self._title = title

        def UID(self):
            # 真实内容对象的 UID 是不带前缀的十六进制字符串
            return self._title.lower()

        @property
        def Title(self):
            return self._title

        def absolute_url(self):
            return "http://nohost/plone/setup/%s" % self._title

    class _Virtual(object):
        def __init__(self, title):
            self._title = title

        @property
        def Title(self):
            return self._title

        def absolute_url(self):
            return "http://nohost/plone/@@%s" % self._title

    class _SetupEntry(object):
        """模拟 maitux.groupmanagement 的 SetupEntry（回归真实崩溃场景）：
        Title / absolute_url 为字符串属性，objectIds() 返回空列表"""

        def __init__(self, title, url):
            self.Title = title
            self.absolute_url = url

        def objectIds(self):
            return []

    @classmethod
    def setUpClass(cls):
        _seed_maitux()
        _seed_third_party()
        cls.menus = _load_module("maitux.setupmenu.menus", "menus.py")

    def _stub_environment(self, setup_items, providers):
        menus = self.menus
        menus.api.get_portal = lambda: _NS(
            absolute_url=lambda: "http://nohost/plone")
        menus.api.get_request = lambda: object()
        menus.api.get_view = lambda name, portal, request: _NS(
            setupitems=lambda: list(setup_items))
        menus.getUtilitiesFor = lambda iface: list(providers)

    def test_merge_dedup_sort(self):
        items = [
            self._Content("Beta"),
            self._Virtual("Alpha Virtual"),
        ]
        providers = [
            ("p1", _NS(get_menu_entries=lambda: [{
                "menu_id": "p1.one",
                "title": "Provider One",
                "url": "/@@provider-one",
            }])),
            ("p2", _NS(get_menu_entries=lambda: [{
                # 与 Beta 内容对象 UID 重复（uid:beta）-> 应被去重
                "menu_id": "uid:beta",
                "title": "Duplicated Beta",
                "url": "/@@dup",
            }])),
        ]
        self._stub_environment(items, providers)
        result = self.menus.get_all_menu_items()
        titles = [self.menus.get_item_title(item) for item in result]
        # 排序：Alpha Virtual, Beta, Provider One
        self.assertEqual(titles, ["Alpha Virtual", "Beta", "Provider One"])
        # 去重后共 3 条
        self.assertEqual(len(result), 3)
        # provider 条目被包装为 MenuEntryProxy，可渲染
        proxy = result[-1]
        self.assertEqual(proxy.absolute_url,
                         "http://nohost/plone/@@provider-one")

    def test_with_setupentry_style_virtual(self):
        """有效 lims-setup 视图返回 SetupEntry 风格虚拟条目时不崩溃（回归）"""
        items = [
            self._Content("Analysis Categories"),
            self._SetupEntry(
                "Group Management",
                "http://nohost/plone/@@maitux-group-management"),
        ]
        self._stub_environment(items, [])
        result = self.menus.get_all_menu_items()
        titles = [self.menus.get_item_title(item) for item in result]
        self.assertEqual(
            titles, ["Analysis Categories", "Group Management"])
        # SetupEntry 风格条目能生成稳定 menu_id
        ids = [self.menus.get_menu_id(item) for item in result]
        self.assertIn("url:http://nohost/plone/@@maitux-group-management",
                      ids)


class TestManagementSave(unittest.TestCase):
    """browser.menumanagement 表单解析"""

    class _Request(object):
        def __init__(self, form):
            self.form = form

    @classmethod
    def setUpClass(cls):
        _seed_maitux()
        _seed_third_party()
        # 先加载被依赖的模块（保证顺序无关）
        _load_module("maitux.setupmenu.api", "api.py")
        _load_module("maitux.setupmenu.menus", "menus.py")
        cls.module = _load_module(
            "maitux.setupmenu.browser.menumanagement",
            "browser/menumanagement.py")

    def test_save_parses_rows(self):
        module = self.module
        calls = []

        module.set_filtering_enabled = lambda enabled: calls.append(
            ("filtering", enabled))
        module.set_menu_config = lambda menu_id, enabled, roles: calls.append(
            ("config", menu_id, enabled, roles))

        form = {
            "filtering_enabled": "1",
            "menu_id_0": "uid:aaa",
            "enabled_0": "1",
            "roles_0:list": ["LabClerk", "LabManager"],
            "menu_id_1": "uid:bbb",      # 未启用、无角色
            "menu_id_2": "uid:ccc",
            "enabled_2": "1",
            "roles_2:list": ["", "Sampler"],  # 空串应被过滤
        }
        request = self._Request(form)
        view = module.SetupMenuManagementView.__new__(
            module.SetupMenuManagementView)
        view.request = request
        view.save(form)

        self.assertIn(("filtering", True), calls)
        self.assertIn(("config", "uid:aaa", True, ["LabClerk", "LabManager"]),
                      calls)
        self.assertIn(("config", "uid:bbb", False, []), calls)
        self.assertIn(("config", "uid:ccc", True, ["Sampler"]), calls)

    def test_get_submitted_roles_variants(self):
        """_get_submitted_roles 兼容 ZPublisher 对 :list 的多种处理形态"""
        getter = self.module.SetupMenuManagementView._get_submitted_roles
        # 1. 标准 :list 形态
        form = {"roles_0:list": ["LabClerk", "LabManager"]}
        self.assertEqual(getter(form, 0), ["LabClerk", "LabManager"])
        # 2. 标记被剥离到同名 key
        form = {"roles_0": ["LabClerk"]}
        self.assertEqual(getter(form, 0), ["LabClerk"])
        # 3. 单值字符串（整体作为一个角色，不拆字符）
        form = {"roles_0:list": "LabClerk"}
        self.assertEqual(getter(form, 0), ["LabClerk"])
        # 4. 缺失/未勾选
        self.assertEqual(getter({}, 0), [])
        # 5. 空串过滤
        form = {"roles_0:list": ["", "Sampler", ""]}
        self.assertEqual(getter(form, 0), ["Sampler"])
        # 6. 其它行不受影响
        form = {"roles_1:list": ["LabManager"]}
        self.assertEqual(getter(form, 0), [])
        self.assertEqual(getter(form, 1), ["LabManager"])


class TestToolbar(unittest.TestCase):
    """browser.toolbar 齿轮按钮链接"""

    class _Portal(object):
        def absolute_url(self):
            return "http://nohost/plone"

    class _PortalState(object):
        def __init__(self, anonymous=False):
            self._anonymous = anonymous

        def anonymous(self):
            return self._anonymous

        def portal(self):
            return TestToolbar._Portal()

    class _BaseToolbar(object):
        def __init__(self):
            self.portal_state = TestToolbar._PortalState()

    @classmethod
    def setUpClass(cls):
        _seed_maitux()
        _seed_third_party()
        toolbar_mod = types.ModuleType(
            "senaite.core.browser.viewlets.toolbar")
        toolbar_mod.ToolbarViewletManager = cls._BaseToolbar
        sys.modules["senaite.core.browser.viewlets.toolbar"] = toolbar_mod
        cls.module = _load_module(
            "maitux.setupmenu.browser.toolbar", "browser/toolbar.py")

    def test_manager_gets_lims_setup(self):
        module = self.module
        module.get_roles = lambda *a, **k: ["Authenticated", "Manager"]
        view = module.ToolbarViewletManager()
        self.assertTrue(view.is_manager())
        self.assertEqual(view.get_lims_setup_url(),
                         "http://nohost/plone/@@lims-setup")

    def test_labclerk_gets_new_setup(self):
        """回归：LabClerk 持有 ManageBika 但不是管理员 → 齿轮去新界面"""
        module = self.module
        module.get_roles = lambda *a, **k: ["Authenticated", "LabClerk"]
        view = module.ToolbarViewletManager()
        self.assertTrue(view.is_manager())
        self.assertEqual(view.get_lims_setup_url(),
                         "http://nohost/plone/@@maitux-setup")

    def test_analyst_gets_new_setup(self):
        module = self.module
        module.get_roles = lambda *a, **k: ["Authenticated", "Analyst"]
        view = module.ToolbarViewletManager()
        self.assertTrue(view.is_manager())
        self.assertEqual(view.get_lims_setup_url(),
                         "http://nohost/plone/@@maitux-setup")

    def test_anonymous_no_gear(self):
        module = self.module
        view = module.ToolbarViewletManager()
        view.portal_state = self._PortalState(anonymous=True)
        self.assertFalse(view.is_manager())


if __name__ == "__main__":
    unittest.main()
