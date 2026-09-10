# -*- coding: utf-8 -*-
"""Central configuration of maitux.dualreport.

All constants used by the Word generator and the patched publish flow live
here, so a lab can tune "as close as possible to the PDF" behaviour without
touching the conversion code.
"""
import logging

logger = logging.getLogger("maitux.dualreport")

# Supported output formats (values of the front-end dropdown / report_format)
FORMAT_PDF = "pdf"
FORMAT_WORD = "word"
SUPPORTED_FORMATS = (FORMAT_PDF, FORMAT_WORD)
DEFAULT_FORMAT = FORMAT_PDF

# Word (docx) file details
MIMETYPE_WORD = (
    "application/vnd.openxmlformats-officedocument."
    "wordprocessingml.document")
EXTENSION_WORD = "docx"

# PDF - unchanged senaite.impress defaults
MIMETYPE_PDF = "application/pdf"
EXTENSION_PDF = "pdf"

# --- Word layout fidelity knobs -------------------------------------------
# The report CSS (css.pt of senaite.impress) defines a 9pt base font for the
# whole .report block. We reuse the same % scaling rules.
BASE_FONT_SIZE_PT = 9.0

# Fonts used inside the generated docx. WeasyPrint will use whatever CJK font
# the container provides; Word documents on Windows usually render best with
# SimSun (宋体) for Chinese body text + Arial for latin. Both are standard
# fonts so no embedding is required.
FONT_LATIN = "Arial"
FONT_EAST_ASIA = "SimSun"          # 宋体

# Footer (per page) behaviour
FOOTER_INCLUDE_PAGE_NUMBERS = True
# "{page}" and "{pages}" are replaced by Word PAGE/NUMPAGES fields
FOOTER_PAGE_TEMPLATE = {
    "zh": u"\u7b2c {page} \u9875 / \u5171 {pages} \u9875",   # 第 {page} 页 / 共 {pages} 页
    "en": "Page {page} of {pages}",
}

# Page geometry defaults (mm) - same cascade as senaite.impress
DEFAULT_PAGE_WIDTH_MM = 210.0     # A4
DEFAULT_PAGE_HEIGHT_MM = 297.0
DEFAULT_MARGIN_MM = 20.0

# Image sizing defaults (docx images are embedded at 96 DPI like the
# WeasyPrint preview)
IMAGE_DPI = 96

# Log prefix used for observable verification (rules R9)
LOG_PREFIX = "maitux.dualreport"
