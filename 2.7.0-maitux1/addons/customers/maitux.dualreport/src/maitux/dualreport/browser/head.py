# -*- coding: utf-8 -*-
"""Viewlet that injects the dual-format JS into the publish page <head>.

A normal <script src="..."> tag is used instead of the publish.pt inline
custom-JS mechanism, because publish.pt inlines with tal:content (escaped),
which corrupts any JavaScript containing '&', '<' or '>'.
"""
from bika.lims import api
from plone.app.layout.viewlets import ViewletBase
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from maitux.dualreport.config import LOG_PREFIX

# ++plone++ static registration name and file (see configure.zcml)
RESOURCE_NAME = "maitux.dualreport"
JS_FILENAME = "impress_dualformat.js"


class PublishFormatResourcesViewlet(ViewletBase):
    """Renders the <script src> tag in the publish page head."""

    index = ViewPageTemplateFile("templates/publish_format_js.pt")

    def get_script_url(self):
        portal = api.get_portal()
        url = "{}/++plone++{}/{}".format(
            portal.absolute_url(), RESOURCE_NAME, JS_FILENAME)
        return url

    def render(self):
        try:
            return super(PublishFormatResourcesViewlet, self).render()
        except Exception as exc:  # noqa: B902 - never break the page
            import logging
            logging.getLogger(LOG_PREFIX).error(
                "failed to render format JS viewlet: %s" % exc)
            return ""
