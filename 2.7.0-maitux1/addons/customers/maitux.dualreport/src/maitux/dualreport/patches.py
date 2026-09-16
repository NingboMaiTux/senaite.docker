# -*- coding: utf-8 -*-
"""Monkey-patches that teach senaite.impress how to handle a Word output.

Patched targets (each kept minimal, original logic is preserved for the PDF
flow):

1. ``senaite.impress.publishview.PublishView.download``
   honours ``report_format=word`` (download / print Word documents).

2. ``senaite.impress.ajax.AjaxPublishView.ajax_save_reports``
   stores the selected format (PDF or Word) when reports are saved.

3. ``senaite.impress.storage.PdfReportStorageAdapter.create_report``
   names the stored blob and sets its content-type according to the actual
   format (Word files are stored inside the existing ResultsReport.pdf field,
   which is just a NamedBlobFile field).

4. ``bika.lims.browser.publish.downloadview.DownloadView.__call__``
   downloads already-saved reports with the correct filename / content-type
   (a stored Word file must not be delivered as "*.pdf").

5. ``bika.lims.browser.publish.reports_listing.ReportsListingView.folderitem``
   labels a stored Word report as "Word" instead of "PDF" in the listing.

The patches are applied when the package is imported (same pattern as
maitux.calcenhance) and are idempotent.
"""
from maitux.dualreport import config as cfg
from maitux.dualreport.config import logger

# Registry of patched (class, attribute-name) pairs.
#
# NOTE: do NOT mark patched methods via setattr() on the method object.
# In Python 2 a plain function assigned to a class attribute comes back as an
# *unbound method* (instancemethod) when looked up on the class, and
# instancemethod objects do not allow attribute assignment.
_PATCHED = set()


def _is_patched(klass, attr):
    return (klass, attr) in _PATCHED


def _mark_patched(klass, attr):
    _PATCHED.add((klass, attr))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _report_file_info(blob, fallback_name=u"report"):
    """Return (filename, content_type) for a stored report blob.

    The ResultsReport.pdf field holds whichever format was saved (PDF or
    Word). Some upstream code paths assume PDF and hardcode "*.pdf" plus
    "application/pdf" - and even mutate ``blob.filename``, which Zope then
    persists. This helper derives both values from the blob itself so every
    download (toolbar action, file link, email attachment) serves the real
    format, and it self-heals blobs whose filename was renamed to "*.pdf"
    by the old code.
    """
    content_type = (getattr(blob, "contentType", "") or "").strip()
    filename = getattr(blob, "filename", "") or ""
    if isinstance(filename, str):
        filename = filename.decode("utf-8", "ignore")
    filename = unicode(filename)

    base = filename
    if "." in base:
        base = base.rsplit(".", 1)[0]
    if not base:
        base = unicode(fallback_name or u"report")
    lower = base.lower()

    ctype = content_type.lower()
    if "wordprocessingml" in ctype:
        if not lower.endswith(".docx"):
            base += ".docx"
        return base, content_type or cfg.MIMETYPE_WORD
    if ctype.startswith("application/pdf") or ctype == cfg.MIMETYPE_PDF:
        if not lower.endswith(".pdf"):
            base += ".pdf"
        return base, content_type or cfg.MIMETYPE_PDF
    # unknown content type: keep the stored name
    return (filename or (base + ".pdf")), (content_type or cfg.MIMETYPE_PDF)


def _format_value(value):
    """Normalize a report_format parameter to 'pdf' or 'word'."""
    value = (value or cfg.DEFAULT_FORMAT)
    if isinstance(value, str):
        value = value.decode("utf-8", "ignore")
    value = unicode(value).strip().lower()
    if value not in cfg.SUPPORTED_FORMATS:
        value = cfg.DEFAULT_FORMAT
    return value


def is_word_template(template):
    """True when the given impress template is allowed to produce Word.

    Word output is restricted to the CoA template - every other template is
    served as PDF (same rule the front-end dropdown applies, enforced here so
    a hand crafted request cannot bypass it).
    """
    from maitux.dualreport.docx import coa
    return coa.is_coa_template(template)


def _effective_format(value, template):
    """Requested format, downgraded to PDF for templates without Word support.
    """
    report_format = _format_value(value)
    if report_format == cfg.FORMAT_WORD and not is_word_template(template):
        logger.warn(
            "maitux.dualreport: Word output is limited to the CoA template "
            "(requested template=%r), falling back to PDF" % (template,))
        return cfg.FORMAT_PDF
    return report_format


def _language():
    """Best-effort detection of the request language ('zh' | 'en')."""
    try:
        from bika.lims import api
        request = api.get_request()
        lang = request.get("LANGUAGE", "") or ""
        if unicode(lang).lower().startswith("zh"):
            return "zh"
    except Exception:  # noqa: B902
        pass
    return "en"


def make_url_fetcher():
    """Return a callable url -> bytes for local portal image URLs.

    Mirrors what WeasyPrint's url_fetcher does for senaite.impress, so Word
    documents can embed the same images (logos, signatures, attachments).
    External/unknown URLs return None (the image is skipped with a warning).
    """
    def fetch(url):
        if not url or url.startswith("data:"):
            return None
        try:
            from bika.lims import api
            from plone.subrequest import subrequest

            request = api.get_request()
            portal = api.get_portal()
            path = "/".join(request.physicalPathFromURL(url))
            context = portal.restrictedTraverse(path, None)
            if context is None:
                return None
            response = subrequest(path)
            return response.getBody()
        except Exception as exc:  # noqa: B902
            logger.warn(
                "maitux.dualreport: cannot fetch image URL '%s': %s"
                % (url, exc))
            return None
    return fetch


def _conversion_kwargs(view, paperformat, orientation):
    """Build the keyword arguments for html_to_docx from a publish view."""
    paperformat = paperformat or view.get_default_paperformat()
    orientation = orientation or view.get_default_orientation() or "portrait"
    dims = view.calculate_dimensions(paperformat, orientation)
    return {
        "page_width_mm": dims.get("page_width"),
        "page_height_mm": dims.get("page_height"),
        "margin_top_mm": dims.get("margin_top"),
        "margin_right_mm": dims.get("margin_right"),
        "margin_bottom_mm": dims.get("margin_bottom"),
        "margin_left_mm": dims.get("margin_left"),
        "orientation": orientation,
        "language": _language(),
        "fetch_url": make_url_fetcher(),
    }


def _docx_bytes(view, html, paperformat, orientation, template=None):
    """Generate the Word document for the given report HTML.

    For the CoaReport template the laboratory's own Word template is filled
    with the report values; every other template uses the generic HTML->docx
    converter.
    """
    from maitux.dualreport.docx import coa
    if coa.is_coa_template(template):
        data = coa.build_coa_docx(html)
        if data:
            return data
        logger.warn("maitux.dualreport: CoA Word generation failed, "
                    "falling back to the generic converter")

    from maitux.dualreport.docx.builder import html_to_docx
    kwargs = _conversion_kwargs(view, paperformat, orientation)
    return html_to_docx(html, **kwargs)


# ---------------------------------------------------------------------------
# 1) PublishView.download (download / print Word)
# ---------------------------------------------------------------------------
def patch_download():
    from senaite.impress.publishview import PublishView
    if _is_patched(PublishView, "download"):
        return
    original = PublishView.download

    def download(self):
        request = self.request
        form = request.form
        template = form.get("template")
        # Word is only served for the CoA template - everything else stays PDF
        report_format = _effective_format(form.get("report_format"), template)
        if report_format != cfg.FORMAT_WORD:
            # plain PDF flow (unchanged)
            return original(self)

        from bika.lims import api
        html = api.safe_unicode(form.get("html", ""))
        paperformat = form.get("format")
        orientation = form.get("orientation", "portrait")

        filename = form.get("filename", template or "report")
        if isinstance(filename, str):
            filename = filename.decode("utf-8", "ignore")
        if filename.lower().endswith(".pdf"):
            filename = filename[:-4]
        filename = api.safe_unicode(filename)

        logger.info("maitux.dualreport: generating Word document for download")
        data = _docx_bytes(self, html, paperformat, orientation,
                           template=template)

        disposition = "attachment; filename=%s.%s" % (filename,
                                                       cfg.EXTENSION_WORD)
        request.response.setHeader("Content-Disposition", disposition)
        request.response.setHeader("Content-Type", cfg.MIMETYPE_WORD)
        request.response.setHeader("Content-Length", len(data))
        request.response.setHeader("Cache-Control", "no-store")
        request.response.setHeader("Pragma", "no-cache")
        request.response.write(data)

    PublishView.download = download
    _mark_patched(PublishView, "download")


# ---------------------------------------------------------------------------
# 2) AjaxPublishView.ajax_save_reports (save with selected format)
# ---------------------------------------------------------------------------
def patch_ajax_save_reports():
    from senaite.impress.ajax import AjaxPublishView
    if _is_patched(AjaxPublishView, "ajax_save_reports"):
        return
    original = AjaxPublishView.ajax_save_reports

    def ajax_save_reports(self):
        """Render all reports and store them in the selected format."""
        data = self.get_json()
        html = data.get("html")
        # triggered action (save|email)
        action = data.get("action", "save")
        template = data.get("template")
        paperformat = data.get("format")
        orientation = data.get("orientation", "portrait")
        # Word is only produced for the CoA template (server side guard)
        report_format = _effective_format(data.get("report_format"), template)
        # Emails always use PDF (Word emailing is out of scope)
        if action == "email":
            report_format = cfg.FORMAT_PDF

        from bika.lims import api
        from DateTime import DateTime
        from senaite.impress.interfaces import IPdfReportStorage
        from senaite.impress.interfaces import IReportWrapper
        from zope.component import getMultiAdapter

        timestamp = DateTime().ISO()

        # Generate the print CSS with the set format/orientation
        css = self.get_print_css(paperformat=paperformat,
                                 orientation=orientation)
        logger.info(u"Print CSS: {}".format(css))

        # get the publisher instance
        publisher = self.publisher
        publisher.add_inline_css(css)

        # split the html per report
        html_reports = publisher.parse_reports(html)
        report_uids = map(
            lambda report: report.get("uids", "").split(","), html_reports)

        # get the storage multi-adapter to save the generated reports
        storage = getMultiAdapter(
            (self.context, self.request), IPdfReportStorage)

        report_groups = []
        for html_node, uids in zip(html_reports, report_uids):
            # ensure we have valid UIDs here
            uids = filter(api.is_uid, uids)
            # convert the bs4.Tag back to pure HTML
            node_html = publisher.to_html(html_node)

            if report_format == cfg.FORMAT_WORD:
                logger.info(
                    "maitux.dualreport: generating Word report for %s UIDs"
                    % len(list(uids)))
                data = _docx_bytes(self, node_html, paperformat, orientation,
                                   template=template)
                metadata = {
                    "template": template,
                    "paperformat": paperformat,
                    "orientation": orientation,
                    "timestamp": timestamp,
                    "contained_requests": list(uids),
                    "format": cfg.FORMAT_WORD,
                }
                objs = storage.store(data, node_html, uids,
                                     metadata=metadata)
            else:
                # classic PDF path - identical to senaite.impress
                report = getMultiAdapter(
                    (node_html,
                     map(self.to_model, uids),
                     template,
                     paperformat,
                     orientation,
                     None,
                     publisher), interface=IReportWrapper)
                metadata = report.get_metadata(
                    contained_requests=uids, timestamp=timestamp)
                metadata["format"] = cfg.FORMAT_PDF
                objs = storage.store(report.pdf, node_html, uids,
                                     metadata=metadata)
            report_groups.append(objs)

        exit_urls = map(lambda reports: self.get_exit_url_for(
            reports, action=action), report_groups)

        if not exit_urls:
            return api.get_url(self.context)

        # Group the urls by path (same logic as senaite.impress)
        groups = {}
        for url in exit_urls:
            base_path, uids = url.split("?uids=")
            path_uids = groups.get(base_path, "")
            groups[base_path] = ",".join(
                filter(None, [path_uids, uids]))
        return "?uids=".join(groups.items()[0])

    AjaxPublishView.ajax_save_reports = ajax_save_reports
    _mark_patched(AjaxPublishView, "ajax_save_reports")


# ---------------------------------------------------------------------------
# 3) storage adapter: name blob + content-type according to actual format
# ---------------------------------------------------------------------------
def patch_create_report():
    from senaite.impress.storage import PdfReportStorageAdapter
    if _is_patched(PdfReportStorageAdapter, "create_report"):
        return
    original = PdfReportStorageAdapter.create_report

    def _detect_format(data):
        """Detect pdf/word from magic bytes when no hint is present."""
        if data:
            if data[:4] == "%PDF":
                return cfg.FORMAT_PDF
            if data[:2] == "PK":  # docx is a zip container
                return cfg.FORMAT_WORD
        return cfg.DEFAULT_FORMAT

    def create_report(self, parent, pdf, html, uids, metadata):
        """Create a new report object (same as upstream, but stores the blob
        with the correct filename and content-type for the actual format).
        """
        from bika.lims import api
        from plone.namedfile.file import NamedBlobFile

        metadata = metadata or {}
        fmt = unicode(metadata.get("format") or "").strip().lower()
        if fmt not in cfg.SUPPORTED_FORMATS:
            fmt = _detect_format(pdf)

        parent_id = api.get_id(parent)
        logger.info(
            "maitux.dualreport: create %s report for %s ..." % (fmt,
                                                                parent_id))

        # Manually update the view on the database to avoid conflict errors
        parent._p_jar.sync()

        if fmt == cfg.FORMAT_WORD:
            filename = "{}.{}".format(parent_id, cfg.EXTENSION_WORD)
            content_type = cfg.MIMETYPE_WORD
        else:
            filename = "{}.{}".format(parent_id, cfg.EXTENSION_PDF)
            content_type = cfg.MIMETYPE_PDF

        blob = NamedBlobFile(
            data=pdf,
            filename=api.safe_unicode(filename),
            contentType=content_type,
        )

        report = api.create(
            parent,
            "ResultsReport",
            sample=api.get_uid(parent),
            contained_samples=uids if uids else [],
            pdf=blob,
            metadata=metadata if metadata else {})

        logger.info("Create Report for {} [DONE]".format(parent_id))
        return report

    PdfReportStorageAdapter.create_report = create_report
    _mark_patched(PdfReportStorageAdapter, "create_report")


# ---------------------------------------------------------------------------
# 4) download of stored reports keeps correct filename/content-type
# ---------------------------------------------------------------------------
def patch_downloadview():
    from bika.lims.browser.publish.downloadview import DownloadView
    if _is_patched(DownloadView, "__call__"):
        return
    original = DownloadView.__call__

    def __call__(self):
        from bika.lims import api
        report = self.context
        blob = report.getPdf()
        if blob is None:
            filename = "{}.pdf".format(api.get_id(report))
            self.download("", filename)
            return

        filename, content_type = _report_file_info(
            blob, fallback_name=api.get_id(report))

        is_pdf = content_type == cfg.MIMETYPE_PDF or \
            content_type.startswith("application/pdf")
        disposition = "inline" if is_pdf else "attachment"
        self.request.response.setHeader(
            "Content-Disposition", "%s; filename=%s" % (disposition, filename))
        self.request.response.setHeader("Content-Type", content_type)
        self.request.response.setHeader("Content-Length", len(blob.data))
        self.request.response.setHeader("Cache-Control", "no-store")
        self.request.response.setHeader("Pragma", "no-cache")
        self.request.response.write(blob.data)

    DownloadView.__call__ = __call__
    _mark_patched(DownloadView, "__call__")


# ---------------------------------------------------------------------------
# 4b) "Download" toolbar action of the reports listing (workflow action)
# ---------------------------------------------------------------------------
def patch_workflow_download_reports():
    """Serve the stored report file (PDF *or* Word) from the toolbar action.

    The upstream adapter hardcodes "*.pdf" / "application/pdf" and mutates
    the persistent blob filename (``pdf.filename = "...pdf"``) - because Zope
    commits every request, that rename is persisted and afterwards even the
    file link serves a wrongly named file.
    """
    from bika.lims.browser.workflow.client import \
        WorkflowActionDownloadReportsAdapter
    if _is_patched(WorkflowActionDownloadReportsAdapter, "__call__"):
        return

    def __call__(self, action, uids):
        import tempfile
        import zipfile
        from bika.lims import api
        from DateTime import DateTime
        from bika.lims import bikaMessageFactory as _b

        reports = map(api.get_object_by_uid, uids)
        files = []
        for report in reports:
            sample = report.getAnalysisRequest()
            sample_id = api.get_id(sample)
            blob = self.get_pdf(report)
            if blob is None:
                self.add_status_message(
                    _b("Could not load report for sample {}"
                       .format(sample_id)), "warning")
                continue
            filename, content_type = _report_file_info(
                blob, fallback_name=sample_id)
            files.append((filename, blob.data, content_type))

        if len(files) == 1:
            filename, data, content_type = files[0]
            return self.download(data, filename, type=content_type)

        # several reports -> ZIP archive with the real file names
        archive = tempfile.NamedTemporaryFile(suffix=".zip")
        with zipfile.ZipFile(archive.name, "w", zipfile.ZIP_DEFLATED) as zf:
            for filename, data, _content_type in files:
                zf.writestr(filename, data)
        archive_name = "Reports-{}.zip".format(
            DateTime().strftime("%Y%m%d_%H%M%S"))
        data = archive.file.read()
        return self.download(data, archive_name, type="application/zip")

    WorkflowActionDownloadReportsAdapter.__call__ = __call__
    _mark_patched(WorkflowActionDownloadReportsAdapter, "__call__")

    # the upstream download() appends "; charset=utf-8" to every content
    # type, which is wrong for binary payloads (docx/pdf/zip)
    if not _is_patched(WorkflowActionDownloadReportsAdapter, "download"):
        def download(self, data, filename, type="application/zip"):
            response = self.request.response
            response.setHeader(
                "Content-Disposition",
                "attachment; filename={}".format(filename))
            response.setHeader("Content-Type", type)
            response.setHeader("Content-Length", len(data))
            response.setHeader("Cache-Control", "no-store")
            response.setHeader("Pragma", "no-cache")
            response.write(data)

        WorkflowActionDownloadReportsAdapter.download = download
        _mark_patched(WorkflowActionDownloadReportsAdapter, "download")


# ---------------------------------------------------------------------------
# 4c) email attachments use the real file name (pdf vs docx)
# ---------------------------------------------------------------------------
def patch_email_report_filename():
    from bika.lims.browser.publish.emailview import EmailView
    if _is_patched(EmailView, "get_report_filename"):
        return

    def get_report_filename(self, report):
        from bika.lims import api
        try:
            blob = report.getPdf()
        except Exception:  # noqa: B902
            blob = None
        sample = report.getAnalysisRequest()
        sample_id = api.get_id(sample)
        if blob is None:
            return "{}.pdf".format(sample_id)
        filename, _content_type = _report_file_info(
            blob, fallback_name=sample_id)
        return filename

    EmailView.get_report_filename = get_report_filename
    _mark_patched(EmailView, "get_report_filename")


# ---------------------------------------------------------------------------
# 5) reports listing: label stored Word reports correctly
# ---------------------------------------------------------------------------
def patch_reports_listing():
    from bika.lims.browser.publish.reports_listing import ReportsListingView
    if _is_patched(ReportsListingView, "folderitem"):
        return
    original = ReportsListingView.folderitem

    def folderitem(self, obj, item, index):
        item = original(self, obj, item, index)
        try:
            from bika.lims import api
            from bika.lims.utils import get_link
            report = api.get_object(obj)
            blob = report.getPdf()
            if blob and blob.contentType \
                    and "wordprocessingml" in (blob.contentType or ""):
                url = "{}/download_pdf".format(report.absolute_url())
                item["replace"]["PDF"] = get_link(
                    url, value="Word", target="_blank")
        except Exception:  # noqa: B902 - never break the listing
            logger.warn("maitux.dualreport: could not tag Word report row")
        return item

    ReportsListingView.folderitem = folderitem
    _mark_patched(ReportsListingView, "folderitem")


# ---------------------------------------------------------------------------
# 6) report date formatting + "Published by" identity
# ---------------------------------------------------------------------------
def patch_reportview_dates():
    """Render report dates with an explicit, locale-independent format.

    The site's Chinese translation catalog translates the date-format
    msgids ("date_format_long", ...) to the literal label "长日期格式"
    instead of a date pattern, so any zh-CN render prints that text instead
    of the actual date - in the PDF as well as in Word. This patch makes the
    impress report view format dates as "%Y-%m-%d %H:%M" (matching the
    laboratory reference PDF) regardless of the active translation.
    """
    from senaite.impress.analysisrequest.reportview import ReportView
    if _is_patched(ReportView, "to_localized_time"):
        return

    def to_localized_time(self, date, **kw):
        from DateTime import DateTime
        if not date:
            return u""
        long_format = kw.get("long_format", True)
        time_only = kw.get("time_only", False)
        try:
            if hasattr(date, "parts"):
                dt = date
            else:
                dt = DateTime(date)
            year = int(dt.year())
            month = int(dt.month())
            day = int(dt.day())
            hour = int(dt.hour())
            minute = int(dt.minute())
        except Exception:  # noqa: B902 - never break the report
            return u""
        if time_only:
            return u"%02d:%02d" % (hour, minute)
        if not long_format:
            return u"%04d-%02d-%02d" % (year, month, day)
        return u"%04d-%02d-%02d %02d:%02d" % (
            year, month, day, hour, minute)

    ReportView.to_localized_time = to_localized_time
    _mark_patched(ReportView, "to_localized_time")


def patch_reportview_publisher():
    """"Published by" falls back to the user who published the sample.

    The impress report templates print view.current_user as the reporter
    ("Published by" in the summary and the signatures). When the current
    principal has no full name (or the render context has no current user)
    the field comes out empty. If the sample has a recorded "publish"
    transition actor, we use that actor's profile instead - this is the
    person that really published the report (matches the reference PDF).
    """
    from senaite.impress.analysisrequest.reportview import ReportView
    if _is_patched(ReportView, "current_user"):
        return

    def _primary_object(self):
        """Best-effort: the primary analysis request object of this view."""
        from bika.lims import api
        try:
            model = getattr(self, "model", None)
            if model is not None:
                obj = getattr(model, "instance", None)
                if obj is not None:
                    return obj
                uid = getattr(model, "uid", None)
                if uid:
                    return api.get_object_by_uid(uid, None)
            collection = getattr(self, "collection", None)
            if collection:
                first = collection[0]
                obj = getattr(first, "instance", None)
                if obj is not None:
                    return obj
                uid = getattr(first, "uid", None)
                if uid:
                    return api.get_object_by_uid(uid, None)
        except Exception:  # noqa: B902
            return None
        return None

    def _publisher(self, obj):
        from bika.lims.workflow import getTransitionActor
        for action in ("publish", "submit"):
            try:
                actor = getTransitionActor(obj, action)
                if actor:
                    return actor
            except Exception:  # noqa: B902
                continue
        return None

    def _build_properties(user):
        from bika.lims import api
        properties = api.get_user_properties(user)
        try:
            properties.update({
                "userid": user.getId(),
                "username": user.getUserName(),
                "roles": user.getRoles(),
                "email": user.getProperty("email"),
                "fullname": user.getProperty("fullname"),
            })
        except Exception:  # noqa: B902
            pass
        return properties

    def getter(self):
        from bika.lims import api
        try:
            obj = _primary_object(self)
            if obj is not None:
                actor = _publisher(obj)
                if actor:
                    user = api.get_user(actor)
                    if user is not None:
                        return _build_properties(user)
        except Exception:  # noqa: B902 - never break the report
            pass
        # fall back to the current user (original behaviour)
        try:
            user = api.get_current_user()
            return _build_properties(user)
        except Exception:  # noqa: B902
            return {}

    ReportView.current_user = property(getter)
    _mark_patched(ReportView, "current_user")


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------
def apply_patches():
    """Apply all patches; returns True when anything was patched."""
    patch_download()
    patch_ajax_save_reports()
    patch_create_report()
    patch_downloadview()
    patch_workflow_download_reports()
    patch_email_report_filename()
    patch_reports_listing()
    patch_reportview_dates()
    patch_reportview_publisher()
    return True
