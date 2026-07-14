# -*- coding: utf-8 -*-

import itertools

from bika.lims import _
from bika.lims import api
from bika.lims.browser.workflow import RequestContextAware
from bika.lims.interfaces import IWorkflowActionUIDsAdapter
from bika.lims.workflow import doActionFor
from medai.autopublish.behaviors.auto_publish import IAutoPublishBehavior
from zope.interface import implements


class PublishWithCOACheckAdapter(RequestContextAware):
    """Adapter for 'publish' action in sample listings.
    Routes auto_publish samples directly to published, others to Impress.
    """
    implements(IWorkflowActionUIDsAdapter)

    def __call__(self, action, uids):
        samples = filter(None, map(api.get_object_by_uid, uids))

        # Separate samples by auto_publish setting
        auto_publish_samples = []
        normal_samples = []

        for sample in samples:
            if self._is_auto_publish(sample):
                auto_publish_samples.append(sample)
            else:
                normal_samples.append(sample)

        # Auto-publish samples directly
        for sample in auto_publish_samples:
            doActionFor(sample, "publish")
            self.add_status_message(
                _("Auto-published {}").format(sample.getId()), "info")

        # Normal samples: redirect to Impress publish (COA report creation)
        if normal_samples:
            uids = ",".join(map(api.get_uid, normal_samples))
            portal_url = api.get_url(api.get_portal())
            url = "{}/samples/publish?items={}".format(portal_url, uids)
            return self.redirect(redirect_url=url)

        # Redirect back
        referer = self.request.get_header("referer")
        return self.redirect(redirect_url=referer)

    def _is_auto_publish(self, sample):
        """Check if the sample's SampleType has auto_publish enabled."""
        try:
            sample_type = sample.getSampleType()
        except Exception:
            return False
        if not sample_type:
            return False
        behavior = IAutoPublishBehavior(sample_type, None)
        if behavior is None:
            return False
        return behavior.auto_publish == "enabled"


class PublishSamplesAdapter(RequestContextAware):
    """Adapter for 'publish_samples' action in report listings.
    Handles the case where context is NOT IClient/IAnalysisRequest
    (e.g., analysis_reports Portal Folder).
    """
    implements(IWorkflowActionUIDsAdapter)

    def __call__(self, action, uids):
        published = []

        # Get the selected ARReport objects
        reports = map(api.get_object_by_uid, uids)
        # Get all contained sample UIDs from the reports' metadata
        sample_uids = map(self._get_sample_uids_in_report, reports)
        # Uniquify
        unique_sample_uids = set(list(
            itertools.chain.from_iterable(sample_uids)))

        # Publish all contained samples
        for uid in unique_sample_uids:
            sample = api.get_object_by_uid(uid)
            if self._publish_sample(sample):
                published.append(sample)

        # Status message
        if published:
            message = _("Published {}").format(
                ", ".join(map(api.get_id, published)))
        else:
            message = _("No items published")
        self.add_status_message(message, "info")

        # Redirect back to where the user came from
        referer = self.request.get_header("referer")
        return self.redirect(redirect_url=referer)

    def _get_sample_uids_in_report(self, report):
        """Return a list of contained sample UIDs from report metadata."""
        metadata = report.getMetadata() or {}
        return metadata.get("contained_requests", [])

    def _publish_sample(self, sample):
        """Set status to published/republished based on current state."""
        status = api.get_workflow_status_of(sample)
        transitions = {
            "verified": "publish",
            "report_drafting": "publish_final",
            "published": "republish",
        }
        transition = transitions.get(status, "prepublish")
        succeed, _ = doActionFor(sample, transition)
        return succeed


class PublishSamplesReportDraftingAdapter(PublishSamplesAdapter):
    """Adapter for 'publish_samples' to support report_drafting -> publish_final.
    Registered in overrides.zcml for all contexts (*).
    """
