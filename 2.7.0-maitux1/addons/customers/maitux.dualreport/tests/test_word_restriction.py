# -*- coding: utf-8 -*-
"""Regression test for the Word template restriction.

Word output is only allowed for the CoA template (config.WORD_TEMPLATE_MARKER);
every other template must be served/stored as PDF, even when the request asks
for ``report_format=word``.

Runs standalone (no ZODB / no Zope app needed):

    bin/zopepy src/maitux.dualreport/tests/test_word_restriction.py
"""
from maitux.dualreport import config as cfg
from maitux.dualreport import patches

# (template, requested format, expected effective format)
CASES = [
    ("CoaReport.pt", "word", "word"),
    ("coareport.pt", "word", "word"),
    ("COAREPORT.PT", "word", "word"),
    ("Coa Report.pt", "word", "word"),
    ("INNOCARE.reportdesign:CoaReport.pt", "word", "word"),
    ("DataReport.pt", "word", "pdf"),
    ("senaite.impress:Default.pt", "word", "pdf"),
    ("senaite.impress:MultiDefault.pt", "word", "pdf"),
    ("senaite.impress:MultiDefaultByColumn.pt", "word", "pdf"),
    (None, "word", "pdf"),
    ("", "word", "pdf"),
    ("CoaReport.pt", "pdf", "pdf"),
    ("DataReport.pt", "pdf", "pdf"),
    ("DataReport.pt", "bogus", "pdf"),
    ("DataReport.pt", None, "pdf"),
]


def main():
    print("WORD_TEMPLATE_MARKER = %r" % cfg.WORD_TEMPLATE_MARKER)
    failures = 0
    for template, requested, expected in CASES:
        got = patches._effective_format(requested, template)
        ok = got == expected
        if not ok:
            failures += 1
        print("%-4s template=%-38r requested=%-6r -> %-5r (expected %r)"
              % ("PASS" if ok else "FAIL", template, requested, got, expected))

    # the predicate itself must agree with the CoA docx builder
    from maitux.dualreport.docx import coa
    for template, expected in (("CoaReport.pt", True),
                               ("DataReport.pt", False),
                               (None, False)):
        got = patches.is_word_template(template)
        ok = got is expected and coa.is_coa_template(template) is expected
        if not ok:
            failures += 1
        print("%-4s is_word_template(%-16r) -> %s (coa.is_coa_template=%s)"
              % ("PASS" if ok else "FAIL", template, got,
                 coa.is_coa_template(template)))

    print("")
    print("RESULT: %s" % ("PASS" if failures == 0 else "FAIL (%d)" % failures))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
