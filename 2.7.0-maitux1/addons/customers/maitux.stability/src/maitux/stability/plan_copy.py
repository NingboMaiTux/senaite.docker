# -*- coding: utf-8 -*-
"""稳定性方案复制（Copy Plan）的公共逻辑。

业务链路：
1. 「稳定性方案」列表页勾选一个方案 -> 点「复制计划」；
2. ``workflow_action_copy_plan`` 适配器校验后跳到新建计划表单
   （``++add++StabilityPlan?copy_from_uid=<uid>``）；
3. 表单按被复制方案的字段与时间点明细预填，用户确认/修改后保存；
4. 保存时 ``subscribers.stability_plan_added`` 会按明细重新生成时间点任务。

复制规则（与需求约定一致）：
* 计划字段（名称/说明/方案模板/T0/贮存数量/单位/附件）整体复制；
* 时间点明细整体复制，但状态统一重置为"待放置"，并清空样品与库存批次关联
  —— 新方案必须重新排样，不能继承旧方案的样品进度。

约定：界面文案一律写英文 msgid，由 ``i18n.translate_stability`` 翻译；
明细的清理规则只在这里实现一份，前后端共用（前端调用
``@@plan_copy_defaults`` 拿到的就是这里处理过的数据）。
"""

from datetime import datetime

from bika.lims import api
from DateTime import DateTime

from maitux.stability.title import strip_copy_suffix


try:  # py2 / py3 兼容：环境本身是 py2.7，但保持与本包其它模块一致的写法
    string_types = (basestring,)  # noqa: F821
except NameError:
    string_types = (str,)


# 新建计划表单上的复制来源参数
COPY_SOURCE_PARAM = "copy_from_uid"

# 复制出来的名称后缀：**存英文 msgid**，显示时按语言替换（见 title.localize_copy_suffix）。
# 中文注释：早期版本把翻译后的后缀直接落库，于是中文站复制出的方案切到英文站
# 仍然显示"副本"。这里统一只存英文，由 Title() 按当前语言渲染。
COPY_SUFFIX = u"Copy"

# 明细状态默认值：与 content/stabilityplan.py 的 DETAIL_STATUS_VOCABULARY 保持一致
DETAIL_STATUS_DEFAULT = "pending_placement"

# 复制明细时需要重置的字段与重置值：
#   detail_status    -> 回到"待放置"，避免新方案直接继承旧方案的进度；
#   analysis_request -> 旧方案已关联的样品（新方案要重新排样）；
#   stock_batch      -> 旧方案已排的库存批次。
DETAIL_RESET_VALUES = {
    "detail_status": DETAIL_STATUS_DEFAULT,
    "analysis_request": u"",
    "stock_batch": u"",
}

# IStabilityPlanDetailSchema 的字段全集。
# 历史数据可能缺列，而 DataGrid 的行校验要求每一列都存在，
# 所以复制时统一补齐（缺的用下面的默认值）。
DETAIL_ROW_KEYS = (
    "packaging_specification",
    "storage_condition",
    "orientation",
    "timepoint_days",
    "window_days",
    "analysis_specification",
    "analysis_profile",
    "analysis_request",
    "inspection_quantity",
    "batch",
    "detail_status",
    "notes",
)

DETAIL_ROW_DEFAULTS = {
    "window_days": 0,
    "inspection_quantity": 0,
    "detail_status": DETAIL_STATUS_DEFAULT,
}

# 明细里需要连同展示记录一起下发给前端的 UID 引用字段
# （前端 UIDReference 控件只有拿到记录才能显示已选内容）。
DETAIL_REFERENCE_FIELDS = (
    "packaging_specification",
    "storage_condition",
    "analysis_specification",
    "analysis_profile",
    "batch",
)

# 计划级需要复制的数量字段
PLAN_QUANTITY_FIELDS = ("sample_quantity", "reserve_quantity")

START_TIME_FORMAT = "%Y-%m-%d %H:%M"


def first(value):
    """取列表/元组的第一项，兼容单值与多值两种历史数据。"""
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


def extract_uid(value):
    """从任意形态的引用值里取出 UID 字符串。"""
    value = first(value)
    if value is None:
        return ""
    if isinstance(value, dict):
        value = value.get("uid") or value.get("UID") or value.get("value") or ""
    if isinstance(value, string_types):
        return value.strip()
    return ""


def to_unicode(value):
    """把任意值安全转成 unicode（py2 下 Title() 可能是 utf-8 字节串）。"""
    if value is None:
        return u""
    try:
        return api.safe_unicode(value)
    except Exception:
        try:
            return value.decode("utf-8")
        except Exception:
            try:
                return unicode(value)  # noqa: F821
            except Exception:
                return u""


def record_for(obj):
    """UID 引用控件的展示记录（与 @@plan_template_defaults 的格式一致）。"""
    if obj is None:
        return {}
    return {
        "uid": api.get_uid(obj),
        "url": api.get_url(obj),
        "Title": to_unicode(api.get_title(obj) or api.get_id(obj)),
        "Description": to_unicode(api.get_description(obj) or u""),
    }


def to_datetime(value):
    """把 DateTime/datetime 统一成本地时间（去时区）的 datetime，识别不了返回 None。

    前端 datetime 控件提交/回填的都是**本地时间**字符串
    （见 senaite.core 的 DatetimeDataConverter），所以这里先按站点时区换算再取掉时区，
    否则被复制方案的 T0 会整体偏移一个时区差。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, DateTime):
        try:
            dt = value.asdatetime()
        except Exception:
            return None
    else:
        return None

    if getattr(dt, "tzinfo", None) is not None:
        try:
            from senaite.core.api import dtime
            tz = dtime.get_os_timezone()
            if tz and dtime.is_valid_timezone(tz):
                dt = dtime.to_zone(dt, tz)
        except Exception:
            pass
        try:
            dt = dt.replace(tzinfo=None)
        except Exception:
            pass
    return dt


def format_start_time(value):
    """把 T0 格式化成 datetime 控件能直接吃的 "YYYY-MM-DD HH:MM"。"""
    dt = to_datetime(value)
    if dt is None:
        return u""
    return dt.strftime(START_TIME_FORMAT)


def get_start_time_value(plan):
    """被复制方案的 T0（本地时间、无时区），用于给 datetime 字段/控件预填。"""
    if plan is None:
        return None
    return to_datetime(getattr(plan, "start_time", None))


def get_plan_by_uid(uid):
    """按 UID 取稳定性方案对象；不是方案或不存在时返回 None。"""
    uid = extract_uid(uid)
    if not api.is_uid(uid):
        return None
    plan = api.get_object_by_uid(uid)
    if plan is None:
        return None
    if api.get_portal_type(plan) != "StabilityPlan":
        return None
    return plan


def get_copy_source(request=None):
    """从请求里取出被复制的方案对象。

    参数名是 ``copy_from_uid``：与列表页跳转新建表单时带的参数保持一致。
    """
    if request is None:
        try:
            request = api.get_request()
        except Exception:
            request = None
    if request is None:
        return None

    uid = None
    try:
        uid = request.get(COPY_SOURCE_PARAM)
    except Exception:
        uid = None
    if not uid:
        try:
            uid = request.form.get(COPY_SOURCE_PARAM)
        except Exception:
            uid = None
    return get_plan_by_uid(uid)


def get_plan_template_uid(plan):
    """返回方案关联的模板 UID（方案模板是新建表单的必填项）。"""
    if plan is None:
        return ""
    return extract_uid(getattr(plan, "plan_template", None))


def can_copy_plan(plan):
    """方案是否可以复制。

    方案模板在新建表单里是必填且隐藏的，源方案缺模板时进去也存不了，
    所以这里提前拦下来，避免把用户带到一个填不完的表单。
    """
    if plan is None:
        return False
    if api.get_portal_type(plan) != "StabilityPlan":
        return False
    return api.is_uid(get_plan_template_uid(plan))


def build_copied_title(plan):
    """复制出来的名称：原标题 + 副本后缀。

    后缀**只存英文 msgid**（``Copy``），显示阶段由
    ``title.localize_copy_suffix`` 按当前语言渲染 —— 否则"复制时是中文站"
    这个历史状态会被永久写进数据里。

    这里读的是 **raw 标题**：``Title()`` 返回的是当前语言渲染结果，
    直接拿来拼接会让后缀越滚越长（"11 - 副本 - Copy - 副本"）。
    """
    getter = getattr(plan, "raw_title", None)
    raw = getter() if callable(getter) else api.get_title(plan)
    title = to_unicode(strip_copy_suffix(to_unicode(raw or u"")))
    if not title:
        title = to_unicode(api.get_id(plan) or u"")
    if not title:
        return COPY_SUFFIX
    return u"{0} - {1}".format(title, COPY_SUFFIX)


def build_copy_rows(plan):
    """复制时间点明细（返回可以直接落库的行）。

    保留时间点参数（时间点/窗口期/包装规格/贮存条件/检验标准或 Profile/
    批次/检验数量/备注），重置状态并清空样品与库存批次关联。

    注意：这里不写 ``*_record`` 之类的展示辅助字段 —— 这些只在
    ``build_copy_data`` 里拼给前端用，不能落进库里。
    """
    details = getattr(plan, "plan_details", None) or []
    rows = []
    for row in details:
        if not isinstance(row, dict):
            continue

        new_row = {}
        for key, value in row.items():
            if key.endswith("_record"):
                # 历史数据里可能存过展示记录，一律丢弃后重建
                continue
            new_row[key] = value

        # 补齐 schema 字段，避免历史数据缺列导致复制出来的明细存不进去
        for key in DETAIL_ROW_KEYS:
            if key not in new_row:
                new_row[key] = DETAIL_ROW_DEFAULTS.get(key, u"")

        # 状态重置为"待放置"，并清空旧方案的样品与库存批次关联
        for key, value in DETAIL_RESET_VALUES.items():
            new_row[key] = value

        for name in DETAIL_REFERENCE_FIELDS:
            new_row[name] = extract_uid(new_row.get(name))

        rows.append(new_row)
    return rows


def build_copy_rows_payload(plan):
    """在复制出的明细行上补充 UID 引用控件的展示记录，供前端预填。"""
    payload = []
    for row in build_copy_rows(plan):
        item = dict(row)
        for name in DETAIL_REFERENCE_FIELDS:
            uid = extract_uid(item.get(name))
            obj = api.get_object_by_uid(uid) if api.is_uid(uid) else None
            item[name + "_record"] = record_for(obj) if obj is not None else {}
        payload.append(item)
    return payload


def build_copy_data(plan):
    """组装新建表单预填所需的数据（前端 ``@@plan_copy_defaults`` 用的就是它）。"""
    if plan is None:
        return {}

    template_uid = get_plan_template_uid(plan)
    template = api.get_object_by_uid(template_uid) if api.is_uid(template_uid) else None

    unit_uid = extract_uid(getattr(plan, "unit", None))
    unit = api.get_object_by_uid(unit_uid) if api.is_uid(unit_uid) else None

    data = {
        "uid": api.get_uid(plan),
        "url": api.get_url(plan),
        "title": to_unicode(api.get_title(plan) or u""),
        "copied_title": build_copied_title(plan),
        "description": to_unicode(getattr(plan, "description", u"") or u""),
        "plan_template": template_uid,
        "plan_template_record": record_for(template) if template is not None else {},
        "start_time": format_start_time(getattr(plan, "start_time", None)),
        "unit": unit_uid,
        "unit_record": record_for(unit) if unit is not None else {},
        "plan_details": build_copy_rows_payload(plan),
    }
    for name in PLAN_QUANTITY_FIELDS:
        data[name] = getattr(plan, name, 0) or 0
    return data
