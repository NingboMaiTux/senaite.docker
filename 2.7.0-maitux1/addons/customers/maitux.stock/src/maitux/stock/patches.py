# -*- coding: utf-8 -*-
from Products.CMFCore.utils import getToolByName

from maitux.stock.browser.stockbatchactions import get_transition_items_for_batch


_PATCHED = False
_UNICODE_PATCHED = False


def patch_auditlog_searchable_text_unicode():
    """修复审计目录全文索引器在「被引用对象标题含中文」时的 UnicodeDecodeError。

    背景（senaite.core 的 Py2 缺陷）
    ------------------------------
    ``senaite.core.catalog.indexer.auditlog.listing_searchable_text`` 会把快照里
    的 unicode 值统一编码成 utf8 字节串再放进一个 set（源码第 160-161 行）：

        if isinstance(value, unicode):
            value = api.safe_unicode(value).encode("utf8")

    但通过 UID 解析出来的标题（``get_title_or_id_from_uid``）没有做同样处理，
    把 **unicode** 直接丢进同一个 set；最后 ``" ".join(catalog_data)`` 遇到
    「字节串 + unicode」混合类型时，Py2 会尝试按 ASCII 解码字节串，只要标题含
    中文（例如库存单位「瓶」）就抛 ``UnicodeDecodeError``。
    该异常发生在**事务提交阶段**（catalog 的 before-commit 钩子），因此表现为
    「保存对象时页面 500，且对象不会落库」。

    影响面
    ------
    任何被审计（IAuditable）对象，只要引用了标题含中文的对象就存不下去。
    库存模块里最典型的就是「库存单位 / 供应商 / 基质名称用中文」——
    这也是创建库存主数据、库存批次时 500 的根因。

    修法
    ----
    把该辅助函数的返回值统一成 utf8 字节串，使 set 内类型保持一致。
    """
    global _UNICODE_PATCHED
    if _UNICODE_PATCHED:
        return

    try:
        from senaite.core.catalog.indexer import auditlog
    except Exception:
        return

    original = getattr(auditlog, "get_title_or_id_from_uid", None)
    if original is None:
        return

    def get_title_or_id_from_uid(uid):
        value = original(uid)
        # 中文注释：与索引器里直接取值的分支保持同一类型（utf8 字节串），
        # 否则 set 中混入 unicode 会让 " ".join(...) 按 ASCII 解码而报错。
        if isinstance(value, unicode):  # noqa: F821  (Python 2)
            value = value.encode("utf8")
        return value

    auditlog.get_title_or_id_from_uid = get_title_or_id_from_uid
    _UNICODE_PATCHED = True
    try:
        from senaite.core import logger
        logger.info("maitux.stock: patched auditlog searchable-text indexer "
                    "for unicode safety")
    except Exception:
        pass


def patch_allowed_transitions_for_many():
    """为 StockBatch 扩展标准 allowedTransitionsFor_many 返回结果。"""
    global _PATCHED
    if _PATCHED:
        return

    try:
        from bika.lims.jsonapi.allowedtransitionsfor import allowedTransitionsFor
    except Exception:
        return

    original = allowedTransitionsFor.allowed_transitions_for_many

    def wrapped(self, context, request):
        # 中文注释：这里复用标准 listing 的 selected-actions 机制，
        # 仅对 StockBatch 注入自定义动作，其它对象仍保持原生逻辑。
        wftool = getToolByName(context, "portal_workflow")
        uc = getToolByName(context, 'uid_catalog')
        import json
        from zExceptions import BadRequest
        from plone.jsonapi.core import router

        uids = json.loads(request.get('uid', '[]'))
        if not uids:
            raise BadRequest("No object UID specified in request")

        allowed_transitions = []
        try:
            brains = uc(UID=uids)
            for brain in brains:
                obj = brain.getObject()
                if getattr(obj, "portal_type", "") == "StockBatch":
                    trans = get_transition_items_for_batch(obj)
                else:
                    trans = [{'id': t['id'], 'title': t['title']} for t in
                             wftool.getTransitionsFor(obj)]
                allowed_transitions.append(
                    {'uid': obj.UID(), 'transitions': trans})
        except Exception as e:
            msg = "Cannot get the allowed transitions ({})".format(
                getattr(e, "message", str(e)))
            raise BadRequest(msg)

        return {
            "url": router.url_for("allowedTransitionsFor_many",
                                  force_external=True),
            "success": True,
            "error": False,
            "transitions": allowed_transitions
        }

    allowedTransitionsFor.allowed_transitions_for_many = wrapped
    _PATCHED = True
