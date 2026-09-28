# -*- coding: utf-8 -*-
from bika.lims import api
from plone.supermodel import model
from senaite.core.content.base import Container
from zope.i18n import translate as zt
from zope.interface import implementer

from maitux.hazardcategories.interfaces import IHazardCategories


class IHazardCategoriesSchema(model.Schema):
    pass


@implementer(IHazardCategories, IHazardCategoriesSchema)
class HazardCategories(Container):
    """危害分类容器（设置主页上的一个入口 tile）。

    容器放在 ``<site>/setup`` 下，senaite.core 的设置菜单 ``setupitems()``
    会自动把它收录成一个入口 tile；可见性由 maitux.setupmenu 按角色分配。
    """

    def Title(self):
        """显示标题（utf-8 字节串）。

        存储的是 ``Message``（安装时写入 ``_(u"HazardCategories Container")``），
        这里显式按当前请求的语言翻译一次；只把 ``Message`` 原样交给模板，
        在部分渲染路径上会漏掉翻译。

        返回值必须是 **utf-8 字节串**（``api.to_utf8``），与平台约定一致：
        core 的 ``bootstrap.img_tag`` 用字节串做模板
        ``"<img title='{}' ...".format(title)``，含中文的 ``unicode`` 会让
        Py2 先按 ASCII 编码它而抛 ``UnicodeEncodeError``，直接让设置页 500。
        参考实现见 ``maitux.glossary`` 的 ``GlossaryEntries.Title``。
        """
        raw = getattr(self.aq_base, "title", None)
        context = self
        try:
            from zope.globalrequest import getRequest
            request = getRequest()
            if request is not None:
                context = request
        except Exception:
            context = self
        try:
            value = zt(raw, context=context, domain="maitux.hazardcategories")
        except Exception:
            value = None
        return api.to_utf8(value or raw or u"")
