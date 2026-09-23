# -*- coding: utf-8 -*-
from bika.lims import api
from plone import api as ploneapi
from Products.CMFPlone.interfaces import INonInstallable
from senaite.core import logger
from zope.interface import implementer

from maitux.stock.config import PROJECTNAME
from maitux.stock.config import USAGE_REQUEST_TYPE
from maitux.stock.config import USAGE_REQUEST_WORKFLOW
from maitux.stock.stockbatchexpiry import REVIEW_STATE_ACTIVE
from maitux.stock.stockbatchexpiry import REVIEW_STATE_DESTROYED
from maitux.stock.stockbatchexpiry import expire_batch
from maitux.stock.stockbatchexpiry import is_due_for_expiry
from maitux.stock.stockbatchexpiry import set_status_value

STOCK_MANAGER_ID = "stockmanager"
# 中文注释：**标题一律存英文 msgid**（对象 Title / FTI title 都是）。
# 为什么：菜单名、面包屑、页面 <title> 都是直接读这个值；只有当它等于目录里的
# msgid 时，运行时翻译才能按当前语言给出中/英文：
#   * 英文站 → 英文原文（locales/en 里的同义条目）
#   * 中文站 → locales/zh*/ 里的中文
# 目录见 src/maitux/stock/locales/*/LC_MESSAGES/maitux.stock.po。
# （侧边栏的翻译链路：senaite.core.i18n.translate -> 未命中时由
#   maitux/stock/i18n_fallback.py 回退到本包域。）
STOCK_MANAGER_TITLE = u"Stock Inventory"
DYNAMIC_SECTION_ID = "stock_dynamic"
STOCK_FOLDER_ID = "stock"
STOCK_FOLDER_TITLE = u"Stock Items"
STOCK_UNITS_ID = "stock_units"
STOCK_TYPES_ID = "stock_types"
PURCHASE_ORDERS_ID = "purchase_orders"
STOCK_BATCHES_ID = "stock_batches"
LOW_STOCK_ID = "low_stock"
LOW_STOCK_TITLE = u"Low Stock"
USAGE_TRACE_ID = "usage_trace"
USAGE_TRACE_TITLE = u"Usage Trace"
USAGE_REPORT_ID = "usage_report"
USAGE_REPORT_TITLE = u"Usage Report"
USAGE_REQUESTS_ID = "usage_requests"
USAGE_REQUESTS_TITLE = u"Usage Requests"
SIDEBAR_DEPTH = 2

# 库存使用记录查询界面（两个独立节点，侧边栏按 path 倒序展示，u 开头排在最前）
USAGE_SECTION_DEFINITIONS = (
    (USAGE_TRACE_ID, "StockUsageTrace", USAGE_TRACE_TITLE),
    (USAGE_REPORT_ID, "StockUsageReport", USAGE_REPORT_TITLE),
)

# 领用申请单目录（需要电子签名的库存走申请审批，申请单放在这里）
USAGE_REQUEST_SECTION_DEFINITIONS = (
    (USAGE_REQUESTS_ID, "StockUsageRequests", USAGE_REQUESTS_TITLE),
)

# 领用申请必须走电子签名的迁移。esignature 是靠"规则表"驱动的，
# 缺行会导致迁移被直接执行（没有签名）——所以安装时幂等写入。
#
# 中文注释：**submit（发起领用）不需要签名**。需求口径是：
#   提交申请 -> 直接进入待审核 -> 审核人（非申请人）**双人复核签名**后才会扣减。
#
# 双人复核为什么必须写在规则表里：
#   * 审核人不能是申请人 —— 工作流守则只能看到"当前用户"，所以单人签名时
#     `disallow_initiator` 就够了；
#   * "双人"是指签名页上一次性录入两个操作员账号密码（primary + secondary），
#     其中**第一个账号**是真正执行迁移的人。第二个账号是复核人，
#     守则完全看不到他，所以只能在签名页按 `disallow_initiator` 校验：
#     两个账号都不能是申请人，且两个账号必须不同。
USAGE_REQUEST_SIGNATURE_RULES = (
    # (transition_id, require_countersign, disallow_initiator)
    (u"approve", True, True),    # 审核领用：双人复核签名 + 双人/申请人都受限
    (u"reject", False, True),    # 驳回：单人签名（驳回不扣减，不需要双人）
)

# 历史上曾经要求签名、现在不该再要求的迁移。安装时要把这些规则**删掉**，
# 否则老站点升级后"提交申请"仍然会弹出签名页。
USAGE_REQUEST_UNSIGNED_TRANSITIONS = (u"submit",)

# 库存相关类型的图标（图标名必须是 senaite 图标表里真实存在的，
# 否则会回退成 icon-not-found —— 即界面上的"问号"图标）。
# 与 senaite core 各类型一致，使用 ``senaite_theme/icon/<名称>`` 形式。
TYPE_ICONS = (
    ("LowStockSection", "senaite_theme/icon/warning"),
    ("StockUsageTrace", "senaite_theme/icon/auditlog"),
    ("StockUsageReport", "senaite_theme/icon/report"),
    ("StockSection", "senaite_theme/icon/clientfolder"),
    ("StockType", "senaite_theme/icon/category"),
    ("StockUnit", "senaite_theme/icon/container"),
)

# 只有命中这些历史取值才覆盖，避免冲掉客户自定义的图标
BROKEN_ICON_EXPRS = ("", None, "senaite_theme/icon/folder")

STOCK_CHILDREN = (
    # 与上面的模块标题同理：存英文 msgid，运行时按语言翻译成中文
    (STOCK_UNITS_ID, "StockUnits", u"Units"),
    (STOCK_TYPES_ID, "StockTypes", u"Stock Types"),
    (PURCHASE_ORDERS_ID, "StockPurchaseOrders", u"Purchase Orders"),
    (STOCK_BATCHES_ID, "StockBatches", u"Stock Batches"),
)


@implementer(INonInstallable)
class HiddenProfiles(object):
    """隐藏卸载 profile，保持插件入口与标准 Add-on 一致。"""

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

    logger.info("MAITUX STOCK setup handler [BEGIN]")
    portal = context.getSite()
    run_install_steps(portal)
    logger.info("MAITUX STOCK setup handler [DONE]")


def setup_stock_content(context):
    """兼容旧入口，统一委托到标准插件安装入口。"""
    setup_handler(context)


def run_install_steps(portal):
    """按官方安装器风格拆分步骤，逐步执行并保留完整日志。"""
    setup_type_constraints()
    setup_type_icons()
    stock_manager = setup_site_structure(portal)
    setup_permissions(stock_manager)
    setup_sidebar()
    setup_workflows()
    ensure_unicode_workflow_state_titles()
    setup_esignature_rules()
    reindex_stock_structure(stock_manager)


def ensure_unicode_workflow_state_titles():
    """把领用申请工作流的"状态标题"归一化成 unicode。

    为什么必须做（踩过的坑）：DCWorkflow 从 XML 导入时，状态标题会以 **UTF-8
    字节串**（py2 的 str）落库。而 ``senaite.app.listing`` 的
    ``translate_review_state()`` 会把标题当 msgid 交给 MessageFactory：

        state_title = wf.getTitleForStateOnType(state, portal_type)
        ts.translate(_(state_title or state), context=self.request)

    py2 下 MessageFactory 收到非 ASCII 字节串会直接抛
    ``UnicodeDecodeError: 'ascii' codec can't decode byte 0xe5``，表现为
    **列表接口 500**（页签/表格都刷不出来）。

    上游那个位置不方便改，所以在自己的安装步骤里把标题转成 unicode。
    幂等：已经是 unicode 就直接跳过。
    """
    logger.info("*** Ensure Unicode Workflow State Titles ***")
    workflow_tool = api.get_tool("portal_workflow")
    if workflow_tool is None:
        logger.warn("portal_workflow not found; skip state title fix")
        return
    workflow = workflow_tool.getWorkflowById(USAGE_REQUEST_WORKFLOW)
    if workflow is None:
        logger.warn("workflow '%s' not found; skip state title fix",
                    USAGE_REQUEST_WORKFLOW)
        return

    states = getattr(workflow, "states", None)
    if states is None:
        return

    fixed = 0
    for container_name in ("states", "transitions"):
        container = getattr(workflow, container_name, None)
        if container is None:
            continue
        for item_id in list(getattr(container, "objectIds", lambda: [])()):
            item = container.get(item_id)
            if item is None:
                continue
            title = getattr(item, "title", None)
            if not title or isinstance(title, unicode):
                continue
            try:
                item.title = title.decode("utf-8")
                fixed += 1
            except Exception:
                logger.warn("Could not normalize title of %s '%s'",
                            container_name, item_id)
    logger.info("Normalized %s workflow state/transition title(s)", fixed)


def setup_type_icons():
    """修正库存相关类型的图标，避免侧边栏/列表出现"问号"图标。

    背景：senaite 的图标表（``@@senaite_theme`` 的 ``icons()``）按
    ``senaite.core/browser/static/assets/icons`` 下的文件名建索引，
    取不到的图标名会回退成 ``icon-not-found``（问号）。历史 FTI 里写的
    ``senaite_theme/icon/folder`` 并不存在（图标表里没有 ``folder``），
    因此这几个节点一直显示问号。
    """
    logger.info("*** Setup Stock Type Icons ***")
    types_tool = api.get_tool("portal_types")
    if types_tool is None:
        raise RuntimeError("portal_types tool not found")

    for type_name, icon_expr in TYPE_ICONS:
        fti = types_tool.getTypeInfo(type_name)
        if fti is None:
            logger.error("Skip icon for '%s': portal type is not registered yet.",
                         type_name)
            continue
        current = fti.getProperty("icon_expr", None)
        if current not in BROKEN_ICON_EXPRS:
            logger.info("Skip icon for '%s': already '%s'", type_name, current)
            continue
        fti.manage_changeProperties(icon_expr=icon_expr)
        logger.info("Set icon '%s' for '%s' (was %r)", icon_expr, type_name, current)


def setup_type_constraints():
    logger.info("*** Setup Stock Type Constraints ***")
    types_tool = api.get_tool("portal_types")
    if types_tool is None:
        raise RuntimeError("portal_types tool not found")

    ensure_allowed_content_type(types_tool, "Plone Site", "StockManager")
    ensure_allowed_content_type(types_tool, "StockManager", "LowStockSection")

    # 领用申请单目录 + 目录下允许创建申请单
    for type_name, allowed_type in (
            ("StockManager", "StockUsageRequests"),
            ("StockUsageRequests", "StockUsageRequest"),
    ):
        if types_tool.getTypeInfo(allowed_type) is None:
            logger.error(
                "Skip allowed_content_types for '%s' -> '%s': portal type is "
                "not registered yet. Please run the maitux.stock profile "
                "import once more.", type_name, allowed_type)
            continue
        ensure_allowed_content_type(types_tool, type_name, allowed_type)

    for obj_id, portal_type, title in USAGE_SECTION_DEFINITIONS:
        if types_tool.getTypeInfo(portal_type) is None:
            # 中文注释：本环境的 GenericSetup 步骤依赖图存在历史遗留的环，
            # types.xml 的导入（typeinfo）有可能排在本步骤之后。这里只记录明确
            # 错误、不抛异常，避免一次 profile 导入被整体回滚；导入完成后再跑一次
            # profile（或访问 @@stock_usage_setup）即可补齐。
            logger.error(
                "Skip allowed_content_types for '%s': portal type is not "
                "registered yet. Please run the maitux.stock profile import "
                "once more.", portal_type)
            continue
        ensure_allowed_content_type(types_tool, "StockManager", portal_type)


def ensure_allowed_content_type(types_tool, type_name, allowed_type):
    fti = types_tool.getTypeInfo(type_name)
    if fti is None:
        raise RuntimeError("FTI '{}' not found".format(type_name))

    allowed = list(getattr(fti, "allowed_content_types", ()) or ())
    if allowed_type in allowed:
        logger.info("Skip allowed_content_types update for '%s' -> '%s'", type_name, allowed_type)
        return

    allowed.append(allowed_type)
    fti.manage_changeProperties(allowed_content_types=tuple(allowed))
    logger.info("Added '%s' to allowed_content_types of '%s'", allowed_type, type_name)


def setup_site_structure(portal):
    logger.info("*** Setup Stock Site Structure ***")
    with ploneapi.env.adopt_roles(["Manager"]):
        migrate_legacy_stock_root_from_setup(portal)
        stock_manager = ensure_content(
            portal, "StockManager", STOCK_MANAGER_ID, STOCK_MANAGER_TITLE)
        remove_dynamic_section(stock_manager)
        stock_folder = ensure_stock_folder(stock_manager)
        migrate_legacy_root_stock_folder(portal, stock_folder)
        move_root_stock_items_into_folder(stock_manager, stock_folder)

        for child_id, portal_type, title in STOCK_CHILDREN:
            ensure_content(stock_manager, portal_type, child_id, title)

        ensure_usage_sections(stock_manager)
        ensure_usage_request_section(stock_manager)
        ensure_low_stock_section(stock_manager)
        return stock_manager


def ensure_usage_request_section(stock_manager):
    """创建领用申请单目录（幂等）。

    与使用记录节点同理：FTI 尚未导入时只记录 error 并跳过，不中断 profile 导入。
    """
    logger.info("*** Ensure Stock Usage Request Section ***")
    types_tool = api.get_tool("portal_types")
    for obj_id, portal_type, title in USAGE_REQUEST_SECTION_DEFINITIONS:
        if types_tool is not None and types_tool.getTypeInfo(portal_type) is None:
            logger.error(
                "Cannot create '%s': portal type '%s' is not registered yet. "
                "Re-run the maitux.stock profile import to create it.",
                obj_id, portal_type)
            continue
        ensure_content(stock_manager, portal_type, obj_id, title)


def ensure_usage_sections(stock_manager):
    """创建库存使用记录查询界面的两个节点（幂等）。

    与其它子目录不同，这两个类型的 FTI 是本次新增的，可能因为 GenericSetup
    步骤依赖图存在环而尚未导入。此时记录明确的 error 日志并跳过，不中断整个
    profile 导入；再执行一次 profile 导入（或访问 ``@@stock_usage_setup``）即可。
    """
    logger.info("*** Ensure Stock Usage Sections ***")
    types_tool = api.get_tool("portal_types")
    for obj_id, portal_type, title in USAGE_SECTION_DEFINITIONS:
        if types_tool is not None and types_tool.getTypeInfo(portal_type) is None:
            logger.error(
                "Cannot create '%s': portal type '%s' is not registered yet. "
                "Re-run the maitux.stock profile import (or visit "
                "@@stock_usage_setup on the stock manager) to create it.",
                obj_id, portal_type)
            continue
        ensure_content(stock_manager, portal_type, obj_id, title)


def migrate_legacy_stock_root_from_setup(portal):
    logger.info("*** Migrate Legacy Root From bika_setup ***")
    bika_setup = api.get_bika_setup()
    if bika_setup is None or STOCK_FOLDER_ID not in bika_setup:
        logger.info("Skip legacy migration from bika_setup")
        return

    if STOCK_FOLDER_ID in portal:
        bika_setup.manage_delObjects([STOCK_FOLDER_ID])
        logger.info("Removed legacy '%s' from bika_setup because portal root already has it", STOCK_FOLDER_ID)
        return

    clipboard = bika_setup.manage_cutObjects([STOCK_FOLDER_ID])
    portal.manage_pasteObjects(clipboard)
    logger.info("Moved legacy '%s' from bika_setup to portal root", STOCK_FOLDER_ID)


def ensure_content(container, portal_type, obj_id, title):
    """先检查再创建，避免依赖 try/except 做幂等。"""
    if obj_id in container:
        obj = container[obj_id]
        existing_type = getattr(obj, "portal_type", "")
        if existing_type != portal_type:
            raise RuntimeError(
                "Expected '{}' at '{}', got '{}'".format(
                    portal_type, api.get_path(obj), existing_type))
        ensure_title(obj, title)
        logger.info("Skip existing %s", api.get_path(obj))
        return obj

    ploneapi.content.create(
        container=container,
        type=portal_type,
        id=obj_id,
        title=title,
    )
    obj = container[obj_id]
    logger.info("Created %s", api.get_path(obj))
    return obj


def ensure_title(obj, title):
    if not getattr(obj, "Title", None):
        return
    # 中文注释：obj.Title() 返回的是 UTF-8 字节串（py2），而 title 是 unicode，
    # 直接 == 比较会触发 UnicodeWarning 并且恒为 False，导致标题永远设不上。
    # 统一用 api.safe_unicode 归一化后再比较。
    try:
        current = api.safe_unicode(obj.Title() or u"")
    except Exception:
        current = u""
    wanted = api.safe_unicode(title or u"")
    if current == wanted:
        return
    try:
        obj.setTitle(wanted)
        logger.info("Updated title for %s", api.get_path(obj))
    except Exception:
        logger.warn("Could not set title for %s", api.get_path(obj))
        return
    # 中文注释：侧边栏/菜单读的是 **catalog 里的 Title 索引**，只 setTitle 不 reindex
    # 的话菜单会一直显示旧名字（历史上就出现过"改了常量菜单不变"）。
    try:
        obj.reindexObject(idxs=["Title", "sortable_title"])
    except Exception:
        pass
    # 兜底：Dexterity 对象没挂 IMultiCatalogBehavior 时 reindexObject() 是空操作
    # （本模块的容器类型以前就漏了这个 behavior），这里直接对目录做一次 catalog_object。
    for tool_name in ("portal_catalog", "uid_catalog"):
        tool = api.get_tool(tool_name)
        if tool is None:
            continue
        try:
            tool.catalog_object(obj, api.get_path(obj))
        except Exception:
            logger.warn("Could not catalog %s in %s", api.get_path(obj), tool_name)


def remove_dynamic_section(stock_manager):
    logger.info("*** Remove Dynamic Section ***")
    if DYNAMIC_SECTION_ID not in stock_manager:
        logger.info("Skip missing '%s' section", DYNAMIC_SECTION_ID)
        return
    stock_manager.manage_delObjects([DYNAMIC_SECTION_ID])
    logger.info("Removed '%s' section from stock manager", DYNAMIC_SECTION_ID)


def ensure_stock_folder(stock_manager):
    logger.info("*** Ensure Stock Folder ***")
    if STOCK_FOLDER_ID not in stock_manager:
        return ensure_content(
            stock_manager, "StockFolder", STOCK_FOLDER_ID, STOCK_FOLDER_TITLE)

    stock_folder = stock_manager[STOCK_FOLDER_ID]
    if getattr(stock_folder, "portal_type", "") != "StockFolder":
        raise RuntimeError("Existing '{}' is not a StockFolder".format(STOCK_FOLDER_ID))

    if api.get_uid(stock_folder):
        ensure_title(stock_folder, STOCK_FOLDER_TITLE)
        logger.info("Skip existing %s", api.get_path(stock_folder))
        return stock_folder

    # 历史坏数据可能没有 UID，这里显式重建并迁移子对象。
    legacy_id = get_unique_legacy_id(stock_manager, STOCK_FOLDER_ID)
    stock_manager.manage_renameObject(STOCK_FOLDER_ID, legacy_id)
    logger.info("Renamed broken stock folder to '%s'", legacy_id)
    stock_folder = ensure_content(
        stock_manager, "StockFolder", STOCK_FOLDER_ID, STOCK_FOLDER_TITLE)
    move_children(stock_manager[legacy_id], stock_folder)
    stock_manager.manage_delObjects([legacy_id])
    logger.info("Rebuilt stock folder '%s'", api.get_path(stock_folder))
    return stock_folder


def get_unique_legacy_id(container, base_id):
    legacy_id = "{}_legacy".format(base_id)
    index = 1
    while legacy_id in container:
        legacy_id = "{}_legacy_{}".format(base_id, index)
        index += 1
    return legacy_id


def move_children(source, target):
    child_ids = list(getattr(source, "objectIds", lambda: [])())
    if not child_ids:
        logger.info("Skip empty move from %s", api.get_path(source))
        return

    clipboard = source.manage_cutObjects(child_ids)
    target.manage_pasteObjects(clipboard)
    logger.info("Moved %s child object(s) from %s to %s",
                len(child_ids), api.get_path(source), api.get_path(target))


def migrate_legacy_root_stock_folder(portal, stock_folder):
    logger.info("*** Migrate Legacy Portal Stock Folder ***")
    if STOCK_FOLDER_ID not in portal:
        logger.info("Skip missing legacy portal root '%s'", STOCK_FOLDER_ID)
        return

    legacy = portal[STOCK_FOLDER_ID]
    if getattr(legacy, "portal_type", "") != "StockFolder":
        raise RuntimeError("Legacy portal root '{}' is not a StockFolder".format(STOCK_FOLDER_ID))

    move_children(legacy, stock_folder)
    portal.manage_delObjects([STOCK_FOLDER_ID])
    logger.info("Removed migrated legacy portal root '%s'", STOCK_FOLDER_ID)


def move_root_stock_items_into_folder(stock_manager, stock_folder):
    logger.info("*** Move Root Stock Items ***")
    moved = 0
    for obj_id in list(getattr(stock_manager, "objectIds", lambda: [])()):
        if obj_id == STOCK_FOLDER_ID:
            continue
        obj = stock_manager.get(obj_id)
        if getattr(obj, "portal_type", "") != "Stock":
            continue
        clipboard = stock_manager.manage_cutObjects([obj_id])
        stock_folder.manage_pasteObjects(clipboard)
        moved += 1

    if moved:
        logger.info("Moved %s stock item(s) into %s", moved, api.get_path(stock_folder))
    else:
        logger.info("Skip root stock item migration")


def ensure_low_stock_section(stock_manager):
    logger.info("*** Ensure Low Stock Section ***")
    if LOW_STOCK_ID in stock_manager:
        existing = stock_manager[LOW_STOCK_ID]
        if getattr(existing, "portal_type", "") != "LowStockSection":
            stock_manager.manage_delObjects([LOW_STOCK_ID])
            logger.info("Removed incompatible '%s' before recreation", LOW_STOCK_ID)

    ensure_content(
        stock_manager, "LowStockSection", LOW_STOCK_ID, LOW_STOCK_TITLE)


def setup_permissions(stock_manager):
    logger.info("*** Setup Stock Permissions ***")
    # 中文注释：InventoryAdministrator（库存管理员）必须在这里，否则它连库存结构都
    # 看不到——领用审批的复核人正是这个角色，看不到批次就没法审核。
    roles = ["LabClerk", "LabManager", "InventoryAdministrator",
             "Manager", "Owner"]
    targets = [
        stock_manager,
        stock_manager.get(STOCK_FOLDER_ID),
        stock_manager.get(STOCK_UNITS_ID),
        stock_manager.get(STOCK_TYPES_ID),
        stock_manager.get(PURCHASE_ORDERS_ID),
        stock_manager.get(STOCK_BATCHES_ID),
        stock_manager.get(LOW_STOCK_ID),
    ]
    for obj_id, portal_type, title in USAGE_SECTION_DEFINITIONS:
        targets.append(stock_manager.get(obj_id))

    for obj in filter(None, targets):
        obj.manage_permission("View", roles=roles, acquire=0)
        obj.manage_permission("Access contents information", roles=roles, acquire=0)
        obj.reindexObjectSecurity()
        logger.info("Updated permissions for %s", api.get_path(obj))

    # 领用申请审批目录：**只有审批角色能看到**（这是审批队列，不是普通业务目录）。
    # 申请人自己仍然能看到"自己那张申请单"——申请单的状态权限映射里给了 Owner
    # （CMF 会把创建者设为该对象的 Owner），见工作流定义。
    approval_roles = ["LabManager", "InventoryAdministrator", "Manager", "Owner"]
    container = stock_manager.get(USAGE_REQUESTS_ID)
    if container is not None:
        container.manage_permission("View", roles=approval_roles, acquire=0)
        container.manage_permission(
            "Access contents information", roles=approval_roles, acquire=0)
        container.reindexObjectSecurity()
        logger.info("Restricted '%s' to approver roles %s",
                    api.get_path(container), approval_roles)


def setup_sidebar():
    logger.info("*** Setup Stock Sidebar ***")
    setup_tool = api.get_senaite_setup()
    if setup_tool is None:
        raise RuntimeError("SENAITE setup tool not found")

    folders = list(setup_tool.getSidebarFolders())
    if STOCK_MANAGER_ID not in folders:
        folders.append(STOCK_MANAGER_ID)
        setup_tool.setSidebarFolders(tuple(folders))
        logger.info("Added '%s' to SENAITE sidebar folders", STOCK_MANAGER_ID)
    else:
        logger.info("Skip existing sidebar folder '%s'", STOCK_MANAGER_ID)

    get_depth = getattr(setup_tool, "getSidebarNavigationDepth", None)
    set_depth = getattr(setup_tool, "setSidebarNavigationDepth", None)
    if callable(get_depth) and callable(set_depth):
        current = get_depth()
        if current is None or current < SIDEBAR_DEPTH:
            set_depth(SIDEBAR_DEPTH)
            logger.info("Set sidebar navigation depth to %s", SIDEBAR_DEPTH)
        else:
            logger.info("Skip sidebar depth update, current depth is %s", current)


def setup_workflows():
    logger.info("*** Setup Stock Workflows ***")
    workflow_tool = api.get_tool("portal_workflow")
    if workflow_tool is None:
        raise RuntimeError("portal_workflow tool not found")

    workflow_tool.setChainForPortalTypes(
        ("StockBatch",), ("senaite_stockbatch_workflow",))
    logger.info("Bound 'senaite_stockbatch_workflow' to 'StockBatch'")

    workflow_tool.setChainForPortalTypes(
        ("StockUsageRequest",), ("senaite_stockusagerequest_workflow",))
    logger.info("Bound 'senaite_stockusagerequest_workflow' to 'StockUsageRequest'")

    # 兼容当前 SENAITE/Plone 栈：角色映射更新应针对工作流定义或具体对象，
    # 不能对 portal_workflow 工具使用 portal_type 关键字参数。
    workflow_definition = workflow_tool.getWorkflowById(
        "senaite_stockbatch_workflow")

    catalog = api.get_tool("portal_catalog")
    brains = catalog(portal_type="StockBatch") if catalog else []
    synced_destroyed = 0
    synced_expired = 0
    rolemap_updated = 0
    for brain in brains:
        batch = brain.getObject()
        if not api.is_object(batch):
            continue
        if workflow_definition is not None:
            workflow_definition.updateRoleMappingsFor(batch)
            rolemap_updated += 1

        review_state = api.get_review_status(batch) or ""
        status_value = getattr(batch, "status", "") or ""

        if review_state == REVIEW_STATE_DESTROYED:
            if set_status_value(batch, REVIEW_STATE_DESTROYED):
                batch.reindexObject()
            continue

        if status_value == REVIEW_STATE_DESTROYED:
            workflow_tool.doActionFor(batch, "destroy")
            set_status_value(batch, REVIEW_STATE_DESTROYED)
            batch.reindexObject()
            synced_destroyed += 1
            continue

        if is_due_for_expiry(batch):
            if expire_batch(
                batch,
                workflow_tool=workflow_tool,
                operator=u"system",
                remarks=u"Auto expired during workflow setup",
                reindex=True,
            ):
                synced_expired += 1
                continue

        if review_state == REVIEW_STATE_ACTIVE and set_status_value(batch, REVIEW_STATE_ACTIVE):
            batch.reindexObject()

    logger.info("Updated workflow role mappings for %s StockBatch object(s)",
                rolemap_updated)
    logger.info("Synced destroyed workflow state for %s StockBatch object(s)", synced_destroyed)
    logger.info("Synced expired workflow state for %s StockBatch object(s)", synced_expired)


def setup_esignature_rules():
    """把领用申请的签名规则幂等写入 maitux.esignature 的规则表。

    为什么必须自动写：电子签名是靠 (portal_type, workflow_id, transition_id)
    规则表驱动的。规则缺失时标准工作流入口会**直接执行迁移**——也就是申请会
    在没有任何签名的情况下被批出去。守卫里有 fail-closed 兜底会拦住这种情况，
    但那只会在界面上表现为"点了没反应"，所以安装时就把规则补齐。

    规则表在 registry 里（maitux.esignature.policy_rules_json）。
    本步骤只管理"领用申请"这一个 portal_type 的那几行：新增缺失行、把已存在
    行的配置**收敛到期望值**（例如把旧的单人签名纠正为双人复核）、删掉不该再
    要求签名的迁移；其它 portal_type 的规则原样保留。
    """
    logger.info("*** Setup Stock Usage Request Signature Rules ***")
    try:
        from maitux.esignature.interfaces import (
            IESignatureControlPanelSettings,
        )
        from maitux.esignature.services.rules import dumps_policy_rules
        from maitux.esignature.services.rules import loads_policy_rules
        from maitux.esignature.services.rules import normalize_rule
    except ImportError:
        logger.warn("maitux.esignature is not available; "
                    "skip stock usage request signature rules")
        return

    from plone.registry.interfaces import IRegistry
    from zope.component import getUtility

    # 中文注释：IRegistry 在 Plone 里通常是**站点级本地工具**，
    # 没有站点上下文时 getUtility 会抛 ComponentLookupError。
    # 这里做两级兜底，避免因为取注册表失败而让整个安装步骤挂掉。
    registry = None
    try:
        registry = getUtility(IRegistry)
    except Exception:
        registry = getattr(api.get_portal(), "portal_registry", None)
    if registry is None:
        logger.warn("Cannot reach the registry; skip stock usage request "
                    "signature rules")
        return
    # 与 esignature 控制面板一致：先确保 registry 记录存在（老站点补齐）
    try:
        registry.registerInterface(
            IESignatureControlPanelSettings, prefix="maitux.esignature")
    except Exception:
        pass

    key = "maitux.esignature.policy_rules_json"
    record = registry.records.get(key)
    raw = getattr(record, "value", u"[]") if record is not None else u"[]"
    rules = loads_policy_rules(raw)

    # 1) 先纠正历史配置：删掉不该再要求签名的迁移规则
    removed = 0
    kept = []
    for rule in rules:
        if (rule.get("portal_type") == USAGE_REQUEST_TYPE
                and rule.get("transition_id") in USAGE_REQUEST_UNSIGNED_TRANSITIONS):
            removed += 1
            continue
        kept.append(rule)
    rules = kept

    # 2) 再补齐/纠正需要的规则。
    #    这里必须"按期望值收敛"而不是"已存在就跳过"：老站点上 approve 那行
    #    可能还是旧的 require_countersign=False（单人签名），如果只做增量追加，
    #    改了常量重新安装也不会生效，界面上就表现为"电子签名不是双人的"。
    managed_keys = ("signature_required", "require_countersign",
                    "disallow_initiator")
    desired = {}
    for rule_spec in USAGE_REQUEST_SIGNATURE_RULES:
        transition_id, require_countersign, disallow_initiator = rule_spec
        desired[transition_id] = normalize_rule({
            "portal_type": USAGE_REQUEST_TYPE,
            "workflow_id": USAGE_REQUEST_WORKFLOW,
            "transition_id": transition_id,
            "signature_required": True,
            "require_countersign": require_countersign,
            "disallow_initiator": disallow_initiator,
            "meaning_required": True,
            "reason_required": True,
        })

    added = 0
    updated = 0
    kept_rules = []
    present = set()
    for rule in rules:
        if rule.get("portal_type") != USAGE_REQUEST_TYPE:
            kept_rules.append(rule)
            continue
        transition_id = rule.get("transition_id")
        expected = desired.get(transition_id)
        if expected is None:
            # 不是本模块期望管理的迁移，原样保留
            kept_rules.append(rule)
            continue
        present.add(transition_id)
        # 只覆盖本模块管理的字段，保留用户对 meaning/reason 等其它开关的自定义
        merged = dict(rule)
        merged.update(dict(
            (key, expected[key]) for key in managed_keys))
        if merged != rule:
            updated += 1
        kept_rules.append(merged)
    rules = kept_rules

    for transition_id in sorted(desired):
        if transition_id in present:
            continue
        rules.append(desired[transition_id])
        added += 1

    if not added and not removed and not updated:
        logger.info("Signature rules for '%s' already up to date", USAGE_REQUEST_TYPE)
        return

    if record is None:
        try:
            registry.registerInterface(
                IESignatureControlPanelSettings, prefix="maitux.esignature")
        except Exception:
            pass
        record = registry.records.get(key)
    if record is None:
        logger.error("Cannot write signature rules: registry record '%s' missing", key)
        return

    record.value = dumps_policy_rules(rules)
    logger.info("Stock usage request signature rules: +%s added, ~%s updated, "
                "-%s removed", added, updated, removed)


def reindex_stock_structure(stock_manager):
    logger.info("*** Reindex Stock Structure ***")
    targets = [
        stock_manager,
        stock_manager.get(STOCK_FOLDER_ID),
        stock_manager.get(STOCK_UNITS_ID),
        stock_manager.get(STOCK_TYPES_ID),
        stock_manager.get(PURCHASE_ORDERS_ID),
        stock_manager.get(STOCK_BATCHES_ID),
        stock_manager.get(LOW_STOCK_ID),
    ]
    for obj_id, portal_type, title in USAGE_SECTION_DEFINITIONS:
        targets.append(stock_manager.get(obj_id))

    for obj in filter(None, targets):
        obj.reindexObject()
        logger.info("Reindexed %s", api.get_path(obj))


def uninstall_handler(context):
    """标准插件卸载入口，不删除业务数据，仅清理注册信息。"""
    uninstall_file = "%s-uninstall.txt" % PROJECTNAME
    if context.readDataFile(uninstall_file) is None:
        return

    logger.info("MAITUX STOCK uninstall handler [BEGIN]")

    setup_tool = api.get_senaite_setup()
    if setup_tool is None:
        raise RuntimeError("SENAITE setup tool not found")

    folders = list(setup_tool.getSidebarFolders())
    if STOCK_MANAGER_ID in folders:
        folders.remove(STOCK_MANAGER_ID)
        setup_tool.setSidebarFolders(tuple(folders))
        logger.info("Removed '%s' from SENAITE sidebar folders", STOCK_MANAGER_ID)
    else:
        logger.info("Skip missing sidebar folder '%s'", STOCK_MANAGER_ID)

    logger.info("MAITUX STOCK uninstall handler [DONE]")


def uninstall(context):
    """兼容旧卸载入口，统一委托到标准插件卸载入口。"""
    uninstall_handler(context)

