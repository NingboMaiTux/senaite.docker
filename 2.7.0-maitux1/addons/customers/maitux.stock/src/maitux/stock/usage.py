# -*- coding: utf-8 -*-
"""库存使用记录查询引擎

对应需求：
1. 库存管理使用记录的追溯
   按 LIMS 库存编号、厂家批号查询批次去向与使用情况，实现从批号到使用记录的追溯。
2. 库存管理
   按起止时间、库存编号、批号、物料名称、供应商查询并导出（对照品）使用记录。

数据来源（全部来自 maitux.stock 现有模型，不新增业务对象、不新增目录索引）：

- ``Stock`` 主数据
  ``number`` 库存编号 / ``sample_matrix`` 物料名称 / ``stock_type`` 库存类型
  ``supplier`` 供应商（多值）/ ``unit`` 单位 / ``location`` 存放位置
- ``StockBatch`` 批次
  ``batch_id`` 批次编号 / ``batch`` 厂家批号 / ``current_amount`` 当前数量
  ``unit`` 单位 / ``expiry_date`` 有效期 / ``location`` 存放位置
  ``usage_records`` 操作流水（DataGrid）
- ``StockBatch.usage_records`` 使用记录
  每条含 ``operation_type`` / ``operator`` / ``operation_date`` / ``quantity``
  / ``remarks`` / ``from_batch``（分装时写入来源批次编号）
- 批次去向（关联工作表）
  ``maitux.worksheetfields`` 给 ``Worksheet`` 增加的 ``stock_batches`` 多选 UID 字段

为什么不用目录查询做精确筛选：

``usage_records`` 是对象内部的 DataGrid 结构，**没有任何目录索引**；``batch``
（厂家批号）也没有索引。因此本模块统一采用「目录粗筛出 StockBatch 列表 +
Python 侧精筛」，以保证**页面展示与 CSV 导出用完全相同的口径**，两者结果永远一致。

性能边界：精筛需要唤醒批次对象（每个批次约 1 次 ZODB 加载）。实验室库存批次量级
（千级以内）下耗时可接受；「关联工作表去向」需要遍历 Worksheet 目录反查，
成本更高，因此页面提供开关，默认开启。
"""

from decimal import Decimal

from bika.lims import api
from senaite.core.api import dtime

# ---------------------------------------------------------------- 常量

STOCK_MANAGER_PORTAL_TYPE = "StockManager"
STOCK_BATCH_PORTAL_TYPE = "StockBatch"
STOCK_TYPE_PORTAL_TYPE = "StockType"
SUPPLIER_PORTAL_TYPE = "Supplier"
WORKSHEET_PORTAL_TYPE = "Worksheet"

STOCK_BATCHES_ID = "stock_batches"
WORKSHEETS_ID = "worksheets"

PORTAL_CATALOG_ID = "portal_catalog"
SETUP_CATALOG_ID = "senaite_catalog_setup"
UID_CATALOG_ID = "uid_catalog"
WORKSHEET_CATALOG_ID = "senaite_catalog_worksheet"

# Worksheet 上由 maitux.worksheetfields 行为提供的库存批次字段名
WORKSHEET_STOCK_BATCHES_FIELD = "stock_batches"

# 操作类型 -> 中文标签（与 stockbatchview.py 保持一致，另补 create/expire）
OPERATION_LABELS = {
    u"create": u"创建",
    u"consume": u"领用",
    u"expire": u"过期",
    u"return": u"归还",
    u"destroy": u"销毁",
    u"split": u"分装",
    u"adjust": u"调整",
    u"stocktake": u"盘存",
}

# 批次状态展示用中文标签
STATUS_LABELS = {
    u"active": u"可用",
    u"expired": u"已过期",
    u"inactive": u"停用",
    u"destroyed": u"已销毁",
}

MAX_PAGE_SIZE = 500
DEFAULT_PAGE_SIZE = 50


def get_operation_label(operation_type):
    """返回操作类型的中文标签，未知类型原样返回。"""
    value = api.safe_unicode(operation_type or u"").strip()
    return OPERATION_LABELS.get(value, value)


def get_status_label(status):
    """返回批次状态的中文标签，未知状态原样返回。"""
    value = api.safe_unicode(status or u"").strip()
    return STATUS_LABELS.get(value, value)


# ---------------------------------------------------------------- 基础工具


def normalize(value):
    """把查询条件/字段值归一成为可比较的小写 unicode 字符串。"""
    return api.safe_unicode(value or u"").strip().lower()


def get_field_uids(obj, fieldname, fields=None):
    """读取对象上某个字段的 UID 取值，统一返回 UID 列表。

    兼容三种字段形态：
    - ``UIDReferenceField``：走 ``get_raw``，返回 UID 列表
    - ``schema.Choice``（存 UID 字符串）：走属性读取
    - 未安装的行为字段：返回空列表，不抛错

    :param fields: 可选的 ``api.get_fields(obj)`` 结果，避免批量处理时重复解析 schema
    """
    if obj is None:
        return []

    if fields is None:
        fields = api.get_fields(obj)
    field = fields.get(fieldname, None)
    if field is None:
        return []

    raw = None
    get_raw = getattr(field, "get_raw", None)
    if callable(get_raw):
        try:
            raw = get_raw(obj)
        except Exception:
            raw = None
    if raw is None:
        raw = getattr(obj, fieldname, None)

    if raw is None:
        return []

    if isinstance(raw, (list, tuple)):
        values = list(raw)
    else:
        values = [raw]

    uids = []
    for value in values:
        if api.is_object(value):
            value = api.get_uid(value)
        if api.is_uid(value) and value not in uids:
            uids.append(value)
    return uids


def to_decimal(value, default=u"0.00"):
    """安全转 Decimal，失败时返回默认值。"""
    try:
        return Decimal(value)
    except Exception:
        try:
            return Decimal(default)
        except Exception:
            return Decimal("0.00")


def format_amount(value, default=u""):
    """把数量格式化为两位小数字符串。"""
    if value in (None, u""):
        return default
    try:
        return u"{:.2f}".format(Decimal(value))
    except Exception:
        return api.safe_unicode(value)


def format_datetime(value, default=u""):
    """把 DateTime/datetime 格式化为 ``YYYY-MM-DD HH:MM:SS``。"""
    if not value:
        return default
    try:
        ansi = dtime.to_ansi(value, show_time=True)
    except Exception:
        return default
    if not ansi:
        return default
    ansi = api.safe_unicode(ansi)
    if len(ansi) < 14:
        return ansi
    return u"{}-{}-{} {}:{}:{}".format(
        ansi[0:4], ansi[4:6], ansi[6:8],
        ansi[8:10], ansi[10:12], ansi[12:14],
    )


def format_date(value, default=u""):
    """把 DateTime/datetime 格式化为 ``YYYY-MM-DD``。"""
    text = format_datetime(value, default=default)
    return text[:10] if text else default


def parse_date_range(date_from=u"", date_to=u""):
    """把页面上的起止日期解析成闭区间时间边界。

    :returns: (start, end)，均为 Zope DateTime 或 None
    """
    start = None
    end = None

    value = api.safe_unicode(date_from or u"").strip()
    if value:
        try:
            parsed = dtime.to_DT(value)
        except Exception:
            parsed = None
        if parsed:
            start = parsed.earliestTime()

    value = api.safe_unicode(date_to or u"").strip()
    if value:
        try:
            parsed = dtime.to_DT(value)
        except Exception:
            parsed = None
        if parsed:
            end = parsed.latestTime()

    return start, end


# ---------------------------------------------------------------- 查询引擎


class StockUsageQuery(object):
    """库存使用记录查询引擎。

    一次查询内缓存已唤醒的对象，避免同一批次被反复加载。
    """

    def __init__(self, context):
        self.context = context
        self._objects = {}
        self._fields = {}
        self._batches = None
        self._batch_by_id = None
        self._stock_of = {}
        self._row_context = {}
        self._worksheet_links = None
        self._split_targets = None

    # ------------------------------ 对象解析

    def get_object(self, uid):
        """按 UID 取对象（带缓存），取不到返回 None。"""
        if not api.is_uid(uid):
            return None
        if uid not in self._objects:
            self._objects[uid] = api.get_object_by_uid(uid, default=None)
        return self._objects[uid]

    def get_fields(self, obj):
        """返回对象的 name -> field 映射（带缓存）。

        ``api.get_fields()`` 每次都会重新遍历 schema 与行为，批量处理上千个批次时
        会被反复调用，这里按 UID 缓存一次。
        """
        uid = api.get_uid(obj)
        if uid not in self._fields:
            self._fields[uid] = api.get_fields(obj)
        return self._fields[uid]

    def get_uids(self, obj, fieldname):
        """返回对象上引用字段的 UID 列表（复用字段缓存）。"""
        if obj is None:
            return []
        return get_field_uids(obj, fieldname, fields=self.get_fields(obj))

    def get_first_object(self, obj, fieldname):
        """取引用字段的第一个对象。"""
        for uid in self.get_uids(obj, fieldname):
            ref = self.get_object(uid)
            if ref is not None:
                return ref
        return None

    def get_first_object_title(self, obj, fieldname):
        """取引用字段的第一个对象标题。"""
        ref = self.get_first_object(obj, fieldname)
        return api.get_title(ref) if ref is not None else u""

    # ------------------------------ 批次集合

    def get_stock_manager(self):
        """从当前上下文向上找到库存管理根节点。"""
        obj = self.context
        while obj is not None and api.is_object(obj):
            if api.get_portal_type(obj) == STOCK_MANAGER_PORTAL_TYPE:
                return obj
            obj = api.get_parent(obj)
        return None

    def get_batches_container(self):
        """返回库存批次目录；找不到时返回 None（退化为全站查询）。"""
        stock_manager = self.get_stock_manager()
        if stock_manager is None:
            return None
        container = stock_manager.get(STOCK_BATCHES_ID, None)
        if container is None or not api.is_object(container):
            return None
        return container

    def get_batches(self):
        """返回全部库存批次对象（按创建时间倒序，缓存一次）。"""
        if self._batches is None:
            self._batches = self._load_batches()
        return self._batches

    def _load_batches(self):
        """以「批次目录的子对象」为准加载全部批次。

        为什么不直接查 portal_catalog：

        1. 本模块的筛选条件（批号、使用时间、物料名称）都落在对象内部字段上，无论如何
           都要唤醒批次对象，因此不走「目录粗筛」并不会更慢；
        2. ``StockBatch`` 的 FTI 没有启用 ``IMultiCatalogBehavior``，而 senaite 的
           ``CatalogMultiplexProcessor`` 会拒绝为这类 Dexterity 对象做目录索引，
           导致部分批次根本不在 ``portal_catalog`` 里（实测 18 个批次对象只有 11 个在目录中，
           且 reindexObject 补不上）。以目录为数据源会直接漏数据。

        因此这里以容器子对象为准，保证「报表口径 = 实际存在的批次」。
        """
        container = self.get_batches_container()
        if container is None:
            return self._load_batches_from_catalog()

        batches = []
        for obj in container.objectValues():
            if api.get_portal_type(obj) == STOCK_BATCH_PORTAL_TYPE:
                batches.append(obj)
        return self._sort_batches(batches)

    def _load_batches_from_catalog(self):
        """目录兜底：库存批次目录不存在时退化为目录查询。"""
        catalog = api.get_tool(PORTAL_CATALOG_ID)
        if catalog is None:
            return []

        brains = catalog(
            portal_type=STOCK_BATCH_PORTAL_TYPE,
            sort_on="created",
            sort_order="descending",
        )
        batches = []
        for brain in brains:
            batch = api.get_object(brain, default=None)
            if batch is not None:
                batches.append(batch)
        return batches

    def _sort_batches(self, batches):
        """按创建时间倒序；时间相同再按批次编号倒序，保证结果稳定。"""
        def sort_key(batch):
            created = None
            try:
                created = batch.created()
            except Exception:
                created = None
            return (
                format_datetime(created),
                api.safe_unicode(getattr(batch, "batch_id", u"") or u""),
            )

        return sorted(batches, key=sort_key, reverse=True)

    def get_batch_by_id(self, batch_id):
        """按批次编号（batch_id）找批次，用于分装来源批次链接。"""
        key = normalize(batch_id)
        if not key:
            return None
        if self._batch_by_id is None:
            mapping = {}
            for batch in self.get_batches():
                value = normalize(getattr(batch, "batch_id", u"") or u"")
                if value and value not in mapping:
                    mapping[value] = batch
            self._batch_by_id = mapping
        return self._batch_by_id.get(key)

    def get_stock(self, batch):
        """返回批次对应的库存主数据。"""
        uid = api.get_uid(batch)
        if uid not in self._stock_of:
            self._stock_of[uid] = self.get_first_object(batch, "stock")
        return self._stock_of[uid]

    # ------------------------------ 供应商

    def get_supplier_uids(self, batch, stock=None):
        """返回批次涉及的供应商 UID：批次优先，其次库存主数据上的候选供应商。"""
        uids = list(self.get_uids(batch, "supplier"))
        if stock is None:
            stock = self.get_stock(batch)
        if stock is not None:
            for uid in self.get_uids(stock, "supplier"):
                if uid not in uids:
                    uids.append(uid)
        return uids

    def get_supplier_title(self, batch, stock=None):
        """返回批次的供应商展示文本，多个用逗号连接。"""
        titles = []
        for uid in self.get_supplier_uids(batch, stock=stock):
            obj = self.get_object(uid)
            # 中文注释：中文标题可能是 utf8 字节串，统一成 unicode 再 join，
            # 避免 Py2 按 ASCII 解码报错。
            title = api.safe_unicode(api.get_title(obj)) if obj is not None else u""
            if title and title not in titles:
                titles.append(title)
        return u", ".join(titles)

    # ------------------------------ 行上下文

    def get_usage_records(self, batch):
        """返回批次的流水列表（容错：字段缺失或类型异常时返回空列表）。"""
        records = getattr(batch, "usage_records", None) or []
        if not isinstance(records, (list, tuple)):
            return []
        return list(records)

    def get_row_context(self, batch):
        """返回与具体流水无关的批次/库存上下文（带缓存）。"""
        uid = api.get_uid(batch)
        if uid in self._row_context:
            return self._row_context[uid]

        stock = self.get_stock(batch)

        unit = self.get_first_object(batch, "unit")
        if unit is None and stock is not None:
            unit = self.get_first_object(stock, "unit")

        location = self.get_first_object(batch, "location")
        if location is None and stock is not None:
            location = self.get_first_object(stock, "location")

        expiry_date = getattr(batch, "expiry_date", None)
        if not expiry_date and stock is not None:
            expiry_date = getattr(stock, "expiry_date", None)

        context = {
            "batch": batch,
            "stock": stock,
            "batch_uid": uid,
            "stock_uid": api.get_uid(stock) if stock is not None else u"",
            "number": api.safe_unicode(getattr(stock, "number", u"") or u"") if stock is not None else u"",
            "material_name": self.get_first_object_title(stock, "sample_matrix"),
            "stock_type": self.get_first_object_title(stock, "stock_type"),
            "stock_type_uids": self.get_uids(stock, "stock_type") if stock is not None else [],
            "supplier": self.get_supplier_title(batch, stock=stock),
            "supplier_uids": self.get_supplier_uids(batch, stock=stock),
            "batch_number": api.safe_unicode(getattr(batch, "batch", u"") or u""),
            "batch_id": api.safe_unicode(getattr(batch, "batch_id", u"") or u""),
            "unit": api.get_title(unit) if unit is not None else u"",
            "location": api.get_title(location) if location is not None else u"",
            "expiry_date": expiry_date,
            "batch_status": api.get_review_status(batch) or u"",
            "current_amount": getattr(batch, "current_amount", None),
            "batch_url": api.get_url(batch),
            "stock_url": api.get_url(stock) if stock is not None else u"",
        }
        self._row_context[uid] = context
        return context

    def make_row(self, context, record=None):
        """把「批次上下文 + 单条流水」拼成一行查询结果。"""
        record = record or {}
        return {
            # 批次/库存维度
            "batch_uid": context["batch_uid"],
            "stock_uid": context["stock_uid"],
            "number": context["number"],
            "material_name": context["material_name"],
            "stock_type": context["stock_type"],
            "supplier": context["supplier"],
            "batch_number": context["batch_number"],
            "batch_id": context["batch_id"],
            "unit": context["unit"],
            "location": context["location"],
            "expiry_date": context["expiry_date"],
            "batch_status": context["batch_status"],
            "batch_status_label": get_status_label(context["batch_status"]),
            "current_amount": context["current_amount"],
            "batch_url": context["batch_url"],
            "stock_url": context["stock_url"],
            # 流水维度
            "operation_type": api.safe_unicode(record.get("operation_type", u"") or u""),
            "operation_label": get_operation_label(record.get("operation_type", u"")),
            "operation_date": record.get("operation_date", None),
            "operator": api.safe_unicode(record.get("operator", u"") or u""),
            "quantity": record.get("quantity", None),
            "remarks": api.safe_unicode(record.get("remarks", u"") or u""),
            "from_batch": api.safe_unicode(record.get("from_batch", u"") or u""),
        }

    # ------------------------------ 过滤

    def filter_batches(self, stock_number=u"", batch_number=u"", stock_type_uid=u"",
                       material_name=u"", supplier_uid=u""):
        """按库存编号/批号/物料名称/库存类型/供应商过滤批次。

        - 库存编号、物料名称：不区分大小写的包含匹配
        - 批号：同时匹配「厂家批号(batch)」与「批次编号(batch_id)」
        - 库存类型、供应商：UID 精确匹配
        """
        needle_number = normalize(stock_number)
        needle_batch = normalize(batch_number)
        needle_material = normalize(material_name)
        stock_type_uid = api.safe_unicode(stock_type_uid or u"").strip()
        supplier_uid = api.safe_unicode(supplier_uid or u"").strip()

        matched = []
        for batch in self.get_batches():
            context = self.get_row_context(batch)

            if needle_number and needle_number not in normalize(context["number"]):
                continue

            if needle_batch:
                haystack = u"\n".join([
                    normalize(context["batch_number"]),
                    normalize(context["batch_id"]),
                ])
                if needle_batch not in haystack:
                    continue

            if needle_material and needle_material not in normalize(context["material_name"]):
                continue

            if stock_type_uid and stock_type_uid not in context["stock_type_uids"]:
                continue

            if supplier_uid and supplier_uid not in context["supplier_uids"]:
                continue

            matched.append(batch)

        return matched

    def is_in_range(self, value, start=None, end=None):
        """判断流水时间是否落在闭区间 [start, end] 内。"""
        if start is None and end is None:
            return True
        if not value:
            # 有起止时间要求但没有时间戳的流水：不纳入结果，避免出现来源不明的行
            return False
        try:
            moment = dtime.to_DT(value)
        except Exception:
            moment = None
        if moment is None:
            return False
        if start is not None and moment < start:
            return False
        if end is not None and moment > end:
            return False
        return True

    def collect_rows(self, batches, start=None, end=None, include_without_records=False):
        """把批次列表展开成使用记录行。

        :param include_without_records: 无流水（或流水都不在时间范围内）的批次
            是否也产出一行空流水，用于「批次追溯」场景展示没有被使用的批次。
        """
        rows = []
        for batch in batches:
            context = self.get_row_context(batch)
            records = [
                record for record in self.get_usage_records(batch)
                if self.is_in_range(record.get("operation_date"), start, end)
            ]
            if not records:
                if include_without_records:
                    rows.append(self.make_row(context, None))
                continue
            for record in records:
                rows.append(self.make_row(context, record))
        return rows

    # ------------------------------ 批次去向（关联工作表）

    def get_split_target_map(self):
        """构建 ``{来源批次编号: [批次对象]}`` 的分装去向索引。

        分装时目标批次会写入 ``from_batch = 来源批次编号``，据此可以反推
        「这批货分装到哪里去了」。一次遍历全部批次并缓存，避免逐批次重复扫描。
        """
        if self._split_targets is None:
            mapping = {}
            for candidate in self.get_batches():
                for record in self.get_usage_records(candidate):
                    source = normalize(record.get("from_batch", u"") or u"")
                    if not source:
                        continue
                    targets = mapping.setdefault(source, [])
                    if candidate not in targets:
                        targets.append(candidate)
            self._split_targets = mapping
        return self._split_targets

    def get_split_targets(self, batch):
        """返回由指定批次分装出去的批次列表。"""
        batch_id = normalize(getattr(batch, "batch_id", u"") or u"")
        if not batch_id:
            return []
        return list(self.get_split_target_map().get(batch_id, []))

    def get_worksheets_by_batch(self, batch_uids):
        """反查每个批次被哪些工作表引用。

        ``maitux.worksheetfields`` 给 Worksheet 增加的 ``stock_batches`` 字段
        既没有目录索引、也没有反向引用，只能遍历工作表读取该字段。
        未安装该行为时本方法自动返回空结果，不影响页面其余部分。
        """
        wanted = set([uid for uid in batch_uids if uid])
        result = dict([(uid, []) for uid in wanted])
        if not wanted:
            return result

        for worksheet in self._iter_worksheets():
            for uid in get_field_uids(worksheet, WORKSHEET_STOCK_BATCHES_FIELD):
                if uid in wanted:
                    result[uid].append(self._worksheet_info(worksheet))
        return result

    def _iter_worksheets(self):
        """遍历全部工作表对象：优先读工作表目录的子对象，取不到时退回目录查询。"""
        portal = api.get_portal()
        container = None
        if portal is not None:
            container = portal.get(WORKSHEETS_ID, None)
        if api.is_object(container):
            for obj in container.objectValues():
                if api.get_portal_type(obj) == WORKSHEET_PORTAL_TYPE:
                    yield obj
            return

        catalog = api.get_tool(WORKSHEET_CATALOG_ID)
        if catalog is None:
            catalog = api.get_tool(UID_CATALOG_ID)
        if catalog is None:
            return

        try:
            brains = catalog(portal_type=WORKSHEET_PORTAL_TYPE)
        except Exception:
            return

        for brain in brains:
            worksheet = api.get_object(brain, default=None)
            if worksheet is not None:
                yield worksheet

    def _worksheet_info(self, worksheet):
        created = None
        try:
            created = worksheet.created()
        except Exception:
            created = None
        return {
            "uid": api.get_uid(worksheet),
            "title": api.get_title(worksheet) or api.get_id(worksheet),
            "status": api.get_review_status(worksheet) or u"",
            "created": created,
            "created_text": format_datetime(created),
            "url": api.get_url(worksheet),
        }

    def get_worksheet_links(self, batch_uids):
        """带缓存的批次-工作表反查结果（多次调用会合并缓存）。"""
        links = self.get_worksheets_by_batch(batch_uids)
        if self._worksheet_links is None:
            self._worksheet_links = {}
        self._worksheet_links.update(links)
        return self._worksheet_links

    # ------------------------------ 汇总

    def summarize(self, rows):
        """统计行级汇总：记录数、领用合计、归还合计、批次集合。"""
        consume = Decimal("0.00")
        restock = Decimal("0.00")
        batches = []
        for row in rows:
            if row["operation_type"] == u"consume":
                consume += to_decimal(row.get("quantity"), u"0.00")
            elif row["operation_type"] == u"return":
                restock += to_decimal(row.get("quantity"), u"0.00")
            if row["batch_uid"] not in batches:
                batches.append(row["batch_uid"])
        return {
            "record_count": len(rows),
            "batch_count": len(batches),
            "consume_total": format_amount(consume, u"0.00"),
            "return_total": format_amount(restock, u"0.00"),
        }

    def get_stock_type_options(self):
        """库存类型下拉选项（来自库存类型字典）。"""
        catalog = api.get_tool(SETUP_CATALOG_ID)
        if catalog is None:
            return []
        brains = catalog(
            portal_type=STOCK_TYPE_PORTAL_TYPE,
            is_active=True,
            sort_on="sortable_title",
            sort_order="ascending",
        )
        options = []
        for brain in brains:
            uid = getattr(brain, "UID", None)
            if not uid:
                continue
            options.append({
                "uid": uid,
                "title": api.get_title(brain) or uid,
            })
        return options

    def get_supplier_options(self):
        """供应商下拉选项（来自 SENAITE 供应商字典）。"""
        catalog = api.get_tool(SETUP_CATALOG_ID)
        if catalog is None:
            return []
        brains = catalog(
            portal_type=SUPPLIER_PORTAL_TYPE,
            is_active=True,
            sort_on="sortable_title",
            sort_order="ascending",
        )
        options = []
        for brain in brains:
            uid = getattr(brain, "UID", None)
            if not uid:
                continue
            options.append({
                "uid": uid,
                "title": api.get_title(brain) or uid,
            })
        return options
