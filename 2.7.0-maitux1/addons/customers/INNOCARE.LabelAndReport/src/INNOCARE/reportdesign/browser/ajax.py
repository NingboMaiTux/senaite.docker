# -*- coding: utf-8 -*-

from senaite.impress.ajax import AjaxPublishView


class INNOCAREAjaxPublishView(AjaxPublishView):
    """Normalize configured template keys before sending them to the UI."""

    TEMPLATE_NAME_MAP = {
        "DataReport:reportdesign.pt": "DataReport.pt",
        "INNOCARE.reportdesign:DataReport.pt": "DataReport.pt",
        "INNOCARE.reportdesign:reportdesign.pt": "DataReport.pt",
        "reportdesign:reportdesign.pt": "DataReport.pt",
        "reportdesign:coa.pt": "CoaReport.pt",
        "reportdesign:CoaReport.pt": "CoaReport.pt",
        "INNOCARE.reportdesign:CoaReport.pt": "CoaReport.pt",
    }

    PROJECT_TEMPLATE_ORDER = [
        "DataReport.pt",
        "CoaReport.pt",
    ]

    def normalize_template_name(self, template_name):
        if not template_name:
            return template_name
        return self.TEMPLATE_NAME_MAP.get(template_name, template_name)

    def _sort_templates(self, templates):
        def sort_key(name):
            if name in self.PROJECT_TEMPLATE_ORDER:
                return (0, self.PROJECT_TEMPLATE_ORDER.index(name), name.lower())
            return (1, 999, name.lower())

        return sorted(templates, key=sort_key)

    def get_report_templates(self):
        templates = super(INNOCAREAjaxPublishView, self).get_report_templates()
        normalized = []
        seen = set()

        for template in templates:
            name = self.normalize_template_name(template)
            if name in seen:
                continue
            seen.add(name)
            normalized.append(name)

        return self._sort_templates(normalized)

    def get_default_template(self, default="senaite.lims:Default.pt"):
        template = super(INNOCAREAjaxPublishView, self).get_default_template(
            default=default)
        return self.normalize_template_name(template)

    def get_template_format_mapping(self):
        mapping = super(INNOCAREAjaxPublishView, self).get_template_format_mapping()
        normalized = {}

        for template, paperformat in mapping.items():
            normalized[self.normalize_template_name(template)] = paperformat

        return normalized
