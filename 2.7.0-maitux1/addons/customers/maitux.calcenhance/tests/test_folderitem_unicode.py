# -*- coding: utf-8 -*-
"""Regression: patched_folderitem must survive a non-ascii interim value.

The bug this pins down
----------------------
The `calculatedlist` branch of _patch_folder_item's patched_folderitem read

    try:
        parsed = json.loads(str(value))
        ...
    except (ValueError, TypeError):
        value = json.dumps([str(value)])        # <-- str() AGAIN

UnicodeEncodeError is a subclass of ValueError, so the first str() was caught
-- and then the recovery path re-ran the very call that had failed, with
nobody left to catch it.  Result: HTTP 500 on the whole manage_results page,
in BOTH the AS-Grouped and the Classic layout.

It stays hidden until an analysis stops being editable, because that is when
core swaps the stored value for its formatted display text:

    # bika/lims/browser/analyses/view.py, _folder_item_calculation
    if not is_editable:
        interim_field["value"] = interim_formatted

The stored value is json (ascii, because json.dumps escapes), but the
formatted text is not: a RESULT_STATUS column renders as u"—<br/>—" using our
own em-dash placeholder, and a substance-name column renders as CJK.  So the
crash needs a *submitted* analysis -- which is why it survived this long.

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


# What core hands over once the analysis is no longer editable.  Both of these
# are real: the first is RESULT_STATUS's placeholder joined by
# get_formatted_interim, the second is a substance-name column.
FORMATTED_EM_DASH = u"—<br/>—"
FORMATTED_CJK = u"未知杂质, 甲醇"


def test_safe_text_covers_the_crash_inputs(p, r):
    """The helper the fix relies on must handle every shape we see."""
    f = p._safe_text
    r.check("_safe_text(em dash)", f(FORMATTED_EM_DASH), FORMATTED_EM_DASH)
    r.check("_safe_text(CJK)", f(FORMATTED_CJK), FORMATTED_CJK)
    r.check("_safe_text(utf-8 bytes)",
            f(FORMATTED_CJK.encode("utf-8")), FORMATTED_CJK)
    r.check("_safe_text(None)", f(None), u"")
    r.check("_safe_text(json array)", f(u'["a","b"]'), u'["a","b"]')


def test_source_no_longer_repeats_str_in_the_handler(p, r):
    """The shape of the bug, asserted on the shipped source.

    A value assertion alone cannot catch a regression here: somebody could
    reintroduce `str(value)` in the handler and every *ascii* fixture would
    still pass.  So the source itself is checked for the pattern.
    """
    src = open(p.__source_path__, "rb").read().decode("utf-8")
    start = src.index(u'elif result_type == "calculatedlist":')
    # Search for the terminator AFTER start: the same attribute name also
    # appears earlier, where the original method is captured
    # (`original_folderitem = analysis_view.AnalysesView._folder_item_...`),
    # and a plain src.index() would return that one -- giving end < start and
    # an EMPTY block, which makes both assertions below pass vacuously.
    # This test caught exactly that mistake in its own first run.
    end = src.index(
        u'analysis_view.AnalysesView._folder_item_calculation =', start)
    block = src[start:end]
    r.check("block located (non-empty)", len(block) > 200, True)

    # Comments are stripped first: the fix's own comment quotes the old
    # `str(value)` call to explain the trap, and an assertion that cannot tell
    # prose from code would fail on the explanation instead of the behaviour.
    code = u"\n".join(line for line in block.split(u"\n")
                      if not line.strip().startswith(u"#"))

    r.check("calculatedlist branch no longer calls str(value)",
            u"str(value)" in code, False)
    r.check("calculatedlist branch goes through _safe_text",
            u"_safe_text(value)" in code, True)


def test_the_exact_crash_is_gone(p, r):
    """Replay the branch's logic on the values that used to kill the page.

    patched_folderitem itself needs a live AnalysesView, so what is exercised
    here is the conversion the branch now performs, on the real _safe_text
    from the shipped module -- the part that used to raise.
    """
    for label, value in (("em dash", FORMATTED_EM_DASH),
                         ("CJK", FORMATTED_CJK)):
        text = p._safe_text(value)
        try:
            parsed = json.loads(text)
            out = text if isinstance(parsed, list) else json.dumps([text])
        except (ValueError, TypeError):
            out = json.dumps([text])
        # Must produce a json array holding the text, and must not raise.
        r.check("%s survives and stays a json array" % label,
                json.loads(out), [value])

    # The old code's failure mode, kept as an executable reminder of WHY the
    # handler may not repeat the call: str() raises on both of these.
    for label, value in (("em dash", FORMATTED_EM_DASH),
                         ("CJK", FORMATTED_CJK)):
        r.raises("str(%s) still raises -- that is the trap" % label,
                 UnicodeEncodeError, lambda v=value: str(v))
    r.check("UnicodeEncodeError is a ValueError (why it was swallowed)",
            issubclass(UnicodeEncodeError, ValueError), True)

    # A well-formed stored value must keep passing through untouched.
    text = p._safe_text(u'["---", "---"]')
    r.check("json array value is left as the array it is",
            json.loads(text), [u"---", u"---"])


def main():
    p = load_patches()
    print("IMPORT OK  (no Zope instance started)")
    print("  source under test: %s" % p.__source_path__)

    r = Results()
    test_safe_text_covers_the_crash_inputs(p, r)
    test_source_no_longer_repeats_str_in_the_handler(p, r)
    test_the_exact_crash_is_gone(p, r)
    return r.report("folderitem unicode regression")


if __name__ == "__main__":
    sys.exit(main())
