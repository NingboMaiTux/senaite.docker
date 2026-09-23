# -*- coding: utf-8 -*-
"""Browser views for maitux.worksheetfilter."""

from senaite.core.browser.modals.sample import CreateWorksheetModal
from senaite.core.api.worksheet import create_worksheet

from bika.lims import api
from bika.lims import senaiteMessageFactory as _


class WorksheetCreateFilterModal(CreateWorksheetModal):
    """Create-worksheet modal that honours the selected Worksheet Template.

    senaite.core's modal collects every unassigned analysis of the selected
    samples and hands them to `create_worksheet()`, which adds them all to the
    new worksheet *before* the template is applied. The template therefore only
    fills layout slots and never restricts what enters the worksheet.

    This subclass is registered in overrides.zcml under the same name, so it
    replaces the stock modal.
    """

    def get_template(self):
        """Return the selected Worksheet Template, or None.

        :returns: WorksheetTemplate object or None
        """
        template_uid = self.request.form.get("template", "")
        if not template_uid:
            return None
        return api.get_object(template_uid, default=None)

    def get_template_services(self):
        """Return the Analysis Service UIDs declared by the selected template.

        Returns an empty list when no template was selected, or when the
        selected template declares no services at all. Callers must tell those
        two cases apart by looking at the request themselves -- an empty list
        here means "no restriction", not "nothing matches".

        :returns: List of Analysis Service UIDs (str)
        """
        template = self.get_template()
        if template is None:
            return []
        # getRawServices() returns the raw uid strings of the services field
        return api.to_list(template.getRawServices())

    def get_selected_categories(self):
        """Return the category UIDs the user selected in the modal.

        :returns: List of AnalysisCategory UIDs (str)
        """
        categories = self.request.form.get("categories", [])
        categories = filter(None, api.to_list(categories))
        # filter out non-UIDs
        return list(filter(api.is_uid, categories))

    def get_template_category_titles(self):
        """Return the titles of the categories the template's services belong to.

        The template declares Analysis *Services*, not categories, so the
        category has to be read back from each service.

        :returns: Sorted list of category titles (unicode)
        """
        titles = set()
        for service_uid in self.get_template_services():
            service = api.get_object(service_uid, default=None)
            if service is None:
                continue
            category = service.getCategory()
            if category is None:
                continue
            titles.add(api.safe_unicode(api.get_title(category)))
        return sorted(titles)

    def get_selected_category_titles(self):
        """Return the titles of the categories the user selected.

        :returns: Sorted list of category titles (unicode)
        """
        titles = set()
        for category_uid in self.get_selected_categories():
            category = api.get_object(category_uid, default=None)
            if category is None:
                continue
            titles.add(api.safe_unicode(api.get_title(category)))
        return sorted(titles)

    def get_analyses(self):
        """Return the analyses that should enter the new worksheet.

        Stock behaviour is kept for the categories filter; the template is
        applied on top of it, so selecting both yields their intersection.

        Analyses already assigned to another worksheet are left out. Stock
        `get_analyses()` keeps them and lets `create_worksheet()` reject them
        one by one via `addAnalysis()`, which is fine when nothing depends on
        the result -- but `handle_submit()` uses "no analyses" to mean "the
        selection matches nothing", and an already-assigned analysis can never
        enter the worksheet. Leaving them in would make that check miss the
        case "every service of the template is already assigned", and an empty
        worksheet would be created silently.
        """
        categories = self.get_selected_categories()

        # Analysis Services declared by the selected template. Empty means
        # "no template selected" or "template declares no services" -- in both
        # cases we do not restrict by template here (handle_submit() rejects
        # the second case before anything is created).
        template_services = self.get_template_services()

        analyses = []
        for sample in self.get_selected_samples():
            if sample is None:
                continue
            for analysis in sample.getAnalyses(full_objects=True):
                # if categories not empty then skip analyses that do not belong
                # to the selected categories
                if categories and analysis.getRawCategory() not in categories:
                    continue
                # if a template with services is selected, only keep analyses
                # whose Analysis Service is declared by that template
                if template_services:
                    service_uid = analysis.getRawAnalysisService()
                    if service_uid not in template_services:
                        continue
                # skip analyses that already belong to another worksheet --
                # create_worksheet() would reject them anyway
                if self.is_assigned(analysis):
                    continue
                analyses.append(analysis)
        return analyses

    def get_template_analyses_on_samples(self):
        """Return the analyses on the selected samples that match the template.

        Unlike `get_analyses()` this ignores the categories filter -- it answers
        "which of the template's services exist on these samples at all", which
        is what the error messages need to tell "the categories do not overlap"
        apart from "everything is already assigned to another worksheet".

        :returns: List of Analysis objects
        """
        template_services = self.get_template_services()
        if not template_services:
            return []
        analyses = []
        for sample in self.get_selected_samples():
            for analysis in sample.getAnalyses(full_objects=True):
                if analysis.getRawAnalysisService() in template_services:
                    analyses.append(analysis)
        return analyses

    def is_assigned(self, analysis):
        """Return True if the analysis already belongs to a worksheet.

        Same test `create_worksheet()` uses before calling `addAnalysis()`.

        :returns: bool
        """
        ws_uid = analysis.getWorksheetUID()
        return all([ws_uid, api.is_uid(ws_uid)])

    def get_missing_template_services(self, analyses):
        """Return the titles of the template's services absent from `analyses`.

        A template declares Analysis *Services*, but a sample may not carry an
        analysis for every one of them -- the sample was created with a
        different set of analyses, or some were removed. The worksheet is still
        created with whatever matched, so the user has to be told what did not
        make it in; otherwise a partial result looks like a full one.

        :param analyses: the analyses that entered the worksheet
        :returns: Sorted list of service titles (unicode)
        """
        template_services = self.get_template_services()
        if not template_services:
            return []
        present = set()
        for analysis in analyses:
            present.add(analysis.getRawAnalysisService())
        missing = []
        for service_uid in template_services:
            if service_uid in present:
                continue
            service = api.get_object(service_uid, default=None)
            if service is None:
                continue
            missing.append(api.safe_unicode(api.get_title(service)))
        return sorted(missing)

    def handle_submit(self, REQUEST=None):
        """Validate the selection, then create the worksheet.

        The stock implementation hands the analyses straight to
        `create_worksheet()`, which only ever returns None when no analyst was
        given -- so an empty intersection would silently produce an empty
        worksheet. The checks below run *before* anything is created.
        """
        analyst = self.request.form.get("analyst")
        template = self.request.form.get("template", "")
        instrument = self.request.form.get("instrument", "")

        # No analyst: keep stock behaviour (create_worksheet() returns None and
        # the modal is re-rendered).
        if not analyst:
            return self.template()

        template_obj = self.get_template()

        # A template was selected but declares no services: it cannot restrict
        # anything, so creating a worksheet would silently fall back to
        # "everything goes in" -- exactly the behaviour this addon removes.
        if template_obj is not None and not self.get_template_services():
            self.add_status_message(
                _(u"worksheetfilter_template_without_services",
                  default=u"The selected template \"${template}\" declares no "
                          u"analysis services, so it cannot be used to create "
                          u"a worksheet. Please pick another template or "
                          u"select the analyses by category.",
                  mapping={"template": api.safe_unicode(
                      api.get_title(template_obj))}),
                level="error")
            return self.template()

        analyses = self.get_analyses()

        # Nothing would enter the worksheet. There are two distinct reasons and
        # they need different messages -- telling a user "the categories do not
        # overlap" when both sides actually name the same category is worse
        # than saying nothing.
        if template_obj is not None and not analyses:
            template_title = api.safe_unicode(api.get_title(template_obj))
            on_samples = self.get_template_analyses_on_samples()
            # "already assigned" only when the template's services DO exist on
            # the samples but every one of them is taken. If some are free, the
            # reason nothing matched is the categories filter, not assignment.
            if on_samples and all(self.is_assigned(a) for a in on_samples):
                self.add_status_message(
                    _(u"worksheetfilter_all_assigned",
                      default=u"All analyses of template \"${template}\" on the "
                              u"selected samples are already assigned to other "
                              u"worksheets, so there is nothing left to add. "
                              u"Please release them first or pick another "
                              u"template.",
                      mapping={"template": template_title}),
                    level="error")
            else:
                # The template's services are not on the samples at all, or the
                # categories filter excluded them. Name both sides.
                self.add_status_message(
                    _(u"worksheetfilter_empty_intersection",
                      default=u"No analysis matches the current selection. "
                              u"Template \"${template}\" covers the categories: "
                              u"${template_categories}. You selected: "
                              u"${selected_categories}. Please adjust your "
                              u"selection.",
                      mapping={
                          "template": template_title,
                          "template_categories": u", ".join(
                              self.get_template_category_titles()) or u"-",
                          "selected_categories": u", ".join(
                              self.get_selected_category_titles()) or u"-",
                      }),
                    level="error")
            return self.template()

        ws = create_worksheet(analyst=analyst, instrument=instrument,
                              template=template, analyses=analyses)

        if not ws:
            return self.template()
        message = _(
            u"worksheet_created",
            default=u"Created worksheet ${ws_id}",
            mapping={"ws_id": ws.getId()},
        )
        self.add_status_message(message)

        # The worksheet was created, but the template may only be partially
        # covered: a sample does not necessarily carry an analysis for every
        # service the template declares. Say so -- a silent partial success is
        # the hardest kind to notice, and this addon exists precisely to stop
        # the system from quietly doing something other than what was asked.
        if template_obj is not None:
            missing = self.get_missing_template_services(analyses)
            if missing:
                self.add_status_message(
                    _(u"worksheetfilter_partial_template",
                      default=u"Template \"${template}\" declares ${total} "
                              u"analysis services, but ${missing_count} of them "
                              u"are not on the selected samples and were not "
                              u"added: ${missing}. The worksheet was created "
                              u"with the remaining ${added_count}.",
                      mapping={
                          "template": api.safe_unicode(
                              api.get_title(template_obj)),
                          "total": len(self.get_template_services()),
                          "missing_count": len(missing),
                          "added_count": len(analyses),
                          "missing": u", ".join(missing),
                      }),
                    level="warning")

        # redirect to the new worksheet
        return api.get_url(ws)
