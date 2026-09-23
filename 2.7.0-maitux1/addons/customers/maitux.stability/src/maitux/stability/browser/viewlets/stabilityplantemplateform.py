# -*- coding: utf-8 -*-
from bika.lims import api
from plone.app.layout.viewlets import ViewletBase
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from maitux.stability.i18n import translate_stability


class StabilityPlanTemplateFormViewlet(ViewletBase):
    index = ViewPageTemplateFile("templates/stabilityplantemplate_form.pt")

    def available(self):
        try:
            url = self.request.get("ACTUAL_URL", "") or ""
            if "++add++StabilityPlanTemplate" in url:
                return True
            if "++add++StabilityPlan" in url:
                return True
            return api.get_portal_type(self.context) in (
                "StabilityPlanTemplate",
                "StabilityPlan",
            )
        except Exception:
            return False

    def get_labels(self):
        """模板里 JS 用到的界面文案（英文 msgid -> 当前语言）。

        中文注释：这段模板是纯 ``<script>``（没有可加 ``i18n:translate``
        的元素），所以译文挂在 ``<script>`` 自己的 ``data-msg-*`` 上，
        由 JS 读取 —— 硬编码任何一种语言都会让另一种语言显示错。
        """
        return {
            "basic-information": translate_stability(u"Basic Information"),
        }

    def render(self):
        try:
            if not self.available():
                return ""
            return self.index()
        except Exception:
            return ""
