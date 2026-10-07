# -*- coding: utf-8 -*-
"""0 点「关联往期样品」的候选页与关联动作（阶段 3）。

口径（2026-09-29 客户确认）：

* **只有零点行**能关联；其余时间点请用「创建样品」（生成）——
  非零点提交到这里会被服务端拒绝并说明原因；
* 窗口 = ``[T0 - N, T0]``（**含 T0 当天**），``N`` = 站点配置
  ``zero_point_lookback_days``（默认 30）；
* 候选日期：``DateSampled`` 优先，**缺失退回 ``created``**，
  列表里必须标注用的是哪个日期（否则"它为什么在窗口内"看不出来）；
* **默认只看方案客户的样品**，可切换看全部客户（页面顶部一个开关）；
* 服务端校验（前端只能提示）：行存在且是零点、方案有 T0、样品存在、
  日期在窗口内、该样品**没有被任何方案关联过**（强制唯一）、行身份一致。

视图名 ``@@zero_point_candidates``：看板上的「关联已有样品」与登样页上
零点行的「关联已有样品」按钮都指向它（**唯一实现**，不再有第二个页面）。
"""

from bika.lims import api
from bika.lims.api.security import check_permission as has_permission
from DateTime import DateTime
from datetime import datetime
from plone import api as ploneapi
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.core import logger
from senaite.core.catalog import SAMPLE_CATALOG

from maitux.stability import automation
from maitux.stability.browser.rowids import parse_row_id
from maitux.stability.browser.rowids import selected_row_ids
from maitux.stability.i18n import translate_stability
from maitux.stability import plan_status
from maitux.stability import sampleautomation as sa
from maitux.stability import samplegeneration as sg
from maitux.stability.timepoints import get_row_uid
from maitux.stability.timepoints import has_initial_row
from maitux.stability.timepoints import is_initial_row
from maitux.stability.timepoints import normalize_months
from maitux.stability.timepoints import normalize_status
from maitux.stability.title import localized_task_title

# 关联结果的文案（msgid；带占位符的先取原文再 .format）
LINK_MESSAGES = {
    sa.LINK_OK: u"Linked sample {sample} to {plan} / {task}.",
    sa.LINK_UNKNOWN_ROW: u"The selected timepoint no longer exists.",
    sa.LINK_NOT_ZERO_POINT: u"Only the zero point can be linked to an existing sample. Please use Generate for the other timepoints.",
    sa.LINK_UNKNOWN_SAMPLE: u"The selected sample does not exist any more.",
    sa.LINK_OUT_OF_WINDOW: u"The sample date {date} is outside the allowed window ({start} ~ {end}) for this timepoint.",
    sa.LINK_ALREADY_LINKED: u"This sample is already linked to {plan} / {task}.",
    sa.LINK_NO_TARGET_DATE: u"The plan has no Start Time (T0), so there is no window to link samples from.",
    sg.RESULT_ROW_CHANGED: u"The plan details changed since this page was opened. Please select the rows again.",
    sg.RESULT_ERROR: u"Linking the sample failed.",
    # 阶段 6a：方案被暂停 / 终止 -> 关联动作被拒（与登样同一道门）。
    # 这两条文案与 browser/planstatus.STATUS_MESSAGES / browser/edit.py 的
    # _BLOCK_MESSAGES 必须一致：同一个事实不能在三个页面上有三种说法。
    plan_status.BLOCK_PLAN_PAUSED: u"This stability plan is paused. All operations on it are frozen.",
    plan_status.BLOCK_PLAN_TERMINATED: u"This stability plan is terminated.",
    # 阶段 6b：时间点已过期 -> 不能关联往期样品（与登样同一道门，
    # 但码分开取：三套码各有各的文案表，撞值会查错表）。
    sa.LINK_ROW_EXPIRED: u"This timepoint has expired and can no longer be linked to a sample.",
}

# 候选列表/页面的文案
CANDIDATE_LIMIT = 200
STATUS_TITLES = {
    "pending_placement": u"Pending Placement",
    "placed": u"Placed",
    "active": u"In Progress",
    "completed": u"Completed",
}


def us(value):
    return api.safe_unicode(value) if value is not None else u""


def field_value(obj, name):
    """读字段值：属性可能是值、也可能是访问器方法。

    ⚠️ 这个 senaite 版本的 `bika.lims.api` **没有** `get_field_value`
    （写了会 `AttributeError: module has no attribute`），所以统一走这里。
    """
    if obj is None:
        return None
    value = getattr(obj, name, None)
    if callable(value):
        try:
            value = value()
        except Exception:
            return None
    return value


def status_title(status):
    return translate_stability(STATUS_TITLES.get(status, status or u""))


def link_message(result, target=None, task_title=u""):
    """把关联结果拼成一句当前语言的提示（带名字/窗口区间）。"""
    msgid = LINK_MESSAGES.get(result.get("reason"))
    values = {
        "sample": result.get("sample_id") or result.get("sample_uid") or u"",
        "plan": (target or {}).get("plan_title") or u"",
        "task": task_title or u"",
        "date": result.get("sample_date") or u"-",
        "start": result.get("window_start") or u"-",
        "end": result.get("window_end") or u"-",
    }
    if not msgid:
        return us(result.get("reason") or u"")
    text = translate_stability(msgid)
    try:
        return text.format(**values)
    except Exception:
        logger.exception("Failed to format link message %r", msgid)
        return text


class ZeroPointCandidatesView(BrowserView):
    """``@@zero_point_candidates``：选候选样品 → 关联到某个零点行。"""

    template = ViewPageTemplateFile("templates/zero_point_link.pt")

    row_ids = []
    targets = []
    candidates = []
    show_all_clients = False
    selected_target = u""
    filter_client_title = u""
    window_start = u""
    window_end = u""
    notice = u""
    _sampled_index = None

    def __call__(self):
        if not has_permission("Modify portal content", self.context):
            ploneapi.portal.show_message(
                message=translate_stability(
                    u"You do not have permission to link samples."),
                request=self.request, type="error")
            return self.request.response.redirect(self.get_back_url())

        form = getattr(self.request, "form", {}) or {}
        self.row_ids = selected_row_ids(self.request)
        self.show_all_clients = bool(form.get("all_clients"))
        self.targets = self.get_targets()

        requested = us(form.get("target_row_id")).strip()
        if requested:
            self.selected_target = requested
        elif len(self.targets) == 1:
            self.selected_target = self.targets[0]["row_id"]

        if form.get("button_cancel"):
            return self.request.response.redirect(self.get_back_url())

        if form.get("button_link"):
            handled = self.handle_link()
            if handled is not None:
                return handled

        self.notice = self.get_notice()
        self.candidates = self.get_candidates()
        return self.template()

    # ---------------------------------------------------------------- helpers
    def get_notice(self):
        """勾选行后，页面顶部要**额外**说明什么（没有就说空串）。

        ★ 2026-09-30（B 方案）：0 点在代码里**不强制**，方案里可能压根没有 0 点行。
        页面原先在这种情况下只说一句"No plan details selected."，与事实不符
        （用户明明勾了行）—— 这里按三种情形把话说清：

        1. 选中的行里**一个 0 点都没有**，且该方案**根本没有 0 点行** ->
           告诉用户"要先去方案明细里加一行 0 点"（复用方案页提示条的口径）；
        2. 选中的行里**一个 0 点都没有**，但方案里有 0 点 ->
           告诉用户"只有 0 点能关联"（让他去勾 0 点那一行）；
        3. 选中的行**有 0 点**、却没成为目标（方案被改过 / 行被删）->
           复用 unknown_row 文案。

        有目标行时不提示：目标表里已经把每行的原因（红字）写在"可关联窗口"列了。
        """
        if not self.row_ids:
            return u""
        if self._selected_zero_point_rows():
            if self.targets:
                return u""
            return translate_stability(LINK_MESSAGES[sa.LINK_UNKNOWN_ROW])
        if self._plans_without_zero_point():
            return translate_stability(
                u"Zero Point (baseline) is not defined in this plan: add a row with "
                u"Timepoint (Months) = 0 and select it here, otherwise no past sample "
                u"can be linked as the baseline.")
        return translate_stability(
            u"None of the selected timepoints is a zero point: only the zero point "
            u"(Timepoint (Months) = 0) can be linked to an existing past sample.")

    def _plans_without_zero_point(self):
        """选中的行所属方案里，哪些**没有 0 点行**（去重保序）。"""
        titles = []
        seen = set()
        plans = {}
        for row_id in self.row_ids:
            plan_uid, _seq = parse_row_id(row_id)
            if plan_uid is None or plan_uid in seen:
                continue
            seen.add(plan_uid)
            plan = plans.get(plan_uid)
            if plan is None:
                plan = api.get_object_by_uid(plan_uid, None)
                plans[plan_uid] = plan
            if plan is None or api.get_portal_type(plan) != "StabilityPlan":
                continue
            if has_initial_row(getattr(plan, "plan_details", None) or []):
                continue
            title = api.get_title(plan) or api.get_id(plan) or u""
            if title and title not in titles:
                titles.append(title)
        return titles

    def _selected_zero_point_rows(self):
        """选中的行里**确实是 0 点**的行（不看能不能关联）。"""
        found = []
        plans = {}
        for row_id in self.row_ids:
            plan_uid, seq = parse_row_id(row_id)
            if plan_uid is None:
                continue
            plan = plans.get(plan_uid)
            if plan is None:
                plan = api.get_object_by_uid(plan_uid, None)
                plans[plan_uid] = plan
            if plan is None or api.get_portal_type(plan) != "StabilityPlan":
                continue
            details = list(getattr(plan, "plan_details", None) or [])
            if seq > len(details) or not isinstance(details[seq - 1], dict):
                continue
            if is_initial_row(details[seq - 1]):
                found.append(row_id)
        return found
    def get_back_url(self):
        return "{0}/@@task_board".format(api.get_url(self.context))

    def current_target(self):
        for target in self.targets:
            if target["row_id"] == self.selected_target:
                return target
        return None

    def get_targets(self):
        """把选中的行解析成"能不能关联"的目标清单。"""
        targets = []
        plans = {}
        now = datetime.now()
        for row_id in self.row_ids:
            plan_uid, seq = parse_row_id(row_id)
            if plan_uid is None:
                continue
            plan = plans.get(plan_uid)
            if plan is None:
                plan = api.get_object_by_uid(plan_uid, None)
                plans[plan_uid] = plan
            if plan is None or api.get_portal_type(plan) != "StabilityPlan":
                continue
            details = list(getattr(plan, "plan_details", None) or [])
            if seq > len(details) or not isinstance(details[seq - 1], dict):
                continue
            row = details[seq - 1]

            months = normalize_months(row.get("timepoint_days", 0))
            status = normalize_status(row.get("detail_status"))
            client = automation.get_client(plan, row)
            window = sa.zero_point_window(
                getattr(plan, "start_time", None),
                automation.get_zero_point_lookback_days())
            start = sa.format_timestamp(window[0])
            end = sa.format_timestamp(window[1])

            can_link = True
            reason = u""
            # ★ 2026-09-30（用户报的）：**页面也要按同一套门判**。
            #   此前这里只判"是不是零点 / 登过没 / 有没有 T0"，
            #   被暂停/终止的方案照样能列出候选样品、给 Link 按钮 ——
            #   用户填完提交才被服务端一句"方案已终止"弹回来，
            #   观感就是"终止了还能关联"。顺序与服务端
            #   `link_sample_to_row` 完全一致：方案冻结 -> 过期 -> ...
            blocked = sg.plan_block_reason(plan)
            expired = automation.row_is_expired(plan, row, now)
            if blocked:
                can_link, reason = False, translate_stability(
                    LINK_MESSAGES.get(blocked, blocked))
            elif expired:
                can_link, reason = False, translate_stability(
                    LINK_MESSAGES[sa.LINK_ROW_EXPIRED])
            elif not is_initial_row(row):
                can_link, reason = False, translate_stability(
                    LINK_MESSAGES[sa.LINK_NOT_ZERO_POINT])
            elif sa.is_generated(row):
                can_link, reason = False, translate_stability(
                    u"This timepoint already has a sample linked.")
            elif window[1] is None:
                can_link, reason = False, translate_stability(
                    LINK_MESSAGES[sa.LINK_NO_TARGET_DATE])

            targets.append({
                "row_id": row_id,
                "plan": plan,
                "plan_uid": plan_uid,
                "plan_title": api.get_title(plan) or api.get_id(plan) or u"",
                "plan_url": api.get_url(plan),
                "seq": seq,
                "detail_uid": get_row_uid(row),
                "months": months,
                "task_title": localized_task_title(seq, months),
                "status": status,
                "status_title": status_title(status),
                "client_title": (api.get_title(client) or api.get_id(client)
                                 if client is not None else u""),
                "client_uid": api.get_uid(client) if client is not None else u"",
                "window_start": start,
                "window_end": end,
                # ★ 判定用的是**真正的 datetime 窗口**，不是上面两个显示字符串：
                #   把格式化字符串拿去比较会抛 `can't compare datetime to unicode`。
                "window": window,
                "can_link": can_link,
                "reason": reason,
                # 给页面用：这一行是不是因为"方案冻结"才不能关联
                # （页面上要单独出一条红色横幅，而不是只在表格里写红字）
                "frozen": bool(blocked),
                "expired": bool(expired),
            })
        return targets

    def has_frozen_targets(self):
        """选中的目标行里有没有"方案已暂停/终止"的（页面要出一条横幅）。"""
        return any(target.get("frozen") for target in self.targets)

    def frozen_notice(self):
        """冻结横幅的文案（与看板/放置页**同一句 msgid**）。"""
        return translate_stability(
            u"Paused or terminated plans are frozen: their timepoints "
            u"cannot be modified.")

    def get_candidates(self):
        """候选样品清单（默认只看方案客户；窗口 + 日期回退都在这里判定）。"""
        target = self.current_target()
        if target is None or not target.get("can_link"):
            return []
        window = target.get("window") or (None, None)
        return self.query_candidates(target.get("client_uid"), window)

    def sampled_index_name(self):
        """取样日期在样品目录里的索引名。

        ⚠️ 真机实测：样品目录里**没有** ``DateSampled`` 这个索引
        （照字段名写会 `CatalogError: Unknown sort_on index`），
        实际索引名是 ``getDateSampled``。这里按"存在的那个"来选，
        两个都没有就退化为只按创建日期查（功能不致命，只是少了主查询）。
        """
        if getattr(self, "_sampled_index", None) is not None:
            return self._sampled_index
        name = None
        try:
            indexes = api.get_tool(SAMPLE_CATALOG).indexes()
            for candidate in ("getDateSampled", "DateSampled"):
                if candidate in indexes:
                    name = candidate
                    break
        except Exception:
            logger.exception("Failed to read the sample catalog indexes")
        self._sampled_index = name
        return name

    def query_candidates(self, client_uid, window):
        start, end = window
        if not start or not end:
            return []
        # ★ 目录的 DateIndex 范围查询要 **DateTime**（传格式化字符串会让
        #   range 查询匹配不到任何东西 —— 真机踩过：候选永远是 0 个）。
        try:
            range_values = (DateTime(start), DateTime(end))
        except Exception:
            logger.exception("Bad zero point window: %r", window)
            return []
        formatted = (sa.format_timestamp(start), sa.format_timestamp(end))
        base = {"portal_type": "AnalysisRequest"}
        if not self.show_all_clients and client_uid:
            base["getClientUID"] = client_uid

        found = {}
        # ① 取样日期在窗口内的（正常情形）
        index_name = self.sampled_index_name()
        if index_name:
            query = dict(base)
            query["sort_on"] = index_name
            query["sort_order"] = "descending"
            query[index_name] = {"query": range_values, "range": "minmax"}
            for brain in self._search(query):
                found[api.get_uid(brain)] = brain
        # ② 取样日期为空的：退回创建日期判定（列表里会标注用的是 Created）
        query = dict(base)
        query["created"] = {"query": range_values, "range": "minmax"}
        for brain in self._search(query):
            uid = api.get_uid(brain)
            if uid not in found:
                found[uid] = brain

        items = []
        for uid, brain in found.items():
            item = self.describe_candidate(brain, window)
            if item is None:
                continue
            items.append(item)
        items.sort(key=lambda item: item.get("sort_key") or u"", reverse=True)
        for item in items:
            item.pop("sort_key", None)
        return items[:CANDIDATE_LIMIT]

    def _search(self, query):
        """查样品目录：**先走权限过滤的查询，空结果再退回不限制查询**。

        为什么要退回：`bin/instance run` / 后台脚本里的"匿名"安全上下文
        查带权限过滤的目录常常返回 0 条（本仓库其它脚本也踩过），
        而这一页本身已经要求 `Modify portal content`（见 `__call__`），
        候选结果随后还要过窗口 / 客户 / 已关联三道判定 ——
        所以"过滤查询为空时用不限制查询兜底"并没有放宽谁能看到这一页，
        只是让页面在脚本与自动化场景下也能拿到数据。
        """
        try:
            brains = list(api.search(query, catalog=SAMPLE_CATALOG))
            if brains:
                return brains
        except Exception:
            logger.exception("Failed to query zero point candidates: %r", query)
        try:
            catalog = api.get_tool(SAMPLE_CATALOG)
            return list(catalog.unrestrictedSearchResults(**query))
        except Exception:
            logger.exception(
                "Failed to query zero point candidates (unrestricted): %r", query)
            return []

    def describe_candidate(self, brain, window):
        """把一个样品整理成"候选行"；不在窗口内的返回 None。"""
        try:
            sample = api.get_object(brain)
        except Exception:
            return None
        if sample is None:
            return None
        try:
            sampled = field_value(sample, "DateSampled")
        except Exception:
            sampled = None
        try:
            created = api.get_creation_date(sample)
        except Exception:
            created = None
        moment, source = sa.choose_sample_date(sampled, created)
        if not sa.in_zero_point_window(moment, window):
            return None

        uid = api.get_uid(sample)
        conflict = sg.find_link_conflict(uid)
        linked_to = u""
        conflict_plan = conflict[0] if conflict else None
        conflict_seq = conflict[1] if conflict else None
        if conflict_plan is not None:
            months = normalize_months(
                (getattr(conflict_plan, "plan_details", None) or [{}])[
                    max(0, conflict_seq - 1)].get("timepoint_days", 0))
            linked_to = u"%s / %s" % (
                api.get_title(conflict_plan) or api.get_id(conflict_plan) or u"",
                localized_task_title(conflict_seq, months))

        client = None
        try:
            client = field_value(sample, "Client")
        except Exception:
            client = None
        sample_type = None
        try:
            sample_type = field_value(sample, "SampleType")
        except Exception:
            sample_type = None
        state = u""
        try:
            state = api.get_workflow_status_of(sample)
        except Exception:
            state = u""
        moment_text = sa.format_timestamp(moment)
        return {
            "uid": uid,
            "id": api.get_id(sample) or u"",
            "url": api.get_url(sample),
            "client_title": (api.get_title(client) or api.get_id(client)
                             if client is not None else u"-"),
            "sample_type_title": (api.get_title(sample_type)
                                  or api.get_id(sample_type)
                                  if sample_type is not None else u"-"),
            "date": moment_text,
            "date_source": source,
            "date_source_title": (
                u"Sampled Date" if source == sa.DATE_SOURCE_SAMPLED
                else u"Created Date"),
            "state": state,
            "linked_to": linked_to,
            "can_link": not bool(linked_to),
            "sort_key": moment_text,
        }

    # ----------------------------------------------------------------- action
    def handle_link(self):
        """执行关联；成功 -> 回看板（带提示），失败 -> 留在页面上说明原因。"""
        form = getattr(self.request, "form", {}) or {}
        sample_uid = us(form.get("sample_uid")).strip()
        target = self.current_target()

        if target is None:
            ploneapi.portal.show_message(
                message=translate_stability(
                    u"Please select a timepoint and a sample."),
                request=self.request, type="error")
            return None
        if not target.get("can_link"):
            ploneapi.portal.show_message(
                message=target.get("reason") or translate_stability(
                    LINK_MESSAGES[sa.LINK_NOT_ZERO_POINT]),
                request=self.request, type="error")
            return None
        if not api.is_uid(sample_uid):
            ploneapi.portal.show_message(
                message=translate_stability(
                    u"Please select an existing sample first."),
                request=self.request, type="error")
            return None

        result = sg.link_sample_to_row(
            target["plan"], target["seq"], sample_uid,
            request=self.request,
            linked_by=sg.current_user_id(),
            expected_uid=target.get("detail_uid"))

        message = link_message(result, target=target,
                               task_title=target.get("task_title") or u"")
        ploneapi.portal.show_message(
            message=message, request=self.request,
            type="info" if result.get("ok") else "error")

        if result.get("ok"):
            return self.request.response.redirect(self.get_back_url())
        # 失败：留在本页，让用户换一个样品/换一行（候选清单已刷新）
        self.targets = self.get_targets()
        return None
