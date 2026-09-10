# -*- coding: utf-8 -*-
"""Low-level OOXML helpers for the zero-dependency Word generator.

Only the Python standard library is used (plus BeautifulSoup in builder.py).
Everything here is Python 2.7 compatible.

Units used inside docx files:
    EMU   - drawing measure (1 mm = 36000 EMU, 1 in = 914400 EMU)
    twips - page geometry measure (1 mm = 1440 / 25.4 twips)
    half-points - font size (1 pt = 2 half-points)
"""
import zipfile

# XML namespaces -----------------------------------------------------------
NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
NS_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"

# Unit conversions ---------------------------------------------------------
MM_TO_TWIPS = 1440.0 / 25.4
MM_TO_EMU = 36000.0
PX_TO_PT = 0.75            # assume 96 DPI
PT_TO_HALF = 2.0


def mm2twips(value):
    """Millimeters -> twips (integer)."""
    try:
        return int(round(float(value) * MM_TO_TWIPS))
    except (TypeError, ValueError):
        return 0


def mm2emu(value):
    """Millimeters -> EMU (integer)."""
    try:
        return int(round(float(value) * MM_TO_EMU))
    except (TypeError, ValueError):
        return 0


def pt2half(value):
    """Points -> half-points (integer)."""
    try:
        return int(round(float(value) * PT_TO_HALF))
    except (TypeError, ValueError):
        return 0


def px2pt(value):
    """Pixels (96 DPI) -> points."""
    try:
        return float(value) * PX_TO_PT
    except (TypeError, ValueError):
        return 0.0


# XML helpers --------------------------------------------------------------
def esc(value):
    """Escape text content for XML."""
    if value is None:
        return u""
    if isinstance(value, str):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            value = value.decode("latin-1")
    value = unicode(value)
    return (value
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


def esc_attr(value):
    """Escape attribute value for XML."""
    return (esc(value)
            .replace('"', "&quot;")
            .replace("\n", "&#10;"))


def xml_decl():
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


# Part builders ------------------------------------------------------------
def build_content_types(has_footer, media_extensions):
    """[Content_Types].xml content."""
    ext_defaults = {
        "rels": "application/vnd.openxmlformats-package.relationships+xml",
        "xml": "application/xml",
    }
    for ext in media_extensions:
        ext_defaults[ext] = "image/%s" % ext
    lines = [xml_decl(),
             '<Types xmlns="%s">' % NS_CT]
    for ext, ctype in sorted(ext_defaults.items()):
        lines.append('  <Default Extension="%s" ContentType="%s"/>'
                     % (esc_attr(ext), esc_attr(ctype)))
    lines.append('  <Override PartName="/word/document.xml" '
                 'ContentType="application/vnd.openxmlformats-officedocument.'
                 'wordprocessingml.document.main+xml"/>')
    lines.append('  <Override PartName="/word/styles.xml" '
                 'ContentType="application/vnd.openxmlformats-officedocument.'
                 'wordprocessingml.styles+xml"/>')
    lines.append('  <Override PartName="/docProps/core.xml" '
                 'ContentType="application/vnd.openxmlformats-package.'
                 'core-properties+xml"/>')
    lines.append('  <Override PartName="/docProps/app.xml" '
                 'ContentType="application/vnd.openxmlformats-officedocument.'
                 'extended-properties+xml"/>')
    if has_footer:
        lines.append('  <Override PartName="/word/footer1.xml" '
                     'ContentType="application/vnd.openxmlformats-'
                     'officedocument.wordprocessingml.footer+xml"/>')
    lines.append('</Types>')
    return "\n".join(lines)


def build_root_rels():
    """_rels/.rels content."""
    return "\n".join([
        xml_decl(),
        '<Relationships xmlns="%s">' % NS_REL,
        '  <Relationship Id="rId1" '
        'Type="%s/officeDocument" Target="word/document.xml"/>' % NS_R,
        '  <Relationship Id="rId2" '
        'Type="%s/metadata/core-properties" '
        'Target="docProps/core.xml"/>' % NS_REL,
        '  <Relationship Id="rId3" '
        'Type="%s/extended-properties" '
        'Target="docProps/app.xml"/>' % NS_REL,
        '</Relationships>',
    ])


def build_document_rels(has_footer, media_names):
    """word/_rels/document.xml.rels content.

    :param media_names: list of media file names (e.g. ['image1.png', ...]).
                        The relationship Target MUST contain the file
                        extension, otherwise Word cannot resolve the part and
                        renders the image as missing/broken.
    """
    lines = [xml_decl(),
             '<Relationships xmlns="%s">' % NS_REL]
    if has_footer:
        lines.append('  <Relationship Id="rIdF1" '
                     'Type="%s/footer" Target="footer1.xml"/>' % NS_R)
    for index, name in enumerate(media_names):
        rid = "rIdI%d" % (index + 1)
        lines.append('  <Relationship Id="%s" '
                     'Type="%s/image" Target="media/%s"/>'
                     % (rid, NS_R, name))
    lines.append('</Relationships>')
    return "\n".join(lines)


def build_styles(font_latin, font_east_asia, base_size_pt):
    """word/styles.xml with the document defaults (font + size)."""
    sz = pt2half(base_size_pt)
    return "\n".join([
        xml_decl(),
        '<w:styles xmlns:w="%s">' % NS_W,
        '  <w:docDefaults>',
        '    <w:rPrDefault>',
        '      <w:rPr>',
        '        <w:rFonts w:ascii="%s" w:hAnsi="%s" w:eastAsia="%s"/>'
        % (esc_attr(font_latin), esc_attr(font_latin),
           esc_attr(font_east_asia)),
        '        <w:sz w:val="%d"/>' % sz,
        '        <w:szCs w:val="%d"/>' % sz,
        '      </w:rPr>',
        '    </w:rPrDefault>',
        '    <w:pPrDefault>',
        '      <w:pPr>',
        '        <w:spacing w:after="0" w:line="240" w:lineRule="auto"/>',
        '      </w:pPr>',
        '    </w:pPrDefault>',
        '  </w:docDefaults>',
        '</w:styles>',
    ])


def build_core_props(title):
    return "\n".join([
        xml_decl(),
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/'
        'package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
        '  <dc:title>%s</dc:title>' % esc(title),
        '  <dc:creator>senaite.impress (maitux.dualreport)</dc:creator>',
        '</cp:coreProperties>',
    ])


def build_app_props():
    return "\n".join([
        xml_decl(),
        '<Properties xmlns="http://schemas.openxmlformats.org/'
        'officeDocument/2006/extended-properties">',
        '  <Application>SENAITE / maitux.dualreport</Application>',
        '</Properties>',
    ])


def write_docx(path_or_none, document_xml, footer_xml=None,
               media=None, title=u"Report",
               font_latin="Arial", font_east_asia="SimSun",
               base_size_pt=9.0):
    """Package the parts into a .docx and return the bytes.

    :param path_or_none: if a path is given the bytes are additionally
                         written there (convenience for local debugging)
    :param document_xml: content of word/document.xml
    :param footer_xml: optional content of word/footer1.xml
    :param media: list of (filename, bytes) tuples for word/media/
    :param title: document title for docProps
    :param font_latin: latin font name used in the document defaults
    :param font_east_asia: east-asian (CJK) font name
    :param base_size_pt: base font size in points
    :returns: docx bytes
    """
    media = media or []
    has_footer = bool(footer_xml)
    extensions = []
    for name, _data in media:
        ext = name.rsplit(".", 1)[-1].lower()
        if ext not in extensions:
            extensions.append(ext)

    parts = [
        ("[Content_Types].xml",
         build_content_types(has_footer, extensions)),
        ("_rels/.rels", build_root_rels()),
        ("word/document.xml", document_xml),
        ("word/styles.xml",
         build_styles(font_latin, font_east_asia, base_size_pt)),
        ("docProps/core.xml", build_core_props(title)),
        ("docProps/app.xml", build_app_props()),
        ("word/_rels/document.xml.rels",
         build_document_rels(has_footer, [name for name, _data in media])),
    ]
    if has_footer:
        parts.append(("word/footer1.xml", footer_xml))
    for name, data in media:
        parts.append(("word/media/" + name, data))

    buffer = __import__("io").BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in parts:
            if isinstance(content, unicode):
                content = content.encode("utf-8")
            zf.writestr(name, content)
    data = buffer.getvalue()

    if path_or_none:
        with open(path_or_none, "wb") as handle:
            handle.write(data)
    return data
