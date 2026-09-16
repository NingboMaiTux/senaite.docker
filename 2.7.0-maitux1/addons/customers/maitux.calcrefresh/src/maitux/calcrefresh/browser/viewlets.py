# -*- coding: utf-8 -*-
"""Viewlet to inject the per-AS refresh button into manage_results.

The toolbar action only carries the bare @@refresh_calculation URL (no
keyword), which the server now rejects to avoid whole-worksheet recalculations.
This viewlet loads refresh_as.js, which adds a per-AS button to each
as-group-header in the AS-Grouped manage_results table.
"""

from bika.lims import api
from plone.app.layout.viewlets import ViewletBase


class RefreshAsScriptViewlet(ViewletBase):
    """Inject refresh_as.js on worksheet manage_results pages."""

    def available(self):
        try:
            if api.get_portal_type(self.context) != "Worksheet":
                return False
            url = self.request.get("ACTUAL_URL", "") or ""
            return "manage_results" in url
        except Exception:
            return False

    def render(self):
        portal_url = api.get_url(api.get_portal())
        base = "{}/++resource++maitux.calcrefresh.static".format(portal_url)
        css = ('<link rel="stylesheet" type="text/css" '
               'href="{}/refresh_as.css" />'.format(base))
        js = ('<script type="text/javascript" '
              'src="{}/refresh_as.js"></script>'.format(base))
        return css + js
