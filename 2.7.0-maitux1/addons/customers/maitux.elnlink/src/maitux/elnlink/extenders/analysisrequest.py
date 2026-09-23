# -*- coding: utf-8 -*-
"""Sample (AnalysisRequest) fields that name the MaiELN experiment a
sample came from.

The fields are hidden from the add / edit forms on purpose: MaiELN sets
them through the JSON API when it registers the sample, and the
"Source Experiment (MaiELN)" viewlet renders them read-only. Editing
them in the LIMS would break the ELN's reference.
"""
from archetypes.schemaextender.field import ExtensionField
from archetypes.schemaextender.interfaces import IBrowserLayerAwareExtender
from archetypes.schemaextender.interfaces import ISchemaExtender
from bika.lims.interfaces import IAnalysisRequest
from Products.Archetypes.public import StringField
from Products.Archetypes.public import StringWidget
from zope.component import adapts
from zope.interface import implements

from maitux.elnlink import _
from maitux.elnlink.interfaces import IElnLinkLayer

HIDDEN = {"edit": "invisible", "view": "invisible", "add": "invisible"}

# (field name, label)
ELN_FIELDS = (
    ("ELNExperimentNo", u"ELN Experiment No"),
    ("ELNExperimentTitle", u"ELN Experiment Title"),
    ("ELNExperimentURL", u"ELN Experiment URL"),
    ("ELNScientist", u"ELN Scientist"),
    ("ELNDepartment", u"ELN Department"),
    ("ELNProjectCode", u"ELN Project Code"),
    ("ELNSampleURL", u"ELN Sample URL"),
    # MaiRegistration V1.1 section 6: the registered compound / batch this
    # sample tests — stable ids plus the numbers people read. MaiLIMS keeps
    # the reference only; the registry stays the compound authority.
    ("RegCompoundId", u"Registration Compound ID"),
    ("RegCompoundNumber", u"Registration Number"),
    ("RegBatchId", u"Registration Batch ID"),
    ("RegBatchNumber", u"Registration Batch Number"),
    ("RegBatchURL", u"Registration Batch URL"),
)


class StringExtensionField(ExtensionField, StringField):
    pass


def _field(name, label):
    return StringExtensionField(
        name,
        required=False,
        searchable=True,
        schemata="default",
        widget=StringWidget(
            label=_(label),
            description=u"",
            visible=HIDDEN,
            render_own_label=True,
        ),
    )


class ARElnSchemaExtender(object):
    adapts(IAnalysisRequest)
    implements(ISchemaExtender, IBrowserLayerAwareExtender)
    layer = IElnLinkLayer

    fields = [_field(name, label) for name, label in ELN_FIELDS]

    def __init__(self, context):
        self.context = context

    def getFields(self):
        return self.fields
