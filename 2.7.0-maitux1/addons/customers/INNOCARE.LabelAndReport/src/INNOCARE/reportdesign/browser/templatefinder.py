# -*- coding: utf-8 -*-

import os

from senaite.impress.template import TemplateFinder


class INNOCARETemplateFinder(TemplateFinder):
    """Expose friendly names for INNOCARE report templates.

    Keep the internal file lookup compatible with both the old prefixed
    keys and the new short names shown in the UI.
    """

    PROJECT_TEMPLATE_ORDER = [
        "DataReport.pt",
        "CoaReport.pt",
    ]

    PROJECT_TEMPLATE_NAMES = {
        "DataReport.pt": "DataReport.pt",
        "CoaReport.pt": "CoaReport.pt",
    }

    LEGACY_TEMPLATE_NAMES = {
        "DataReport.pt": [
            "DataReport:reportdesign.pt",
            "INNOCARE.reportdesign:DataReport.pt",
            "INNOCARE.reportdesign:reportdesign.pt",
            "reportdesign:reportdesign.pt",
        ],
        "CoaReport.pt": [
            "reportdesign:coa.pt",
            "reportdesign:CoaReport.pt",
            "INNOCARE.reportdesign:CoaReport.pt",
        ],
    }

    def _get_alias(self, key, path):
        filename = os.path.basename(path)
        return self.PROJECT_TEMPLATE_NAMES.get(filename)

    def _get_project_order(self, template_name):
        try:
            return self.PROJECT_TEMPLATE_ORDER.index(template_name)
        except ValueError:
            return len(self.PROJECT_TEMPLATE_ORDER)

    def get_templates(self, extensions=[".pt", ".html"]):
        templates = []
        seen = set()

        for key, path in super(INNOCARETemplateFinder, self).get_templates(
                extensions=extensions):
            template_name = self._get_alias(key, path) or key
            if template_name in seen:
                continue
            seen.add(template_name)
            templates.append((template_name, path))

        def sort_key(item):
            name = item[0]
            if name in self.PROJECT_TEMPLATE_NAMES.values():
                return (0, self._get_project_order(name), name.lower())
            return (1, 999, name.lower())

        return sorted(templates, key=sort_key)

    def find_template(self, name):
        templates = {}

        for key, path in super(INNOCARETemplateFinder, self).get_templates():
            filename = os.path.basename(path)
            alias = self._get_alias(key, path)

            templates[key] = path
            templates[filename] = path

            if alias:
                templates[alias] = path
                for legacy_name in self.LEGACY_TEMPLATE_NAMES.get(alias, []):
                    templates[legacy_name] = path

        return templates.get(name)
