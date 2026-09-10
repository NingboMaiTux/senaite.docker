# -*- coding: utf-8 -*-
"""Local smoke test for the zero-dependency docx generator.

Runnable outside Zope (only needs the add-on source + beautifulsoup4):

    python -m maitux.dualreport.tests.test_docx_smoke

Verifies that a report HTML snippet (modelled after the senaite.impress AR
templates) converts into a structurally valid .docx (zip + well-formed XML).
This is the "observable" baseline check of the converter; final verification
must happen inside the container (see README).
"""
from __future__ import print_function

import io
import os
import tempfile
import zipfile
from xml.etree import ElementTree as ET

from maitux.dualreport.docx.builder import html_to_docx

SAMPLE_HTML = u"""<!doctype html>
<html><head><meta charset="utf-8"><title>Report</title></head>
<body>
<style type="text/css">
.report * { font: 9pt; }
.report .section-header h1 { font-size: 175%; }
.report table { border-color: black; }
.report table td, .report table th { border-top: 1px solid black; }
</style>
<div class="report" uids="uid1">
  <div class="row section-header no-gutters">
    <table class="w-100 mb-0 noborder"><tr>
      <td><h1>Analysis Report</h1></td>
      <td class="text-right">
        <img class="logo" style="height:30px"
             src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg=="/>
      </td>
    </tr></table>
  </div>
  <div class="row section-summary no-gutters">
    <h1>Summary</h1>
    <table class="table table-sm table-condensed">
      <tr><td class="label">Sample ID</td><td>AR-0001</td></tr>
      <tr><td class="label">Client</td><td>ACME \u6d4b\u8bd5\u5ba4</td></tr>
    </table>
  </div>
  <div class="row section-results no-gutters">
    <h1>Results for AR-0001</h1>
    <table class="table table-sm">
      <thead><tr>
        <th>Category</th><th class="text-right">Result</th>
        <th>Unit</th><th>Range</th>
      </tr></thead>
      <tbody>
        <tr><td>pH</td><td class="text-right">7.2</td><td></td>
            <td>6.5-8.5</td></tr>
        <tr><td>Conductivity</td><td class="text-right">15.3</td>
            <td>uS/cm</td><td>&lt; 50</td></tr>
      </tbody>
    </table>
  </div>
  <div class="row section-footer no-gutters">
    <div id="footer-line"></div>
    <table class="w-100"><tr><td>
      <div><strong>Lab Name</strong> \u2014 Lab Street 1, 315000 Ningbo</div>
      <div>Phone: 0574-12345678 \u2014 Fax: 0574-12345679 \u2014
        <a href="mailto:lab@example.com">lab@example.com</a></div>
    </td></tr></table>
  </div>
</div>
</body></html>
"""


def _validate_docx(path):
    """Structural validation: zip readable, every XML part well-formed."""
    errors = []
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            for name in names:
                if name.endswith(".xml") or name.endswith(".rels"):
                    data = zf.read(name)
                    try:
                        ET.fromstring(data)
                    except Exception as exc:  # noqa: B902
                        errors.append("%s -> %s" % (name, exc))
            if "word/document.xml" not in names:
                errors.append("word/document.xml missing")
            if "word/styles.xml" not in names:
                errors.append("word/styles.xml missing")
    except Exception as exc:  # noqa: B902
        errors.append(str(exc))
    return errors


def main():
    data = html_to_docx(
        SAMPLE_HTML,
        page_width_mm=210.0, page_height_mm=297.0,
        margin_top_mm=20.0, margin_right_mm=20.0,
        margin_bottom_mm=20.0, margin_left_mm=20.0,
        orientation="portrait", language="zh", fetch_url=None)

    fd, path = tempfile.mkstemp(suffix=".docx")
    os.close(fd)
    with io.open(path, "wb") as handle:
        handle.write(data)
    print("docx bytes :", len(data))
    print("written to :", path)

    errors = _validate_docx(path)
    if errors:
        print("VALIDATION ERRORS:")
        for err in errors:
            print(" -", err)
        return 1

    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        print("members    :", len(names))
        for name in names:
            if name.startswith("word/") or name.startswith("[Content"):
                print("  ", name)
    print("OK: docx structure is valid")
    return 0


def check_multi_image():
    """Two images must produce two distinct relationship ids."""
    png = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUl"
           "EQVR4nGNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg==")
    html = ('<div class="report"><p><img src="data:image/png;base64,%s"/>'
            '<img src="data:image/png;base64,%s"/></p></div>' % (png, png))
    data = html_to_docx(html, language="en")
    fd, path = tempfile.mkstemp(suffix=".docx")
    os.close(fd)
    with io.open(path, "wb") as handle:
        handle.write(data)
    errors = _validate_docx(path)
    if errors:
        print("MULTI-IMAGE VALIDATION ERRORS:")
        for err in errors:
            print(" -", err)
        return 1
    with zipfile.ZipFile(path) as zf:
        doc = zf.read("word/document.xml")
        rels = zf.read("word/_rels/document.xml.rels")
    ok = doc.find(b'rIdI1') != -1 and doc.find(b'rIdI2') != -1 \
        and rels.find(b'rIdI1') != -1 and rels.find(b'rIdI2') != -1
    print("multi-image rIds OK :", ok)
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    rc = main()
    if rc == 0:
        rc = check_multi_image()
    sys.exit(rc)
