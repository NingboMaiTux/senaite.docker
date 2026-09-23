# -*- coding: utf-8 -*-
"""把 addon 自带的样式表注入页面 <head>。

为什么不用 plone.resources / plone.bundles
------------------------------------------
SENAITE 的 main_template 只渲染它自己那份 bundle 列表，
addon 新注册的 bundle 记录（registry 里能看到）不会出现在页面上 ——
实测注册成功但页面不加载，样式静默失效。
所以这里用最朴素也最可靠的方式：在 IHtmlHead 里输出一个 <link>，
指向本包通过 ``browser:resourceDirectory`` 注册的 ``++resource++`` 资源。

中文注释：有效期提醒的行底色（黄/红）就靠这个文件，
详见 browser/static/maitux.stock.css 顶部说明。
"""

from plone.app.layout.viewlets import ViewletBase
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.core import logger


class StockStylingViewlet(ViewletBase):
    """输出 addon 自带 CSS 的 <link>。"""

    index = ViewPageTemplateFile("templates/stock_styling.pt")

    def css_url(self):
        """返回 addon 样式表在 ++resource++ 下的绝对地址。"""
        portal_url = ""
        try:
            portal_url = self.context.portal_url()
        except Exception:
            try:
                portal_url = self.request.physicalPathToURL(
                    self.context.getPhysicalPath()[:2])
            except Exception:
                portal_url = ""
        if portal_url.endswith("/"):
            portal_url = portal_url[:-1]
        return "{0}/++resource++maitux.stock/maitux.stock.css".format(portal_url)

    def render(self):
        try:
            return self.index()
        except Exception as exc:
            # 中文注释：样式加载失败不能把整站页面打成 500，但也不能静默 ——
            # 行底色会跟着一起消失，必须能在日志里查到原因。
            logger.error(
                "maitux.stock: failed to render styling viewlet: %s: %s",
                type(exc).__name__, exc)
            return ""
