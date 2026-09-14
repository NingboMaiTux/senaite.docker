# -*- coding: utf-8 -*-

from plone.supermodel import model
from senaite.core.interfaces import ISenaiteCore
from zope import schema
from zope.interface import Interface
from zope.publisher.interfaces.browser import IDefaultBrowserLayer

from maitux.glossary import _


class IGlossaryLayer(ISenaiteCore, IDefaultBrowserLayer):
    """Browser layer for maitux.glossary.

    The package registers nothing against foreign (senaite/bika/plone)
    interfaces, so this layer is not used for gating (rules R14). It is
    declared to keep the door open should such a registration be needed later.
    """


class IGlossaryEntries(Interface):
    """Marker interface for the middle table container.
    """


class IGlossaryEntry(Interface):
    """Marker interface for one row of the middle table.

    A row is one combination ``(analysis_keyword, calc_keyword)``.
    """


class IGlossaryEntriesSchema(model.Schema):
    """Schema for the middle table container. Intentionally empty.
    """


class IGlossaryEntrySchema(model.Schema):
    """Schema for one middle table row.

    注意：**没有** ``translation_status`` 字段 —— 原先的"翻译进度"列已按需求移除。
    ``zh`` / ``en`` 都**默认为空**，由人工填写；同步不会从站点回填中文名。
    """

    analysis_keyword = schema.TextLine(
        title=_(u"Analysis Keyword"),
        description=_(
            u"Keyword of the Analysis Service this row belongs to. "
            u"Part of the row key; written by the sync and never changed."
        ),
        required=True,
    )

    calc_keyword = schema.TextLine(
        title=_(u"calc keyword"),
        description=_(
            u"Keyword of the Calculation interim field (the 'Keyword' column "
            u"on the Calculation edit page). Part of the row key."
        ),
        required=True,
    )

    category = schema.TextLine(
        title=_(u"Analysis category"),
        description=_(u"Analysis category of the Analysis Service."),
        required=False,
    )

    zh = schema.TextLine(
        title=_(u"zh"),
        description=_(
            u"Chinese name of the formula field. Empty by default - filled "
            u"in by hand. Editing it applies to every row of the same calc "
            u"keyword."
        ),
        required=False,
    )

    en = schema.TextLine(
        title=_(u"en"),
        description=_(
            u"English name of the formula field. Empty by default - filled "
            u"in by hand. Editing it applies to every row of the same calc "
            u"keyword."
        ),
        required=False,
    )

    sync_state = schema.Choice(
        title=_(u"State"),
        description=_(
            u"Whether the combination still exists on the site. Maintained "
            u"by the sync; the only field the sync is allowed to change on an "
            u"existing row."
        ),
        vocabulary=u"maitux.glossary.vocabularies.SyncStates",
        required=True,
        default=u"active",
    )

    first_seen = schema.Datetime(
        title=_(u"First seen"),
        description=_(u"When the sync appended this row."),
        required=False,
    )

    state_changed_on = schema.Datetime(
        title=_(u"State changed on"),
        description=_(
            u"When the sync set the current state. Written only when the row "
            u"is created or its state changes - existing rows are never "
            u"touched otherwise."
        ),
        required=False,
    )

    last_sync_by = schema.TextLine(
        title=_(u"Last sync by"),
        description=_(
            u"Who triggered the sync that wrote or re-stated this row. The "
            u"write itself is performed with elevated privileges, so this is "
            u"the only attribution available."
        ),
        required=False,
    )

    note = schema.Text(
        title=_(u"Note"),
        required=False,
    )
