# -*- coding: utf-8 -*-
from plone.app.layout.viewlets.common import ViewletBase


class SearchBoxViewlet(ViewletBase):
    """渲染在页头的智慧搜索框（templates/searchbox.pt）。
    实际搜索请求由 searchbox.pt 里的 JS 发到 @@smartsearch-api。"""

    def search_url(self):
        return "%s/@@smartsearch" % self.context.absolute_url()
