# -*- coding: utf-8 -*-
"""Setup handlers for medai.reportsportal.

Based on the proven patterns from medai.setupdepartmentsaccess and medai.stability:
- Uses post_handler= on GS profile registration (not custom import steps)
- Uses bika.lims.api.create() with temporary_allow_type for folder creation
- post_install / post_uninstall take GS context (not portal)
"""

import logging

try:
    from zope.component.hooks import setSite
except Exception:
    def setSite(site):  # noqa
        return None

try:
    from bika.lims import api
    from senaite.core.upgrade.utils import temporary_allow_type
except ImportError:
    from contextlib import contextmanager
    from bika.lims import api

    @contextmanager
    def temporary_allow_type(container, portal_type):
        yield container

from zope.i18nmessageid import MessageFactory

_ = MessageFactory("medai.reportsportal")

logger = logging.getLogger("medai.reportsportal")

FOLDER_ID = "analysis_reports"
FOLDER_TITLE = _(u"Analysis Reports")
FOLDER_LAYOUT = "@@global_reports_listing"


def _pick_existing_portal_type(portal_types, candidates, fallback=None):
    for portal_type in candidates:
        try:
            if portal_types.get(portal_type) is not None:
                return portal_type
        except Exception:
            continue
    return fallback


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


def _normalize_sidebar_folders(values):
    normalized = []
    for value in values or ():
        if value and value not in normalized:
            normalized.append(value)
    return tuple(normalized)


def _add_sidebar_folder(setup, folder_id):
    current = ()
    try:
        current = setup.getSidebarFolders() or ()
    except Exception:
        current = ()
    updated = _normalize_sidebar_folders(tuple(current) + (folder_id,))
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
    updated = tuple(v for v in _normalize_sidebar_folders(current) if v != folder_id)
    try:
        setup.setSidebarFolders(updated)
    except Exception:
        logger.exception("Failed to clear sidebar folders during uninstall")
        return
    _reindex(setup)


def _create_folder(container, object_id, title):
    """Create a Folder using the proven bika.lims.api.create()+temporary_allow_type pattern."""
    portal_types = api.get_tool("portal_types")
    folder_type = _pick_existing_portal_type(
        portal_types,
        candidates=("Folder",),
        fallback="Folder",
    )
    with temporary_allow_type(container, folder_type) as ct:
        return api.create(ct, folder_type, id=object_id, title=title)


def _upsert_folder(container, object_id, title, layout):
    """Create or update a Folder with given layout (idempotent)."""
    obj = _get_child(container, object_id)
    if obj is None:
        obj = _create_folder(container, object_id, title)
    else:
        _set_title(obj, title)

    _set_layout(obj, layout)
    _set_exclude_from_nav(obj, False)
    _publish(obj)
    _reindex(obj)
    return obj


def get_site_from_context(context):
    get_site = getattr(context, "getSite", None)
    if callable(get_site):
        site = get_site()
        if site is not None:
            return site
    return api.get_portal()


def setup_reports_entry(portal):
    try:
        setSite(portal)
    except Exception:
        pass

    reports = _upsert_folder(
        portal,
        object_id=FOLDER_ID,
        title=FOLDER_TITLE,
        layout=FOLDER_LAYOUT,
    )

    # Restrict visibility: only LabManager and Manager
    try:
        reports.manage_permission(
            "View",
            roles=["LabManager", "Manager"],
            acquire=False,
        )
        reports.reindexObjectSecurity()
        logger.info("medai.reportsportal: restricted View to LabManager/Manager")
    except Exception:
        logger.exception("medai.reportsportal: failed to set View permission")

    try:
        setup = api.get_senaite_setup()
    except Exception:
        setup = None

    if setup is not None:
        _add_sidebar_folder(setup, FOLDER_ID)

    return reports


def remove_reports_entry(portal):
    try:
        setup = api.get_senaite_setup()
    except Exception:
        setup = None

    if setup is not None:
        _remove_sidebar_folder(setup, FOLDER_ID)

    ids = getattr(portal, "objectIds", lambda: [])()
    if FOLDER_ID in ids:
        try:
            portal.manage_delObjects([FOLDER_ID])
        except Exception:
            logger.exception("Failed to remove %s during uninstall", FOLDER_ID)


def post_install(context):
    portal = get_site_from_context(context)
    setup_reports_entry(portal)
    logger.info("medai.reportsportal: installed successfully")


def post_uninstall(context):
    portal = get_site_from_context(context)
    remove_reports_entry(portal)
    logger.info("medai.reportsportal: uninstalled successfully")
