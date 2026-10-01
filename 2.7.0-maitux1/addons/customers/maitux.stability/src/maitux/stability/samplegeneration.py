# -*- coding: utf-8 -*-
"""稳定性「登样」—— 按样品模板建样并回写明细行（**对象级唯一实现**）。

需求口径（2026-09-28 评审已锁定）：

* 客户、样品类型、检验项**一律取自样品模板**（``SampleTemplate``）；
  联系人取方案上的联系人（方案级覆盖方案模板）；
* 计划取样日期 ``SamplingDate = max(目标日期, 现在)``；
* **不写** ``DateSampled`` —— 稳定性样品是"手工作样"进箱，实际取样日期由
  实验室在收样时填；先写死会造成"已取样"的假象（并且会让自动收样被触发）；
* 时间点的目标日期 = ``T0 + 月数 x 30 天``（口径在 ``sampleautomation``）；
* 建样成功后回写明细行：``analysis_request`` / ``detail_status=active`` /
  ``generated_at`` / ``generated_by``，并把时间点任务对象上的状态同步过去。

为什么把这段从视图里拆出来
--------------------------

阶段 2 是"手工点按钮登样"，阶段 4 是"定时自动登样" —— 两者**必须**是同一份实现，
否则会出现"手动登的样有审计字段、自动登的样没有"这类分叉。
所以视图（``browser/samplegen.py``）只做"选行 / 提示 / 跳转"，
建样与回写全在这里，阶段 4 的定时入口直接复用 ``generate_samples_for_plan``。

几个必须提权的点
----------------

``create_analysisrequest`` 会写 ``Template`` / ``SamplingDate`` / ``Contact`` 等字段，
它们在 AR 上是**字段级权限**（``FieldEditTemplate`` 等），普通登记员没有；
``plone.dexterity`` 容器写子对象也要求 ``cmf.DeleteObjects``
（平台坑，见 ``subscribers`` 的长注释与 README）。
所以建样与写回都包在 ``as_privileged_user()`` 里 —— 能走到这里的用户
已经过了视图层的 ``Modify portal content`` 校验，提权只是绕过**字段级**这几道门。
"""

from datetime import datetime

from bika.lims import api
from bika.lims.api.security import as_privileged_user
from bika.lims.utils.analysisrequest import create_analysisrequest
from DateTime import DateTime
from senaite.core import logger

from maitux.stability import automation
from maitux.stability import audit
from maitux.stability import plan_status
from maitux.stability import sampleautomation as sa
from maitux.stability.indexing import ensure_indexed
from maitux.stability.sampleautomation import GENERATED_AT_FIELD
from maitux.stability.sampleautomation import GENERATED_BY_FIELD
from maitux.stability.sampleautomation import LINK_ALREADY_LINKED
from maitux.stability.sampleautomation import LINK_NO_TARGET_DATE
from maitux.stability.sampleautomation import LINK_NOT_ZERO_POINT
from maitux.stability.sampleautomation import LINK_OK
from maitux.stability.sampleautomation import LINK_OUT_OF_WINDOW
from maitux.stability.sampleautomation import LINK_UNKNOWN_ROW
from maitux.stability.sampleautomation import LINK_UNKNOWN_SAMPLE
from maitux.stability.sampleautomation import REASON_OK
from maitux.stability.sampleautomation import REVOKED_AT_FIELD
from maitux.stability.sampleautomation import REVOKED_BY_FIELD
from maitux.stability.sampleautomation import REVOKE_COMPLETED
from maitux.stability.sampleautomation import REVOKE_NOTHING_TO_REVOKE
from maitux.stability.sampleautomation import REVOKE_OK
from maitux.stability.sampleautomation import REVOKE_REASON_FIELD
from maitux.stability.sampleautomation import REVOKE_REASON_REQUIRED
from maitux.stability.sampleautomation import REVOKE_ROW_CHANGED
from maitux.stability.sampleautomation import REVOKE_UNKNOWN_ROW
from maitux.stability.sampleautomation import as_text
from maitux.stability.sampleautomation import choose_sample_date
from maitux.stability.sampleautomation import format_timestamp
from maitux.stability.sampleautomation import generation_check
from maitux.stability.sampleautomation import in_zero_point_window
from maitux.stability.sampleautomation import is_generation_due
from maitux.stability.sampleautomation import reason_is_blank
from maitux.stability.sampleautomation import resolve_sampling_date
from maitux.stability.sampleautomation import row_links_sample
from maitux.stability.sampleautomation import status_after_revoke
from maitux.stability.sampleautomation import target_date as _target_date
from maitux.stability.sampleautomation import to_naive_datetime
from maitux.stability.sampleautomation import zero_point_window
from maitux.stability.timepoints import STATUS_ACTIVE
from maitux.stability.timepoints import STATUS_COMPLETED
from maitux.stability.timepoints import STATUS_PENDING
from maitux.stability.timepoints import get_row_uid
from maitux.stability.timepoints import is_initial_row
from maitux.stability.timepoints import normalize_status
from maitux.stability.timepoints import task_matches_row


def _field_value(obj, name):
    """读字段值（属性可能是值、也可能是访问器方法）。"""
    if obj is None:
        return None
    value = getattr(obj, name, None)
    if callable(value):
        try:
            value = value()
        except Exception:
            return None
    return value


def _first(value):
    """取引用字段的第一个值（DataGrid 里常是单元素列表）。"""
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


def plan_block_reason(plan):
    """方案级拒绝原因码（暂停 / 终止）；方案可写时返回 ``None``。

    ★ 唯一判据在 ``automation.can_modify_plan`` -> ``plan_status.can_modify_plan``。
      本函数只是把它暴露成"写库路径与预览路径共用的一处短路"：

      * ``describe_generation``（页面预览）—— 传 ``blocked_reason`` 给 generation_check；
      * ``generate_samples_for_plan`` / ``link_sample_to_row`` /
        ``revoke_sample_from_row``（真正写库）—— 循环里最先判它。

      页面与服务端必须给出**同一个**结论，否则就是"页面上说能登、提交后被拒"
      （或者更糟：页面上说不能登、直接 POST 却登上了）。
    """
    if plan is None:
        return None
    try:
        ok, reason = automation.can_modify_plan(plan)
    except Exception:
        logger.exception("Failed to resolve the plan state of %r", plan)
        return None
    return None if ok else reason


def row_expired(plan, row, now):
    """这一行现在是否已过期（阶段 6b）。

    ★ 判据的唯一实现在 ``automation.row_is_expired`` ->
      ``sampleautomation.row_is_expired``；这里只是让本模块内部调用更短。
      **写库路径与预览路径必须都走它** —— 页面与服务端口径不一致是这一块
      最容易出的问题（与 ``plan_block_reason`` 同一条纪律）。
    """
    return automation.row_is_expired(plan, row, now)


def row_voided(row):
    """这一行是否已作废（阶段 6c）。

    ★ 判据的唯一实现在 ``automation.row_is_voided`` -> ``timepoints.is_voided``；
      登样 / 关联 / 撤销 / 放置 / 到期扫描**全部**要过这道门
      （作废 = "这一行不要了"，任何自动化与人工操作都不该再碰它）。
    """
    return automation.row_is_voided(row)


# 结果原因码（**不在这里翻译**：视图按码取文案，脚本按码做断言）
RESULT_CREATED = "created"
RESULT_ERROR = "error"
RESULT_ROW_CHANGED = "row_changed"
RESULT_UNKNOWN_ROW = "unknown_row"
# 行标识里的方案 uid 解析不出来（目录陈旧等情况）——
# 与"行不存在"分开报，便于现场判断是数据陈旧还是行被删了。
RESULT_UNKNOWN_PLAN = "unknown_plan"


def current_user_id():
    """当前用户的 id（写进 ``generated_by``）；取不到时返回空串。

    取不到不抛异常：审计字段缺失可以接受，**登样本身失败不可接受**。
    """
    user = None
    try:
        user = api.get_current_user()
    except Exception:
        user = None
    if user is None:
        return u""
    for name in ("getId", "getUserName"):
        method = getattr(user, name, None)
        if callable(method):
            try:
                value = method()
            except Exception:
                continue
            if value:
                return api.safe_unicode(value)
    value = getattr(user, "id", None)
    return api.safe_unicode(value) if value else u""


def to_field_datetime(value):
    """把 naive ``datetime`` 转成 AR 日期字段能直接吃的 ``DateTime``。

    为什么要显式给 ``DateTime(y, m, d, h, mi)`` 而不是传字符串：
    字符串要经过平台的日期格式解析（``dtime`` 支持多种格式，写错一个字符就静默变成
    "现在"），而 y/m/d 构造没有歧义。
    """
    if value is None:
        return None
    if isinstance(value, DateTime):
        return value
    naive = to_naive_datetime(value)
    if naive is None:
        return None
    return DateTime(naive.year, naive.month, naive.day,
                    naive.hour, naive.minute, 0)


def build_sample_values(config, sampling_date):
    """构造 ``create_analysisrequest`` 的 ``values``。

    ⚠️ ``Analyses`` 不在这里：``to_service_uids()`` 只认 ``Analyses`` 与 ``Profiles``，
    ``values["Template"]`` **不会**自动带出模板的检验项（已核实），
    所以检验项必须由调用方作为 ``analyses`` 参数显式传入。

    ⚠️ 不设 ``DateSampled``：见模块说明。
    """
    values = {
        "Client": api.get_uid(config.get("client")),
        "Contact": api.get_uid(config.get("contact")),
        "SampleType": api.get_uid(config.get("sample_type")),
        "Template": api.get_uid(config.get("sample_template")),
        "SamplingDate": to_field_datetime(sampling_date),
    }
    return values


def create_sample(config, sampling_date, request):
    """按配置建一个 AnalysisRequest，返回 AR 对象（失败抛异常，由调用方兜住）。"""
    client = config.get("client")
    service_uids = list(config.get("service_uids") or [])
    values = build_sample_values(config, sampling_date)
    with as_privileged_user():
        return create_analysisrequest(
            client, request, values, analyses=service_uids)


def write_back_row(rows, index, sample_uid, generated_by, now):
    """把登样结果写进 ``plan_details`` 的行（**不改原 dict**）。

    ``analysis_request`` 存成"单元素列表"—— 与 ``LinkSampleView`` /
    ``CreateSampleView`` 的既有写法一致（该字段在 schema 上是 UIDReference，
    列表是它在 DataGrid 里的落库形态；读取方一律用 ``_first()`` 取第一个）。
    """
    row = rows[index]
    new_row = dict(row)
    new_row["analysis_request"] = [sample_uid]
    new_row["detail_status"] = STATUS_ACTIVE
    new_row[GENERATED_AT_FIELD] = format_timestamp(now)
    new_row[GENERATED_BY_FIELD] = generated_by
    rows[index] = new_row
    return new_row


def mirror_task(plan, seq, row_uid, sample_uid, sample_template_uid=None):
    """把「已登样」同步到对应的时间点任务对象（按 ``detail_uid`` 配对）。

    任务对象是明细的镜像，看板与工作流读的是它 —— 不同步会出现
    "明细已经是进行中、任务还是待放置"的双口径。
    只动**待放置**的任务：已经开始的任务是实际执行结果，不覆盖。

    同步两件事：
      * ``detail_status`` -> ``active``；
      * ``sample_template`` -> 该行选的样品模板（2026-09-29 起样品模板逐个时间点维护，
        任务对象上也有这一列，保持镜像一致，报表/看板才不会读到空值）。

    任务 schema 上没有 ``analysis_request`` 字段，所以样品关联本身不同步。
    """
    mirrored = 0
    try:
        children = list(plan.objectValues())
    except Exception:
        children = []
    for child in children:
        try:
            if api.get_portal_type(child) != "StabilityTimepointTask":
                continue
            if not task_matches_row(child, row_uid, seq):
                continue
            status = getattr(child, "detail_status", None) or "pending_placement"
            if status != "pending_placement":
                continue
            child.detail_status = STATUS_ACTIVE
            if sample_template_uid:
                try:
                    child.sample_template = sample_template_uid
                except Exception:
                    logger.exception(
                        "Failed to mirror sample template to timepoint task "
                        "for plan '%s' seq %s", api.get_path(plan), seq)
            child.reindexObject()
            # reindexObject() 在本包里可能是静默空操作（见 indexing 模块）：
            # 不显式编目，"已登样"的任务在看板/列表里就看不到。
            ensure_indexed(child)
            mirrored += 1
        except Exception:
            logger.exception(
                "Failed to mirror sample generation to timepoint task "
                "for plan '%s' seq %s", api.get_path(plan), seq)
    return mirrored


def generate_samples_for_plan(plan, seqs, request, generated_by=None,
                              now=None, expected_uids=None):
    """给一个方案里的若干个时间点行登样（**一个方案只写一次 plan_details**）。

    :param plan: ``StabilityPlan``
    :param seqs: 要登样的行号列表（1 起；与看板 ``plan_uid::seq`` 的口径一致）
    :param request: 当前请求（``create_analysisrequest`` 需要）
    :param generated_by: 审计用的操作人 id，缺省取当前用户
    :param now: 注入"现在"，便于自检
    :param expected_uids: ``{seq: detail_uid}``，用来做**行身份校验**：
        页面渲染到提交之间，方案可能被别的用户改过（删行/排序/改行），
        这时行号指向的已经不是同一行 —— 宁可不登样，也不能把样品挂到别的行上。
        库里那一行没有 ``detail_uid``（历史数据）时跳过校验。

    :returns: 每个行号一条结果 dict：``seq`` / ``ok`` / ``reason`` /
        ``sample_uid`` / ``sample_id`` / ``sampling_date`` / ``target_date`` /
        ``detail``（异常摘要，仅排查用）。
    """
    if now is None:
        now = datetime.now()
    if generated_by is None:
        generated_by = current_user_id()
    if expected_uids is None:
        expected_uids = {}

    rows = list(getattr(plan, "plan_details", None) or [])
    start_time = getattr(plan, "start_time", None)
    # 阶段 6a：方案级冻结判一次（不在循环里重复读工作流状态）。
    plan_blocked = plan_block_reason(plan)

    results = []
    changed = False
    mirrored = 0

    for seq in seqs:
        result = {
            "seq": seq,
            "ok": False,
            "reason": None,
            "sample_uid": u"",
            "sample_id": u"",
            "sampling_date": u"",
            "target_date": u"",
            "sample_template": u"",
            "sample_template_uid": u"",
            "service_count": 0,
            "detail": u"",
        }
        results.append(result)

        # 方案被暂停 / 终止：整个方案冻结，一行都不登。
        # 放在任何行级判据之前 —— 用户最需要知道的是"方案停了"。
        if plan_blocked:
            result["reason"] = plan_blocked
            continue

        try:
            index = int(seq) - 1
        except Exception:
            result["reason"] = RESULT_UNKNOWN_ROW
            continue
        if index < 0 or index >= len(rows):
            result["reason"] = RESULT_UNKNOWN_ROW
            continue

        row = rows[index]
        if not isinstance(row, dict):
            result["reason"] = RESULT_UNKNOWN_ROW
            continue

        # 行身份校验：库里有 id 就要求提交上来的 id 一致（空 = 页面没带，视为不一致）
        stored_uid = get_row_uid(row)
        expected_uid = expected_uids.get(seq)
        if stored_uid and stored_uid != (expected_uid or u""):
            result["reason"] = RESULT_ROW_CHANGED
            continue

        # 目标日期：T0 缺失时 target 为 None，交由 generation_check 判成 no_target_date
        target = _target_date(start_time, row.get("timepoint_days", 0))
        # 阶段 6b：过期的行不再登样（页面预览与这里**同一判据**）
        expired = row_expired(plan, row, now)
        # 阶段 6c：作废的行任何路径都不再登样
        voided = row_voided(row)
        ok, reason = generation_check(row, target,
                                      blocked_reason=plan_blocked,
                                      expired=expired, voided=voided)
        result["target_date"] = format_timestamp(target)
        result["expired"] = expired
        result["voided"] = voided
        if not ok:
            result["reason"] = reason
            continue

        # ★ 配置**逐行解析**（2026-09-29 需求订正）：样品模板维护在时间点行上，
        #   所以客户/样品类型/检验项都要按**这一行**选的模板来算 ——
        #   同一方案的不同时间点可以验不同的项目。
        config = automation.get_generation_config(plan, row)
        problems = list(config.get("problems") or [])
        result["sample_template"] = config.get("sample_template_title") or u""
        if config.get("sample_template") is not None:
            result["sample_template_uid"] = api.get_uid(
                config.get("sample_template"))
        result["service_count"] = len(config.get("service_uids") or [])
        if problems:
            # 配置不全（缺样品模板/客户/联系人/样品类型/检验项）：
            # 报出这一行缺什么，界面负责展示。
            result["reason"] = RESULT_ERROR
            result["detail"] = u";".join(problems)
            continue

        sampling_date = resolve_sampling_date(target, now)
        result["sampling_date"] = format_timestamp(sampling_date)

        try:
            ar = create_sample(config, sampling_date, request)
        except Exception as exc:
            logger.exception(
                "Failed to create stability sample for plan '%s' seq %s",
                api.get_path(plan), seq)
            result["reason"] = RESULT_ERROR
            result["detail"] = api.safe_unicode(str(exc))[:200]
            continue

        if ar is None:
            result["reason"] = RESULT_ERROR
            result["detail"] = u"create_analysisrequest returned None"
            continue

        sample_uid = api.get_uid(ar)
        write_back_row(rows, index, sample_uid, generated_by, now)
        changed = True
        result["ok"] = True
        result["reason"] = RESULT_CREATED
        result["sample_uid"] = sample_uid
        result["sample_id"] = api.get_id(ar) or u""

    if changed:
        try:
            plan.plan_details = rows
            plan.reindexObject()
            # 明细写回后同样显式编目（reindexObject 可能是空操作）。
            ensure_indexed(plan)
        except Exception:
            logger.exception(
                "Failed to write sample references back to plan '%s'",
                api.get_path(plan))
        else:
            # 明细写成功之后再镜像任务：反过来会出现"任务已完成、明细没记上"。
            for result in results:
                if not result.get("ok"):
                    continue
                index = int(result["seq"]) - 1
                row_uid = get_row_uid(rows[index])
                mirrored += mirror_task(plan, result["seq"], row_uid,
                                        result["sample_uid"],
                                        result.get("sample_template_uid") or u"")

        # 阶段 6b：把这次动作写进**审计快照**（A2）。
        #
        # 为什么必须显式补：本模块的写回是"直接改 plan_details + reindexObject"，
        # **不触发 IObjectModifiedEvent**，平台不会自动拍快照 ——
        # 在此之前"谁在什么时候给哪个时间点登了哪个样品"在审计页里完全看不到。
        #
        # ★ 自动/定时路径与人工路径走的是同一个写点，所以这里一处就覆盖了两条路径；
        #   区别只在 actor（定时任务传的是 scheduler / lazy-trigger）。
        created = [r for r in results if r.get("ok")]
        if created:
            audit.record_write_back(
                plan, audit.ACTION_GENERATE_SAMPLE, actor=generated_by,
                seqs=[r.get("seq") for r in created],
                samples=[r.get("sample_id") for r in created])

    logger.info(
        "maitux.stability: sample generation for plan '%s' -> "
        "created=%s failed=%s skipped=%s tasks_mirrored=%s (by %s)",
        api.get_path(plan),
        len([r for r in results if r.get("ok")]),
        len([r for r in results if r.get("reason") == RESULT_ERROR]),
        len([r for r in results if r.get("reason") not in (RESULT_CREATED,
                                                          RESULT_ERROR)]),
        mirrored, generated_by)
    return results


def find_link_conflict(sample_uid, plans=None, exclude_plan_uid=None,
                       exclude_seq=None):
    """这个样品**已经被哪一行关联过** —— 返回 ``(plan, seq)` 或 ``None``。

    ★ 强制唯一（客户确认 2026-09-29）：一个往期样品只能被关联一次，
    **同方案与跨方案都拦**。理由：0 点关联的是"这批样品的基线"，
    同一个样品被两个时间点/两个方案同时引用，后面按样品追数据时会分不清归属。

    实现是"扫方案明细"而不是维护反向索引：方案数量是**几十份**量级，
    而反向索引要额外维护一致性（写失败就会出现"索引说没关联、明细里其实有"）。
    将来方案多了再换成索引（那时才有必要）。
    """
    wanted = api.safe_unicode(sample_uid).strip()
    if not wanted:
        return None
    if plans is None:
        plans = []
        try:
            from senaite.core.catalog import SETUP_CATALOG
            brains = api.search({"portal_type": "StabilityPlan",
                                 "sort_on": "created"}, catalog=SETUP_CATALOG)
        except Exception:
            logger.exception("Failed to list stability plans for the link check")
            brains = []
        for brain in brains:
            try:
                plans.append(api.get_object(brain))
            except Exception:
                continue
    for plan in plans:
        if plan is None:
            continue
        plan_uid = api.get_uid(plan)
        if exclude_plan_uid and plan_uid == exclude_plan_uid:
            continue
        details = getattr(plan, "plan_details", None) or []
        for index, row in enumerate(details, start=1):
            if not isinstance(row, dict):
                continue
            if exclude_plan_uid and plan_uid == exclude_plan_uid \
                    and exclude_seq == index:
                continue
            if row_links_sample(row, wanted):
                return (plan, index)
    return None


def link_sample_to_row(plan, seq, sample_uid, request=None, linked_by=None,
                       expected_uid=None, now=None, lookback_days=None):
    """把「往期样品」关联到某个 **0 点行**（0 点登样的**唯一实现**）。

    校验（全部在服务端；前端只能提示）：

    1. 行存在、且是**零点行**（非零点请用"生成"，不是关联）；
    2. 方案有 T0（没有 T0 就没有"往期"的定义）；
    3. 样品存在、是 ``AnalysisRequest``；
    4. 样品日期（``DateSampled``，缺失退回 ``created``）落在窗口
       ``[T0 - N, T0]`` 内（``N`` = 站点配置 ``zero_point_lookback_days``）；
    5. 该样品没有被**任何方案**的行关联过（强制唯一）；
    6. 行身份（``expected_uid``）与页面打开时一致 —— 防止页面停留期间
       别人删行/排序导致"关联到另一行"。

    成功后的写回与登样保持一致：``analysis_request`` / ``detail_status=active``
    / 登样审计，并镜像到时间点任务、显式编目。

    返回结果 dict（与 ``generate_samples_for_plan`` 同构）：``ok`` / ``reason``
    （``sampleautomation.LINK_*``）/ ``detail`` / ``window`` / ``sample_id`` /
    ``sample_date`` / ``sample_date_source`` / ``conflict_plan`` / ``conflict_seq``。
    """
    if now is None:
        now = datetime.now()
    result = {
        "ok": False,
        "seq": seq,
        "reason": LINK_UNKNOWN_ROW,
        "detail": u"",
        "sample_uid": api.safe_unicode(sample_uid).strip(),
        "sample_id": u"",
        "sample_date": u"",
        "sample_date_source": u"",
        "window_start": u"",
        "window_end": u"",
        "conflict_plan": u"",
        "conflict_seq": None,
        "sample_template_uid": u"",
    }

    if plan is None or not isinstance(seq, int) or seq <= 0:
        return result
    rows = list(getattr(plan, "plan_details", None) or [])
    if seq > len(rows) or not isinstance(rows[seq - 1], dict):
        return result

    index = seq - 1
    row = rows[index]

    # 阶段 6a：方案被暂停 / 终止 -> 不允许关联往期样品（与登样同一道门）。
    # 放在行校验**之后**：行号本身不合法时，报"这一行不存在"比"方案已暂停"
    # 更有助于排查（前者说明页面参数错了，后者说明方案状态错了）。
    blocked = plan_block_reason(plan)
    if blocked:
        result["reason"] = blocked
        return result

    if expected_uid is not None:
        if get_row_uid(row) != api.safe_unicode(expected_uid).strip():
            result["reason"] = RESULT_ROW_CHANGED
            return result

    # 阶段 6c：**已作废的行不允许关联**（作废 = 这一行不要了）。
    #   ★ 排在过期之前：作废行本来就不再被判为"过期"，
    #     但先报"已作废"更接近事实。
    if row_voided(row):
        result["reason"] = sa.LINK_ROW_VOIDED
        return result

    # 阶段 6b：**过期的时间点不允许关联往期样品**（需求："过期的时间点不允许
    # 修改关联和登录样品"）。
    #
    # ★ 放在零点校验**之前**：对"过期 + 非零点"的行，先说"该时间点已过期"
    #   远比说"只有零点能关联"有用 —— 后者会把用户引去做"生成样品"，
    #   而那条路同样被过期挡住（两条路都封了，就该直接说"这个点已经过期"）。
    if row_expired(plan, row, now):
        result["reason"] = sa.LINK_ROW_EXPIRED
        return result

    if not is_initial_row(row):
        result["reason"] = LINK_NOT_ZERO_POINT
        return result

    window = zero_point_window(getattr(plan, "start_time", None), lookback_days)
    result["window_start"] = format_timestamp(window[0])
    result["window_end"] = format_timestamp(window[1])
    if window[1] is None:
        result["reason"] = LINK_NO_TARGET_DATE
        return result

    sample = api.get_object_by_uid(sample_uid, None) if api.is_uid(
        api.safe_unicode(sample_uid).strip()) else None
    if sample is None or api.get_portal_type(sample) != "AnalysisRequest":
        result["reason"] = LINK_UNKNOWN_SAMPLE
        return result

    result["sample_id"] = api.get_id(sample) or u""
    try:
        sampled = _field_value(sample, "DateSampled")
    except Exception:
        sampled = None
    try:
        created = api.get_creation_date(sample)
    except Exception:
        created = None
    moment, source = choose_sample_date(sampled, created)
    result["sample_date"] = format_timestamp(moment)
    result["sample_date_source"] = source
    if not in_zero_point_window(moment, window):
        result["reason"] = LINK_OUT_OF_WINDOW
        return result

    conflict = find_link_conflict(result["sample_uid"],
                                  exclude_plan_uid=api.get_uid(plan),
                                  exclude_seq=seq)
    if conflict is not None:
        result["reason"] = LINK_ALREADY_LINKED
        result["conflict_plan"] = api.get_title(conflict[0]) or api.get_id(
            conflict[0]) or u""
        result["conflict_seq"] = conflict[1]
        return result

    sample_uid_value = api.get_uid(sample)
    generated_by = linked_by or u""
    write_back_row(rows, index, sample_uid_value, generated_by, now)
    try:
        plan.plan_details = rows
        plan.reindexObject()
        ensure_indexed(plan)
    except Exception:
        logger.exception(
            "Failed to write the linked sample back to plan '%s'",
            api.get_path(plan))
        result["reason"] = RESULT_ERROR
        return result

    row_uid = get_row_uid(rows[index])
    try:
        result["sample_template_uid"] = api.safe_unicode(
            _first(rows[index].get("sample_template")) or u"")
    except Exception:
        pass
    mirror_task(plan, seq, row_uid, sample_uid_value,
                result["sample_template_uid"])

    result["ok"] = True
    result["reason"] = LINK_OK
    result["sample_uid"] = sample_uid_value
    # 阶段 6b：零点关联的审计快照（A2）—— 与登样同一个理由，
    # 本路径同样不触发修改事件，不补就查不到。
    audit.record_write_back(plan, audit.ACTION_LINK_SAMPLE,
                            actor=generated_by, seqs=[seq],
                            samples=[result["sample_id"]])
    logger.info(
        "maitux.stability: linked sample '%s' (%s, %s) to plan '%s' seq %s "
        "window=[%s .. %s] (by %s)",
        result["sample_id"], result["sample_date"],
        result["sample_date_source"] or u"-", api.get_path(plan), seq,
        result["window_start"], result["window_end"], generated_by)
    return result


def describe_generation(plan, row, now=None):
    """页面预览用：算出这一行"登样会变成什么样"，**不建样、不写库**。

    返回与 ``generate_samples_for_plan`` 同构的 dict（多一个 ``ok``/``reason``），
    这样页面与提交后的结果口径完全一致 —— 页面上说"可以登"，提交后就不会失败
    （除了并发改动与建样本身的异常）。

    配置也是**逐行解析**的（样品模板在行上），所以预览能反映出
    "这一行选的模板有没有检验项 / 客户解析不解析得出来"。
    """
    if now is None:
        now = datetime.now()
    row = row if isinstance(row, dict) else {}
    target = _target_date(getattr(plan, "start_time", None),
                          row.get("timepoint_days", 0))
    # 阶段 6a：方案被暂停 / 终止时，预览也必须说"方案停了"——
    # 判据与真正写库时完全同一处（automation.can_modify_plan），
    # 避免出现"页面上说能登、提交后被拒"。
    blocked = plan_block_reason(plan)
    # 阶段 6b：过期也要在预览里说清楚（同一判据）
    expired = row_expired(plan, row, now)
    # 阶段 6c：作废的行在预览里也要说"这一行已作废"（同一判据）
    voided = row_voided(row)
    ok, reason = generation_check(row, target, blocked_reason=blocked,
                                 expired=expired, voided=voided)
    config = automation.get_generation_config(plan, row)
    problems = list(config.get("problems") or [])
    if ok and problems:
        ok, reason = False, RESULT_ERROR
    sampling_date = resolve_sampling_date(target, now) if ok else None
    return {
        "ok": ok,
        "reason": reason if reason != REASON_OK else RESULT_CREATED,
        "target_date": format_timestamp(target),
        "sampling_date": format_timestamp(sampling_date),
        "sample_template": config.get("sample_template_title") or u"",
        "sample_template_uid": api.get_uid(config.get("sample_template"))
        if config.get("sample_template") is not None else u"",
        "service_count": len(config.get("service_uids") or []),
        "sample_type": config.get("sample_type_title") or u"",
        "client": config.get("client_title") or u"",
        "problems": problems,
        # 问题的参数（给"带名字的报错文案"用，见 automation 的 problem_data）
        "problem_data": dict(config.get("problem_data") or {}),
    }


# ── 阶段 4：到期自动登样（定时入口的**唯一实现**）────────────────────────────
#
# 设计约束（开发计划 §8.3 的硬要求）：
#   1. 判据只允许是"该行 analysis_request 有没有值"（+ generated_at 做审计），
#      **不要**引入"上次跑到哪"之类的游标状态；
#   2. 视图要能安全地被**重复、并发**调用（同一行不会建出两个样品）；
#   3. 每次调用给出可读摘要（扫了几个方案 / 建了几个样品 / 跳了几个），写日志。
#
# 幂等是怎么保证的：
#   * 每一行的判定都走 `generation_check()` —— 已经有样品的行必然被
#     `already_generated` 拦下（`analysis_request` 或 `generated_at` 有值）；
#   * 真正建样只走 `generate_samples_for_plan()`（唯一实现），它自己再判一遍；
#   * 并发：两个请求同时跑到同一行时，ZODB 会在提交阶段抛 ConflictError
#     （同一对象被两个事务改），其中一个回滚 —— 不会留下两个样品。
#     这里**不做进程内锁**：本环境是单进程 Zope，而冲突检测已经由 ZODB 兜住。

# 判定"没到点"之外还会被跳过的原因（摘要里按这些桶计数）
# ★ 桶名与映射表在**纯逻辑**模块 sampleautomation 里（便于脱离 Zope 自检），
#   这里只引用，不重复定义字符串。
SKIP_DISABLED_PLAN = sa.SKIP_DISABLED_PLAN
SKIP_NOT_DUE = sa.SKIP_NOT_DUE
SKIP_NOT_PENDING = sa.SKIP_NOT_PENDING
SKIP_ALREADY_GENERATED = sa.SKIP_ALREADY_GENERATED
SKIP_ZERO_POINT = sa.SKIP_ZERO_POINT
SKIP_COMPLETED = sa.SKIP_COMPLETED
SKIP_NO_TARGET_DATE = sa.SKIP_NO_TARGET_DATE
SKIP_REVOKED = sa.SKIP_REVOKED
SKIP_REASON_BY_CODE = sa.SKIP_REASON_BY_CODE

# 阶段 6a：方案被暂停 / 终止导致的跳过。
# 桶名直接复用 plan_status 的拒绝原因码 —— 同一个事实只有一份字符串，
# 摘要里的桶名与界面上的拒绝原因因此永远对得上。
SKIP_PLAN_PAUSED = plan_status.BLOCK_PLAN_PAUSED
SKIP_PLAN_TERMINATED = plan_status.BLOCK_PLAN_TERMINATED


def _plans_in_container(context, limit=None):
    """容器里（下一层）的稳定性方案对象列表。"""
    from senaite.core.catalog import SETUP_CATALOG
    try:
        path = api.get_path(context)
    except Exception:
        return []
    query = {
        "portal_type": "StabilityPlan",
        "path": {"query": path, "depth": 1},
        "sort_on": "created",
    }
    plans = []
    try:
        brains = api.search(query, catalog=SETUP_CATALOG)
    except Exception:
        logger.exception("Failed to list stability plans for the due scan")
        return []
    for brain in brains:
        try:
            plan = api.get_object(brain)
        except Exception:
            continue
        if plan is None:
            continue
        plans.append(plan)
        if limit is not None and len(plans) >= limit:
            break
    return plans


def generate_due_samples(context, request, now=None, dry_run=False, limit=None,
                         generated_by=None, respect_time=True, plan_uids=None,
                         require_enabled=True):
    """扫一遍到期的时间点行，给它们登样（阶段 4 的**唯一实现**）。

    :param context: 搜索起点（方案容器；定时入口传的是 ``stability_studies/200_stability_plans``）
    :param request: 当前请求（``create_analysisrequest`` 需要）
    :param now: 注入"现在"（自检用）
    :param dry_run: 只报告"会做什么"，不写库
    :param limit: 最多扫几个方案（保命参数）
    :param generated_by: 审计用的操作人（定时任务写 ``scheduler``）
    :param respect_time: 是否遵守"当天的生成时刻"（``auto_create_time``）。
        定时入口是 True；看板上的「生成到期样品」按钮传 False
        （= 只要目标日期到了就生成，不等 08:00）。
    :param plan_uids: 只扫这几个方案（看板按钮按勾选的行限定范围时用）
    :param require_enabled: 是否要求方案开启自动登样。定时入口 True；
        人工按钮也保持 True —— "没开自动登样"的方案要手工建样请用「创建样品」，
        免得"为什么这个方案自己长出了样品"。
    """
    if now is None:
        now = datetime.now()
    if generated_by is None:
        generated_by = current_user_id()

    generation_time = u"%02d:%02d" % automation.get_generation_time()
    if not respect_time:
        # 人工触发：把"当天要等到的时刻"降到 00:00 —— 只保留"目标日期到了没"这道门
        generation_time = u"00:00"
    lead_days = automation.get_lead_days()

    summary = {
        "now": format_timestamp(now),
        "dry_run": bool(dry_run),
        "respect_time": bool(respect_time),
        "generation_time": generation_time,
        "lead_days": lead_days,
        "site_enabled": automation.is_site_enabled(),
        "scanned_plans": 0,
        "enabled_plans": 0,
        "due_rows": 0,
        "created": 0,
        "failed": 0,
        "skipped": {},
        "plans": [],
        "errors": [],
    }

    def bump(bucket):
        summary["skipped"][bucket] = summary["skipped"].get(bucket, 0) + 1

    if plan_uids:
        plans = []
        for uid in plan_uids:
            plan = api.get_object_by_uid(uid, None)
            if plan is not None and api.get_portal_type(plan) == "StabilityPlan":
                plans.append(plan)
    else:
        plans = _plans_in_container(context, limit=limit)

    for plan in plans:
        summary["scanned_plans"] += 1
        plan_uid = api.get_uid(plan)
        plan_id = api.get_id(plan)
        detail = {
            "plan_uid": plan_uid,
            "plan_id": plan_id,
            "title": api.get_title(plan) or u"",
            "enabled": False,
            "due_seqs": [],
            "created": 0,
            "failed": 0,
            "skipped": {},
        }

        def plan_bump(bucket):
            detail["skipped"][bucket] = detail["skipped"].get(bucket, 0) + 1
            bump(bucket)

        # 阶段 6a：先把方案状态摊进摘要 —— 排障时"为什么这个方案没生成"
        # 的第一个要看的字段（站点开着、方案也开着，但状态是 paused 时同样一条都不生成）。
        plan_state = plan_status.get_plan_state(plan)
        detail["plan_state"] = plan_state

        enabled = automation.is_plan_enabled(plan)
        detail["enabled"] = bool(enabled)
        if enabled:
            summary["enabled_plans"] += 1
        elif require_enabled:
            # 整份方案跳过，但要**分清是哪一种跳过**：
            #   * 方案暂停 / 终止 -> plan_paused / plan_terminated
            #   * 其它（站点总开关关了、方案开关没开）-> disabled_plan
            # 合并成一个桶会让"站点急停"和"方案被暂停"看起来一样，
            # 而这俩的处理动作完全不同（前者找管理员、后者找方案负责人）。
            if plan_state == plan_status.STATE_PAUSED:
                plan_bump(SKIP_PLAN_PAUSED)
            elif plan_state == plan_status.STATE_TERMINATED:
                plan_bump(SKIP_PLAN_TERMINATED)
            else:
                plan_bump(SKIP_DISABLED_PLAN)
            summary["plans"].append(detail)
            continue

        rows = list(getattr(plan, "plan_details", None) or [])
        start_time = getattr(plan, "start_time", None)
        due_seqs = []
        for seq, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            target = _target_date(start_time, row.get("timepoint_days", 0))
            # ★ 阶段 6b：**过期的行不补生成** —— 这一句就是
            #   "暂停期间过期的点，恢复之后不会被自动补登"的落点
            #   （不是靠暂停/恢复这两个动作，而是靠这条日期规则）。
            # ★ 阶段 6c：**已作废的行永不生成**（作废是人的决定，
            #   与"撤销过登样的行"同一个道理 —— 见 SKIP_ROW_VOIDED 的说明）。
            ok, reason = generation_check(
                row, target, expired=row_expired(plan, row, now),
                voided=row_voided(row))
            if not ok:
                plan_bump(SKIP_REASON_BY_CODE.get(reason, reason))
                continue
            # ★ 被人撤销过登样的行：自动化不再碰（见 sampleautomation.SKIP_REVOKED 的说明）。
            #   要重新登样请人工用「创建样品」——那条路径不受这里影响。
            if sa.is_revoked(row):
                plan_bump(SKIP_REVOKED)
                continue
            if target is None:
                plan_bump(SKIP_NO_TARGET_DATE)
                continue
            if not is_generation_due(target, now, lead_days=lead_days,
                                     generation_time=generation_time):
                plan_bump(SKIP_NOT_DUE)
                continue
            due_seqs.append(seq)

        detail["due_seqs"] = due_seqs
        summary["due_rows"] += len(due_seqs)
        if due_seqs and not dry_run:
            # ★ 行身份校验（`expected_uids`）只对"**页面渲染 → 提交**"那条路径有意义：
            #   它挡的是"页面打开后别人改了方案，行号已经指向另一行"。
            #   定时/自动路径没有这个时间差 —— 这里刚读到的行就是我们要登的行，
            #   所以按**读到的** detail_uid 原样回填（等价于"已确认"）。
            #   ⚠️ 不传的话默认是 {}，而 `new_detail_row()` 造的行天生带 detail_uid，
            #   于是每一行都会被判成 `row_changed` —— 自动登样会**一声不响地什么都不做**
            #   （2026-09-30 自检抓到过一次）。
            expected = dict(
                (seq, get_row_uid(rows[seq - 1]))
                for seq in due_seqs if seq <= len(rows))
            try:
                results = generate_samples_for_plan(
                    plan, due_seqs, request, generated_by=generated_by, now=now,
                    expected_uids=expected)
            except Exception as exc:
                logger.exception(
                    "Failed to generate due samples for plan '%s'",
                    api.get_path(plan))
                summary["errors"].append((plan_id, api.safe_unicode(str(exc))[:200]))
                detail["failed"] += len(due_seqs)
                summary["failed"] += len(due_seqs)
                summary["plans"].append(detail)
                continue
            for item in results:
                if item.get("ok"):
                    detail["created"] += 1
                else:
                    detail["failed"] += 1
                    plan_bump(item.get("reason") or RESULT_ERROR)
            summary["created"] += detail["created"]
            summary["failed"] += detail["failed"]

        summary["plans"].append(detail)

    logger.info(
        "maitux.stability: due scan by '%s' now=%s dry_run=%s -> "
        "plans=%s enabled=%s due=%s created=%s failed=%s skipped=%s",
        generated_by, summary["now"], summary["dry_run"],
        summary["scanned_plans"], summary["enabled_plans"], summary["due_rows"],
        summary["created"], summary["failed"], summary["skipped"])
    return summary


# ── 阶段 4：「撤销登样」的**唯一实现** ──────────────────────────────────────


def mirror_task_status(plan, seq, row_uid, status):
    """把某一行的状态**强制**同步到对应的时间点任务（撤销时用）。

    与 ``mirror_task`` 的区别：那个只动"待放置"的任务（登样是单向推进），
    而撤销是**管理员显式动作**，要把任务状态一起退回去 —— 否则会出现
    "明细退回了待放置、任务还是进行中"的双口径（看板读任务）。

    按 ``detail_uid`` 配对（没有 id 的历史行按 ``seq`` 兜底）。
    """
    changed = 0
    try:
        children = list(plan.objectValues())
    except Exception:
        children = []
    for child in children:
        try:
            if api.get_portal_type(child) != "StabilityTimepointTask":
                continue
            if not task_matches_row(child, row_uid, seq):
                continue
            if (getattr(child, "detail_status", None) or "") == status:
                continue
            child.detail_status = status
            child.reindexObject()
            ensure_indexed(child)
            changed += 1
        except Exception:
            logger.exception(
                "Failed to mirror revoked status to timepoint task for plan "
                "'%s' seq %s", api.get_path(plan), seq)
    return changed


def _append_revoke_note(notes, reason, revoked_by, now):
    """把撤销这件事追加进行备注（**界面上看得见**的那份审计）。

    格式固定成一行，便于人工核对与文本检索::

        [Sample revoked 2026-09-30 03:12 by admin] 原因原文

    为什么写进 notes：审计要"看得到"，而专用字段要改 schema + 重跑 profile；
    结构化留痕另外写在 ``revoked_at`` / ``revoked_by`` / ``revoke_reason`` 三个
    非 schema 键上（见 sampleautomation 的说明）。
    """
    reason = as_text(reason).strip().replace(u"\n", u" ").replace(u"\r", u" ")
    if len(reason) > 200:
        reason = reason[:200] + u"..."
    line = u"[Sample revoked %s by %s] %s" % (
        format_timestamp(now), revoked_by or u"-", reason)
    old = as_text(notes).strip()
    if not old:
        return line
    return u"%s\n%s" % (old, line)


def revoke_sample_from_row(plan, seq, reason, revoked_by=None, now=None,
                           expected_uid=None):
    """撤销某一行的登样（阶段 4 的**唯一实现**）。

    做什么（开发计划 §8.1）：

    * 清空该行的 ``analysis_request``（**不删样品对象**）；
    * 状态退回 —— 有库存批次的回「已放置」，否则回「待放置」
      （见 :func:`maitux.stability.sampleautomation.status_after_revoke`）；
    * 清 ``generated_at`` / ``generated_by``（登样审计作废）；
    * 写撤销审计：``revoked_at`` / ``revoked_by`` / ``revoke_reason``（结构化）
      + 行备注里追加一行（看得见）+ 日志一条；
    * 把时间点任务的状态一起退回去。

    不做什么：**不删样品对象**（样品作废走它自己的工作流），也不动 ``stock_batch``
    （那是"放置"那一步的事实，与登样无关）。

    允许撤销的前提：这一行**有样品**（否则 ``nothing_to_revoke``）、
    状态**不是「已完成」**（``completed_not_revocable``）、
    原因非空（``reason_required``）、行身份一致（``row_changed``）。
    """
    if now is None:
        now = datetime.now()
    if revoked_by is None:
        revoked_by = current_user_id()

    result = {
        "ok": False,
        "seq": seq,
        "reason": REVOKE_UNKNOWN_ROW,
        "detail_uid": u"",
        "sample_uid": u"",
        "sample_id": u"",
        "sample_url": u"",
        "status_before": u"",
        "status_after": u"",
        "mirrored": 0,
    }

    if plan is None or not isinstance(seq, int) or seq <= 0:
        return result
    rows = list(getattr(plan, "plan_details", None) or [])
    if seq > len(rows) or not isinstance(rows[seq - 1], dict):
        return result

    index = seq - 1
    row = rows[index]
    result["detail_uid"] = get_row_uid(row)

    # 阶段 6a：方案被暂停 / 终止 -> 撤销登样也禁止（第 3 轮第 5 条：
    # "暂停就是冻结所有操作"）。放在行校验之后、行身份校验之前：
    # 方案停了这个事实比"这一行被人改过"更值得先告诉用户。
    blocked = plan_block_reason(plan)
    if blocked:
        result["reason"] = blocked
        return result

    # 阶段 6c：已作废的行不允许撤销登样。
    #   ★ 现实里一条已作废的行**不该**还有样品（作废只对"还没登样"的行开放，
    #     见 timepoints.is_voidable），但历史数据 / 手工改过的数据可能两者并存 ——
    #     那种行让它"保持作废状态"比允许改它更安全。
    if row_voided(row):
        result["reason"] = sa.REVOKE_ROW_VOIDED
        return result

    if expected_uid is not None:
        if get_row_uid(row) != api.safe_unicode(expected_uid).strip():
            result["reason"] = REVOKE_ROW_CHANGED
            return result

    sample_uid = _first(row.get("analysis_request")) or u""
    result["sample_uid"] = api.safe_unicode(sample_uid)
    if not sample_uid:
        result["reason"] = REVOKE_NOTHING_TO_REVOKE
        return result

    status_before = row.get("detail_status") or STATUS_PENDING
    result["status_before"] = status_before
    if normalize_status(status_before) == STATUS_COMPLETED:
        result["reason"] = REVOKE_COMPLETED
        return result

    if reason_is_blank(reason):
        result["reason"] = REVOKE_REASON_REQUIRED
        return result

    sample = api.get_object_by_uid(sample_uid, None)
    if sample is not None:
        result["sample_id"] = api.get_id(sample) or u""
        result["sample_url"] = api.get_url(sample)

    status_after = status_after_revoke(row)
    new_row = dict(row)
    new_row["analysis_request"] = u""
    new_row["detail_status"] = status_after
    new_row[GENERATED_AT_FIELD] = u""
    new_row[GENERATED_BY_FIELD] = u""
    new_row[REVOKED_AT_FIELD] = format_timestamp(now)
    new_row[REVOKED_BY_FIELD] = revoked_by or u""
    new_row[REVOKE_REASON_FIELD] = as_text(reason).strip()
    new_row["notes"] = _append_revoke_note(
        row.get("notes"), reason, revoked_by, now)
    rows[index] = new_row

    try:
        plan.plan_details = rows
        plan.reindexObject()
        ensure_indexed(plan)
    except Exception:
        logger.exception(
            "Failed to write the revoked row back to plan '%s'",
            api.get_path(plan))
        result["reason"] = RESULT_ERROR
        return result

    result["status_after"] = status_after
    result["mirrored"] = mirror_task_status(plan, seq, result["detail_uid"],
                                            status_after)
    result["ok"] = True
    result["reason"] = REVOKE_OK
    # 阶段 6b：撤销登样的审计快照（A2）—— 原因进 comments
    # （与行上的 revoked_reason、行备注里那一行、日志一并构成四处留痕）。
    audit.record_write_back(plan, audit.ACTION_REVOKE_SAMPLE,
                            actor=revoked_by, seqs=[seq],
                            samples=[result["sample_id"]], reason=reason)
    logger.info(
        "maitux.stability: revoked sample '%s' (%s) from plan '%s' seq %s "
        "(%s -> %s, by %s, reason: %s)",
        result["sample_id"] or u"-", result["sample_uid"] or u"-",
        api.get_path(plan), seq, status_before, status_after, revoked_by,
        as_text(reason).strip()[:120])
    return result
