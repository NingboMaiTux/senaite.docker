# -*- coding: utf-8 -*-
"""稳定性方案「时间点行」增删规则 —— 唯一实现。

业务约定（需求原文）：

1. **新增**：任何方案（含已经开始的方案）都可以新增时间点行；
   新增行的状态一律是「待放置（pending_placement）」。
2. **删除**：只有「待放置」的行可以删除；
   「进行中（active）」「已完成（completed）」的行**不允许删除**。

为什么需要 ``detail_uid``
------------------------

明细行在 DataGrid 里的**行号不是身份**：允许删行、允许拖动排序，
一旦删掉中间一行，后面所有行的行号都会平移。
而 ``StabilityTimepointTask.sequence`` 是照着行号写的 ——
按行号把「明细行」和「任务对象」配对，删中间行会**删错对象**
（实测推演：3 行删第 2 行时，被删掉的是第 3 行那条待放置任务，
第 2 行那条"进行中"的任务反被留下并错配）。

因此每一行带一个 ``detail_uid``：生成后**永不改变**，
删行/排序都不会影响其它行；任务对象也记同一个值，两边靠它配对。
历史数据没有该列时，按"没有 id 的行按出现顺序"兜底配对，
并在下一次保存时补齐（见 ``subscribers.ensure_plan_detail_uids``）。

为什么还要"保留字段兜底"
------------------------

DataGrid 表单只提交 **schema 里声明过的列**，而明细行里有两个
关键字段并不在 schema 里 / 界面上不可编辑：

``stock_batch``
    方案明细的库存批次引用，由「样品放置」页写回，**没有对应的 schema 字段**。
``analysis_request``
    关联样品（UIDReference，hidden），界面上不可编辑。

登样审计（``generated_at`` / ``generated_by``）虽然声明成了隐藏列，
但界面上同样改不了，提交值只会是空值 —— 一并按保留字段处理。

不兜底的话，「编辑一次方案」就会把排样结果、样品关联与登样审计
**静默清空**。所以 ``sanitize_submitted_rows`` 会在提交值为空时，
从原行把这些值带过来。

本模块是**纯逻辑**（不 import Zope/bika），便于用 py2.7 / py3 直接跑自检脚本。
"""

import re
import uuid
from datetime import datetime


try:  # py2 / py3 兼容：本环境是 py2.7，但自检脚本用 py3 跑
    string_types = (basestring,)  # noqa: F821
    text_type = unicode  # noqa: F821
except NameError:
    string_types = (str,)
    text_type = str


# 时间点（月）词表 —— **药典序列**，两个 schema（方案明细 / 时间点任务）共用这一份。
#
# 依据《中国药典》9001《原料药物与制剂稳定性试验指导原则》：
#   长期试验：0、3、6、9、12、18、24、36 月
#   加速试验：0、1、2、3、6 月
# 取并集即下面这组值。**注意含 0**：零点（0 点）是样品入箱前的基线点。
PHARMACOPOEIA_MONTHS = (0, 1, 2, 3, 6, 9, 12, 18, 24, 36)

# 零点：0 点 / 起始点（入箱前的基线点）
INITIAL_MONTHS = 0

# 任务标题的**落库形态**（一律英文 msgid，渲染时按语言翻译）：
#   TP 1 (3 Months)   普通时间点
#   TP 1 (Initial)    零点
TASK_TITLE_PATTERN = re.compile(u"^TP (\\d+) \\((\\d+) Months\\)$")
TASK_TITLE_INITIAL_PATTERN = re.compile(u"^TP (\\d+) \\(Initial\\)$")

# 明细行的稳定标识字段名（方案明细与时间点任务共用同一个键）
DETAIL_UID_FIELD = "detail_uid"

# 明细状态值：与 content/stabilityplan.py 的 DETAIL_STATUS_VOCABULARY 一致
STATUS_PENDING = "pending_placement"
# 「已放置」：只记了库存批次（出/放置动作），**还没有**登样。
# 2026-09-29 需求订正（先放置、再登样）：放置不再等同于"进行中"，
# 放置过的行仍然可以登样；登样后才会变成 active 并锁住。
STATUS_PLACED = "placed"
STATUS_ACTIVE = "active"
STATUS_COMPLETED = "completed"

# 明确认识的"已经开过"的状态，仅作说明/日志用。
#
# ⚠️ 判定受保护时**不要**用 `status in PROTECTED_STATUSES`：
# 规则是"还没登样的（待放置 / 已放置）可删"，非空且不在词表内的脏数据
# （例如历史遗留值）也必须按受保护处理（见 is_deletable / is_protected）。
PROTECTED_STATUSES = (STATUS_ACTIVE, STATUS_COMPLETED)

# 提交值缺失/为空时，要从原行带过来的字段。
# 这些字段都**不可在编辑表单里编辑**（hidden / 不在 schema 里），
# 提交上来只会是空值，不兜底等于每次保存都把它们清掉。
#
# ``detail_uid`` 也在其中：万一隐藏列没能把 id 提交上来，
# 靠"配对上哪一行"把原 id 带回去，行身份就不会因为一次保存而漂移，
# 已生成的时间点任务也就不会变成孤儿。
#
# ``generated_at`` / ``generated_by``（登样审计）同理：它们是隐藏列，
# 界面上改不了，但**必须**在保存时保留 —— 否则"这个样品是谁什么时候登的"
# 会被一次无关的方案编辑抹掉（GMP 场景下等于丢失审计痕迹）。
#
# ``revoked_at`` / ``revoked_by`` / ``revoke_reason``（撤销登样审计，阶段 4）
# 连隐藏列都不是（**不在 schema 里**），只靠这里兜底 —— 与 ``stock_batch`` 同类。
#
# ``voided_at`` / ``voided_by`` / ``void_reason``（行作废，阶段 6c）同理：
# 同样不是 schema 字段，只在"行缺席"时才由服务端写上去；
# 提交上来天然是空值（界面没有这三列），不兜底的话一次无关的方案保存
# 就会把"这行是什么时候被谁作废的"抹掉。
PRESERVED_FIELDS = (
    "detail_uid",
    "detail_status",
    "analysis_request",
    "stock_batch",
    "generated_at",
    "generated_by",
    "revoked_at",
    "revoked_by",
    "revoke_reason",
    "voided_at",
    "voided_by",
    "void_reason",
)


def new_detail_uid():
    """生成一个新的行标识。

    用 uuid4 的 hex：32 个 ASCII 字符、无分隔符，
    可以直接放进 DataGrid 的隐藏列，也不需要额外的序列号维护。
    """
    return uuid.uuid4().hex


def normalize_months(value):
    """把时间点月份归一成非负整数（兼容下拉回传的字符串 / 单值列表）。"""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    try:
        value = int(value)
    except Exception:
        return INITIAL_MONTHS
    return value if value >= 0 else INITIAL_MONTHS


def is_initial_month(months):
    """给定的月份是否**明确**为零点（0 点）。

    只有能解析成 ``0`` 的值才算；缺失 / 空 / 无法解析一律**不算**零点 ——
    零点会走"关联往期样品"这条特殊分支，脏数据不能误入。
    """
    if isinstance(months, (list, tuple)):
        months = months[0] if months else None
    if months is None:
        return False
    if isinstance(months, string_types) and not as_text(months).strip():
        return False
    try:
        return int(months) == INITIAL_MONTHS
    except Exception:
        return False


def is_initial_row(row):
    """该明细行是否为零点（0 点）行。

    零点 = 样品入箱前的基线点：业务上**不新建样品**，而是关联往期样品。
    """
    if not isinstance(row, dict):
        return False
    return is_initial_month(row.get("timepoint_days"))


def initial_row_seqs(rows):
    """明细里 0 点行的**行号**（从 1 起，可有多行）。

    行号与看板/登样页的 ``<plan_uid>::<seq>`` 同一口径：
    直接 ``enumerate(rows, start=1)``，非 dict 的行也占一个位置（不能跳过，
    否则算出来的行号会与页面上的行号错位）。
    """
    if not isinstance(rows, (list, tuple)):
        return []
    return [seq for seq, row in enumerate(rows, start=1) if is_initial_row(row)]


def has_initial_row(rows):
    """这批明细行里**有没有** 0 点行（基线点）。

    ★ 2026-09-30（B 方案）：0 点**不强制** —— 方案可以有、也可以没有
    （新建方案会预置一行，但用户可以删）。所以"有没有"会被反复问到：
    方案页提示条、任务看板提示条、登样页提示条都走这里（唯一实现）。

    口径与 :func:`is_initial_row` 完全一致：只有 ``timepoint_days``
    **明确等于 0** 才算，缺失 / 空 / 无法解析的脏值**不算**（脏数据不能冒充基线点）。
    """
    return bool(initial_row_seqs(rows))


def build_task_title(seq, months):
    """生成任务标题的**落库形态**（英文 msgid，渲染时按语言翻译）。

    * 零点：``TP 1 (Initial)``
    * 其它：``TP 1 (3 Months)``
    """
    try:
        seq = int(seq)
    except Exception:
        seq = 0
    months = normalize_months(months)
    if months == INITIAL_MONTHS:
        return u"TP {0} (Initial)".format(seq)
    return u"TP {0} ({1} Months)".format(seq, months)


def parse_task_title(raw):
    """解析任务标题，返回 ``(seq, months)``；解析不了返回 ``None``。

    零点标题返回 ``(seq, 0)``。落库的一律是英文形态（译文不会进 ZODB），
    所以这里只认英文。
    """
    if not raw:
        return None
    match = TASK_TITLE_INITIAL_PATTERN.match(as_text(raw))
    if match:
        return (int(match.group(1)), INITIAL_MONTHS)
    match = TASK_TITLE_PATTERN.match(as_text(raw))
    if match:
        return (int(match.group(1)), normalize_months(match.group(2)))
    return None


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


def normalize_status(value):
    """把任意形态的状态值归一成状态 token。

    空值一律当「待放置」—— 这与看板 ``_get_rows`` 的
    ``row.get("detail_status") or "pending_placement"`` 口径一致，
    保证"界面上看着能删"和"后端判成能删"是同一个结论。
    """
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    value = as_text(value).strip()
    return value or STATUS_PENDING


def is_deletable(row):
    """该行是否允许删除：**还没登样的**都允许（待放置 / 已放置）。

    ★ 2026-09-29 需求订正（先放置、再登样）：
      「样品放置」只记库存批次、没有样品，所以那种行（``placed``）仍然可以删；
      一旦登过样（``active``）或已完成（``completed``），就是实际执行结果，
      不允许再删 —— 与删除守卫、任务同步同一条口径。

    状态值缺失/为空时按「待放置」处理（与界面显示口径一致）；
    但**非空且不在词表内**的状态（脏数据）按"不允许删除"保守处理 ——
    "认不出它有没有开始"就不该让它被删掉。
    """
    if not isinstance(row, dict):
        return False
    status = normalize_status(row.get("detail_status"))
    return status in (STATUS_PENDING, STATUS_PLACED)


def is_protected(row):
    """该行是否受保护（不允许删除）：凡不是「待放置」的都算。"""
    if not isinstance(row, dict):
        return False
    return not is_deletable(row)


# ── 阶段 6c：行作废（软删除）────────────────────────────────────────────
#
# 需求（确认稿 Q1–Q5 / 2.5 / D6）：
#   * 方案明细**只增不减** —— 用户"删行"不再真删，改成写三个标记键；
#   * 标记键**不进 schema**（与 ``revoked_*`` 三件套、``stock_batch`` 同类），
#     不新增 ``detail_status`` 取值 —— 状态词表不动，8 处状态映射都不用改；
#   * 原因**选填**（与"方案状态变更原因必填"是两个口径）；
#   * 作废行**不参与过期计算**（否则会既显示"已过期"又显示"已作废"）。

VOIDED_AT_FIELD = "voided_at"
VOIDED_BY_FIELD = "voided_by"
VOID_REASON_FIELD = "void_reason"
VOID_FIELDS = (VOIDED_AT_FIELD, VOIDED_BY_FIELD, VOID_REASON_FIELD)


def is_voided(row):
    """该行是否已作废（软删除）。

    判据只看 ``voided_at`` 非空 —— 与"过期"一样是**行上的一个事实**，
    与 ``detail_status`` 无关（作废不改状态：那一行原来是什么状态就是什么状态，
    这样"作废前它到哪一步了"这个信息不会丢）。
    """
    if not isinstance(row, dict):
        return False
    return not _is_empty(row.get(VOIDED_AT_FIELD))


def void_marker(row):
    """作废三件套的可读摘要（日志 / 审计 extra / 页面展示用）。"""
    if not isinstance(row, dict):
        return {}
    return {
        "voided_at": as_text(row.get(VOIDED_AT_FIELD)).strip(),
        "voided_by": as_text(row.get(VOIDED_BY_FIELD)).strip(),
        "void_reason": as_text(row.get(VOID_REASON_FIELD)).strip(),
    }


def is_voidable(row):
    """这一行**从行自身的角度**还能不能被作废（与方案、样品无关）。

    两条：
    1. 还没作废过（作废是**一次性**的：再"作废"一次只会覆盖掉原来的时间/人/原因，
       把审计痕迹弄脏）；
    2. 状态上属于"可删"的那种（待放置 / 已放置）——
       已登样（``active``）/ 已完成（``completed``）的行是**实际执行结果**，
       既有口径就是"不许删"，作废沿用同一条（Q1：作废只替代"可删的行"）。

    ★ "有关联样品时必须样品已达终态"（C1）**不在这里**：
      它要读样品对象，本模块是纯逻辑、不认识 Zope（见模块头部的说明）。
      那道门在 ``voiding.can_void_row()``。
    """
    if not isinstance(row, dict):
        return False
    if is_voided(row):
        return False
    return is_deletable(row)


def void_row(row, actor=u"", reason=u"", now=None):
    """返回一份**已作废**的新行（不修改入参）。

    ``now`` 缺省取当前时间；时间戳格式与 ``generated_at`` / ``revoked_at``
    一致（``format_timestamp``），便于同一列里排序与比对。
    """
    new_row = dict(row or {})
    new_row[VOIDED_AT_FIELD] = format_timestamp(now)
    new_row[VOIDED_BY_FIELD] = as_text(actor).strip()
    new_row[VOID_REASON_FIELD] = as_text(reason).strip()
    return new_row


def format_timestamp(value=None):
    """``YYYY-MM-DD HH:MM`` 形态的时间戳（与 sampleautomation 同格式）。

    ★ 为什么不直接 import ``sampleautomation.format_timestamp``：
      那个模块要 import 的东西比本模块多，而本模块是"行规则"的最底层 ——
      两边都只是 ``datetime.strftime``，格式写在两处的风险由自检挡住
      （``check_voiding.py`` 断言两边格式串一致）。
    """
    if value is None:
        value = datetime.now()
    try:
        return value.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return as_text(value).strip()


def get_row_uid(row):
    """取行的稳定标识；没有则返回空串。"""
    if not isinstance(row, dict):
        return u""
    value = row.get(DETAIL_UID_FIELD)
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return as_text(value).strip()


def _as_row_list(rows):
    if not isinstance(rows, (list, tuple)):
        return []
    return [row for row in rows if isinstance(row, dict)]


# ---------------------------------------------------------------------------
# z3c.form 的「没有值」哨兵（NO_VALUE）—— 写库前的最后一道网
# ---------------------------------------------------------------------------
#
# 事故（2026-09-30 16:11，生产）：编辑页保存报 500，事务在 commit 时抛
#
#     PicklingError: Can't pickle <class 'z3c.form.interfaces.NO_VALUE'>:
#                    it's not the same object as z3c.form.interfaces.NO_VALUE
#
# 成因：DataGrid 的**整行**没提交上来（当时是"已作废的行被前端 disable 了"），
# 而计数标记 `form.widgets.plan_details.count` 还说有这一行 ——
# `MultiWidget.extract` 就会把**哨兵对象**塞进值列表当占位；
# 哨兵是 `z3c.form.interfaces.NO_VALUE` 这个类的**实例**，而模块里同名属性
# 是实例不是类，pickle 找不到它 → 落库那一刻整个事务炸掉，页面 500。
#
# 所以：**任何**要写进 `plan_details` 的值都必须先过这一层。
# 纯逻辑模块不许 import z3c.form（要能在 py3 下离线跑），按"类名 + 模块名"认。

SENTINEL_TYPE_NAMES = ("NO_VALUE", "NOVALUE")


def is_sentinel(value):
    """是不是 z3c.form 的 NO_VALUE 哨兵（实例**或**那个类本身）。

    只认 ``z3c.*`` 模块下的同名对象：业务里真出现一个叫 NO_VALUE 的
    字符串/枚举，不该被这里当哨兵吃掉（那会把用户的数据改没）。
    """
    if value is None:
        return False
    cls = type(value)
    if (getattr(cls, "__name__", "") in SENTINEL_TYPE_NAMES and
            (getattr(cls, "__module__", "") or "").split(".")[0] == "z3c"):
        return True
    # 哨兵**类**本身（`z3c.form.interfaces.NO_VALUE` 这个 class 对象）：
    # 直接 pickle 类时也会炸，同样要拦。
    return (getattr(value, "__name__", "") in SENTINEL_TYPE_NAMES and
            (getattr(value, "__module__", "") or "").split(".")[0] == "z3c")


def clean_row_value(value):
    """把哨兵值换成空串（唯一实现）；别的值原样返回。"""
    if is_sentinel(value):
        return u""
    return value


def clean_row(row):
    """清洗一个行字典；不是字典的行返回 ``None``（调用方决定丢还是留）。

    只替换哨兵值 —— 其余值保持**原对象**，这样行对象的同一性不变
    （自检和 `pairing` 都依赖"库里那一行"的身份）。
    """
    if not isinstance(row, dict):
        return None
    has_sentinel = False
    for value in row.values():
        if is_sentinel(value):
            has_sentinel = True
            break
    if not has_sentinel:
        return row
    return dict(
        (name, clean_row_value(value)) for name, value in row.items())


def clean_extracted_rows(rows):
    """清洗 Widget 提取出来的行列表，返回 ``(rows, dropped)``。

    ``dropped`` = 整行不是字典的条数。**丢**而不是猜：哨兵行意味着
    "这一行到底填了什么，服务端一无所知"，按位置去猜原行会张冠李戴；
    而 `sanitize_submitted_rows` 对"库里那一行缺席"有既定的处理
    （不许删的放回、能删的作废），不会丢数据。

    ★ 调用方（表单）必须把 ``dropped`` 报给用户：**丢行是异常情况**，
      不能悄悄吞掉 —— 否则用户看到的会是"我删的那一行没删掉"。
    """
    if not isinstance(rows, (list, tuple)):
        return [], 0
    cleaned = []
    dropped = 0
    for row in rows:
        new_row = clean_row(row)
        if new_row is None:
            dropped += 1
            continue
        cleaned.append(new_row)
    return cleaned, dropped


def pairing(stored, submitted):
    """把「库里已有的行」与「本次提交上来的行」配对。

    返回 ``[(stored_row, submitted_row_or_None, submitted_index_or_None), ...]``，
    顺序与 ``stored`` 一致；``submitted_row`` 为 ``None`` 表示该行被删掉了。

    配对策略分两轮：

    1. 有 ``detail_uid`` 的行 **按 uid 精确配对**（正常路径，排序/增删都不受影响）；
    2. 剩下的行（两边都没配上的）**按出现顺序**兜底配对。

    第 2 轮兜住两种情况：

    * 历史数据还没有 ``detail_uid``；
    * 隐藏列没能把 ``detail_uid`` 提交上来（降级模式）。

    第 2 轮只是兜底，不能长期依赖：只要经过一次保存，行身份就会被
    ``carry_over_preserved_fields`` 带回来或由 ``ensure_row_uids`` 补上，
    此后一律走第 1 轮。
    """
    stored = _as_row_list(stored)
    submitted = _as_row_list(submitted)

    result = [None] * len(stored)
    used = set()

    # 第 1 轮：按 detail_uid 精确配对
    by_uid = {}
    for index, row in enumerate(submitted):
        uid = get_row_uid(row)
        if uid and uid not in by_uid:
            by_uid[uid] = index
    for index, row in enumerate(stored):
        uid = get_row_uid(row)
        if not uid:
            continue
        match = by_uid.get(uid)
        if match is None or match in used:
            continue
        result[index] = (row, submitted[match], match)
        used.add(match)

    # 第 2 轮：剩下的行按出现顺序配对
    leftover_stored = [
        index for index, _row in enumerate(stored) if result[index] is None
    ]
    leftover_submitted = [
        index for index in range(len(submitted)) if index not in used
    ]
    for offset, stored_index in enumerate(leftover_stored):
        if offset >= len(leftover_submitted):
            break
        match = leftover_submitted[offset]
        result[stored_index] = (stored[stored_index], submitted[match], match)
        used.add(match)

    return [
        result[index] if result[index] is not None else (row, None, None)
        for index, row in enumerate(stored)
    ]


def protected_deletions(stored, submitted):
    """挑出"不允许删除、却不在提交数据里"的行。

    返回值是**被删掉的原行**列表（按原顺序）；空列表表示没有违规删除。
    """
    blocked = []
    for stored_row, submitted_row, _index in pairing(stored, submitted):
        if submitted_row is not None:
            continue
        if is_protected(stored_row):
            blocked.append(stored_row)
    return blocked


def ensure_row_uids(rows):
    """给缺 ``detail_uid`` 的行补上，返回 ``(rows, assigned_count)``。

    不修改入参里的 dict（返回新 dict），避免在事件处理里
    意外改动已经存进 ZODB 的对象。
    """
    result = []
    assigned = 0
    for row in _as_row_list(rows):
        if get_row_uid(row):
            result.append(row)
            continue
        new_row = dict(row)
        new_row[DETAIL_UID_FIELD] = new_detail_uid()
        result.append(new_row)
        assigned += 1
    return result, assigned


def carry_over_preserved_fields(stored, submitted):
    """把提交数据里丢掉/清空的「保留字段」从原行带回来。

    只认**配对上的那一行**（按 ``detail_uid``），不会串行。
    仅当提交值为"空"时才带过来：有值则以提交值为准。
    """
    stored = _as_row_list(stored)
    submitted = _as_row_list(submitted)

    rows = [dict(row) for row in submitted]
    for stored_row, submitted_row, submitted_index in pairing(stored, submitted):
        if submitted_row is None or submitted_index is None:
            continue
        target = rows[submitted_index]
        for name in PRESERVED_FIELDS:
            if not _is_empty(target.get(name)):
                continue
            value = stored_row.get(name)
            if _is_empty(value):
                continue
            target[name] = value
    return rows


def _is_empty(value):
    if value is None:
        return True
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    if isinstance(value, string_types):
        return not as_text(value).strip()
    return False


# ── 阶段 6b：不允许编辑的行（过期行）─────────────────────────────────────
#
# 需求原文："过期的时间点，不允许修改关联和登录样品，**只允许删除或者新增时间点**"。
# 所以这里的口径是：
#   * **改值** -> 一律丢弃（把原行放回去）；
#   * **删除** -> 仍然允许（走既有的 protected_deletions 那套守卫，
#     过期行的状态是待放置/已放置，本来就是可删的）。
#
# ★ 为什么"改值"要放回原行而不是拒绝保存整个表单：
#   用户可能同时改了别的行（合法的），整表拒绝会让他丢掉那些改动。
#   放回 + 明确提示"这一行已过期、改动被忽略"既保住了合法改动，
#   又不会让人以为改动生效了。


def _values_equal(left, right):
    """宽松比较两个行字段值。

    宽松的三处，都来自 DataGrid 的实际形态差异：
      * 空值三种形态（None / "" / []）应当等价；
      * 单元素列表与单值等价（引用字段在 DataGrid 里落库是 ``[uid]``，
        而比较时另一边可能是 ``uid``）；
      * 字符串两侧去空白后比较（下拉回传可能带空白）。
    """
    if _is_empty(left) and _is_empty(right):
        return True
    if isinstance(left, (list, tuple)) and len(left) == 1:
        left = left[0]
    if isinstance(right, (list, tuple)) and len(right) == 1:
        right = right[0]
    if isinstance(left, string_types) or isinstance(right, string_types):
        return as_text(left).strip() == as_text(right).strip()
    if isinstance(left, (list, tuple, dict)) or isinstance(right, (list, tuple, dict)):
        try:
            return list(left) == list(right)
        except Exception:
            return left == right
    return left == right


def locked_row_changes(stored, submitted, is_locked):
    """哪些"不允许编辑"的行被**真的改了**（返回原行列表，按原顺序）。

    只用于给用户提示 —— 真正把值放回去的是 :func:`restore_locked_rows`。

    ★ 比较时**跳过 ``PRESERVED_FIELDS``**：那些列在界面上是隐藏的
      （``detail_uid`` / ``analysis_request`` / ``stock_batch`` / 登样撤销审计…），
      提交上来天然是空值，拿它们比会把"其实没改"误判成"改了"，
      于是每次保存都弹一堆"改动被忽略"，提示就没人看了。
    """
    if is_locked is None:
        return []
    changed = []
    for stored_row, submitted_row, _index in pairing(stored, submitted):
        if submitted_row is None:
            continue                    # 被删掉的行由删除守卫管（允许删）
        try:
            locked = bool(is_locked(stored_row))
        except Exception:
            locked = False
        if not locked:
            continue
        for key in set(stored_row) | set(submitted_row):
            if key in PRESERVED_FIELDS:
                continue
            if not _values_equal(stored_row.get(key), submitted_row.get(key)):
                changed.append(stored_row)
                break
    return changed


def restore_locked_rows(stored, submitted, is_locked):
    """把"不允许编辑的行"按**原值**放回（返回新的行列表）。

    与 :func:`protected_deletions` / :func:`restore_blocked_rows` 的分工：

    * 那两个管"**不许删**"（受保护的行被删 -> 放回去 + 报错）；
    * 这个管"**不许改**" —— 删除仍然允许（需求：过期行只允许删除或新增）。

    配对按 ``detail_uid``（与别处同一套 ``pairing``），所以拖排序不会串行。
    """
    rows = list(_as_row_list(submitted))
    if is_locked is None:
        return rows
    for stored_row, submitted_row, submitted_index in pairing(stored, submitted):
        if submitted_row is None or submitted_index is None:
            continue
        try:
            if not is_locked(stored_row):
                continue
        except Exception:
            continue
        # 用**原行**覆盖提交值：这一行的所有改动（含隐藏列的形态差异）都作废，
        # 保留字段（样品/库存批次/审计）也就自然保住了。
        rows[submitted_index] = dict(stored_row)
    return rows


def sanitize_submitted_rows(stored, submitted, is_locked=None, void_guard=None,
                            now=None, actor=u""):
    """整理表单提交上来的明细行，返回 ``(rows, report)``。

    这是编辑表单保存前的**唯一入口**。阶段 6c 起，方案明细**只增不减**：
    "提交里缺席的行"不再被真删，而是被**作废**（写 ``voided_*`` 标记后留在原位）。

    依次做六件事：

    1. 逐行配对（``pairing``，按 ``detail_uid``）；
    2. **缺席的行**（= 用户在 DataGrid 里删了这一行）按下面三种情况处理：
       * 状态上不允许删（已登样 / 已完成 / 认不出的脏状态）-> 原样放回，
         记进 ``report["blocked"]``；
       * 已经作废过 -> 原样放回（**不重复作废**：会覆盖掉原来的时间/人/原因）；
       * ``void_guard(row)`` 说不许作废（C1：关联的样品还没到终态）->
         原样放回，记进 ``report["blocked_by_sample"]``；
       * 其余 -> **作废**：写 ``voided_at/by/reason`` 后放回原位，
         记进 ``report["voided"]``；
    3. 从原行带回 ``detail_status`` / ``analysis_request`` / ``stock_batch`` /
       登样与撤销与作废的审计字段（``PRESERVED_FIELDS``）；
    4. **把"不允许编辑的行"按原值放回**（过期的行、已作废的行）——
       记进 ``report["locked"]``；删除仍然允许（对过期行而言），
       而对已作废的行，删除请求已在第 2 步被拒（不重复作废）；
    5. 第 2 步放回的行插回**原来的位置**（``restore_blocked_rows`` 同一套逻辑）；
    6. 给缺 id 的行补 ``detail_uid``。

    :param is_locked: ``callable(row) -> bool``，判断**原行**是否不允许编辑
        （``automation.row_is_locked``：过期 **或** 已作废）；
        缺省 ``None`` = 不做这一步。
    :param void_guard: ``callable(row) -> (ok, reason)``，判断这一行**能不能作废**
        （``automation.can_void_row``：C1 前置条件 —— 关联样品必须已达终态）；
        缺省 ``None`` = 不拦（旧调用方的行为不变）。
    :param now: 作废时间戳（自检注入用）；``actor`` 是作废人。

    ``report`` 的四个清单都要给用户提示（调用方负责），否则就是
    "点了删除、行还在，但没人说为什么"。
    """
    stored = _as_row_list(stored)
    raw_submitted = list(submitted) if isinstance(submitted, (list, tuple)) else []
    submitted = _as_row_list(submitted)

    report = {
        "blocked": [],              # 不允许删除（状态层面）-> 原样放回
        "blocked_by_sample": [],    # C1 未满足 -> 原样放回；元素是 (行, 原因码, 明细)
        "voided": [],               # 本次被作废的行（已写入 voided_*）
        "locked": [],               # 改值被忽略的行（过期 / 已作废）
        "restored": 0,              # 本次"放回原位"的行数（**含**没进任何清单的：
                                    #   已经作废过的行 —— 调用方做行数守恒时
                                    #   必须用这个数，不能把四个清单加起来）
        "dropped_rows": len(raw_submitted) - len(submitted),   # 非字典行（哨兵）
    }

    # 状态层面的删除守卫：唯一实现在 protected_deletions（既有口径，6c 不变）。
    blocked_rows = protected_deletions(stored, submitted)
    blocked_ids = set([id(row) for row in blocked_rows])

    # ★ 起点是**全部提交上来的行**（包含用户新增的行）——
    #   `pairing()` 只按"库里已有的行"逐条给结果，用它当起点会把新增行丢掉。
    rows = [dict(row) for row in submitted]

    # 第 1+2 步：逐条看"库里已有的行"，处理那些**在提交里缺席**的行。
    restored = []                    # [(原下标, 行)]，稍后插回原位置
    voided_by_uid = {}               # 本次新作废的行：uid -> 作废后的行
    for index, (stored_row, submitted_row, _i) in enumerate(
            pairing(stored, submitted)):
        if submitted_row is not None:
            continue

        # 缺席 = 用户删掉了这一行
        if id(stored_row) in blocked_ids:
            # 状态层面不许删（已登样 / 已完成 / 认不出的脏状态）
            report["blocked"].append(stored_row)
            restored.append((index, dict(stored_row)))
            continue
        if is_voided(stored_row):
            # 已经作废过：不重复作废（否则覆盖掉原来的时间/人/原因）
            restored.append((index, dict(stored_row)))
            continue

        allowed = True
        code = u""
        detail = u""
        if void_guard is not None:
            try:
                decision = void_guard(stored_row)
            except Exception:
                # 判据本身出错时**不拦**：宁可让它作废，也不要让用户
                # "点了删除却什么也没发生、还说不出原因"。
                decision = (True, u"", u"")
            try:
                allowed = bool(decision[0])
                code = decision[1] if len(decision) > 1 else u""
                detail = decision[2] if len(decision) > 2 else u""
            except Exception:
                allowed, code, detail = True, u"", u""
        if not allowed:
            report["blocked_by_sample"].append((stored_row, code, detail))
            restored.append((index, dict(stored_row)))
            continue

        new_row = void_row(stored_row, actor=actor, reason=u"", now=now)
        report["voided"].append(new_row)
        restored.append((index, new_row))
        uid = get_row_uid(new_row)
        if uid:
            voided_by_uid[uid] = new_row

    # 第 3+4 步：保留字段兜底 + 锁定行按原值放回。
    rows = carry_over_preserved_fields(stored, rows)
    rows = restore_locked_rows(stored, rows, is_locked)

    # 第 5 步：把放回的行插回原位置。
    for index, row in restored:
        rows.insert(min(index, len(rows)), row)

    # 第 5b 步：★ 作废三件套是**服务端专有**字段 —— 提交上来的值一律不认。
    #   两层理由：
    #   ① **防伪造**：客户端只要自己塞一个 `voided_at`，就能绕过 C1 前置条件
    #      （"关联样品还在检验中"的行本该被拦下）—— 所以这三个键只能服务端写；
    #   ② **防覆盖**：反过来，"作废一个过期行"是需求明确允许的动作，
    #      而过期行同时是**锁定行**（`restore_locked_rows` 会用原行覆盖它）：
    #      只要顺序错了，刚写上的作废标记就会被原行盖掉，
    #      用户看到的是"点了删除、行回来了、也没作废"。
    #   做法：先把每个提交行的作废字段重置成**库里那份**，再单独写上本次新作废的行。
    stored_marker_by_uid = {}
    for row in stored:
        uid = get_row_uid(row)
        if uid:
            stored_marker_by_uid[uid] = void_marker(row)

    for position, row in enumerate(rows):
        uid = get_row_uid(row)
        if not uid or uid in voided_by_uid:
            continue
        marker = stored_marker_by_uid.get(uid)
        if marker is None:
            continue
        if all(as_text(row.get(name)).strip() == marker[name] or
               (not as_text(row.get(name)).strip() and not marker[name])
               for name in VOID_FIELDS):
            continue
        new_row = dict(row)
        for name in VOID_FIELDS:
            new_row[name] = marker[name] or u""
        rows[position] = new_row

    # 第 6 步：补行标识。
    rows, _assigned = ensure_row_uids(rows)

    # 第 7 步：★ 写库前的最后一道网 —— 行内哨兵值一律换成空串。
    #   哨兵（`z3c.form.interfaces.NO_VALUE` 实例）是**不可 pickle** 的，
    #   只要有一个漏进明细，整个事务会在 commit 时炸掉（2026-09-30 生产事故）。
    #   这一步只替换哨兵，不动别的值。
    rows = [clean_row(row) for row in rows]

    # 放回原位的行数：**含**"已经作废过、静默放回"的行（它们不在任何清单里）。
    report["restored"] = len(restored)

    # 锁定行的提示清单（必须在"放回"之后再算一遍 —— 这时行已经在位了）
    try:
        report["locked"] = locked_row_changes(stored, rows, is_locked)
    except Exception:
        report["locked"] = []
    return rows, report


def task_matches_row(task, row_uid, sequence):
    """判断一个 ``StabilityTimepointTask`` 是否属于某一行明细。

    优先按 ``detail_uid`` 配对；只有**任务自身没有 id** 时
    （本功能上线前创建的历史任务）才退回按 ``sequence`` 配对 ——
    否则一个带 id 的新任务可能被一个碰巧同序号的历史任务顶掉。
    """
    task_uid = as_text(getattr(task, DETAIL_UID_FIELD, None)).strip()

    if task_uid:
        return bool(row_uid) and task_uid == row_uid

    if row_uid:
        # 明细行有 id、任务没有 —— 这是引入 id 之前建的历史任务，
        # 不能拿序号去猜，交给调用方按"无 id 任务"兜底处理。
        return False

    try:
        return int(getattr(task, "sequence", 0) or 0) == int(sequence)
    except Exception:
        return False
