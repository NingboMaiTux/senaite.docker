# -*- coding: utf-8 -*-
#
# 中间表容器（站点根下的 keyword_glossary）

from bika.lims import api
from senaite.core.content.base import Container
from zope.i18n import translate as zt
from zope.interface import implementer

from maitux.glossary import _
from maitux.glossary.config import PROJECTNAME
from maitux.glossary.interfaces import IGlossaryEntries
from maitux.glossary.interfaces import IGlossaryEntriesSchema


@implementer(IGlossaryEntries, IGlossaryEntriesSchema)
class GlossaryEntries(Container):
    """Keyword glossary container.

    容器本身没有业务字段；它的默认视图（listing）负责：
      - 进入页面时与站点对账同步
      - 展示 / 编辑中间表的 zh、en（外加两个只读参考列）
    """

    def Title(self):
        """显示标题（utf-8 字节串）。

        存储的是 ``Message``（安装时写入 ``_(u"Keyword glossary")``），
        这里**显式**用当前请求的语言翻译一次 —— 只把 Message 原样交给
        模板，在部分渲染路径（页面 ``<title>``、侧边栏）上会漏掉翻译而
        显示英文原文。用请求对象作为 context，语言从请求协商得到。

        返回值必须是 **utf-8 字节串**（``api.to_utf8``），这是平台的既有
        约定（``senaite.core.i18n.translate``、``bika.lims.utils.to_utf8``
        都返回字节串）。原因：core 的 ``bootstrap.img_tag`` 用字节串做模板
        ``"<img title='{}' ...".format(title)``，若 title 是含中文的
        ``unicode``，Py2 会先按 ASCII 编码它而抛 ``UnicodeEncodeError``，
        直接让 ``@@setup`` 设置页 500。其它 setup 项的标题都是 ASCII 的
        msgid，所以这条隐雷一直没被触发。
        """
        raw = getattr(self.aq_base, "title", None)
        if not raw:
            raw = _(u"Keyword glossary")
        context = self
        try:
            from zope.globalrequest import getRequest
            request = getRequest()
            if request is not None:
                context = request
        except Exception:
            context = self
        try:
            value = zt(raw, context=context, domain=PROJECTNAME)
        except Exception:
            value = None
        return api.to_utf8(value or raw)
