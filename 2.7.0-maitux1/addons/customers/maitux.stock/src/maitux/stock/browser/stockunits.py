# -*- coding: utf-8 -*-
import collections

from bika.lims import api
from maitux.stock import stockMessageFactory as _
from bika.lims.utils import get_link
from senaite.app.listing import ListingView
from senaite.core.catalog import SETUP_CATALOG
from senaite.core.i18n import translate
from maitux.stock.i18n import translate_stock


class StockUnitsView(ListingView):
    def __init__(self, context, request):
        super(StockUnitsView, self).__init__(context, request)

        self.catalog = SETUP_CATALOG
        self.contentFilter = {
            "portal_type": "StockUnit",
            "sort_on": "sortable_title",
            "sort_order": "ascending",
            "path": {
                "query": api.get_path(self.context),
                "depth": 1,
            },
        }

        self.context_actions = {
            _(u"Add"): {
                "url": "++add++StockUnit",
                "permission": "cmf.AddPortalContent",
                "icon": "senaite_theme/icon/plus",
            }
        }

        self.title = translate_stock(u"Units")
        self.show_select_column = True

        self.columns = collections.OrderedDict((
            ("Title", {
                "title": _(u"Title"),
                "index": "sortable_title",
            }),
            ("Description", {
                "title": _(u"Description"),
                "toggle": True,
            }),
        ))

        self.review_states = [
            {
                "id": "default",
                "title": _(u"Active"),
                "contentFilter": {"is_active": True},
                "columns": self.columns.keys(),
            }, {
                "id": "inactive",
                "title": _(u"Inactive"),
                "contentFilter": {"is_active": False},
                "columns": self.columns.keys(),
            }, {
                "id": "all",
                "title": _(u"All"),
                "contentFilter": {},
                "columns": self.columns.keys(),
            },
        ]

    def folderitem(self, obj, item, index):
        item = super(StockUnitsView, self).folderitem(obj, item, index)
        obj = api.get_object(obj)
        item["replace"]["Title"] = get_link(
            href=api.get_url(obj),
            value=api.get_title(obj),
            csrf=False,
        )
        return item
