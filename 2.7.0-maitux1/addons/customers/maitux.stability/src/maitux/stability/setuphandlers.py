# -*- coding: utf-8 -*-
from bika.lims import api
from plone import api as ploneapi
from datetime import timedelta
from DateTime import DateTime
from Products.CMFPlone.interfaces import INonInstallable
try:
    from Products.CMFPlone.utils import safe_unicode
except Exception:
    safe_unicode = None
from senaite.core import logger
from senaite.core.upgrade.utils import temporary_allow_type
from zope.interface import implementer

from maitux.stability.permissions import AddStabilityPlanTemplate
from maitux.stability.permissions import ManagePlanStatus
from maitux.stability.permissions import ViewLogTab
from maitux.stability.permissions import permission_name


MODULE_ID = "stability_studies"
# 中文注释：以下标题即"菜单名 / 页面标题"的来源（对象 Title），统一用中文，
# 与 maitux.stock 的做法保持一致（原为英文，侧边栏与页面标题都是英文）。
# 中文注释：标题一律存**英文 msgid**，运行时按语言翻译（见 i18n.py 与 locales/）：
#   英文站 -> "Stability Studies"  中文站 -> 稳定性研究
MODULE_TITLE = u"Stability Studies"
MODULE_TYPE = "StabilityStudies"
DEFAULT_STUDY_ID = "default_stability_study"
DEFAULT_STUDY_TITLE = u"Default Stability Study"
DEFAULT_STUDY_TYPE = "StabilityStudy"
# sidebar 当前对子级使用 path 倒序查询，这里通过数字前缀稳定控制显示顺序。
# 同时保留旧 ID 别名，方便历史数据在升级/卸载时统一清理。
TABLE_DEFINITIONS = (
    ("storage_conditions", "500_storage_conditions", u"Storage Conditions", "StorageConditions", ("storage_conditions", "z_storage_conditions")),
    ("packaging_specifications", "400_packaging_specifications", u"Packaging Specifications", "PackagingSpecifications", ("packaging_specifications", "y_packaging_specifications")),
    ("stability_plan_templates", "300_stability_plan_templates", u"Stability Plan Templates", "StabilityPlanTemplates", ("stability_plan_templates", "x_stability_plan_templates")),
    ("stability_plans", "200_stability_plans", u"Stability Plans", "StabilityPlans", ("stability_plans", "w_stability_plans")),
    ("task_board", "100_task_board", u"Task Board", "StabilityPlans", ("task_board", "v_task_board")),
)
TABLE_ID_BY_LOGICAL = dict([(item[0], item[1]) for item in TABLE_DEFINITIONS])
TABLE_ID_ALIASES = dict([(item[1], item[4]) for item in TABLE_DEFINITIONS])
STATIC_TABLES = tuple([(item[1], item[2], item[3]) for item in TABLE_DEFINITIONS])
SIDEBAR_DEPTH = 2
PROJECTNAME = "maitux.stability"

#: 权限的 id 形式 -> title 形式（**兜底表**）。
#:
#: 为什么需要它：`manage_permission()` 校验的是 Zope 认的权限名。本包在
#: **无请求的启动路径**（`bin/instance run` —— 阶段 6a 的停机迁移走的正是它）
#: 下，ZCML 的 id 形式会被判为 "invalid"，而 title 形式始终有效
#: （`workflow` / `rolemap` 两个导入步骤用的就是 title 形式，它们都成功）。
#: `permissions.permission_name()` 依赖 `queryUtility(IPermission)`，
#: 也就是依赖 ZCML 已被加载 —— 迁移路径下不保证，所以这里再留一份字面量兜底。
#:
#: ⚠️ 这张表必须与 profiles/default/rolemap.xml 里的名字**逐字一致**
#: （check_permissions.py 的自检会盯 rolemap 那一侧）。
PERMISSION_TITLE_FALLBACK = {
    AddStabilityPlanTemplate: "maitux.stability: Add Stability Plan Template",
    ManagePlanStatus: "maitux.stability: Manage Plan Status",
}


def _resolved_permission(permission):
    """把权限名解析成 **``possible_permissions()`` 里真正存在的那个名字**。

    ★ 真机实测（2026-09-30，阶段 6a 停机迁移，`bin/instance run`）：

        queryUtility(IPermission, 'maitux.stability.permissions.X') -> FOUND，
            它的 ``.title`` 是 ``'maitux.stability: X'``；
        possible_permissions() 里**只有 title 形式**；
        manage_permission('maitux.stability.permissions.X', ...) 直接报
            ValueError: The permission <em>maitux.stability.permissions.X</em>
            is invalid.

      这与 permissions.py 模块注释的结论完全一致：**id 形式只给
      ``queryUtility(IPermission)`` / ``write_permission()`` 用；
      ``manage_permission()`` / ``checkPermission()`` 认的是 title 形式。**
      本包过去有两处把 id 形式直接喂给 manage_permission（ensure_permissions
      与 force_setup_like_permissions），在有请求的路径下靠 rolemap 兜住了，
      但在**无请求的启动路径**下会直接把整个 setup_handler 打断
      —— 于是后面的工作流绑定、存量方案迁移全都不执行。
    """
    resolved = permission_name(permission)
    if resolved:
        return resolved
    return PERMISSION_TITLE_FALLBACK.get(permission, permission)


def manage_permission_pair(portal, permission, roles):
    """给权限设角色映射：先试解析后的名字，不行再试原样。

    :returns: True 表示已写入；False 表示两种写法都不认。
        刻意**不抛异常** —— 见 ensure_permissions() 里的说明：本 profile 的
        rolemap.xml 已经用 title 形式把同一批角色映射建立过了，
        为了这个"再确认一次"的调用中断整个安装，代价太大。
    """
    candidates = []
    for name in (_resolved_permission(permission), permission,
                 PERMISSION_TITLE_FALLBACK.get(permission)):
        if name and name not in candidates:
            candidates.append(name)

    last_error = None
    for name in candidates:
        try:
            portal.manage_permission(name, roles=roles, acquire=False)
            if name != permission:
                logger.info(
                    "manage_permission needed the resolved form: "
                    "'%s' -> '%s'", permission, name)
            return True
        except Exception as exc:
            last_error = exc
            continue

    logger.error(
        "Failed to register portal permission '%s' "
        "(tried %s; last error: %s)", permission, candidates, last_error)
    return False


def ensure_audit_log_permission(portal):
    """把审计页的读权限**增量**授给 StabilityAdministrator（阶段 6a · A4）。

    ★ 为什么是模块级函数而不是 setup_handler 里的闭包：
      阶段 6a 的迁移脚本（``bin/instance run``，停机执行）**也要**做这一步，
      两个入口必须是**同一份实现** —— 否则"走 profile 装"和"走迁移脚本装"
      会得到两种权限结果，而这种差异只会在某个角色看不到审计页时才被发现。

    为什么必须在 Python 里"读出来再追加"，而不是写进 rolemap.xml：
      GenericSetup 的 rolemap 导入是 ``manage_permission(roles=[...])`` ——
      **整体替换**。写成 XML 会把站点上已经额外勾选的角色全抹掉
      （例如客户在站点后台给 Verifier 开了审计页）。这里是纯增量操作。

    为什么非加不可：``senaite.core: View Log Tab`` 默认只给
      LabManager / Manager（senaite/core/profiles/default/rolemap.xml）
      —— 本模块自己的管理角色（含 cron 专用账号）根本打不开审计页，
      那这一轮做的审计等于没人看得见。

    :returns: True 表示已确认（或刚写入）；False 表示环境不满足、跳过了
    """
    wanted = "StabilityAdministrator"
    try:
        current = portal.rolesOfPermission(ViewLogTab)
        roles = [item["name"] for item in current if item.get("selected")]
        if not roles:
            # 权限还没注册（senaite.core 没装完）—— 不猜默认值，直接跳过。
            logger.warning(
                "Permission '%s' has no roles yet; skipping the grant of '%s'",
                ViewLogTab, wanted)
            return False
        if wanted in roles:
            return True
        roles.append(wanted)
        portal.manage_permission(ViewLogTab, roles=roles, acquire=False)
        logger.info(
            "Granted '%s' to %s (roles now: %s)",
            ViewLogTab, wanted, ", ".join(roles))
        return True
    except Exception:
        # 这是"让审计页可见"的便利项，不是模块能跑起来的前提 —— 记警告不中断。
        logger.warning(
            "Could not grant '%s' to %s", ViewLogTab, wanted, exc_info=True)
        return False


@implementer(INonInstallable)
class HiddenProfiles(object):
    """隐藏卸载 Profile，保持 Add-ons 面板整洁。"""

    def getNonInstallableProfiles(self):  # noqa camelCase
        return [
            "%s:uninstall" % PROJECTNAME,
        ]

    def getNonInstallableProducts(self):  # noqa camelCase
        return []


def setup_handler(context):
    """标准插件安装入口。"""
    install_file = "%s.txt" % PROJECTNAME
    if context.readDataFile(install_file) is None:
        return

    logger.info("MAITUX Stability Studies setup handler [BEGIN]")
    portal = context.getSite()
    _setup_stability_content(portal)
    logger.info("MAITUX Stability Studies setup handler [DONE]")


def post_install(context):
    logger.info("MAITUX Stability Studies post install handler [BEGIN]")
    portal = api.get_portal()
    _setup_stability_content(portal)
    logger.info("MAITUX Stability Studies post install handler [DONE]")


def setup_stability_content(context):
    """兼容旧入口，统一委托到标准安装入口。"""
    setup_handler(context)


def _as_unicode(value):
    """把任意值安全地转成 unicode（py2 下 Title() 返回的是 UTF-8 字节串）。"""
    if value is None:
        return u""
    if isinstance(value, unicode):  # noqa: F821  (py2)
        return value
    try:
        return value.decode("utf-8")
    except Exception:
        try:
            return unicode(value)  # noqa: F821
        except Exception:
            return u""


def sync_title(obj, title):
    """把对象 Title 同步成期望值（幂等），并刷新目录索引。

    两个坑：
    1. py2 下 ``obj.Title()`` 返回 UTF-8 字节串，直接比较会触发 UnicodeWarning
       且结果不可靠 —— 标题永远刷不上去。
    2. 侧边栏/菜单读的是 **catalog 的 Title 索引**，只 setTitle 不 reindex 时
       菜单会一直显示旧名字（"切英文还是中文"就是这么来的）。
    """
    if obj is None or not getattr(obj, "Title", None):
        return False
    current = _as_unicode(obj.Title())
    wanted = _as_unicode(title)
    if current == wanted:
        return False
    try:
        obj.setTitle(wanted)
    except Exception:
        logger.warning("Could not set title of %s", api.get_path(obj))
        return False

    logger.info("Updated title of %s: %r -> %r",
                api.get_path(obj), current, wanted)
    try:
        obj.reindexObject(idxs=["Title", "sortable_title"])
    except Exception:
        pass
    # 兜底：Dexterity 对象没挂 IMultiCatalogBehavior 时 reindexObject() 是空操作
    for tool_name in ("portal_catalog", "uid_catalog"):
        tool = api.get_tool(tool_name)
        if tool is None:
            continue
        try:
            tool.catalog_object(obj, api.get_path(obj))
        except Exception:
            logger.warning("Could not catalog %s in %s",
                           api.get_path(obj), tool_name)
    return True


def _candidate_ids(value):
    canonical = TABLE_ID_BY_LOGICAL.get(value, value)
    related = [canonical]
    aliases = TABLE_ID_ALIASES.get(canonical, ())
    related.extend(aliases)
    candidates = []
    for related_value in related:
        for v in (
            related_value,
            related_value.replace("_", "-"),
            related_value.replace("-", "_"),
        ):
            if v and v not in candidates:
                candidates.append(v)
    return candidates


def _setup_stability_content(portal):
    def object_label(obj):
        """返回对象标识，便于安装日志定位问题对象。"""
        if obj is None:
            return "<missing>"
        try:
            return api.get_path(obj)
        except Exception:
            return repr(obj)

    def prune_container_refs(container, obj_id):
        if container is None or not obj_id:
            return
        for attr in ("_ordering", "_order"):
            order = getattr(container, attr, None)
            if not order:
                continue
            try:
                while obj_id in order:
                    order.remove(obj_id)
            except Exception:
                pass
        try:
            mt_index = getattr(container, "_mt_index", None)
            if mt_index:
                for mt, ids in mt_index.items():
                    try:
                        while obj_id in ids:
                            ids.remove(obj_id)
                    except Exception:
                        pass
        except Exception:
            pass

    def scrub_missing_children(container):
        if container is None:
            return
        try:
            child_ids = list(getattr(container, "objectIds", lambda: [])())
        except Exception:
            child_ids = []
        for child_id in child_ids:
            try:
                obj = container.get(child_id)
            except Exception:
                obj = None
            if obj is not None:
                continue
            prune_container_refs(container, child_id)
            try:
                tree = getattr(container, "_tree", None)
                if tree is not None and child_id in tree:
                    del tree[child_id]
            except Exception:
                pass
            logger.info("Pruned missing child reference '%s' from %s", child_id, api.get_path(container))

    def ensure_fti_permissions():
        types_tool = api.get_tool("portal_types")
        if not types_tool:
            return
        fti = types_tool.getTypeInfo("StabilityPlanTemplate")
        if fti is None:
            return
        try:
            value = getattr(fti, "add_permission", None)
            if value != "maitux.stability.permissions.AddStabilityPlanTemplate":
                setter = getattr(fti, "_setPropValue", None)
                if callable(setter):
                    setter("add_permission", "maitux.stability.permissions.AddStabilityPlanTemplate")
                else:
                    fti.manage_changeProperties(add_permission="maitux.stability.permissions.AddStabilityPlanTemplate")
        except Exception:
            logger.exception(
                "Failed to configure add_permission for StabilityPlanTemplate FTI"
            )
            raise

    def force_setup_like_permissions(obj):
        if obj is None:
            return
        # 这些权限属于核心安装配置，失败后必须中断安装，避免站点处于半配置状态。
        # ⚠️ permission 一律先过 _resolved_permission()：AddStabilityPlanTemplate
        #    这里原本写的是 ZCML 的 **id 形式**，在无请求的启动路径下
        #    manage_permission 会报 "is invalid" 并因此中断整个 setup_handler
        #    （阶段 6a 停机迁移时实测踩到）。
        permission_rules = (
            ("View", ["Authenticated"]),
            ("Access contents information", ["Authenticated"]),
            ("List folder contents", ["Authenticated"]),
            ("Modify portal content", ["LabClerk", "LabManager", "Manager"]),
            ("Add portal content", ["LabClerk", "LabManager", "Manager"]),
            (
                _resolved_permission(AddStabilityPlanTemplate),
                ["LabClerk", "LabManager", "Manager", "Owner"],
            ),
        )
        for permission, roles in permission_rules:
            try:
                obj.manage_permission(permission, roles=roles, acquire=False)
            except Exception:
                logger.exception(
                    "Failed to set permission '%s' on %s",
                    permission,
                    object_label(obj),
                )
                raise

    def ensure_permissions():
        # ★ 2026-09-30 真机订正（阶段 6a 停机迁移时暴露）：
        #
        # 这里原先只传 **ZCML 的 id 形式**，并注释说"两种形式都有映射"。
        # 实测在 `bin/instance run`（停机迁移路径）下会直接炸：
        #     ValueError: The permission
        #     <em>maitux.stability.permissions.AddStabilityPlanTemplate</em> is invalid.
        # 而**同一批权限的 title 形式**（`maitux.stability: ...`）是有效的 ——
        # `workflow` 与 `rolemap` 两个导入步骤用的正是 title 形式，它们都成功了。
        # 这与 permissions.py 模块注释里那条结论完全一致：
        # **`manage_permission()` / `checkPermission()` 认的是 title 形式**，
        # id 形式只给 `queryUtility(IPermission)` / `write_permission()` 用。
        #
        # 所以改成 manage_permission_pair()：先试 id（有请求的路径下它一直是好的，
        # 不改变既有行为），失败再试 permission_name() 解析出的 title，
        # 最后用 PERMISSION_TITLE_FALLBACK 里的字面量兜底。
        # 而且**不再 raise** —— 这个 profile 的 rolemap.xml 已经用 title 形式把
        # 角色映射建立了一遍，这里只是"再确认一次"；为了它中断整个安装，
        # 代价是后面的容器创建、工作流绑定、存量方案迁移全部不执行。
        roles = ["LabClerk", "LabManager", "Manager", "Owner"]
        manage_permission_pair(portal, AddStabilityPlanTemplate, roles)

        # 阶段 6a：管理方案状态（暂停 / 恢复 / 终止）的权限。
        status_roles = ["LabManager", "Manager", "StabilityAdministrator"]
        manage_permission_pair(portal, ManagePlanStatus, status_roles)

        # 阶段 6a · A4：把审计页的读权限加给 StabilityAdministrator。
        # 实现提到模块级了（ensure_audit_log_permission）—— 迁移脚本要用同一份。
        ensure_audit_log_permission(portal)

    def bind_workflows():
        wf_tool = api.get_tool("portal_workflow")
        if wf_tool is None:
            raise RuntimeError("portal_workflow tool not found")

        bindings = (
            (
                (
                    "StabilityPlanTemplate",
                    "StorageCondition",
                    "PackagingSpecification",
                ),
                ("senaite_deactivable_type_workflow",),
            ),
            (
                (
                    "StabilityStudies",
                    "StorageConditions",
                    "PackagingSpecifications",
                    "StabilityPlanTemplates",
                    "StabilityPlans",
                ),
                ("senaite_setup_workflow",),
            ),
            (
                ("StabilityStudy",),
                ("senaite_one_state_workflow",),
            ),
            (
                # 时间点任务仍是单状态：任务的"状态"是明细行状态
                # （pending_placement / placed / active / completed）的镜像，
                # 与**方案的生命周期**（进行中/暂停/终止）是两回事，不跟着改。
                ("StabilityTimepointTask",),
                ("senaite_one_state_workflow",),
            ),
            (
                # 阶段 6a：稳定性方案改绑三态工作流（进行中 / 已暂停 / 已终止）。
                # 定义见 profiles/default/workflows/senaite_stability_plan_workflow/。
                ("StabilityPlan",),
                ("senaite_stability_plan_workflow",),
            ),
        )
        available = set(getattr(wf_tool, "objectIds", lambda: [])() or [])
        for portal_types, workflows in bindings:
            missing = [w for w in workflows if w not in available]
            if missing:
                # 工作流对象还不存在。本 profile 的 workflows/ 目录是由标准
                # `workflow` 导入步骤建的，那一步与本步的先后由 GenericSetup
                # 的依赖图决定 —— 所以这里**不能 raise**：profile 里的
                # workflows.xml 已经声明了绑定，那一步会正确完成，
                # 这里只是"再确认一次"的兜底。
                logger.warning(
                    "Workflow(s) not available yet, skipping binding %s -> %s "
                    "(missing: %s)",
                    ", ".join(portal_types),
                    ", ".join(workflows),
                    ", ".join(missing),
                )
                continue
            try:
                wf_tool.setChainForPortalTypes(portal_types, workflows)
            except Exception:
                logger.exception(
                    "Failed to bind workflows %s to portal types %s",
                    ", ".join(workflows),
                    ", ".join(portal_types),
                )
                raise

    def update_security(obj):
        try:
            wf_tool = api.get_tool("portal_workflow")
        except Exception:
            wf_tool = None

        if wf_tool is not None:
            try:
                # Ensure object is in 'active' state if it has no state
                if not api.get_review_status(obj):
                    wf_tool.setStatusOf("senaite_setup_workflow", obj, {
                        "review_state": "active",
                        "action": None,
                        "actor": "admin",
                        "time": DateTime(),
                        "comments": "Initial state",
                    })
                wf_tool.updateRoleMappingsFor(obj)
            except Exception:
                pass

        try:
            obj.reindexObject(idxs=["allowedRolesAndUsers"])
        except Exception:
            pass

    def apply_constraints(obj, allowed_types):
        try:
            types_tool = api.get_tool("portal_types")
            if types_tool:
                fti = types_tool.getTypeInfo(api.get_portal_type(obj))
            else:
                fti = None
        except Exception:
            fti = None

        behavior_id = "plone.constraintypes"

        if fti is not None and behavior_id:
            try:
                behaviors = list(getattr(fti, "behaviors", ()) or ())
                if behavior_id not in behaviors:
                    behaviors.append(behavior_id)
                    fti.behaviors = tuple(behaviors)
            except Exception:
                pass

        candidates = []
        try:
            from Products.CMFPlone.interfaces.constrains import ISelectableConstrainTypes
            candidates.append(ISelectableConstrainTypes)
        except Exception:
            pass
        try:
            from plone.app.dexterity.behaviors.constrains import ISelectableConstrainTypes
            candidates.append(ISelectableConstrainTypes)
        except Exception:
            pass
        try:
            from plone.app.content.interfaces import ISelectableConstrainTypes
            candidates.append(ISelectableConstrainTypes)
        except Exception:
            pass

        for iface in candidates:
            adapter = None
            try:
                adapter = iface(obj, None)
            except Exception:
                adapter = None

            if adapter is None:
                continue

            set_mode = getattr(adapter, "setConstrainTypesMode", None)
            set_local = getattr(adapter, "setLocallyAllowedTypes", None)
            set_addable = getattr(adapter, "setImmediatelyAddableTypes", None)
            if not callable(set_mode) or not callable(set_local) or not callable(set_addable):
                continue

            try:
                types = list(allowed_types)
                if safe_unicode is not None:
                    try:
                        types = map(safe_unicode, types)
                    except Exception:
                        pass

                adapter.setConstrainTypesMode(1)
                adapter.setLocallyAllowedTypes(types)
                adapter.setImmediatelyAddableTypes(types)

                try:
                    if not adapter.getLocallyAllowedTypes():
                        adapter.setLocallyAllowedTypes(tuple(types))
                        adapter.setImmediatelyAddableTypes(tuple(types))
                except Exception:
                    pass

                try:
                    if not adapter.getLocallyAllowedTypes():
                        adapter.setConstrainTypesMode(2)
                except Exception:
                    pass
                return True
            except Exception:
                pass
        return False

    types_tool = api.get_tool("portal_types")
    if not types_tool:
        return

    ensure_permissions()
    ensure_fti_permissions()
    bind_workflows()

    required_types = [MODULE_TYPE, DEFAULT_STUDY_TYPE]
    required_types.extend([t[2] for t in STATIC_TABLES])
    for portal_type in required_types:
        if types_tool.getTypeInfo(portal_type) is None:
            logger.warning(
                "Type '%s' not found in portal_types. Skipping stability setup.",
                portal_type,
            )
            return

    def cleanup_stale_entries(obj):
        obj_uid = api.get_uid(obj)
        obj_path = api.get_path(obj)
        portal_path = api.get_path(portal)
        for tool_name in ("portal_catalog", "uid_catalog"):
            try:
                tool = api.get_tool(tool_name)
                if tool is None:
                    continue
                brains = tool(
                    UID=obj_uid,
                    sort_on="path",
                )
                for brain in brains:
                    brain_path = brain.getPath()
                    if brain_path != obj_path:
                        try:
                            tool.uncatalog_object(brain_path)
                            logger.info(
                                "Removed stale %s entry for %s: %s",
                                tool_name, obj_uid, brain_path,
                            )
                        except Exception:
                            pass
                if tool_name == "uid_catalog":
                    stale = tool(
                        portal_type=api.get_portal_type(obj),
                        path={"query": portal_path, "depth": 3},
                    )
                    for brain in stale:
                        if api.get_uid(brain) == obj_uid:
                            continue
                        if api.get_title(brain) != api.get_title(obj):
                            continue
                        try:
                            brain.getObject()
                        except Exception:
                            try:
                                tool.uncatalog_object(brain.getPath())
                            except Exception:
                                pass
            except Exception:
                pass

    def recatalog(obj):
        try:
            obj.reindexObject()
        except Exception:
            pass
        for tool_name in ("portal_catalog", "uid_catalog"):
            try:
                tool = api.get_tool(tool_name)
                if tool:
                    tool.catalog_object(obj, api.get_path(obj))
            except Exception:
                pass
        cleanup_stale_entries(obj)

    def migrate_alias_children(source, target):
        if source is None or target is None or source == target:
            return
        try:
            source_ids = list(getattr(source, "objectIds", lambda: [])())
        except Exception:
            source_ids = []
        try:
            target_ids = set(getattr(target, "objectIds", lambda: [])())
        except Exception:
            target_ids = set()

        # 升级过程中如果同时存在旧容器和新容器，先迁移子对象，
        # 避免业务数据残留在旧 ID 下。
        for child_id in source_ids:
            if child_id in target_ids:
                logger.warning(
                    "Skip moving duplicate child '%s' from %s to %s",
                    child_id,
                    api.get_path(source),
                    api.get_path(target),
                )
                continue
            try:
                clipboard = source.manage_cutObjects([child_id])
                target.manage_pasteObjects(clipboard)
                target_ids.add(child_id)
                logger.info(
                    "Moved stability child '%s' from %s to %s",
                    child_id,
                    api.get_path(source),
                    api.get_path(target),
                )
            except Exception as exc:
                logger.warning(
                    "Could not move stability child '%s' from %s to %s: %s",
                    child_id,
                    api.get_path(source),
                    api.get_path(target),
                    exc,
                )

    def merge_alias_objects(container, obj, obj_id):
        if container is None or obj is None:
            return obj

        canonical_id = api.get_id(obj) or obj_id
        is_task_board = canonical_id == TABLE_ID_BY_LOGICAL.get("task_board")

        for alias_id in _candidate_ids(obj_id):
            if alias_id == canonical_id:
                continue
            alias = container.get(alias_id)
            if alias is None:
                continue

            if is_task_board:
                try:
                    alias_children = list(getattr(alias, "objectIds", lambda: [])())
                except Exception:
                    alias_children = []
                # Task Board 理论上不承载业务数据；若历史对象下仍有内容，先保留并记录日志。
                if alias_children:
                    logger.warning(
                        "Keeping old task board alias '%s' because it still contains children",
                        alias_id,
                    )
                    continue
            else:
                migrate_alias_children(alias, obj)

            try:
                container.manage_delObjects([alias_id])
                logger.info("Removed obsolete stability alias '%s'", alias_id)
            except Exception:
                prune_container_refs(container, alias_id)
        return obj

    def create_or_update(container, portal_type, obj_id, title):
        obj = None
        found_id = None
        for cid in _candidate_ids(obj_id):
            obj = container.get(cid)
            if obj is not None:
                found_id = cid
                break
        if obj is None:
            with temporary_allow_type(container, portal_type):
                obj = ploneapi.content.create(
                    container=container,
                    type=portal_type,
                    id=obj_id,
                    title=title,
                )
        elif found_id and found_id != obj_id and obj_id not in getattr(container, "objectIds", lambda: [])():
            try:
                old_id = found_id
                container.manage_renameObject(found_id, obj_id)
                obj = container.get(obj_id)
                found_id = obj_id
                logger.info("Renamed stability object '%s' -> '%s'", old_id, obj_id)
            except Exception:
                pass
        try:
            sync_title(obj, title)
        except Exception:
            pass
        obj = merge_alias_objects(container, obj, obj_id)
        recatalog(obj)
        force_setup_like_permissions(obj)
        update_security(obj)
        return obj

    def reorder_children(container, ordered_ids):
        if container is None or not hasattr(container, "moveObjectToPosition"):
            return
        position = 0
        for obj_id in ordered_ids:
            obj = None
            for cid in _candidate_ids(obj_id):
                obj = container.get(cid)
                if obj is not None:
                    obj_id = cid
                    break
            if obj is None:
                continue
            try:
                container.moveObjectToPosition(obj_id, position)
                position += 1
            except Exception as exc:
                logger.warning(
                    "Could not reorder stability child '%s' in %s: %s",
                    obj_id,
                    object_label(container),
                    exc,
                )

    def delete_if_exists(container, obj_id):
        if container is None:
            return
        for cid in _candidate_ids(obj_id):
            if cid in getattr(container, "objectIds", lambda: [])():
                try:
                    container.manage_delObjects([cid])
                    logger.info("Removed obsolete stability object '%s'", cid)
                except Exception:
                    prune_container_refs(container, cid)

    def delete_default_studies(container):
        def low_level_delete(obj_id):
            tree = getattr(container, "_tree", None)
            if tree is None:
                return False
            try:
                if obj_id not in tree:
                    prune_container_refs(container, obj_id)
                    return True
                del tree[obj_id]
            except Exception:
                prune_container_refs(container, obj_id)
                return False
            prune_container_refs(container, obj_id)
            return True

        if container is None:
            return
        try:
            child_ids = list(getattr(container, "objectIds", lambda: [])())
        except Exception:
            child_ids = []

        for child_id in child_ids:
            obj = container.get(child_id)
            if obj is None:
                if child_id in _candidate_ids(DEFAULT_STUDY_ID):
                    low_level_delete(child_id)
                continue
            if getattr(obj, "portal_type", "") != DEFAULT_STUDY_TYPE:
                continue
            try:
                container.manage_delObjects([child_id])
                logger.info("Removed obsolete default study '%s'", child_id)
            except Exception:
                if low_level_delete(child_id):
                    logger.info("Removed obsolete default study via low-level delete '%s'", child_id)
            cleanup_stale_entries(obj)

    def migrate_storage_time_duration(table):
        if table is None:
            return
        try:
            templates = table.objectValues("StabilityPlanTemplate")
        except Exception as exc:
            logger.warning(
                "Could not enumerate StabilityPlanTemplate objects in %s: %s",
                object_label(table),
                exc,
            )
            templates = []
        for obj in templates:
            try:
                current = getattr(obj, "storage_time", None)
                old = getattr(obj, "storage_duration_minutes", None)
                if isinstance(current, (int, long)) and current:
                    obj.storage_time = timedelta(minutes=int(current))
                if current is None and isinstance(old, (int, long)) and old:
                    obj.storage_time = timedelta(minutes=int(old))
            except Exception as exc:
                logger.warning(
                    "Could not migrate storage_time for %s: %s",
                    object_label(obj),
                    exc,
                )
                continue

    def migrate_plan_workflow_states():
        """阶段 6a：给存量方案补工作流状态（幂等）。

        为什么必须做：方案从 ``senaite_one_state_workflow`` 换绑到
        ``senaite_stability_plan_workflow`` 之后，**存量方案在新工作流下没有任何
        状态记录** —— ``getInfoFor`` 返回空串。虽然 ``plan_status.normalize_state``
        把空当「进行中」（功能不会坏），但目录里 ``review_state`` 也是空，
        方案列表的状态列和状态筛选就都是空的，等于"状态没生效"。

        ★ 只补"完全没有状态"的：已经是 paused / terminated 的方案
        **绝不能被覆盖** —— 那会静默解冻一个被人工停掉的方案。
        """
        try:
            from maitux.stability.plan_status import migrate_existing_plans
        except Exception:
            logger.exception(
                "Failed to import the plan status module; skipping the "
                "workflow state migration")
            return 0
        return migrate_existing_plans(actor=u"profile-import")

    container = None
    for cid in _candidate_ids(MODULE_ID):
        container = portal.get(cid)
        if container is not None:
            break
    if container is None:
        with temporary_allow_type(portal, MODULE_TYPE):
            container = create_or_update(portal, MODULE_TYPE, MODULE_ID, MODULE_TITLE)
    else:
        # 中文注释：容器已存在时**也要**同步标题。
        # 老站点上这个容器是历史安装时用英文标题建的，而这里过去只做
        # recatalog/权限同步 —— 于是改了 MODULE_TITLE 也永远刷不上去，
        # 侧边栏菜单一直显示英文。
        sync_title(container, MODULE_TITLE)
        recatalog(container)
        force_setup_like_permissions(container)
        update_security(container)

    if container is not None:
        for table_id, table_title, table_type in STATIC_TABLES:
            table = create_or_update(container, table_type, table_id, table_title)
            if table_type == "StabilityPlanTemplates":
                apply_constraints(table, ("StabilityPlanTemplate",))
                migrate_storage_time_duration(table)
            if table_type == "StabilityPlans":
                apply_constraints(table, ("StabilityPlan",))
            if table_id == TABLE_ID_BY_LOGICAL["task_board"]:
                apply_constraints(table, ())
                try:
                    table.setLayout("task_board")
                    # Ensure it's not excluded from navigation
                    if getattr(table, "setExcludeFromNav", None):
                        table.setExcludeFromNav(False)
                    table.reindexObject(idxs=["excludeFromNav", "review_state"])
                    logger.info("Configured stability task board entry at '%s'", api.get_path(table))
                except Exception as exc:
                    logger.warning(
                        "Could not configure stability task board entry at '%s': %s",
                        object_label(table),
                        exc,
                    )

        # Default Stability Study is no longer used and should not appear in sidebar.
        delete_if_exists(container, DEFAULT_STUDY_ID)
        delete_default_studies(container)
        reorder_children(container, [item[0] for item in STATIC_TABLES])
        scrub_missing_children(container)

    # 阶段 6a：换绑工作流后给存量方案补状态。放在容器/表都建好之后 ——
    # 方案可能就在这些容器里，早于它们跑会漏掉"刚被建出来"的那批。
    try:
        migrated = migrate_plan_workflow_states()
        if migrated:
            logger.info(
                "Initialized the stability plan workflow state for %d plan(s)",
                migrated)
    except Exception:
        logger.exception(
            "Failed to initialize the workflow state of existing stability plans")

    setup_tool = api.get_senaite_setup()
    if setup_tool:
        folders = list(setup_tool.getSidebarFolders())
        actual_module_id = api.get_id(container) if container else MODULE_ID
        for obsolete_id in _candidate_ids(MODULE_ID):
            if obsolete_id != actual_module_id and obsolete_id in folders:
                folders.remove(obsolete_id)
        if actual_module_id not in folders:
            folders.append(actual_module_id)
            setup_tool.setSidebarFolders(tuple(folders))
        current_depth = getattr(
            setup_tool, "getSidebarNavigationDepth", lambda: None
        )()
        set_depth = getattr(setup_tool, "setSidebarNavigationDepth", None)
        if set_depth and (current_depth is None or current_depth < SIDEBAR_DEPTH):
            set_depth(SIDEBAR_DEPTH)


def uninstall_handler(context):
    """标准插件卸载入口。"""
    uninstall_file = "%s-uninstall.txt" % PROJECTNAME
    if context.readDataFile(uninstall_file) is None:
        return
    uninstall(context)


def uninstall(context):
    """Uninstall handler - 不删除业务数据，仅清理侧边栏注册信息
    """
    logger.info("MAITUX Stability Studies uninstall handler [BEGIN]")
    portal = api.get_portal()

    module_ids = list(_candidate_ids(MODULE_ID))

    # 移除侧边栏注册
    try:
        setup_tool = api.get_senaite_setup()
        if setup_tool:
            folders = list(setup_tool.getSidebarFolders())
            original = list(folders)
            folders = [folder_id for folder_id in folders if folder_id not in module_ids]
            if folders != original:
                setup_tool.setSidebarFolders(tuple(folders))
                logger.info(
                    "Removed stability folder ids from SENAITE sidebar folders: %s",
                    ", ".join(module_ids),
                )
    except Exception as exc:
        logger.warning(
            "Could not remove stability folder ids from sidebar folders: %s", exc
        )

    logger.info("MAITUX Stability Studies uninstall handler [DONE]")
