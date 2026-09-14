# -*- coding: utf-8 -*-
#
# 中间表的一行 = 一个 (analysis_keyword, calc_keyword) 组合
#
# 行的 ID 是**确定性**的，见 keys.make_entry_id：
#   - 同一次组合重复同步不会产生第二行（幂等）
#   - 同步查"这一行存不存在"是 O(1)

from senaite.core.content.base import Item
from zope.interface import implementer

from maitux.glossary.interfaces import IGlossaryEntry
from maitux.glossary.interfaces import IGlossaryEntrySchema
from maitux.glossary.keys import make_entry_id  # noqa: F401  (re-export)
from maitux.glossary.keys import safe_unicode
from maitux.glossary.keys import text


@implementer(IGlossaryEntry, IGlossaryEntrySchema)
class GlossaryEntry(Item):
    """中间表的一行。
    """

    def Title(self):
        """显示用标题：``<analysis_keyword> / <calc_keyword>``。

        不使用站点上的任何 title —— 本表的 zh/en 是**独立术语**
        （见 结构定稿.md §2），标题只用于列表页与 ZMI 里认人。
        """
        analysis = text(getattr(self, "analysis_keyword", None))
        calc = text(getattr(self, "calc_keyword", None))
        if analysis and calc:
            return u"%s / %s" % (analysis, calc)
        return calc or analysis or safe_unicode(self.getId())

    def Description(self):
        return text(getattr(self, "category", None))
