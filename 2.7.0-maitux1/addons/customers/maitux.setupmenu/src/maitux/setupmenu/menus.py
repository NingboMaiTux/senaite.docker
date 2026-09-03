# -*- coding: utf-8 -*-
"""Setup 菜单条目收集

收集范围（与 ``@@lims-setup`` 页面所见一致，并自动覆盖 addon 追加的条目）：

1. **生效的 @@lims-setup 视图的 ``setupitems()``**
   包含 setup/bika_setup 文件夹的内容对象，以及其它 addon
   （如 maitux.groupmanagement）通过覆盖该视图追加的虚拟条目。
2. **所有注册的 ``IMenuEntryProvider``**
   面向未来 addon 的声明式注册 API（见 interfaces.IMenuEntryProvider）。

新增 addon 时无需改动本模块：内容建在 setup/bika_setup 文件夹里，
或按 ``IMenuEntryProvider`` 注册条目，即可被自动识别并进入管理界面。
"""

from bika.lims import api
from senaite.core.i18n import translate as t
from zope.component import getUtilitiesFor

from maitux.setupmenu.interfaces import IMenuEntryProvider


class MenuEntryProxy(object):
    """把 IMenuEntryProvider 返回的 dict 包装成类对象，供模板渲染

    提供模板所需的最小子集：``Title`` / ``absolute_url`` / ``objectIds``。
    """

    def __init__(self, menu_id, data):
        self.menu_id = menu_id
        self.data = data
        self.title = data.get("title") or menu_id
        self.url = data.get("url") or ""
        self.icon = data.get("icon") or ""
        self.default_enabled = data.get("enabled", True)

    def Title(self):
        """方法形式，兼容 bika.lims.api.get_title 的 ``Title()`` 调用约定"""
        return self.title

    @property
    def absolute_url(self):
        portal = api.get_portal()
        url = self.url
        if url.startswith("/"):
            return portal.absolute_url() + url
        return url

    def objectIds(self):
        return []


def get_item_title(item):
    """安全获取菜单条目标题

    兼容三类条目：
      - 内容对象（Title() 方法）
      - IMenuEntryProvider 代理（Title() 方法）
      - 其它 addon 的虚拟条目（Title 属性，如 maitux.groupmanagement）
    """
    title = getattr(item, "Title", None)
    if callable(title):
        try:
            return title()
        except Exception:  # noqa: B902
            return ""
    return title or ""


def get_effective_lims_setup_view():
    """返回当前请求下真正生效的 @@lims-setup 视图实例

    其它 addon 可能通过更具体的浏览器层覆盖了该视图并在 ``setupitems()``
    里追加虚拟条目；这里拿到的就是覆盖后的实例，从而自动识别这些条目。
    无请求（如命令行/测试）时返回 None。
    """
    portal = api.get_portal()
    request = api.get_request()
    if request is None:
        return None
    return api.get_view("lims-setup", portal, request)


def get_menu_id(item):
    """为菜单条目生成稳定唯一 ID

    - 内容对象：``uid:xxx``（UID 稳定，不随路径迁移变化）
    - 虚拟条目：``url:xxx``（absolute_url 可能是方法（如 MenuEntryProxy）
      也可能是普通字符串属性（如 maitux.groupmanagement 的 SetupEntry））
    - 兜底：``id:<对象稳定标识>``（绝不对未知对象调用 bika api，
      否则对非内容对象会抛 ``APIError: ... is not supported``）
    """
    # 1. 内容对象 -> UID
    uid = getattr(item, "UID", None)
    if callable(uid):
        try:
            value = uid()
            if value:
                return "uid:%s" % value
        except Exception:  # noqa: B902
            pass

    # 2. absolute_url（方法或属性均可）
    url = getattr(item, "absolute_url", None)
    if callable(url):
        try:
            url = url()
        except Exception:  # noqa: B902
            url = None
    if url:
        return "url:%s" % url

    # 3. 兜底：基于对象自身属性（不调用 bika api，避免未知对象报错）
    return "id:%s" % _safe_object_id(item)


def _safe_object_id(item):
    """安全的对象标识：优先 getId / id / __name__，最后用内存地址

    仅用于既无 UID 又无 URL 的极端兜底（同一请求内内存地址稳定）。
    """
    for attr in ("getId", "id", "__name__"):
        value = getattr(item, attr, None)
        if callable(value):
            try:
                value = value()
            except Exception:  # noqa: B902
                value = None
        if value:
            return str(value)
    return str(id(item))


def get_all_menu_items():
    """收集全部 Setup 菜单条目并排序（按翻译后标题，与 @@lims-setup 一致）"""
    items = []

    # 1. 生效的 @@lims-setup 视图的 setupitems()
    view = get_effective_lims_setup_view()
    if view is not None and hasattr(view, "setupitems"):
        try:
            items = list(view.setupitems())
        except Exception:  # noqa: B902
            items = []

    # 2. IMenuEntryProvider 注册的条目（按 menu_id 去重，避免与内容对象重复）
    seen = set([get_menu_id(item) for item in items])
    for name, provider in getUtilitiesFor(IMenuEntryProvider):
        try:
            entries = provider.get_menu_entries() or []
        except Exception:  # noqa: B902
            entries = []
        for entry in entries:
            menu_id = entry.get("menu_id") or "provider:%s" % name
            if menu_id in seen:
                continue
            seen.add(menu_id)
            items.append(MenuEntryProxy(menu_id, entry))

    return sorted(items, key=lambda item: t(get_item_title(item)))
