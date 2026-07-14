# -*- coding: utf-8 -*-

from bika.lims import senaiteMessageFactory as _
from plone.autoform.interfaces import IFormFieldProvider
from plone.supermodel import model
from zope import schema
from zope.interface import provider
from zope.schema.vocabulary import SimpleVocabulary, SimpleTerm


def AutoPublishVocabulary():
    """Vocabulary for auto_publish field."""
    return SimpleVocabulary([
        SimpleTerm(value="disabled", title=_(u"Disabled")),
        SimpleTerm(value="enabled", title=_(u"Enabled")),
    ])


@provider(IFormFieldProvider)
class IAutoPublishBehavior(model.Schema):
    """Behavior that adds auto_publish field to SampleType.
    When enabled, samples of this type will be directly published
    (skip Impress COA generation) on publish action.
    """

    auto_publish = schema.Choice(
        title=_(
            u"title_sampletype_auto_publish",
            default=u"Auto Publish",
        ),
        description=_(
            u"description_sampletype_auto_publish",
            default=u"If enabled, samples of this type will be automatically "
                    u"published without going through the COA report "
                    u"generation step. Leave disabled for normal workflow.",
        ),
        vocabulary=AutoPublishVocabulary(),
        default="disabled",
        required=False,
    )
