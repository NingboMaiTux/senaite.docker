# -*- coding: utf-8 -*-
#
# 列表页静态资源注入（只作用于 GlossaryEntries 的列表页）。
#
# 为什么需要：core 没有给 addon 提供"给某个 listing 加一段 JS"的扩展点 ——
# senaite.app.listing 的 JS 是**预编译 bundle**，而它的 Save 按钮 / 行勾选框
# 都是 React 组件，服务端没有开关（见 static/glossary_listing.js 的注释：
# 本包用注入脚本实现"勾选行即保存"）。senaite.core 提供了
# ``senaite.abovelistingtable`` 视图件管理器，正好在表格上方，用它注入
# 一个 <script> 标签（按内容类型限定，不影响其它 listing）。

from bika.lims import api
from plone.app.layout.viewlets.common import ViewletBase


class GlossaryListingAssetsViewlet(ViewletBase):
    """把本包的列表页脚本插到表格上方。"""

    def resource_url(self):
        # 注意：bika.lims.api 没有 get_portal_url（那是 senaite.core.api 的），
        # 这里用本项目一贯的 api.get_url(api.get_portal())。
        return "%s/++resource++%s/%s" % (
            api.get_url(api.get_portal()), "maitux.glossary",
            "glossary_listing.js")

    def render(self):
        return (
            u'<script type="text/javascript" src="%s"></script>'
            % self.resource_url())
