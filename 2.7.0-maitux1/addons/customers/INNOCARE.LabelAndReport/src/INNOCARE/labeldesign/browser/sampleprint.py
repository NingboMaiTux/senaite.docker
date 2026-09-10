# -*- coding: utf-8 -*-
# ADD(2026-08-21) - 样品标签打印视图。
# 供 Sample / AnalysisRequest 选择多个 uids 后打印样品标签（④⑤）。
# 复用 maitux.stock 的 stockbatchprint 渲染+PDF 机制，模板目录在 sample/。
import os

from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from bika.lims import api as bika_api
from bika.lims.utils import createPdf
from plone.resource.utils import queryResourceDirectory
from Products.CMFPlone.utils import safe_unicode
from senaite.app.supermodel import SuperModel


class SampleLabelPrintView(BrowserView):
    def _value(self, obj, attr, default=None):
        value = getattr(obj, attr, default)
        if callable(value):
            try:
                return value()
            except TypeError:
                return default
        return value

    def _schema_field(self, obj, fieldname):
        schema = self._value(obj, "Schema")
        if schema is None:
            return None
        getter = getattr(schema, "getField", None)
        if not callable(getter):
            return None
        try:
            return getter(fieldname)
        except Exception:
            return None

    def _format_date(self, value):
        if not value:
            return ""
        if hasattr(value, "strftime"):
            try:
                return value.strftime("%Y-%m-%d")
            except Exception:
                pass
        for attr in ("ISO", "asdatetime"):
            method = getattr(value, attr, None)
            if callable(method):
                try:
                    converted = method()
                    if attr == "ISO":
                        return converted.split(" ")[0]
                    if hasattr(converted, "strftime"):
                        return converted.strftime("%Y-%m-%d")
                except Exception:
                    continue
        return bika_api.safe_unicode(value)

    def get_analysis_request(self, item):
        if callable(getattr(item, "getDateReceived", None)):
            return item
        for attr in ("getAnalysisRequest", "getRequest", "getRequestInstance"):
            ar = self._value(item, attr)
            if ar:
                return ar
        parent = getattr(item, "aq_parent", None)
        if parent and callable(getattr(parent, "getDateReceived", None)):
            return parent
        return item

    def get_batch_title(self, item):
        batch = self._value(item, "getBatch")
        if batch is None:
            return ""
        return self._value(batch, "Title", "") or self._value(batch, "getId", "") or ""

    def get_project_no(self, item):
        ar = self.get_analysis_request(item)
        field = self._schema_field(ar, "ProjectNo")
        project = None
        if field is not None:
            raw_getter = getattr(field, "getRaw", None)
            if callable(raw_getter):
                try:
                    project = raw_getter(ar)
                except Exception:
                    project = None
        if not project:
            project = self._value(ar, "getProject")
        if not project:
            return ""
        return self._value(project, "getId", "") or self._value(project, "Title", "") or ""

    def get_sent_sample_time(self, item):
        ar = self.get_analysis_request(item)
        date_value = self._value(ar, "getDateReceived")
        if not date_value:
            date_value = getattr(ar, "DateReceived", None)
        return self._format_date(date_value)

    def get_date_sampled(self, item):
        date_value = self._value(item, "getDateSampled")
        if not date_value:
            date_value = getattr(item, "DateSampled", None)
        if not date_value:
            ar = self.get_analysis_request(item)
            date_value = self._value(ar, "getDateSampled") or getattr(ar, "DateSampled", None)
        return self._format_date(date_value)

    def get_sampling_point_title(self, item):
        point = getattr(item, "SamplingPoint", None) or self._value(item, "getSamplePoint")
        if point is None:
            ar = self.get_analysis_request(item)
            point = getattr(ar, "SamplingPoint", None) or self._value(ar, "getSamplePoint")
        if not point:
            return ""
        return self._value(point, "Title", "") or self._value(point, "getId", "") or ""

    def __call__(self):
        if self.request.form.get("pdf", "0") == "1":
            response = self.request.response
            response.setHeader("Content-type", "application/pdf")
            response.setHeader("Content-Disposition", "inline")
            response.setHeader("filename", "sample-sticker.pdf")
            return self.pdf_from_post()
        return self.index()

    def get_uids(self):
        uids = self.request.get("uids", "")
        if isinstance(uids, (list, tuple)):
            uids = ",".join(uids)
        uids = [u.strip() for u in bika_api.safe_unicode(uids).split(",") if u.strip()]
        uids = filter(bika_api.is_uid, uids)
        return list(uids)

    def get_items(self):
        uids = self.get_uids()
        return list(map(lambda uid: SuperModel(uid), uids))

    def get_selected_template(self):
        template_id = self.request.get("template", "")
        if template_id:
            return template_id
        return "INNOCARE.LabelAndReport:SampleNormal_40x30mm.pt"

    def get_available_templates(self):
        return [
            {"id": "INNOCARE.LabelAndReport:SampleNormal_40x30mm.pt",
             "title": "样品标签 (Sample Normal)", "selected": False},
            {"id": "INNOCARE.LabelAndReport:SampleStability_40x30mm.pt",
             "title": "样品标签·稳定性 (Sample Stability)", "selected": False},
        ]

    def _get_templates_dir(self, prefix):
        templates_dir = queryResourceDirectory("stickers", prefix).directory
        return templates_dir

    def get_selected_template_css(self):
        template = self.get_selected_template()
        if ":" not in template:
            return ""
        prefix, filename = template.split(":", 1)
        templates_dir = self._get_templates_dir(prefix)
        css_path = os.path.join(templates_dir, "{}.css".format(filename[:-3]))
        if not os.path.isfile(css_path):
            return ""
        with open(css_path, "r") as content_file:
            return content_file.read()

    def render_sticker(self, item):
        self.current_item = item
        template = self.get_selected_template()
        if ":" not in template:
            return ""
        prefix, filename = template.split(":", 1)
        fullpath = os.path.join(self._get_templates_dir(prefix), filename)
        embed = ViewPageTemplateFile(fullpath)
        return embed(
            self,
            item=item,
            batch_title=self.get_batch_title(item),
            project_no=self.get_project_no(item),
            sent_sample_time=self.get_sent_sample_time(item),
            date_sampled=self.get_date_sampled(item),
            sampling_point=self.get_sampling_point_title(item),
        )

    def render_stickers(self):
        html = []
        for item in self.get_items():
            html.append("<div class='sticker'>{}</div>".format(self.render_sticker(item)))
        return "<div class='stickers'>{}</div>".format("".join(html))

    def pdf_from_post(self):
        html = self.request.form.get("html")
        style = self.request.form.get("style")
        reporthtml = "<html><head>{0}</head><body>{1}</body></html>"
        reporthtml = reporthtml.format(style, html)
        reporthtml = safe_unicode(reporthtml).encode("utf-8")
        pdf_fn = os.path.join(os.path.dirname(__file__), "sample-sticker.pdf")
        pdf_file = createPdf(htmlreport=reporthtml, outfile=pdf_fn)
        return pdf_file
