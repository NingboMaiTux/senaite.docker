# -*- coding: utf-8 -*-

from bika.lims import api
from senaite.impress.interfaces import ITemplateFinder
from zope.component import getUtility
from zope.interface import implementer
from zope.schema.interfaces import IVocabularyFactory
from zope.schema.vocabulary import SimpleTerm
from zope.schema.vocabulary import SimpleVocabulary


@implementer(IVocabularyFactory)
class INNOCARETemplateVocabulary(object):
    TEMPLATE_NAME_MAP = {
        "DataReport:reportdesign.pt": "DataReport.pt",
        "INNOCARE.reportdesign:DataReport.pt": "DataReport.pt",
        "INNOCARE.reportdesign:reportdesign.pt": "DataReport.pt",
        "reportdesign:reportdesign.pt": "DataReport.pt",
        "reportdesign:coa.pt": "CoaReport.pt",
        "reportdesign:CoaReport.pt": "CoaReport.pt",
        "INNOCARE.reportdesign:CoaReport.pt": "CoaReport.pt",
    }

    def normalize_template_name(self, template_name):
        if not template_name:
            return template_name
        return self.TEMPLATE_NAME_MAP.get(template_name, template_name)

    def get_current_template_values(self):
        values = []

        templates = api.get_registry_record("senaite.impress.templates") or []
        values.extend(templates)

        default_template = api.get_registry_record(
            "senaite.impress.default_template")
        if default_template:
            values.append(default_template)

        mappings = api.get_registry_record(
            "senaite.impress.template_format_mapping") or []
        for mapping in mappings:
            template = mapping.get("template")
            if template:
                values.append(template)

        return values

    def __call__(self, context):
        finder = getUtility(ITemplateFinder)
        templates = finder.get_templates()
        preferred_values = {}

        for current_value in self.get_current_template_values():
            normalized = self.normalize_template_name(current_value)
            if normalized and normalized not in preferred_values:
                preferred_values[normalized] = current_value

        items = []
        for template_name, _path in templates:
            value = preferred_values.get(template_name, template_name)
            items.append(SimpleTerm(value, value, template_name))

        return SimpleVocabulary(items)


TemplateVocabularyFactory = INNOCARETemplateVocabulary()  # noqa
