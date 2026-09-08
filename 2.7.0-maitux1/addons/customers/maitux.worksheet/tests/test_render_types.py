# -*- coding: utf-8 -*-
"""Exercise the REAL select-rendering helpers of maitux.worksheet (Python 2.7).

Covers the two pure functions behind the `select` render type:

    choices_label()      key -> display label, for read-only cells
    _with_blank_choice() guarantees the "clear it again" option

Same technique as maitux.calcenhance/tests/harness.py: stub only the
module-scope imports, then load the SHIPPED file.  views.py executes nothing at
import time beyond constants and class definitions, so this reaches the real
functions rather than a transcription of them -- a hand-copied body drifts the
moment somebody edits one and not the other, and the test keeps passing while
the shipped code is broken.

What this canNOT reach: the ZPT itself and the browser side.  Those need the
running instance; the observable judgements for them are in
Docs/worksheet-select-interim-Backlog.md (S1/S2), which check the rendered
<option> list and the round-trip through the real save endpoint.

Run it inside the container -- the only place a Python 2.7 lives:

    MSYS_NO_PATHCONV=1 docker cp tests/ maituxlimslatest:/tmp/mw_tests/
    MSYS_NO_PATHCONV=1 docker exec maituxlimslatest         python /tmp/mw_tests/test_render_types.py
"""

from __future__ import print_function

import imp
import os
import shutil
import sys
import tempfile

VIEWS = ("/opt/addons/customers/maitux.worksheet"
         "/src/maitux/worksheet/browser/views.py")


def _stub(name, attrs=None):
    import types
    module = types.ModuleType(name)
    for key, value in (attrs or {}).items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def load():
    sys.dont_write_bytecode = True
    scratch = tempfile.mkdtemp(prefix="mw_")
    copy = os.path.join(scratch, "views_under_test.py")
    shutil.copyfile(VIEWS, copy)

    _stub("Products")
    _stub("Products.Five")
    _stub("Products.Five.browser")
    _stub("Products.Five.browser.pagetemplatefile",
          {"ViewPageTemplateFile": lambda path: path})
    sys.modules["Products"].Five = sys.modules["Products.Five"]
    sys.modules["Products.Five"].browser = sys.modules["Products.Five.browser"]
    _stub("bika")
    _stub("bika.lims", {"api": None})
    _stub("bika.lims.api")
    _stub("bika.lims.api.analysis", {"is_out_of_range": lambda *a: (False, False)})
    sys.modules["bika"].lims = sys.modules["bika.lims"]
    _stub("senaite")
    _stub("senaite.core")
    _stub("senaite.core.browser")
    _stub("senaite.core.browser.worksheets")
    _stub("senaite.core.browser.worksheets.worksheet")
    _stub("senaite.core.browser.worksheets.worksheet.analyses_listing",
          {"AnalysesView": object})
    _stub("senaite.core.i18n", {"translate": lambda s, **kw: s})
    return imp.load_source("mw_views_under_test", copy)


def main():
    mod = load()
    fn = mod.GroupedRenderingMixin.choices_label
    print("loaded real views.py from %s" % VIEWS)

    col = {"choices": [
        {"ResultValue": u"", "ResultText": u""},
        {"ResultValue": u"imp_linearity",
         "ResultText": u"情况1 各浓度点单独称量"},
        {"ResultValue": u"imp_linearity_shared",
         "ResultText": u"情况2 其它称量共用"},
    ]}
    no_choices = {}

    cases = [
        ("key -> label",
         (col, u"imp_linearity"),
         u"情况1 各浓度点单独称量"),
        ("other key -> its label",
         (col, u"imp_linearity_shared"),
         u"情况2 其它称量共用"),
        ("empty stays empty", (col, u""), u""),
        ("None stays empty", (col, None), u""),
        # A value no longer among the choices must stay VISIBLE, not vanish:
        # that is a data problem worth seeing.
        ("unknown key falls back to itself", (col, u"imp_gone"), u"imp_gone"),
        # A column with no choices at all (should never happen for a select,
        # but must not crash).
        ("column without choices", (no_choices, u"imp_linearity"),
         u"imp_linearity"),
        # Already-formatted label passes through: core swaps value->formatted
        # on non-editable analyses, so the read-only cell may hand us a label.
        ("label passes through",
         (col, u"情况1 各浓度点单独称量"),
         u"情况1 各浓度点单独称量"),
    ]

    failures = 0
    for label, args, want in cases:
        got = fn(*args)
        ok = (got == want)
        if not ok:
            failures += 1
        print("  %-36s %s  got=%r" % (label, "PASS" if ok else "FAIL", got))

    print("")
    print("choices_label: %d/%d passed" % (len(cases) - failures, len(cases)))

    # ---- _with_blank_choice: the field must stay CLEARABLE --------------
    blank = mod.GroupedRenderingMixin._with_blank_choice
    dash = mod.GroupedRenderingMixin._BLANK_CHOICE_LABEL
    print("")
    core_with_blank = [
        {"ResultValue": u"", "ResultText": u""},
        {"ResultValue": u"imp_linearity", "ResultText": u"A"},
    ]
    core_without_blank = [
        {"ResultValue": u"imp_linearity", "ResultText": u"A"},
        {"ResultValue": u"imp_linearity_shared", "ResultText": u"B"},
    ]
    b_cases = [
        # core supplied a blank (field still empty): keep exactly one, and
        # give the invisible label the em dash
        ("core blank kept, label filled",
         blank(core_with_blank),
         [{"ResultValue": u"", "ResultText": dash},
          {"ResultValue": u"imp_linearity", "ResultText": u"A"}]),
        # core dropped the blank (field has a value): put one back in front
        ("blank prepended when missing",
         blank(core_without_blank),
         [{"ResultValue": u"", "ResultText": dash}] + core_without_blank),
        ("empty input still yields a blank option",
         blank([]), [{"ResultValue": u"", "ResultText": dash}]),
        ("None input still yields a blank option",
         blank(None), [{"ResultValue": u"", "ResultText": dash}]),
    ]
    for label, got, want in b_cases:
        ok = (got == want)
        if not ok:
            failures += 1
        print("  %-36s %s" % (label, "PASS" if ok else "FAIL"))
        if not ok:
            print("       got  %r" % (got,))
            print("       want %r" % (want,))

    # never duplicate, never mutate the caller's dicts
    src = [{"ResultValue": u"", "ResultText": u""}]
    out = blank(src)
    ok = (len([c for c in out if c["ResultValue"] == u""]) == 1
          and src[0]["ResultText"] == u"")
    if not ok:
        failures += 1
    print("  %-36s %s" % ("exactly one blank, input untouched",
                          "PASS" if ok else "FAIL"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
