from archetypes.schemaextender.field import ExtensionField
from archetypes.schemaextender.interfaces import ISchemaExtender
from bika.lims.interfaces import IClient
from Products.Archetypes.public import StringField
from Products.Archetypes.public import StringWidget
from zope.component import adapts
from zope.interface import implements
from zope.i18nmessageid import MessageFactory

_ = MessageFactory("maitux.clientcompany")


class StringExtensionField(ExtensionField, StringField):
    """String field for schema extension."""


class ClientSchemaExtender(object):
    adapts(IClient)
    implements(ISchemaExtender)

    fields = [
        StringExtensionField(
            "Company",
            required=False,
            searchable=True,
            schemata="default",
            widget=StringWidget(
                label=_(u"Company"),
                description=_(u"Company name for this client."),
            ),
        ),
    ]

    def __init__(self, context):
        self.context = context

    def getFields(self):
        return self.fields
