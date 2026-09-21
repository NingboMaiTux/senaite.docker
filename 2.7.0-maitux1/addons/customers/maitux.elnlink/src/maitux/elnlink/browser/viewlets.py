# -*- coding: utf-8 -*-
"""The "Source Experiment (MaiELN)" card on a sample that came from MaiELN
(the LIMS -> ELN deep link, spec section 11 / 22)."""
from bika.lims import api
from plone.app.layout.viewlets import ViewletBase
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from maitux.elnlink import ELN_PUBLIC_URL


class SourceExperimentViewlet(ViewletBase):
    index = ViewPageTemplateFile("templates/source_experiment.pt")

    def _get(self, name):
        try:
            field = self.context.getField(name)
            if field is None:
                return u""
            value = field.get(self.context)
            return value or u""
        except Exception:
            return u""

    def available(self):
        try:
            return api.get_portal_type(self.context) == "AnalysisRequest" and bool(self._get("ELNExperimentNo"))
        except Exception:
            return False

    def experiment_url(self):
        url = self._get("ELNExperimentURL")
        if url:
            return url
        return "%s/?experiment=%s" % (ELN_PUBLIC_URL.rstrip("/"), self._get("ELNExperimentNo"))

    def sample_url(self):
        url = self._get("ELNSampleURL")
        if url:
            return url
        return "%s/?sample=%s" % (ELN_PUBLIC_URL.rstrip("/"), api.get_id(self.context))

    def project_title(self):
        try:
            field = self.context.getField("ProjectNo")
            project = field.get(self.context) if field is not None else None
            project = api.get_object(project) if project else None
            return api.get_title(project) if project else self._get("ELNProjectCode")
        except Exception:
            return self._get("ELNProjectCode")

    def data(self):
        return {
            "experiment_no": self._get("ELNExperimentNo"),
            "experiment_title": self._get("ELNExperimentTitle"),
            "scientist": self._get("ELNScientist"),
            "department": self._get("ELNDepartment"),
            "project_code": self._get("ELNProjectCode"),
            "project": self.project_title(),
            "experiment_url": self.experiment_url(),
            "sample_url": self.sample_url(),
        }

    def render(self):
        if not self.available():
            return u""
        return self.index()
