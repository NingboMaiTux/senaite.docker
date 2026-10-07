# -*- coding: utf-8 -*-
"""稳定性「自动登样」的**纯逻辑**：配置值解析、日期口径与生成前判定 —— 唯一实现。

本模块**不 import Zope / bika**，所以能直接用 py2.7 / py3 跑自检脚本
（与 `timepoints.py` 同一套路；对象级/registry 级的访问在 `automation.py`）。

为什么要它：
* "生成时刻"是**配置项**（默认 08:00），调度器只是高频来问"到点了吗" ——
  判定逻辑必须能脱离运行环境单独测；
* 零点回溯窗口、提前天数的边界（含不含当天）是**业务口径**，
  写错了会静默漏生成或误生成，必须能被断言覆盖；
* "时间点 -> 目标日期"（1 月 = 30 天）与"计划取样日期 = max(目标日期, 现在)"
  是全模块共用的口径：看板、任务对象同步、登样三处必须给出**同一个**日期，
  否则会出现"看板说到点了、登样说没到点"这种自相矛盾的状态。
"""

from datetime import datetime
from datetime import timedelta

from maitux.stability.timepoints import STATUS_COMPLETED
from maitux.stability.timepoints import STATUS_PENDING
from maitux.stability.timepoints import STATUS_PLACED
from maitux.stability.timepoints import is_initial_row
from maitux.stability.timepoints import is_voided
from maitux.stability.timepoints import normalize_months
from maitux.stability.timepoints import normalize_status

try:  # py2 / py3 兼容
    string_types = (basestring,)  # noqa: F821
    text_type = unicode  # noqa: F821
except NameError:
    string_types = (str,)
    text_type = str


# 站点级配置的默认值（registry 里没有记录时用这些）
DEFAULT_GENERATION_TIME = u"08:00"
DEFAULT_LEAD_DAYS = 0
DEFAULT_ZERO_POINT_LOOKBACK_DAYS = 30

# `HH:MM` 解析失败时的回落值（08:00）
FALLBACK_GENERATION_TIME = (8, 0)

# 时间点单位是「月」，而所有日期计算都按天做 —— 1 个月折算 30 天。
# ⚠️ 这是**全模块唯一**的折算系数：看板（browser/view.py）、任务同步
# （subscribers.py）、登样（samplegeneration.py）都调 target_date()，
# 不允许任何一处再写 `months * 30`（改了系数就该全局一起改）。
MONTH_DAYS = 30

# 登样回写字段（方案明细行）：生成时间与操作人。
# 与 detail_uid 一样是"隐藏列"——界面上不可编辑，但**必须在 schema 里声明**，
# 否则 DataGrid 表单保存时会把它们丢掉（见 timepoints.PRESERVED_FIELDS）。
GENERATED_AT_FIELD = "generated_at"
GENERATED_BY_FIELD = "generated_by"

# 「撤销登样」的审计字段（阶段 4）。
# ★ 刻意**不做成 schema 字段**：它们只是审计留痕，不是业务数据，也不需要出现在
#   DataGrid 的列里；落库形态与 ``stock_batch`` 同类（非 schema 键），
#   靠 timepoints.PRESERVED_FIELDS 在保存时带过来（否则编辑一次方案就没了）。
#   界面上看得见的那份审计写在行的 ``notes`` 里（追加一行，见 samplegeneration）。
REVOKED_AT_FIELD = "revoked_at"
REVOKED_BY_FIELD = "revoked_by"
REVOKE_REASON_FIELD = "revoke_reason"

# 生成前的判定结果（原因码）。界面文案由调用方按这些码翻译。
REASON_OK = u"ok"
REASON_ZERO_POINT = u"zero_point"
REASON_NOT_PENDING = u"not_pending"
REASON_ALREADY_GENERATED = u"already_generated"
REASON_NO_TARGET_DATE = u"no_target_date"
# 已完成的点不再登样（与"还没登样就能登"配套：放置过不算开始）
REASON_COMPLETED = u"completed"

# ── 阶段 6b：时间点「过期」（**计算**状态，不落库）─────────────────────────
#
# 需求口径（《方案状态与过期规则-需求确认稿》2.2 / D2）：
#   **过期 = 今天 > 窗口结束日**，且这一行**还没登样**（待放置 / 已放置）。
#
# ★ 为什么是"计算"而不是给 detail_status 加第 5 个值 `expired`：
#   ① timepoints.is_deletable() 对"非空但不在词表内"的状态是**保守判为不可删**
#      —— 新值不加白名单会得到与需求相反的行为；
#   ② 落库**不可逆**（以后规则放宽也回不去）；
#   ③ 一条日期规则本来就不该变成持久化状态（它每天都可能变）。
REASON_ROW_EXPIRED = u"row_expired"
# 关联（零点）那一套码**单独取值**：三套码各有各的文案表，
# 撞值会让"按码找文案"查错表（stage 3 的 LINK_NO_TARGET_DATE 就是这么定的）。
LINK_ROW_EXPIRED = u"link_row_expired"

# ── 阶段 6c：行「作废」（软删除，标记键落库、状态词表不动）──────────────────
#
# 需求口径（确认稿 Q1–Q5 / D6）：
#   * 方案明细**只增不减** —— 用户"删行"改成写 ``voided_at/by/reason``；
#   * 作废行**不再参与任何操作**（登样 / 关联 / 撤销 / 放置 / 自动登样）；
#   * 作废行**不算过期**（否则看板上会同时出现"已过期"和"已作废"两个标记，
#     而"过期"是给"还能作废、还能补录"的行用的提醒）。
REASON_ROW_VOIDED = u"row_voided"
# 同样单独取值（见上面 LINK_ROW_EXPIRED 的理由）。
LINK_ROW_VOIDED = u"link_row_voided"

# ── 0 点「关联往期样品」的结果码（阶段 3）──────────────────────────────────
#
# 与 REASON_* 同级：界面按码取文案，服务端只给码 + 参数（不拼中文）。
LINK_OK = u"ok"
LINK_UNKNOWN_ROW = u"unknown_row"
LINK_NOT_ZERO_POINT = u"not_zero_point"
LINK_UNKNOWN_SAMPLE = u"unknown_sample"
LINK_OUT_OF_WINDOW = u"out_of_window"
LINK_ALREADY_LINKED = u"already_linked"
# 刻意与 REASON_NO_TARGET_DATE（登样用）取不同的值：两套码分别由
# LINK_MESSAGES / REASON_MESSAGES 取文案，值相同会让"按码找文案"出现歧义。
LINK_NO_TARGET_DATE = u"link_no_target_date"

# 候选样品的"日期来源"标注（DateSampled 为空时退回 Created，列表里要说明用的是哪个）
DATE_SOURCE_SAMPLED = u"DateSampled"
DATE_SOURCE_CREATED = u"Created"

# ── 「撤销登样」的结果码（阶段 4）──────────────────────────────────────────
#
# 与 LINK_* / REASON_* 同级：界面按码取文案，服务端只给码（不拼中文）。
#
# ★ 取值刻意与 LINK_* / RESULT_* **不重复**（连"意思一样"的也不复用）：
#   三套码各自有 `*_MESSAGES` 文案表，"按码找文案"一旦撞值就会查错表
#   （阶段 3 的 LINK_NO_TARGET_DATE 就是为此单独取值的，这里沿用同一约定）。
REVOKE_OK = u"ok"
REVOKE_UNKNOWN_ROW = u"revoke_unknown_row"
REVOKE_ROW_CHANGED = u"revoke_row_changed"
# 这一行本来就没有样品可撤（没登过样）
REVOKE_NOTHING_TO_REVOKE = u"nothing_to_revoke"
# 「已完成」是最终结果，不允许撤销（与"完成的行不能删、不再登样"同一口径）
REVOKE_COMPLETED = u"completed_not_revocable"
# 撤销**必须填原因**（GMP：撤销动作要能解释）
REVOKE_REASON_REQUIRED = u"reason_required"
# 阶段 6c：这一行已经作废了，不允许再撤销它的登样
#   （作废行保持原样；要恢复流程请新增时间点）
REVOKE_ROW_VOIDED = u"revoke_row_voided"
# 原因的最短长度：一个字符的"无意义原因"不算填了（挡掉顺手点确定）
REVOKE_REASON_MIN_LENGTH = 2

# ── 到期扫描的「跳过桶」（阶段 4）──────────────────────────────────────────
#
# 定时入口每次调用都会报告"扫了什么、跳了什么"，这些桶就是摘要里的分类。
# 放在**纯逻辑**模块里（而不是 samplegeneration），是为了能脱离 Zope 自检；
# samplegeneration 从 here 引用，避免两处各写一份字符串。
SKIP_DISABLED_PLAN = u"disabled_plan"
SKIP_NOT_DUE = u"not_due"
SKIP_NOT_PENDING = u"not_pending"
SKIP_ALREADY_GENERATED = u"already_generated"
SKIP_ZERO_POINT = u"zero_point"
SKIP_COMPLETED = u"completed"
SKIP_NO_TARGET_DATE = u"no_target_date"
# ★ 被人工「撤销登样」过的行（``revoked_at`` 有值）：自动扫描**不再碰它**。
#
# 为什么必须有这一桶：撤销之后这一行又变成"到期 + 没样品"，定时任务下一次
# （cron 每 10 分钟一次）就会把它重新建出来 —— 那样「撤销登样」这个功能
# 在开了 cron 的环境里等于没用。自动化不能悄悄撤销人的决定：
# 撤销是人的决定，要重新登样请人工点「创建样品」（那条路径不受本桶影响）。
SKIP_REVOKED = u"revoked"

# 阶段 6b：窗口已过（过期）的行 —— 到期扫描**不再补生成**。
#
# ★ 这一桶就是需求里"暂停期间过期的点，恢复之后不会被补登"的**真正落点**：
#   那条要求不是靠"暂停/恢复"这两个动作实现的，而是靠这条**日期规则** ——
#   恢复后这些点的窗口早就过了，所以扫描时会落进这一桶。
SKIP_ROW_EXPIRED = REASON_ROW_EXPIRED

# 阶段 6c：已作废的行 —— 到期扫描**永不碰它**。
#
# ★ 与 SKIP_REVOKED 同一个道理：作废是**人的决定**（"这一行不要了"），
#   而作废之后这一行还是"到期 + 没样品"，扫描下一轮（cron 每 10 分钟）
#   就会把它重新建出来 —— 那样"作废"这个功能在开了 cron 的环境里等于没用。
SKIP_ROW_VOIDED = REASON_ROW_VOIDED

# 登样原因码 -> 跳过桶（`generation_check()` 判不通过时按这个归类）
SKIP_REASON_BY_CODE = {
    REASON_NOT_PENDING: SKIP_NOT_PENDING,
    REASON_ALREADY_GENERATED: SKIP_ALREADY_GENERATED,
    REASON_ZERO_POINT: SKIP_ZERO_POINT,
    REASON_COMPLETED: SKIP_COMPLETED,
    REASON_NO_TARGET_DATE: SKIP_NO_TARGET_DATE,
    REASON_ROW_EXPIRED: SKIP_ROW_EXPIRED,
    REASON_ROW_VOIDED: SKIP_ROW_VOIDED,
}

# 「序列化哨兵」：DataGrid 的隐藏列在"没有值"时会被渲染成这些字面量，
# 保存时又原样写回库里 —— 判定"有没有填"时必须当空（见 is_blank 的说明）。
PLACEHOLDER_VALUES = (u"<NO_VALUE>", u"NO_VALUE", u"<no value>")

# 方案级配置解析出来的问题（缺客户/样品模板/联系人/样品类型/检验项）。
#
# ★ 关于"客户"（2026-09-29 需求确认）：客户**维护在方案上**（方案模板可给默认值），
#   登样时自动带过去。样品模板自身"挂在客户下"只是**兜底**来源 ——
#   所以"样品模板不属于任何客户"本身**不是**问题，只有当三处都取不到客户时
#   才报 no_client。详见 automation.get_client()。
PROBLEM_NO_SAMPLE_TEMPLATE = u"no_sample_template"
PROBLEM_NO_CLIENT = u"no_client"
PROBLEM_CLIENT_TEMPLATE_MISMATCH = u"client_template_mismatch"
PROBLEM_NO_CONTACT = u"no_contact"
PROBLEM_CONTACT_OTHER_CLIENT = u"contact_other_client"
PROBLEM_NO_SAMPLE_TYPE = u"no_sample_type"
PROBLEM_NO_SERVICES = u"no_services"

# 「带名字」的报错文案（msgid）。
#
# 为什么要有它：只说"联系人与客户不是同一家"，用户还得自己翻是**谁家**的谁 ——
# 站点上 5 个客户各有关联人时，这条提示等于没说。占位符由
# `get_generation_config()["problem_data"]` 填（见 automation 的同名字段）。
MESSAGE_CONTACT_OTHER_CLIENT = (
    u"The Contact \"{contact}\" belongs to \"{contact_client}\", but the "
    u"samples are created for \"{client}\"."
)
MESSAGE_TEMPLATE_OTHER_CLIENT = (
    u"The Sample Template \"{template}\" belongs to \"{template_client}\", but "
    u"the samples are created for \"{client}\"."
)
# 保存方案/方案模板时清掉错配联系人的提示（portal message）。
MESSAGE_CONTACT_CLEARED = (
    u"The Contact \"{contact}\" belongs to \"{contact_client}\" and does not "
    u"match the Client \"{client}\": the Contact was cleared. Please select a "
    u"Contact of \"{client}\"."
)


def as_text(value):
    """把任意值安全转成 text（py2 下可能是 utf-8 字节串）。"""
    if value is None:
        return u""
    if isinstance(value, text_type):
        return value
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except Exception:
            return u""
    if isinstance(value, string_types):
        try:
            return value.decode("utf-8")
        except Exception:
            return u""
    try:
        return text_type(value)
    except Exception:
        return u""


def parse_generation_time(value):
    """把配置里的"生成时刻"解析成 ``(hour, minute)``。

    接受的写法：``08:00`` / ``8:00`` / ``08:00:00`` / ``0800``（两侧空格忽略）。
    **非法值一律回落 08:00** —— 配置写错不能让整套自动登样停摆，
    也不能让它跑到半夜去（所以不做"取当前时间"之类的兜底）。
    """
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    text = as_text(value).strip()
    if not text:
        return FALLBACK_GENERATION_TIME

    parts = text.replace(u"：", u":").split(u":")
    if len(parts) == 1 and len(text) == 4 and text.isdigit():
        # 兼容 0800 这种写法
        parts = [text[:2], text[2:]]
    if len(parts) < 2:
        return FALLBACK_GENERATION_TIME
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except Exception:
        return FALLBACK_GENERATION_TIME
    if not (0 <= hour <= 23) or not (0 <= minute <= 59):
        return FALLBACK_GENERATION_TIME
    return (hour, minute)


def format_generation_time(value):
    """``(hour, minute)`` -> ``u"HH:MM"``（日志/提示用）。"""
    hour, minute = parse_generation_time(
        u"%s:%s" % (value[0], value[1]) if isinstance(value, (list, tuple))
        else value)
    return u"%02d:%02d" % (hour, minute)


def resolve_int(default, *values):
    """按优先级取第一个"有填"的整数值；都没填则用 ``default``。

    "没填" = ``None`` / 空串。**0 是有效值**（例如"提前 0 天"= 当天），
    所以不能用 `if value` 判断 —— 这正是这类配置最容易写错的地方。
    """
    for value in values:
        if value is None:
            continue
        if isinstance(value, string_types) and not as_text(value).strip():
            continue
        try:
            return int(value)
        except Exception:
            continue
    return int(default)


def resolve_bool(default, *values):
    """按优先级取第一个"有填"的布尔值；都没填则用 ``default``。

    与 `resolve_int` 同理：``False`` 是有效值，不能被当成"没填"。
    """
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            return value
        if isinstance(value, string_types):
            text = as_text(value).strip().lower()
            if not text:
                continue
            if text in (u"true", u"1", u"yes", u"on"):
                return True
            if text in (u"false", u"0", u"no", u"off"):
                return False
            continue
        return bool(value)
    return bool(default)


def is_blank(value):
    """值是否按"没填"处理（``None`` / 空串 / 空序列 / 序列化哨兵）。

    ⚠️ ``0`` / ``False`` **不算空** —— 与本模块 `resolve_int` / `resolve_bool`
    的口径一致；把它们当空会让"0 月""关闭"这类有效值被静默忽略。

    列表/元组**递归**判定：引用字段在落库里可能是 ``[""]`` 这种"有一个空元素"
    的形态（表单/脚本写坏时）。若把它当"有值"，登样会误判成"已经登过样"而拒绝，
    所以只要所有元素都空就算空。

    ★ 还要把 **z3c.form 的序列化哨兵** 当空（2026-09-29 真机踩到）：
    DataGrid 的隐藏列（``generated_at`` / ``generated_by`` / ``detail_uid``…）
    在"没有值"时会被渲染成字面量 ``<NO_VALUE>``，保存时又原样写回库里 ——
    于是"这个字段没填"在数据里表现为**非空字符串**。
    不把它当空，``generated_at="<NO_VALUE>"`` 就会被判成"登过样"，
    历史行因此永远不能再登样（真机上就这么误判过一次）。
    """
    if value is None:
        return True
    if isinstance(value, dict):
        return all(is_blank(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return all(is_blank(item) for item in value)
    if isinstance(value, string_types):
        text = value.strip()
        if not text:
            return True
        return text in PLACEHOLDER_VALUES
    return False


def to_naive_datetime(value):
    """把任意日期时间值统一成**朴素（无时区）** ``datetime``；不可解析返回 ``None``。

    为什么必须有它：这一栈里同时存在三种日期形态 ——
    Zope ``DateTime``（字段值）、``datetime.datetime``（Python 计算）、
    字符串（表单/配置）。它们**不能直接互相比较**：
    ``DateTime > datetime`` 在部分版本上会抛 ``TypeError``，
    带时区与不带时区的 ``datetime`` 比较同样会抛。
    所有比较/算术一律先走这里，避免"某一条路径崩在比较上"。

    本函数是纯逻辑（只 duck-typing ``asdatetime`` / ``isoformat``），
    所以不 import Zope 也能测。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        naive = value
    else:
        converter = getattr(value, "asdatetime", None)
        if callable(converter):
            try:
                naive = converter()
            except Exception:
                return None
        elif isinstance(value, string_types):
            text = as_text(value).strip()
            if not text:
                return None
            naive = None
            for fmt in (u"%Y-%m-%d %H:%M:%S", u"%Y-%m-%d %H:%M",
                        u"%Y-%m-%dT%H:%M:%S", u"%Y-%m-%dT%H:%M",
                        u"%Y-%m-%d"):
                try:
                    naive = datetime.strptime(text, fmt)
                    break
                except Exception:
                    continue
            if naive is None:
                return None
        else:
            return None
    if getattr(naive, "tzinfo", None) is not None:
        try:
            naive = naive.replace(tzinfo=None)
        except Exception:
            return None
    return naive


def format_timestamp(value):
    """把日期时间格式化成落库用的一分钟精度字符串 ``YYYY-MM-DD HH:MM``。

    * 不写秒：本字段是"什么时候登的样"的审计信息，分钟足够，
      且固定长度便于人工比对与 SQL 式的字典序排序；
    * ``None`` 返回空串（不写 ``"None"`` —— 那会被当成一个真实的值）。
    """
    if value is None:
        return u""
    for attr in ("strftime", "ISO8601", "isoformat"):
        method = getattr(value, attr, None)
        if not callable(method):
            continue
        try:
            if attr == "strftime":
                return as_text(method(u"%Y-%m-%d %H:%M"))
            text = as_text(method())
        except Exception:
            continue
        # ISO 形式：``2026-08-23T15:42:00+00:00`` -> ``2026-08-23 15:42``
        if u"T" in text:
            text = text.split(u"T", 1)[0] + u" " + text.split(u"T", 1)[1][:5]
        return text[:16]
    return as_text(value)[:16]


def shift_days(value, days):
    """在日期值上加减天数，返回**朴素 ``datetime``**（不可解析时返回 ``None``）。

    ★ 为什么不直接 ``value + timedelta(days=n)``（实测踩过，务必看完）：

    这一栈里的"日期"有两种落库形态，取决于**是谁写进去的**：

    * 走添加/编辑表单（``senaite.core`` 的 ``DatetimeField``）-> 存的是标准库
      ``datetime``，``datetime + timedelta`` 正常；
    * 脚本/导入直接赋 ``DateTime(...)`` -> 存的是 Zope ``DateTime``，而本环境的
      ``DateTime.__add__`` **不支持 ``timedelta``**：它会把参数当"天数"去
      ``float(...)``，于是抛 ``TypeError: float() argument must be a string
      or a number``（HTTP 直接 500）。

    这类错误只在"数据是脚本灌进去的"方案上出现，用界面建的方案永远复现不了 ——
    所以**不能靠"我在界面上试过没问题"来判定这段代码是对的**。
    统一先归一成朴素 ``datetime`` 再算，两种形态就都安全了。
    """
    if value is None:
        return None
    naive = to_naive_datetime(value)
    if naive is None:
        # 认不出的形态：交给原对象自己去算（不吞异常，让调用方看见）
        return value + timedelta(days=days) if days >= 0 \
            else value - timedelta(days=-days)
    return naive + timedelta(days=days)


def target_date(start_time, months, month_days=MONTH_DAYS):
    """时间点的目标日期 = ``T0 + 月数 x 30 天``（返回朴素 ``datetime``）。

    ``start_time`` 缺失（方案没填 T0）时返回 ``None`` —— 调用方必须显式处理，
    不能拿"现在"顶替（那会让一个没有 T0 的方案自动生成一堆样品）。

    日期形态的坑见 ``shift_days`` 的说明。
    """
    if start_time is None:
        return None
    return shift_days(start_time, normalize_months(months) * int(month_days))


# ── 阶段 6b：时间点「过期」的唯一口径 ────────────────────────────────────


def window_end(start_time, months, window_days=None):
    """时间点的**窗口结束日** = 目标日期 + 窗口天数（返回朴素 ``datetime``）。

    ★ 这是"过期"判定的**唯一口径**（需求确认稿 D2）。
      与 ``target_date`` 同一个道理：看板的过期标记、登样预览、
      编辑页的行锁、到期扫描**四处**必须给出同一个日期 ——
      否则会出现"看板说已过期、登样说能登"这种自相矛盾。
      对象层入口是 ``automation.window_end``（同一份实现，别再写第二遍）。

    ``window_days`` 缺省 / 为 0 时窗口是**零宽**的（^= 目标日期当天），
    于是"过期"退化为"今天 > 目标日期"—— 对既有数据是**行为不变**的
    （站点上 window_days 全是 0）。

    负数按 0 处理（负数窗口没有意义，且会让"过期"变得不可预期）。
    """
    target = target_date(start_time, months)
    if target is None:
        return None
    days = resolve_int(0, window_days)
    if days < 0:
        days = 0
    return shift_days(target, days)


def row_is_expired(start_time, row, now):
    """这一行是否**已过期**（"今天 > 窗口结束日"）。

    四个条件同时成立才算过期：

    1. **窗口结束日早于今天**。比的是**日期**而不是时刻 ——
       窗口结束日当天仍然是有效的（"今天 > 窗口结束日"里的"今天"是日子）。
    2. **这一行还没登样**：状态 ∈ {待放置, 已放置}，且行上没有样品 / 登样审计。
       ★ 已经登过样（``active``）或已完成（``completed``）的行**不算过期** ——
         那些点的工作早就做完了；把它们标成"过期"会让看板出现一批
         "过期但其实已经做完"的行，还会连带在编辑页上把正常行也锁住。
       ★ 用 ``is_generated`` 而不是只看状态：历史数据里"放置过"的行状态是
         ``active``，而"状态被改回 pending 但行上还留着样品"也可能出现 ——
         判据要与 ``generation_check`` 完全一致。
    3. 方案有 T0（没有目标日期就没有"窗口"可言）。
    4. **这一行没被作废**（阶段 6c）。作废行已经"退出流程"了：
       再给它标一个"已过期"既没有意义（它不需要补录、也不需要提醒），
       又会让看板上同一行出现两个互相矛盾的标记。

    ``now`` 缺失时返回 ``False``：读不到"现在"就不要判过期
    （宁可放行也不能凭空把一批行锁死）。
    """
    if not isinstance(row, dict):
        return False
    if is_voided(row):
        return False
    status = normalize_status(row.get("detail_status"))
    if status not in (STATUS_PENDING, STATUS_PLACED):
        return False
    if is_generated(row):
        return False
    end = window_end(start_time, row.get("timepoint_days", 0),
                     row.get("window_days", 0))
    if end is None:
        return False
    today = to_naive_datetime(now)
    end_naive = to_naive_datetime(end)
    if today is None or end_naive is None:
        return False
    return today.date() > end_naive.date()


def resolve_sampling_date(target, now):
    """计划取样日期 ``SamplingDate`` = ``max(目标日期, 现在)``。

    为什么不能直接用目标日期：AR 的 ``SamplingDate`` 字段带 ``min="created"``，
    补登一个**已经过期**的时间点（目标日期在过去）时，直接把过去的时间写进去
    会被字段校验顶掉，整次登样失败。取两者较大者既满足字段约束，
    又保住了"目标日期还没到就按目标日期"的语义（计划取样日期=预期取样日）。

    比较前两边都走 ``to_naive_datetime`` 归一：``target`` 常是 Zope ``DateTime``
    （字段值），``now`` 是朴素 ``datetime``，直接比会抛 ``TypeError``。
    返回值是**胜出的那个原对象**（不强行转换类型，调用方按自己的需要再转）。
    """
    if target is None:
        return now
    if now is None:
        return target
    left = to_naive_datetime(target)
    right = to_naive_datetime(now)
    if left is None:
        return now
    if right is None:
        return target
    return target if left > right else now


def is_generated(row):
    """这一行**真的登过样**了吗 —— 看样品关联与登样审计，而不是只看状态。

    ★ 2026-09-29 需求订正（先放置、再登样）：
      「样品放置」只写库存批次（状态置为 ``placed``），**没有**样品；
      历史数据里"放置过"的行状态还是 ``active``。所以状态不能当唯一判据 ——
      真正登过样的行一定有 ``analysis_request`` 或 ``generated_at``（登样时写入），
      这两个字段才是"已经开始了、不许再登"的证据。
    """
    if not isinstance(row, dict):
        return False
    if not is_blank(row.get("analysis_request")):
        return True
    return not is_blank(row.get("generated_at"))


def generation_check(row, target=None, generate_zero_point=False,
                     blocked_reason=None, expired=False, voided=False):
    """判断某一行明细现在是否**可以**登样，返回 ``(ok, reason)``。

    判据（顺序即优先级，界面只展示第一条命中的原因）：

    0. **方案级拒绝**（``blocked_reason``）—— 方案被暂停 / 终止时一律拒绝。
       ★ 为什么由调用方传进来、而不是本函数去读方案状态：
         本函数只认"行"，方案状态是 ``plan_status`` 的事 ——
         让 sampleautomation 反过来 import plan_status 会成环
         （plan_status 要用本模块的 as_text / format_timestamp）。
         分层是：``plan_status`` 判方案能不能写 -> 把原因码交给这里做最优先的短路。
    1. **已完成的点**不再登样（完成是最终结果，不能被覆盖）；
    2. **已经登过样的行**不重复登样（``analysis_request`` / ``generated_at`` 非空）——
       ★ 注意：「样品放置」过的行**不受影响**（放置只记库存批次），
       仍然可以继续登样（2026-09-29 需求订正：先放置、再登样）；
    3. **已作废的行**（``voided``，阶段 6c）—— 作废就是"这一行不要了"，
       任何自动化都不该再碰它（与"被撤销过的行"同一个道理，见 SKIP_REVOKED）；
    4. **已过期的时间点**（``expired``，阶段 6b）—— 窗口已过就不再登样
       （需求："过期的时间点不允许登录样品"）。
       ★ 这一条同时管住了**自动补生成**：到期扫描也要把它传进来，
         否则"暂停期间过期的点"恢复后会被补登 —— 而那正是需求明确不要的。
    5. **零点不新建样品**：需求口径是"0 点关联往期样品"，
       自动/批量登样一律跳过（``generate_zero_point=True`` 仅供将来的例外场景）；
    6. 没有目标日期（方案没填 T0）不能登样 —— 不知道登哪一天。

    ★ 作废（3）排在过期（4）之前：作废行本来就不再被判为"过期"
      （见 ``row_is_expired``），但调用方可能自己算过期 —— 先报"已作废"
      对用户更有用（"这一行已经作废了"比"它过期了"更接近事实）。

    本函数**只判定、不动作**，所以能脱离 Zope 断言；
    真正的建样与回写在 `maitux.stability.samplegeneration`。
    """
    # 0) 方案级拒绝优先：用户最需要知道的是"这个方案停了"，
    #    而不是"这一行还没有目标日期"这种次要原因。
    if blocked_reason:
        return (False, blocked_reason)
    if not isinstance(row, dict):
        return (False, REASON_NOT_PENDING)
    if normalize_status(row.get("detail_status")) == STATUS_COMPLETED:
        return (False, REASON_COMPLETED)
    if is_generated(row):
        return (False, REASON_ALREADY_GENERATED)
    # 3) 作废：排在过期与"零点是关联不是登样"之前（见上面 docstring 的说明）
    if voided or is_voided(row):
        return (False, REASON_ROW_VOIDED)
    # 4) 过期：排在"零点是关联不是登样"之前 —— 方案停了、点过期了，
    #    这些是"现在什么都不能做"的事实，比"该走哪条路"更该先说。
    if expired:
        return (False, REASON_ROW_EXPIRED)
    if is_initial_row(row) and not generate_zero_point:
        return (False, REASON_ZERO_POINT)
    if target is None:
        return (False, REASON_NO_TARGET_DATE)
    return (True, REASON_OK)


def zero_point_window(t0, lookback_days):
    """零点的可关联窗口 ``(最早, 最晚)``，两端都是**朴素 ``datetime``**。

    口径：样品日期必须落在 ``[T0 - N 天, T0]`` —— **含 T0 当天**，
    不含更早的（这就是需求里"最多能关联样品的时间区间"）。
    ``lookback_days`` 为 0 或负数时窗口退化为"仅 T0 当天"。

    两端都过一遍 ``shift_days``（含 0 天的那一端），是为了让窗口边界与
    "查出来的样品日期"是**同一种形态** —— 否则边界比较会踩
    ``DateTime`` 与 ``datetime`` 混比的坑（见 ``shift_days``）。
    """
    if t0 is None:
        return (None, None)
    days = resolve_int(DEFAULT_ZERO_POINT_LOOKBACK_DAYS, lookback_days)
    if days < 0:
        days = 0
    return (shift_days(t0, -days), shift_days(t0, 0))


def choose_sample_date(sampled, created):
    """候选样品"参与窗口判定的日期"：**取样日期优先，缺失退回创建日期**。

    返回 ``(naive datetime 或 None, 来源标注)``；来源是
    :data:`DATE_SOURCE_SAMPLED` / :data:`DATE_SOURCE_CREATED` / 空串。
    列表里必须把来源显示出来 —— 否则"这个样品为什么算在窗口内"看不出来。
    """
    for value, source in ((sampled, DATE_SOURCE_SAMPLED),
                          (created, DATE_SOURCE_CREATED)):
        moment = to_naive_datetime(value)
        if moment is not None:
            return (moment, source)
    return (None, u"")


def in_zero_point_window(date, window):
    """``date`` 是否落在零点窗口 ``[T0 - N, T0]`` 内（**两端都含**）。

    ``window`` 由 :func:`zero_point_window` 给出；缺 T0 时窗口是 ``(None, None)``，
    这时一律判 False（没有 T0 就没有"往期"的定义）。
    """
    start, end = window if window else (None, None)
    # ★ 两端都先归一：窗口可能来自"显示用的格式化字符串"或 Zope DateTime，
    #   直接比较会踩 `can't compare datetime.datetime to unicode`（真机踩过）。
    start = to_naive_datetime(start) if start is not None else None
    end = to_naive_datetime(end)
    if end is None:
        return False
    moment = to_naive_datetime(date)
    if moment is None:
        return False
    if start is not None and moment < start:
        return False
    return moment <= end


def row_links_sample(row, sample_uid):
    """这一行明细是否**已经关联了**给定样品。

    引用字段在库里可能是 ``u"uid"`` / ``[u"uid"]`` / 含空元素的列表，
    统一按"把所有元素取出来比对"处理；``sample_uid`` 为空一律 False。
    """
    if not isinstance(row, dict) or not sample_uid:
        return False
    value = row.get("analysis_request")
    if isinstance(value, (list, tuple)):
        candidates = value
    else:
        candidates = [value]
    wanted = as_text(sample_uid).strip()
    if not wanted:
        return False
    for candidate in candidates:
        if as_text(candidate).strip() == wanted:
            return True
    return False


def is_generation_due(target, now, lead_days=0, generation_time=None):
    """现在是否到了"该给这一行生成样品"的时刻。

    条件：``now >= 目标日期 - 提前天数``，且**当天的生成时刻已过**
    （生成时刻默认 08:00，取自配置）。

    * ``lead_days = 0``（默认）表示目标日期当天生成；
    * 只比到"分钟"，不比秒 —— 调度器可能每 10 分钟来问一次。
    """
    if target is None or now is None:
        return False
    days = resolve_int(DEFAULT_LEAD_DAYS, lead_days)
    due_date = target - timedelta(days=days)
    hour, minute = parse_generation_time(generation_time)

    # 先比日期：目标日还没到，直接不算到点
    if now.date() < due_date.date():
        return False
    if now.date() > due_date.date():
        # 已经过了目标日（例如调度器停了几天）—— 补生成
        return True
    # 同一天：要等配置的时刻
    return (now.hour, now.minute) >= (hour, minute)


# ── 「撤销登样」的纯逻辑（阶段 4）──────────────────────────────────────────


def reason_is_blank(reason):
    """撤销原因算不算"没填"。

    规则：去空白后长度 < :data:`REVOKE_REASON_MIN_LENGTH` 一律算没填 ——
    要求"必须填原因"就得挡掉顺手敲一个字符的情况，否则这条审计形同虚设。
    """
    return len(as_text(reason).strip()) < REVOKE_REASON_MIN_LENGTH


def status_after_revoke(row):
    """撤销登样后，这一行该回到哪个状态。

    * 放过库存批次的行（``stock_batch`` 有值）-> **已放置（placed）**；
    * 其它行 -> **待放置（pending_placement）**。

    ★ 为什么不无脑回「待放置」：本模块的口径是"放置只记库存批次、登样才置进行中"
    （2026-09-29 需求订正）。撤销掉的是**登样**这一步，放置那一步的事实还在 ——
    回成"待放置"会让看板显示"还没放置"，而库存批次明明已经占了。
    两者的共同点是：**都允许删除**（``is_deletable``），所以不回退保护状态。
    """
    if not isinstance(row, dict):
        return STATUS_PENDING
    if is_blank(row.get("stock_batch")):
        return STATUS_PENDING
    return STATUS_PLACED


def is_revoked(row):
    """这一行**曾经**被撤销过登样（``revoked_at`` 有值）。"""
    if not isinstance(row, dict):
        return False
    return not is_blank(row.get(REVOKED_AT_FIELD))
