# -*- coding: utf-8 -*-
"""Manager-only demo endpoints on the site root:

    POST /MaiLIMS/@@eln-demo-seed    -> master data for the integrated demo
    POST /MaiLIMS/@@eln-demo-reset   -> delete the demo samples, rewind ids
    GET  /MaiLIMS/@@eln-demo-status  -> what exists (no changes)

They answer JSON. MaiELN's seed script calls them with the LIMS service
account before it creates its own half of the demo.
"""
import json

from bika.lims import api
from Products.Five.browser import BrowserView

from maitux.elnlink import demo
from maitux.elnlink import logger


class _JsonView(BrowserView):
    require_post = True

    def _json(self, payload, status=200):
        self.request.response.setStatus(status)
        self.request.response.setHeader("Content-Type", "application/json; charset=utf-8")
        return json.dumps(payload, default=str)

    def __call__(self):
        if self.require_post and self.request.get("REQUEST_METHOD") != "POST":
            return self._json({"success": False, "message": "POST required"}, 405)
        try:
            return self._json(dict(self.run(), success=True))
        except Exception as exc:
            logger.exception("elnlink demo view failed")
            return self._json({"success": False, "message": repr(exc)}, 500)


class SeedView(_JsonView):
    def run(self):
        return demo.seed(api.get_portal())


class ResetView(_JsonView):
    def run(self):
        return demo.reset(api.get_portal())


class StatusView(_JsonView):
    require_post = False

    def run(self):
        portal = api.get_portal()
        samples = [api.get_id(s) for s in demo.demo_samples(portal)]
        project = None
        projects = getattr(portal, "projects", None)
        if projects is not None:
            obj = demo._first(projects, "Project", client_project_id=demo.PROJECT_ID)
            project = {"uid": api.get_uid(obj), "url": api.get_url(obj), "title": api.get_title(obj)} if obj else None
        return {"samples": samples, "project": project, "next_sample_id": demo.next_sample_id()}
