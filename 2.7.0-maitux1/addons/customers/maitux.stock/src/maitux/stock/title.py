# -*- coding: utf-8 -*-
"""让容器类的 Title() 按当前语言翻译（参考 maitux.hazardcategories）。

为什么：Plone 的内容区 h1、页面 ``<title>``、面包屑都是直接取 ``context.Title()``，
框架不做翻译。把翻译放进 ``Title()``，这些位置才跟语言切换。

约定：
* ZODB 里的对象 ``title`` 字段**始终是英文 msgid**（安装步骤写入）；
* 目录（uid_catalog.Title，侧边栏读它）由安装步骤在"无请求"上下文显式编目，
  因此索引里是英文 msgid，侧边栏再按当前语言翻译 -> 中英双语。
"""

from bika.lims import api

from maitux.stock.i18n import translate_stock


class TranslatableTitleMixin(object):
    """Title() 返回当前语言的标题；取不到译文时原样返回英文 msgid。

    **没有请求时不翻译**（返回原始英文 msgid）：安装/编目是在
    ``bin/instance run`` 里跑的（没有 request），此时若按"默认语言"翻译，
    uid_catalog 里的 Title 就会变成中文，英文站菜单反而会显示中文。
    网页渲染一定有 request，所以界面侧不受影响。
    """

    def raw_title(self):
        """原始（未翻译）标题：对象 title 字段，空则退回 id。"""
        value = getattr(self, "title", None)
        if value:
            return value
        getter = getattr(self, "getId", None)
        return getter() if callable(getter) else u""

    def Title(self):
        raw = self.raw_title()
        if not raw:
            return u""
        try:
            if api.get_request() is None:
                return raw
        except Exception:
            return raw
        return translate_stock(raw) or raw
