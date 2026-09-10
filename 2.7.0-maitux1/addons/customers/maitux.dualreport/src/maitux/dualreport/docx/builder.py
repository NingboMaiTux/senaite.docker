# -*- coding: utf-8 -*-
"""HTML -> .docx converter for senaite.impress reports.

Converts the *same* rendered report HTML that WeasyPrint uses for the PDF into
an editable Word document. The conversion is deliberately lossy where Word has
no CSS equivalent (fixed-position footers, @page rules, complex floats), but it
re-uses the exact CSS semantics of the report templates (base 9pt font, % size
scaling, horizontal-only table borders, bold labels, section headers ...) so
the Word output stays as close as possible to the PDF output.

Only stdlib + BeautifulSoup are used (both already present in the runtime).
"""
import re

from bs4 import BeautifulSoup
from bs4 import CData
from bs4 import Comment
from bs4 import Doctype
from bs4 import NavigableString
from bs4 import ProcessingInstruction
from bs4 import Tag

from maitux.dualreport import config as cfg
from maitux.dualreport.docx import media as media_lib
from maitux.dualreport.docx import ooxml

# ---------------------------------------------------------------------------
# Constants shared with senaite.impress report CSS (css.pt)
# ---------------------------------------------------------------------------
BASE = cfg.BASE_FONT_SIZE_PT

HEADING_SCALE = {
    "h1": 1.40,
    "h2": 1.20,
    "h3": 1.10,
    "h4": 1.05,
    "h5": 1.00,
    "h6": 1.00,
}
# .report .section-header h1 { font-size: 175% } overrides the generic h1
SECTION_HEADER_SCALE = {
    "h1": 1.75,
    "h2": 1.35,
    "h3": 1.20,
}

FONT_SIZE_CLASSES = {
    "font-size-140": 1.40,
    "font-size-120": 1.20,
    "font-size-100": 1.00,
}

SMALL_TEXT_SCALE = 0.85   # bootstrap .small / .figure-caption / .methodtitle

# Tags that always start their own block
BLOCK_TAGS = ("p", "h1", "h2", "h3", "h4", "h5", "h6", "address", "div",
              "blockquote", "pre", "ul", "ol", "table", "figure",
              "figcaption", "hr", "li", "section", "article", "header",
              "footer")
# Tags we never render
SKIP_TAGS = ("script", "style", "template", "noscript", "iframe",
             "input", "button", "select", "textarea", "option")

# Tags treated as embedded images (each resolved via MediaCollector.add).
# "object" is how the impress barcode plugin (output:"bmp") embeds the
# barcode: <object type="image/bmp" data="data:image/bmp;base64,...">.
IMAGE_TAGS = ("img", "object", "embed")

# Non-text NavigableString subclasses (HTML comments, declarations, ...).
# They must never become visible text: the report templates are full of
# comments like <!-- REPORT HEADER --> / <!-- Barcode -->.
_NON_TEXT_NODES = (Comment, Doctype, CData, ProcessingInstruction)

# CSS classes / states that hide an element from the printed PDF (bootstrap
# "noprint", "d-none", ...). Elements with these (or a hidden ancestor) must
# be skipped in Word as well, otherwise the report control panels and other
# screen-only markup leak into the document.
HIDDEN_CLASSES = set([
    "noprint", "no-print", "d-none", "hidden", "invisible", "sr-only",
    "print-hidden",
])


def _is_text_node(node):
    """True for real text nodes (HTML comments/doctypes are not text)."""
    return isinstance(node, NavigableString) \
        and not isinstance(node, _NON_TEXT_NODES)


def _is_hidden(el):
    """True when the element (or an ancestor) is hidden for printing.

    Mirrors the CSS that hides these parts in the PDF (bootstrap-print.css
    .noprint, inline display:none, class="hidden", ...).
    """
    if not isinstance(el, Tag):
        return False
    node = el
    while isinstance(node, Tag):
        if node.get("hidden") is not None:
            return True
        if set(_classes(node)) & HIDDEN_CLASSES:
            return True
        style = _style_map(node)
        display = style.get("display", "").split("!")[0].strip().lower()
        visibility = style.get("visibility", "").split("!")[0].strip().lower()
        if display == "none" or visibility == "hidden":
            return True
        node = node.parent
    return False

_SINGLE_SPACE = re.compile(r"\s+")
_SIZE_PCT = re.compile(r"^([0-9.]+)\s*%$")
_SIZE_PT = re.compile(r"^([0-9.]+)\s*pt$")
_SIZE_PX = re.compile(r"^([0-9.]+)\s*px$")
_SIZE_MM = re.compile(r"^([0-9.]+)\s*mm$")
_SIZE_EM = re.compile(r"^([0-9.]+)\s*em$")
_SIZE_NUM = re.compile(r"^([0-9.]+)$")


def _collapse(text):
    """Collapse whitespace and strip."""
    if not text:
        return u""
    return _SINGLE_SPACE.sub(" ", text).strip()


def _norm_spaces(text):
    """Collapse internal whitespace to single spaces, keep boundaries.

    Used for inline text runs so that whitespace between elements is
    preserved (a whitespace-only text node must keep words apart instead of
    gluing them together).
    """
    if not text:
        return u""
    return _SINGLE_SPACE.sub(" ", unicode(text))


# ---------------------------------------------------------------------------
# Style helpers
# ---------------------------------------------------------------------------
def _classes(el):
    """Class names of an element (list of unicode)."""
    if not isinstance(el, Tag):
        return []
    cls = el.get("class") or []
    if isinstance(cls, basestring):
        cls = [cls]
    return [c for c in cls if c]


def _has_ancestor_class(el, class_name):
    node = el.parent
    while node is not None:
        if class_name in _classes(node):
            return True
        node = node.parent
    return False


def _style_map(el):
    """Parse the element style attribute into a dict."""
    out = {}
    if isinstance(el, Tag) and el.get("style"):
        for part in el["style"].split(";"):
            if ":" not in part:
                continue
            key, _, value = part.partition(":")
            out[key.strip().lower()] = value.strip().lower()
    return out


def _scale_from_style(el):
    """Font-size scale factor derived from classes and inline style."""
    scale = 1.0
    for cls in _classes(el):
        if cls in FONT_SIZE_CLASSES:
            scale *= FONT_SIZE_CLASSES[cls]
    style = _style_map(el)
    size = style.get("font-size")
    if size:
        m = _SIZE_PCT.match(size)
        if m:
            scale *= float(m.group(1)) / 100.0
        else:
            m = _SIZE_EM.match(size)
            if m:
                scale *= float(m.group(1))
    return scale


def _resolve_pt(el, tag=None):
    """Resolve the effective font size in pt for a text-bearing element.

    The report CSS sets .report * { font-size: 9pt } and scales everything
    with % so we apply the same cascade relative to the 9pt base. Ancestors
    with a "small" / "figure-caption" class (bootstrap .small = 85%) shrink
    their whole subtree (e.g. the discreeter legend, table header rows).
    """
    if tag in HEADING_SCALE:
        if _has_ancestor_class(el, "section-header"):
            scale = SECTION_HEADER_SCALE.get(tag, HEADING_SCALE[tag])
        else:
            scale = HEADING_SCALE[tag]
    else:
        scale = 1.0
    scale *= _scale_from_style(el)
    cls = set(_classes(el))
    if "small" in cls or "figure-caption" in cls or "methodtitle" in cls \
            or "results_interims" in cls or "att_for" in cls \
            or "att_keys" in cls or "att_filename" in cls \
            or "barcode-hri" in cls:
        scale *= SMALL_TEXT_SCALE
    # ancestors that shrink/grow their subtree
    node = el.parent
    while node is not None:
        if not isinstance(node, Tag):
            break
        anc = set(_classes(node))
        if anc & set(FONT_SIZE_CLASSES):
            for c in anc:
                if c in FONT_SIZE_CLASSES:
                    scale *= FONT_SIZE_CLASSES[c]
        if "small" in anc or "figure-caption" in anc or "methodtitle" in anc \
                or "results_interims" in anc or "barcode-hri" in anc:
            scale *= SMALL_TEXT_SCALE
        node = node.parent
    return BASE * scale


def _font_weight_bold(el):
    if not isinstance(el, Tag):
        return False
    if el.name in ("strong", "b", "th"):
        return True
    cls = set(_classes(el))
    if "font-weight-bold" in cls or "label" in cls or "client-name" in cls \
            or "lab-title" in cls:
        return True
    style = _style_map(el)
    weight = style.get("font-weight")
    if weight in ("bold", "700", "bolder"):
        return True
    return False


def _font_italic(el):
    if not isinstance(el, Tag):
        return False
    if el.name in ("em", "i"):
        return True
    cls = set(_classes(el))
    return "font-italic" in cls


def _font_underline(el):
    if not isinstance(el, Tag):
        return False
    return el.name == "u"


def _alignment(el, default=None):
    if not isinstance(el, Tag):
        return default
    align = el.get("align")
    if align in ("left", "center", "right", "justify"):
        return align
    cls = set(_classes(el))
    if "text-center" in cls:
        return "center"
    if "text-right" in cls:
        return "right"
    if "text-left" in cls:
        return "left"
    if "text-justify" in cls:
        return "justify"
    style = _style_map(el)
    if style.get("text-align") in ("left", "center", "right", "justify"):
        return style["text-align"]
    return default


def _image_align(el):
    """Alignment for an image, honouring (float-right / text-*) ancestors.

    The report HTML floats e.g. the summary barcode to the right
    (class="text-center float-right barcode-container"); Word cannot float,
    so we right-align the image paragraph instead.
    """
    align = "left"
    node = el
    while isinstance(node, Tag):
        cls = set(_classes(node))
        if "float-right" in cls or "text-right" in cls:
            align = "right"
        elif "text-center" in cls and align != "right":
            align = "center"
        node = node.parent
    return align


# ---------------------------------------------------------------------------
# Block model: every block is a dict
#   {'type': 'p',   'align': ..., 'runs': [run, ...], 'keep_next': bool}
#   {'type': 'tbl', 'rows': [[cell, ...], ...], 'widths': [twips or None]}
#   {'type': 'page_break'}
#   run = {'text': unicode} or {'break': True} or {'image': run-image}
# ---------------------------------------------------------------------------
class MediaCollector(object):
    """Collects embedded images while building the document."""

    def __init__(self, fetch_url=None):
        self.fetch_url = fetch_url
        self.images = []      # (filename, bytes)
        self._index = 0

    def add(self, img_el):
        """Try to add an image element; returns a run dict or None."""
        # <img src>, <object data> (barcode plugin), <embed src>
        src = (img_el.get("src") or img_el.get("data")
               or img_el.get("data-src"))
        if not src:
            return None
        resolved = media_lib.resolve_image(src, fetch_url=self.fetch_url)
        if not resolved:
            return None
        ext, data, width_px, height_px = resolved
        self._index += 1
        name = "image%d.%s" % (self._index, ext)
        self.images.append((name, data))
        rid = "rIdI%d" % self._index

        # compute drawing extents (EMU)
        width_mm = self._image_width_mm(img_el, width_px)
        height_mm = self._image_height_mm(img_el, height_px, width_px)
        # keep the aspect ratio when only one dimension is known
        if not width_mm and height_mm and width_px and height_px:
            width_mm = height_mm * (float(width_px) / float(height_px))
        if not height_mm and width_mm and width_px and height_px:
            height_mm = width_mm * (float(height_px) / float(width_px))
        if not width_mm or not height_mm:
            # fall back to intrinsic size @96dpi
            if width_px and height_px:
                width_mm = width_px * 25.4 / cfg.IMAGE_DPI
                height_mm = height_px * 25.4 / cfg.IMAGE_DPI
            else:
                width_mm = 40.0
                height_mm = 20.0

        return {
            "image": name,
            "rid": rid,
            "ext": ext,
            "width_mm": width_mm,
            "height_mm": height_mm,
        }

    # -- style based sizing -------------------------------------------------
    def _parse_len(self, value):
        value = value.strip().lower()
        m = _SIZE_MM.match(value)
        if m:
            return ("mm", float(m.group(1)))
        m = _SIZE_PT.match(value)
        if m:
            return ("mm", float(m.group(1)) * 25.4 / 72.0)
        m = _SIZE_PX.match(value)
        if m:
            return ("mm", float(m.group(1)) * 25.4 / cfg.IMAGE_DPI)
        m = _SIZE_NUM.match(value)
        if m:
            return ("mm", float(m.group(1)) * 25.4 / cfg.IMAGE_DPI)
        return None

    def _style_dims(self, img_el):
        style = _style_map(img_el)
        width = style.get("width")
        height = style.get("height")
        parsed_w = self._parse_len(width) if width else None
        parsed_h = self._parse_len(height) if height else None
        if parsed_w and parsed_w[0] == "%":
            parsed_w = None
        return (parsed_w[1] if parsed_w else None,
                parsed_h[1] if parsed_h else None)

    def _image_width_mm(self, img_el, intrinsic_px):
        style = _style_map(img_el)
        width = style.get("width")
        if width:
            parsed = self._parse_len(width)
            if parsed:
                return parsed[1]
        if img_el.get("width"):
            try:
                return float(img_el["width"]) * 25.4 / cfg.IMAGE_DPI
            except (TypeError, ValueError):
                pass
        return None

    def _image_height_mm(self, img_el, intrinsic_px, intrinsic_w):
        style = _style_map(img_el)
        height = style.get("height")
        if height:
            parsed = self._parse_len(height)
            if parsed:
                return parsed[1]
        # senaite logo: css .report .section-header img.logo { height: 30px }
        if "logo" in _classes(img_el):
            return 30.0 * 25.4 / cfg.IMAGE_DPI
        return None


# ---------------------------------------------------------------------------
# The converter
# ---------------------------------------------------------------------------
class HtmlToDocxConverter(object):
    """Convert impress report HTML into a .docx byte string."""

    def __init__(self, html, page_width_mm=210.0, page_height_mm=297.0,
                 margin_top_mm=20.0, margin_right_mm=20.0,
                 margin_bottom_mm=20.0, margin_left_mm=20.0,
                 orientation="portrait", language="en", fetch_url=None):
        self.html = html
        self.page_width_mm = float(page_width_mm)
        self.page_height_mm = float(page_height_mm)
        self.margin_top_mm = float(margin_top_mm)
        self.margin_right_mm = float(margin_right_mm)
        self.margin_bottom_mm = float(margin_bottom_mm)
        self.margin_left_mm = float(margin_left_mm)
        self.orientation = orientation or "portrait"
        self.language = language or "en"
        self.fetch_url = fetch_url
        self.media = MediaCollector(fetch_url=fetch_url)
        self._image_run_id = 0
        self._has_footer = False

    # -- top level ----------------------------------------------------------
    def convert(self):
        """Returns docx bytes."""
        soup = BeautifulSoup(self.html or "", "html.parser")
        reports = soup.find_all("div", class_="report")

        all_blocks = []
        footer_nodes = []

        if reports:
            for index, report in enumerate(reports):
                if index > 0:
                    all_blocks.append({"type": "page_break"})
                footer = report.find("div", class_="section-footer")
                if footer is not None:
                    footer_nodes.append(footer)
                    footer.extract()
                all_blocks.extend(self._blocks_for(report))
        else:
            # Not wrapped in a report container - convert the whole body
            body = soup.body or soup
            all_blocks.extend(self._blocks_for(body))

        # purge empty paragraphs before serialization
        all_blocks = [b for b in all_blocks if self._block_not_empty(b)]

        # footer first: _document_xml needs to know whether a footer exists
        footer_xml = self._footer_xml(footer_nodes)
        document_xml = self._document_xml(all_blocks)
        title = u"Analysis Report"

        return ooxml.write_docx(
            None,
            document_xml,
            footer_xml=footer_xml,
            media=self.media.images,
            title=title,
            font_latin=cfg.FONT_LATIN,
            font_east_asia=cfg.FONT_EAST_ASIA,
            base_size_pt=cfg.BASE_FONT_SIZE_PT)

    def _block_not_empty(self, block):
        if block["type"] in ("page_break", "tbl"):
            return True
        runs = block.get("runs") or []
        for run in runs:
            if run.get("image"):
                return True
            if run.get("text") and _collapse(run["text"]):
                return True
        return False

    # -- body ---------------------------------------------------------------
    def _document_xml(self, blocks):
        parts = [ooxml.xml_decl(),
                 '<w:document xmlns:w="%s" xmlns:r="%s" xmlns:wp="%s" '
                 'xmlns:a="%s" xmlns:pic="%s">'
                 % (ooxml.NS_W, ooxml.NS_R, ooxml.NS_WP,
                    ooxml.NS_A, ooxml.NS_PIC),
                 '<w:body>']
        for block in blocks:
            parts.append(self._block_xml(block))
        parts.append(self._sectpr_xml())
        parts.append('</w:body>')
        parts.append('</w:document>')
        return "".join(parts)

    def _block_xml(self, block):
        btype = block["type"]
        if btype == "page_break":
            return ('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
        if btype == "tbl":
            return self._table_xml(block)
        # paragraph
        align = block.get("align")
        runs = self._trim_para_runs(block.get("runs") or [])
        runs_xml = []
        for run in runs:
            runs_xml.append(self._run_xml(run))
        ppr = []
        # right tab stop (used for heading + barcode on the same line)
        right_tab = block.get("right_tab_pos")
        if right_tab:
            ppr.append('<w:tabs><w:tab w:val="right" w:pos="%d"/></w:tabs>'
                       % right_tab)
        spacing_before = block.get("space_before")
        if spacing_before:
            ppr.append('<w:spacing w:before="%d" w:after="%d"/>'
                       % (spacing_before, block.get("space_after", 0)))
        # NOTE: OOXML schema requires <w:tabs>/<w:spacing> BEFORE <w:jc>
        if align and align != "left":
            ppr.append('<w:jc w:val="%s"/>' % align)
        if ppr:
            ppr_xml = '<w:pPr>%s</w:pPr>' % "".join(ppr)
        else:
            ppr_xml = ""
        return '<w:p>%s%s</w:p>' % (ppr_xml, "".join(runs_xml))

    def _trim_para_runs(self, runs):
        """Remove leading/trailing spaces of a paragraph (kept inter-word
        spaces intact - they are what separates words that live in different
        HTML elements)."""
        out = list(runs)
        # leading spaces
        while out and out[0].get("text") is not None:
            text = out[0]["text"]
            stripped = text.lstrip(" ")
            if not stripped:
                out.pop(0)
                continue
            if stripped != text:
                out[0] = dict(out[0], text=stripped)
            break
        # trailing spaces
        while out and out[-1].get("text") is not None:
            text = out[-1]["text"]
            stripped = text.rstrip(" ")
            if not stripped:
                out.pop()
                continue
            if stripped != text:
                out[-1] = dict(out[-1], text=stripped)
            break
        return out

    def _run_xml(self, run):
        if run.get("image"):
            return self._image_run_xml(run["image"], run.get("width_mm"),
                                       run.get("height_mm"),
                                       rid=run.get("rid"))
        if run.get("tab"):
            return '<w:r><w:tab/></w:r>'
        if run.get("break"):
            return '<w:r><w:br/></w:r>'
        text = run.get("text") or u""
        # NOTE: whitespace-only runs must be kept - they carry the single
        # space that separates words from different HTML elements. The
        # paragraph serializer trims leading/trailing spaces afterwards.
        if not text:
            return ""
        rpr = []
        props = run.get("props") or {}
        if props.get("bold"):
            rpr.append("<w:b/>")
        if props.get("italic"):
            rpr.append("<w:i/>")
        if props.get("underline"):
            rpr.append('<w:u w:val="single"/>')
        size_pt = props.get("size_pt")
        if size_pt:
            rpr.append('<w:sz w:val="%d"/><w:szCs w:val="%d"/>'
                       % (ooxml.pt2half(size_pt), ooxml.pt2half(size_pt)))
        rpr_xml = '<w:rPr>%s</w:rPr>' % "".join(rpr) if rpr else ""
        return ('<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>'
                % (rpr_xml, ooxml.esc(text)))

    def _image_run_xml(self, filename, width_mm, height_mm, rid=None):
        self._image_run_id += 1
        if rid is None:
            rid = "rIdI%d" % len(self.media.images)
        cx = ooxml.mm2emu(width_mm)
        cy = ooxml.mm2emu(height_mm)
        # pic:cNvPr id must be unique document-wide (and normally equals the
        # wp:docPr id); a repeated id="0" can make Word refuse the file
        image_id = self._image_run_id
        return (
            '<w:r>'
            '<w:drawing>'
            '<wp:inline distT="0" distB="0" distL="0" distR="0">'
            '<wp:extent cx="%d" cy="%d"/>'
            '<wp:docPr id="%d" name="Picture %d"/>'
            '<a:graphic><a:graphicData uri="%s">'
            '<pic:pic>'
            '<pic:nvPicPr><pic:cNvPr id="%d" name="%s"/>'
            '<pic:cNvPicPr/></pic:nvPicPr>'
            '<pic:blipFill><a:blip r:embed="%s"/>'
            '<a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            '<pic:spPr><a:xfrm><a:off x="0" y="0"/>'
            '<a:ext cx="%d" cy="%d"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
            '</pic:spPr>'
            '</pic:pic>'
            '</a:graphicData></a:graphic>'
            '</wp:inline>'
            '</w:drawing>'
            '</w:r>'
            % (cx, cy, image_id, image_id,
               "http://schemas.openxmlformats.org/drawingml/2006/picture",
               image_id, ooxml.esc_attr(filename), rid, cx, cy))

    def _sectpr_xml(self):
        width = self.page_width_mm
        height = self.page_height_mm
        orient = "portrait"
        if self.orientation == "landscape":
            width, height = height, width
            orient = "landscape"
        pg = ['<w:pgSz w:w="%d" w:h="%d"' % (ooxml.mm2twips(width),
                                             ooxml.mm2twips(height))]
        if orient == "landscape":
            pg.append(' w:orient="landscape"')
        pg.append("/>")
        margins = ('<w:pgMar w:top="%d" w:right="%d" w:bottom="%d" '
                   'w:left="%d" w:header="400" w:footer="400" w:gutter="0"/>'
                   % (ooxml.mm2twips(self.margin_top_mm),
                      ooxml.mm2twips(self.margin_right_mm),
                      ooxml.mm2twips(self.margin_bottom_mm),
                      ooxml.mm2twips(self.margin_left_mm)))
        footer = ('<w:footerReference w:type="default" r:id="rIdF1"/>'
                  if self._has_footer else "")
        return '<w:sectPr>%s%s%s</w:sectPr>' % ("".join(pg), margins, footer)

    # -- footer -------------------------------------------------------------
    def _footer_xml(self, footer_nodes):
        """Render .section-footer content + page numbers into a Word footer.

        Word repeats the footer on every page, which matches the fixed
        position of the PDF footer.
        """
        self._has_footer = False
        paragraphs = []

        # 1) footer text (first report that has one)
        footer_lines = []
        for node in footer_nodes:
            for child in node.children:
                if not isinstance(child, Tag):
                    continue
                if child.get("id") == "footer-line":
                    continue
                footer_lines.extend(self._footer_text_lines(child))
            if footer_lines:
                break

        if footer_lines:
            # top border to emulate the footer line
            paragraphs.append(
                '<w:p><w:pPr><w:pBdr><w:top w:val="single" w:sz="6" '
                'w:space="1" w:color="auto"/></w:pBdr></w:pPr>'
                '<w:r><w:t xml:space="preserve"> </w:t></w:r></w:p>')
            for line in footer_lines:
                paragraphs.append(
                    '<w:p><w:r><w:rPr><w:sz w:val="18"/>'
                    '<w:szCs w:val="18"/></w:rPr>'
                    '<w:t xml:space="preserve">%s</w:t></w:r></w:p>'
                    % ooxml.esc(line))

        # 2) page numbers
        if cfg.FOOTER_INCLUDE_PAGE_NUMBERS:
            template = (cfg.FOOTER_PAGE_TEMPLATE.get(self.language)
                        or cfg.FOOTER_PAGE_TEMPLATE["en"])
            paragraphs.append(self._page_number_paragraph(template))

        if not paragraphs:
            return None
        self._has_footer = True
        xml = [ooxml.xml_decl(),
               '<w:ftr xmlns:w="%s">' % ooxml.NS_W]
        xml.extend(paragraphs)
        xml.append('</w:ftr>')
        return "".join(xml)

    def _page_number_paragraph(self, template):
        """Build a right aligned "Page X of Y" paragraph using Word fields."""
        left, _sep, right = template.partition("{page}")
        # template format: "Page {page} of {pages}"
        parts = template.split("{page}")
        before = parts[0]
        after = parts[1].split("{pages}")[0] if len(parts) > 1 else ""
        tail = parts[1].split("{pages}")[1] if len(parts) > 1 else ""

        def text_run(value):
            return ('<w:r><w:rPr><w:sz w:val="14"/><w:szCs w:val="14"/></w:rPr>'
                    '<w:t xml:space="preserve">%s</w:t></w:r>'
                    % ooxml.esc(value))

        def field(instr, cached):
            return ('<w:r><w:rPr><w:sz w:val="14"/><w:szCs w:val="14"/></w:rPr>'
                    '<w:fldChar w:fldCharType="begin"/></w:r>'
                    '<w:r><w:rPr><w:sz w:val="14"/><w:szCs w:val="14"/></w:rPr>'
                    '<w:instrText xml:space="preserve"> %s </w:instrText></w:r>'
                    '<w:r><w:rPr><w:sz w:val="14"/><w:szCs w:val="14"/></w:rPr>'
                    '<w:fldChar w:fldCharType="separate"/></w:r>'
                    '%s'
                    '<w:r><w:rPr><w:sz w:val="14"/><w:szCs w:val="14"/></w:rPr>'
                    '<w:fldChar w:fldCharType="end"/></w:r>'
                    % (ooxml.esc(instr), text_run(cached)))

        return ('<w:p><w:pPr><w:jc w:val="right"/></w:pPr>'
                + text_run(before)
                + field("PAGE", "1")
                + text_run(after)
                + field("NUMPAGES", "1")
                + text_run(tail)
                + '</w:p>')

    # -- block builder ------------------------------------------------------
    def _blocks_for(self, el, state=None):
        """Flatten an element into a list of block dicts."""
        out = []
        if el is None:
            return out
        if _is_text_node(el):
            text = _collapse(unicode(el))
            if text:
                block = self._para_block(text, state)
                # inherit the font size of the surrounding container so text
                # inside "small" wrappers (discreeter legend, table headers)
                # stays smaller
                size_pt = _resolve_pt(el.parent, None) \
                    if isinstance(el.parent, Tag) else None
                if size_pt:
                    block["runs"][0]["props"]["size_pt"] = size_pt
                out.append(block)
            return out
        if not isinstance(el, Tag):
            return out
        # skip anything that is hidden in the printed PDF
        if _is_hidden(el):
            return out
        tag = (el.name or "").lower()

        if tag in SKIP_TAGS:
            return out
        if tag in IMAGE_TAGS:
            run = self.media.add(el)
            if run:
                out.append({"type": "p", "runs": [run],
                            "align": _image_align(el)})
            return out
        if tag == "table":
            out.append(self._table_block(el))
            return out
        if tag in ("ul", "ol"):
            for li in el.find_all("li", recursive=False):
                blocks = self._blocks_for(li, state)
                if blocks:
                    # prefix bullet
                    first = blocks[0]
                    if first["type"] == "p":
                        first["runs"].insert(0, {"text": u"\u2022  ",
                                                 "props": {}})
                    out.extend(blocks)
            return out
        if tag in ("p", "h1", "h2", "h3", "h4", "h5", "h6",
                   "figcaption", "li", "td", "th"):
            # simple inline paragraph
            block = self._para_block_from_tag(el, tag, state)
            if block:
                out.append(block)
            return out
        if tag == "br":
            out.append(self._para_block("", state, force=True))
            return out
        if tag == "hr":
            out.append({"type": "p", "runs": [], "hr": True})
            return out

        # Generic container
        if not self._has_block_or_img_child(el):
            # only inline content (text, spans, <br>): render as ONE
            # paragraph - this keeps e.g. "⚠ Result out of client specified
            # range." on a single line instead of splitting every element
            block = self._para_block_from_tag(el, tag, state)
            if block:
                out.append(block)
            return out

        # render children as blocks. A "float-right" image (barcode) that is
        # directly followed by a heading is rendered on the SAME line as the
        # heading via a right tab stop (heading left, barcode right), which
        # matches the PDF without using a table (a table row made Word
        # refuse the file).
        children = list(el.children)
        index = 0
        while index < len(children):
            child = children[index]
            # look ahead past whitespace to the next real element
            j = index + 1
            while j < len(children):
                cand = children[j]
                if isinstance(cand, Tag):
                    break
                if _is_text_node(cand) and not _collapse(unicode(cand)):
                    j += 1
                    continue
                break
            nxt = children[j] if j < len(children) else None
            if isinstance(child, Tag) and isinstance(nxt, Tag) \
                    and "float-right" in _classes(child) \
                    and self._has_embedded_image(child) \
                    and (nxt.name or "").lower() in \
                    ("h1", "h2", "h3", "h4"):
                out.extend(self._heading_image_blocks(nxt, child, state))
                index = j + 1
                continue
            out.extend(self._blocks_for(child, state))
            index += 1
        return out

    def _heading_image_blocks(self, heading_el, container_el, state):
        """Heading + floated barcode on one line using a right tab stop.

        Returns paragraph blocks:
          1. "<heading text>\t<img>"  (tab to the right margin)
          2. "\t<HRI text>"           (barcode caption, right aligned)
        """
        out = []
        heading = self._para_block_from_tag(
            heading_el, (heading_el.name or "").lower(), state)
        content_blocks = self._blocks_for(container_el, state)

        image_run = None
        caption_runs = []
        for block in content_blocks:
            if block.get("type") != "p":
                continue
            for run in block.get("runs") or []:
                if run.get("image") and image_run is None:
                    image_run = run
                elif run.get("text") and _collapse(run.get("text")):
                    caption_runs.append(run)

        if heading is None or image_run is None:
            # fall back to plain sequence
            if heading is not None:
                out.append(heading)
            out.extend(content_blocks)
            return out

        tab_pos = ooxml.mm2twips(
            self.page_width_mm - self.margin_left_mm - self.margin_right_mm)
        row_runs = list(heading.get("runs") or [])
        row_runs.append({"tab": True})
        row_runs.append(image_run)
        out.append({"type": "p", "runs": row_runs,
                    "right_tab_pos": tab_pos, "align": None})
        if caption_runs:
            out.append({"type": "p",
                        "runs": [{"tab": True}] + caption_runs,
                        "right_tab_pos": tab_pos, "align": None})
        return out

    def _has_embedded_image(self, el):
        """True when the element contains an embedded image anywhere."""
        if not isinstance(el, Tag):
            return False
        return el.find(IMAGE_TAGS) is not None

    def _has_block_or_img_child(self, el):
        """True when the element has a block-level or image child.

        Used to decide whether a container is "pure inline" (merge into one
        paragraph) or must be flattened block by block.
        """
        if not isinstance(el, Tag):
            return False
        for child in el.children:
            if not isinstance(child, Tag):
                continue
            name = (child.name or "").lower()
            if name in BLOCK_TAGS or name in IMAGE_TAGS \
                    or name in ("table", "ul", "ol"):
                return True
        return False

    def _para_block_from_tag(self, el, tag, state):
        """Create a paragraph block from a paragraph-like element."""
        if tag in ("td", "th"):
            # cell paragraphs are collected by the table builder instead
            return None
        runs, _ = self._inline_runs(el, tag)
        # skip empty blocks (e.g. empty optional address fields) - they would
        # render as blank lines that do not exist in the PDF
        if not runs:
            return None
        align = _alignment(el)
        block = {"type": "p", "runs": runs, "align": align}
        if tag in HEADING_SCALE:
            block["space_before"] = 120
            block["space_after"] = 60
        return block

    def _para_block(self, text, state=None, force=False):
        runs = [{"text": text, "props": {}}]
        return {"type": "p", "runs": runs}

    def _inline_runs(self, el, tag=None):
        """Collect runs from the inline content of an element.

        :returns: (runs, had_image) - image runs are appended with sizing
        """
        runs = []
        size_pt = _resolve_pt(el, tag)
        # set once content after a block-level child must start on a new line
        after_block = [False]

        def append_run(run, props=None):
            """Append a single run honouring block boundaries.

            - whitespace between inline elements is kept as one single space
              (otherwise words from different HTML elements glue together);
            - after a block child (e.g. </div>) the next real content starts
              on a new line and the separating whitespace is dropped.
            """
            if run.get("break"):
                runs.append(run)
                after_block[0] = False
                return
            if run.get("image"):
                if after_block[0]:
                    runs.append({"break": True})
                    after_block[0] = False
                runs.append(run)
                return
            text = _norm_spaces(run.get("text") or u"")
            if not text:
                return
            if after_block[0]:
                if not text.strip():
                    # whitespace between two block lines is meaningless
                    return
                runs.append({"break": True})
                after_block[0] = False
                text = text.lstrip(" ")
            merged_props = dict(props or {})
            merged_props.update(run.get("props") or {})
            merged_props.setdefault("size_pt", size_pt)
            if runs and runs[-1].get("text") is not None:
                prev = runs[-1]["text"]
                if prev.endswith(" ") and text.startswith(" "):
                    text = text[1:]
            if text:
                runs.append({"text": text, "props": merged_props})

        for child in el.children:
            if _is_text_node(child):
                append_run({"text": unicode(child)})
                continue
            if not isinstance(child, Tag):
                continue
            if _is_hidden(child):
                continue
            ctag = (child.name or "").lower()
            if ctag in SKIP_TAGS:
                continue
            if ctag == "br":
                runs.append({"break": True})
                after_block[0] = False
                continue
            if ctag in IMAGE_TAGS:
                run = self.media.add(child)
                if run:
                    append_run(run)
                continue
            if ctag in BLOCK_TAGS:
                # nested block inside an inline context: its content belongs
                # on its own line(s)
                if runs:
                    runs.append({"break": True})
                nested_runs, _nested_img = self._inline_runs(child)
                runs.extend(nested_runs)
                after_block[0] = True
                continue
            # inline element (span, a, strong, ...)
            props = {
                "bold": _font_weight_bold(child),
                "italic": _font_italic(child),
                "underline": _font_underline(child),
                "size_pt": _resolve_pt(child, ctag),
            }
            sub_runs, _img = self._inline_runs(child)
            for sub in sub_runs:
                merged = dict(sub)
                merged_props = dict(props)
                merged_props.update(sub.get("props") or {})
                merged["props"] = merged_props
                append_run(merged)
        return runs, False

    # -- tables -------------------------------------------------------------
    def _table_block(self, table_el):
        classes = set(_classes(table_el))
        style = _style_map(table_el)
        no_borders = bool(classes & set(["noborder", "range-table"]))
        if "border" in style and style["border"] == "none":
            no_borders = True

        # extract columns widths (colgroup / inline cell styles)
        widths = self._column_widths(table_el)

        rows = []
        for tr in table_el.find_all("tr"):
            cells = []
            for cell in tr.find_all(["td", "th"], recursive=False):
                cell_block = self._cell(cell, no_borders)
                cells.append(cell_block)
            # in case a <tr> only contains nested markup, fall back to one
            # cell containing all text
            if not cells:
                runs, _ = self._inline_runs(tr)
                if runs:
                    cells.append({"runs": runs, "borders": not no_borders,
                                  "align": None, "valign": None})
            if cells:
                rows.append(cells)

        ncols = max([len(r) for r in rows] or [0])
        return {"type": "tbl", "rows": rows, "widths": widths,
                "no_borders": no_borders, "ncols": ncols}

    def _column_widths(self, table_el):
        """Return a list of % widths for the columns (or None)."""
        widths = []
        colgroup = table_el.find("colgroup")
        if colgroup:
            for col in colgroup.find_all("col"):
                style = _style_map(col)
                m = _SIZE_PCT.match(style.get("width", ""))
                if m:
                    widths.append(float(m.group(1)))
        if not widths:
            # fall back to first row styles
            first_tr = table_el.find("tr")
            if first_tr:
                for cell in first_tr.find_all(["td", "th"], recursive=False):
                    style = _style_map(cell)
                    m = _SIZE_PCT.match(style.get("width", ""))
                    if m:
                        widths.append(float(m.group(1)))
        if not widths:
            return None
        total = sum(widths)
        if total <= 0:
            return None
        return [w / total * 100.0 for w in widths]

    def _cell(self, cell_el, table_no_borders):
        style = _style_map(cell_el)
        no_border = table_no_borders or (
            "border" in style and style["border"] == "none")
        classes = set(_classes(cell_el))

        # cell content may contain block level elements (divs), so we
        # flatten them into paragraphs
        paragraphs = []
        for child in cell_el.children:
            if _is_text_node(child):
                text = _collapse(unicode(child))
                if text:
                    paragraphs.append(self._para_block(text))
                continue
            if not isinstance(child, Tag):
                continue
            if _is_hidden(child):
                continue
            tag = (child.name or "").lower()
            if tag in SKIP_TAGS:
                continue
            if tag in ("p", "h1", "h2", "h3", "h4", "h5", "h6"):
                block = self._para_block_from_tag(child, tag, None)
                if block:
                    paragraphs.append(block)
                continue
            if tag in IMAGE_TAGS:
                run = self.media.add(child)
                if run:
                    paragraphs.append({"type": "p", "runs": [run],
                                       "align": _image_align(child)})
                continue
            if tag == "table":
                paragraphs.append(self._table_block(child))
                continue
            if tag == "br":
                paragraphs.append(self._para_block(""))
                continue
            # generic container: flatten children into separate paragraphs
            for sub in child.children:
                if _is_text_node(sub):
                    text = _collapse(unicode(sub))
                    if text:
                        paragraphs.append(self._para_block(text))
                elif isinstance(sub, Tag):
                    if _is_hidden(sub):
                        continue
                    stag = (sub.name or "").lower()
                    if stag in SKIP_TAGS:
                        continue
                    if stag in ("p", "h1", "h2", "h3", "h4", "h5", "h6"):
                        block = self._para_block_from_tag(sub, stag, None)
                        if block:
                            paragraphs.append(block)
                    elif stag in IMAGE_TAGS:
                        run = self.media.add(sub)
                        if run:
                            paragraphs.append(
                                {"type": "p", "runs": [run],
                                 "align": _image_align(sub)})
                    elif stag == "table":
                        paragraphs.append(self._table_block(sub))
                    else:
                        block = self._para_block_from_tag(sub, stag, None)
                        if block:
                            paragraphs.append(block)

        # remove paragraphs without any real content (blank lines caused by
        # empty optional fields/wrappers do not exist in the PDF either)
        paragraphs = [p for p in paragraphs if self._block_not_empty(p)]

        if not paragraphs:
            paragraphs.append(self._para_block(""))

        valign = "center" if "align-middle" in classes else None
        if not valign:
            v = style.get("vertical-align")
            if v in ("middle", "top", "bottom"):
                valign = v
        return {"paragraphs": paragraphs,
                "borders": not no_border,
                "align": _alignment(cell_el),
                "valign": valign}

    # -- table xml ----------------------------------------------------------
    def _table_xml(self, block):
        rows = block.get("rows") or []
        widths_pct = block.get("widths")
        no_borders = block.get("no_borders")
        ncols = block.get("ncols") or max([len(r) for r in rows] or [0])
        ncols = max(ncols, 1)

        # borders: emulate the PDF look (horizontal lines only)
        tbl_borders = ''
        if no_borders:
            tbl_borders = (
                '<w:tblBorders><w:top w:val="nil"/><w:left w:val="nil"/>'
                '<w:bottom w:val="nil"/><w:right w:val="nil"/>'
                '<w:insideH w:val="nil"/><w:insideV w:val="nil"/>'
                '</w:tblBorders>')
        else:
            tbl_borders = (
                '<w:tblBorders><w:top w:val="single" w:sz="4" '
                'w:space="0" w:color="000000"/>'
                '<w:left w:val="nil"/><w:bottom w:val="single" w:sz="4" '
                'w:space="0" w:color="000000"/>'
                '<w:right w:val="nil"/>'
                '<w:insideH w:val="single" w:sz="4" w:space="0" '
                'w:color="000000"/>'
                '<w:insideV w:val="nil"/></w:tblBorders>')

        tbl_w = ('<w:tblW w:w="%d" w:type="dxa"/>'
                 % ooxml.mm2twips(self.page_width_mm
                                  - self.margin_left_mm
                                  - self.margin_right_mm))

        # grid
        grid_xml = ""
        if widths_pct:
            content_twips = ooxml.mm2twips(self.page_width_mm
                                           - self.margin_left_mm
                                           - self.margin_right_mm)
            cols = []
            for pct in widths_pct:
                cols.append(int(content_twips * pct / 100.0))
            grid_xml = "<w:tblGrid>" + "".join(
                '<w:gridCol w:w="%d"/>' % c for c in cols) + "</w:tblGrid>"
        else:
            content_twips = ooxml.mm2twips(self.page_width_mm
                                           - self.margin_left_mm
                                           - self.margin_right_mm)
            grid_xml = "<w:tblGrid>" + "".join(
                '<w:gridCol w:w="%d"/>'
                % (content_twips / ncols) for _ in range(ncols)) + "</w:tblGrid>"

        xml = ['<w:tbl>',
               '<w:tblPr>',
               tbl_w,
               tbl_borders,
               '</w:tblPr>',
               grid_xml]

        for row_index, row in enumerate(rows):
            xml.append('<w:tr>')
            for cell in row:
                xml.append(self._cell_xml(cell, widths_pct))
            xml.append('</w:tr>')
        xml.append('</w:tbl>')
        return "".join(xml)

    def _cell_xml(self, cell, widths_pct):
        tcpr = []
        paragraphs = cell.get("paragraphs") or []
        runs = cell.get("runs")
        if runs is not None:
            paragraphs = [{"type": "p", "runs": runs, "align": cell.get("align")}]
        if not paragraphs:
            paragraphs = [self._para_block("")]
        if cell.get("borders"):
            tcpr.append(
                '<w:tcBorders>'
                '<w:top w:val="single" w:sz="4" w:color="000000"/>'
                '<w:left w:val="nil"/>'
                '<w:bottom w:val="single" w:sz="4" w:color="000000"/>'
                '<w:right w:val="nil"/>'
                '</w:tcBorders>')
        else:
            tcpr.append(
                '<w:tcBorders><w:top w:val="nil"/><w:left w:val="nil"/>'
                '<w:bottom w:val="nil"/><w:right w:val="nil"/>'
                '</w:tcBorders>')
        valign = cell.get("valign")
        if valign:
            tcpr.append('<w:vAlign w:val="%s"/>' % valign)
        tcpr_xml = '<w:tcPr>%s</w:tcPr>' % "".join(tcpr)

        p_xml = []
        for para in paragraphs:
            align = para.get("align") or cell.get("align")
            runs_xml = []
            for run in self._trim_para_runs(para.get("runs") or []):
                runs_xml.append(self._run_xml(run))
            ppr = []
            if align and align != "left":
                ppr.append('<w:jc w:val="%s"/>' % align)
            ppr_xml = '<w:pPr>%s</w:pPr>' % "".join(ppr) if ppr else ""
            p_xml.append('<w:p>%s%s</w:p>' % (ppr_xml, "".join(runs_xml)))

        return '<w:tc>%s%s</w:tc>' % (tcpr_xml, "".join(p_xml))

    # -- footer text extraction ---------------------------------------------
    def _footer_text_lines(self, el):
        """Extract footer content as plain text lines.

        Block tags (div/p/td/tr/...) end a line, <br> also ends a line,
        inline tags merge their text. This produces a clean, deduplicated
        list of footer lines for the Word page footer.
        """
        lines = []
        current = []

        def flush():
            text = _collapse(u" ".join(current))
            if text:
                lines.append(text)
            del current[:]

        def walk(node):
            if _is_text_node(node):
                text = _collapse(unicode(node))
                if text:
                    current.append(text)
                return
            if not isinstance(node, Tag):
                return
            if _is_hidden(node):
                return
            tag = (node.name or "").lower()
            if tag in SKIP_TAGS:
                return
            if tag == "br":
                flush()
                return
            if tag in ("div", "p", "td", "tr", "table", "address",
                       "section", "article", "footer", "li", "ul", "ol",
                       "figcaption"):
                for child in node.children:
                    walk(child)
                flush()
                return
            # inline level: span, a, strong, em, font, ...
            for child in node.children:
                walk(child)

        walk(el)
        flush()
        return lines


def html_to_docx(html, page_width_mm=210.0, page_height_mm=297.0,
                 margin_top_mm=20.0, margin_right_mm=20.0,
                 margin_bottom_mm=20.0, margin_left_mm=20.0,
                 orientation="portrait", language="en", fetch_url=None):
    """Convert impress report HTML to .docx bytes.

    All dimensions default to the senaite.impress A4 + 20mm margin setup.

    :param html: report HTML (string)
    :param fetch_url: optional callable(url)->bytes to resolve <img> sources
                      that are portal URLs (same role as WeasyPrint's fetcher)
    """
    converter = HtmlToDocxConverter(
        html,
        page_width_mm=page_width_mm,
        page_height_mm=page_height_mm,
        margin_top_mm=margin_top_mm,
        margin_right_mm=margin_right_mm,
        margin_bottom_mm=margin_bottom_mm,
        margin_left_mm=margin_left_mm,
        orientation=orientation,
        language=language,
        fetch_url=fetch_url)
    return converter.convert()
