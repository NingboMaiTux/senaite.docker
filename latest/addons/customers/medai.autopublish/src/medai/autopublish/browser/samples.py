# -*- coding: utf-8 -*-

from bika.lims import api
from Products.Five import BrowserView
from senaite.core.browser.samples.view import SamplesView


def _is_department_filter_enabled():
    """Check if the department filter toggle is enabled in Setup."""
    try:
        setup = api.get_senaite_setup()
        return bool(getattr(setup, "department_filter_enabled", False))
    except Exception:
        return False


def _get_user_department_uids():
    """Return department UIDs for the current user's LabContact.

    Returns None if the user is not linked to a LabContact or has no
    departments assigned, or if the department filter is disabled.
    """
    if not _is_department_filter_enabled():
        return None

    try:
        user = api.get_current_user()
    except Exception:
        return None

    # LabManager and Manager see everything
    roles = user.getRoles()
    if "LabManager" in roles or "Manager" in roles:
        return None

    try:
        contact = api.get_user_contact(user, ["LabContact"])
    except Exception:
        return None
    if not contact:
        return None

    departments = contact.getDepartment()
    if not departments:
        return None

    return [d.UID() for d in departments if d]


class SamplesViewWithAnalysesNum(SamplesView):
    """Samples listing with getAnalysesNum column enabled by default
    and report_drafting state included in the Active tab.
    Shows three-number format: To verify / Verified / Total.
    Department filtering: non-LabManager users see only samples
    that have analyses in their department(s).
    """

    def __init__(self, context, request):
        super(SamplesViewWithAnalysesNum, self).__init__(context, request)

        # Enable the getAnalysesNum column and update title
        if "getAnalysesNum" in self.columns:
            self.columns["getAnalysesNum"]["toggle"] = True
            self.columns["getAnalysesNum"]["alt"] = u"待审核 / 已审核 / 总数"

        # Add report_drafting to the default (Active) review state filter
        for rs in self.review_states:
            if rs["id"] == "default":
                states = list(rs["contentFilter"]["review_state"])
                if "report_drafting" not in states:
                    states.append("report_drafting")
                    rs["contentFilter"]["review_state"] = tuple(states)
                break

        # Apply department filter (non-LabManager users see only their
        # department's samples)
        self._apply_department_filter()

    def _apply_department_filter(self):
        """Restrict listing to samples that have analyses in the user's
        department(s).  LabManager and Manager are NOT filtered.
        """
        dept_uids = _get_user_department_uids()
        if dept_uids is not None:
            self.contentFilter["department_uids"] = dept_uids

    def folderitem(self, obj, item, index):
        item = super(SamplesViewWithAnalysesNum, self).folderitem(
            obj, item, index)
        if not item:
            return None

        # Three-number format: to_be_verified / verified / total
        # Use api.get_object to get live data, not cached catalog metadata
        real_obj = api.get_object(obj)
        analysesnum = real_obj.getAnalysesNum() if real_obj else None
        if analysesnum:
            # analysesnum = [verified, total, not_submitted, to_be_verified]
            verified = analysesnum[0]
            total = analysesnum[1]
            to_verify = analysesnum[3]
            item["getAnalysesNum"] = "{}/{}/{}".format(
                to_verify, verified, total)
            item["replace"]["getAnalysesNum"] = (
                '<span class="text-state-to_be_verified">{}</span>'
                '<span class="separator">/</span>'
                '<span class="text-state-verified">{}</span>'
                '<span class="separator">/</span>'
                '<span class="text-black">{}</span>'
            ).format(to_verify, verified, total)

        return item


class SamplesToVerifyView(SamplesViewWithAnalysesNum):
    """Samples listing for Verifier: only samples with analyses to verify.

    Catalog filter: sample_received + to_be_verified
    Folderitem filter: to_be_verified > 0 and verified != total
    """

    def __init__(self, context, request):
        super(SamplesToVerifyView, self).__init__(context, request)
        self.title = u"待审核"
        self.contentFilter["review_state"] = (
            "sample_received", "to_be_verified")

        # Hide the Add button
        self.context_actions = {}

        # Override all review_states tabs: only Verifier-relevant states
        verify_states = ("sample_received", "to_be_verified")
        for rs in self.review_states:
            rs["contentFilter"]["review_state"] = verify_states
            if rs["id"] == "default":
                rs["title"] = u"待审核"

    def folderitem(self, obj, item, index):
        item = super(SamplesToVerifyView, self).folderitem(obj, item, index)
        if not item:
            return None

        # Use api.get_object for live data, not cached catalog metadata
        real_obj = api.get_object(obj)
        analysesnum = real_obj.getAnalysesNum() if real_obj else None
        if not analysesnum:
            return None

        verified = analysesnum[0]
        total = analysesnum[1]
        to_be_verified = analysesnum[3]

        # Exclude samples with no pending verifications
        if to_be_verified == 0:
            return None
        # Exclude samples where all analyses are already verified
        if verified == total:
            return None

        return item


class SamplesToApproveView(SamplesViewWithAnalysesNum):
    """Samples listing for LabManager: only samples ready for approval.

    Catalog filter: to_be_verified
    Folderitem filter: verified == total
    """

    def __init__(self, context, request):
        super(SamplesToApproveView, self).__init__(context, request)
        self.title = u"待批准"
        self.contentFilter["review_state"] = ("to_be_verified",)

        # Hide the Add button
        self.context_actions = {}

        # Override all review_states tabs: only to_be_verified
        approve_states = ("to_be_verified",)
        for rs in self.review_states:
            rs["contentFilter"]["review_state"] = approve_states
            if rs["id"] == "default":
                rs["title"] = u"待批准"

    def folderitem(self, obj, item, index):
        item = super(SamplesToApproveView, self).folderitem(obj, item, index)
        if not item:
            return None

        # Use api.get_object for live data, not cached catalog metadata
        real_obj = api.get_object(obj)
        analysesnum = real_obj.getAnalysesNum() if real_obj else None
        if not analysesnum:
            return None

        verified = analysesnum[0]
        total = analysesnum[1]

        # Only include samples where all analyses are verified
        if verified != total:
            return None

        return item


def _ensure_portal_folder(folder_id, title, layout):
    """Lazily create a Portal Folder with given layout and add to sidebar."""
    portal = api.get_portal()
    if folder_id in portal.objectIds():
        return portal.get(folder_id)

    from senaite.core.upgrade.utils import temporary_allow_type

    portal_types = api.get_tool("portal_types")
    fti = portal_types.get("Folder")
    if fti is None:
        return None
    with temporary_allow_type(portal, "Folder") as ct:
        folder = api.create(ct, "Folder", id=folder_id, title=title)

    try:
        folder.setLayout(layout)
    except Exception:
        folder.layout = layout

    try:
        from plone import api as plone_api
        if plone_api.content.get_state(obj=folder) != "published":
            plone_api.content.transition(obj=folder, transition="publish")
    except Exception:
        pass
    folder.reindexObject()

    # Restrict View permissions on role-specific folders
    _FOLDER_VIEW_ROLES = {
        "samples-to-verify": ("Verifier", "LabManager", "Manager"),
        "samples-to-approve": ("LabManager", "Manager"),
    }
    if folder_id in _FOLDER_VIEW_ROLES:
        folder.manage_permission(
            "View",
            roles=_FOLDER_VIEW_ROLES[folder_id],
            acquire=False,
        )
        folder.reindexObjectSecurity()

    try:
        setup = api.get_senaite_setup()
        current = list(setup.getSidebarFolders() or ())
        if folder_id not in current:
            current.append(folder_id)
            setup.setSidebarFolders(tuple(current))
            setup.reindexObject()
    except Exception:
        pass

    return folder


class RedirectToSamplesToVerify(BrowserView):
    """Redirect to /samples/@@samples-to-verify.
    Lazily creates Portal Folder on first access.
    """

    def __call__(self):
        _ensure_portal_folder(
            "samples-to-verify",
            u"待审核",
            "@@redirect-samples-to-verify",
        )
        portal = api.get_portal()
        url = "{}/samples/@@samples-to-verify".format(
            portal.absolute_url())
        self.request.response.redirect(url, status=302)
        return ""


class RedirectToSamplesToApprove(BrowserView):
    """Redirect to /samples/@@samples-to-approve.
    Lazily creates Portal Folder on first access.
    """

    def __call__(self):
        _ensure_portal_folder(
            "samples-to-approve",
            u"待批准",
            "@@redirect-samples-to-approve",
        )
        portal = api.get_portal()
        url = "{}/samples/@@samples-to-approve".format(
            portal.absolute_url())
        self.request.response.redirect(url, status=302)
        return ""


class FixFolderPermissionsView(BrowserView):
    """One-time view to fix View permissions on all three Portal Folders."""

    _FIXES = [
        ("analysis_reports", ["LabManager", "Manager"]),
        ("samples-to-verify", ["Verifier", "LabManager", "Manager"]),
        ("samples-to-approve", ["LabManager", "Manager"]),
    ]

    def __call__(self):
        portal = api.get_portal()
        results = []
        for folder_id, roles in self._FIXES:
            if folder_id not in portal.objectIds():
                results.append("SKIP {} (not found)".format(folder_id))
                continue
            try:
                obj = portal.get(folder_id)
                obj.manage_permission("View", roles=roles, acquire=False)
                obj.reindexObjectSecurity()
                results.append("OK {} -> View: {}".format(folder_id, roles))
            except Exception as e:
                results.append("ERR {}: {}".format(folder_id, str(e)))
        return "<br/>".join(results)
