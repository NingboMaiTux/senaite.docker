# -*- coding: utf-8 -*-
"""批次到期提醒：在"到期前 N 天"开始提醒，并在批次列表里着色。

需求口径
--------
1. **提醒天数配置在 Stock（库存物料）上**：``expiry_reminder_days`` ——
   批次的到期日进入"到期前 N 天"这个窗口时开始提醒；0 = 关闭提醒。
2. **批次列表按行着色**（见 ``browser/stockbatches.py``）：
   * 已过期        -> 红色（``row-expiry-expired``）
   * 到期提醒中    -> 黄色（``row-expiry-reminder``）

设计要点
--------
* 判定"是否已过期"复用 ``stockbatchexpiry.is_due_for_expiry``，
  与"过期自动同步"（``sync_expired_batches``）保持同一口径，避免两处判断不一致。
* 计算逻辑里与 Zope 无关的部分（``compute_reminder_state``）单独抽出，
  便于用纯单元测试覆盖边界（正好第 N 天、已过期、未配置、无到期日）。
"""

from bika.lims import api
from DateTime import DateTime

from maitux.stock.i18n import translate_stock
from maitux.stock.stockbatchexpiry import is_due_for_expiry


# 未显式配置时的默认提醒天数（与 Stock schema 的 default 保持一致）
DEFAULT_REMINDER_DAYS = 30

# 行 CSS class（样式见 browser/static/expiry-reminder.css）
ROW_CLASS_REMINDER = u"row-expiry-reminder"
ROW_CLASS_EXPIRED = u"row-expiry-expired"

STATE_EXPIRED = u"expired"
STATE_REMINDER = u"reminder"


def to_int(value, default=None):
    """宽松地取整数（None/空串/非法值 -> default）。"""
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default


def compute_reminder_state(days_left, reminder_days):
    """纯函数：根据"还剩多少天"和"提醒天数"返回 (state, days_left)。

    :param days_left: 距到期还有多少天（负数/0 表示已过期）
    :param reminder_days: 提醒天数；None 或 <0 视为未配置（用默认值），0 表示关闭
    :returns: (state, days_left)；state ∈ {"", "reminder", "expired"}
    """
    if days_left is None:
        return u"", None
    try:
        days_left = float(days_left)
    except (TypeError, ValueError):
        return u"", None

    if days_left <= 0:
        return STATE_EXPIRED, days_left

    reminder_days = to_int(reminder_days, DEFAULT_REMINDER_DAYS)
    if reminder_days is None or reminder_days <= 0:
        # 0 = 关闭提醒（只标已过期）
        return u"", days_left
    if days_left <= reminder_days:
        return STATE_REMINDER, days_left
    return u"", days_left


def get_reminder_days(stock):
    """取 Stock 上配置的提醒天数。

    * 未设置（老对象没有这个字段）-> ``DEFAULT_REMINDER_DAYS``
    * 显式 0 -> 关闭提醒
    """
    value = getattr(stock, "expiry_reminder_days", None)
    days = to_int(value, None)
    if days is None:
        return DEFAULT_REMINDER_DAYS
    return days


def to_datetime(value):
    """把任意"时间值"统一转成 Zope DateTime（兼容 datetime / DateTime / 字符串）。

    为什么需要：批次的 ``expiry_date`` 在不同数据来源下可能是
    ``datetime.datetime``（naive）也可能是 Zope ``DateTime``，
    两者直接相减会抛 TypeError —— 表现就是"快到期的批次不变黄"。
    """
    if value is None:
        return None
    if isinstance(value, DateTime):
        return value
    try:
        return DateTime(value)
    except Exception:
        pass
    # 兜底：先转 ANSI 字符串再解析
    try:
        from senaite.core.api import dtime
        ansi = api.safe_unicode(dtime.to_ansi(value, show_time=True) or u"")
        if ansi:
            return DateTime(ansi)
    except Exception:
        pass
    return None


def days_between(expiry, now):
    """返回 expiry - now 的天数（浮点）；无法计算时返回 None。"""
    expiry_dt = to_datetime(expiry)
    now_dt = to_datetime(now)
    if expiry_dt is None or now_dt is None:
        return None
    try:
        return float(expiry_dt - now_dt)
    except Exception:
        return None


def default_expiry_from_stock(batch, stock=None):
    """新建批次时，用物料上的"批次默认到期日"预填批次的到期日。

    语义（与字段标题一致）：
    * 主数据（Stock）上的那个到期日是**默认值 / 参考有效期**，不是权威数据；
    * **权威数据是批次自己的 `expiry_date`** —— 到期提醒、使用记录查询/追溯
      都读批次的值；
    * 因此这里只在批次没有填到期日时预填，**绝不覆盖**用户已填的值。

    :returns: True 表示确实写了（调用方负责 reindex）
    """
    if not api.is_object(batch):
        return False
    if getattr(batch, "expiry_date", None):
        return False
    if stock is None:
        stock = get_batch_stock(batch)
    if stock is None:
        return False
    value = getattr(stock, "expiry_date", None)
    if not value:
        return False
    try:
        batch.expiry_date = value
    except Exception:
        return False
    return True


def get_batch_expiry(batch):
    """批次的到期时间（没有则 None）。"""
    expiry = getattr(batch, "expiry_date", None)
    if not expiry:
        return None
    return expiry


def get_batch_stock(batch):
    """批次关联的 Stock（没有则 None）。"""
    try:
        from maitux.stock.usageapproval import get_batch_stock as _get
        return _get(batch)
    except Exception:
        return None


def get_batch_reminder(batch, stock=None, now=None):
    """返回批次的到期提醒信息（给列表行着色用）。

    :returns: dict:
        state      : "" / "reminder" / "expired"
        days_left  : float 或 None
        row_class  : 追加到 ``item["state_class"]`` 的 CSS class（可能为空）
        badge_text : 已翻译的提示文案（可能为空）
        badge_class: 徽标用的 bootstrap class（可能为空）
    """
    empty = {
        "state": u"",
        "days_left": None,
        "row_class": u"",
        "badge_text": u"",
        "badge_class": u"",
    }
    if not api.is_object(batch):
        return empty

    expiry = get_batch_expiry(batch)
    if expiry is None:
        return empty

    # 已销毁的批次不再提醒（与 is_due_for_expiry 的口径一致）
    if api.safe_unicode(api.get_review_status(batch) or u"") == u"destroyed":
        return empty

    if now is None:
        try:
            from senaite.core.api import dtime
            now = dtime.now()
        except Exception:
            return empty

    # 1) 是否已过期：复用既有判定，保证与自动过期同步一致
    expired = False
    try:
        expired = bool(is_due_for_expiry(batch, now=now))
    except Exception:
        expired = False

    if expired:
        state, days_left = STATE_EXPIRED, 0.0
    else:
        days_left = days_between(expiry, now)
        if days_left is None:
            return empty
        if stock is None:
            stock = get_batch_stock(batch)
        reminder_days = get_reminder_days(stock) if stock is not None else None
        state, days_left = compute_reminder_state(days_left, reminder_days)

    if not state:
        return empty

    if state == STATE_EXPIRED:
        return {
            "state": state,
            "days_left": days_left,
            "row_class": ROW_CLASS_EXPIRED,
            "badge_text": translate_stock(u"Already expired"),
            "badge_class": u"badge-danger",
        }

    # 提醒窗口内：向上取整，避免"还剩 0.3 天"显示成 0
    import math
    days_text = int(math.ceil(float(days_left)))
    return {
        "state": state,
        "days_left": days_left,
        "row_class": ROW_CLASS_REMINDER,
        "badge_text": translate_stock(
            u"{0} day(s) to expiry").format(days_text),
        "badge_class": u"badge-warning",
    }


def reminder_badge_html(info):
    """把提醒信息渲染成小徽标 HTML（列表单元格用）。"""
    if not info or not info.get("badge_text"):
        return u""
    return (
        u'<span class="badge {cls} ml-1">{text}</span>'.format(
            cls=info.get("badge_class") or u"badge-secondary",
            text=info.get("badge_text") or u"",
        )
    )
