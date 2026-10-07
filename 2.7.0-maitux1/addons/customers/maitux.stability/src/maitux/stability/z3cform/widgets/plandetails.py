# -*- coding: utf-8 -*-
from bika.lims import api
from senaite.core.z3cform.widgets.datagrid.datagrid import DataGridWidget
from senaite.core.z3cform.widgets.uidreference.widget import UIDReferenceWidget
from z3c.form.interfaces import IFieldWidget
from z3c.form.interfaces import NO_VALUE
from z3c.form.widget import FieldWidget
from zope.browserpage.viewpagetemplatefile import ViewPageTemplateFile
from zope.interface import implementer

from maitux.stability.timepoints import clean_extracted_rows
from maitux.stability.timepoints import is_sentinel
from maitux.stability.timepoints import is_voided


plandetails_datagrid_input = ViewPageTemplateFile("plandetails_datagrid_input.pt")


class PlanDetailsWidget(DataGridWidget):
    #: ``extract()`` 丢掉的行数（整行是 z3c.form 哨兵 = 这一行没提交上来）。
    #: 表单读它来决定"本次不改明细"，并用一句话告诉用户 —— 见 browser/edit.py。
    #: ``-1`` 表示**整段明细**都没读出来（计数标记缺失，DGF 直接返回哨兵）。
    dropped_rows = 0

    def render(self):
        if self.mode == "input":
            return plandetails_datagrid_input(self)
        return super(PlanDetailsWidget, self).render()

    def extract(self, default=NO_VALUE):
        """提取明细行 —— 顺手把 z3c.form 的 NO_VALUE 哨兵挡在写库之前。

        ★ 为什么必须在**控件层**做（2026-09-30 生产事故）：
          DataGrid 的整行没提交上来时（计数标记说有 N 行、请求里只有 N-1 行），
          `MultiWidget.extract` 会把 `z3c.form.interfaces.NO_VALUE` 哨兵
          塞进列表当占位。哨兵不可 pickle，落到 ZODB 会让**整个事务**
          在 commit 时抛 PicklingError（页面 500，用户那次保存全丢）。
          这是"最近的一道网"：编辑页和新建页都从这里过。

        两种形态：
        * 整段明细是哨兵（计数标记没提交上来）-> 原样返回，让上层按
          "字段没提交"处理（表单侧会**不写**明细字段，保留库里的行）；
        * 列表里有哨兵元素（某几行没提交上来）-> 丢掉落哨兵的行并计数。
        """
        value = super(PlanDetailsWidget, self).extract(default=default)
        self.dropped_rows = 0
        if value is default or is_sentinel(value):
            # 整段明细没读出来：原样返回哨兵，**绝不**在这里改写成空列表 ——
            # 那等于"用户把行删光了"，会被当成删除请求。
            self.dropped_rows = -1
            return value
        rows, dropped = clean_extracted_rows(value)
        self.dropped_rows = dropped
        return rows

    def row_is_voided(self, index):
        """模板用：这一行是不是**已作废/已废弃**（阶段 6c）。

        模板据此给 ``<tr>`` 挂 ``data-voided="1"``，前端脚本再把该行隐藏。

        ★ 判据取 ``timepoints.is_voided``（唯一实现），不在这里另写一份
          "看 voided_at 有没有值"。取不到（模板行 ``TT`` / 自动追加行 ``AA`` /
          越界 / 值不是行字典）一律当"没作废" —— 渲染期不该把整张表单弄崩。
        """
        try:
            rows = self.value or []
            row = rows[int(index)]
        except Exception:
            return False
        return is_voided(row) if isinstance(row, dict) else False


class SafeUIDReferenceWidget(UIDReferenceWidget):
    def get_context(self):
        context = super(SafeUIDReferenceWidget, self).get_context()
        if context in (None, NO_VALUE):
            return api.get_portal()
        return context


@implementer(IFieldWidget)
def PlanDetailsWidgetFactory(field, request):
    return FieldWidget(field, PlanDetailsWidget(request))


@implementer(IFieldWidget)
def SafeUIDReferenceWidgetFactory(field, request):
    return FieldWidget(field, SafeUIDReferenceWidget(request))
