# -*- coding: utf-8 -*-
#
# 安装 / 卸载
#
# 容器建在 **setup 文件夹里**（不是站点根目录）：
# senaite.core/browser/controlpanel/setupview.py 的 setupitems() 是
#     items = self.setup.objectValues() + self.bika_setup.objectValues()
# 放进 setup 的内容对象会**自动**出现在 Setup 菜单里 —— 所以本包不再需要
# BikaSetup 的 sidebar folders 配置（v1 用过，已移除）。
#
# 安装做四件事（幂等，可重复执行）：
#   1. 确保两个 FTIs 注册、Setup 允许放 GlossaryEntries
#   2. 在 setup 下建中间表容器；**若旧版本把容器建在了站点根目录，搬进 setup**
#   3. 给容器设权限；把容器与条目挂进 uid_catalog / portal_catalog
#   4. 无（Setup 菜单自动收录，不需要额外注册）
#
# 卸载**不删数据**：中间表是台账，删掉等于抹掉历史。

from bika.lims import api
from plone import api as ploneapi
from Products.CMFPlone.interfaces import INonInstallable
from zope.interface import implementer

from maitux.glossary import _
from maitux.glossary import logger
from maitux.glossary.config import CONTAINER_TYPE
from maitux.glossary.config import ENTRY_TYPE
from maitux.glossary.config import FOLDER_ID
from maitux.glossary.config import LISTING_VIEW_NAME
from maitux.glossary.config import PROFILE_ID
from maitux.glossary.config import PROJECTNAME
from maitux.glossary.config import SETUP_FOLDER_ID

FOLDER_TITLE = _(u"Keyword glossary")

SETUP_TYPE = "Setup"

#: 容器上给这些角色开读写（与其它设置数据保持一致）
VIEW_ROLES = ["LabClerk", "LabManager", "Manager", "Owner"]


@implementer(INonInstallable)
class HiddenProfiles(object):

    def getNonInstallableProfiles(self):
        return ["%s:uninstall" % PROJECTNAME]


def post_install(context):
    logger.info("maitux.glossary post install [BEGIN]")
    portal = api.get_portal()
    run_install_steps(portal)
    logger.info("maitux.glossary post install [DONE]")


def run_install_steps(portal):
    setup_type_constraints()
    container = setup_site_structure(portal)
    setup_permissions(container)
    ensure_cataloged(portal, container)


# ---------------------------------------------------------------------------
# 1. 类型约束
# ---------------------------------------------------------------------------

def setup_type_constraints():
    logger.info("*** maitux.glossary: setup type constraints ***")
    types_tool = api.get_tool("portal_types")
    if types_tool is None:
        raise RuntimeError("portal_types tool not found")

    if types_tool.getTypeInfo(CONTAINER_TYPE) is None or \
            types_tool.getTypeInfo(ENTRY_TYPE) is None:
        try:
            setup_tool = api.get_tool("portal_setup")
            setup_tool.runImportStepFromProfile(PROFILE_ID, "typeinfo")
            logger.info("Ran 'typeinfo' import step from %s", PROFILE_ID)
        except Exception as exc:
            logger.warn("typeinfo import failed: %s", exc)

    # setup 文件夹开了 filter_content_types，必须显式允许本类型
    _allow_content_type(types_tool, SETUP_TYPE, CONTAINER_TYPE)
    # 容器只允许放条目
    _allow_content_type(types_tool, CONTAINER_TYPE, ENTRY_TYPE)


def _allow_content_type(types_tool, type_name, allowed_type):
    fti = types_tool.getTypeInfo(type_name)
    if fti is None:
        logger.warn("FTI '%s' not found, skip allowed_content_types", type_name)
        return
    allowed = list(getattr(fti, "allowed_content_types", ()) or ())
    if allowed_type in allowed:
        return
    allowed.append(allowed_type)
    fti.manage_changeProperties(allowed_content_types=tuple(allowed))
    logger.info("Added '%s' to allowed_content_types of '%s'",
                allowed_type, type_name)


# ---------------------------------------------------------------------------
# 2. 站点结构（含旧位置迁移）
# ---------------------------------------------------------------------------

def get_setup_folder(portal=None):
    portal = portal or api.get_portal()
    try:
        return portal._getOb(SETUP_FOLDER_ID, None)
    except Exception:
        return None


def setup_site_structure(portal):
    logger.info("*** maitux.glossary: setup site structure ***")
    setup = get_setup_folder(portal)
    if setup is None:
        raise RuntimeError("'%s' folder not found in the site" % SETUP_FOLDER_ID)

    with ploneapi.env.adopt_roles(["Manager"]):
        # 旧版本把容器建在站点根目录 -> 搬进 setup（保留全部行）
        _migrate_from_site_root(portal, setup)

        container = _get_child(setup, FOLDER_ID)
        if container is not None:
            if api.get_portal_type(container) != CONTAINER_TYPE:
                raise RuntimeError(
                    "%s/%s already exists with type '%s', expected '%s' - "
                    "resolve manually" % (SETUP_FOLDER_ID, FOLDER_ID,
                                          api.get_portal_type(container),
                                          CONTAINER_TYPE))
            logger.info("Skip existing container '%s/%s'",
                        SETUP_FOLDER_ID, FOLDER_ID)
        else:
            container = ploneapi.content.create(
                container=setup,
                type=CONTAINER_TYPE,
                id=FOLDER_ID,
                title=FOLDER_TITLE,
                safe_id=False,
            )
            logger.info("Created container '%s/%s' (%s)",
                        SETUP_FOLDER_ID, FOLDER_ID, CONTAINER_TYPE)

        try:
            current = container.getLayout()
        except Exception:
            current = None
        if current != LISTING_VIEW_NAME:
            container.setLayout(LISTING_VIEW_NAME)
            logger.info("Set layout of '%s' to '%s'", FOLDER_ID,
                        LISTING_VIEW_NAME)

        return container


def _get_child(parent, child_id):
    try:
        return parent._getOb(child_id, None)
    except Exception:
        return None


def _migrate_from_site_root(portal, setup):
    """把站点根目录下的同名容器搬进 setup。

    v1 的容器建在 ``/<site>/keyword_glossary``；现在要放到
    ``/<site>/setup/keyword_glossary``。直接搬（cut/paste）可以保留全部行
    与 UID —— 行对象不重建，因此已填的 zh/en 不会丢。
    """
    old = _get_child(portal, FOLDER_ID)
    if old is None or api.get_portal_type(old) != CONTAINER_TYPE:
        return None

    existing = _get_child(setup, FOLDER_ID)
    if existing is not None:
        logger.warn("Both /%s and /%s/%s exist - leaving them alone, "
                    "please merge manually", FOLDER_ID, SETUP_FOLDER_ID,
                    FOLDER_ID)
        return None

    logger.info("Migrating /%s -> /%s/%s ...", FOLDER_ID, SETUP_FOLDER_ID,
                FOLDER_ID)
    try:
        clipboard = portal.manage_cutObjects([FOLDER_ID])
        setup.manage_pasteObjects(clipboard)
    except Exception as exc:
        logger.error("Migration failed: %s", exc)
        return None

    moved = _get_child(setup, FOLDER_ID)
    if moved is None:
        logger.error("Migration failed: object not found after paste")
        return None

    logger.info("Migrated %d row(s) into /%s/%s", len(moved.objectIds()),
                SETUP_FOLDER_ID, FOLDER_ID)
    return moved


# ---------------------------------------------------------------------------
# 3. 权限
# ---------------------------------------------------------------------------

def setup_permissions(container):
    logger.info("*** maitux.glossary: setup permissions ***")
    targets = [container]
    try:
        targets += list(container.objectValues())
    except Exception:
        pass
    for obj in targets:
        try:
            obj.manage_permission("View", roles=VIEW_ROLES, acquire=0)
            obj.manage_permission("Access contents information",
                                  roles=VIEW_ROLES, acquire=0)
            obj.reindexObjectSecurity()
        except Exception as exc:
            logger.warn("permission setup failed for %s: %s", obj.getId(), exc)


# ---------------------------------------------------------------------------
# 4. 索引（UID 路径变化后必须重挂）
# ---------------------------------------------------------------------------

def ensure_cataloged(portal, container):
    """把容器与条目挂进 catalog。

    uid_catalog 是必须的：列表页保存单元格走
    ``senaite.app.listing.ajax.ajax_set_fields`` -> ``api.get_object_by_uid``，
    uid_catalog 里查不到就会 500。容器搬家后路径变了，也必须重挂。
    """
    if container is None:
        return 0
    targets = [container]
    try:
        targets += [obj for obj in container.objectValues()
                    if api.get_portal_type(obj) == ENTRY_TYPE]
    except Exception:
        pass

    done = 0
    for obj in targets:
        path = "/".join(obj.getPhysicalPath())
        for tool_name in ("uid_catalog", "portal_catalog"):
            try:
                catalog = api.get_tool(tool_name)
                catalog.catalog_object(obj, path)
            except Exception as exc:
                logger.warn("cataloging %s into %s failed: %s",
                            path, tool_name, exc)
        done += 1
    logger.info("maitux.glossary: cataloged %d object(s)", done)
    return done


# ---------------------------------------------------------------------------
# 卸载
# ---------------------------------------------------------------------------

def uninstall(context):
    logger.info("maitux.glossary uninstall [BEGIN]")
    portal = api.get_portal()
    setup = get_setup_folder(portal)
    container = _get_child(setup, FOLDER_ID) if setup is not None else None
    if container is not None:
        logger.info(
            "NOTE: '%s/%s' and its rows are left in place on purpose - the "
            "middle table is an append-only ledger, deleting it would erase "
            "history. Remove it manually if you really want it gone.",
            SETUP_FOLDER_ID, FOLDER_ID)
    logger.info("maitux.glossary uninstall [DONE]")
