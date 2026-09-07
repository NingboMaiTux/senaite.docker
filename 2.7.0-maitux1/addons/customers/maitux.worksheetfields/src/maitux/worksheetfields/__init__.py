# -*- coding: utf-8 -*-
"""maitux.worksheetfields

Worksheet header multi-select extension:
- multi-valued Instruments (new field, replaces the original single-select)
- multi-valued Stock Batches from the maitux.stock module (new field)

The original single-select Instrument field/UI and the "instrument
acquisition" entry on the Worksheet manage results page are hidden.
"""

from zope.i18nmessageid import MessageFactory

worksheetfieldsMessageFactory = MessageFactory('maitux.worksheetfields')


def initialize(context):
    """Zope 2 product initialization hook"""
    return
