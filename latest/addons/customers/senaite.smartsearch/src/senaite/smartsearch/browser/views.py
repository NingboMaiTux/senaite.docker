# -*- coding: utf-8 -*-
import json

from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.smartsearch import search as smartsearch


class SmartSearchPageView(BrowserView):
    """智慧搜索的独立搜索页面。"""

    template = ViewPageTemplateFile("templates/search.pt")

    def __call__(self):
        return self.template()


class SmartSearchAPI(BrowserView):
    """JSON 接口：query 参数 q，返回当前用户权限范围内的搜索结果。"""

    def __call__(self):
        q = self.request.form.get("q", "").strip()
        self.request.response.setHeader("Content-Type", "application/json; charset=utf-8")
        try:
            results = smartsearch.global_search(q)
            return json.dumps({"query": q, "count": len(results), "results": results}, ensure_ascii=False)
        except Exception as e:
            self.request.response.setStatus(500)
            return json.dumps({"error": str(e)}, ensure_ascii=False)
