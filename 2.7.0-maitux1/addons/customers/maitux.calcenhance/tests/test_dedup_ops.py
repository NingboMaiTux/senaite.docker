# -*- coding: utf-8 -*-
"""Tests for the de-duplication family and LOOKUP2 (第二批 A/B/C/D).

Run inside the container (Python 2.7):

    MSYS_NO_PATHCONV=1 docker cp tests/ maituxlimslatest:/tmp/ce_tests/
    MSYS_NO_PATHCONV=1 docker exec maituxlimslatest python /tmp/ce_tests/test_dedup_ops.py

Exit code 0 means every case passed.  harness.py says what this can reach;
test_engine.py holds the rest of the engine's tests and the two helpers
imported from it are shared on purpose.

What each block is for:

    A  DISTINCT_SEQlist  -- 序号列.  The column exists so a reader can COUNT:
       the largest number in it IS how many impurities this run has to
       report.  Filling every row would be easier and would destroy exactly
       that, so the repeats are blank -- and blank is u"", never '---'.
    B  GROUP_REPORT_TOPlist -- 单杂报告值, the group's highest TIER, on the
       same rows as A.  Tested together with A because "same rows" is the
       requirement, not a coincidence.
    C  DISTINCT_<OP> -- statistics after de-duplication.  总杂 is a
       broadcast column; an RSD over it is diluted by the repeats and looks
       perfectly reasonable.
    D  LOOKUP2 -- two-field key, plus the dependency-propagation regexes
       that have to learn the new name or the downstream value goes stale.
"""

from __future__ import print_function

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import (  # noqa: E402
    Results, build_sample, evaluate, install_engine_stubs, load_patches,
    rebuild)
from test_engine import _registry_keys  # noqa: E402


class _FakeOwner(object):
    """Only the `id` the WARN lines quote."""

    id = "S2601-R01-imp_repeat"


A = u"杂质A"
B = u"杂质B"
U1 = u"未知1"
R085 = u"RRT0.85"
R120 = u"RRT1.20"


def _rebuild_dedup(p, owner):
    """Rebuild the 去重族 bottom-up through its shared cells."""
    norm_key = rebuild(p, "_norm_key")
    agg_stdev = rebuild(p, "_agg_stdev")
    agg_rsd = rebuild(p, "_agg_rsd", freevars={"_agg_stdev": agg_stdev})
    xagg_warn = rebuild(p, "_xagg_warn")
    first_rows = rebuild(p, "_distinct_first_rows", defaults=(None,),
                         freevars={"_norm_key": norm_key})
    report_rank = rebuild(p, "_report_rank")
    values_fn = rebuild(p, "_distinct_values", freevars={
        "_distinct_first_rows": first_rows,
        "_xagg_warn": xagg_warn,
        "self": owner,
    })
    agg_fn = rebuild(p, "_distinct_agg", freevars={
        "_distinct_values": values_fn})
    return {
        "first_rows": first_rows,
        "report_rank": report_rank,
        "seq": rebuild(p, "_distinct_seqlist", freevars={
            "_distinct_first_rows": first_rows}),
        "top": rebuild(p, "_group_report_toplist", freevars={
            "_distinct_first_rows": first_rows,
            "_report_rank": report_rank}),
        "rsd": rebuild(p, "_distinct_rsd", freevars={
            "_distinct_agg": agg_fn, "_agg_rsd": agg_rsd}),
        "range": rebuild(p, "_distinct_range", freevars={
            "_distinct_agg": agg_fn}),
        "max": rebuild(p, "_distinct_max", freevars={"_distinct_agg": agg_fn}),
        "min": rebuild(p, "_distinct_min", freevars={"_distinct_agg": agg_fn}),
        "avg": rebuild(p, "_distinct_avg", freevars={"_distinct_agg": agg_fn}),
        "count": rebuild(p, "_distinct_count", freevars={
            "_distinct_agg": agg_fn}),
    }


# ---------------------------------------------------------------------------
# A: DISTINCT_SEQlist
# ---------------------------------------------------------------------------

def test_distinct_seq_counts(p, r):
    """A 的核心判据: 3 个杂质 × 6 针 -> 1 …空×5… 2 …空×5… 3 …空×5…

    最大的那个序号 = 3 = 要外报的杂质个数.  That is the whole point of the
    column: 实验人员 reads it to check the report is complete.  A version
    that filled every row would pass a "looks right" eyeball test and lose
    exactly this.
    """
    install_engine_stubs()
    fns = _rebuild_dedup(p, _FakeOwner())
    f = fns["seq"]
    r.check("rebuilt DISTINCT_SEQlist", f is not None, True)
    if f is None:
        return

    groups = [R085] * 6 + [R120] * 6 + [u"RRT1.50"] * 6
    got = f(groups)
    r.check("18 rows in, 18 rows out", len(got), 18)
    r.check("序号 only on the first row of each group",
            got, [1] + [u""] * 5 + [2] + [u""] * 5 + [3] + [u""] * 5)

    numbered = [v for v in got if v != u""]
    r.check("最大序号 = 杂质个数", max(numbered), 3)
    r.check("有值的行数 = 杂质个数", len(numbered), 3)


def test_distinct_seq_blank_is_not_placeholder(p, r):
    """A 边界 1: 重复行是空字符串, 不是 '---'.

    '---' means "could not be computed" everywhere else in this package.
    Using it for "deliberately not shown" would read as a fault.
    """
    install_engine_stubs()
    f = _rebuild_dedup(p, _FakeOwner())["seq"]
    got = f([A, A, B])
    r.check("repeat row value", got[1], u"")
    r.check("repeat row is a unicode string, not the placeholder",
            isinstance(got[1], unicode) and got[1] != p._PLACEHOLDER, True)
    r.check("'---' appears nowhere in the column",
            p._PLACEHOLDER in got, False)
    r.check("first rows still numbered", [got[0], got[2]], [1, 2])


def test_distinct_seq_keys(p, r):
    """A: 单键 / 双键 / 中文 / 空键值."""
    install_engine_stubs()
    f = _rebuild_dedup(p, _FakeOwner())["seq"]

    # 双键: 同名不同组是两个杂质 (AS-12 的理由)
    names = [U1, U1, U1, U1]
    groups = [R085, R085, R120, R120]
    r.check("single key merges the two 未知1 rows",
            f(names), [1, u"", u"", u""])
    r.check("dual key keeps them apart",
            f(names, groups), [1, u"", 2, u""])

    # 中文键: 一半是 utf-8 str, 一半是 unicode -- 不归一就会被拆成两组,
    # 序号因此多数一个, 而且不报错 (R13).
    mixed = [A, A.encode("utf-8"), A, B]
    r.check("str and unicode spellings of one CJK name are ONE group",
            f(mixed), [1, u"", u"", 2])

    # 空键值也是一种身份 -- 指定杂质那几行的杂质分组就是空的 (裁决 §5-D1),
    # 跳过它就会少数一个要外报的杂质.
    r.check("an empty key is a group of its own, and is numbered",
            f([u"", u"", R085]), [1, u"", 2])
    r.check("None and u'' are the same key",
            f([None, u"", R085]), [1, u"", 2])

    r.check("no key column at all -> placeholder, not a lone 1",
            f(), [p._PLACEHOLDER])


# ---------------------------------------------------------------------------
# B: GROUP_REPORT_TOPlist
# ---------------------------------------------------------------------------

def test_report_rank(p, r):
    """B: the tier function -- 数字 > ＜x% > ND > 没数据."""
    f = rebuild(p, "_report_rank")
    r.check("rebuilt _report_rank", f is not None, True)
    if f is None:
        return
    r.check("a number is the top tier", f(0.12)[0], 3)
    r.check("a numeric string counts as a number", f(u"0.12")[0], 3)
    r.check("below-limit marker is the middle tier", f(u"＜0.05%")[0], 2)
    r.check("its magnitude comes from the number inside",
            f(u"＜0.05%")[1], 0.05)
    r.check("ND is the bottom tier", f(u"ND")[0], 1)
    r.check("N.D. too", f(u"N.D.")[0], 1)
    r.check("empty is not a tier at all", f(u"")[0], 0)
    r.check("the placeholder is not a tier", f(p._PLACEHOLDER)[0], 0)
    r.check("unrecognised text is not a tier either", f(u"N/A")[0], 0)
    r.check("tiers order as 数字 > 标记 > ND",
            f(0.0) > f(u"＜0.05%") > f(u"ND") > f(u""), True)


def test_group_report_top(p, r):
    """B: 四种组各一条 + 组内取大 (实验人员 Q4a「不在同一象限，取大值」)."""
    install_engine_stubs()
    f = _rebuild_dedup(p, _FakeOwner())["top"]
    r.check("rebuilt GROUP_REPORT_TOPlist", f is not None, True)
    if f is None:
        return

    def top(values, keys):
        return f(values, keys)

    r.check("全数字 -> 最大的那个数字",
            top([0.12, 0.15, 0.11], [A] * 3), [0.15, u"", u""])
    r.check("全 ＜0.05% -> ＜0.05%（GROUP_MAXlist 在这里给的是占位符）",
            top([u"＜0.05%"] * 3, [A] * 3), [u"＜0.05%", u"", u""])
    r.check("全 ND -> ND",
            top([u"ND", u"ND", u"ND"], [A] * 3), [u"ND", u"", u""])
    r.check("混合 -> 数字这一档赢",
            top([u"ND", 0.06, u"＜0.05%"], [A] * 3), [0.06, u"", u""])
    r.check("没有数字但有标记 -> 标记赢 ND",
            top([u"ND", u"＜0.05%", u"ND"], [A] * 3), [u"＜0.05%", u"", u""])
    r.check("同为标记档时取里面那个数大的",
            top([u"＜0.05%", u"＜0.1%"], [A] * 2), [u"＜0.1%", u""])
    r.check("N.D. 的写法原样回来，不被规整成 ND",
            top([u"N.D.", u"N.D."], [A] * 2), [u"N.D.", u""])
    r.check("整组没有一个有效值 -> 首行 '---'（这是真的算不出来）",
            top([u"", p._PLACEHOLDER, u"N/A"], [A] * 3),
            [p._PLACEHOLDER, u"", u""])

    # 双键 + 中文, 与 A 同一套语义
    r.check("双键分组",
            f([0.02, 0.03, 0.9, 0.8], [U1, U1, U1, U1],
              [R085, R085, R120, R120]),
            [0.03, u"", 0.9, u""])


def test_seq_and_top_line_up(p, r):
    """判据 5: A 与 B 的有值行完全一致.

    They share _distinct_first_rows for exactly this reason.  Two
    independent "have I seen this key" loops would drift apart the first
    time one of them grew a special case, and the drift shows up as
    「序号在这行、值在那行」-- nobody reads that as an error.
    """
    install_engine_stubs()
    fns = _rebuild_dedup(p, _FakeOwner())
    names = [A, A, A, U1, U1, U1, U1, U1, U1, B]
    groups = [u"", u"", u"", R085, R085, R085, R120, R120, R120, u""]
    values = [0.12, 0.15, 0.11, u"ND", u"＜0.05%", 0.06,
              0.02, 0.03, 0.01, u"ND"]

    seq = fns["seq"](names, groups)
    top = fns["top"](values, names, groups)
    r.check("same length", len(seq) == len(top) == 10, True)
    r.check("非空的行完全一致",
            [v != u"" for v in seq], [v != u"" for v in top])
    r.check("序号", seq, [1, u"", u"", 2, u"", u"", 3, u"", u"", 4])
    r.check("单杂报告值", top,
            [0.15, u"", u"", 0.06, u"", u"", 0.03, u"", u"", u"ND"])
    r.check("最大序号 = 要外报的条目数", max(v for v in seq if v != u""), 4)


# ---------------------------------------------------------------------------
# C: DISTINCT_<OP>
# ---------------------------------------------------------------------------

def test_distinct_stats(p, r):
    """判据 7: 重复不影响结果 —— 「6 行 × 重复 N 次」与「6 行」一致.

    总杂 is GROUP_SUMlist broadcast over every impurity row of a sample, so
    a plain RSD over that column counts each sample as many times as it has
    impurity rows.  n is inflated, the spread is diluted, and the number
    that comes out is smaller than the truth and perfectly plausible.
    """
    install_engine_stubs()
    fns = _rebuild_dedup(p, _FakeOwner())
    r.check("rebuilt DISTINCT_RSD", fns["rsd"] is not None, True)
    if fns["rsd"] is None:
        return

    samples = [u"S1", u"S2", u"S3", u"S4", u"S5", u"S6"]
    totals = [1.02, 1.10, 0.98, 1.05, 1.01, 1.08]

    flat_keys = []
    flat_values = []
    for index, sample in enumerate(samples):
        repeats = index + 2          # 2..7 impurity rows per sample
        flat_keys.extend([sample] * repeats)
        flat_values.extend([totals[index]] * repeats)

    plain_rsd = fns["rsd"](totals, samples)
    repeated_rsd = fns["rsd"](flat_values, flat_keys)
    r.check("去重后 RSD 不受重复次数影响", repeated_rsd, plain_rsd, tol=1e-12)
    r.check("而且确实算出了东西", plain_rsd > 0, True)

    r.check("DISTINCT_COUNT = 去重后的个数", fns["count"](flat_values,
                                                     flat_keys), 6)
    r.check("DISTINCT_RANGE", fns["range"](flat_values, flat_keys),
            max(totals) - min(totals), tol=1e-12)
    r.check("DISTINCT_MAX", fns["max"](flat_values, flat_keys), max(totals))
    r.check("DISTINCT_MIN", fns["min"](flat_values, flat_keys), min(totals))
    r.check("DISTINCT_AVG", fns["avg"](flat_values, flat_keys),
            sum(totals) / 6.0, tol=1e-12)

    # 一个值都没有 / 只有一个值
    r.check("没有数字 -> '---'", fns["rsd"]([u"ND", u""], [u"S1", u"S1"]),
            p._PLACEHOLDER)
    r.check("只有一个样品 -> RSD 无定义, '---'",
            fns["rsd"]([1.0, 1.0], [u"S1", u"S1"]), p._PLACEHOLDER)
    r.check("但 COUNT 说得出是 1", fns["count"]([1.0, 1.0], [u"S1", u"S1"]), 1)


def test_distinct_stats_warns_on_disagreement(p, r):
    """C: 同一个去重键下的行不一致时取首行并 warn.

    That means the de-dup key is the wrong one, and the consequence is
    "one of them was picked" -- a number that looks entirely reasonable.
    """
    logger = install_engine_stubs()
    fns = _rebuild_dedup(p, _FakeOwner())
    before = len(logger.lines)
    got = fns["max"]([1.0, 2.0, 5.0], [u"S1", u"S1", u"S2"])
    r.check("取的是每个键的首行值", got, 5.0)
    r.check("并且说了出来", len(logger.lines) > before, True)
    joined = " ".join(logger.lines[before:])
    r.check("日志点名了是哪个键", "S1" in joined, True)

    before = len(logger.lines)
    fns["max"]([1.0, 1.0, 5.0], [u"S1", u"S1", u"S2"])
    r.check("一致时不说话", len(logger.lines), before)


# ---------------------------------------------------------------------------
# D: LOOKUP2
# ---------------------------------------------------------------------------

def _lookup_fixture():
    """A 称样量 table: same impurity at three spike levels."""
    return {
        u"weigh": {
            u"imp_name": [A, A, A, B, B, B],
            u"imp_spike_level": [u"80%", u"100%", u"120%"] * 2,
            u"imp_weigh": [10.1, 10.2, 10.3, 20.1, 20.2, 20.3],
            u"one_row": 42.0,
        },
        u"dup": {
            u"imp_name": [A, A],
            u"imp_spike_level": [u"100%", u"100%"],
            u"imp_weigh": [1.0, 2.0],
        },
        u"empty": {
            u"imp_name": [],
            u"imp_spike_level": [],
            u"imp_weigh": [],
        },
    }


def _lookups(p):
    """(logger, LOOKUP, LOOKUP2).

    The logger comes back from here on purpose: install_engine_stubs()
    REBINDS bika.lims.logger every call, so a logger captured before this
    one is not the object the code under test writes to -- an assertion on
    it would silently pass forever.
    """
    logger = install_engine_stubs()
    lookup, lookup2 = p._make_lookup(_lookup_fixture())
    return logger, lookup, lookup2


def test_make_lookup_returns_both(p, r):
    """D: _make_lookup now hands back both spellings.

    One factory, one `sibling_data` closure, one set of "has this been
    captured yet" rules -- a second factory would have to copy them, and two
    copies of that rule is how the two spellings drift apart.
    """
    install_engine_stubs()
    pair = p._make_lookup(_lookup_fixture())
    r.check("returns a 2-tuple", isinstance(pair, tuple) and len(pair) == 2,
            True)
    lookup, lookup2 = pair
    r.check("LOOKUP still works", lookup(u"weigh", u"imp_weigh",
                                        u"imp_name", A), 10.1)
    r.check("LOOKUP2 is callable", callable(lookup2), True)


def test_lookup2_two_keys(p, r):
    """D: 两个键都要命中 —— 单键取回来的是别的加标水平那一行."""
    _logger, lookup, lookup2 = _lookups(p)

    r.check("单键 LOOKUP 只能拿到第一行（这正是要解决的问题）",
            lookup(u"weigh", u"imp_weigh", u"imp_name", A), 10.1)
    r.check("LOOKUP2 标量形式", lookup2(u"weigh", u"imp_weigh",
                                    u"imp_name", A,
                                    u"imp_spike_level", u"120%"), 10.3)
    r.check("换一个键值就换一行", lookup2(u"weigh", u"imp_weigh",
                                  u"imp_name", B,
                                  u"imp_spike_level", u"100%"), 20.2)

    r.check("元素级：两列键并排",
            lookup2(u"weigh", u"imp_weigh", u"imp_name", [A, B, A],
                    u"imp_spike_level", [u"80%", u"120%", u"100%"]),
            [10.1, 20.3, 10.2])
    r.check("一列键 + 一个广播的标量键",
            lookup2(u"weigh", u"imp_weigh", u"imp_name", [A, B],
                    u"imp_spike_level", u"100%"),
            [10.2, 20.2])
    r.check("键值也可以是 JSON 数组文本（[kw] 替换进来的形状）",
            lookup2(u"weigh", u"imp_weigh", u"imp_name",
                    json.dumps([A, B]), u"imp_spike_level",
                    json.dumps([u"80%", u"80%"])),
            [10.1, 20.1])

    # 中文键的 str / unicode 边界 (R13)
    r.check("utf-8 str 键值与 unicode 列相等",
            lookup2(u"weigh", u"imp_weigh", u"imp_name", A.encode("utf-8"),
                    u"imp_spike_level", u"80%"), 10.1)


def test_lookup2_failures(p, r):
    """D: 找不到 / 多行 / 列不齐 / 字段缺失 —— 每一种都要看得见."""
    logger, lookup, lookup2 = _lookups(p)

    r.raises("没有匹配行时抛 KeyError（调用方据此出 '---'）",
             KeyError, lookup2, u"weigh", u"imp_weigh", u"imp_name", A,
             u"imp_spike_level", u"200%")
    r.check("给了默认值就用默认值",
            lookup2(u"weigh", u"imp_weigh", u"imp_name", A,
                    u"imp_spike_level", u"200%", 0.0), 0.0)
    r.check("元素级下默认值逐行生效",
            lookup2(u"weigh", u"imp_weigh", u"imp_name", [A, A],
                    u"imp_spike_level", [u"80%", u"200%"], 0.0),
            [10.1, 0.0])

    r.raises("源 AS 不存在", KeyError, lookup2, u"nobody", u"imp_weigh",
             u"imp_name", A, u"imp_spike_level", u"80%")
    r.raises("字段不存在", KeyError, lookup2, u"weigh", u"nope",
             u"imp_name", A, u"imp_spike_level", u"80%")
    r.raises("列是空的 = 还没录入，不是空结果", KeyError, lookup2,
             u"empty", u"imp_weigh", u"imp_name", A,
             u"imp_spike_level", u"80%")
    r.raises("两列键值行数不同时拒绝配对", ValueError, lookup2,
             u"weigh", u"imp_weigh", u"imp_name", [A, B],
             u"imp_spike_level", [u"80%"])
    r.raises("键字段必须是字符串", TypeError, lookup2, u"weigh",
             u"imp_weigh", 1, A, u"imp_spike_level", u"80%")

    before = len(logger.lines)
    r.check("命中多行取第一行",
            lookup2(u"dup", u"imp_weigh", u"imp_name", A,
                    u"imp_spike_level", u"100%"), 1.0)
    r.check("并且 warn 了一条", len(logger.lines) > before, True)

    # 标量值列（整张表共用一个值）广播到每一行：同一个存储值
    # 不能“第 0 行答得出、第 3 行报错”。
    r.check("标量值列被广播到每一行",
            [lookup2(u"weigh", u"one_row", u"imp_name", A,
                     u"imp_spike_level", level)
             for level in (u"80%", u"120%")],
            [42.0, 42.0])
    # 但“广播”不等于“不用匹配”—— 不给 LOOKUP 那条「省略键 = 取那
    # 唯一一行」的捷径，否则用两个键消歧义的意义就没了。
    r.raises("键对不上时标量值列照样报错", KeyError, lookup2,
             u"weigh", u"one_row", u"imp_name", A,
             u"imp_spike_level", u"200%")


def test_lookup2_is_a_dependency(p, r):
    """D: 依赖传播必须认识 LOOKUP2.

    `_LOOKUP_SRC_RE` used to read `LOOKUP\\s*\\(`, which does not match
    `LOOKUP2(`.  A formula whose only cross-AS reference is a LOOKUP2 would
    look dependency-free: computed once, then never refreshed when the
    source changes.  No '---', no log line -- just an old number on screen.
    That is the exact failure v1.5.0 fixed for LOOKUP.
    """
    sources = p._extract_lookup_sources(
        u'LOOKUP2("imp_rec_weigh","imp_weigh","imp_name",[imp_name],'
        u'"imp_spike_level",[imp_spike_level])')
    r.check("LOOKUP2 的源 AS 被登记为依赖",
            u"imp_rec_weigh" in sources, True)
    r.check("LOOKUP 的照旧",
            u"a" in p._extract_lookup_sources(u'LOOKUP("a","b","c",1)'), True)
    r.check("动态选源也认 LOOKUP2",
            p._lookup_has_dynamic_source(u'LOOKUP2([src],"b","c",1,"d",2)'),
            True)
    r.check("字面量源不算动态",
            p._lookup_has_dynamic_source(u'LOOKUP2("src","b","c",1,"d",2)'),
            False)


# ---------------------------------------------------------------------------
# registration + through the engine
# ---------------------------------------------------------------------------

def test_dedup_registration(p, r):
    """全部注册, 且路由到数组路径."""
    safe = _registry_keys(p, "_SAFE")
    scalar = _registry_keys(p, "safe_globals")
    for name in ("DISTINCT_SEQlist", "GROUP_REPORT_TOPlist", "DISTINCT_RSD",
                 "DISTINCT_RANGE", "DISTINCT_MAX", "DISTINCT_MIN",
                 "DISTINCT_AVG", "DISTINCT_COUNT", "LOOKUP2"):
        r.check("%s registered in _SAFE" % name, name in safe, True)
    r.check("LOOKUP2 also in the scalar table, like LOOKUP",
            "LOOKUP2" in scalar, True)
    r.check("DISTINCT_* stay out of the scalar table",
            [n for n in scalar if n.startswith("DISTINCT_")], [])

    src = open(p.__source_path__, "rb").read().decode("utf-8")
    r.check("DISTINCT_\\w+ named in the dispatch regex in source",
            u"|DISTINCT_\\w+)" in src, True)

    array_fn_re = re.compile(
        r'(GROUP_\w+(?:list)?|\w+_ROWS|RESULT_STATUS|TIME_ELAPSED_HOURS'
        r'|COALESCE|SHIFT|BASELINE_BYlist|XAGG_\w+|APPEND|INDEX_BY_GROUP'
        r'|DISTINCT_\w+)\s*\(')
    for name in ("DISTINCT_SEQlist", "DISTINCT_RSD", "DISTINCT_COUNT"):
        r.check("%s takes the array path" % name,
                bool(array_fn_re.search(u"%s([a],[b])" % name)), True)
    r.check("GROUP_REPORT_TOPlist rides the GROUP_ entry (no regex change)",
            bool(array_fn_re.search(u"GROUP_REPORT_TOPlist([a],[b])")), True)

    # 没有 DISTINCT_ 那条的话它们会掉到逐元素路径, 那里只看得见一个格,
    # 「去重」这件事根本无从谈起 —— 而且不报错.
    without = re.compile(
        r'(GROUP_\w+(?:list)?|\w+_ROWS|RESULT_STATUS|TIME_ELAPSED_HOURS'
        r'|COALESCE|SHIFT|BASELINE_BYlist|XAGG_\w+|APPEND|INDEX_BY_GROUP)'
        r'\s*\(')
    r.check("the pre-existing alternation does not cover DISTINCT_SEQlist",
            bool(without.search(u"DISTINCT_SEQlist([a])")), False)


def test_dedup_through_the_engine(p, r):
    """AS-10 的形状端到端跑真引擎: 序号列 + 单杂报告值 + 去重 RSD."""
    install_engine_stubs()

    names = [A, A, A, U1, U1, U1]
    groups = [u"", u"", u"", R085, R085, R085]
    reports = [0.12, 0.15, 0.11, u"ND", u"＜0.05%", 0.06]
    totals = [1.02, 1.02, 1.02, 1.10, 1.10, 1.10]
    samples = [u"S1", u"S1", u"S1", u"S2", u"S2", u"S2"]

    def column(keyword, title, value):
        return {"keyword": keyword, "title": title, "result_type": "list",
                "value": json.dumps(value)}

    _, analyses = build_sample([
        {"as_id": "REP", "service_kw": "imp_repeat", "fields": [
            column("imp_name", u"物质名称", names),
            column("imp_pct_group", u"杂质分组", groups),
            column("imp_report", u"报告值", reports),
            column("imp_total", u"总杂", totals),
            column("g_sample_id", u"样品编号", samples),
            {"keyword": "imp_seq", "title": u"序号",
             "result_type": "calculatedlist",
             "formula": u"DISTINCT_SEQlist([imp_name], [imp_pct_group])"},
            {"keyword": "imp_single_top", "title": u"单杂报告值（%）",
             "result_type": "calculatedlist",
             "formula": (u"GROUP_REPORT_TOPlist([imp_report], [imp_name], "
                         u"[imp_pct_group])")},
            {"keyword": "imp_total_rsd", "title": u"总杂RSD",
             "result_type": "calculatedlist",
             "formula": u"DISTINCT_RSD([imp_total], [g_sample_id])"},
            {"keyword": "imp_total_range", "title": u"总杂极差",
             "result_type": "calculatedlist",
             "formula": u"DISTINCT_RANGE([imp_total], [g_sample_id])"},
        ]},
    ])

    out = evaluate(p, analyses, ("REP",), passes=3)
    got = dict((k.split(".", 1)[1], json.loads(v))
               for k, v in out.items() if v)

    r.check("engine: 序号", got.get("imp_seq"),
            [1, u"", u"", 2, u"", u""])
    # 值原样回来，而本 AS 内的混合列到引擎这里已经是**文本**：
    # calculatedlist 的收集器对「并非整列都能转数」的 list 字段整列转字符串
    # （跟 _collect_cross_referenceable_data 逐格定类型不同）。显示上一样，
    # 但别在它外面套计算。
    r.check("engine: 单杂报告值与序号同行",
            got.get("imp_single_top"), [u"0.15", u"", u"", u"0.06", u"", u""])
    total_range = got.get("imp_total_range") or []
    r.check("engine: 总杂极差只算了两个值", len(total_range), 1)
    if len(total_range) == 1:
        r.check("engine: 总杂极差（两份样品）",
                total_range[0], 1.10 - 1.02, tol=1e-9)
    rsd = got.get("imp_total_rsd") or []
    r.check("engine: 总杂RSD 只算了两个值", len(rsd), 1)
    if len(rsd) == 1:
        values = [1.02, 1.10]
        mean = sum(values) / 2.0
        stdev = (sum((v - mean) ** 2 for v in values)) ** 0.5
        r.check("engine: 总杂RSD 的数", rsd[0], stdev / mean * 100.0,
                tol=1e-9)


def test_dedup_readme(p, r):
    """README 是配置线的参考, 新函数要在里面."""
    readme = os.path.normpath(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(p.__source_path__))),
        "..", "..", "README.md"))
    r.check("README found at %s" % readme, os.path.exists(readme), True)
    if not os.path.exists(readme):
        return
    text = open(readme, "rb").read().decode("utf-8")
    for name in ("DISTINCT_SEQlist", "GROUP_REPORT_TOPlist", "DISTINCT_RSD",
                 "DISTINCT_RANGE", "DISTINCT_MAX", "DISTINCT_MIN",
                 "DISTINCT_AVG", "DISTINCT_COUNT", "LOOKUP2",
                 # 1.17.0 (修约位数随值传递 S4 / S5)
                 "GROUP_AVG_TOPlist", "EARLIEST_TIME"):
        r.check("README documents %s" % name, name in text, True)
    r.check("README 写明序号列是用来数个数的",
            u"有几个" in text or u"个数" in text, True)
    r.check("README 写明重复行是空、不是 '---'",
            u"不是 '---'" in text or u"不是 `---`" in text, True)


def test_group_avg_top_through_the_engine(p, r):
    """S4 (修约位数随值传递 Backlog): GROUP_AVG_TOPlist, the Q1-A mean.

    Driven through the real engine: the function is only useful if the
    array path finds it (GROUP_\w+ in _ARRAY_FN_RE) and if the report
    column it reads is RESULT_STATUS's own output.
    """
    install_engine_stubs()

    def run(fields):
        _, analyses = build_sample([{
            "as_id": "AS1", "service_kw": "s4avg", "fields": fields}])
        out = evaluate(p, analyses, ("AS1",))
        return dict((k.split(".", 1)[1], json.loads(v))
                    for k, v in out.items() if v and v.startswith("["))

    def col(kw, values):
        return {"keyword": kw, "result_type": "list",
                "value": json.dumps(values)}

    # -- 裁决 Q1 的例子: 0.06 / 0.05 / ＜0.05% / ＜0.05% / ND / ND ----------
    pct = [u"0.061", u"0.052", u"0.031", u"0.029", u"0.004", u"0.003"]
    rep = [u"0.06", u"0.05", u"＜0.05%", u"＜0.05%", u"ND", u"ND"]
    got = run([
        col("imp_pct_num", pct), col("imp_report", rep),
        col("imp_pct_group", [u"Z1"] * 6),
        {"keyword": "avg", "result_type": "calculatedlist",
         "formula": u"GROUP_AVG_TOPlist([imp_pct_num],[imp_report],"
                    u"[imp_pct_group])"},
        {"keyword": "avg_r", "result_type": "calculatedlist",
         "formula": u"ROUND_EVEN(GROUP_AVG_TOPlist([imp_pct_num],"
                    u"[imp_report],[imp_pct_group]), 4)"},
        {"keyword": "old", "result_type": "calculatedlist",
         "formula": u"GROUP_AVGlist([imp_pct_num],[imp_pct_group])"},
    ])
    r.check("S4 Q1 example: only the two reportable injections",
            [round(v, 9) for v in got.get("avg", [])],
            [round((0.061 + 0.052) / 2, 9)] * 6)
    r.check("S4 Q1 example, rounded after averaging",
            got.get("avg_r"), [u"0.0565"] * 6)
    r.check("S4 differs from GROUP_AVGlist (which averages all six)",
            round(got.get("old", [0])[0], 9),
            round(sum(float(v) for v in pct) / 6, 9))

    # -- bands 2 and 1, and a group with nothing usable --------------------
    got = run([
        col("v", [u"0.03", u"0.02", u"0.001", u"0.004", u"0.002",
                  u"0.5", u"0.6"]),
        col("rep", [u"＜0.05%", u"＜0.05%", u"ND",
                    u"ND", u"ND",
                    u"---", u""]),
        col("g", [u"A", u"A", u"A", u"B", u"B", u"C", u"C"]),
        {"keyword": "avg", "result_type": "calculatedlist",
         "formula": u"GROUP_AVG_TOPlist([v],[rep],[g])"},
    ])
    avg = got.get("avg", [])
    r.check("S4 band 2 (＜x%) beats ND",
            [round(x, 9) for x in avg[:3]], [0.025] * 3)
    r.check("S4 all ND: every injection takes part",
            [round(x, 9) for x in avg[3:5]], [0.003] * 2)
    r.check("S4 no band at all -> '---', not 0", avg[5:], [u"---"] * 2)

    # -- dual key (AS-12: [imp_name],[imp_pct_group]) ----------------------
    got = run([
        col("v", [u"0.10", u"0.20", u"0.30", u"0.40"]),
        col("rep", [u"0.10", u"ND", u"0.30", u"0.40"]),
        col("name", [u"甲", u"甲", u"乙", u"乙"]),
        col("grp", [u"R0.85", u"R0.85", u"R0.85", u"R0.85"]),
        {"keyword": "avg", "result_type": "calculatedlist",
         "formula": u"GROUP_AVG_TOPlist([v],[rep],[name],[grp])"},
    ])
    r.check("S4 dual key keeps the two impurities apart",
            [round(x, 9) for x in got.get("avg", [])],
            [0.1, 0.1, 0.35, 0.35])

    # -- the ≥ boundary, through RESULT_STATUS: equal to the report limit
    #    is reported as a number, so it is in the top band ------------------
    got = run([
        col("v", [u"0.05", u"0.049", u"0.01"]),
        col("g", [u"Z", u"Z", u"Z"]),
        {"keyword": "loq", "result_type": "", "value": u"0.05"},
        {"keyword": "lod", "result_type": "", "value": u"0.02"},
        {"keyword": "rep", "result_type": "calculatedlist",
         "formula": u"RESULT_STATUS([v],[loq],[lod])"},
        {"keyword": "avg", "result_type": "calculatedlist",
         "formula": u"GROUP_AVG_TOPlist([v],[rep],[g])"},
    ])
    r.check("S4 boundary: RESULT_STATUS reports the =loq injection",
            got.get("rep", [None])[0] not in (u"ND", u"---")
            and not unicode(got.get("rep", [u""])[0]).startswith(u"＜"),
            True)
    r.check("S4 boundary: =报告限 is in the top band on its own",
            [round(x, 9) for x in got.get("avg", [])], [0.05] * 3)


def test_group_avg_top_shares_the_banding(p, r):
    """S4: one banding, not two -- GROUP_AVG_TOPlist reuses _report_rank
    and _distinct_first_rows exactly as GROUP_REPORT_TOPlist does."""
    src = open(p.__source_path__, "rb").read().decode("utf-8")
    start = src.index(u"    def _group_avg_toplist(")
    end = src.index(u"\n    def ", start + 10)
    body = src[start:end]
    r.check("S4 uses _report_rank", u"_report_rank(" in body, True)
    r.check("S4 uses _distinct_first_rows",
            u"_distinct_first_rows(" in body, True)
    r.check("S4 has no banding of its own (no prefix/ND tests)",
            u"_BELOW_LIMIT_PREFIXES" in body or u"_is_zero_marker" in body,
            False)
    r.check("S4 registered", u'"GROUP_AVG_TOPlist": _group_avg_toplist'
            in src, True)


def main():
    p = load_patches()
    print("IMPORT OK  (no Zope instance started)")
    print("  source under test: %s" % p.__source_path__)

    r = Results()
    test_distinct_seq_counts(p, r)
    test_distinct_seq_blank_is_not_placeholder(p, r)
    test_distinct_seq_keys(p, r)
    test_report_rank(p, r)
    test_group_report_top(p, r)
    test_seq_and_top_line_up(p, r)
    test_distinct_stats(p, r)
    test_distinct_stats_warns_on_disagreement(p, r)
    test_make_lookup_returns_both(p, r)
    test_lookup2_two_keys(p, r)
    test_lookup2_failures(p, r)
    test_lookup2_is_a_dependency(p, r)
    test_dedup_registration(p, r)
    test_dedup_through_the_engine(p, r)
    test_dedup_readme(p, r)
    test_group_avg_top_through_the_engine(p, r)
    test_group_avg_top_shares_the_banding(p, r)
    return r.report(
        "去重族: DISTINCT_SEQlist / GROUP_REPORT_TOPlist / DISTINCT_<OP> "
        "+ LOOKUP2")


if __name__ == "__main__":
    sys.exit(main())
