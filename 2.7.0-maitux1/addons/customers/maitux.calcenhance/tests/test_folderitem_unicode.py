# -*- coding: utf-8 -*-
"""patched_folderitem: a non-editable interim must neither crash nor be mangled.

Two halves of the same defect, both in the `calculatedlist` branch of
_patch_folder_item's patched_folderitem, and both only reachable once an
analysis stops being editable.

Why "not editable" is the trigger for both
------------------------------------------
core replaces the stored value with its formatted display text at that point:

    # bika/lims/browser/analyses/view.py, _folder_item_calculation
    if not is_editable:
        interim_field["value"] = interim_formatted

The STORED value is json and ascii-safe (json.dumps escapes non-ascii).  The
FORMATTED text is neither: for a calculatedlist, patched_get_formatted_interim
joins the elements with a NEWLINE, so the branch receives things like
u"1.0<NL>1.0" or, for a RESULT_STATUS column, two em dashes joined the same
way.  That is why both halves survived so long -- nothing hits them until
somebody submits or retracts.

Half 1 (fixed 2026-09-07, PR #48): the crash
    try:
        parsed = json.loads(str(value))
        ...
    except (ValueError, TypeError):
        value = json.dumps([str(value)])        # <-- str() AGAIN
UnicodeEncodeError is a subclass of ValueError, so the first str() was caught
-- and the recovery path then re-ran the very call that had failed, with
nobody left to catch it.  HTTP 500 on the whole manage_results page, in BOTH
the AS-Grouped and the Classic layout.

Half 2 (fixed 2026-09-07, same day, after retracting an analysis and looking
at it): the mangling.  Fixing the crash was not enough -- the handler still
WRAPPED the display text into json.dumps([text]), producing a bogus
single-element array that the MultiValue widget rendered verbatim.  A
retracted analysis showed its computed columns as one quoted string with an
escaped newline inside, instead of the two values it holds.  The `list` branch
twenty lines above had always got this right ("Already formatted display text
- keep as-is"); the two branches disagreed on the same situation.

Run inside the container (Python 2.7):

    MSYS_NO_PATHCONV=1 docker cp tests/ maituxlimslatest:/tmp/ce_tests/
    MSYS_NO_PATHCONV=1 docker exec maituxlimslatest \
        python /tmp/ce_tests/test_folderitem_unicode.py
"""

from __future__ import print_function

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import Results, load_patches  # noqa: E402


NL = u"\n"
EM = u"—"                                  # em dash, RESULT_STATUS's mark

# What core hands over once the analysis is no longer editable.
FORMATTED_EM_DASH = EM + u"<br/>" + EM          # report-side join
FORMATTED_CJK = u"未知杂质, 甲醇"                 # a name column
FORMATTED_NUMBERS = u"1.0" + NL + u"1.0"        # calculatedlist join
FORMATTED_EM_NL = EM + NL + EM                  # RESULT_STATUS, same join


def _branch(p, value):
    """The calculatedlist branch's conversion, as shipped.

    patched_folderitem itself needs a live AnalysesView, so the branch's own
    two lines are replayed here against the REAL _safe_text from the shipped
    module.  test_source_matches_this_replay below keeps the two in step.
    """
    text = p._safe_text(value)
    try:
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            return json.dumps([text])
    except (ValueError, TypeError):
        return value                            # keep as-is
    return value


def test_safe_text_covers_the_crash_inputs(p, r):
    """The helper the fix relies on must handle every shape we see."""
    f = p._safe_text
    r.check("_safe_text(em dash)", f(FORMATTED_EM_DASH), FORMATTED_EM_DASH)
    r.check("_safe_text(CJK)", f(FORMATTED_CJK), FORMATTED_CJK)
    r.check("_safe_text(utf-8 bytes)",
            f(FORMATTED_CJK.encode("utf-8")), FORMATTED_CJK)
    r.check("_safe_text(None)", f(None), u"")
    r.check("_safe_text(json array)", f(u'["a","b"]'), u'["a","b"]')


def test_half1_no_crash(p, r):
    """Half 1: the values that used to take the page down must go through."""
    for label, value in (("em dash", FORMATTED_EM_DASH),
                         ("CJK", FORMATTED_CJK),
                         ("newline em dashes", FORMATTED_EM_NL)):
        # must not raise, and must not lose the text
        r.check("half1/%s survives" % label, _branch(p, value), value)

    # The old failure mode, kept executable: this is WHY the handler may not
    # repeat the call it just failed on.
    for label, value in (("em dash", FORMATTED_EM_DASH),
                         ("CJK", FORMATTED_CJK)):
        r.raises("str(%s) still raises -- that is the trap" % label,
                 UnicodeEncodeError, lambda v=value: str(v))
    r.check("UnicodeEncodeError is a ValueError (why it was swallowed)",
            issubclass(UnicodeEncodeError, ValueError), True)


def test_half2_display_text_is_not_rewrapped(p, r):
    """Half 2: display text must be left alone, not wrapped into an array."""
    for label, text in (("newline-joined numbers", FORMATTED_NUMBERS),
                        ("newline-joined em dashes", FORMATTED_EM_NL),
                        ("comma-joined CJK", FORMATTED_CJK)):
        got = _branch(p, text)
        r.check("half2/%s kept as-is" % label, got, text)
        # the visible symptom was a value that both starts and ends with a
        # bracket -- i.e. text that had been dressed up as an array
        r.check("half2/%s not wrapped" % label,
                got.startswith(u"[") and got.endswith(u"]"), False)
        r.check("half2/%s keeps its newline" % label,
                (NL in got) if (NL in text) else True, True)

    # A real stored array still passes straight through, untouched.
    r.check("stored placeholder array untouched",
            _branch(p, u'["---", "---"]'), u'["---", "---"]')
    r.check("stored numeric array untouched",
            _branch(p, u"[1.0, 2.0]"), u"[1.0, 2.0]")
    r.check("stored escaped-CJK array untouched",
            _branch(p, u'["\\u7532\\u9187"]'), u'["\\u7532\\u9187"]')

    # A json scalar IS still wrapped -- that half of the logic was correct:
    # a lone number has to become a one-element array for MultiValue.
    r.check("json scalar still wrapped", _branch(p, u"5"), u'["5"]')


def test_source_matches_this_replay(p, r):
    """Pin the shipped shape, so the replay above cannot drift from it.

    Value assertions alone are not enough twice over: somebody could put
    `str(value)` back (half 1) or `json.dumps([text])` back in the handler
    (half 2), and every ascii fixture would still pass.
    """
    src = open(p.__source_path__, "rb").read().decode("utf-8")
    start = src.index(u'elif result_type == "calculatedlist":')
    # Search for the terminator AFTER start: the same attribute name also
    # appears earlier, where the original method is captured
    # (`original_folderitem = analysis_view.AnalysesView._folder_item_...`),
    # and a plain src.index() would return that one -- giving end < start and
    # an EMPTY block, which makes every assertion below pass vacuously.
    # This test caught exactly that mistake in its own first run.
    end = src.index(
        u'analysis_view.AnalysesView._folder_item_calculation =', start)
    block = src[start:end]
    r.check("block located (non-empty)", len(block) > 200, True)

    # Comments are stripped first: the fix's own comments quote the old calls
    # to explain the trap, and an assertion that cannot tell prose from code
    # would fail on the explanation instead of the behaviour.
    code = u"\n".join(line for line in block.split(u"\n")
                      if not line.strip().startswith(u"#"))

    r.check("half1: no str(value) left", u"str(value)" in code, False)
    r.check("half1: goes through _safe_text",
            u"_safe_text(value)" in code, True)
    # exactly one wrap remains -- the `not isinstance(parsed, list)` one.
    # A second occurrence means the handler started re-wrapping again.
    r.check("half2: exactly one json.dumps([text])",
            code.count(u"json.dumps([text])"), 1)


def main():
    p = load_patches()
    print("IMPORT OK  (no Zope instance started)")
    print("  source under test: %s" % p.__source_path__)

    r = Results()
    test_safe_text_covers_the_crash_inputs(p, r)
    test_half1_no_crash(p, r)
    test_half2_display_text_is_not_rewrapped(p, r)
    test_source_matches_this_replay(p, r)
    return r.report("folderitem: non-editable interim")


if __name__ == "__main__":
    sys.exit(main())
