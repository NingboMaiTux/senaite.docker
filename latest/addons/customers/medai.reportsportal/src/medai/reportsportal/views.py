# -*- coding: utf-8 -*-
"""Global Analysis Reports listing view.

Extends the standard ReportsListingView to show reports from ALL clients
(instead of being restricted to a single Client context), and adds an
Invalidate custom transition for individual report invalidation.
"""

import collections

from bika.lims import api
from bika.lims import senaiteMessageFactory as _
from bika.lims.browser.publish.reports_listing import ReportsListingView
from senaite.core.catalog import REPORT_CATALOG
from senaite.core.permissions.sample import can_publish
from zope.interface import implementer
from zope.publisher.interfaces import IPublishTraverse


@implementer(IPublishTraverse)
class GlobalReportsListingView(ReportsListingView):
    """Listing view of all generated reports across all Clients.

    Accessible via the sidebar "Analysis Reports" entry.
    """

    def __init__(self, context, request):
        super(GlobalReportsListingView, self).__init__(context, request)

        self.catalog = REPORT_CATALOG

        # Remove path restriction to show reports from ALL clients
        self.contentFilter = {
            "portal_type": ["ResultsReport"],
            "sort_on": "created",
            "sort_order": "descending",
        }

        self.form_id = "global_reports_listing"
        self.title = u"分析报告"

        self.icon = "{}/{}".format(
            self.portal_url,
            "++resource++bika.lims.images/report_big.png"
        )
        self.context_actions = {}
        self.allow_edit = False
        self.show_select_column = True
        self.show_workflow_action_buttons = True
        self.pagesize = 30

        self.columns = collections.OrderedDict((
            ("Info", {
                "title": "",
                "toggle": True},),
            ("AnalysisRequest", {
                "title": _("Primary Sample"),
                "index": "sortable_title"},),
            ("Client", {
                "title": _("Client"),
                "index": "getClientTitle"},),
            ("Batch", {
                "title": _("Batch")},),
            ("State", {
                "title": _("Review State")},),
            ("PDF", {
                "title": _("Download PDF")},),
            ("FileSize", {
                "title": _("Filesize")},),
            ("Date", {
                "title": _("Published Date")},),
            ("PublishedBy", {
                "title": _("Published By")},),
            ("Sent", {
                "title": _("Email sent"),
                "sortable": False},),
            ("SentTo", {
                "title": _("Sent to"),
                "sortable": False},),
        ))

        # ResultsReport uses one_state_workflow (always "active").
        # We filter by the associated sample's review_state in folderitems.
        self.review_states = [
            {
                "id": "default",
                "title": u"报告编写",
                "contentFilter": {},
                "columns": self.columns.keys(),
                "custom_transitions": [],
            },
            {
                "id": "published",
                "title": u"已发布",
                "contentFilter": {},
                "columns": self.columns.keys(),
                "custom_transitions": [],
            },
        ]

    def before_render(self):
        """Before render hook - init custom transitions."""
        super(ReportsListingView, self).before_render()
        self.init_custom_transitions()

    def init_custom_transitions(self):
        """Add custom transitions including Invalidate."""
        custom_transitions = [
            self.custom_transition_download,
        ]
        if can_publish(self.context):
            custom_transitions.append(self.custom_transition_email)
            custom_transitions.append(self.custom_transition_publish)
            custom_transitions.append(self.custom_transition_invalidate)
        # hook in custom transitions
        for state in self.review_states:
            state["custom_transitions"].extend(custom_transitions)

    @property
    def custom_transition_invalidate(self):
        """Custom transition to invalidate reports."""
        return {
            "id": "invalidate_report",
            "title": _("Invalidate"),
            "url": "workflow_action?action=invalidate_report",
            "css_class": "btn btn-outline-danger",
            "help": _("Invalidate the selected reports"),
        }

    def folderitem(self, obj, item, index):
        """Augment folder listing item with Client info.

        Also filters reports by the associated sample's review_state,
        because ResultsReport uses one_state_workflow (always "active").
        """
        item = super(GlobalReportsListingView, self).folderitem(
            obj, item, index)

        obj = api.get_object(obj)
        sample = obj.getSample()

        # Filter by sample state based on active review_state tab
        active_tab = self.review_state["id"]
        if sample:
            sample_state = api.get_workflow_status_of(sample)
            if active_tab == "default" and sample_state != "report_drafting":
                return None
            if active_tab == "published" and sample_state != "published":
                return None
        else:
            # No associated sample, hide
            return None

        if sample:
            client = sample.getClient()
            if client:
                item["Client"] = client.Title()
            else:
                item["Client"] = ""
        else:
            item["Client"] = ""
        return item
