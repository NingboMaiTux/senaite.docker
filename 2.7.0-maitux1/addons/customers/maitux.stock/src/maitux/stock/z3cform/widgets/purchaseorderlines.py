# -*- coding: utf-8 -*-
from senaite.core.z3cform.widgets.datagrid.datagrid import DataGridWidget
from z3c.form.interfaces import IFieldWidget
from z3c.form.widget import FieldWidget
from zope.browserpage.viewpagetemplatefile import ViewPageTemplateFile
from zope.interface import implementer

from maitux.stock.i18n import translate_stock


purchaseorderlines_datagrid_input = ViewPageTemplateFile(
    "purchaseorderlines_datagrid_input.pt")


class PurchaseOrderLinesWidget(DataGridWidget):
    def render(self):
        if self.mode == "input":
            return purchaseorderlines_datagrid_input(self)
        return super(PurchaseOrderLinesWidget, self).render()

    def frontend_messages(self):
        """模板里 JS 用到的提示文案，按当前语言翻译后挂在 data-msg-* 上。

        中文注释：这段模板是整块 ``<script>``，字符串写在 JS 里就**不会**被
        翻译（而且非 ASCII 会被 Zope 写成实体，所以前端还要 decodeEntities）。
        统一从 data-* 属性读，中英文才都能正确显示。
        """
        return {
            "quantity-decimal": translate_stock(
                u"Quantity Ordered must be a number (decimals allowed)"),
        }


@implementer(IFieldWidget)
def PurchaseOrderLinesWidgetFactory(field, request):
    return FieldWidget(field, PurchaseOrderLinesWidget(request))
