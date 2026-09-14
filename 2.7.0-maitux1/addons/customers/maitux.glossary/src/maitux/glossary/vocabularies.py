# -*- coding: utf-8 -*-

from zope.schema.vocabulary import SimpleTerm
from zope.schema.vocabulary import SimpleVocabulary

from maitux.glossary import _
from maitux.glossary.config import STATE_ACTIVE
from maitux.glossary.config import STATE_INACTIVE


def SyncStatesVocabulary(context=None):
    """活跃 / 未激活 —— 由同步维护，人工不选。
    """
    terms = [
        SimpleTerm(STATE_ACTIVE, STATE_ACTIVE, _(u"Active")),
        SimpleTerm(STATE_INACTIVE, STATE_INACTIVE, _(u"Inactive")),
    ]
    return SimpleVocabulary(terms)
