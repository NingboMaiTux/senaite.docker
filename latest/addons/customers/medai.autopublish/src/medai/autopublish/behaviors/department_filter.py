# -*- coding: utf-8 -*-
"""Behavior that adds department_filter_enabled toggle to Senaite Setup.

Toggles department-based filtering of Samples list and Analyses list.
"""

from bika.lims import senaiteMessageFactory as _
from plone.autoform import directives
from plone.autoform.interfaces import IFormFieldProvider
from plone.supermodel import model
from zope import schema
from zope.interface import provider


@provider(IFormFieldProvider)
class IDepartmentFilterSetup(model.Schema):
    """Behavior that adds a Department Filter toggle to Setup."""

    directives.widget("department_filter_enabled", fieldset="sampling")
    department_filter_enabled = schema.Bool(
        title=_(
            u"Enable Department Filtering",
        ),
        description=_(
            u"When enabled, non-LabManager users will only see Samples and "
            u"Analyses that belong to their assigned Department(s) in "
            u"Lab Contacts. LabManager and Manager always see everything. "
            u"Disable this for small labs where everyone works together."
        ),
        default=False,
        required=False,
    )
