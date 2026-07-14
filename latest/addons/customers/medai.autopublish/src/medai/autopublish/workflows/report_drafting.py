# -*- coding: utf-8 -*-
"""Event subscriber that transitions verified samples to report_drafting
when an ARReport (ResultsReport) is created via Impress Save.

Only fires when the Report Drafting workflow is globally enabled in Setup.
"""

from bika.lims import api
from bika.lims import logger
from bika.lims.workflow import doActionFor
from Products.CMFCore.WorkflowCore import WorkflowException


def _is_report_drafting_enabled():
    """Check if Report Drafting workflow is globally enabled in Setup."""
    try:
        setup = api.get_senaite_setup()
        if setup is None:
            return False
        return getattr(setup, "report_drafting_enabled", False)
    except Exception:
        return False


def _get_contained_sample_uids(report):
    """Extract contained sample UIDs from report metadata or parent.

    The Impress publish action stores contained_requests in the report's
    metadata. These are the UIDs of samples whose results are included in
    the report.

    Falls back to the report's acquisition parent if metadata is empty
    (e.g. when report was created via ajax_save_reports in Impress).
    """
    try:
        metadata = report.getMetadata() or {}
    except Exception:
        metadata = {}

    uids = metadata.get("contained_requests", [])
    uids = uids if isinstance(uids, (list, tuple)) else []

    # Fallback: use acquisition parent (the sample the report lives in)
    if not uids:
        try:
            parent = report.aq_parent
            parent_pt = getattr(parent, "portal_type", "")
            if parent_pt == "AnalysisRequest":
                parent_uid = api.get_uid(parent)
                if parent_uid:
                    uids = [parent_uid]
                    logger.info(
                        "report_drafting: resolved sample %s from parent",
                        parent.getId())
        except Exception:
            pass

    return uids


def _ensure_partition_reports(sample_uids):
    """Cascade report_drafting transition to partition descendants and create
    minimal ResultsReport objects so they appear in the Analysis Reports listing.
    """
    for uid in sample_uids:
        try:
            sample = api.get_object_by_uid(uid)
        except Exception:
            continue
        if sample is None:
            continue

        descendants = sample.getDescendants(all_descendants=False)
        for partition in descendants:
            try:
                state = api.get_workflow_status_of(partition)
            except Exception:
                continue

            if state != "verified":
                # Already in report_drafting or not yet verified; skip
                continue

            # Transition partition to report_drafting
            try:
                doActionFor(partition, "submit_for_report")
            except WorkflowException:
                continue

            # Create a minimal ResultsReport so it shows in the listing
            _create_partition_results_report(partition)


def _create_partition_results_report(partition):
    """Create a minimal ResultsReport object inside a partition AR
    so the Analysis Reports portal can list it.
    """
    report_id = api.create(
        partition,
        "ResultsReport",
        title=u"{} Report".format(partition.getId()),
        description=u"Auto-generated for partition {}".format(partition.getId()),
        sample=partition.UID(),
        Pdf=None,
    )
    logger.info(
        "report_drafting: created ResultsReport %s for partition %s",
        report_id, partition.getId())


def on_arreport_created(report, event):
    """Subscriber: when a ResultsReport is created, check if Report Drafting
    is globally enabled AND any associated samples are in 'verified' state,
    then transition them to 'report_drafting'.

    This only fires for auto_publish=Disabled samples because:
    - auto_publish=Enabled samples are published directly (skip Impress),
      so no ARReport is created via Impress at the verified stage.
    """
    # Diagnostic: log every call to verify subscriber is loaded
    try:
        pt = report.portal_type
    except Exception:
        pt = "?"
    logger.info(
        "report_drafting: subscriber called for portal_type=%s id=%s",
        pt, getattr(report, "getId", lambda: "?")())

    # Guard 1: global setup switch must be ON
    if not _is_report_drafting_enabled():
        logger.info("report_drafting: skipped - global switch is OFF")
        return

    # Guard 2: only handle ResultsReport type
    try:
        portal_type = report.portal_type
    except Exception:
        return

    if portal_type != "ResultsReport":
        logger.info(
            "report_drafting: skipped - wrong portal_type=%s", portal_type)
        return

    # Get associated sample UIDs from report metadata
    sample_uids = _get_contained_sample_uids(report)
    if not sample_uids:
        logger.warning(
            "report_drafting: no contained_requests in report %s metadata",
            report.getId())
        return

    logger.info(
        "report_drafting: found %d sample UIDs in report %s",
        len(sample_uids), report.getId())

    # Transition verified samples to report_drafting
    for uid in sample_uids:
        try:
            sample = api.get_object_by_uid(uid)
            if sample is None:
                continue
        except Exception:
            logger.warning(
                "report_drafting: could not resolve sample uid {}".format(uid))
            continue

        try:
            status = api.get_workflow_status_of(sample)
        except Exception:
            continue

        if status != "verified":
            continue

        logger.info(
            "report_drafting: transitioning {} from verified to report_drafting"
            .format(sample.getId()))
        try:
            doActionFor(sample, "submit_for_report")
        except Exception as e:
            logger.error(
                "report_drafting: failed to transition {}: {}".format(
                    sample.getId(), e))

    # Cascade submit_for_report to partition descendants and create
    # ResultsReport placeholders for them so they appear in Analysis Reports.
    _ensure_partition_reports(sample_uids)
