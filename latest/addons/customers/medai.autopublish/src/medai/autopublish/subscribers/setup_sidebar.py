# -*- coding: utf-8 -*-
"""Subscriber to ensure samples-to-verify and samples-to-approve
stay in sidebar_folders even after Setup is saved via the web form.
"""

from bika.lims import api
from bika.lims import logger


FOLDER_IDS = ("samples-to-verify", "samples-to-approve")
FOLDER_TITLES = {
    "samples-to-verify": u"待审核",
    "samples-to-approve": u"待批准",
}


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


def _ensure_folder_title(portal, folder_id):
    """Ensure the stored folder title matches the expected localized title."""
    title = FOLDER_TITLES.get(folder_id)
    if not title:
        return False
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
    """IObjectModifiedEvent subscriber: ensure samples-to-verify and
    samples-to-approve are always in sidebar_folders."""
    if getattr(obj, "portal_type", None) != "Setup":
        return
    if not hasattr(obj, "getSidebarFolders"):
        return
    try:
        portal = api.get_portal()
    except Exception:
        return

    for folder_id in FOLDER_IDS:
        if folder_id not in portal.objectIds():
            continue
        _ensure_sidebar_folder(obj, folder_id)
        _ensure_folder_title(portal, folder_id)
