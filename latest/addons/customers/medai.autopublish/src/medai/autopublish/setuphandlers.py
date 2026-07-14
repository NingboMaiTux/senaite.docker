# -*- coding: utf-8 -*-
"""Setup handlers for medai.autopublish.

- Binds IReportDraftingSetup behavior to Setup FTI
- Creates Portal Folders for samples-to-verify / samples-to-approve
"""

import logging

try:
    from senaite.core.upgrade.utils import temporary_allow_type
except ImportError:
    from contextlib import contextmanager

    @contextmanager
    def temporary_allow_type(container, portal_type):
        yield container

from bika.lims import api
from zope.i18nmessageid import MessageFactory

_ = MessageFactory("medai.autopublish")

logger = logging.getLogger("medai.autopublish")

BEHAVIOR = "medai.autopublish.behaviors.report_drafting_setup.IReportDraftingSetup"
DEPT_FILTER_BEHAVIOR = "medai.autopublish.behaviors.department_filter.IDepartmentFilterSetup"
AUTO_PUBLISH_BEHAVIOR = "medai.autopublish.behaviors.auto_publish.IAutoPublishBehavior"
MARKER_FILE = "medai.autopublish_various.txt"
UNINSTALL_MARKER = "medai.autopublish_uninstall.txt"

# Portal Folders for the Samples review entry split
ENTRY_FOLDERS = (
    {
        "id": "samples-to-verify",
        "title": _(u"Samples to Verify"),
        "layout": "@@redirect-samples-to-verify",
    },
    {
        "id": "samples-to-approve",
        "title": _(u"Samples to Approve"),
        "layout": "@@redirect-samples-to-approve",
    },
)


# ---------------------------------------------------------------------------
# FTI behavior helpers
# ---------------------------------------------------------------------------

def _add_behavior_to_fti(fti_name, behavior):
    """Add a behavior to an existing Dexterity FTI (idempotent)."""
    types_tool = api.get_tool("portal_types")
    fti = types_tool.get(fti_name)
    if fti is None:
        logger.warning("FTI '%s' not found, cannot add behavior %s", fti_name, behavior)
        return

    behaviors = list(fti.behaviors)
    if behavior in behaviors:
        logger.info("Behavior %s already registered on %s", behavior, fti_name)
        return

    behaviors.append(behavior)
    fti.behaviors = tuple(behaviors)
    logger.info("Added behavior %s to FTI %s", behavior, fti_name)


def _remove_behavior_from_fti(fti_name, behavior):
    """Remove a behavior from a Dexterity FTI."""
    types_tool = api.get_tool("portal_types")
    fti = types_tool.get(fti_name)
    if fti is None:
        return

    behaviors = list(fti.behaviors)
    if behavior not in behaviors:
        return

    behaviors.remove(behavior)
    fti.behaviors = tuple(behaviors)
    logger.info("Removed behavior %s from FTI %s", behavior, fti_name)


# ---------------------------------------------------------------------------
# Portal Folder helpers
# ---------------------------------------------------------------------------

def _get_child(container, object_id):
    try:
        return container.get(object_id)
    except Exception:
        try:
            return getattr(container, object_id, None)
        except Exception:
            return None


def _set_title(obj, title):
    try:
        obj.setTitle(title)
        return
    except Exception:
        pass
    try:
        obj.title = title
    except Exception:
        return


def _set_layout(obj, layout):
    current = None
    try:
        current = obj.getLayout()
    except Exception:
        current = None
    if current == layout:
        return
    try:
        obj.setLayout(layout)
    except Exception:
        return


def _set_exclude_from_nav(obj, value):
    setter = getattr(obj, "setExcludeFromNav", None)
    if callable(setter):
        try:
            setter(value)
            return
        except Exception:
            pass
    try:
        obj.exclude_from_nav = bool(value)
    except Exception:
        return


def _publish(obj):
    try:
        from plone import api as plone_api
        state = plone_api.content.get_state(obj=obj)
        if state != "published":
            plone_api.content.transition(obj=obj, transition="publish")
        return
    except Exception:
        pass
    try:
        wf = api.get_tool("portal_workflow")
        state = wf.getInfoFor(obj, "review_state", default=None)
        if state != "published":
            wf.doActionFor(obj, "publish")
    except Exception:
        return


def _reindex(obj):
    try:
        obj.reindexObject()
    except Exception:
        return


def _create_folder(container, object_id, title):
    portal_types = api.get_tool("portal_types")
    folder_type = "Folder"
    with temporary_allow_type(container, folder_type) as ct:
        return api.create(ct, folder_type, id=object_id, title=title)


_FOLDER_VIEW_ROLES = {
    "samples-to-verify": ("Verifier", "LabManager", "Manager"),
    "samples-to-approve": ("LabManager", "Manager"),
}


def _upsert_folder(container, object_id, title, layout):
    """Create or update a Folder with given layout (idempotent)."""
    obj = _get_child(container, object_id)
    if obj is None:
        obj = _create_folder(container, object_id, title)
    else:
        _set_title(obj, title)

    _set_layout(obj, layout)
    _set_exclude_from_nav(obj, False)

    # Restrict View permission for role-specific folders
    if object_id in _FOLDER_VIEW_ROLES:
        try:
            obj.manage_permission(
                "View",
                roles=list(_FOLDER_VIEW_ROLES[object_id]),
                acquire=False,
            )
            obj.reindexObjectSecurity()
        except Exception:
            logger.exception("Failed to set View permission on %s", object_id)

    _publish(obj)
    _reindex(obj)
    return obj


def _add_sidebar_folder(setup, folder_id):
    current = ()
    try:
        current = setup.getSidebarFolders() or ()
    except Exception:
        current = ()
    if folder_id in current:
        return
    updated = tuple(current) + (folder_id,)
    try:
        setup.setSidebarFolders(updated)
    except Exception:
        logger.exception("Failed to set sidebar folders during install")
        return
    _reindex(setup)


def _remove_sidebar_folder(setup, folder_id):
    current = ()
    try:
        current = setup.getSidebarFolders() or ()
    except Exception:
        current = ()
    updated = tuple(v for v in current if v != folder_id)
    try:
        setup.setSidebarFolders(updated)
    except Exception:
        logger.exception("Failed to clear sidebar folders during uninstall")
        return
    _reindex(setup)


# ---------------------------------------------------------------------------
# Install / Uninstall
# ---------------------------------------------------------------------------

def setup_entry_folders(portal):
    setup = None
    try:
        setup = api.get_senaite_setup()
    except Exception:
        pass

    for entry in ENTRY_FOLDERS:
        _upsert_folder(
            portal,
            object_id=entry["id"],
            title=entry["title"],
            layout=entry["layout"],
        )
        if setup is not None:
            _add_sidebar_folder(setup, entry["id"])

    logger.info("medai.autopublish: entry folders created")


def remove_entry_folders(portal):
    setup = None
    try:
        setup = api.get_senaite_setup()
    except Exception:
        pass

    for entry in ENTRY_FOLDERS:
        folder_id = entry["id"]
        if setup is not None:
            _remove_sidebar_folder(setup, folder_id)

        ids = getattr(portal, "objectIds", lambda: [])()
        if folder_id in ids:
            try:
                portal.manage_delObjects([folder_id])
            except Exception:
                logger.exception(
                    "Failed to remove %s during uninstall", folder_id)


def _add_catalog_indexes():
    """Add department-related indexes to catalogs (idempotent).
    Uses string type names (not class objects) for addIndex compatibility.
    """
    try:
        # Sample catalog: multi-value department_uids index
        sample_cat = api.get_tool("senaite_catalog_sample")
        if "department_uids" not in sample_cat.indexes():
            sample_cat.addIndex("department_uids", "KeywordIndex")
            logger.info("Added department_uids index to sample catalog")

        # Analysis catalog: single-value getDepartmentUID index
        analysis_cat = api.get_tool("senaite_catalog_analysis")
        if "getDepartmentUID" not in analysis_cat.indexes():
            analysis_cat.addIndex("getDepartmentUID", "FieldIndex")
            logger.info("Added getDepartmentUID index to analysis catalog")
    except Exception:
        logger.exception("Failed to add catalog indexes")


def _enable_auto_verify_samples():
    """Enable the Senaite 'Auto Verify Samples' setting so that when
    all analyses of a sample are verified, the sample automatically
    transitions from to_be_verified to verified.
    """
    try:
        setup = api.get_senaite_setup()
        if getattr(setup, "getAutoVerifySamples", lambda: None)():
            logger.info("AutoVerifySamples already enabled")
        else:
            setup.setAutoVerifySamples(True)
            logger.info("AutoVerifySamples enabled")
    except Exception:
        logger.exception("Failed to enable AutoVerifySamples")


def post_install(portal):
    """Bind behaviors + create entry folders + add catalog indexes."""
    _add_behavior_to_fti("Setup", BEHAVIOR)
    _add_behavior_to_fti("Setup", DEPT_FILTER_BEHAVIOR)
    _add_behavior_to_fti("SampleType", AUTO_PUBLISH_BEHAVIOR)
    setup_entry_folders(portal)
    _add_catalog_indexes()
    _enable_auto_verify_samples()
    logger.info("medai.autopublish: post_install complete")


def post_uninstall(portal):
    """Remove behaviors + entry folders."""
    _remove_behavior_from_fti("Setup", BEHAVIOR)
    _remove_behavior_from_fti("Setup", DEPT_FILTER_BEHAVIOR)
    _remove_behavior_from_fti("SampleType", AUTO_PUBLISH_BEHAVIOR)
    remove_entry_folders(portal)
    logger.info("medai.autopublish: post_uninstall complete")


def import_step_handler(context):
    """GenericSetup import step handler for install + uninstall."""
    portal = context.getSite()
    if context.readDataFile(MARKER_FILE) is not None:
        post_install(portal)
    elif context.readDataFile(UNINSTALL_MARKER) is not None:
        post_uninstall(portal)
