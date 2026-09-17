# -*- coding: utf-8 -*-
"""CoA (Certificate of Analysis) Word generation.

For the ``CoaReport`` template we do not translate the report HTML into a
fresh document - the laboratory provides a formatted Word template
(``templates/CoaReportTemplate.docx``) that has to be filled with the report
values. This module extracts the values from the rendered CoaReport HTML
(the same HTML that WeasyPrint turns into the PDF) and fills them into the
bundled Word template, so the Word output keeps the customers corporate
layout.

Only the ``word/document.xml`` part of the template is modified; every other
part (styles, headers, images, customXml, ...) is copied verbatim.
"""
import copy
import io
import zipfile

from bs4 import BeautifulSoup
from lxml import etree

from maitux.dualreport.config import WORD_TEMPLATE_MARKER
from maitux.dualreport.config import logger

# WordprocessingML namespace
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

TEMPLATE_PACKAGE = "maitux.dualreport"
TEMPLATE_PATH = "templates/CoaReportTemplate.docx"

# analysis table header marker (used to locate the header row)
ANALYSES_HEADER = u"Testing Item"


def q(tag):
    return "{%s}%s" % (W, tag)


def is_coa_template(template_name):
    """True when the given impress template is the CoA template.

    This is also the gate for Word output: only this template may produce
    docx files (see config.WORD_TEMPLATE_MARKER).
    """
    if not template_name:
        return False
    name = template_name
    if isinstance(name, str):
        name = name.decode("utf-8", "ignore")
    return WORD_TEMPLATE_MARKER in unicode(name).lower().replace(" ", "")


# ---------------------------------------------------------------------------
# HTML value extraction
# ---------------------------------------------------------------------------
def _text(el):
    if el is None:
        return u""
    return u" ".join(el.get_text(u" ", strip=True).split())


def _cell_texts(tr):
    return tr.find_all(["td", "th"], recursive=False)


def extract_coa_data(html):
    """Extract the CoA fields from the rendered CoaReport HTML.

    :returns: dict with report_no, meta {}, analyses [(item, method, spec,
              result)], signatures {} or None when this is not CoA HTML
    """
    soup = BeautifulSoup(html or "", "html.parser")
    wrapper = soup.find(id="coa-wrapper")
    if wrapper is None:
        return None

    data = {
        "report_no": u"",
        "meta": {},
        "analyses": [],
        "signatures": [],
    }

    rid = wrapper.find(class_="rid-value")
    if rid is not None:
        data["report_no"] = _text(rid)

    # --- meta table (label / value pairs) ---
    for table in wrapper.find_all("table", class_="meta-table"):
        for tr in table.find_all("tr"):
            cells = _cell_texts(tr)
            for index, cell in enumerate(cells):
                classes = cell.get("class") or []
                if "m-label" not in classes:
                    continue
                zh = cell.find(class_="zh")
                label = _text(zh if zh is not None else cell)
                if not label:
                    continue
                value = u""
                if index + 1 < len(cells):
                    value = _text(cells[index + 1])
                data["meta"][label] = value

    # --- analyses table ---
    for table in wrapper.find_all("table", class_="analyses-table"):
        for tr in table.find_all("tr"):
            cells = _cell_texts(tr)
            if len(cells) < 4:
                # "No analyses published" placeholder row
                continue
            row = tuple(_text(cell) for cell in cells[:4])
            if not any(row):
                continue
            data["analyses"].append(row)

    # --- signature block: one entry per row (role, name, date) ---
    for row in wrapper.select(".sig-block .sig-row"):
        labels = row.find_all(class_="sig-label-col")
        values = row.find_all(class_="sig-value-col")
        entry = {"role": u"", "name": u"", "date": u""}
        pairs = []
        for label_el, value_el in zip(labels, values):
            zh = label_el.find(class_="zh")
            label = _text(zh if zh is not None else label_el)
            pairs.append((label, _text(value_el)))
        if pairs:
            entry["role"] = pairs[0][0]
            entry["name"] = pairs[0][1]
        if len(pairs) > 1:
            entry["date"] = pairs[1][1]
        if entry["role"] or entry["name"]:
            data["signatures"].append(entry)

    return data


# ---------------------------------------------------------------------------
# Word template editing helpers (lxml)
# ---------------------------------------------------------------------------
def _paragraph_text(p):
    return u"".join(t.text or u"" for t in p.iter(q("t")))


def _set_cell_text(cell, value):
    """Write ``value`` into a w:tc, keeping the existing formatting."""
    value = value or u""
    paragraphs = cell.findall(q("p"))
    if paragraphs:
        keep = paragraphs[0]
        for extra in paragraphs[1:]:
            cell.remove(extra)
    else:
        keep = etree.SubElement(cell, q("p"))

    runs = keep.findall(q("r"))
    if runs:
        proto = runs[0]
        for extra in runs[1:]:
            keep.remove(extra)
    else:
        proto = etree.SubElement(keep, q("r"))

    # drop hyperlinks / other inline containers that would duplicate text
    for child in list(keep):
        if child.tag not in (q("pPr"), q("r")):
            keep.remove(child)

    for t in proto.findall(q("t")):
        proto.remove(t)
    text = etree.SubElement(proto, q("t"))
    text.set(XML_SPACE, "preserve")
    text.text = value


def _row_cells(tr):
    return tr.findall(q("tc"))


def _iter_tables(root):
    return root.iter(q("tbl"))


def _table_text(tbl):
    return _paragraph_text(tbl)


def _fill_label_value_table(tbl, mapping):
    """Fill a "label | value" table (also handles 4-column rows)."""
    filled = 0
    for tr in tbl.findall(q("tr")):
        cells = _row_cells(tr)
        for index, cell in enumerate(cells):
            label = _paragraph_text(cell).strip()
            if not label:
                continue
            for key, value in mapping.items():
                if label.startswith(key) and index + 1 < len(cells):
                    _set_cell_text(cells[index + 1], value)
                    filled += 1
                    break
    return filled


def _fill_analyses_table(tbl, analyses):
    """Replace the example rows with one row per analysis."""
    rows = tbl.findall(q("tr"))
    if not rows:
        return False

    header_index = 0
    for index, tr in enumerate(rows):
        if ANALYSES_HEADER in _paragraph_text(tr):
            header_index = index
            break

    data_rows = rows[header_index + 1:]
    if not data_rows:
        return False

    parent = data_rows[0].getparent()
    base_index = list(parent).index(data_rows[0])
    prototype = copy.deepcopy(data_rows[0])

    for offset, extra in enumerate(data_rows):
        parent.remove(extra)

    for i, (item, method, spec, result) in enumerate(analyses):
        row = copy.deepcopy(prototype)
        cells = _row_cells(row)
        for cell, value in zip(cells, (item, method, spec, result)):
            _set_cell_text(cell, value)
        parent.insert(base_index + i, row)

    if not analyses:
        row = copy.deepcopy(prototype)
        cells = _row_cells(row)
        for cell in cells:
            _set_cell_text(cell, u"")
        parent.insert(base_index, row)
    return True


def _append_report_no(root, report_no):
    """Append the report number after the "Report ID" label."""
    if not report_no:
        return
    for p in root.iter(q("p")):
        text = _paragraph_text(p)
        if "Report ID" not in text:
            continue
        runs = p.findall(q("r"))
        if runs:
            new_run = copy.deepcopy(runs[-1])
            for t in new_run.findall(q("t")):
                new_run.remove(t)
            for child in list(new_run):
                if child.tag != q("rPr"):
                    new_run.remove(child)
        else:
            new_run = etree.SubElement(p, q("r"))
        text_el = etree.SubElement(new_run, q("t"))
        text_el.set(XML_SPACE, "preserve")
        text_el.text = u" " + report_no
        p.append(new_run)


def _fill_signatures(tbl, signatures):
    """Fill the signature table (drafted / reviewed / approved + dates).

    :param signatures: ordered list of dicts with role / name / date
    """
    rows = tbl.findall(q("tr"))
    for index, tr in enumerate(rows):
        cells = _row_cells(tr)
        if len(cells) < 4:
            continue
        if index >= len(signatures):
            break
        entry = signatures[index]
        _set_cell_text(cells[1], entry.get("name", u""))
        _set_cell_text(cells[3], entry.get("date", u""))
    return True


# ---------------------------------------------------------------------------
# builder
# ---------------------------------------------------------------------------
def _load_template_bytes():
    from pkg_resources import resource_string
    return resource_string(TEMPLATE_PACKAGE, TEMPLATE_PATH)


def build_coa_docx(html):
    """Build the CoA Word document from rendered report HTML.

    :returns: docx bytes, or None when the HTML is not CoA HTML / the
              template is not available (caller falls back)
    """
    data = extract_coa_data(html)
    if data is None:
        return None

    try:
        template = _load_template_bytes()
    except Exception as exc:  # noqa: B902
        logger.error("maitux.dualreport: CoA template missing: %s" % exc)
        return None

    try:
        return _fill_template(template, data)
    except Exception as exc:  # noqa: B902 - never break the report
        logger.error("maitux.dualreport: CoA docx generation failed: %s"
                     % exc)
        import traceback
        logger.error(traceback.format_exc())
        return None


def _fill_template(template_bytes, data):
    zin = zipfile.ZipFile(io.BytesIO(template_bytes))
    document_xml = zin.read("word/document.xml")
    root = etree.fromstring(document_xml)

    meta_map = {
        u"项目号": data["meta"].get(u"项目号", u""),
        u"CoA版本号": data["meta"].get(u"CoA版本号", u""),
        u"化合物编号": data["meta"].get(u"化合物编号", u""),
        u"批数量": data["meta"].get(u"批数量", u""),
        u"物料名称": data["meta"].get(u"物料名称", u""),
        u"生产日期": data["meta"].get(u"生产日期", u""),
        u"批号": data["meta"].get(u"批号", u""),
        u"检测日期": data["meta"].get(u"检测日期", u""),
        u"规格": data["meta"].get(u"规格", u""),
        u"复检日期": data["meta"].get(u"复检日期", u""),
        u"生产企业": data["meta"].get(u"生产企业", u""),
        u"储存条件": data["meta"].get(u"储存条件", u""),
        u"备注": data["meta"].get(u"备注", u""),
    }

    analyses_done = False
    meta_done = 0
    signatures_done = False
    for tbl in _iter_tables(root):
        text = _table_text(tbl)
        if u"项目号" in text and not meta_done:
            meta_done = _fill_label_value_table(tbl, meta_map)
        elif ANALYSES_HEADER in text and not analyses_done:
            analyses_done = _fill_analyses_table(tbl, data["analyses"])
        elif u"起草人" in text and not signatures_done:
            signatures_done = _fill_signatures(tbl, data["signatures"])

    _append_report_no(root, data["report_no"])

    new_xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8",
                             standalone=True)

    out = io.BytesIO()
    zout = zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED)
    for item in zin.infolist():
        payload = zin.read(item.filename)
        if item.filename == "word/document.xml":
            payload = new_xml
        zout.writestr(item, payload)
    zout.close()
    zin.close()

    logger.info("maitux.dualreport: CoA Word document generated "
                "(report %s, %d analyses)"
                % (data["report_no"], len(data["analyses"])))
    return out.getvalue()
