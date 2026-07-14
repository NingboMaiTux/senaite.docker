# -*- coding: utf-8 -*-
"""IListingViewAdapter to filter Analyses by user's department.

When the department filter toggle is enabled in Setup, non-LabManager users
will only see Analyses that belong to their assigned Department(s) inside
the sample detail page (Lab / Field / QC analyses tables).
"""

from senaite.app.listing.interfaces import IListingView
from senaite.app.listing.interfaces import IListingViewAdapter
from zope.component import adapts
from zope.interface import implements


# Class names of analyses tables we want to filter
_ANALYSES_TABLE_CLASSES = {
    "LabAnalysesTable",
    "FieldAnalysesTable",
    "QCAnalysesTable",
}


def _get_user_department_uids():
    """Re-import from samples module to avoid circular imports."""
    from bika.lims import api

    try:
        setup = api.get_senaite_setup()
        if not bool(getattr(setup, "department_filter_enabled", False)):
            return None
    except Exception:
        return None

    try:
        user = api.get_current_user()
    except Exception:
        return None

    roles = user.getRoles()
    if "LabManager" in roles or "Manager" in roles:
        return None

    try:
        contact = api.get_user_contact(user, ["LabContact"])
    except Exception:
        return None
    if not contact:
        return None

    departments = contact.getDepartments()
    if not departments:
        return None

    return [d.UID() for d in departments if d]


class AnalysesDepartmentFilterAdapter(object):
    """Filter Analyses listing by user's department."""
    adapts(IListingView)
    implements(IListingViewAdapter)

    def __init__(self, listing, context):
        self.listing = listing
        self.context = context

    def before_render(self):
        """Add department uid filter to the contentFilter."""
        # Only apply to analyses tables
        cls_name = self.listing.__class__.__name__
        if cls_name not in _ANALYSES_TABLE_CLASSES:
            return

        dept_uids = _get_user_department_uids()
        if dept_uids is not None:
            self.listing.contentFilter["getDepartmentUID"] = dept_uids

    def folder_item(self, obj, item, index):
        """No per-row filtering needed (handled at catalog level)."""
        return item
