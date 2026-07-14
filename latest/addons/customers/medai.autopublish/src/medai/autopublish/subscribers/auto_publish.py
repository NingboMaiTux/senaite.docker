# -*- coding: utf-8 -*-

from bika.lims import api
from bika.lims import logger
from bika.lims.utils import changeWorkflowState
from medai.autopublish.behaviors.auto_publish import IAutoPublishBehavior
from senaite.core.workflow import SAMPLE_WORKFLOW


def after_verify(instance, event):
    """Subscriber for IAfterTransitionEvent on AnalysisRequest (sample).
    When a sample transitions via 'verify', checks if its SampleType has
    auto_publish enabled and if so, directly publishes it (skip 'verified').
    """
    if instance.portal_type != "AnalysisRequest":
        return

    transition_id = None
    if event.transition is not None:
        transition_id = getattr(event.transition, "id", None)
        if transition_id is None:
            transition_id = getattr(event.transition, "getId", lambda: None)()

    logger.info(
        "auto_publish subscriber: sample=%s state=%s transition=%s",
        instance.getId(),
        getattr(instance, "review_state", "?"),
        transition_id,
    )

    if transition_id != "verify":
        return

    # Skip if already published (prevents re-entry from changeWorkflowState)
    current_state = api.get_workflow_status_of(instance)
    if current_state == "published":
        logger.info("auto_publish: %s already published, skipping", instance.getId())
        return

    try:
        sample_type = instance.getSampleType()
    except Exception:
        logger.warning("auto_publish: getSampleType failed for %s", instance.getId())
        return

    if not sample_type:
        return

    # Read auto_publish via behavior adapter (correct way for plone.behavior)
    behavior = IAutoPublishBehavior(sample_type, None)
    if behavior is None:
        logger.info("auto_publish: %s behavior not bound on SampleType %s",
                     instance.getId(), sample_type.Title())
        return

    auto_publish = behavior.auto_publish
    logger.info(
        "auto_publish: sample=%s SampleType=%s auto_publish=%s",
        instance.getId(),
        sample_type.Title(),
        auto_publish,
    )

    if auto_publish != "enabled":
        return

    logger.info("Auto-publishing %s (%s)", instance.getId(), sample_type.Title())

    changeWorkflowState(
        instance,
        SAMPLE_WORKFLOW,
        "published",
        action="publish",
        trigger_events=True,
    )
