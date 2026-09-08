# -*- coding: utf-8 -*-
"""A Chinese choices label must not read as a syntax error.

What this is about
------------------
senaite.core's Dexterity validator parses a select interim's `choices` with

    dict(map(lambda ch: map(str.strip, str(ch).split(":")), choices))

(senaite/core/validators/interimfields.py, choices_syntax_validator).

Calculation is Dexterity, so z3c.form hands the field over as *unicode*.
`str(u'imp_linearity:...中文...')` raises UnicodeEncodeError on Python 2, and
UnicodeEncodeError is a subclass of ValueError -- so the `except ValueError`
right below catches it and reports a SYNTAX error for a string whose syntax is
fine.  Nothing is logged (the exception never leaves that inner try), so the
only thing on screen points the wrong way: it tells you to fix the format.

Measured consequence on /Care: the three Calculations that carry
`imp_cf_source` (17 / 19 / 35) could not be saved from the Edit Calculation
form AT ALL -- not just that field, the whole form was rejected, so name,
description and the other 22 interims were un-editable too.

★ Why half-fixing is worse
--------------------------
Swap only `str(ch)` and `map(str.strip, ...)` is next in line:

    TypeError: descriptor 'strip' requires a 'str' object
               but received a 'unicode'

TypeError is not a ValueError, so it escapes to the outer `except Exception` in
InterimFieldsValidator.validate() and surfaces as "Validation chain internal
error" -- a different wrong answer.  test_half_fix_shape below pins that down
so nobody "simplifies" the helper back into the trap.

Run inside the container (Python 2.7):

    MSYS_NO_PATHCONV=1 docker cp tests/ maituxlimslatest:/tmp/ce_tests/
    MSYS_NO_PATHCONV=1 docker exec maituxlimslatest \
        python /tmp/ce_tests/test_choices_syntax_unicode.py
"""

from __future__ import print_function

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import Results, load_patches  # noqa: E402

# The real configuration on /Care, byte for byte (three Calculations share it).
LABEL_1 = u"情况1 各浓度点单独称量"
LABEL_2 = u"情况2 其它称量共用"
CHOICES = u"imp_linearity:%s|imp_linearity_shared:%s" % (LABEL_1, LABEL_2)

KEY_1 = u"imp_linearity"
KEY_2 = u"imp_linearity_shared"


def test_core_shape_is_the_defect(p, r):
    """The core expression really does raise on this exact string.

    Without this the rest of the file proves nothing: it would only show that
    our helper works, not that it was needed.
    """
    try:
        dict(map(lambda ch: map(str.strip, str(ch).split(":")),
                 CHOICES.split(u"|")))
        raised = None
    except Exception as err:  # noqa: BLE001 - the type IS the assertion
        raised = type(err).__name__
    r.check("core expression raises UnicodeEncodeError",
            raised, "UnicodeEncodeError")
    # ... and that is why core's `except ValueError` swallows it.
    r.check("UnicodeEncodeError is a ValueError",
            issubclass(UnicodeEncodeError, ValueError), True)


def test_half_fix_shape(p, r):
    """Fixing only str(ch) leaves a TypeError, which core does NOT catch."""
    try:
        dict(map(lambda ch: map(str.strip, ch.split(u":")),
                 CHOICES.split(u"|")))
        raised = None
    except Exception as err:  # noqa: BLE001
        raised = type(err).__name__
    r.check("half fix raises TypeError", raised, "TypeError")
    r.check("TypeError is not a ValueError",
            issubclass(TypeError, ValueError), False)


def test_chinese_labels_parse(p, r):
    """The real configuration parses, and the keys survive intact."""
    parsed = p._parse_choices_unicode_safe(CHOICES)
    r.check("two options", len(parsed), 2)
    r.check("keys", sorted(parsed.keys()), sorted([KEY_1, KEY_2]))
    r.check("label 1 kept", parsed.get(KEY_1), LABEL_1)
    r.check("label 2 kept", parsed.get(KEY_2), LABEL_2)


def test_utf8_bytes_parse_the_same(p, r):
    """Bytes and unicode must agree -- the form can hand over either."""
    parsed = p._parse_choices_unicode_safe(CHOICES.encode("utf-8"))
    r.check("bytes give the same keys",
            sorted(parsed.keys()), sorted([KEY_1, KEY_2]))
    r.check("bytes give the same label", parsed.get(KEY_1), LABEL_1)


def test_whitespace_is_stripped(p, r):
    """core strips both halves; so must we."""
    parsed = p._parse_choices_unicode_safe(
        u"  imp_linearity :  %s  | imp_linearity_shared:%s " % (LABEL_1, LABEL_2))
    r.check("key stripped", KEY_1 in parsed, True)
    r.check("label stripped", parsed.get(KEY_1), LABEL_1)


def test_real_syntax_errors_still_raise(p, r):
    """Only the encoding got more permissive.  Bad syntax is still bad.

    Each of these must raise ValueError, because that is what the caller turns
    into "No valid format in choices field".
    """
    bad = [
        (u"imp_linearity%s" % LABEL_1, "no colon at all"),
        (u"imp_linearity:%s|no_colon_here" % LABEL_1, "second chunk has none"),
        (u"a:b:c", "two colons"),
        (u"a:b|c:d:e", "two colons in the second chunk"),
    ]
    for value, why in bad:
        try:
            p._parse_choices_unicode_safe(value)
            raised = None
        except ValueError:
            raised = "ValueError"
        except Exception as err:  # noqa: BLE001
            raised = type(err).__name__
        r.check("rejects (%s)" % why, raised, "ValueError")


def test_empty_is_not_an_error(p, r):
    """An interim without choices must stay valid -- most of them have none."""
    for value in (u"", None):
        r.check("empty (%r) parses to {}" % (value,),
                p._parse_choices_unicode_safe(value), {})


def test_source_has_no_str_call(p, r):
    """Guard the helper against being 'simplified' back into the trap.

    A value assertion cannot catch it: every ASCII case passes either way.
    Same reasoning as PR #50's source assertion.
    """
    path = p.__source_path__
    import io
    code = io.open(path, encoding="utf-8").read()
    start = code.index(u"def _parse_choices_unicode_safe")
    end = code.index(u"def _patch_validator_choices_syntax_unicode")
    body = code[start:end]

    # Skip the docstring: it quotes core's broken expression on purpose, so
    # scanning the whole function body would flag the explanation as the bug.
    # (First run did exactly that -- 19/21, both failures were the assertion's
    # fault, not the code's.)
    opening = body.index(u'"""')
    closing = body.index(u'"""', opening + 3)
    executable = body[closing + 3:]

    r.check("helper does not call str()", u"str(" in executable, False)
    r.check("helper does not use str.strip", u"str.strip" in executable, False)
    # The scan must not be vacuous -- prove it is looking at real code.
    r.check("executable part found", u"return dict(pairs)" in executable, True)
    # And the patch must actually be registered, not just defined.
    r.check("patch is registered in apply_patches",
            code.count(u"_patch_validator_choices_syntax_unicode()"), 2)


def main():
    p = load_patches()
    print("IMPORT OK  (no Zope instance started)")
    print("  source under test: %s" % p.__source_path__)

    r = Results()
    test_core_shape_is_the_defect(p, r)
    test_half_fix_shape(p, r)
    test_chinese_labels_parse(p, r)
    test_utf8_bytes_parse_the_same(p, r)
    test_whitespace_is_stripped(p, r)
    test_real_syntax_errors_still_raise(p, r)
    test_empty_is_not_an_error(p, r)
    test_source_has_no_str_call(p, r)
    return r.report("choices syntax unicode safety")


if __name__ == "__main__":
    sys.exit(main())
