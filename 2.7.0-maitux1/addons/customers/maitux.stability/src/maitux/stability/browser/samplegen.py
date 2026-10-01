# -*- coding: utf-8 -*-
"""稳定性「登样」批量页 —— ``@@generate_sample``（阶段 2：手工触发的登样）。

这一页做三件事：

1. **摊开配置**：把"这次登样会用到的客户 / 样品模板 / 联系人 / 样品类型 /
   检验项"全部列出来（来自 ``automation.get_generation_config``）——
   配置错在哪儿必须一眼看得见，而不是点完按钮才发现建不出样品；
2. **逐行预演**：对每一行算"目标日期 / 计划取样日期 / 能不能登"，
   与真正提交后的结果口径完全一致（同一份 ``sampleautomation`` 纯逻辑）；
3. **提交并从服务端复核**：提交时把行标识与 ``detail_uid`` 一起带上，
   服务端按 id 校验"要登的还是当初那一行"，然后交给
   ``samplegeneration.generate_samples_for_plan`` 建样。

★ 登样是**写操作**，所以这里不信任页面上的任何结论：
   能不能登、配额、行身份全部在服务端重算（页面只是提示层）。
"""

from bika.lims import api
from bika.lims.api.security import check_permission as has_permission
from plone import api as ploneapi
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.core import logger

try:  # py2 / py3 兼容（urlencode 在 py2 里还有 doseq 语义差异）
    from urllib import urlencode
except ImportError:
    from urllib.parse import urlencode

from maitux.stability import automation
from maitux.stability import plan_status
from maitux.stability.browser.rowids import parse_row_id
from maitux.stability.browser.rowids import selected_row_ids
from maitux.stability.browser.rowids import submitted_detail_uids
from maitux.stability.i18n import translate_stability
from maitux.stability import sampleautomation as sa
from maitux.stability.sampleautomation import PROBLEM_CLIENT_TEMPLATE_MISMATCH
from maitux.stability.sampleautomation import PROBLEM_CONTACT_OTHER_CLIENT
from maitux.stability.sampleautomation import PROBLEM_NO_CLIENT
from maitux.stability.sampleautomation import PROBLEM_NO_CONTACT
from maitux.stability.sampleautomation import PROBLEM_NO_SAMPLE_TEMPLATE
from maitux.stability.sampleautomation import PROBLEM_NO_SAMPLE_TYPE
from maitux.stability.sampleautomation import PROBLEM_NO_SERVICES
from maitux.stability.sampleautomation import REASON_ALREADY_GENERATED
from maitux.stability.sampleautomation import REASON_COMPLETED
from maitux.stability.sampleautomation import REASON_NO_TARGET_DATE
from maitux.stability.sampleautomation import REASON_NOT_PENDING
from maitux.stability.sampleautomation import REASON_ZERO_POINT
from maitux.stability.sampleautomation import normalize_months
from maitux.stability.samplegeneration import RESULT_ERROR
from maitux.stability.samplegeneration import RESULT_ROW_CHANGED
from maitux.stability.samplegeneration import RESULT_UNKNOWN_PLAN
from maitux.stability.samplegeneration import RESULT_UNKNOWN_ROW
from maitux.stability.samplegeneration import describe_generation
from maitux.stability.samplegeneration import generate_samples_for_plan
from maitux.stability.timepoints import get_row_uid
from maitux.stability.timepoints import has_initial_row
from maitux.stability.title import localized_task_title


# 行级原因的文案（英文 msgid，渲染时翻译）。
# 与 sampleautomation / samplegeneration 里的原因码一一对应 ——
# 新增原因码时必须在这里补一条，否则界面会显示原始码。
REASON_MESSAGES = {
    REASON_ZERO_POINT: u"Zero point: link an existing sample instead of creating one.",
    REASON_NOT_PENDING: u"Only timepoints in Pending Placement can be generated.",
    REASON_ALREADY_GENERATED: u"A sample has already been generated for this timepoint.",
    REASON_COMPLETED: u"This timepoint is completed and can no longer be generated.",
    REASON_NO_TARGET_DATE: u"No target date: the plan has no Start Time (T0).",
    RESULT_ROW_CHANGED: u"The plan details changed since this page was opened. Please select the rows again.",
    RESULT_UNKNOWN_ROW: u"The selected timepoint no longer exists.",
    RESULT_ERROR: u"Sample generation failed.",
    RESULT_UNKNOWN_PLAN: u"The selected stability plan could not be found (stale reference).",
    # 阶段 6a：方案被暂停 / 终止 -> 整份方案冻结，一行都不能登。
    # 文案与 browser/planstatus.STATUS_MESSAGES / browser/edit.py 的
    # _BLOCK_MESSAGES 保持一致（同一个事实不许有多种说法）。
    plan_status.BLOCK_PLAN_PAUSED: u"This stability plan is paused. All operations on it are frozen.",
    plan_status.BLOCK_PLAN_TERMINATED: u"This stability plan is terminated.",
    # 阶段 6b：时间点已过期（窗口结束日已过）-> 不能登样。
    # 到期扫描的跳过桶用的是同一个码（SKIP_ROW_EXPIRED == REASON_ROW_EXPIRED），
    # 所以这里一条就够。
    sa.REASON_ROW_EXPIRED: u"This timepoint has expired and can no longer be generated.",
}

# 方案级配置问题的文案
PROBLEM_MESSAGES = {
    # 样品模板**逐个时间点维护在明细行上**，所以"缺模板"是行级问题
    PROBLEM_NO_SAMPLE_TEMPLATE: u"This timepoint has no Sample Template.",
    PROBLEM_NO_CLIENT: u"No Client is configured for this plan.",
    PROBLEM_CLIENT_TEMPLATE_MISMATCH: u"The Client of the plan does not match the client the Sample Template of this timepoint belongs to.",
    PROBLEM_NO_CONTACT: u"The plan has no Contact.",
    PROBLEM_CONTACT_OTHER_CLIENT: u"The Contact belongs to another client than the samples are created for.",
    PROBLEM_NO_SAMPLE_TYPE: u"The Sample Template has no Sample Type.",
    PROBLEM_NO_SERVICES: u"The Sample Template has no analyses.",
}

# 能填进"名字"的问题（比上面那几句通用文案更能定位）：
# 占位符来自 automation.get_generation_config()["problem_data"][code]。
PARAMETERIZED_PROBLEM_MESSAGES = {
    PROBLEM_CONTACT_OTHER_CLIENT: sa.MESSAGE_CONTACT_OTHER_CLIENT,
    PROBLEM_CLIENT_TEMPLATE_MISMATCH: sa.MESSAGE_TEMPLATE_OTHER_CLIENT,
}


def us(value):
    """把任意值安全转成 unicode（py2 下可能是 utf-8 字节串）。"""
    if isinstance(value, unicode):  # noqa: F821
        return value
    if isinstance(value, str):
        return value.decode("utf-8", "replace")
    try:
        return unicode(value)  # noqa: F821
    except Exception:
        return repr(value)


def reason_text(reason):
    """原因码 -> 当前语言的提示文案（认不出就原样返回，便于排查）。"""
    msgid = REASON_MESSAGES.get(reason)
    if not msgid:
        return api.safe_unicode(reason or u"")
    return translate_stability(msgid)


def problem_text(problem, data=None):
    """配置问题码 -> 当前语言的提示文案。

    ``data`` 是该问题的参数（``get_generation_config()["problem_data"][code]``）：
    有参数时用**带名字**的那条文案（"联系人 contact-7 属于 Ŝunnyside，
    而客户是 Klaymore"），没有参数时退回通用文案。
    """
    if data and problem in PARAMETERIZED_PROBLEM_MESSAGES:
        text = translate_stability(PARAMETERIZED_PROBLEM_MESSAGES[problem])
        try:
            return text.format(**data)
        except Exception:
            logger.exception(
                "Failed to format problem message for %r with %r", problem, data)
    msgid = PROBLEM_MESSAGES.get(problem)
    if not msgid:
        return api.safe_unicode(problem or u"")
    return translate_stability(msgid)


def status_title(status):
    """明细状态 -> 文案（复用看板的既有 msgid，不新增重复条目）。"""
    mapping = {
        "pending_placement": u"Pending Placement",
        "placed": u"Placed",
        "active": u"In Progress",
        "completed": u"Completed",
    }
    return translate_stability(mapping.get(status, status))


class GenerateSamplesView(BrowserView):
    template = ViewPageTemplateFile("templates/generate_sample.pt")

    row_ids = []
    rows = []
    plans = []

    def __call__(self):
        if not has_permission("Modify portal content", self.context):
            ploneapi.portal.show_message(
                message=translate_stability(
                    u"You do not have permission to create samples."),
                request=self.request,
                type="error",
            )
            return self.request.response.redirect(self.get_back_url())

        self.row_ids = selected_row_ids(self.request)
        # 行身份是**提交上来的**（不是从库里读的）：库里读出来的 id 永远与库一致，
        # 那样这道校验就等于没做。见 browser/rowids.submitted_detail_uids。
        self.submitted_uids = submitted_detail_uids(self.request)
        self.rows = self.get_rows()
        self.plans = self.get_plan_configs()

        if self.request.form.get("button_cancel"):
            return self.request.response.redirect(self.get_back_url())
        if self.request.form.get("button_generate"):
            return self.handle_generate()

        return self.template()

    def get_back_url(self):
        return "{0}/@@task_board".format(api.get_url(self.context))

    def has_generatable_rows(self):
        """选中的行里有没有"现在就能登"的（没有就把提交按钮禁掉）。"""
        return any(row.get("can_generate") for row in self.rows)

    def _plan(self, plan_uid, cache):
        if plan_uid in cache:
            return cache[plan_uid]
        # ★ 必须给 default=None：`api.get_object_by_uid(uid)` 在 uid 解析不出来时
        #   **抛 APIError**（页面直接 500）。目录陈旧/对象未编目时 uid 就可能取不到，
        #   页面应当照常打开并说明"这一行加载不出来"，而不是整页崩掉。
        plan = api.get_object_by_uid(plan_uid, None)
        if plan is None or api.get_portal_type(plan) != "StabilityPlan":
            plan = None
        cache[plan_uid] = plan
        return plan

    def _config(self, plan_uid, plan, cache):
        """方案级配置（客户/联系人/生成时刻…）。

        ⚠️ 样品模板**不在方案级**（2026-09-29 需求订正：逐个时间点维护在明细行上），
        所以这里传 ``row=None``，得到的 problems 只反映方案级的问题
        （客户/联系人）；每行的模板问题由 ``describe_generation`` 逐行给出。
        """
        if plan_uid in cache:
            return cache[plan_uid]
        config = automation.get_generation_config(plan) if plan is not None else None
        cache[plan_uid] = config
        return config

    def get_rows(self):
        """逐行预演："这一行登样会发生什么"。不写库。"""
        rows = []
        plans = {}
        configs = {}
        for row_id in self.row_ids:
            plan_uid, seq = parse_row_id(row_id)
            if plan_uid is None:
                continue
            plan = self._plan(plan_uid, plans)
            if plan is None:
                # 不静默丢掉：给一行"加载不出来"的占位，让用户知道选了它、
                # 为什么不能登样（而不是少一行、没人说为什么）。
                rows.append({
                    "row_id": row_id,
                    "plan_uid": plan_uid,
                    "plan_url": u"",
                    "plan_title": u"",
                    "seq": seq,
                    "detail_uid": self.submitted_uids.get(row_id, u""),
                    "task_title": u"-",
                    "timepoint_months": u"",
                    "status": u"",
                    "status_title": u"-",
                    "target_date": u"-",
                    "sampling_date": u"-",
                    "sample_template": u"-",
                    "service_count": u"-",
                    "can_generate": False,
                    "reason": RESULT_UNKNOWN_PLAN,
                    "reason_text": reason_text(RESULT_UNKNOWN_PLAN),
                })
                continue

            details = list(getattr(plan, "plan_details", None) or [])
            if seq > len(details):
                continue
            row = details[seq - 1]
            if not isinstance(row, dict):
                continue

            months = normalize_months(row.get("timepoint_days", 0))
            status = row.get("detail_status") or "pending_placement"
            # ★ 逐行预演：样品模板、检验项数量、能不能登，都按**这一行**算
            preview = describe_generation(plan, row)
            reason = preview.get("reason")
            can_generate = bool(preview.get("ok"))
            if reason == RESULT_ERROR and preview.get("problems"):
                # 配置问题的具体原因（缺模板/缺检验项/客户不一致…）逐条列给用户
                problem_data = preview.get("problem_data") or {}
                reason_text_value = u"; ".join(
                    problem_text(code, problem_data.get(code))
                    for code in preview["problems"])
            else:
                reason_text_value = reason_text(reason) if not can_generate else u""

            rows.append({
                "row_id": row_id,
                "plan_uid": plan_uid,
                "plan_url": api.get_url(plan),
                "plan_title": api.get_title(plan) or "",
                "seq": seq,
                "detail_uid": get_row_uid(row),
                "task_title": localized_task_title(seq, months),
                "timepoint_months": months,
                "status": status,
                "status_title": status_title(status),
                "target_date": preview.get("target_date") or "-",
                "sampling_date": preview.get("sampling_date") or "-",
                "sample_template": preview.get("sample_template") or u"-",
                "service_count": preview.get("service_count") or 0,
                "can_generate": can_generate,
                "reason": reason,
                "reason_text": reason_text_value,
                # 零点行：登样动作其实是"关联往期样品"（阶段 3）——
                # 页面上直接给一个跳到候选页的按钮，别让人再回看板绕一圈。
                "is_zero_point": (reason == REASON_ZERO_POINT),
                "zero_point_url": "%s/@@zero_point_candidates?%s" % (
                    api.get_url(self.context),
                    urlencode([("row_ids:list", row_id)])),
            })
        return rows

    def get_plan_configs(self):
        """页面上要展示的方案级配置（去重、保序）。"""
        result = []
        seen = set()
        plans = {}
        configs = {}
        for row_id in self.row_ids:
            plan_uid, _seq = parse_row_id(row_id)
            if plan_uid is None or plan_uid in seen:
                continue
            seen.add(plan_uid)
            plan = self._plan(plan_uid, plans)
            if plan is None:
                continue
            config = self._config(plan_uid, plan, configs) or {}
            problem_data = config.get("problem_data") or {}
            result.append({
                "plan_uid": plan_uid,
                "plan_title": api.get_title(plan) or "",
                "plan_url": api.get_url(plan),
                "client": config.get("client_title") or "",
                "contact": config.get("contact_title") or "",
                "generation_time": u"%02d:%02d" % automation.get_generation_time(),
                "lead_days": automation.get_lead_days(),
                "problems": [problem_text(code, problem_data.get(code))
                             for code in (config.get("problems") or [])],
                "warnings": [problem_text(code, problem_data.get(code))
                             for code in (config.get("warnings") or [])],
                # ★ 本方案有没有 0 点行（B 方案，2026-09-30）：0 点不强制，
                #   但没有 0 点 = 没有基线样品可关联 —— 登样页上给一句提示。
                "lacks_zero_point": not has_initial_row(
                    getattr(plan, "plan_details", None) or []),
            })
        return result

    def handle_generate(self):
        """真正登样：按方案分组，交给 samplegeneration 建样并回写。"""
        plans = {}
        grouped = []
        index = {}
        for row in self.rows:
            plan_uid = row["plan_uid"]
            plan = self._plan(plan_uid, plans)
            if plan is None:
                continue
            if plan_uid not in index:
                index[plan_uid] = len(grouped)
                grouped.append({"plan": plan, "seqs": [], "uids": {}})
            group = grouped[index[plan_uid]]
            group["seqs"].append(row["seq"])
            # 行身份随提交带上：页面渲染到提交之间方案可能被改过
            group["uids"][row["seq"]] = self.submitted_uids.get(row["row_id"], u"")

        if not grouped:
            ploneapi.portal.show_message(
                message=translate_stability(u"No pending tasks selected."),
                request=self.request,
                type="warning",
            )
            return self.request.response.redirect(self.get_back_url())

        created = []
        skipped = []
        for group in grouped:
            results = generate_samples_for_plan(
                group["plan"],
                group["seqs"],
                self.request,
                expected_uids=group["uids"],
            )
            for result in results:
                if result.get("ok"):
                    created.append(result)
                else:
                    skipped.append((group["plan"], result))

        if created:
            ploneapi.portal.show_message(
                message=translate_stability(
                    u"Generated {0} sample(s).").format(len(created)),
                request=self.request,
                type="info",
            )
        if skipped:
            # 逐行给出原因（最多列 5 条，多的折算成数量）——
            # 只报"失败 3 条"而不说为什么，用户没法自己修。
            details = []
            for plan, result in skipped[:5]:
                reason = result.get("reason")
                if reason == RESULT_ERROR and result.get("detail"):
                    # 配置问题的具体原因（缺模板/缺检验项/…）逐个翻译出来
                    reason = u"; ".join(
                        problem_text(code)
                        for code in us(result["detail"]).split(u";") if code)
                else:
                    reason = reason_text(reason)
                details.append(u"{0} / {1}: {2}".format(
                    api.get_title(plan) or api.get_id(plan),
                    localized_task_title(
                        result.get("seq"),
                        normalize_months(_row_months(plan, result.get("seq")))),
                    reason))
            if len(skipped) > 5:
                details.append(u"... +{0}".format(len(skipped) - 5))
            ploneapi.portal.show_message(
                message=translate_stability(
                    u"Skipped {0} timepoint(s): {1}").format(
                        len(skipped), u"; ".join(details)),
                request=self.request,
                type="error",
            )
            # 一行都没成功时留在本页（可以顺手改配置），否则回看板。
            if not created:
                self.rows = self.get_rows()
                self.plans = self.get_plan_configs()
                return self.template()

        return self.request.response.redirect(self.get_back_url())


def _row_months(plan, seq):
    """取某个方案第 seq 行的月份（只为把提示文案里的时间点标题拼对）。"""
    try:
        rows = list(getattr(plan, "plan_details", None) or [])
        row = rows[int(seq) - 1]
        return row.get("timepoint_days", 0)
    except Exception:
        return 0
