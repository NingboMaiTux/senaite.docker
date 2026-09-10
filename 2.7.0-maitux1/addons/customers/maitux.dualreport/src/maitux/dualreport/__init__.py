# -*- coding: utf-8 -*-
#
# maitux.dualreport - Dual PDF/Word report output for senaite.impress
#
# This package monkey-patches a small, well-defined set of senaite.impress /
# senaite.core methods (same technique as maitux.calcenhance) so that:
#
#   * the senaite.impress Publish view understands an extra
#     "report_format" (pdf | word) parameter
#   * the Save action stores the selected format (PDF blob or Word .docx)
#     into the existing ResultsReport.pdf field (with proper filename and
#     content-type)
#   * the Download action returns the selected format
#   * downloads of already-saved Word reports keep the correct filename /
#     content-type
#
# The Word document is generated from the *same* rendered report HTML that
# WeasyPrint uses for the PDF, with a dependency-free OOXML writer, so the
# layout stays as close as possible to the PDF output.

try:
    from zope.i18nmessageid import MessageFactory
except ImportError:  # pragma: no cover - standalone/offline fallback
    def MessageFactory(domain):
        """Simplest possible factory so the package stays importable."""
        def factory(msgid, *args, **kw):
            return msgid
        return factory

dualreportMessageFactory = MessageFactory('maitux.dualreport')

from maitux.dualreport.config import logger  # noqa: E402


def _apply_patches():
    """Apply the monkey-patches once, when this package is imported.

    Patch failures must NEVER take the site down, but they must also never be
    silent (see SENAITE-Addon开发规则 R9): log an ERROR with a marker that the
    deployment log/UI can be checked against.

    A plain ImportError of a senaite.* module means we are not running inside
    a SENAITE instance (e.g. running the standalone docx smoke test), so it
    is logged at debug level only.
    """
    try:
        from maitux.dualreport.patches import apply_patches
        applied = apply_patches()
        if applied:
            logger.info(
                "maitux.dualreport: monkey-patches applied "
                "(download/save/storage/report-listing)")
    except ImportError:
        logger.debug("maitux.dualreport: senaite modules not importable - "
                     "skipping monkey-patches")
    except Exception as exc:  # noqa: B902 - keep startup safe
        logger.error(
            "maitux.dualreport: FAILED to apply patches: %s" % exc)
        import traceback
        logger.error(traceback.format_exc())


# Import-time application (same pattern as maitux.calcenhance). The import of
# the target modules below happens lazily inside apply_patches(), so ZCML load
# order of senaite.impress is irrelevant.
_apply_patches()
