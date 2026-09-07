# -*- coding: utf-8 -*-
"""The three collectors must not drop a column whose value holds literal CJK.

What this is about
------------------
Three places read a stored list value with `json.loads(str(val))` inside a
`try` whose handler only `pass`es:

    _collect_cross_referenceable_data   cross-AS LOOKUP source data
    _evaluate_calculated_interims       scalar engine's collector
    _evaluate_calculatedlist_interims   list engine's collector

`str(u"中文")` raises UnicodeEncodeError on Python 2, the handler swallows it,
and the column is then simply ABSENT from the engine's context.  Nothing
crashes; the dependent fields just read '---'.  That is the worst shape a
defect can take here -- see R9 in SENAITE-Addon开发规则.md.

Why it is reachable
-------------------
Almost every writer goes through json.dumps() with the default
ensure_ascii=True, which escapes CJK and is therefore str()-safe.  Two things
break that assumption:

  * `_normalize_list_value_once`'s last-resort text branch dumps with
    ensure_ascii=False -- though the caller loops until the value settles, and
    the second pass re-encodes through the JSON branch with the default, so
    this one never actually reaches storage.  (Measured 2026-09-07.)
  * The XLSX setup importer writes an interim's DEFAULT value VERBATIM
    (`interim["value"] = row.get("value", "")`), with no normalisation at all.
    Measured on /Care the same day: 23 interims across three 溶液残留-*
    Calculations carry literal CJK defaults, 14 of them calculatedlist and 9
    list.  A new analysis snapshots those defaults, so the collectors see
    literal CJK before anybody saves the field.

So the escaped case is what live data looks like today, and the literal case
is what config import puts there.  Both are exercised below.

Run inside the container (Python 2.7):

    MSYS_NO_PATHCONV=1 docker cp tests/ maituxlimslatest:/tmp/ce_tests/
    MSYS_NO_PATHCONV=1 docker exec maituxlimslatest \
        python /tmp/ce_tests/test_collector_unicode.py
"""

from __future__ import print_function

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import (  # noqa: E402
    Results, build_sample, evaluate, install_engine_stubs, load_patches,
)

CJK = [u"未知杂质", u"甲醇"]
VALUES = [10.0, 20.0]
PICK = u"甲醇"              # look this one up -> must resolve to 20.0

DROPPED = (u"---", u'["---"]', u'["---", "---"]', u"", None)


def specs(literal):
    """Two analyses; `literal` decides how the CJK column is stored.

    escaped -> json.dumps(CJK)                      (what live data looks like)
    literal -> json.dumps(CJK, ensure_ascii=False)  (what XLSX import can leave)
    """
    names = json.dumps(CJK, ensure_ascii=not literal)
    index_by = u'INDEX_BY([imp_val],[imp_name],"%s")' % PICK
    return [
        {"as_id": "SRC", "service_kw": "src_as",
         "fields": [
             {"keyword": "imp_name", "title": u"物质名称",
              "result_type": "list", "value": names,
              "cross_referenceable": True},
             {"keyword": "imp_val", "title": u"数值",
              "result_type": "list", "value": json.dumps(VALUES),
              "cross_referenceable": True},
             # the SCALAR engine's collector
             {"keyword": "pick_scalar", "title": u"标量取值",
              "result_type": "calculated", "formula": index_by},
             # the CALCULATEDLIST engine's collector
             {"keyword": "pick_list", "title": u"数组取值",
              "result_type": "calculatedlist", "formula": index_by},
         ]},
        {"as_id": "DST", "service_kw": "dst_as",
         "fields": [
             {"keyword": "key", "title": u"键",
              "result_type": "list", "value": names},
             # the CROSS-REFERENCE collector
             {"keyword": "looked_up", "title": u"跨AS取值",
              "result_type": "calculatedlist",
              "formula": u'LOOKUP("src_as","imp_val","imp_name",[key])'},
         ]},
    ]


def run(p, literal):
    _, analyses = build_sample(specs(literal))
    return evaluate(p, analyses, ("SRC", "DST"))


SITES = (
    ("cross-ref collector", "DST.looked_up", [10.0, 20.0]),
    ("scalar engine collector", "SRC.pick_scalar", 20.0),
    ("list engine collector", "SRC.pick_list", [20.0]),
)


def _value(raw):
    """The stored text as a comparable Python value."""
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return raw


def test_escaped_baseline(p, r):
    """Escaped CJK must resolve -- otherwise the literal half proves nothing.

    This is the test's own validity gate: if the escaped run cannot resolve,
    the fixture is broken and a "dropped" verdict on the literal run would be
    meaningless.
    """
    out = run(p, literal=False)
    for label, key, expected in SITES:
        r.check("escaped/%s" % label, _value(out.get(key)), expected)


def test_literal_is_not_dropped(p, r):
    """The actual regression: literal CJK must resolve exactly the same."""
    out = run(p, literal=True)
    for label, key, expected in SITES:
        raw = out.get(key)
        r.check("literal/%s not dropped" % label, raw in DROPPED, False)
        r.check("literal/%s value" % label, _value(raw), expected)


def test_both_encodings_agree(p, r):
    """How the array was encoded must not change any result at all."""
    esc = run(p, literal=False)
    lit = run(p, literal=True)
    for label, key, _ in SITES:
        r.check("encoding-independent/%s" % label,
                _value(lit.get(key)), _value(esc.get(key)))


def test_source_uses_the_safe_helper(p, r):
    """Pin the shape, not just the behaviour.

    A value assertion alone cannot catch a regression: somebody could put
    `str(val)` back and every ASCII fixture would still pass.  Comments are
    stripped first so the explanations that quote the old call do not count.
    """
    src = open(p.__source_path__, "rb").read().decode("utf-8")
    code = u"\n".join(line for line in src.split(u"\n")
                      if not line.strip().startswith(u"#"))
    for bad in (u"_jj.loads(str(val))", u"_jj2.loads(str(val))"):
        r.check("no %s left" % bad, bad in code, False)
    r.check("collectors go through _safe_text",
            code.count(u"loads(_safe_text(val))"), 3)


def main():
    p = load_patches()
    install_engine_stubs()
    print("IMPORT OK  (no Zope instance started)")
    print("  source under test: %s" % p.__source_path__)

    r = Results()
    test_escaped_baseline(p, r)
    test_literal_is_not_dropped(p, r)
    test_both_encodings_agree(p, r)
    test_source_uses_the_safe_helper(p, r)
    return r.report("collector unicode safety")


if __name__ == "__main__":
    sys.exit(main())
