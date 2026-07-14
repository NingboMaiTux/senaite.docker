# -*- coding: utf-8 -*-
"""Behavior that adds report_drafting_enabled toggle to Senaite Setup.

Allows admin to globally enable/disable the report_drafting workflow node
(verified → report_drafting → published).

Field appears in Setup → Sampling tab, alongside SamplingWorkflowEnabled,
AutoReceive, etc.
"""

from bika.lims import senaiteMessageFactory as _
from plone.autoform import directives
from plone.autoform.interfaces import IFormFieldProvider
from plone.supermodel import model
from zope import schema
from zope.interface import provider


@provider(IFormFieldProvider)
class IReportDraftingSetup(model.Schema):
    """Behavior that adds a global Report Drafting toggle to Setup."""

    directives.widget("report_drafting_enabled", fieldset="sampling")
    report_drafting_enabled = schema.Bool(
        title=_(
            u"Enable Report Drafting",
        ),
        description=_(
            u"When enabled, verified samples will enter a 'Report Drafting' "
            u"state before final publication. This allows report drafting "
            u"personnel to prepare the report before LabManager publishes it. "
            u"When disabled, the standard Senaite workflow applies "
            u"(verified → published directly)."
        ),
        default=False,
        required=False,
    )
