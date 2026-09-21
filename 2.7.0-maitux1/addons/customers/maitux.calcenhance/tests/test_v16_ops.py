# -*- coding: utf-8 -*-
"""Tests for the five V16 engine capabilities (裁决 §7 ①②③④⑤).

Run inside the container (Python 2.7):

    MSYS_NO_PATHCONV=1 docker cp tests/ maituxlimslatest:/tmp/ce_tests/
    MSYS_NO_PATHCONV=1 docker exec maituxlimslatest python /tmp/ce_tests/test_v16_ops.py

Exit code 0 means every case passed.  See harness.py for what this can and
cannot reach; test_engine.py holds the rest of the engine's tests, and the
two helpers imported from it are shared on purpose -- a second copy of the
registry reader would drift away from the one the other file asserts on.

What each block is for:

    ①  RESULT_STATUS's report wording, and the COUPLING that wording has
       with RESULT_NUM: '＜0.05%' carries a number, so a static marker
       table cannot recognise it and 总杂 silently blanks out.
    ②  XAGG_NTH2  -- the n-th injection of a key's own group.
    ③  XAGG_KEYS_WHERE2 -- row space filtered by value.
    ④  the dual key 「物质名称 + 杂质分组」, on the row-space builders AND
       on every aggregate: a pair matched on one field merges two
       different impurities into one plausible-looking number.
    ⑤  INDEX_BY_GROUP -- the per-injection lookup.
"""

from __future__ import print_function

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import (  # noqa: E402
    FakeService, Results, build_sample, evaluate, install_engine_stubs,
    load_patches, rebuild)
from test_engine import _find_code, _registry_keys  # noqa: E402


class _FakeOwner(object):
    """Only what the WARN lines quote, plus the AS the limits are read from."""

    id = "S2601-R01-imp_ip_stat"

    def __init__(self, loq=None, lod=None):
        self._service = FakeService("imp_ip_stat", loq, lod)

    def getAnalysisService(self):
        return self._service


# ---------------------------------------------------------------------------
# ① RESULT_STATUS wording + the RESULT_NUM coupling
# ---------------------------------------------------------------------------

def _rebuild_result_status(p, owner):
    fmt_limit = rebuild(p, "_fmt_limit")
    return rebuild(p, "_result_status", defaults=(None, None), freevars={
        "self": owner, "_fmt_limit": fmt_limit})


def _rebuild_result_num(p):
    return rebuild(p, "_result_num", defaults=(None, None), freevars={
        "_norm_key": rebuild(p, "_norm_key")})


def test_is_zero_marker(p, r):
    """①: every below-limit spelling folds to zero, including the ones
    that carry a number.

    The '＜0.05%' label is the reason this is a predicate and not a set:
    the number follows each AS's own report limit, so no literal table can
    list them all, and an unrecognised marker does not fail loudly -- it
    returns '---' from RESULT_NUM and blanks 总杂 for the whole column.
    """
    f = p._is_zero_marker
    for text in (u"", u"ND", u"N.D.", u"N.D", u"nd", u"<LOQ", u"< LOQ",
                 u"<LOD", u"< LOD", u"＜0.05%", u"＜0.1%", u"＜0.005%",
                 u"<0.05%", u"  ＜0.05%  ", u"<"):
        r.check("zero marker %r" % (text,), f(text), True)
    for text in (u"0.05", u"0", u"ND2", u"N/A", u"未检出", u">0.05%",
                 u"0.05%"):
        r.check("not a zero marker %r" % (text,), f(text), False)
    # A str (not unicode) with CJK in it must not raise -- R13.
    r.check("utf-8 str argument", f(u"未检出".encode("utf-8")), False)
    r.check("None", f(None), True)


def test_result_num_folds_the_new_labels(p, r):
    """①: RESULT_NUM's contract, re-asserted through the new predicate.

    This is the case that took 总杂 down: '＜0.05%' was not in the marker
    table, so it fell through to '---', and the sum of the report values
    read '---' on every row without a single log line.
    """
    f = _rebuild_result_num(p)
    r.check("rebuilt RESULT_NUM", f is not None, True)
    if f is None:
        return
    for text in (u"＜0.05%", u"＜0.1%", u"<LOQ", u"ND", u"N.D.", u""):
        r.check("RESULT_NUM(%r) -> 0" % (text,), f(text), 0)
    r.check("RESULT_NUM passes a number through", f(u"0.12"), 0.12)
    r.check("RESULT_NUM leaves unknown text as the placeholder",
            f(u"N/A"), p._PLACEHOLDER)
    r.check("RESULT_NUM: the main component contributes 0",
            f(u"99.5", u"主峰", u"主峰"), 0)


def test_result_status_wording(p, r):
    """①: the three bands, in the analysts' own wording (裁决 G2).

    The middle label is built from `loq`, not frozen into the source: an AS
    with a different report limit has to say its own number, and the day
    somebody changes the limit the report must change with it.
    """
    install_engine_stubs()
    f = _rebuild_result_status(p, _FakeOwner())
    r.check("rebuilt RESULT_STATUS", f is not None, True)
    if f is None:
        return

    got = f([0.12, 0.03, 0.001, u"", None, u"abc"], 0.05, 0.01)
    r.check("≥ 报告限 -> the number itself", got[0], 0.12)
    r.check("积分限 ≤ x < 报告限 -> ＜<loq>%", got[1], u"＜0.05%")
    r.check("< 积分限 -> ND", got[2], u"ND")
    r.check("empty -> em dash", got[3], u"—")
    r.check("None -> em dash", got[4], u"—")
    r.check("non-numeric -> em dash", got[5], u"—")

    r.check("the label follows loq, not a constant",
            f([0.07], 0.1, 0.01), [u"＜0.1%"])
    r.check("a limit with trailing zeros does not claim precision",
            f([0.07], 0.100, 0.01), [u"＜0.1%"])
    r.check("full-width ＜, not ASCII <",
            f([0.03], 0.05, 0.01)[0][0], u"＜")

    # loq/lod arrive as one-element columns when the formula referenced a
    # scalar interim -- the array path pads every reference to the row count.
    r.check("loq/lod unwrapped from a column", f([0.03], [0.05], [0.01]),
            [u"＜0.05%"])

    # Read from the AS's Limits tab when the formula omits them.
    auto = _rebuild_result_status(p, _FakeOwner(loq=0.05, lod=0.01))
    r.check("limits read from the AS when not passed",
            auto([0.12, 0.03, 0.001]), [0.12, u"＜0.05%", u"ND"])


def test_result_status_feeds_result_num(p, r):
    """①: the two functions joined up -- the actual failure mode.

    RESULT_STATUS writes the report column; RESULT_NUM sums it into 总杂.
    Asserting them separately would have missed the defect entirely: both
    were individually correct and the pair was broken.
    """
    install_engine_stubs()
    status = _rebuild_result_status(p, _FakeOwner())
    num = _rebuild_result_num(p)
    if status is None or num is None:
        r.check("rebuilt both halves", False, True)
        return
    reported = status([0.12, 0.03, 0.001], 0.05, 0.01)
    contributions = [num(v) for v in reported]
    r.check("every band contributes a number to 总杂",
            contributions, [0.12, 0, 0])
    r.check("总杂 adds up", sum(contributions), 0.12)


# ---------------------------------------------------------------------------
# ②③④ the dual-key XAGG family
# ---------------------------------------------------------------------------
#
# The fixture is AS-25 in miniature: three injections per substance instead
# of six, and the four source shapes that matter side by side.
#
#   std     指定杂质, from 杂质对照品称量 -- has NO 杂质分组 column and no
#           report column at all.  Its rows are on the table because a
#           reference standard was weighed, not because of a value.
#   chrom   第一人.  Holds a substance that is ALSO in std (杂质A), and the
#           same unnamed name (未知1) under TWO different groups, which is
#           the whole reason the key is a pair.
#   spiked  第二人.  A different unnamed substance, so the row space is a
#           union of the two operators rather than either one alone.
#   ghost   exists in the sample but has none of these fields flagged.
#
# Sample ids are deliberately "2", "10", "1": sorted as text, 10 lands
# between 1 and 2 and XAGG_NTH2 returns the wrong injection.
#
# The report column is MIXED on purpose, and the types are not decorative:
# _collect_cross_referenceable_data floats every floatable cell and leaves
# the rest as text, so this is the shape the functions really see --
# numbers next to '＜0.05%' and 'ND'.  Writing the numbers as strings here
# would have tested a shape that never occurs.

A = u"杂质A"
B = u"杂质B"
U1 = u"未知1"
U2 = u"未知2"
U3 = u"未知3"
R085 = u"RRT0.85"
R120 = u"RRT1.20"
R150 = u"RRT1.50"
R200 = u"RRT2.00"


def _v16_fixture():
    sibling_data = {
        u"std": {u"imp_name": [A, B]},
        u"chrom": {
            u"imp_name": [A, A, A, U1, U1, U1, U1, U1, U1, U3, U3, U3],
            u"imp_pct_group": [u"", u"", u"",
                               R085, R085, R085,
                               R120, R120, R120,
                               R200, R200, R200],
            u"g_sample_id": [u"2", u"10", u"1"] * 4,
            u"imp_report": [0.12, 0.15, 0.11,
                            0.06, u"ND", u"＜0.05%",
                            0.02, 0.03, 0.01,
                            u"ND", u"ND", u"＜0.05%"],
        },
        u"spiked": {
            u"imp_name": [A, A, A, U2, U2, U2],
            u"imp_pct_group": [u"", u"", u"", R150, R150, R150],
            u"g_sample_id": [u"1", u"2", u"3"] * 2,
            u"imp_report": [0.13, 0.14, 0.12,
                            0.09, 0.08, 0.07],
        },
    }
    existing = set([u"std", u"chrom", u"spiked", u"ghost"])
    return sibling_data, existing


def _rebuild_v16(p, owner, sibling_data, existing_services):
    """Rebuild the dual-key family bottom-up through its shared cells."""
    norm_key = rebuild(p, "_norm_key")
    group_apply = rebuild(p, "_group_apply", freevars={"_norm_key": norm_key},
                          defaults=(p._PLACEHOLDER,))
    agg_stdev = rebuild(p, "_agg_stdev")
    agg_rsd = rebuild(p, "_agg_rsd", freevars={"_agg_stdev": agg_stdev})
    xagg_warn = rebuild(p, "_xagg_warn")
    resolve_sources = rebuild(p, "_xagg_resolve_sources", freevars={
        "self": owner, "_xagg_warn": xagg_warn})
    as_column = rebuild(p, "_xagg_as_column")
    collect_columns = rebuild(p, "_xagg_collect_columns", defaults=((),),
                              freevars={
        "self": owner,
        "_xagg_existing_services": existing_services,
        "sibling_data": sibling_data,
        "_xagg_resolve_sources": resolve_sources,
        "_xagg_warn": xagg_warn,
        "_xagg_as_column": as_column,
    })
    dual_collect = rebuild(p, "_xagg_dual_collect", freevars={
        "_xagg_collect_columns": collect_columns})
    pairs = rebuild(p, "_xagg_pairs", freevars={"_norm_key": norm_key})
    row_pairs = rebuild(p, "_xagg_row_pairs", freevars={"_xagg_pairs": pairs})
    part = rebuild(p, "_xagg_part", freevars={
        "self": owner, "_xagg_warn": xagg_warn})
    sort_key = rebuild(p, "_xagg_sort_key", freevars={"_norm_key": norm_key})
    op2 = rebuild(p, "_xagg_op2", freevars={
        "_group_apply": group_apply,
        "_xagg_dual_collect": dual_collect,
        "_xagg_pairs": pairs,
        "_xagg_row_pairs": row_pairs,
    })
    out = {
        "keys2": rebuild(p, "_xagg_keys2", freevars={
            "_xagg_dual_collect": dual_collect,
            "_xagg_pairs": pairs,
            "_xagg_part": part,
        }),
        "where2": rebuild(p, "_xagg_keys_where2", freevars={
            "_xagg_dual_collect": dual_collect,
            "_xagg_pairs": pairs,
            "_xagg_part": part,
            "_xagg_warn": xagg_warn,
            "self": owner,
        }),
        "nth2": rebuild(p, "_xagg_nth2", freevars={
            "_xagg_dual_collect": dual_collect,
            "_xagg_pairs": pairs,
            "_xagg_row_pairs": row_pairs,
            "_xagg_sort_key": sort_key,
            "_xagg_warn": xagg_warn,
            "self": owner,
        }),
        "avg2": rebuild(p, "_xagg_avg2", freevars={"_xagg_op2": op2}),
        "rsd2": rebuild(p, "_xagg_rsd2", freevars={
            "_xagg_op2": op2, "_agg_rsd": agg_rsd}),
        "max2": rebuild(p, "_xagg_max2", freevars={"_xagg_op2": op2}),
        "min2": rebuild(p, "_xagg_min2", freevars={"_xagg_op2": op2}),
        "count2": rebuild(p, "_xagg_count2", freevars={"_xagg_op2": op2}),
    }
    return out


def test_xagg_keys2(p, r):
    """④: the row space as PAIRS, returned one segment at a time.

    The two calls have to walk the same deduplicated list, or the name
    column and the group column beside it describe different rows.
    """
    install_engine_stubs()
    sibling_data, existing = _v16_fixture()
    fn = _rebuild_v16(p, _FakeOwner(), sibling_data, existing)["keys2"]
    r.check("rebuilt XAGG_KEYS2", fn is not None, True)
    if fn is None:
        return

    names = fn(u"imp_name", u"imp_pct_group", 1, u"chrom")
    groups = fn(u"imp_name", u"imp_pct_group", 2, u"chrom")
    r.check("segment 1: distinct combinations, first-seen order",
            names, [A, U1, U1, U3])
    r.check("segment 2: row-aligned with segment 1",
            groups, [u"", R085, R120, R200])
    r.check("the two columns have the same length",
            len(names) == len(groups), True)

    # 未知1 appears twice because its GROUP differs -- that is the pair
    # doing its job.  A single-key row space would have merged them.
    r.check("same name, two groups -> two rows",
            [n for n in names if n == U1], [U1, U1])

    # A source with no 杂质分组 column at all: empty second segment (D1).
    r.check("no group column -> empty segment, not a missing row",
            fn(u"imp_name", u"imp_pct_group", 1, u"std"), [A, B])
    r.check("no group column -> u'' for every row",
            fn(u"imp_name", u"imp_pct_group", 2, u"std"), [u"", u""])

    # Dedup across sources, first-seen order preserved.
    r.check("two sources dedupe against each other",
            fn(u"imp_name", u"imp_pct_group", 1, u"std", u"spiked"),
            [A, B, U2])

    # An empty 键字段2 is the single-key case -- no second family needed.
    r.check("empty 键字段2 behaves as a single key",
            fn(u"imp_name", u"", 1, u"chrom"), [A, U1, U3])

    r.check("取第几段 must be 1 or 2",
            fn(u"imp_name", u"imp_pct_group", 3, u"chrom"), [p._PLACEHOLDER])
    r.check("a source that was never run -> placeholder, not a crash",
            fn(u"imp_name", u"imp_pct_group", 1, u"nobody_ran_this"),
            [p._PLACEHOLDER])
    r.check("a source that exists but has nothing flagged -> placeholder",
            fn(u"imp_name", u"imp_pct_group", 1, u"ghost"),
            [p._PLACEHOLDER])


def test_xagg_keys_where2(p, r):
    """③: 指定杂质 unconditionally, everything else only if it was SEEN.

    The two source lists are separate arguments because the two groups are
    asked different questions; folding them into one list and deciding by
    "does this source have a report column" would turn a forgotten
    cross_referenceable flag into a complete-looking table.
    """
    install_engine_stubs()
    sibling_data, existing = _v16_fixture()
    fn = _rebuild_v16(p, _FakeOwner(), sibling_data, existing)["where2"]
    r.check("rebuilt XAGG_KEYS_WHERE2", fn is not None, True)
    if fn is None:
        return

    names = fn(u"imp_name", u"imp_pct_group", 1, [u"std"],
               u"imp_report", 0.05, [u"chrom", u"spiked"])
    groups = fn(u"imp_name", u"imp_pct_group", 2, [u"std"],
                u"imp_report", 0.05, [u"chrom", u"spiked"])
    r.check("指定杂质 first, then the qualifying rows, deduplicated",
            names, [A, B, U1, U2])
    r.check("the group column lines up with it",
            groups, [u"", u"", R085, R150])

    # 未知1/RRT1.20 tops out at 0.03 and 未知3 never reads a number at all.
    r.check("below the threshold on every injection -> not on the table",
            U3 in names, False)
    r.check("the LOW group of a name that also has a HIGH one stays off",
            groups.count(R120), 0)

    # 未知1/RRT0.85 is on the table because ONE injection reached 0.06,
    # even though the other two read 'ND' and '＜0.05%' (裁决 Q6b).
    r.check("any single injection qualifies the row", U1 in names, True)

    r.check("the threshold is an argument, not a constant",
            fn(u"imp_name", u"imp_pct_group", 1, [], u"imp_report", 0.5,
               [u"chrom", u"spiked"]),
            [p._PLACEHOLDER])
    r.check("a lower threshold takes more rows in",
            fn(u"imp_name", u"imp_pct_group", 1, [], u"imp_report", 0.01,
               [u"chrom", u"spiked"]),
            [A, U1, U1, U2])
    r.check("a non-numeric threshold refuses rather than guessing",
            fn(u"imp_name", u"imp_pct_group", 1, [u"std"], u"imp_report",
               u"0.05%", [u"chrom"]),
            [p._PLACEHOLDER])
    r.check("a bare string is accepted where a list is expected",
            fn(u"imp_name", u"imp_pct_group", 1, u"std", u"imp_report",
               0.05, u"chrom"),
            [A, B, U1])

    # The filter field missing from a FILTERED source is the configuration
    # mistake: fail the whole thing, do not take every row of that source.
    r.check("filtered source without the filter field -> placeholder",
            fn(u"imp_name", u"imp_pct_group", 1, [u"std"], u"imp_report",
               0.05, [u"std"]),
            [p._PLACEHOLDER])


def test_xagg_op2(p, r):
    """④: every aggregate matches on the PAIR, not on the name.

    Without this, 未知1/RRT0.85 and 未知1/RRT1.20 would share one mean --
    a number that looks entirely reasonable on the report.
    """
    install_engine_stubs()
    sibling_data, existing = _v16_fixture()
    fns = _rebuild_v16(p, _FakeOwner(), sibling_data, existing)
    for name in ("avg2", "rsd2", "max2", "min2", "count2"):
        r.check("rebuilt XAGG_%s" % name.upper(), fns[name] is not None, True)
    if fns["avg2"] is None:
        return

    rows = [A, B, U1, U1, U3]
    groups = [u"", u"", R085, R120, R200]

    def call(fn, sources=(u"chrom", u"spiked")):
        return fn(u"imp_report", u"imp_name", u"imp_pct_group", rows, groups,
                  *sources)

    avg = call(fns["avg2"])
    r.check("杂质A: both operators' numbers, one mean",
            round(avg[0], 6),
            round((0.12 + 0.15 + 0.11 + 0.13 + 0.14 + 0.12) / 6.0, 6))
    r.check("杂质B: weighed but never chromatographed -> placeholder",
            avg[1], p._PLACEHOLDER)
    r.check("未知1/RRT0.85: only the numeric injection counts",
            round(avg[2], 6), 0.06)
    r.check("未知1/RRT1.20: a DIFFERENT number, not merged with RRT0.85",
            round(avg[3], 6), round((0.02 + 0.03 + 0.01) / 3.0, 6))
    r.check("未知3: rows exist, nothing numeric -> placeholder",
            avg[4], p._PLACEHOLDER)

    r.check("MAX2 on the pair", call(fns["max2"])[3], 0.03)
    r.check("MIN2 on the pair", call(fns["min2"])[3], 0.01)

    count = call(fns["count2"])
    r.check("COUNT2 counts only the numeric survivors", count[2], 1)
    r.check("COUNT2: pair present, nothing numeric -> 0", count[4], 0)
    r.check("COUNT2: pair absent from the sources -> '---', not 0",
            count[1], p._PLACEHOLDER)

    rsd = call(fns["rsd2"])
    values = [0.02, 0.03, 0.01]
    mean = sum(values) / 3.0
    stdev = (sum((v - mean) ** 2 for v in values) / 2.0) ** 0.5
    r.check("RSD2 on the pair", round(rsd[3], 6),
            round(stdev / mean * 100.0, 6))

    # Empty is a key segment, never a wildcard: asking for 杂质A in a group
    # it does not belong to must not fall back to the name alone.
    wrong = fns["avg2"](u"imp_report", u"imp_name", u"imp_pct_group",
                        [A], [R085], u"chrom")
    r.check("empty group is not a wildcard", wrong, [p._PLACEHOLDER])

    # A single-key call, for the AS that has no second column at all.
    single = fns["avg2"](u"imp_report", u"imp_name", u"", [A], [u""],
                         u"chrom")
    r.check("empty 键字段2 collapses to a single-key match",
            round(single[0], 6), round((0.12 + 0.15 + 0.11) / 3.0, 6))


def test_xagg_nth2(p, r):
    """②: the n-th injection of a row's own group, ordered by 样品编号.

    The report values come back exactly as stored -- '＜0.05%' and 'ND' are
    results, and a number is the wrong type for them.
    """
    install_engine_stubs()
    sibling_data, existing = _v16_fixture()
    fn = _rebuild_v16(p, _FakeOwner(), sibling_data, existing)["nth2"]
    r.check("rebuilt XAGG_NTH2", fn is not None, True)
    if fn is None:
        return

    rows = [A, B, U1]
    groups = [u"", u"", R085]

    def nth(n, source=u"chrom"):
        return fn(u"imp_report", u"imp_name", u"imp_pct_group", rows, groups,
                  u"g_sample_id", n, source)

    # Sample ids are "2", "10", "1": numeric order is 1, 2, 10.
    r.check("第1份 is 样品编号 1, not the first row collected",
            nth(1)[0], 0.11)
    r.check("第2份", nth(2)[0], 0.12)
    r.check("第3份 -- text sorting would have put 10 before 2 here",
            nth(3)[0], 0.15)
    r.check("第4份 of a three-injection group -> '---', never a shift",
            nth(4)[0], p._PLACEHOLDER)

    r.check("a row with no injections at all -> '---'",
            nth(1)[1], p._PLACEHOLDER)

    r.check("strings come back as stored: below-limit label",
            nth(1)[2], u"＜0.05%")
    r.check("strings come back as stored: ND", nth(3)[2], u"ND")
    r.check("the numeric one in between", nth(2)[2], 0.06)
    r.check("one group, one mixed column -- numbers stay numbers",
            [type(v) is float for v in
             (nth(1)[0], nth(2)[0], nth(3)[0])], [True] * 3)

    r.check("第二人 is sorted on its own 样品编号",
            fn(u"imp_report", u"imp_name", u"imp_pct_group", [A], [u""],
               u"g_sample_id", 1, u"spiked"),
            [0.13])

    r.check("第几份 below 1 -> '---'", nth(0)[0], p._PLACEHOLDER)
    r.check("第几份 not a number -> '---'", nth(u"x")[0], p._PLACEHOLDER)
    r.check("a source that was never run -> '---' for every row",
            nth(1, u"nobody_ran_this"), [p._PLACEHOLDER] * 3)


def test_xagg_collect_columns_alignment(p, r):
    """④: the per-source padding, and what it refuses to pad.

    Columns of different lengths inside ONE source cannot be paired by
    position; zipping them anyway is how a value ends up beside another
    row's key.
    """
    logger = install_engine_stubs()
    sibling_data, existing = _v16_fixture()
    sibling_data[u"ragged"] = {
        u"imp_name": [A, B, U1],
        u"imp_pct_group": [u"", u""],
    }
    existing.add(u"ragged")
    fn = _rebuild_v16(p, _FakeOwner(), sibling_data, existing)["keys2"]

    before = len(logger.lines)
    r.check("misaligned columns inside one source -> placeholder",
            fn(u"imp_name", u"imp_pct_group", 1, u"ragged"),
            [p._PLACEHOLDER])
    r.check("and it says so", len(logger.lines) > before, True)

    before = len(logger.lines)
    fn(u"imp_name", u"imp_pct_group", 1, u"std")
    joined = " ".join(logger.lines[before:])
    r.check("an absent optional column is reported, not silent",
            "does not exist on" in joined, True)


def test_v16_registration(p, r):
    """④②③⑤: registered, and routed to the array path.

    A name that is not dispatched to the array path degrades to the
    per-element one, where it sees a single scalar -- silently, and with a
    perfectly plausible column of results.
    """
    safe = _registry_keys(p, "_SAFE")
    for name in ("XAGG_KEYS2", "XAGG_KEYS_WHERE2", "XAGG_NTH2", "XAGG_AVG2",
                 "XAGG_RSD2", "XAGG_MAX2", "XAGG_MIN2", "XAGG_COUNT2",
                 "INDEX_BY_GROUP"):
        r.check("%s registered in _SAFE" % name, name in safe, True)

    src = open(p.__source_path__, "rb").read().decode("utf-8")
    array_fn_re = re.compile(
        r'(GROUP_\w+(?:list)?|\w+_ROWS|RESULT_STATUS|TIME_ELAPSED_HOURS'
        r'|COALESCE|SHIFT|BASELINE_BYlist|XAGG_\w+|APPEND|INDEX_BY_GROUP)'
        r'\s*\(')
    for name in ("XAGG_KEYS2", "XAGG_KEYS_WHERE2", "XAGG_NTH2", "XAGG_AVG2",
                 "XAGG_COUNT2"):
        r.check("%s rides the XAGG_\\w+ entry" % name,
                bool(array_fn_re.search(u"%s(a,b,[c],d)" % name)), True)
    r.check("INDEX_BY_GROUP is named in the dispatch regex in source",
            u"|INDEX_BY_GROUP)" in src, True)

    # The pre-existing alternation does NOT cover INDEX_BY_GROUP: without
    # the dedicated entry it would fall to the per-element path.
    family_only = re.compile(
        r'(GROUP_\w+(?:list)?|\w+_ROWS|RESULT_STATUS|TIME_ELAPSED_HOURS'
        r'|COALESCE|SHIFT|BASELINE_BYlist|XAGG_\w+|APPEND)\s*\(')
    r.check("the pre-existing patterns do not cover INDEX_BY_GROUP",
            bool(family_only.search(u"INDEX_BY_GROUP([a],[b],c,[d])")), False)

    # INDEX_BY's inlining rewrite must not swallow INDEX_BY_GROUP: four
    # arguments through a three-argument rewrite is a silent mangling.
    index_by_re = re.compile(
        r'INDEX_BY(?!_)\s*\(\s*\[([A-Za-z_]\w*)\]\s*,\s*\[([A-Za-z_]\w*)\]'
        r'\s*,\s*([^)]+)\)')
    r.check("the INDEX_BY rewrite still matches INDEX_BY",
            bool(index_by_re.search(u"INDEX_BY([a],[b],c)")), True)
    r.check("the INDEX_BY rewrite skips INDEX_BY_GROUP",
            bool(index_by_re.search(u"INDEX_BY_GROUP([a],[b],c,[d])")), False)
    r.check("and the source carries that guard",
            u"INDEX_BY(?!_)" in src, True)


def test_v16_docstrings_say_whether_they_inline(p, r):
    """Every array-path addition has to say it cannot be inlined.

    BASELINE_BYlist's docstring records why: inlining puts the whole
    formula on the array path, where `[col] / F(...)` is a list divided by
    a list, and the TypeError blanks the column with one line in the log.
    """
    for name in ("_index_by_group", "_xagg_nth2"):
        code = _find_code(p, name)
        r.check("found %s" % name, code is not None, True)
    src = open(p.__source_path__, "rb").read().decode("utf-8")
    start = src.index(u"def _index_by_group(")
    body = src[start:start + 3000]
    r.check("INDEX_BY_GROUP's docstring warns against inlining it",
            u"BASELINE_BYlist" in body and u"TypeError" in body, True)


# ---------------------------------------------------------------------------
# ⑤ INDEX_BY_GROUP
# ---------------------------------------------------------------------------

def test_index_by_group(p, r):
    """⑤: the main peak's RT per injection, not one value for the table."""
    install_engine_stubs()
    owner = _FakeOwner()
    fn = rebuild(p, "_index_by_group", freevars={
        "_norm_key": rebuild(p, "_norm_key"),
        "_xagg_warn": rebuild(p, "_xagg_warn"),
        "self": owner,
    })
    r.check("rebuilt INDEX_BY_GROUP", fn is not None, True)
    if fn is None:
        return

    main = u"主峰"
    rt = [3.00, 10.1, 3.05, 10.2, 3.11, 10.3]
    names = [main, A, main, A, main, A]
    groups = [u"S1", u"S1", u"S2", u"S2", u"S3", u"S3"]

    r.check("each row gets its OWN injection's main-peak RT",
            fn(rt, names, [main] * 6, groups),
            [3.00, 3.00, 3.05, 3.05, 3.11, 3.11])

    r.check("a scalar 要匹配的键 is broadcast",
            fn(rt, names, main, groups),
            [3.00, 3.00, 3.05, 3.05, 3.11, 3.11])

    # A group whose main peak was not recorded gets '---' -- not the whole
    # table's first match, which would belong to another injection.
    missing_names = [main, A, A, A, main, A]
    r.check("no match inside the group -> '---' for that group only",
            fn(rt, missing_names, [main] * 6, groups),
            [3.00, 3.00, p._PLACEHOLDER, p._PLACEHOLDER, 3.11, 3.11])

    logger = install_engine_stubs()
    before = len(logger.lines)
    dup_names = [main, main, main, A, main, A]
    r.check("more than one match -> the first",
            fn(rt, dup_names, [main] * 6, groups)[0], 3.00)
    r.check("and it warns", len(logger.lines) > before, True)

    # CJK keys arriving as utf-8 str rather than unicode (R13).
    r.check("utf-8 str keys compare equal to unicode ones",
            fn([1.0, 2.0], [main.encode("utf-8"), A], [main] * 2,
               [u"S1", u"S1"]),
            [1.0, 1.0])

    r.check("not given lists at all -> placeholder, with a reason logged",
            fn(3.0, main, main, u"S1"), p._PLACEHOLDER)


# ---------------------------------------------------------------------------
# through the real engine
# ---------------------------------------------------------------------------

def test_v16_through_the_engine(p, r):
    """The AS-25 shape end to end, on the real engine.

    The row space is computed by one field (the "no array deps" branch)
    and read by the next through [imp_ip_name], which only works across
    passes -- the same convergence the single-key XAGG test relies on.
    This is what proves the formulas the config line is about to write
    actually evaluate, rather than each closure being right on its own.
    """
    install_engine_stubs()

    def source(as_id, kw, names, groups, samples, reports):
        fields = [
            {"keyword": "imp_name", "title": u"物质名称",
             "result_type": "list", "value": json.dumps(names),
             "cross_referenceable": True},
            {"keyword": "imp_pct_group", "title": u"杂质分组",
             "result_type": "list", "value": json.dumps(groups),
             "cross_referenceable": True},
            {"keyword": "g_sample_id", "title": u"样品编号",
             "result_type": "list", "value": json.dumps(samples),
             "cross_referenceable": True},
            {"keyword": "imp_report", "title": u"报告值",
             "result_type": "list", "value": json.dumps(reports),
             "cross_referenceable": True},
        ]
        return {"as_id": as_id, "service_kw": kw, "fields": fields}

    _, analyses = build_sample([
        {"as_id": "STD", "service_kw": "std", "fields": [
            {"keyword": "imp_name", "title": u"物质名称",
             "result_type": "list", "value": json.dumps([A, B]),
             "cross_referenceable": True},
        ]},
        source("CHROM", "chrom",
               [A, A, A, U1, U1, U1],
               [u"", u"", u"", R085, R085, R085],
               [u"2", u"10", u"1", u"2", u"10", u"1"],
               [u"0.12", u"0.15", u"0.11", u"0.06", u"ND", u"＜0.05%"]),
        source("SPIKED", "spiked",
               [A, A, A],
               [u"", u"", u""],
               [u"1", u"2", u"3"],
               [u"0.13", u"0.14", u"0.12"]),
        {"as_id": "STAT", "service_kw": "imp_ip_stat", "fields": [
            {"keyword": "imp_ip_name", "title": u"统计项",
             "result_type": "calculatedlist",
             "formula": (u'XAGG_KEYS_WHERE2("imp_name","imp_pct_group",1,'
                         u'["std"],"imp_report",0.05,["chrom","spiked"])')},
            {"keyword": "imp_ip_group", "title": u"杂质分组",
             "result_type": "calculatedlist",
             "formula": (u'XAGG_KEYS_WHERE2("imp_name","imp_pct_group",2,'
                         u'["std"],"imp_report",0.05,["chrom","spiked"])')},
            {"keyword": "imp_ip_p1_v1", "title": u"第一人第1份",
             "result_type": "calculatedlist",
             "formula": (u'XAGG_NTH2("imp_report","imp_name","imp_pct_group",'
                         u'[imp_ip_name],[imp_ip_group],"g_sample_id",1,'
                         u'"chrom")')},
            {"keyword": "imp_ip_avg", "title": u"合并平均值",
             "result_type": "calculatedlist",
             "formula": (u'XAGG_AVG2("imp_report","imp_name","imp_pct_group",'
                         u'[imp_ip_name],[imp_ip_group],"chrom","spiked")')},
            {"keyword": "imp_ip_n", "title": u"有效个数",
             "result_type": "calculatedlist",
             "formula": (u'XAGG_COUNT2("imp_report","imp_name",'
                         u'"imp_pct_group",[imp_ip_name],[imp_ip_group],'
                         u'"chrom","spiked")')},
        ]},
    ])

    out = evaluate(p, analyses, ("STD", "CHROM", "SPIKED", "STAT"), passes=5)
    got = dict((k.split(".", 1)[1], json.loads(v))
               for k, v in out.items() if v)

    r.check("engine: row space", got.get("imp_ip_name"), [A, B, U1])
    r.check("engine: group column, row-aligned",
            got.get("imp_ip_group"), [u"", u"", R085])
    r.check("engine: the first injection by 样品编号 -- a mixed column",
            got.get("imp_ip_p1_v1"), [0.11, p._PLACEHOLDER, u"＜0.05%"])
    avg = got.get("imp_ip_avg") or []
    r.check("engine: mean over both operators", len(avg), 3)
    if len(avg) == 3:
        r.check("engine: 杂质A mean", round(avg[0], 6),
                round((0.12 + 0.15 + 0.11 + 0.13 + 0.14 + 0.12) / 6.0, 6))
        r.check("engine: 杂质B has no chromatography rows", avg[1],
                p._PLACEHOLDER)
        r.check("engine: 未知1 counts only its numeric injection",
                round(avg[2], 6), 0.06)
    r.check("engine: 有效个数", got.get("imp_ip_n"), [6, p._PLACEHOLDER, 1])


def test_v16_readme(p, r):
    """The README is the config line's reference -- it has to list them."""
    readme = os.path.normpath(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(p.__source_path__))),
        "..", "..", "README.md"))
    r.check("README found at %s" % readme, os.path.exists(readme), True)
    if not os.path.exists(readme):
        return
    text = open(readme, "rb").read().decode("utf-8")
    for name in ("XAGG_KEYS2", "XAGG_KEYS_WHERE2", "XAGG_NTH2", "XAGG_AVG2",
                 "XAGG_RSD2", "XAGG_MAX2", "XAGG_MIN2", "XAGG_COUNT2",
                 "INDEX_BY_GROUP"):
        r.check("README documents %s" % name, name in text, True)
    r.check("README records the RESULT_STATUS / RESULT_NUM coupling",
            u"＜0.05%" in text, True)
    r.check("README says the 指定杂质 rows carry an empty group",
            u"杂质分组" in text, True)


def main():
    p = load_patches()
    print("IMPORT OK  (no Zope instance started)")
    print("  source under test: %s" % p.__source_path__)

    r = Results()
    test_is_zero_marker(p, r)
    test_result_num_folds_the_new_labels(p, r)
    test_result_status_wording(p, r)
    test_result_status_feeds_result_num(p, r)
    test_xagg_keys2(p, r)
    test_xagg_keys_where2(p, r)
    test_xagg_op2(p, r)
    test_xagg_nth2(p, r)
    test_xagg_collect_columns_alignment(p, r)
    test_v16_registration(p, r)
    test_v16_docstrings_say_whether_they_inline(p, r)
    test_index_by_group(p, r)
    test_v16_through_the_engine(p, r)
    test_v16_readme(p, r)
    return r.report(
        "V16 engine capabilities: RESULT_STATUS wording + dual-key XAGG "
        "(KEYS2 / KEYS_WHERE2 / NTH2 / <OP>2) + INDEX_BY_GROUP")


if __name__ == "__main__":
    sys.exit(main())
