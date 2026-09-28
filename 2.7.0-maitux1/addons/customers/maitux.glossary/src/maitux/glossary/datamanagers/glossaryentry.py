# -*- coding: utf-8 -*-
#
# IDataManager for one middle table row.
#
# 为什么需要它：listing 里标记为 ``"ajax": True`` 的单元格，保存时走的是
# core 原生的链路（规则 R10 要求复用、不要绕开）：
#
#     senaite.app.listing.ajax.ajax_set_fields
#       -> ListingView.set_field(obj, name, value)
#         -> queryAdapter(obj, IDataManager).set(name, value)
#
# senaite.core 只为 AnalysisService / Sample / Analysis 提供了实现，
# 自定义内容类型没有 -> queryAdapter 返回 None -> set_field 返回空列表
# -> 页面报 "Failed to set field of save queue" 500。
# 所以必须为本包的内容类型补一个 IDataManager。

from AccessControl import Unauthorized
from bika.lims import api
from senaite.core.datamanagers.base import DataManager
from zope.component import adapter

from maitux.glossary import logger
from maitux.glossary.config import EDITABLE_FIELDS
from maitux.glossary.config import WRITABLE_FIELDS
from maitux.glossary.interfaces import IGlossaryEntry
from maitux.glossary.utils import find_by_calc_keyword
from maitux.glossary.utils import text

#: 会按 calc keyword 批量同步到兄弟行的字段。
#: 依据：core 强制"同一个 calc keyword 在站点上只能有一个 Field title"
#: （senaite/core/validators/interimfields.py:125 与 bika/lims/validators.py:375）
#: —— 同一个字段的译文必须是唯一的，否则本表就不能当术语库用。
#:
#: ★ **只有 zh / en 走批量**。报告导入映射列（`acq_*`）虽然也可编辑，但
#: 必须**只写当前行** —— 同一个 calc keyword 在不同分析上来源不同
#: （实测 `g_rt` 8 行：SYS / 供试品 / 稳定性 / 破坏），批量写会把来源改错。
BATCHED_FIELDS = EDITABLE_FIELDS


@adapter(IGlossaryEntry)
class GlossaryEntryDataManager(DataManager):
    """中间表行的 data manager。
    """

    @property
    def fields(self):
        return api.get_fields(self.context)

    def get_field_by_name(self, name):
        return self.fields.get(name)

    def get(self, name):
        field = self.get_field_by_name(name)
        if field is None:
            raise AttributeError("Field '{}' not found".format(name))
        if not self.can_access():
            raise Unauthorized("Field '{}' not readable!".format(name))
        return field.get(self.context)

    def set(self, name, value):
        """保存一个字段，并返回**被改动的全部对象**。

        保存链路会把返回值逐个 reindex，所以批量改动的兄弟行也必须
        在返回列表里，否则列表页只显示当前行变了。
        """
        name = text(name)
        if name not in WRITABLE_FIELDS:
            # 白名单：analysis_keyword / calc_keyword / sync_state 等
            # 都不允许通过列表页的保存链路改写（防伪造 save_queue）。
            logger.error(
                "maitux.glossary: field '%s' is not editable through the "
                "listing, refused", name)
            return []

        if self.get_field_by_name(name) is None:
            raise AttributeError("Field '{}' not found".format(name))

        if not self.can_write():
            logger.error(
                "maitux.glossary: no permission to write '%s' (ModifyPortalContent)",
                name)
            return []

        targets = self.get_batch_targets(name)
        updated = []
        unchanged = 0
        for obj in targets:
            try:
                field = api.get_fields(obj).get(name)
                if field is None:
                    continue
                # 值没变就**不碰**这个对象：写它会把它标成 dirty，
                # 既白写 ZODB，又会扩大并发提交的冲突面
                # （autosave 时代就是这样撞出 ConflictError 500 的）。
                if text(field.get(obj)) == text(value):
                    unchanged += 1
                    continue
                field.set(obj, value)
                updated.append(obj)
            except Exception as exc:
                logger.warn("maitux.glossary: failed to set '%s' on %s: %s",
                            name, obj.getId(), exc)
        if len(updated) > 1 or (updated and unchanged):
            logger.info(
                "maitux.glossary: '%s' on calc keyword '%s' applied to %d rows "
                "(batch by calc keyword, %d already up to date)", name,
                text(getattr(self.context, "calc_keyword", None)),
                len(updated), unchanged)

        if not updated:
            # 一个都没写（最常见的：用户按了保存但内容没变）。**必须**回报
            # 用户编辑的那一行：core 的 ajax_set_fields 把空列表当成保存失败，
            # 会抛 "Failed to set field of save queue" 500。
            logger.info(
                "maitux.glossary: '%s' on calc keyword '%s' unchanged, "
                "nothing to write", name,
                text(getattr(self.context, "calc_keyword", None)))
            return [self.context]
        return updated

    def get_batch_targets(self, name):
        """返回本次写入要落到哪几行。

        对 zh / en：同一 calc keyword 的**所有行**
        （含未激活行）—— 否则改一次只生效一行，其余行仍然是旧译文，
        立刻违反"同一个 calc keyword 译文必须一致"。

        对 `acq_*`（报告导入映射）与其它字段：**只写当前行** ——
        同一 calc keyword 在不同分析上的来源/规则可以不同，批量写会改错。
        """
        context = self.context
        if name not in BATCHED_FIELDS:
            return [context]

        calc_keyword = text(getattr(context, "calc_keyword", None))
        if not calc_keyword:
            return [context]

        container = api.get_parent(context)
        if container is None:
            return [context]

        siblings = find_by_calc_keyword(container, calc_keyword)
        if not siblings:
            return [context]
        # 当前行必须在内（正常都在；万一没有也补上）
        if context not in siblings:
            siblings.append(context)
        return siblings
