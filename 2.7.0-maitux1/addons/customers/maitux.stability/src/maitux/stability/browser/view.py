# -*- coding: utf-8 -*-
import collections
from datetime import datetime
from datetime import timedelta
import re
import six
import time
try:
    from urllib import urlencode
except Exception:
    from urllib.parse import urlencode

from bika.lims import api
from bika.lims.decorators import returns_json
from maitux.stability.i18n import translate_stability
from bika.lims.api.security import check_permission as has_permission
from bika.lims.utils import get_link
from bika.lims.browser.workflow import RequestContextAware
from bika.lims.interfaces import IWorkflowActionUIDsAdapter
from DateTime import DateTime
try:
    from ZPublisher.HTTPRequest import record as RequestRecord
except Exception:
    RequestRecord = None
try:
    from bika.lims.api import to_utf8
except Exception:
    to_utf8 = None
from plone import api as ploneapi
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.app.listing import ListingView
from senaite.core import logger
from senaite.core.browser.dexterity.add import DefaultAddForm as SenaiteDefaultAddForm
from senaite.core.catalog import SETUP_CATALOG
from senaite.core.catalog import SAMPLE_CATALOG
from senaite.core.i18n import translate
from senaite.core.upgrade.utils import temporary_allow_type
from zope.interface import implements

from maitux.stability import automation
from maitux.stability import audit
from maitux.stability import plan_status
from maitux.stability import timepoints as tp
from maitux.stability.browser.rowids import parse_row_id
from maitux.stability.browser.rowids import selected_row_ids
from maitux.stability.indexing import ensure_indexed
from maitux.stability.permissions import AddStabilityPlanTemplate
from maitux.stability.plandetails import new_detail_row
from maitux.stability.plan_copy import can_copy_plan
from maitux.stability.plan_copy import get_plan_by_uid
from maitux.stability.plan_copy import build_copy_data
from maitux.stability.plan_copy import COPY_SOURCE_PARAM
from maitux.stability.sampleautomation import is_generated as row_is_generated
from maitux.stability.sampleautomation import target_date as stability_target_date
from maitux.stability.samplegeneration import current_user_id as current_generator_id
from maitux.stability.samplegeneration import generate_due_samples
from maitux.stability.timepoints import get_row_uid
from maitux.stability.timepoints import has_initial_row
from maitux.stability.timepoints import task_matches_row
from maitux.stability.title import localized_task_title

# ── 懒触发兜底（阶段 4）────────────────────────────────────────────────────
# 没配 cron 时，打开任务看板顺带扫一次到期行 —— 但必须**限流**，
# 否则每次刷新页面都在建样。限流做在**进程内**（模块级时间戳）：
# 这是"多久没跑过"的**运行期节流**，不是"上次跑到哪"的业务游标状态
# （开发计划 §8.3 禁止的是后者）。
LAZY_GENERATE_MIN_INTERVAL = 600      # 秒：同一进程 10 分钟内只懒触发一次
LAZY_GENERATE_PLAN_LIMIT = 50         # 一次最多扫多少方案（保命上限）
_LAZY_GENERATE_LAST = [0.0]           # 进程内时间戳（不落库）

#: 阶段 6b：看板「已过期」筛选的标识。
#:
#: ★ 它**不是** ``detail_status`` 的取值 —— 过期是**计算状态**
#:   （今天 > 窗口结束日 且这一行还没登样，见 automation.row_is_expired）。
#:   因此：筛选要单独分支（不能走"按行状态等值比较"，否则永远筛出空列表）；
#:   词表里也不能加它（那会与"计算状态不落库"的设计冲突）。
EXPIRED_FILTER = "expired"

#: 阶段 6c：看板「已作废」筛选的标识。
#:
#: ★ 与 ``EXPIRED_FILTER`` 同理，它是**行上的标记**（``voided_at`` 非空），
#:   不是 ``detail_status`` 的取值 —— 作废行只在**这一个筛选**下出现，
#:   其余筛选（含 ``all``）一律把它们藏起来（需求："看板默认隐藏、可筛选出来"）。
VOIDED_FILTER = "voided"


def _batch_label(uid):
    """库存批次的**人读标题**（审计快照里存标题而不是 UID）。"""
    try:
        obj = api.get_object_by_uid(uid, None)
    except Exception:
        obj = None
    if obj is None:
        return api.safe_unicode(uid)
    return api.get_title(obj) or api.get_id(obj) or api.safe_unicode(uid)


TABLE_DEFINITIONS = (
    ("storage_conditions", "500_storage_conditions", ("storage_conditions", "z_storage_conditions")),
    ("packaging_specifications", "400_packaging_specifications", ("packaging_specifications", "y_packaging_specifications")),
    ("stability_plan_templates", "300_stability_plan_templates", ("stability_plan_templates", "x_stability_plan_templates")),
    ("stability_plans", "200_stability_plans", ("stability_plans", "w_stability_plans")),
    ("task_board", "100_task_board", ("task_board", "v_task_board")),
)
TABLE_ID_BY_LOGICAL = dict([(item[0], item[1]) for item in TABLE_DEFINITIONS])
TABLE_ID_ALIASES = dict([(item[1], item[2]) for item in TABLE_DEFINITIONS])


def _first(value):
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


def _extract_uid(value):
    value = _first(value)
    if value is None:
        return ""
    if isinstance(value, dict):
        value = value.get("uid") or value.get("UID") or value.get("value") or ""
    if isinstance(value, six.string_types):
        return value.strip()
    return ""


def _normalize_months(value):
    """统一把时间点月份转换为非负整数，兼容下拉控件回传的字符串。"""
    try:
        value = int(value)
    except Exception:
        return 0
    return value if value >= 0 else 0


def _candidate_ids(value):
    canonical = TABLE_ID_BY_LOGICAL.get(value, value)
    related = [canonical]
    related.extend(TABLE_ID_ALIASES.get(canonical, ()))
    candidates = []
    # 兼容升级前后的菜单对象 ID，保证旧路径/旧对象仍可被查找到。
    for related_value in related:
        for v in (
            related_value,
            related_value.replace("_", "-"),
            related_value.replace("-", "_"),
        ):
            if v and v not in candidates:
                candidates.append(v)
    return candidates


def _canonical_id(value):
    return TABLE_ID_BY_LOGICAL.get(value, value)


def _matches_logical_id(value, logical_id):
    return value in _candidate_ids(logical_id)


def _as_url_value(value):
    if value is None:
        return ""
    if to_utf8 is not None:
        try:
            return to_utf8(value)
        except Exception:
            pass
    return value


def _set_prefill_value(request, name, value):
    if value is None:
        return

    try:
        request.form.setdefault("form.widgets.{0}".format(name), value)
    except Exception:
        try:
            request.form["form.widgets.{0}".format(name)] = value
        except Exception:
            pass

    if RequestRecord is None:
        return

    try:
        form_record = request.form.get("form")
        if not isinstance(form_record, RequestRecord):
            form_record = RequestRecord()
            request.form["form"] = form_record

        widgets_record = getattr(form_record, "widgets", None)
        if not isinstance(widgets_record, RequestRecord):
            widgets_record = RequestRecord()
            try:
                form_record["widgets"] = widgets_record
            except Exception:
                try:
                    setattr(form_record, "widgets", widgets_record)
                except Exception:
                    return

        try:
            widgets_record[name] = value
        except Exception:
            try:
                setattr(widgets_record, name, value)
            except Exception:
                pass
    except Exception:
        return


def _is_empty_value(value):
    if value is None:
        return True
    if value in ("", [], (), {}):
        return True
    try:
        # Compatibility with Python 3 (basestring -> str)
        string_types = (str, )
        try:
            if isinstance(value, string_types) and not value.strip():
                return True
        except Exception:
            pass
    except Exception:
        pass
    return False


def _record_for(obj):
    if obj is None:
        return {}
    return {
        "uid": api.get_uid(obj),
        "url": api.get_url(obj),
        "Title": api.get_title(obj) or api.get_id(obj),
        "Description": api.get_description(obj) or "",
    }

def _template_plan_details(template):
    # 模板不再维护 Timepoints 子对象：计划明细由用户在创建计划时直接录入。
    #
    # ★ 2026-09-30（B 方案）：0 点不强制，但"新建的方案默认从一行 0 点开始" ——
    #   所以这里返回**一行 0 点**（而不是空列表）。前端拿到后会用
    #   populatePlanDetails() 把它插进明细表格（用户可见、可删）；
    #   服务端还有 create() 的兜底（见 browser/add.py）。
    return [new_detail_row()]


class StabilityPlanAddFormFromTemplate(SenaiteDefaultAddForm):
    def updateWidgets(self):
        super(StabilityPlanAddFormFromTemplate, self).updateWidgets()
        template_uid = (
            self.request.get("stability_template_uid") or
            self.request.form.get("stability_template_uid")
        )
        if not api.is_uid(template_uid):
            return

        template = api.get_object(template_uid)
        if template is None:
            return

        def set_default(name, value):
            if name not in self.widgets:
                return
            widget = self.widgets.get(name)
            current = getattr(widget, "value", None)
            if _is_empty_value(current):
                widget.value = value

        set_default("plan_template", template_uid)
        set_default("title", api.get_title(template) or "")
        set_default("description", getattr(template, "description", "") or "")

        for name in ("sample_quantity", "reserve_quantity"):
            value = getattr(template, name, None)
            if isinstance(value, int):
                set_default(name, str(value))

        unit = _first(getattr(template, "unit", None))
        if unit:
            set_default("unit", unit)


def _detail_status_title(status):
    """计划明细状态的显示文案（按当前语言翻译）。

    中文注释：状态值（``pending_placement`` / ``placed`` / ``active`` / ``completed``）是
    数据，**不能**直接渲染给用户；显示文案必须走本包翻译，否则中文站会漏英文。
    """
    mapping = {
        "pending_placement": translate_stability(u"Pending Placement"),
        "placed": translate_stability(u"Placed"),
        "active": translate_stability(u"In Progress"),
        "completed": translate_stability(u"Completed"),
    }
    return mapping.get(status, status or u"")


def _task_title(seq, months):
    """时间点任务标题（按当前语言）：``TP 1 (3 Months)`` -> ``TP 1（3 个月）``。

    零点（0 点）走单独文案 ``TP {0} (Initial)`` -> ``TP 1（0 点）``。
    文案与解析规则统一在 maitux.stability.title / timepoints，本处只转调。
    """
    return localized_task_title(seq, months)


class PlanTemplateDefaultsView(BrowserView):
    @returns_json
    def __call__(self):
        uid = self.request.get("uid")
        if not api.is_uid(uid):
            return {}

        template = api.get_object(uid)
        if template is None:
            return {}

        return {
            "plan_template": api.get_uid(template),
            "plan_template_record": _record_for(template),
            "title": api.get_title(template) or "",
            "description": getattr(template, "description", "") or "",
            "sample_quantity": getattr(template, "sample_quantity", 0) or 0,
            "reserve_quantity": getattr(template, "reserve_quantity", 0) or 0,
            "unit": _first(getattr(template, "unit", None)) or "",
            "unit_record": _record_for(api.get_object(_first(getattr(template, "unit", None)))) if _first(getattr(template, "unit", None)) else {},
            "plan_details": _template_plan_details(template),
        }


def _get_or_create_plans_container(request=None):
    portal = api.get_portal()
    module = None
    for cid in _candidate_ids("stability_studies"):
        module = portal.get(cid)
        if module is not None:
            break
    if module is None:
        return None

    types_tool = ploneapi.portal.get_tool("portal_types")
    if getattr(types_tool, "getTypeInfo", None):
        if types_tool.getTypeInfo("StabilityPlans") is None:
            setup = ploneapi.portal.get_tool("portal_setup")
            try:
                setup.runImportStepFromProfile(
                    "profile-maitux.stability:default",
                    "typeinfo",
                )
            except Exception:
                pass

    if getattr(types_tool, "getTypeInfo", None):
        if types_tool.getTypeInfo("StabilityPlans") is None:
            if request is not None:
                try:
                    portal.plone_utils.addPortalMessage(
                        translate_stability(u"StabilityPlans content type is not installed. Please reinstall/upgrade the maitux.stability add-on."),
                        "error",
                    )
                except Exception:
                    pass
            return None

    plans = None
    for cid in _candidate_ids("stability_plans"):
        plans = module.get(cid)
        if plans is not None:
            break

    if plans is None:
        with temporary_allow_type(module, "StabilityPlans"):
            plans = ploneapi.content.create(
                container=module,
                type="StabilityPlans",
                id=_canonical_id("stability_plans"),
                title=u"Stability Plans",
            )
    return plans


def _get_plans_container_in_module(module):
    if module is None:
        return None
    for cid in _candidate_ids("stability_plans"):
        container = module.get(cid)
        if container is not None:
            return container
    return None


class BaseStabilityFolderView(ListingView):
    portal_type = None
    add_type = None
    add_permission = "cmf.AddPortalContent"
    title_text = u""

    def __init__(self, context, request):
        super(BaseStabilityFolderView, self).__init__(context, request)

        self.catalog = SETUP_CATALOG
        self.show_select_column = True

        # ★ 列表标题 viewlet（senaite.core.browser.viewlets.listings）会读
        #   `self.view.icon`：核心的列表视图都设了它；不设就会回落到
        #   `bootstrapview.get_icon_for()`，而那条路径在本模块的容器类型上会抛异常
        #   → 每次打开列表页都往日志写 63 行 Traceback（页面仍 200，所以不易发现）。
        #   这里按核心惯例（controlpanel/*/view.py）显式给一个图标。
        self.icon = api.get_icon(api.get_portal_type(self.context), html_tag=False)

        self.contentFilter = {
            "portal_type": self.portal_type,
            "sort_on": "sortable_title",
            "sort_order": "ascending",
            "path": {
                "query": api.get_path(self.context),
                "depth": 1,
            },
        }

        self.context_actions = {
            translate_stability(u"Add"): {
                "url": "++add++%s" % self.add_type,
                "permission": self.add_permission,
                "icon": "senaite_theme/icon/plus",
            }
        }

        self.title = translate_stability(self.title_text)
        self.columns = collections.OrderedDict((
            ("Title", {
                "title": translate_stability(u"Title"),
                "index": "sortable_title",
            }),
            ("Description", {
                "title": translate_stability(u"Description"),
                "toggle": True,
            }),
            ("state_title", {
                "title": translate_stability(u"State"),
                "index": "review_state",
                "toggle": True,
            }),
        ))

        self.review_states = [
            {
                "id": "default",
                "title": translate_stability(u"Active"),
                "contentFilter": {"is_active": True},
                "transitions": [{"id": "deactivate"}],
                "columns": self.columns.keys(),
            }, {
                "id": "inactive",
                "title": translate_stability(u"Inactive"),
                "contentFilter": {"is_active": False},
                "transitions": [{"id": "activate"}],
                "columns": self.columns.keys(),
            }, {
                "id": "all",
                "title": translate_stability(u"All"),
                "contentFilter": {},
                "columns": self.columns.keys(),
            },
        ]

    def folderitem(self, obj, item, index):
        item = super(BaseStabilityFolderView, self).folderitem(obj, item, index)
        obj = api.get_object(obj)
        item["replace"]["Title"] = get_link(
            href=api.get_url(obj),
            value=api.get_title(obj),
            csrf=False,
        )
        return item


class StorageConditionsView(BaseStabilityFolderView):
    portal_type = "StorageCondition"
    add_type = "StorageCondition"
    title_text = u"Storage Conditions"


class PackagingSpecificationsView(BaseStabilityFolderView):
    portal_type = "PackagingSpecification"
    add_type = "PackagingSpecification"
    title_text = u"Packaging Specifications"


class StabilityPlanTemplatesView(BaseStabilityFolderView):
    portal_type = "StabilityPlanTemplate"
    add_type = "StabilityPlanTemplate"
    add_permission = AddStabilityPlanTemplate
    title_text = u"Stability Plan Templates"

    def __init__(self, context, request):
        super(StabilityPlanTemplatesView, self).__init__(context, request)
        self.init_custom_transitions()

    def init_custom_transitions(self):
        for state in self.review_states:
            custom = state.get("custom_transitions", [])
            if self.custom_transition_create_plan not in custom:
                custom.append(self.custom_transition_create_plan)
            state["custom_transitions"] = custom

    @property
    def custom_transition_create_plan(self):
        return {
            "id": "create_plan",
            "title": translate_stability(u"Create Plan"),
            "url": "workflow_action?action=create_plan",
            "css_class": "btn btn-outline-primary",
            "help": translate_stability(u"Create a stability plan from the selected template"),
        }


class CreatePlanRedirectView(BrowserView):
    def __call__(self):
        template = self.context
        plans = _get_or_create_plans_container(request=self.request)
        if plans is None:
            return self.request.response.redirect(api.get_url(template))

        template_uid = api.get_uid(template)
        url = "{0}/++add++StabilityPlan?template_uid={1}".format(
            api.get_url(plans), _as_url_value(template_uid))
        return self.request.response.redirect(url)


class WorkflowActionCreatePlanAdapter(RequestContextAware):
    implements(IWorkflowActionUIDsAdapter)

    def __call__(self, action, uids):
        if not uids or len(uids) != 1:
            return self.redirect(
                message=translate_stability(u"Please select one template before creating a plan"),
                level="warning",
            )

        template = api.get_object_by_uid(uids[0], None)
        if template is None:
            return self.redirect(
                message=translate_stability(u"The selected template was not found"),
                level="error",
            )

        url = "{0}/@@create_plan".format(api.get_url(template))
        return self.request.response.redirect(url)


class StabilityPlansView(ListingView):
    def __init__(self, context, request):
        super(StabilityPlansView, self).__init__(context, request)

        self.catalog = SETUP_CATALOG
        self.show_select_column = True

        # ★ 与 BaseStabilityFolderView 同一处修复：不设 self.icon 会让
        #   列表标题 viewlet 回落到会抛异常的 get_icon_for()，每次开页写 63 行 Traceback。
        self.icon = api.get_icon(api.get_portal_type(self.context), html_tag=False)

        self.contentFilter = {
            "portal_type": "StabilityPlan",
            "sort_on": "created",
            "sort_order": "descending",
            "path": {
                "query": api.get_path(self.context),
                "depth": 1,
            },
        }

        self.context_actions = {
            translate_stability(u"Task Board"): {
                "url": "@@task_board",
                "permission": "zope2.View",
                "icon": "senaite_theme/icon/file",
            },
        }

        self.title = translate_stability(u"Stability Plans")
        self.columns = collections.OrderedDict((
            ("Title", {
                "title": translate_stability(u"Title"),
                "index": "sortable_title",
            }),
            # 阶段 6a：方案状态（工作流 review_state：进行中 / 已暂停 / 已终止）。
            # index=review_state 让它可按状态排序；值在 folderitem 里换成译文。
            ("review_state", {
                "title": translate_stability(u"Plan Status"),
                "index": "review_state",
            }),
            ("start_time", {
                "title": translate_stability(u"Start Time (T0)"),
                "toggle": True,
            }),
            ("total_quantity", {
                "title": translate_stability(u"Storage Quantity - Total"),
                "toggle": True,
            }),
        ))

        # 状态页签：默认仍是「All」——
        # ★ 与任务看板刻意不同：看板的默认视图是"待办"，已终止方案的待办没有意义
        #   （所以看板默认过滤掉，见 _get_rows）；而**方案列表是管理视图**，
        #   把已终止的方案默认藏起来反而会让人找不到它、也没法复制重做。
        #   需求原话是"看板上可以不显示，或者默认不显示、在条件里面可以显示出来"
        #   —— 管的是看板，不是这里。
        self.review_states = [
            {
                "id": "default",
                "title": translate_stability(u"All"),
                "contentFilter": {},
                "columns": self.columns.keys(),
            },
            {
                "id": "in_progress",
                "title": translate_stability(u"In Progress"),
                "contentFilter": {"review_state": plan_status.STATE_IN_PROGRESS},
                "columns": self.columns.keys(),
            },
            {
                "id": "paused",
                "title": translate_stability(u"Paused"),
                "contentFilter": {"review_state": plan_status.STATE_PAUSED},
                "columns": self.columns.keys(),
            },
            {
                "id": "terminated",
                "title": translate_stability(u"Terminated"),
                "contentFilter": {"review_state": plan_status.STATE_TERMINATED},
                "columns": self.columns.keys(),
            },
        ]

        self.init_custom_transitions()

    def init_custom_transitions(self):
        """给每个状态页签挂上「复制计划」+「暂停 / 恢复 / 终止」按钮。

        **这里刻意不做权限判断**：列表视图是在一个非最终用户的安全上下文里构造的
        （实测 ``check_permission`` / ``portal_membership.checkPermission`` 都返回
        False，用户 id 为 None），按权限决定要不要挂按钮会让功能静默消失。
        权限改由新建表单（``++add++StabilityPlan``）与 ``@@plan_status`` 页
        在点击后统一校验，这与同页「创建计划」按钮的做法保持一致。

        三个状态按钮**总是全挂**（不按选中方案的状态过滤）：senaite 的
        ``custom_transitions`` 是"列表级"的按钮，拿不到每一行的状态；
        状态不匹配时由 ``@@plan_status`` 页说清楚为什么不能改
        （比"按钮时有时无"更容易理解）。方案**页面**上的面板则是按状态过滤的
        （见 browser/viewlets/stabilityplanstatus.py）。
        """
        transition = self.custom_transition_copy_plan
        status_transitions = [
            self.custom_transition_pause_plan,
            self.custom_transition_resume_plan,
            self.custom_transition_terminate_plan,
        ]
        for state in self.review_states:
            custom = state.get("custom_transitions", [])
            if transition not in custom:
                custom.append(transition)
            for item in status_transitions:
                if item not in custom:
                    custom.append(item)
            state["custom_transitions"] = custom

    @property
    def custom_transition_pause_plan(self):
        return {
            "id": "pause_plan",
            "title": translate_stability(u"Pause"),
            "url": "workflow_action?workflow_action_id=pause_plan",
            "css_class": "btn btn-outline-warning",
            "help": translate_stability(u"Pause the selected stability plan"),
        }

    @property
    def custom_transition_resume_plan(self):
        return {
            "id": "resume_plan",
            "title": translate_stability(u"Resume"),
            "url": "workflow_action?workflow_action_id=resume_plan",
            "css_class": "btn btn-outline-primary",
            "help": translate_stability(u"Resume the selected stability plan"),
        }

    @property
    def custom_transition_terminate_plan(self):
        return {
            "id": "terminate_plan",
            "title": translate_stability(u"Terminate"),
            "url": "workflow_action?workflow_action_id=terminate_plan",
            "css_class": "btn btn-outline-danger",
            "help": translate_stability(
                u"Terminate the selected stability plan (final)"),
        }

    @property
    def custom_transition_copy_plan(self):
        return {
            "id": "copy_plan",
            "title": translate_stability(u"Copy Plan"),
            # 服务端只认 workflow_action_id（bika.lims.browser.workflow 的
            # get_action() 读的是 workflow_action_id / workflow_action）；
            # 列表 JS 点击时也会按 id 再带一次，两条路径都能命中。
            "url": "workflow_action?workflow_action_id=copy_plan",
            "css_class": "btn btn-outline-primary",
            "help": translate_stability(
                u"Create a new stability plan by copying the selected plan"),
        }

    def folderitem(self, obj, item, index):
        item = super(StabilityPlansView, self).folderitem(obj, item, index)
        obj = api.get_object(obj)
        item["replace"]["Title"] = get_link(
            href=api.get_url(obj),
            value=api.get_title(obj),
            csrf=False,
        )
        # 阶段 6a：状态列显示**当前语言**的标题。
        # 不直接用目录里的 metadata（那是英文状态名 "in_progress"），
        # 也不自己维护映射表 —— 走 plan_status.state_title（唯一实现）。
        item["review_state"] = translate_stability(
            plan_status.state_title(api.get_review_status(obj)))
        item["start_time"] = getattr(obj, "start_time", "") or ""
        item["total_quantity"] = getattr(obj, "total_quantity", "") or ""
        return item


class PlanCopyDefaultsView(BrowserView):
    """返回被复制方案的预填数据，供新建计划表单前端预填。

    与 ``PlanTemplateDefaultsView`` 同一套路（参数同为 ``uid``）：
    后端只负责给出"干净"的数据（明细状态重置、样品/库存批清空），
    前端负责填进表单控件。
    """

    @returns_json
    def __call__(self):
        plan = get_plan_by_uid(self.request.get("uid"))
        if plan is None:
            return {}
        return build_copy_data(plan)


class WorkflowActionCopyPlanAdapter(RequestContextAware):
    """列表页「复制计划」按钮的适配器：跳到新建表单并带上复制来源。"""

    implements(IWorkflowActionUIDsAdapter)

    def __call__(self, action, uids):
        if not uids or len(uids) != 1:
            return self.redirect(
                message=translate_stability(
                    u"Please select one stability plan to copy"),
                level="warning",
            )

        plan = api.get_object_by_uid(uids[0], None)
        if plan is None or api.get_portal_type(plan) != "StabilityPlan":
            return self.redirect(
                message=translate_stability(
                    u"The selected stability plan was not found"),
                level="error",
            )

        if not can_copy_plan(plan):
            # 方案模板是新建表单的必填且隐藏字段，缺模板时表单存不下去。
            return self.redirect(
                message=translate_stability(
                    u"The selected plan has no plan template and cannot be copied"),
                level="error",
            )

        container = api.get_parent(plan)
        url = "{0}/++add++StabilityPlan?{1}={2}".format(
            api.get_url(container),
            COPY_SOURCE_PARAM,
            _as_url_value(api.get_uid(plan)),
        )
        return self.redirect(
            redirect_url=url,
            message=translate_stability(
                u"The form was pre-filled with the data of the selected plan. "
                u"Please review the values and save."),
            level="info",
        )


class StabilityTaskBoardView(BrowserView):
    template = ViewPageTemplateFile("templates/task_board.pt")
    status_filter = "all"
    plan_query = u""
    sort_on = "target_date"
    sort_order = "asc"
    rows = []
    stats = {}
    has_pending_rows = False
    plans_without_zero_point = []
    plans_without_zero_point_total = 0

    #: 阶段 6a：方案状态过滤的默认值（"active" = 不显示已终止方案的行）。
    #: 声明在类上是为了让 `_get_rows()` 在**批量动作**那条路径里也能安全读到它
    #: （那条路径会在 __call__ 设置实例属性之前就调 _get_rows）。
    PLAN_STATE_FILTER_DEFAULT = "active"
    plan_state_filter = "active"

    def __call__(self):
        # 阶段 6a：方案状态过滤要在**任何** _get_rows() 之前定好 ——
        # 下面的批量动作分支（line_sample 会自己再查一遍 rows）也依赖它。
        self.plan_state_filter = self.get_plan_state_filter()

        # 批量按钮分发：在看板里提交后，统一由后端根据 bulk_action 跳转到对应页面。
        bulk_action = self.request.get("bulk_action")
        if bulk_action:
            value = self.request.get("row_ids", self.request.form.get("row_ids", []))
            if not isinstance(value, (list, tuple)):
                value = [value]

            row_ids = []
            for rid in value:
                if not rid or not isinstance(rid, six.string_types):
                    continue
                if "::" not in rid:
                    continue
                if rid not in row_ids:
                    row_ids.append(rid)

            if not row_ids:
                ploneapi.portal.show_message(
                    message=translate_stability(u"Please select at least one task."),
                    request=self.request,
                    type="warning",
                )
                return self.request.response.redirect(
                    "{0}/@@task_board".format(api.get_url(self.context))
                )

            action_to_view = {
                "sample_placement": "@@sample_placement",
                "link_sample": "@@zero_point_candidates",
                # 「创建样品」= 按**该时间点行的样品模板**（及其检验项）建样。
                # 2026-09-29 需求订正：行上不再有"检验标准 / 分析套餐"，
                # 所以旧的 @@create_sample（按标准/套餐建样）已删除，
                # 这个入口直接走 @@generate_sample（模板驱动的唯一实现）。
                "create_sample": "@@generate_sample",
            }
            # 「生成到期样品」（阶段 4）：与 cron 入口同一份实现，
            # 只把"当天的生成时刻"这道门去掉（点了就生成），范围限定在勾选行所属方案。
            if bulk_action == "generate_due":
                return self.handle_generate_due(row_ids)
            view_name = action_to_view.get(bulk_action)
            if view_name:
                if bulk_action == "link_sample":
                    # 「关联已有样品」只对**零点行**有意义（阶段 3 口径）：
                    # 其余时间点该走「创建样品」，否则会出现"用往期样品顶替应新建的样品"，
                    # 而且窗口是按 T0 算的，非零点行根本没有窗口。
                    all_rows = self._get_rows()
                    by_id = dict((r.get("row_id"), r) for r in all_rows if r.get("row_id"))
                    has_zero_point = any(
                        by_id.get(rid, {}).get("zero_point")
                        for rid in row_ids
                    )
                    if not has_zero_point:
                        ploneapi.portal.show_message(
                            message=translate_stability(u"Only the zero point can be linked to an existing sample. Please use Create Sample for the other timepoints."),
                            request=self.request,
                            type="warning",
                        )
                        return self.request.response.redirect(
                            "{0}/@@task_board".format(api.get_url(self.context))
                        )

                if bulk_action == "sample_placement":
                    # 样品放置只允许对"还没登样"的行执行（待放置 / 已放置）——
                    # 前端有校验，这里做服务端兜底。
                    all_rows = self._get_rows()
                    by_id = dict((r.get("row_id"), r) for r in all_rows if r.get("row_id"))
                    placeable = ("pending_placement", "placed")
                    has_pending = any(
                        by_id.get(rid, {}).get("status") in placeable
                        for rid in row_ids
                    )
                    if not has_pending:
                        ploneapi.portal.show_message(
                            message=translate_stability(u"Sample Placement can only be applied to timepoints that have not been generated yet."),
                            request=self.request,
                            type="warning",
                        )
                        return self.request.response.redirect(
                            "{0}/@@task_board".format(api.get_url(self.context))
                        )

                params = [("row_ids:list", rid) for rid in row_ids]
                url = "{0}/{1}?{2}".format(
                    api.get_url(self.context), view_name, urlencode(params)
                )
                return self.request.response.redirect(url)

        self.status_filter = self.get_status_filter()
        self.plan_query = self.get_plan_query()
        self.sort_on = self.get_sort_on()
        self.sort_order = self.get_sort_order()
        all_rows = self._get_rows()
        all_rows = self._search_rows(all_rows, self.plan_query)
        self.rows = self._filter_rows(all_rows, self.status_filter)
        self.rows = [self._ensure_row_id(row) for row in self.rows]
        self.rows = self._sort_rows(self.rows, self.sort_on, self.sort_order)
        self.stats = self._get_stats(all_rows)
        self.has_pending_rows = any(
            row.get("status") == "pending_placement" for row in self.rows
        )
        # 「哪些方案没有 0 点行」（B 方案提示条，2026-09-30）：
        # 用**筛选前**的行算，免得状态筛选把 0 点行挡掉时误报"没有 0 点"。
        self.plans_without_zero_point = self._plans_without_zero_point(all_rows)
        # 份数单独算：站点上方案标题可能重名（现有 3 份都叫"222"），
        # 按标题去重会让人以为只有 2 份受影响 —— 提示条里要把份数说清。
        self.plans_without_zero_point_total = self._plans_without_zero_point_total(
            all_rows)
        # 懒触发兜底（阶段 4）：打开看板顺带扫一次到期行（限流、失败不影响页面）
        self.lazy_generate_summary = self._maybe_generate_due_lazily()
        return self.template()

    # ------------------------------------------------- 阶段 4：到期自动登样
    def _plans_container(self):
        """方案容器（看板的 ``context`` 可能是"任务看板"子对象，要回到方案文件夹）。"""
        context = self.context
        if _matches_logical_id(api.get_id(context), "task_board"):
            context = _get_plans_container_in_module(api.get_parent(context)) or context
        return context

    def can_generate_due(self):
        """「生成到期样品」按钮要不要显示：有排样权限 **且** 站点总开关是开的。

        站点总开关关着时按钮没有意义（扫一遍只会得到"全部方案未启用"），
        所以直接不显示 —— 要手工给某个方案建样请用「创建样品」。
        """
        if not self.can_place_samples():
            return False
        try:
            return automation.is_site_enabled()
        except Exception:
            return False

    def handle_generate_due(self, row_ids):
        """看板「生成到期样品」：人工触发，**不等当天的生成时刻**。

        与 cron 入口（``@@generate_due_stability_samples``）共用同一份实现
        （``samplegeneration.generate_due_samples``），区别只有两点：

        * ``respect_time=False``：只要目标日期到了就生成，不等配置的 08:00；
        * 只扫**勾选行所属的方案**（勾了行就是明确范围，避免"点一下全站都动"）。

        **仍然要求方案开着自动登样**：没开的方案要手工建样请用「创建样品」，
        否则会出现"我只想给 A 方案建样，B 方案怎么也长出了样品"。
        """
        plan_uids = []
        for row_id in row_ids:
            plan_uid, _seq = parse_row_id(row_id)
            if plan_uid and plan_uid not in plan_uids:
                plan_uids.append(plan_uid)
        try:
            result = generate_due_samples(
                self._plans_container(), self.request, plan_uids=plan_uids,
                respect_time=False, generated_by=current_generator_id())
            skipped = sum((result.get("skipped") or {}).values())
            failures = sum((p.get("failed") or 0)
                           for p in (result.get("plans") or []))
            message = translate_stability(
                u"Due samples: scanned {plans} plan(s), created {created} "
                u"sample(s), skipped {skipped} row(s).").format(
                    plans=result.get("scanned_plans") or 0,
                    created=result.get("created") or 0,
                    skipped=skipped)
            if failures:
                message = u"%s %s" % (message, translate_stability(
                    u"{count} row(s) could not be generated: check the Sample "
                    u"Template and the plan configuration.").format(
                        count=failures))
            ploneapi.portal.show_message(
                message=message, request=self.request,
                type="warning" if failures else "info")
        except Exception:
            logger.exception("Failed to generate due samples from the board")
            ploneapi.portal.show_message(
                message=translate_stability(
                    u"Generating due samples failed. Please check the log."),
                request=self.request, type="error")
        return self.request.response.redirect(
            "{0}/@@task_board".format(api.get_url(self.context)))

    def _maybe_generate_due_lazily(self):
        """打开看板时的懒触发（阶段 4）：没配 cron 时也要能生成。

        三条自我约束：

        1. **只在站点总开关打开时**做（默认关 = 零风险）；
        2. **限流**：同一进程 10 分钟内只跑一次（模块级时间戳，不落库）；
        3. **永不抛异常**：这是"顺带做的事"，不能把看板页面弄崩。
        """
        if not self.can_generate_due():
            return None
        if self.request.form.get("bulk_action"):
            return None                     # 提交动作自己会处理，别叠一次
        now = time.time()
        if now - _LAZY_GENERATE_LAST[0] < LAZY_GENERATE_MIN_INTERVAL:
            return None
        _LAZY_GENERATE_LAST[0] = now
        try:
            result = generate_due_samples(
                self._plans_container(), self.request,
                generated_by=u"lazy-trigger", limit=LAZY_GENERATE_PLAN_LIMIT)
            logger.info(
                "maitux.stability: lazy due scan on the board -> created=%s "
                "due=%s scanned=%s", result.get("created"), result.get("due_rows"),
                result.get("scanned_plans"))
            return result
        except Exception:
            logger.exception("Lazy due scan on the task board failed")
            return None

    def _plans_without_zero_point_total(self, rows):
        """没有 0 点行的方案**份数**（不按标题去重）。"""
        seen = set()
        total = 0
        for row in rows or []:
            plan_uid = row.get("plan_uid")
            if not plan_uid or plan_uid in seen:
                continue
            seen.add(plan_uid)
            plan = api.get_object_by_uid(plan_uid, None)
            if plan is None:
                continue
            if not has_initial_row(getattr(plan, "plan_details", None) or []):
                total += 1
        return total

    def plans_without_zero_point_suffix(self):
        """标题去重后少了份数时，补一句"共 N 份方案"（可翻译；没有重复标题就返回空串）。"""
        total = self.plans_without_zero_point_total
        if not total or total <= len(self.plans_without_zero_point):
            return u""
        return translate_stability(
            u"({0} plans in total)").format(total)

    def _plans_without_zero_point(self, rows):
        """当前列表里**没有 0 点行**的方案标题（保序、去重）。

        ★ 判据取的是**方案对象上的明细**，不是传进来的行 ——
        行已经被状态筛选/搜索筛过，0 点行很可能不在其中；
        拿筛过的行去判断会把"有 0 点"误报成"没有 0 点"。
        """
        titles = []
        seen = set()
        for row in rows or []:
            plan_uid = row.get("plan_uid")
            if not plan_uid or plan_uid in seen:
                continue
            seen.add(plan_uid)
            plan = api.get_object_by_uid(plan_uid, None)
            if plan is None:
                continue
            if has_initial_row(getattr(plan, "plan_details", None) or []):
                continue
            title = row.get("plan_title") or api.get_title(plan) or u""
            if title and title not in titles:
                titles.append(title)
        return titles

    def has_frozen_rows(self):
        """当前列表里有没有"属于已暂停/已终止方案"的行（有就在看板上提示一句）。

        ★ 为什么要提示：冻结方案的行**勾都勾不上**（模板里 `disabled`），
          不解释一句的话用户会以为看板坏了。需求口径是"暂停就是冻结所有操作"
          （第 3 轮第 5 条），所以这里说的和行上的状态徽标是同一件事。
        """
        return any(row.get("plan_frozen") for row in self.rows)

    def frozen_note(self):
        """冻结行的悬停提示（与看板顶部那条提示**同一句 msgid**，不另起文案）。"""
        return translate_stability(
            u"Paused or terminated plans are frozen: their timepoints "
            u"cannot be modified.")

    def voided_title(self, row):
        """「已作废」徽标的悬停提示：谁、什么时候、为什么。

        ★ 只做展示，不参与任何判定（判定在 ``automation.row_is_voided``）。
        """
        parts = []
        when = api.safe_unicode((row or {}).get("voided_at") or u"").strip()
        who = api.safe_unicode((row or {}).get("voided_by") or u"").strip()
        why = api.safe_unicode((row or {}).get("void_reason") or u"").strip()
        if when:
            parts.append(u"%s: %s" % (translate_stability(u"Discarded"), when))
        if who:
            parts.append(u"%s: %s" % (translate_stability(u"Actor"), who))
        if why:
            parts.append(u"%s: %s" % (translate_stability(u"Reason"), why))
        return u" | ".join(parts)

    def can_place_samples(self):
        # 兼容不同环境的权限命名，避免按钮被误隐藏
        if has_permission("Modify portal content", self.context):
            return True
        if has_permission("cmf.ModifyPortalContent", self.context):
            return True
        try:
            user = ploneapi.user.get_current()
            roles = set(user.getRolesInContext(self.context))
            if roles.intersection(set(["Manager", "LabManager", "LabClerk"])):
                return True
        except Exception:
            pass
        return False

    def can_generate_samples(self):
        """「创建样品」按钮要不要显示。

        条件：有排样权限 **且** 当前列表里至少有一个**时间点行**选了样品模板 ——
        样品模板是逐个时间点维护的（不同时间点验的东西不一样），
        一行都没配的话点进去只会看到"缺样品模板"，不如不显示按钮。
        配置入口就是方案明细行上的「样品模板」列（见 content/stabilityplan.py）。
        """
        if not self.can_place_samples():
            return False
        return any(row.get("has_sample_template") for row in self.rows)

    def get_status_filter(self):
        value = self.request.get("status_filter", "all")
        if value not in ("all", EXPIRED_FILTER, VOIDED_FILTER,
                         "pending_placement", "placed", "active", "completed"):
            return "all"
        return value

    # ------------------------------------------------- 阶段 6a：方案状态过滤
    def get_plan_state_filter(self):
        """看板的**方案状态**过滤（与行状态 status_filter 是两个维度）。

        * ``active``（默认）—— 进行中 + 已暂停，**不含已终止**；
        * ``all``            —— 全部；
        * ``terminated``     —— 只看已终止方案的行。

        ★ 为什么默认过滤掉已终止：需求原话是"看板上可以不显示，或者默认不显示，
          在条件里面可以显示出来"（第 2 轮第 6 条）。看板是**待办视图**，
          已终止方案的待办永远不会被执行，留在列表里只会让真实的待办被淹掉。
        ★ 为什么**暂停的方案仍然显示**：它的时间点还被人看（"哪些点被暂停耽误了"），
          解冻后还要接着做 —— 藏起来反而会让人以为方案没了。
        """
        value = self.request.get("plan_state_filter",
                                 self.PLAN_STATE_FILTER_DEFAULT)
        if not isinstance(value, six.string_types):
            return self.PLAN_STATE_FILTER_DEFAULT
        value = value.strip()
        if value not in ("active", "all", "terminated"):
            return self.PLAN_STATE_FILTER_DEFAULT
        return value

    def _plan_state_matches(self, state):
        """当前过滤下，这个状态的方案要不要显示。"""
        if self.plan_state_filter == "all":
            return True
        if self.plan_state_filter == "terminated":
            return state == plan_status.STATE_TERMINATED
        return state != plan_status.STATE_TERMINATED

    def get_plan_state_filter_options(self):
        return [
            ("active", translate_stability(u"Active Plans")),
            ("all", translate_stability(u"All Plans")),
            ("terminated", translate_stability(u"Terminated Plans")),
        ]

    def get_plan_state_filter_buttons(self):
        """顶部「方案状态」筛选按钮（与行状态按钮同一套样式/跳转逻辑）。"""
        buttons = []
        for key, title in self.get_plan_state_filter_options():
            url = self.build_task_board_url({
                "plan_state_filter": key,
            })
            buttons.append({
                "id": "plan-state-%s" % key,
                "title": title,
                "url": url,
                "active": key == self.plan_state_filter,
            })
        return buttons

    def get_plan_query(self):
        value = self.request.get("plan_query", "")
        if not isinstance(value, six.string_types):
            return u""
        return api.safe_unicode(value).strip()

    def get_sort_on(self):
        value = self.request.get("sort_on", "target_date")
        if value not in ("target_date", "window_start", "window_end"):
            return "target_date"
        return value

    def get_sort_order(self):
        value = self.request.get("sort_order", "asc")
        if value not in ("asc", "desc"):
            return "asc"
        return value

    def _get_base_query(self, extra=None):
        # 统一拼装看板查询参数，保证筛选、搜索、排序之间可以叠加。
        query = {}
        if self.status_filter and self.status_filter != "all":
            query["status_filter"] = self.status_filter
        # 阶段 6a：方案状态过滤只在**非默认值**时才写进 URL ——
        # 默认值也写进去会让每个链接都变长，而且看不出"这其实是默认"。
        if self.plan_state_filter and \
                self.plan_state_filter != self.PLAN_STATE_FILTER_DEFAULT:
            query["plan_state_filter"] = self.plan_state_filter
        if self.plan_query:
            query["plan_query"] = self.plan_query
        if self.sort_on:
            query["sort_on"] = self.sort_on
        if self.sort_order:
            query["sort_order"] = self.sort_order
        if extra:
            for key, value in extra.items():
                # ★ 阶段 6a：`plan_state_filter` 必须**逐字段特判**。
                #
                # 下面那条"all / 空值 = 默认、就把它从 URL 里去 de"的约定
                # 只对 `status_filter` 成立（它的默认值就是 "all"）。
                # 而 `plan_state_filter` 的默认值是 "active" —— `"all"` 对它
                # 是一个**有意义的值**（我要看全部方案，包括已终止的）。
                # 一起 pop 掉的话「All Plans」按钮会**静默失效**：
                # 点下去 URL 里没有这个参数，于是又回到默认的 active
                # （真机 HTTP 检查抓到的：'plan_state_filter=all' 在页面上找不到）。
                if key == "plan_state_filter":
                    query[key] = value
                    continue
                if value in (None, "", "all"):
                    query.pop(key, None)
                    continue
                query[key] = value
        return query

    def build_task_board_url(self, extra=None):
        base_url = "{0}/@@task_board".format(api.get_url(self.context))
        query = self._get_base_query(extra=extra)
        if not query:
            return base_url
        return "{0}?{1}".format(base_url, urlencode(query))

    def get_status_filter_options(self):
        # 中文注释：键与状态值一一对应，文案一律走本包翻译（英文站=英文 msgid）。
        # ★ 阶段 6b：`expired` 是一个**虚拟状态** —— 它不是 detail_status 的取值，
        #   而是"今天 > 窗口结束日 且这一行还没登样"算出来的（见 _filter_rows）。
        # ★ 阶段 6c：`voided` 同理（行上的 voided_at 标记），
        #   而且它是唯一能看到作废行的入口（其余筛选都把它们藏起来）。
        return [
            ("all", translate_stability(u"All")),
            ("pending_placement", translate_stability(u"Pending Placement")),
            ("placed", translate_stability(u"Placed")),
            ("active", translate_stability(u"In Progress")),
            ("completed", translate_stability(u"Completed")),
            (EXPIRED_FILTER, translate_stability(u"Expired")),
            (VOIDED_FILTER, translate_stability(u"Discarded")),
        ]

    def get_status_filter_buttons(self):
        # 生成顶部状态按钮数据，样式对齐 Listing 的状态筛选按钮。
        buttons = []
        for key, title in self.get_status_filter_options():
            status_value = None if key == "all" else key
            url = self.build_task_board_url({
                "status_filter": status_value,
            })
            buttons.append({
                "id": key,
                "title": title,
                "url": url,
                "active": key == self.status_filter,
            })
        return buttons

    def get_js_messages(self):
        """看板前端 JS 里要弹的提示文案（同样必须按语言翻译）。

        中文注释：模板里用 ``data-msg-*`` 传给 JS，避免把译文直接拼进
        ``alert('...')`` —— 译文里可能带引号，拼接会破坏脚本。
        """
        return {
            "select_one": translate_stability(u"Please select at least one task."),
            "pending_only": translate_stability(
                u"Sample Placement can only be applied to timepoints that have not been generated yet."),
            "zero_point_only": translate_stability(
                u"Only the zero point can be linked to an existing sample. Please use Create Sample for the other timepoints."),
        }

    def _filter_rows(self, rows, status_filter):
        # ★ 阶段 6c：**作废行默认隐藏** —— 只有"已作废"这一个筛选能看到它们
        #   （需求 Q2："看板默认隐藏、可筛选出来"）。
        #   注意这一步必须排在 `all` 之前：`all` 是"全部**有效**行"，
        #   不是"连作废的也算"。
        if status_filter == VOIDED_FILTER:
            return [row for row in rows if row.get("is_voided")]
        rows = [row for row in rows if not row.get("is_voided")]
        if status_filter == "all":
            return rows
        if status_filter == EXPIRED_FILTER:
            # 阶段 6b：「已过期」是**计算状态**（今天 > 窗口结束日 且还没登样），
            # 不是 detail_status 的取值 —— 所以它不能走下面那条
            # "按行状态等值比较"的分支（走了会永远筛出空列表）。
            return [row for row in rows if row.get("is_expired")]
        return [row for row in rows if row.get("status") == status_filter]

    def _search_rows(self, rows, plan_query):
        if not plan_query:
            return rows
        query = api.safe_unicode(plan_query).lower()
        result = []
        for row in rows:
            title = api.safe_unicode(row.get("plan_title", "")).lower()
            if query in title:
                result.append(row)
        return result

    def _sort_rows(self, rows, sort_on, sort_order):
        key_name = {
            "target_date": "target_dt",
            "window_start": "window_start_dt",
            "window_end": "window_end_dt",
        }.get(sort_on, "target_dt")
        reverse = sort_order == "desc"
        return sorted(
            rows,
            key=lambda r: (r.get(key_name) is None, r.get(key_name)),
            reverse=reverse,
        )

    def get_sort_url(self, sort_on):
        sort_order = "asc"
        if self.sort_on == sort_on and self.sort_order == "asc":
            sort_order = "desc"
        return self.build_task_board_url({
            "sort_on": sort_on,
            "sort_order": sort_order,
        })

    def get_sort_indicator(self, sort_on):
        if self.sort_on != sort_on:
            return u""
        return self.sort_order == "asc" and u" ^" or u" v"

    def sort_header(self, sort_on, label):
        """表头文案（带排序箭头）。

        中文注释：这几个表头是 ``tal:content`` 用 Python 表达式渲染的，
        ``i18n:translate`` 对它不生效，所以必须在这里显式翻译，
        否则中文站会显示英文表头。
        """
        return u"{}{}".format(translate_stability(label),
                             self.get_sort_indicator(sort_on))

    def _build_row_id(self, plan_uid, seq):
        """统一生成任务看板行标识。"""
        if not api.is_uid(plan_uid):
            return u""
        try:
            seq = int(seq)
        except Exception:
            return u""
        if seq <= 0:
            return u""
        return u"{0}::{1}".format(plan_uid, seq)

    def _guess_sequence_from_row(self, row):
        """在缺失 row_id 时，从现有行数据尽量恢复 seq。"""
        if not isinstance(row, dict):
            return None
        for key in ("seq", "sequence"):
            value = row.get(key)
            try:
                value = int(value)
            except Exception:
                value = None
            if value and value > 0:
                return value

        title = api.safe_unicode(row.get("task_title", u"") or u"")
        match = re.match(r"^\s*TP\s+(\d+)\b", title)
        if match:
            try:
                return int(match.group(1))
            except Exception:
                return None
        return None

    def _ensure_row_id(self, row):
        """兼容旧数据路径，保证模板渲染时始终可安全读取 row_id。"""
        if not isinstance(row, dict):
            return row
        if row.get("row_id"):
            return row

        row = dict(row)
        plan_uid = row.get("plan_uid")
        seq = self._guess_sequence_from_row(row)
        row["row_id"] = self._build_row_id(plan_uid, seq)
        return row

    def _to_datetime(self, value):
        if value is None:
            return None
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, DateTime):
            dt = value.asdatetime()
        elif getattr(value, "asdatetime", None):
            try:
                dt = value.asdatetime()
            except Exception:
                return None
        else:
            return None
        if getattr(dt, "tzinfo", None) is not None:
            try:
                dt = dt.replace(tzinfo=None)
            except Exception:
                pass
        return dt

    def _format_datetime(self, value):
        dt = self._to_datetime(value)
        if dt is not None:
            return dt.strftime("%Y-%m-%d %H:%M")
        return value and api.safe_unicode(value) or ""

    def _status_title(self, status):
        # 中文注释：状态文案必须翻译，否则中文站的任务看板会显示英文。
        return _detail_status_title(status)

    def _get_rows(self):
        context = self._plans_container()
        # 看板默认展示计划(Plan)里的 Plan Details 数据，不依赖已生成的 Task 对象。
        plans_query = {
            "portal_type": "StabilityPlan",
            "path": {
                "query": api.get_path(context),
                "depth": 1,
            },
        }
        brains = api.search(plans_query, catalog=SETUP_CATALOG)
        now = datetime.now()

        rows = []
        samples_cache = {}
        for brain in brains:
            plan = api.get_object(brain)
            if plan is None:
                continue

            plan_uid = api.get_uid(plan)
            plan_url = api.get_url(plan)
            plan_title = api.get_title(plan)

            # 阶段 6a：方案状态。
            # * 已终止的方案**默认**不显示（需求第 2 轮第 6 条："看板上可以不显示，
            #   或者默认不显示，在条件里面可以显示出来"），
            #   用顶部的「方案状态」按钮切成 Terminated/All 就能翻出来。
            # * 已**暂停**的方案**仍然显示** —— 它的时间点还被人看
            #   （"哪些点被暂停耽误了"），解冻后还要接着做；藏起来会让人
            #   以为方案没了。行上会打「方案已暂停」的标记，说明为什么不能操作。
            plan_state = plan_status.get_plan_state(plan)
            if not self._plan_state_matches(plan_state):
                continue
            plan_frozen = plan_status.is_frozen(plan_state)

            start_time = getattr(plan, "start_time", None)
            details = getattr(plan, "plan_details", None) or []

            for seq, row in enumerate(details, start=1):
                if not isinstance(row, dict):
                    continue

                months = _normalize_months(row.get("timepoint_days", 0))
                # 样品模板**逐个时间点维护在明细行上**（2026-09-29 需求订正），
                # 所以按行判断有没有配 —— 决定看板上要不要出现「创建样品」按钮。
                has_sample_template = bool(
                    automation.get_row_sample_template(row))

                window_days = row.get("window_days", 0)
                if not isinstance(window_days, int) or window_days < 0:
                    window_days = 0

                status = row.get("detail_status") or "pending_placement"
                # 关联样品 UID，来自 Plan Details 行的 analysis_request 字段。
                sample_uid = _first(row.get("analysis_request")) or ""
                sample_id = ""
                sample_url = ""
                if api.is_uid(sample_uid):
                    sample = samples_cache.get(sample_uid)
                    if sample is None:
                        sample = api.get_object_by_uid(sample_uid, None)
                        samples_cache[sample_uid] = sample
                    if sample is not None:
                        sample_id = api.get_id(sample) or ""
                        sample_url = api.get_url(sample)

                stock_batch_uid = _first(row.get("stock_batch")) or ""
                stock_batch_title = ""
                if api.is_uid(stock_batch_uid):
                    stock_batch = samples_cache.get(stock_batch_uid)
                    if stock_batch is None:
                        stock_batch = api.get_object_by_uid(stock_batch_uid, None)
                        samples_cache[stock_batch_uid] = stock_batch
                    if stock_batch is not None:
                        stock_batch_title = api.get_title(stock_batch) or api.get_id(stock_batch) or ""

                target_date = None
                window_start = None
                window_end = None
                if start_time:
                    # 时间点按月计算（1 月 = 30 天），窗口期按天计算。
                    # 折算口径的唯一实现在 sampleautomation.target_date ——
                    # 看板、任务同步、登样三处必须是同一个日期，否则会出现
                    # "看板说到点了、登样说没到点"。
                    target_date = stability_target_date(start_time, months)
                    # 阶段 6b：窗口结束日改用唯一实现 automation.window_end，
                    # 不再在这里自己 ± timedelta（那是"看板说过期、登样说能登"
                    # 的温床）。
                    window_end = automation.window_end(
                        start_time, months, window_days)
                    if window_days:
                        window_start = target_date - timedelta(days=window_days)
                    else:
                        window_start = target_date
                target_dt = self._to_datetime(target_date)
                window_start_dt = self._to_datetime(window_start)
                window_end_dt = self._to_datetime(window_end)
                # 阶段 6b：**过期**（需求口径：今天 > 窗口结束日，且还没登样）。
                # 判据走唯一实现 automation.row_is_expired ——
                # 看板这里只是显示，但口径必须与登样/关联/编辑页完全一致。
                #
                # 与旧口径的差别（行为变化，已知并确认）：
                #   旧：`目标日期 < 现在`（含已登样/已完成的行）
                #   新：`今天 > 窗口结束日` **且** 该行还没登样
                # 所以"已经登过样但过期了"的行不再算过期 —— 那种点的工作
                # 早就做完了，标成过期只会让看板出现一批"过期但其实做完了"的行。
                is_expired = automation.row_is_expired(plan, row, now)
                # 阶段 6c：**已作废**（软删除）—— 看板默认隐藏（见 _filter_rows），
                # 筛出来时也只读：不给任何操作入口。
                is_voided = automation.row_is_voided(row)

                row_id = "{0}::{1}".format(plan_uid, seq)
                row_uid = get_row_uid(row)
                # ★ 2026-09-30（用户报的）：**界面层也必须冻结**。
                #   服务端（登样/关联/撤销/放置四条写库路径）早就拒了，
                #   但看板此前照样把按钮/链接摆出来、行也照样能勾 ——
                #   用户点进去、填完、提交，才被一句"方案已终止"弹回来，
                #   观感就是"终止了还能操作"（实测：终止方案的
                #   @@zero_point_candidates 页面正常列出候选样品并给 Link 按钮）。
                #   现在三件事一起做：行不能勾、行级动作链接不出现、
                #   相关行的标记位在看板行字典里就置 False。
                # ★ 阶段 6c：已作废的行与冻结方案**同一待遇**（can_* 全 False）——
                #   它已经退出流程了，任何操作都不该再摆出来。
                can_revoke = (bool(sample_uid) and status != "completed"
                              and not plan_frozen and not is_voided)
                revoke_url = "%s/@@revoke_sample?%s" % (
                    api.get_url(context),
                    urlencode([("row_ids:list", row_id),
                               ("row_uids:list", row_uid)]))
                # 「可删/可废弃」这一行吗（阶段 6c 的判据，**只取行 + 方案状态**
                #   这一层，不看样品）：阶段 6d 撤掉了看板上的作废入口，
                #   这个键保留下来当**判据的导出**（自检与将来可能的入口用），
                #   模板已经不再据此渲染链接。
                can_void = (not plan_frozen and not is_voided
                            and tp.is_deletable(row))
                # 「样品放置」：还没登样的行（待放置 / 已放置）且方案没被冻结
                can_place = (status in ("pending_placement", "placed")
                             and not plan_frozen and not is_voided)
                # 「0 点关联往期样品」：零点行、没登过样、没被冻结、**也没过期**
                #   （与 samplegeneration.link_sample_to_row 的四道门一一对应）
                can_link = (months == 0 and not plan_frozen and not is_expired
                            and not row_is_generated(row))

                rows.append({
                    "row_id": row_id,
                    "plan_uid": plan_uid,
                    "plan_url": plan_url,
                    "plan_title": plan_title,
                    # 阶段 6a：方案状态（看板上要标出"这个方案暂停了"，
                    # 否则用户会奇怪为什么这一行的按钮点不动）
                    "plan_state": plan_state,
                    "plan_state_title": translate_stability(
                        plan_status.state_title(plan_state)),
                    "plan_frozen": plan_frozen,
                    "task_title": _task_title(seq, months),
                    "sample_uid": sample_uid,
                    "sample_id": sample_id,
                    "sample_url": sample_url,
                    "stock_batch_uid": stock_batch_uid,
                    "stock_batch_title": stock_batch_title,
                    "timepoint_months": months,
                    "window_days": window_days,
                    "target_date": self._format_datetime(target_date),
                    "target_dt": target_dt,
                    "window_start": self._format_datetime(window_start),
                    "window_start_dt": window_start_dt,
                    "window_end": self._format_datetime(window_end),
                    "window_end_dt": window_end_dt,
                    "status": status,
                    "status_title": self._status_title(status),
                    "is_expired": is_expired,
                    # 阶段 6c：作废（软删除）—— 标记 + 三件套（页面要显示
                    # "谁、什么时候、为什么作废的"）
                    "is_voided": is_voided,
                    "voided_at": api.safe_unicode(row.get("voided_at") or u""),
                    "voided_by": api.safe_unicode(row.get("voided_by") or u""),
                    "void_reason": api.safe_unicode(row.get("void_reason") or u""),
                    "has_sample_template": has_sample_template,
                    # 零点行（0 点）：它的登样动作是"关联往期样品"，不是建样
                    "zero_point": (months == 0),
                    # 撤销登样的入口（阶段 4 + 6a 冻结）
                    "can_revoke": can_revoke,
                    "revoke_url": revoke_url if can_revoke else "",
                    # 可废弃判据的导出（阶段 6d：看板入口已撤，不再是链接）
                    "can_void": can_void,
                    # 「界面层冻结」的三块拼图（模板与自动检查都用它）：
                    # 行能不能勾（冻结方案的行、作废的行**勾都勾不上**）、
                    # 能不能放置、能不能关联
                    "can_select": (not plan_frozen) and (not is_voided)
                    and bool(row_uid or row_id),
                    "can_place": can_place,
                    "can_link": can_link,
                    "detail_uid": row_uid,
                })
        return rows

    def _get_stats(self, rows):
        stats = {
            "expired": 0,
            "pending": 0,
            "in_progress": 0,
            # 阶段 6c：作废行单独计数 —— 它们**不参与**上面三个计数
            # （作废 = 退出流程；混进"待放置"会让待办数量虚高）
            "voided": 0,
        }
        for row in rows:
            if row.get("is_voided"):
                stats["voided"] += 1
                continue
            status = row.get("status")
            if status == "completed":
                continue
            if row.get("is_expired"):
                stats["expired"] += 1
            elif status == "pending_placement":
                stats["pending"] += 1
            else:
                stats["in_progress"] += 1
        return stats


class WorkflowActionSamplePlacementAdapter(RequestContextAware):
    implements(IWorkflowActionUIDsAdapter)

    def __call__(self, action, uids):
        if not has_permission("Modify portal content", self.context):
            return self.redirect(
                message=translate_stability(u"You do not have permission to place samples."),
                level="error",
            )

        selected_uids = [uid for uid in (uids or []) if api.is_uid(uid)]
        if not selected_uids:
            return self.redirect(
                message=translate_stability(u"Please select pending tasks first."),
                level="warning",
            )

        query = [("uids:list", uid) for uid in selected_uids]
        url = "{0}/@@sample_placement?{1}".format(
            api.get_url(self.context), urlencode(query))
        return self.request.response.redirect(url)


class WorkflowActionSyncPlanTasksAdapter(RequestContextAware):
    implements(IWorkflowActionUIDsAdapter)

    def __call__(self, action, uids):
        # 权限校验：只有有编辑权限的人才能做同步。
        if not has_permission("Modify portal content", self.context):
            return self.redirect(
                message=translate_stability(u"You do not have permission to sync plan tasks."),
                level="error",
            )

        selected_uids = [uid for uid in (uids or []) if api.is_uid(uid)]
        if not selected_uids:
            return self.redirect(
                message=translate_stability(u"No items selected."),
                level="warning",
            )

        plans = []
        for uid in selected_uids:
            task = api.get_object_by_uid(uid, None)
            plan = task and api.get_parent(task) or None
            if plan is None:
                continue
            if api.get_portal_type(plan) != "StabilityPlan":
                continue
            if plan not in plans:
                plans.append(plan)

        if not plans:
            return self.redirect(
                message=translate_stability(u"No plans found for selected tasks."),
                level="warning",
            )

        try:
            from maitux.stability.subscribers import sync_plan_timepoint_tasks
        except Exception:
            sync_plan_timepoint_tasks = None

        if sync_plan_timepoint_tasks is None:
            return self.redirect(
                message=translate_stability(u"Sync feature is not available."),
                level="error",
            )

        total_created = 0
        total_updated = 0
        total_deleted = 0
        for plan in plans:
            c, u, d = sync_plan_timepoint_tasks(plan, delete_excess=True)
            total_created += c
            total_updated += u
            total_deleted += d

        return self.redirect(
            message=translate_stability(u"Sync done. Created: {0}, Updated: {1}, Deleted: {2}.")
                    .format(total_created, total_updated, total_deleted),
            level="info",
        )


class SamplePlacementView(BrowserView):
    template = ViewPageTemplateFile("templates/sample_placement.pt")

    def __call__(self):
        if not has_permission("Modify portal content", self.context):
            ploneapi.portal.show_message(
                message=translate_stability(u"You do not have permission to place samples."),
                request=self.request,
                type="error",
            )
            return self.request.response.redirect(self.get_back_url())

        if self.request.form.get("button_cancel"):
            return self.request.response.redirect(self.get_back_url())

        self.row_ids = self.get_selected_row_ids()
        # ★ 2026-09-30（用户报的）：冻结方案的行**在页面上就先摘掉**。
        #   此前它们照样出现在表格里、能选批次、能点保存 ——
        #   保存时被静默跳过并回一句"Updated 0 timepoint(s) to Placed."，
        #   用户看到的就是"终止了还能放置"。
        self.frozen_plan_titles = []
        self.tasks = self.get_tasks_data()
        self.stock_batches = self.get_stock_batches()
        self.selected_stock_batch_uids = self.get_selected_stock_batch_uids()

        if self.row_ids and not self.tasks:
            # 勾的行**全部**属于冻结方案：连表单都不给，直接说明白。
            ploneapi.portal.show_message(
                message=self.frozen_message(),
                request=self.request,
                type="error",
            )
            return self.request.response.redirect(self.get_back_url())

        if self.request.form.get("button_save"):
            return self.handle_save()

        return self.template()

    def frozen_message(self):
        """冻结方案的提示（与看板/关联页**同一句 msgid**，不另起文案）。"""
        return translate_stability(
            u"Paused or terminated plans are frozen: their timepoints "
            u"cannot be modified.")

    def has_frozen_plans(self):
        """选中的行里有没有属于冻结方案的（页面要出一条横幅）。"""
        return bool(self.frozen_plan_titles)

    def get_back_url(self):
        return "{0}/@@task_board".format(api.get_url(self.context))

    def get_selected_row_ids(self):
        # 来自看板的 row_id 列表，格式：plan_uid::seq
        value = self.request.get("row_ids", self.request.form.get("row_ids", []))
        if not isinstance(value, (list, tuple)):
            value = [value]
        result = []
        for rid in value:
            if not rid or not isinstance(rid, six.string_types):
                continue
            if "::" not in rid:
                continue
            if rid not in result:
                result.append(rid)
        return result

    def _parse_row_id(self, row_id):
        # 规则统一在 browser/rowids.py（见 get_selected_row_ids 的说明）。
        return parse_row_id(row_id)

    def get_tasks_data(self):
        """要放置的行（**冻结方案的行在这里就被摘掉**）。

        ``self.frozen_plan_titles`` 由本方法累积（页面据此出横幅 +
        在"全被摘掉"时直接跳回看板），所以直接调用本方法时也要能跑 ——
        没初始化过就当成空列表。
        """
        if getattr(self, "frozen_plan_titles", None) is None:
            self.frozen_plan_titles = []
        data = []
        plans = {}
        for rid in self.row_ids:
            plan_uid, seq = self._parse_row_id(rid)
            if plan_uid is None:
                continue
            plan = plans.get(plan_uid)
            if plan is None:
                plan = api.get_object_by_uid(plan_uid, None)
                plans[plan_uid] = plan
            if plan is None or api.get_portal_type(plan) != "StabilityPlan":
                continue

            # ★ 2026-09-30（用户报的）：冻结方案的行**不列出来**。
            #   判据与写库路径同一处（automation.can_modify_plan），
            #   所以不会出现"这里能放、保存时被跳过"的分裂。
            if not automation.can_modify_plan(plan)[0]:
                title = api.get_title(plan) or api.get_id(plan) or u""
                if title and title not in self.frozen_plan_titles:
                    self.frozen_plan_titles.append(title)
                continue

            details = getattr(plan, "plan_details", None) or []
            if seq > len(details):
                continue
            row = details[seq - 1]
            if not isinstance(row, dict):
                continue
            status = row.get("detail_status") or "pending_placement"
            if status != "pending_placement":
                continue
            stock_batch_uid = _first(row.get("stock_batch")) or ""

            months = _normalize_months(row.get("timepoint_days", 0))
            window_days = row.get("window_days", 0)
            if not isinstance(window_days, int) or window_days < 0:
                window_days = 0

            data.append({
                "row_id": rid,
                "plan_title": api.get_title(plan) or "",
                "plan_url": api.get_url(plan),
                "task_title": _task_title(seq, months),
                "timepoint_months": months,
                "window_days": window_days,
                "stock_batch_uid": stock_batch_uid,
            })
        return data

    def get_stock_batches(self):
        query = {
            "portal_type": "StockBatch",
            "review_state": "active",
            "sort_on": "sortable_title",
            "sort_order": "ascending",
        }
        brains = api.search(query, catalog="portal_catalog")
        data = []
        for brain in brains:
            uid = api.get_uid(brain)
            if not api.is_uid(uid):
                continue
            data.append({
                "uid": uid,
                "title": api.get_title(brain) or uid,
            })
        return data

    def get_selected_stock_batch_uids(self):
        value = self.request.form.get("stock_batch_uid", self.request.get("stock_batch_uid", []))
        if value is None:
            return []
        if isinstance(value, six.string_types):
            value = value.strip()
            return value and [value] or []
        if not isinstance(value, (list, tuple)):
            return []
        result = []
        for item in value:
            if not item:
                result.append("")
                continue
            if isinstance(item, six.string_types):
                result.append(item.strip())
            else:
                result.append("")
        return result

    def get_selected_stock_batch_uid_for(self, row, index):
        if index is None or index < 0:
            index = 0
        selected = self.selected_stock_batch_uids or []
        if index < len(selected) and selected[index]:
            return selected[index]
        return (row or {}).get("stock_batch_uid") or ""

    def handle_save(self):
        if not self.tasks:
            ploneapi.portal.show_message(
                message=translate_stability(u"No pending tasks selected."),
                request=self.request,
                type="warning",
            )
            return self.request.response.redirect(self.get_back_url())

        stock_batch_uids = self.get_selected_stock_batch_uids()
        per_row = {}
        missing = 0
        invalid = 0
        for idx, row in enumerate(self.tasks):
            rid = row.get("row_id")
            sb_uid = stock_batch_uids[idx] if idx < len(stock_batch_uids) else ""
            if not sb_uid:
                missing += 1
                continue
            if not api.is_uid(sb_uid):
                invalid += 1
                continue
            per_row[rid] = sb_uid

        if missing or invalid or len(per_row) != len(self.tasks):
            ploneapi.portal.show_message(
                message=translate_stability(u"Please select a Stock Batch for each selected task."),
                request=self.request,
                type="error",
            )
            return self.template()

        updated = 0
        # 阶段 6a：被暂停 / 终止的方案数（放不进任何一行，页面上要说明）
        frozen_plans = 0
        # 把 StockBatch 和状态写回到 Plan Details，同时尽量同步到已生成的 Task。
        plans = {}
        seqs_by_plan = {}
        for item in self.tasks:
            rid = item.get("row_id")
            plan_uid, seq = self._parse_row_id(rid)
            if plan_uid is None:
                continue
            sb_uid = per_row.get(rid) or ""
            if not api.is_uid(sb_uid):
                continue
            seqs_by_plan.setdefault(plan_uid, {})[seq] = sb_uid

        for plan_uid, seq_map in seqs_by_plan.items():
            plan = plans.get(plan_uid)
            if plan is None:
                plan = api.get_object_by_uid(plan_uid, None)
                plans[plan_uid] = plan
            if plan is None:
                continue

            # 阶段 6a：方案被暂停 / 终止 -> 「样品放置」也禁止
            # （第 3 轮第 5 条："暂停就是冻结所有操作"）。
            # 判据与登样/关联/撤销同一处（automation.can_modify_plan），
            # 所以不会出现"这里能放、那里不能登"的口径分裂。
            if not automation.can_modify_plan(plan)[0]:
                frozen_plans += 1
                continue

            details = list(getattr(plan, "plan_details", None) or [])
            for seq in sorted(seq_map.keys()):
                stock_batch_uid = seq_map.get(seq) or ""
                if not api.is_uid(stock_batch_uid):
                    continue
                if seq > len(details):
                    continue
                row = details[seq - 1]
                if not isinstance(row, dict):
                    continue
                # 只有"还没登样"的行可以放置：待放置 / 已放置（可改批次）。
                # 登过样（active）或已完成的点是实际执行结果，不允许再改。
                if (row.get("detail_status") or "pending_placement") \
                        not in ("pending_placement", "placed"):
                    continue

                new_row = dict(row)
                new_row["stock_batch"] = stock_batch_uid
                # ★ 2026-09-29 需求订正（先放置、再登样）：
                #   放置只记库存批次，状态是 `placed`（已放置），**不是** `active` ——
                #   否则放置过的行就再也不能登样了（旧行为，客户的真实痛点）。
                new_row["detail_status"] = "placed"
                details[seq - 1] = new_row
                updated += 1

                # 同步到已生成的时间点任务（如果存在）。
                # 必须按明细行的稳定标识 detail_uid 配对：序号 sequence 是照行号写的，
                # 删除中间行之后所有行号都会平移，按序号找会写到**别的行**的任务上。
                row_uid = get_row_uid(row)
                try:
                    for child in plan.objectValues():
                        if api.get_portal_type(child) != "StabilityTimepointTask":
                            continue
                        if not task_matches_row(child, row_uid, seq):
                            continue
                        if (getattr(child, "detail_status", None) or "pending_placement") \
                                not in ("pending_placement", "placed"):
                            continue
                        try:
                            child.stock_batch = stock_batch_uid
                        except Exception:
                            try:
                                child.stock_batch = [stock_batch_uid]
                            except Exception:
                                pass
                        # 任务的"已放置"与明细行对着来（放置 ≠ 开始）
                        child.detail_status = "placed"
                        child.reindexObject()
                except Exception:
                    pass

            # 写回计划
            placed_seqs = []
            placed_batches = []
            try:
                plan.plan_details = details
                plan.reindexObject()
                ensure_indexed(plan)
            except Exception:
                logger.exception(
                    "Failed to write the placed rows back to plan '%s'",
                    api.get_path(plan))
            else:
                # 阶段 6b：写回成功之后补审计快照（A2）。
                # 与登样/关联/撤销同一个理由：这里也是"直接改字段 + reindexObject"，
                # 不触发修改事件，平台不会自动拍快照。
                placed_seqs = sorted(seq_map.keys())
                placed_batches = sorted(set(seq_map.values()))
                audit.record_write_back(
                    plan, audit.ACTION_PLACE_SAMPLE,
                    actor=current_generator_id(), seqs=placed_seqs,
                    stock_batch=u", ".join(
                        _batch_label(uid) for uid in placed_batches))

        # ★ 2026-09-30：**一行都没更新时不要报"Updated 0 ..."**。
        #   原来无条件报这句 info，配合下面那条 warning，用户很容易只看到
        #   前一句（"更新了 0 行"像是成功了），于是以为"冻结方案也能放置"。
        if updated:
            ploneapi.portal.show_message(
                message=translate_stability(u"Updated {0} timepoint(s) to Placed.").format(updated),
                request=self.request,
                type="info",
            )
        if frozen_plans:
            # 单独报一句：用户勾选的行里混了被暂停/终止的方案时，
            # 只报"更新了 N 行"会让人以为全都放好了。
            ploneapi.portal.show_message(
                message=translate_stability(
                    u"{count} paused or terminated plan(s) were skipped: "
                    u"all operations on their timepoints are frozen.").format(
                        count=frozen_plans),
                request=self.request,
                type="warning",
            )
        return self.request.response.redirect(self.get_back_url())


