# -*- coding: utf-8 -*-
"""Setup 页上的入口

SENAITE 的 Setup 页（``senaite.core.browser.controlpanel.setupview``）是按
``setup`` / ``bika_setup`` 两个容器里的**内容对象**渲染磁贴的，既不读
portal_actions，模板里也没有 viewlet manager 挂点。本包又不能：

- 建内容对象（要写数据库）
- 写 ``actions.xml`` / ``controlpanel.xml``（要 profile）
- 覆盖 setupview（要 overrides.zcml + 浏览器层，本包没有层）

所以退而求其次：往 Plone 原生的 ``plone.abovecontent`` 管理器里挂一个 viewlet，
只在 Setup 页、且当前用户有 ManagePortal 时渲染一条入口横幅。

关于 R14（注入外来 UI 必须 layer 门控）：本包**随镜像发布、不存在"未安装"
状态**，没有需要门控的场景；门控条件换成了"上下文是 Setup 页 + 有管理权限"。
"""
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from plone.app.layout.viewlets.common import ViewletBase

try:
    from bika.lims import api
except ImportError:  # pragma: no cover
    api = None

try:
    from AccessControl import getSecurityManager
    from Products.CMFCore.permissions import ManagePortal
except ImportError:  # pragma: no cover
    getSecurityManager = None
    ManagePortal = "Manage portal"


#: 在这些上下文里才显示（新旧两个 Setup 都算）
SETUP_TYPES = ("Setup", "BikaSetup")


class SetupEntryViewlet(ViewletBase):
    """Setup 页上的「动态字段管理」入口"""

    index = ViewPageTemplateFile("templates/setup_entry.pt")

    def available(self):
        return self.is_setup_context() and self.can_manage()

    def is_setup_context(self):
        try:
            portal_type = getattr(self.context, "portal_type", None)
        except Exception:
            return False
        return portal_type in SETUP_TYPES

    def can_manage(self):
        if getSecurityManager is None:
            return False
        try:
            return bool(
                getSecurityManager().checkPermission(ManagePortal, self.context))
        except Exception:
            return False

    def url(self):
        if api is None:
            return "@@dynamic-fields"
        try:
            return "%s/@@dynamic-fields" % api.get_url(api.get_portal())
        except Exception:
            return "@@dynamic-fields"

    def render(self):
        if not self.available():
            return u""
        return self.index()
