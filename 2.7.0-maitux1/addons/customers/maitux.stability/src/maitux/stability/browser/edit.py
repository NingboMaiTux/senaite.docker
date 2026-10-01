# -*- coding: utf-8 -*-
"""稳定性方案编辑表单 —— 给「时间点行」的删改加守卫。

需求约定：

* 任何方案（含已经开始的方案）都可以**新增**时间点行；
* 只有**还没登样**的时间点行可以**删除**（待放置 / 已放置），
  登过样（进行中）或已完成的**不允许删除**
  —— 2026-09-29 需求订正（先放置、再登样）：「样品放置」只记库存批次，
  不算"已开始"，所以放置过的行仍然可删。
* **阶段 6c 起，"删除"不再是真删**：可删的行改走**状态删除**（写 ``voided_*``
  三个标记键）—— 行留在方案里、样品关联保留、审计留痕。
* **阶段 6d（用户 2026-09-30 定稿）**：单独的动作页 ``@@void_point`` 已撤掉，
  **删除只有这一条路径**；已废弃的行在本页**不显示**（CSS 隐藏，但照旧随表单
  提交，见下面 ★ 的那条铁律），要看废弃行请走任务看板的「已废弃」筛选。
* **C1 前置条件**：行上关联了样品时，样品必须已达**终态**才允许废弃
  （否则拦下并提示"样品 XXX 尚未完成"）。

三道防线
--------

1. **前端**（`z3cform/widgets/plandetails_datagrid_input.pt`）：
   把受保护行的删除按钮隐藏掉、已废弃的行**隐藏**（★ 只隐藏，**绝不 disable**）。
   这只是体验，用户绕过 JS（改 DOM / 直接构造 POST）就失效。
2. **服务端**（本模块）：保存前拿"库里已有的行"与"本次提交的行"对账 ——
   受保护的行被删就按原位置放回；可删的行被删就**状态删除（废弃）**；
   C1 不满足就放回并报出是哪个样品没完成。
   这一道才是判据 —— 前端判据在本仓库的口径下（R9：失败大多是静默的）不算判据。
3. **写库层**（`timepoints.sanitize_submitted_rows`）：
   废弃标记是**服务端专有字段**，提交上来的值一律不认 ——
   否则伪造一个 ``voided_at`` 就能绕过 C1。

★★ 铁律：DataGrid 里的行**必须继续随表单提交**
----------------------------------------------

"已废弃的行在编辑页不显示"**只能靠 CSS 隐藏**（`tr[data-voided="1"]`），
**绝不能**把行里的输入控件 `disabled`、也不能把行从 DOM 里删掉 ——
被禁用的控件浏览器**根本不提交**，于是"计数标记说有这一行、请求里却没有"，
z3c.form 的 `MultiWidget.extract` 就会拿 `NO_VALUE` 哨兵占位；哨兵不可 pickle，
事务在 commit 时抛 `PicklingError`，**用户那次保存整个丢掉**（2026-09-30
生产事故，就是 6c 在这条上写反了）。同一条铁律在模板注释、自检
`check_write_guard.py`、应用级 G19 与 HTTP 8d 段里各钉了一遍。

为什么放在表单而不是订阅器
--------------------------

`IObjectModifiedEvent` 触发时数据**已经写进对象了**，那时只能"改回去"，
而改回去会再次触发事件。放在表单的 `applyChanges` 里可以在**写库前**修正，
既不引入事件递归，也不会让"删掉的行"在事务里闪现过一下。

落库前的整理逻辑（作废守卫、保留字段兜底、补行标识）全部在
`maitux.stability.timepoints.sanitize_submitted_rows` 里实现，
本模块只负责"取出数据 → 交给它整理 → 给用户提示"。
"""

from AccessControl import Unauthorized
from bika.lims import api
from bika.lims.api.security import check_permission
from plone import api as ploneapi
from plone.dexterity.browser.edit import DefaultEditForm
from senaite.core import logger
from senaite.core.browser.dexterity.views import SenaiteDefaultEditView

from maitux.stability import automation
from maitux.stability import plan_status
from maitux.stability.i18n import translate_stability
from maitux.stability.subscribers import ensure_plan_detail_uids
from maitux.stability.timepoints import sanitize_submitted_rows


# 与 task_board.can_place_samples 同一套兜底角色：
# 本环境里权限命名可能有差异（Modify portal content / cmf.ModifyPortalContent），
# 但实验室这几个角色本来就有编辑权，不能因为查不到权限名就把人挡在门外。
EDIT_ROLES = ("Manager", "LabManager", "LabClerk")


# 方案被冻结时的提示文案（msgid）。
# 与 browser/planstatus.STATUS_MESSAGES 里同名的那两条**必须一致** ——
# 同一个事实（方案暂停了 / 终止了）在两个页面上不能有两种说法。
_BLOCK_MESSAGES = {
    plan_status.BLOCK_PLAN_PAUSED: u"This stability plan is paused. "
                                   u"All operations on it are frozen.",
    plan_status.BLOCK_PLAN_TERMINATED: u"This stability plan is terminated.",
}


def can_edit(context):
    """是否允许打开/提交方案编辑页。

    ★ 为什么权限要在这里查：`@@edit` 的 ZCML 注册只能写 `zope2.View`
    （`cmf.*` 权限在本包 ZCML 加载阶段还没注册，写了会让 Zope 直接起不来，
    见 browser/configure.zcml 的注释）。所以真正的编辑权限必须在这一层补回来 ——
    不补就等于把方案的编辑页开放给所有能看方案的人。
    """
    for name in ("Modify portal content", "cmf.ModifyPortalContent"):
        try:
            if check_permission(name, context):
                return True
        except Exception:
            continue
    try:
        user = ploneapi.user.get_current()
        roles = set(user.getRolesInContext(context))
        if roles.intersection(set(EDIT_ROLES)):
            return True
    except Exception:
        pass
    return False


def _path(obj):
    """日志用的对象路径（取不到也不能让日志本身抛异常）。"""
    try:
        return api.get_path(obj)
    except Exception:
        try:
            return api.get_id(obj)
        except Exception:
            return repr(obj)


def _row_label(index, row):
    """给提示文案用的行标签：``TP 3 (6 Months)`` 这种。

    时间点单位是"月"（字段名是 timepoint_days，历史原因，见
    content/stabilityplan.py 的 MONTHS_VOCABULARY）。
    """
    try:
        months = int(row.get("timepoint_days") or 0)
    except Exception:
        months = 0
    return "TP {0} ({1} Months)".format(index + 1, months)


class StabilityPlanEditForm(DefaultEditForm):
    """稳定性方案的标准编辑表单（覆盖 `@@edit`）。"""

    def updateWidgets(self, *args, **kwargs):
        # 必须在建控件**之前**补行标识：明细的隐藏列 `detail_uid`
        # 取的是对象上的值，晚一步补，这一屏渲染出来的隐藏输入就全是空的。
        # 历史方案（本功能上线前建的）只有第一次打开时才会走到这里。
        try:
            ensure_plan_detail_uids(self.context)
        except Exception:
            logger.exception(
                "Failed to ensure timepoint row ids while rendering the "
                "stability plan edit form for '%s'", _path(self.context))
        return super(StabilityPlanEditForm, self).updateWidgets(*args, **kwargs)

    def applyChanges(self, data):
        data = self._sanitize_timepoint_rows(data)
        return super(StabilityPlanEditForm, self).applyChanges(data)

    def _sanitize_timepoint_rows(self, data):
        """保存前整理时间点明细行（删除守卫 + 保留字段兜底 + 补行标识）。"""
        if "plan_details" not in data:
            # 字段根本没进表单（控件渲染失败/字段被裁掉）：
            # 保持原样交给基类处理，不要在守卫里"顺手清空明细"。
            return data

        submitted = data.get("plan_details")
        if not isinstance(submitted, (list, tuple)):
            # ★ 拿到的不是列表：这是**读失败**，不是"用户把行删光了"。
            #   典型来源有两个：
            #     ① z3c.form 的 NO_VALUE 哨兵 —— DataGrid 的计数标记没提交上来时
            #        `MultiWidget.extract` 直接返回哨兵；
            #     ② 字段被别的东西填成了别的类型。
            #   哨兵是**不可 pickle** 的类实例，写进字段会让事务在 commit 时
            #   抛 PicklingError（2026-09-30 生产事故）。所以这里把字段从提交
            #   数据里**摘掉**：本次不改明细，其余字段照常保存，并告诉用户。
            logger.warning(
                "Unreadable plan_details submitted for stability plan '%s': "
                "%r -> keep the stored timepoint rows",
                _path(self.context), submitted)
            data = dict(data)
            data.pop("plan_details", None)
            self._notify(
                u"The timepoint rows could not be read, so they were left "
                u"unchanged. Please reload the page and try again.",
                [], "error")
            return data

        # 控件层丢过行（整行是哨兵 = 这一行没提交上来）：
        # 这次提交的"缺席行"**不能**当成用户删除 —— 直接按库里的行原样放回。
        dropped = self._dropped_rows()
        if dropped:
            logger.warning(
                "Dropped %s unreadable timepoint row(s) for stability plan "
                "'%s' -> keep the stored timepoint rows", dropped,
                _path(self.context))
            data = dict(data)
            data["plan_details"] = [dict(row) for row in
                                    (getattr(self.context, "plan_details", None) or [])]
            self._notify(
                u"The timepoint rows could not be fully read, so no timepoint "
                u"was deleted. Please reload the page and try again.",
                [], "error")
            return data

        stored = list(getattr(self.context, "plan_details", None) or [])

        # 阶段 6b/6c：**不允许编辑的行**（已过期 / 已作废）改值一律作废。
        # 判据注入（本模块不认识方案与样品，纯逻辑留在 timepoints/plan_status）：
        #   automation.row_is_locked(context, row) —— 与登样/关联/看板同一实现。
        def is_locked(row):
            try:
                return automation.row_is_locked(self.context, row)
            except Exception:
                # 判据本身出错时**不锁**：宁可让用户改，也不要把整张表单锁死
                # （锁死是不可逆的体验 —— 用户连改回来的机会都没有）。
                logger.exception(
                    "Failed to evaluate the row lock for %s", _path(self.context))
                return False

        # 阶段 6c：**C1 前置条件** —— 提交里缺席的行会被作废，
        # 但"有关联样品"的行必须先确认样品已达终态。
        # 返回 (ok, 原因码, 明细)，明细里带着"哪个样品没完成"。
        def void_guard(row):
            try:
                return automation.can_void_row(self.context, row)
            except Exception:
                logger.exception(
                    "Failed to evaluate the void precondition for %s",
                    _path(self.context))
                # 判据出错时不拦：宁可作废（可以再谈），
                # 也不要"点了删除什么也没发生、还说不清为什么"。
                return (True, u"", u"")

        try:
            rows, report = sanitize_submitted_rows(
                stored, submitted, is_locked=is_locked, void_guard=void_guard)
        except Exception:
            logger.exception(
                "Failed to sanitize timepoint rows for stability plan '%s'",
                _path(self.context))
            return data

        blocked = report.get("blocked") or []

        # 行数守恒：提交上来的 dict 行 + 被放回的行。
        # 对不上说明提取出来的数据结构不是预期的形态 ——
        # 这时**放弃守卫**（明细保持库里原样），绝不能把"没校验过的提交数据"
        # 写回去（里面可能还有哨兵/脏值，见下方注释）。
        submitted_count = len([row for row in submitted if isinstance(row, dict)])
        restored_count = int(report.get("restored") or 0)
        if len(rows) != submitted_count + restored_count:
            logger.warning(
                "Unexpected timepoint row count for stability plan '%s': "
                "sanitized=%s submitted=%s restored=%s blocked=%s voided=%s "
                "sample=%s dropped=%s -> keep the stored rows",
                _path(self.context), len(rows), submitted_count,
                restored_count, len(blocked), len(report.get("voided") or []),
                len(report.get("blocked_by_sample") or []),
                report.get("dropped_rows"))
            data = dict(data)
            # ★ 放回**库里那一份**，而不是返回 `data` 原样：
            #   `data` 里是没通过校验的提交数据，直接写库等于把风险交给
            #   ZODB —— 2026-09-30 的生产 500 就是"守卫放弃 + 原样写回"
            #   把 NO_VALUE 哨兵落进明细，commit 时 PicklingError。
            data["plan_details"] = [dict(row) for row in stored]
            self._notify(
                u"The timepoint rows of this plan could not be verified, so "
                u"they were left unchanged.", [], "error")
            return data

        data = dict(data)
        data["plan_details"] = rows

        # ① 状态层面不可删（已登样 / 已完成）-> 原样放回 + 报错
        if blocked:
            self._notify(
                u"Only timepoints that have not been generated yet can be "
                u"deleted.", self._labels_for(blocked, stored), "error")

        # ② C1 前置条件未满足 -> 原样放回 + 报出是哪个样品没完成
        blocked_by_sample = report.get("blocked_by_sample") or []
        if blocked_by_sample:
            labels = self._labels_for(
                [item[0] for item in blocked_by_sample], stored)
            details = u", ".join(
                u"%s: %s" % (labels[index] if index < len(labels) else u"-",
                             item[2] or item[1] or u"")
                for index, item in enumerate(blocked_by_sample))
            message = translate_stability(
                u"The sample {sample} of this timepoint is not finished. "
                u"Please finish or cancel it before deleting this timepoint.")
            self._notify(message, [details], "error")

        # ③ 本次真的废弃了哪些行 -> 明确告知（"删除"其实是**状态删除**：
        #    行还在方案里，只是从这一页隐藏了；不说的话用户会以为没删掉）
        voided = report.get("voided") or []
        if voided:
            self._notify(
                u"The timepoint has been deleted (status deleted) and is kept "
                u"in the plan for traceability. Use the Discarded filter on "
                u"the task board to see it.",
                self._labels_for(voided, stored), "info")

        # ④ 阶段 6b：被"过期行不许改"挡下来的行，也要说清楚是哪几行、为什么 ——
        #    否则用户会以为"我明明改了、保存后怎么还是原样"。
        reverted = report.get("locked") or []
        if reverted:
            self._notify(
                u"An expired timepoint cannot be edited; delete it or add a "
                u"new timepoint instead.",
                self._labels_for(reverted, stored), "warning")

        return data

    def _dropped_rows(self):
        """控件层丢掉的明细行数（`PlanDetailsWidget.dropped_rows`）。

        取不到就当 0 —— 这个数是**加严**用的：读不到只是少一道提示，
        真正的写库兜底在 `timepoints.sanitize_submitted_rows` 第 7 步。
        """
        try:
            widget = self.widgets.get("plan_details")
        except Exception:
            return 0
        try:
            return max(0, int(getattr(widget, "dropped_rows", 0) or 0))
        except Exception:
            return 0

    def _labels_for(self, rows, stored):
        """把行对象翻译成 ``TP 3 (6 Months)`` 这种可读标签（按原位置找下标）。

        ★ 按**对象身份**找下标：明细行是 dict，用 ``list.index`` 做相等比较时，
          两行内容一样会取到前一行（6a 踩过）。
        """
        labels = []
        for row in rows or []:
            found = False
            for position, stored_row in enumerate(stored):
                if stored_row is row:
                    labels.append(_row_label(position, row))
                    found = True
                    break
            if not found:
                # 新作废的行是**新 dict**（不是库里那个对象）——
                # 用 detail_uid 兜底配对，配不上就退化成"（新行）"。
                uid = (row or {}).get("detail_uid")
                for position, stored_row in enumerate(stored):
                    if uid and stored_row.get("detail_uid") == uid:
                        labels.append(_row_label(position, row))
                        found = True
                        break
            if not found:
                labels.append(u"-")
        return labels

    def _notify(self, msgid, labels, level):
        """同时写状态栏与 portal message（页面跳走后还能看到）。

        ★ 只写一处的话，页面跳走以后用户就看不到原因了（6a 的既有做法）。
        """
        message = translate_stability(msgid)
        labels = [label for label in (labels or []) if label]
        if labels:
            message = u"{0} ({1})".format(message, u", ".join(labels))
        self.status = message
        try:
            ploneapi.portal.show_message(
                message=message, request=self.request, type=level)
        except Exception:
            pass


class StabilityPlanEditView(SenaiteDefaultEditView):
    """`@@edit` 的视图壳：把表单换成带守卫的实现，并补回编辑权限校验。"""

    form = StabilityPlanEditForm

    def __call__(self, *args, **kwargs):
        # 权限校验必须在进表单之前：ZCML 里只能声明 zope2.View，
        # 少了这一句，任何能看方案的账号都能打开并提交编辑页。
        if not can_edit(self.context):
            raise Unauthorized(
                "You are not allowed to modify this stability plan.")

        # 阶段 6a：方案被暂停 / 终止 -> **完全冻结**，连打开编辑页都不允许
        # （第 2 轮第 4 条："该计划的方案明细都不允许做任何操作，计划也不允许编辑"；
        #   第 3 轮第 1 条：暂停期间连删/加时间点都不行）。
        #
        # ★ 这里刻意**不抛 Unauthorized**：用户的编辑权限没有问题，是**方案状态**
        #   不允许 —— 抛 401 只会让人以为是自己账号出了问题，然后去找管理员要权限。
        #   改成"给一句说得清的话 + 跳回方案页"，用户才知道该去做什么（恢复或另建方案）。
        # ★ 必须判第 1 个返回值（ok），**不能**判第 2 个（原因码）的真假 ——
        #   "没被冻结"时返回的是 (True, plan_status.BLOCK_OK)，而 BLOCK_OK 是
        #   非空字符串（真值）：按原因码判会把**所有**方案的编辑页都重定向掉。
        #   自检里有一条源码守卫专门盯这个写法（check_plan_status.py 的 F 段）。
        plan_ok, blocked = plan_status.can_modify_plan(
            plan_status.get_plan_state(self.context))
        if not plan_ok:
            message = _BLOCK_MESSAGES.get(blocked)
            ploneapi.portal.show_message(
                message=translate_stability(message) if message
                else translate_stability(
                    u"This stability plan cannot be edited in its current "
                    u"state."),
                request=self.request, type="error")
            return self.request.response.redirect(api.get_url(self.context))

        return super(StabilityPlanEditView, self).__call__(*args, **kwargs)
