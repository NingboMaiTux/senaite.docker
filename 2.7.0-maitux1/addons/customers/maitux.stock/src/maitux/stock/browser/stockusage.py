# -*- coding: utf-8 -*-
"""库存使用记录查询界面

页面清单（均挂在库存管理下的独立节点上，见 ``setuphandlers``）：

- ``@@stock_usage_trace``          库存使用记录追溯：按库存编号 / 厂家批号查批次去向与使用情况
- ``@@stock_usage_report``         （对照品）使用记录查询：按起止时间/库存编号/批号/物料名称/供应商
- ``@@stock_usage_report_export``  使用记录 CSV 导出（与查询页共用同一套筛选与取值口径）
- ``@@stock_usage_setup``          幂等创建/修复上面两个入口（供已安装站点升级时执行一次）

设计说明：

1. 查询与导出共用 :class:`StockUsageReportMixin`，避免「页面能看到、导出却少一行」的口径漂移。
2. 视图不重写 ``__call__``（除无模板的导出/修复视图），把逻辑放在模板调用的方法里，
   避免 ZCML 中 ``class`` + ``template`` 并用时 ``__call__`` 被 MRO 遮蔽（见 SENAITE-Addon 开发规则 R9）。
3. 所有筛选都在 Python 侧完成，原因见 ``maitux.stock.usage`` 模块注释。
"""

import codecs
import csv
import io
import math
from datetime import datetime
from decimal import Decimal

import six
from Products.Five.browser import BrowserView
from bika.lims import api
from bika.lims import senaiteMessageFactory as _
from six.moves.urllib.parse import urlencode

from maitux.stock.usage import DEFAULT_PAGE_SIZE
from maitux.stock.usage import MAX_PAGE_SIZE
from maitux.stock.usage import StockUsageQuery
from maitux.stock.usage import format_amount
from maitux.stock.usage import format_date
from maitux.stock.usage import format_datetime
from maitux.stock.usage import get_status_label
from maitux.stock.usage import parse_date_range
from maitux.stock.usage import to_decimal


#: 使用记录表格/CSV 的统一列定义（取值 key, 列名）
USAGE_COLUMNS = (
    ("number", u"库存编号"),
    ("material_name", u"物料名称"),
    ("stock_type", u"库存类型"),
    ("supplier", u"供应商"),
    ("batch_number", u"厂家批号"),
    ("batch_id", u"批次编号"),
    ("unit", u"单位"),
    ("operation_label", u"操作类型"),
    ("operation_date_text", u"操作时间"),
    ("operator", u"操作人"),
    ("quantity_text", u"数量"),
    ("remarks", u"备注"),
    ("from_batch", u"来源批次"),
    ("batch_status_label", u"批次状态"),
    ("location", u"存放位置"),
    ("expiry_date_text", u"有效期"),
)

#: 查询结果表与 CSV 实际使用的列（含序号），保证「页面所见 = 导出所得」
REPORT_COLUMNS = ((u"index", u"序号"),) + USAGE_COLUMNS


def build_csv(headers, rows):
    """按 Excel 友好方式生成 CSV 字节串（UTF-8 + BOM）。"""
    if six.PY2:
        stream = io.BytesIO()
        stream.write(codecs.BOM_UTF8)
    else:
        stream = io.StringIO()
        stream.write(u"\ufeff")

    writer = csv.writer(stream, lineterminator="\r\n")

    def write_row(values):
        values = [api.safe_unicode(value) for value in values]
        if six.PY2:
            values = [value.encode("utf-8") for value in values]
        writer.writerow(values)

    write_row(headers)
    for row in rows:
        write_row(row)

    data = stream.getvalue()
    if six.PY2:
        return data
    return data.encode("utf-8")


class StockUsageBaseView(BrowserView):
    """查询界面公共基类：请求参数解析、分页、URL 拼装。"""

    DEFAULT_PAGE_SIZE = DEFAULT_PAGE_SIZE
    MAX_PAGE_SIZE = MAX_PAGE_SIZE

    def __init__(self, context, request):
        super(StockUsageBaseView, self).__init__(context, request)
        self._query = None

    # ------------------------------------------------------------ 请求参数

    @property
    def form(self):
        return getattr(self.request, "form", None) or {}

    def get_param(self, name, default=u""):
        """取单个请求参数（兼容多值场景），统一转成去空白的 unicode。"""
        value = None
        form = self.form
        if name in form:
            value = form.get(name)
        else:
            value = self.request.get(name, None)
        if isinstance(value, (list, tuple)):
            value = value[0] if value else u""
        value = api.safe_unicode(value if value is not None else u"").strip()
        return value or default

    def get_bool_param(self, name, default=False):
        """取布尔参数（checkbox）。至少提交过同名参数才会返回 False。"""
        if name not in self.form and self.request.get(name, None) is None:
            return default
        return self.get_param(name, u"").lower() in (u"1", u"on", u"true", u"yes", u"y")

    def get_int_param(self, name, default):
        value = self.get_param(name, u"")
        if not value:
            return default
        try:
            return int(value)
        except Exception:
            return default

    # ------------------------------------------------------------ 查询引擎

    @property
    def query(self):
        if self._query is None:
            self._query = StockUsageQuery(self.context)
        return self._query

    # ------------------------------------------------------------ 分页

    def page_size(self):
        size = self.get_int_param("page_size", self.DEFAULT_PAGE_SIZE)
        return max(1, min(size, self.MAX_PAGE_SIZE))

    def current_page(self):
        return max(1, self.get_int_param("page", 1))

    def paginate(self, items):
        """返回 ``(当前页数据, 当前页码, 总页数)``。"""
        items = list(items)
        size = self.page_size()
        pages = int(math.ceil(len(items) / float(size))) if items else 1
        page = min(self.current_page(), max(1, pages))
        start = (page - 1) * size
        return items[start:start + size], page, pages

    # ------------------------------------------------------------ URL

    def query_string(self, **overrides):
        """把当前查询条件拼成 query string，可覆盖/删除指定参数。"""
        params = []
        for key, value in self.form.items():
            if key in overrides:
                continue
            if isinstance(value, (list, tuple)):
                value = value[0] if value else u""
            params.append((key, api.safe_unicode(value if value is not None else u"")))
        for key, value in overrides.items():
            if value is None:
                continue
            params.append((key, api.safe_unicode(value)))
        pairs = [(key, value.encode("utf-8")) for key, value in params]
        return urlencode(pairs)

    def page_url(self, page):
        """生成指定页码的链接。"""
        query = self.query_string(page=page)
        return u"{}?{}".format(api.get_url(self.context), query)

    def context_url(self):
        """当前页面（节点）地址，用于表单 action 与重置链接。"""
        return api.get_url(self.context)


class StockUsageTraceMixin(object):
    """使用记录追溯的查询逻辑（按库存编号 / 厂家批号）。"""

    def filters(self):
        return {
            "stock_number": self.get_param("stock_number", u""),
            "batch_number": self.get_param("batch_number", u""),
        }

    def has_filters(self):
        filters = self.filters()
        return bool(filters["stock_number"] or filters["batch_number"])

    def include_worksheets(self):
        """是否反查关联工作表；未提交过该筛选项时默认开启。"""
        if not self.get_param("worksheets_filter_submitted", u""):
            return True
        return self.get_bool_param("include_worksheets", False)

    def matched_batches(self):
        if not self.has_filters():
            return []
        filters = self.filters()
        return self.query.filter_batches(
            stock_number=filters["stock_number"],
            batch_number=filters["batch_number"],
        )

    def trace_record_rows(self, batch):
        """返回单个批次的使用记录展示行。"""
        context = self.query.get_row_context(batch)
        rows = []
        for record in self.query.get_usage_records(batch):
            row = self.query.make_row(context, record)
            row["operation_date_text"] = format_datetime(row["operation_date"])
            row["quantity_text"] = format_amount(row["quantity"], u"")
            source = None
            if row["from_batch"]:
                source = self.query.get_batch_by_id(row["from_batch"])
            row["from_batch_url"] = api.get_url(source) if source is not None else u""
            rows.append(row)
        return rows

    def trace_summary(self, rows):
        """批次级使用情况汇总。"""
        consume = Decimal("0.00")
        restock = Decimal("0.00")
        dates = []
        for row in rows:
            if row["operation_type"] == u"consume":
                consume += to_decimal(row.get("quantity"), u"0.00")
            elif row["operation_type"] == u"return":
                restock += to_decimal(row.get("quantity"), u"0.00")
            if row["operation_date_text"]:
                dates.append(row["operation_date_text"])

        return {
            "record_count": len(rows),
            "consume_total": format_amount(consume, u"0.00"),
            "return_total": format_amount(restock, u"0.00"),
            "first_date": min(dates) if dates else u"",
            "last_date": max(dates) if dates else u"",
        }

    # ------------------------------------------------------------ 模板文案
    # 中文注释：带数字的复合句子集中在这里拼装，模板内不出现中文，
    # 以便通过 addon 的 i18n lint（模板静态文案走显式 msgid）。

    def summary_text(self, total, page, pages):
        return u"命中批次 {} 个；第 {} / {} 页。".format(total, page, pages)

    def records_header(self, count):
        return u"使用记录（{} 条）".format(count)

    def page_indicator(self, page, pages):
        return u"第 {} / {} 页".format(page, pages)

    def split_target_hint(self, target):
        return u"（厂家批号 {}；剩余 {}；{}）".format(
            target.get("batch_number") or u"-",
            target.get("current_amount_text") or u"0.00",
            target.get("status_label") or u"-")

    def worksheet_hint(self, worksheet):
        return u"（状态 {}；创建 {}）".format(
            worksheet.get("status") or u"-",
            worksheet.get("created_text") or u"-")

    def split_target_rows(self, batch):
        """分装去向（由本批次分装出去的批次）展示行。"""
        rows = []
        for target in self.query.get_split_targets(batch):
            rows.append({
                "batch_id": getattr(target, "batch_id", u"") or api.get_title(target),
                "batch_number": api.safe_unicode(getattr(target, "batch", u"") or u""),
                "url": api.get_url(target),
                "current_amount_text": format_amount(
                    getattr(target, "current_amount", None), u"0.00"),
                "status_label": get_status_label(api.get_review_status(target) or u""),
            })
        return rows

    def trace_result(self):
        """组装追溯页需要的全部展示数据。"""
        result = {
            "has_filters": self.has_filters(),
            "filters": self.filters(),
            "items": [],
            "total": 0,
            "page": 1,
            "pages": 1,
        }
        if not result["has_filters"]:
            return result

        batches = self.matched_batches()
        page_batches, page, pages = self.paginate(batches)

        links = {}
        if self.include_worksheets():
            links = self.query.get_worksheet_links(
                [api.get_uid(batch) for batch in batches])

        items = []
        for batch in page_batches:
            uid = api.get_uid(batch)
            context = self.query.get_row_context(batch)
            rows = self.trace_record_rows(batch)
            items.append({
                "context": context,
                "records": rows,
                "summary": self.trace_summary(rows),
                "worksheets": links.get(uid, []),
                "split_targets": self.split_target_rows(batch),
                "expiry_date_text": format_date(context.get("expiry_date")),
                "current_amount_text": format_amount(
                    context.get("current_amount"), u"0.00"),
            })

        result.update({
            "items": items,
            "total": len(batches),
            "page": page,
            "pages": pages,
        })
        return result


class StockUsageReportMixin(object):
    """（对照品）使用记录查询逻辑：查询页与导出页共用。"""

    def filters(self):
        date_from = self.get_param("date_from", u"")
        date_to = self.get_param("date_to", u"")
        start, end = parse_date_range(date_from, date_to)

        errors = []
        if date_from and start is None:
            errors.append(u"起始时间“{}”无法识别，本次查询已忽略该条件。".format(date_from))
        if date_to and end is None:
            errors.append(u"截止时间“{}”无法识别，本次查询已忽略该条件。".format(date_to))
        if start is not None and end is not None and start > end:
            errors.append(u"起始时间晚于截止时间，本次查询结果为空。")

        return {
            "date_from": date_from,
            "date_to": date_to,
            "start": start,
            "end": end,
            "stock_number": self.get_param("stock_number", u""),
            "batch_number": self.get_param("batch_number", u""),
            "material_name": self.get_param("material_name", u""),
            "stock_type_uid": self.get_param("stock_type_uid", u""),
            "supplier_uid": self.get_param("supplier_uid", u""),
            "errors": errors,
        }

    def matched_batches(self):
        filters = self.filters()
        if filters["start"] is not None and filters["end"] is not None \
                and filters["start"] > filters["end"]:
            return []
        return self.query.filter_batches(
            stock_number=filters["stock_number"],
            batch_number=filters["batch_number"],
            stock_type_uid=filters["stock_type_uid"],
            material_name=filters["material_name"],
            supplier_uid=filters["supplier_uid"],
        )

    def result_rows(self):
        """返回过滤后的原始行（未分页、未格式化）。"""
        filters = self.filters()
        rows = self.query.collect_rows(
            self.matched_batches(),
            start=filters["start"],
            end=filters["end"],
        )
        rows.sort(key=lambda row: (
            format_datetime(row["operation_date"]),
            api.safe_unicode(row["batch_id"]),
        ))
        return rows

    def display_rows(self):
        """返回可直接渲染/导出的展示行（补齐序号与格式化文本）。"""
        rows = []
        for index, row in enumerate(self.result_rows(), start=1):
            item = dict(row)
            item["index"] = index
            item["operation_date_text"] = format_datetime(row["operation_date"])
            item["quantity_text"] = format_amount(row["quantity"], u"")
            item["expiry_date_text"] = format_date(row["expiry_date"])
            item["current_amount_text"] = format_amount(row["current_amount"], u"0.00")
            rows.append(item)
        return rows

    def summary(self, rows):
        return self.query.summarize(rows)

    # ------------------------------------------------------------ 模板文案
    # 中文注释：带数字的复合句子集中在这里拼装，模板内不出现中文。

    def summary_text(self, summary, page, pages):
        return u"记录 {} 条；涉及批次 {} 个；领用合计 {}；归还合计 {}；第 {} / {} 页。".format(
            summary.get("record_count", 0),
            summary.get("batch_count", 0),
            summary.get("consume_total", u"0.00"),
            summary.get("return_total", u"0.00"),
            page, pages)

    def page_indicator(self, page, pages):
        return u"第 {} / {} 页".format(page, pages)

    # ------------------------------------------------------------ 下拉选项

    def date_input_value(self, name):
        """日期输入框回显值：能解析的按 ``YYYY-MM-DD`` 回显，解析不了则留空。"""
        raw = self.get_param(name, u"")
        if not raw:
            return u""
        start, end = parse_date_range(raw, u"")
        parsed = start or end
        if parsed is None:
            return u""
        return format_date(parsed)

    def stock_type_options(self):
        return self.query.get_stock_type_options()

    def supplier_options(self):
        return self.query.get_supplier_options()

    # ------------------------------------------------------------ 导出

    def export_url(self):
        url = u"{}/@@stock_usage_report_export".format(api.get_url(self.context))
        return u"{}?{}".format(url, self.query_string())


class StockUsageTraceView(StockUsageTraceMixin, StockUsageBaseView):
    """库存使用记录追溯页面。"""

    DEFAULT_PAGE_SIZE = 10

    def page_title(self):
        return u"库存使用记录追溯"

    def results(self):
        return self.trace_result()


class StockUsageReportView(StockUsageReportMixin, StockUsageBaseView):
    """（对照品）使用记录查询页面。"""

    DEFAULT_PAGE_SIZE = 50

    def page_title(self):
        return u"使用记录查询与导出"

    def columns(self):
        return REPORT_COLUMNS

    def results(self):
        filters = self.filters()
        rows = self.display_rows()
        page_rows, page, pages = self.paginate(rows)
        return {
            "filters": filters,
            "errors": filters["errors"],
            "rows": page_rows,
            "total": len(rows),
            "page": page,
            "pages": pages,
            "summary": self.summary(rows),
        }


class StockUsageExportView(StockUsageReportMixin, StockUsageBaseView):
    """使用记录 CSV 导出（无模板，必须自行实现 ``__call__``）。"""

    def __call__(self):
        rows = self.display_rows()
        headers = [title for (key, title) in REPORT_COLUMNS]
        data = []
        for row in rows:
            data.append([row.get(key, u"") for (key, title) in REPORT_COLUMNS])

        payload = build_csv(headers, data)
        filename = "stock_usage_{}.csv".format(
            datetime.now().strftime("%Y%m%d_%H%M%S"))

        response = self.request.response
        response.setHeader("Content-Type", "text/csv; charset=utf-8")
        response.setHeader(
            "Content-Disposition", 'attachment; filename="{}"'.format(filename))
        return payload


class StockUsageSetupView(BrowserView):
    """幂等创建/修复两个查询界面入口。

    已安装站点重跑 profile 后由 ``setuphandlers`` 自动创建；
    本视图用于「只更新了代码、还没来得及重跑 profile」时的手工兜底，
    执行后会给出明确的结果提示（成功/失败都可见，不做静默吞异常）。
    """

    def __call__(self):
        from maitux.stock.setuphandlers import USAGE_SECTION_DEFINITIONS
        from maitux.stock.setuphandlers import ensure_content

        context = self.context
        messages = context.plone_utils.addPortalMessage

        if api.get_portal_type(context) != "StockManager":
            messages(_("Not a Stock Manager."), "warning")
            return self.request.response.redirect(api.get_url(context))

        types_tool = api.get_tool("portal_types")
        created = []
        existing = []
        missing_types = []
        for obj_id, portal_type, title in USAGE_SECTION_DEFINITIONS:
            if types_tool.getTypeInfo(portal_type) is None:
                missing_types.append(portal_type)
                continue
            if obj_id in context:
                existing.append(obj_id)
                continue
            ensure_content(context, portal_type, obj_id, title)
            created.append(obj_id)

        if missing_types:
            messages(
                _(u"Missing portal types: ${types}. Please reinstall "
                  u"maitux.stock from the Add-ons control panel first.",
                  mapping={"types": u", ".join(missing_types)}),
                "error")
        if created:
            messages(
                _(u"Created: ${items}", mapping={"items": u", ".join(created)}),
                "info")
        if existing:
            messages(
                _(u"Already present: ${items}",
                  mapping={"items": u", ".join(existing)}),
                "info")
        if not created and not existing and not missing_types:
            messages(_("No changes made."), "warning")

        return self.request.response.redirect(api.get_url(context))
