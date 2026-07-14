# -*- coding: utf-8 -*-
"""Subscriber to ensure analysis_reports stays in sidebar_folders
even after Setup is saved via the web form.
"""

from bika.lims import api
from bika.lims import logger


FOLDER_ID = "analysis_reports"
FOLDER_TITLE = u"分析报告"


def _ensure_sidebar_folder(setup, folder_id):
    """Re-add folder_id to sidebar_folders if it was removed."""
    current = ()
    try:
        current = setup.getSidebarFolders() or ()
    except Exception:
        return False

    if folder_id in current:
        return False

    updated = tuple(current) + (folder_id,)
    try:
        setup.setSidebarFolders(updated)
        setup.reindexObject()
        logger.info(
            "setup_sidebar: restored %s to sidebar_folders", folder_id)
        return True
    except Exception:
        logger.exception(
            "setup_sidebar: failed to restore %s", folder_id)
        return False


def _ensure_folder_title(portal, folder_id, title):
    """Ensure the stored folder title matches the expected localized title."""
    try:
        folder = portal[folder_id]
    except Exception:
        return False

    try:
        current = folder.Title()
    except Exception:
        current = None

    if current == title:
        return False

    try:
        folder.setTitle(title)
        folder.reindexObject()
        logger.info("setup_sidebar: updated title for %s", folder_id)
        return True
    except Exception:
        logger.exception("setup_sidebar: failed to update title for %s", folder_id)
        return False


def on_setup_modified(obj, event):
    """IObjectModifiedEvent subscriber: ensure analysis_reports is always
    in sidebar_folders, even after web-form save clears it."""
    if getattr(obj, "portal_type", None) != "Setup":
        return
    if not hasattr(obj, "getSidebarFolders"):
        return
    try:
        portal = api.get_portal()
        if FOLDER_ID not in portal.objectIds():
            return
    except Exception:
        return
    _ensure_sidebar_folder(obj, FOLDER_ID)
    _ensure_folder_title(portal, FOLDER_ID, FOLDER_TITLE)
