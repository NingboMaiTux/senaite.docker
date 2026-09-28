# -*- coding: utf-8 -*-
import collections

from bika.lims import api
from maitux.stock import stockMessageFactory as _
from bika.lims.utils import get_link
from senaite.app.listing import ListingView
from senaite.core.api import dtime
from senaite.core.i18n import translate
from maitux.stock.i18n import translate_stock


class StockPurchaseOrdersView(ListingView):
    def __init__(self, context, request):
        super(StockPurchaseOrdersView, self).__init__(context, request)

        self.catalog = "portal_catalog"
        self.contentFilter = {
            "portal_type": "StockPurchaseOrder",
            "sort_on": "created",
            "sort_order": "descending",
            "path": {
                "query": api.get_path(self.context),
                "depth": 1,
            },
        }

        self.context_actions = {
            _(u"Add"): {
                "url": "++add++StockPurchaseOrder",
                "permission": "cmf.AddPortalContent",
                "icon": "senaite_theme/icon/plus",
            }
        }

        self.title = translate_stock(u"Purchase Orders")
        self.show_select_column = True

        self.columns = collections.OrderedDict((
            ("purchase_order_number", {
                "title": _(u"Order No."),
                "toggle": True,
            }),
            ("purchaser", {
                "title": _(u"Purchaser"),
                "toggle": True,
            }),
            ("order_date", {
                "title": _(u"Order Date"),
                "toggle": True,
            }),
            ("status", {
                "title": _(u"Status"),
                "toggle": True,
            }),
        ))

        self.review_states = [
            {
                "id": "default",
                "title": _(u"All"),
                "contentFilter": {},
                "columns": self.columns.keys(),
            },
        ]

    def folderitem(self, obj, item, index):
        item = super(StockPurchaseOrdersView, self).folderitem(obj, item, index)
        obj = api.get_object(obj)
        po_number = getattr(obj, "purchase_order_number", "") or api.get_title(obj)
        item["purchase_order_number"] = po_number
        item["purchaser"] = getattr(obj, "purchaser", "") or ""
        item["status"] = getattr(obj, "status", "") or ""
        item["order_date"] = self.format_date(getattr(obj, "order_date", None))
        item["replace"]["purchase_order_number"] = get_link(
            href=api.get_url(obj),
            value=po_number,
            csrf=False,
        )
        return item

    def format_date(self, value):
        if not value:
            return ""
        try:
            ansi = dtime.to_ansi(value, show_time=True)
            if not ansi:
                return ""
            return "{}-{}-{} {}:{}:{}".format(
                ansi[0:4], ansi[4:6], ansi[6:8],
                ansi[8:10], ansi[10:12], ansi[12:14],
            )
        except Exception:
            return ""
