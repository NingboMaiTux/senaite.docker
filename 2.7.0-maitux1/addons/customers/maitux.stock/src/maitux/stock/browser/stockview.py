# -*- coding: utf-8 -*-
from Products.Five.browser import BrowserView
from bika.lims import api
from senaite.core.api import dtime
from senaite.core.catalog import SETUP_CATALOG


class StockView(BrowserView):
    @property
    def obj(self):
        return api.get_object(self.context)

    def resolve_by_uid(self, uid):
        if not api.is_uid(uid):
            return None
        for catalog_id in ("uid_catalog", SETUP_CATALOG, "portal_catalog"):
            try:
                catalog = api.get_tool(catalog_id)
                brains = catalog(UID=uid)
                if brains:
                    return api.get_object(brains[0])
            except Exception:
                continue
        return None

    def ref_title(self, fieldname):
        fields = api.get_fields(self.obj)
        field = fields.get(fieldname)
        if not field:
            return u""
        try:
            uid = field.get_raw(self.obj)
        except Exception:
            return u""
        if uid is None:
            return u""
        if not isinstance(uid, (list, tuple)):
            uid = [uid]
        titles = []
        for u in filter(None, uid):
            if api.is_object(u):
                title = api.get_title(u)
            else:
                ref = self.resolve_by_uid(u)
                title = api.get_title(ref) if api.is_object(ref) else u""
            if title:
                # 中文注释：中文标题可能是 utf8 字节串，直接与 unicode 一起 join
                # 时 Py2 会按 ASCII 解码而抛 UnicodeDecodeError（库存详情页 500）。
                titles.append(api.safe_unicode(title))
        return u", ".join(titles)

    def expiry_date(self):
        value = getattr(self.obj, "expiry_date", None)
        if not value:
            return u""
        try:
            ansi = dtime.to_ansi(value, show_time=True)
            if not ansi:
                return u""
            return u"{}-{}-{} {}:{}:{}".format(
                ansi[0:4], ansi[4:6], ansi[6:8],
                ansi[8:10], ansi[10:12], ansi[12:14],
            )
        except Exception:
            return u""
