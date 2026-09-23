# -*- coding: utf-8 -*-
from Products.Five.browser import BrowserView
from bika.lims import api
from maitux.stock import stockMessageFactory as _

# 中文注释：这个"修复结构"视图会把标题刷成**约定的英文 msgid**（既不是中文，
# 也不是历史上的旧英文）。原因：菜单名与页面标题都靠运行时翻译按语言显示，
#   英文 msgid + locales/<lang> 目录 -> 英文站英文、中文站中文。
# 取值与 setuphandlers 的常量保持一致：
#   STOCK_MANAGER_TITLE = "Stock Inventory" / STOCK_FOLDER_TITLE = "Stock Items"
#   STOCK_CHILDREN 里 stock_types 的标题 = "Stock Types"
FIX_TITLES = (
    ("", u"Stock Inventory"),
    ("stock_types", u"Stock Types"),
    ("stock", u"Stock Items"),
)


class StockStructureFixView(BrowserView):
    def __call__(self):
        ctx = self.context
        if api.get_portal_type(ctx) != "StockManager":
            self.context.plone_utils.addPortalMessage(_("Not a Stock Manager."), "warning")
            return self.request.response.redirect(api.get_url(ctx))

        # 标题统一刷成当前约定的中文（幂等：已经一致就跳过）
        for obj_id, title in FIX_TITLES:
            target = ctx if not obj_id else ctx.get(obj_id)
            if target is None or not getattr(target, "Title", None):
                continue
            try:
                if api.safe_unicode(target.Title()) != title:
                    target.setTitle(title)
                    target.reindexObject()
            except Exception:
                pass

        # Remove Dynamic section
        try:
            if "stock_dynamic" in ctx.objectIds():
                ctx.manage_delObjects(["stock_dynamic"])
        except Exception:
            pass

        self.context.plone_utils.addPortalMessage(_("Changes applied."), "info")
        return self.request.response.redirect(api.get_url(ctx))
