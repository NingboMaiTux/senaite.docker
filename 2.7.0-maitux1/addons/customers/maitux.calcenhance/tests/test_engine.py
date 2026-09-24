# -*- coding: utf-8 -*-
"""Tests for the module-level formula helpers in patches.py.

Run inside the container (Python 2.7):

    MSYS_NO_PATHCONV=1 docker cp tests/ maituxlimslatest:/tmp/ce_tests/
    MSYS_NO_PATHCONV=1 docker exec maituxlimslatest python /tmp/ce_tests/test_engine.py

Exit code 0 means every case passed.  See harness.py for what this can and
cannot reach.
"""

from __future__ import print_function

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import (  # noqa: E402
    Results, build_sample, evaluate, install_engine_stubs, load_patches,
    rebuild)


# Values recorded from the pre-hoist source, so a typo during the move shows
# up here rather than as a subtly wrong confidence interval months later.
T_95_BEFORE_HOIST = {
    1: 12.706205, 2: 4.302653, 3: 3.182446, 4: 2.776445,
    5: 2.570582, 6: 2.446912, 7: 2.364624, 8: 2.306004,
    9: 2.262157, 10: 2.228139,
}


def test_module_level_visibility(p, r):
    """S0: the hoisted helpers have to be reachable, or nothing else is."""
    for name in ("_PLACEHOLDER", "_num_or_none", "_T_95",
                 "_skip_avg", "_is_missing", "_MISSING"):
        r.check("visible %s" % name, hasattr(p, name), True)

    # The nested copies must be gone.  If one survived it would shadow the
    # module-level definition inside the evaluator, and the hoisted version
    # would be dead code that tests happily exercise while production runs
    # something else.
    src = open(p.__source_path__, "rb").read().decode("utf-8")
    r.check("no nested _num_or_none", src.count(u"def _num_or_none"), 1)
    r.check("no nested _T_95", src.count(u"_T_95 = "), 1)


def test_num_or_none(p, r):
    """S0: the numeric coercion every row statistic is built on."""
    f = p._num_or_none
    cases = [
        ("None", None, None),
        ("empty unicode", u"", None),
        ("whitespace", u"   ", None),
        ("padded number", u" 12.5 ", 12.5),
        ("non-numeric text", u"abc", None),
        ("bool True", True, 1.0),
        ("bool False", False, 0.0),
        ("int", 7, 7.0),
        ("float", 2.5, 2.5),
        ("numeric unicode", u"97816", 97816.0),
        ("placeholder", u"---", None),
        ("negative", u"-958.88", -958.88),
        ("scientific", u"1e3", 1000.0),
    ]
    for label, value, want in cases:
        r.check("_num_or_none(%s)" % label, f(value), want)

    # CJK must not blow up: str(u"中文") raises UnicodeEncodeError on Py2,
    # which is the trap this package exists to guard against.
    r.check("_num_or_none(CJK)", f(u"中文"), None)


def test_t_95_table(p, r):
    """S0: the t table survived the move byte for byte."""
    table = p._T_95
    r.check("_T_95 key count", len(table), len(T_95_BEFORE_HOIST))
    for df, want in sorted(T_95_BEFORE_HOIST.items()):
        r.check("_T_95[%d]" % df, table.get(df), want)

    # df = 4 is the value the linearity example reverse-solves to; calling it
    # out separately because a wrong t here is invisible downstream.
    r.check("_T_95[4] is the 6-point regression t", table.get(4), 2.776445)

    # Out-of-table df must be absent rather than extrapolated.
    r.check("_T_95 has no df=0", table.get(0), None)
    r.check("_T_95 has no df=11", table.get(11), None)


def _walk_code(code):
    """Every code object nested inside `code`, itself included."""
    yield code
    for const in code.co_consts:
        if hasattr(const, "co_name"):
            for sub in _walk_code(const):
                yield sub


def _find_code(p, name):
    """The code object of a function nested inside the calculatedlist engine."""
    outer = p._evaluate_calculatedlist_interims.__code__
    for code in _walk_code(outer):
        if code.co_name == name:
            return code
    return None


def test_hoisted_names_resolve_as_globals(p, r):
    """S0: prove the closures still find the two hoisted names.

    This is the check the before/after interim snapshot CANNOT make.  Stored
    interim values are not recomputed by a restart, so a diff of them proves
    only that nothing was disturbed at rest -- it would look identical even if
    every formula had started raising NameError.  Name resolution happens at
    call time, and at the bytecode level it is decided at compile time: a name
    that is neither local nor in an enclosing scope compiles to LOAD_GLOBAL.
    So if these names appear in co_names (globals) and not in co_freevars
    (closure cells), the module-level definitions are what the engine will
    reach, and the hoist is sound.
    """
    outer = p._evaluate_calculatedlist_interims.__code__
    for name in ("_num_or_none", "_T_95"):
        # Not rebound anywhere inside the engine, or it would shadow again.
        r.check("%s not local to engine" % name, name in outer.co_varnames, False)
        r.check("%s not a cell in engine" % name, name in outer.co_cellvars, False)

    checks = [("_rows_regression", "_num_or_none"), ("_agg_ci", "_T_95")]
    for fn_name, global_name in checks:
        code = _find_code(p, fn_name)
        r.check("found nested %s" % fn_name, code is not None, True)
        if code is None:
            continue
        r.check("%s reads %s as a global" % (fn_name, global_name),
                global_name in code.co_names, True)
        r.check("%s does not close over %s" % (fn_name, global_name),
                global_name in code.co_freevars, False)


def test_rows_regression_runs(p, r):
    """S0: actually execute the row machinery that consumes _num_or_none.

    _rows_regression is nested, but it closes over nothing -- it only reads
    globals -- so it can be rebuilt against the module namespace and called
    for real.  That turns 'the name resolves' into 'the code runs and returns
    the right answer', which is the part that matters.
    """
    import types

    code = _find_code(p, "_rows_regression")
    if code is None:
        r.check("_rows_regression reachable", False, True)
        return
    r.check("_rows_regression closes over nothing", code.co_freevars, ())
    if code.co_freevars:
        return

    rows_regression = types.FunctionType(
        code, p.__dict__, "_rows_regression", (2,))

    # Two rows, two levels: y columns first, then x columns.
    ys1, ys2 = [2.0, 10.0], [4.0, 20.0]
    xs1, xs2 = [1.0, 5.0], [2.0, 10.0]
    counts = rows_regression(lambda ys, xs: len(ys), (ys1, ys2, xs1, xs2), 0)
    r.check("_rows_regression counts both rows", counts, [2, 2])

    # A missing cell drops that pair only -- this is the _num_or_none path.
    holed = rows_regression(
        lambda ys, xs: len(ys), ([2.0, 10.0], [None, 20.0], xs1, xs2), 0)
    r.check("_rows_regression skips the missing pair", holed, [1, 2])

    # An empty string is missing too (a part-blank column becomes text).
    blanked = rows_regression(
        lambda ys, xs: len(ys), ([2.0, 10.0], [u"", 20.0], xs1, xs2), 0)
    r.check("_rows_regression skips the blank pair", blanked, [1, 2])

    # Odd column count is refused rather than silently mis-paired.
    r.check("_rows_regression refuses odd column count",
            rows_regression(lambda ys, xs: len(ys), (ys1, ys2, xs1), 0), [])


def _registry_keys(p, table):
    """Names registered in one of the two eval namespaces.

    Both tables are written as ``{"__builtins__": {...}}``, so the outer key
    has to come off or every count is one too high -- which is exactly the
    kind of off-by-one that makes a "52 -> 54" prediction pass for the wrong
    reason.
    """
    src = open(p.__source_path__, "rb").read().decode("utf-8")
    anchor = {
        "_SAFE": u'_SAFE = {"__builtins__": {',
        "safe_globals": u'safe_globals = {"__builtins__": {',
    }[table]
    start = src.index(anchor) + len(anchor)
    depth = 1
    for pos in range(start, len(src)):
        if src[pos] == u"{":
            depth += 1
        elif src[pos] == u"}":
            depth -= 1
            if depth == 0:
                break
    return re.findall(r'"([A-Za-z_][A-Za-z_0-9]*)"\s*:', src[start:pos])


# Z7's six injections, from the gap document's worked example.  Row 1 is the
# same substance run only three times -- the case the fixed /6 divisor gets
# wrong -- so every assertion below tests per-row independence at the same
# time as the arithmetic.
SIX = [97816.0, 96710.0, 98251.0, 98596.0, 98715.0, 98112.0]
THREE = [50000.0, 50100.0, 50200.0]
AVG_SIX = sum(SIX) / 6.0        # 98033.3333...
AVG_THREE = sum(THREE) / 3.0    # 50100.0


def _columns(missing):
    """Six parallel columns, two rows; row 1 keeps 3 values then `missing`."""
    row1 = THREE + [missing, missing, missing]
    return [[SIX[i], row1[i]] for i in range(6)]


def test_avg_rows(p, r):
    """S1: horizontal mean, variable injection count."""
    f = p._avg_rows

    r.check("AVG_ROWS no columns", f(), [])

    got = f(*_columns(None))
    r.check("AVG_ROWS row0 all six", got[0], AVG_SIX, tol=1e-12)
    r.check("AVG_ROWS row1 three of six (None)", got[1], AVG_THREE, tol=1e-12)
    # The whole point: row 1 must NOT be sum/6.
    r.check("AVG_ROWS row1 is not /6", got[1] == sum(THREE) / 6.0, False)

    # A part-blank numeric column degrades to a string array upstream, so the
    # empty cells arrive as u"" rather than None.  Both must be skipped.
    got_blank = f(*_columns(u""))
    r.check("AVG_ROWS row1 three of six (blank)", got_blank[1], AVG_THREE,
            tol=1e-12)

    # The "---" placeholder is a missing cell too, not text to choke on.
    got_ph = f(*_columns(p._PLACEHOLDER))
    r.check("AVG_ROWS skips the placeholder", got_ph[1], AVG_THREE, tol=1e-12)

    # A row with nothing numeric yields "---", never 0.0.
    empty = f(*[[None], [u""], [p._PLACEHOLDER], [None], [None], [None]])
    r.check("AVG_ROWS all-missing row", empty, [p._PLACEHOLDER])
    r.check("AVG_ROWS all-missing is not 0.0", empty == [0.0], False)


def test_count_values_rows(p, r):
    """S1: the audit count that keeps the denominator visible."""
    f = p._count_values_rows

    r.check("COUNT_VALUES_ROWS no columns", f(), [])
    r.check("COUNT_VALUES_ROWS None-missing", f(*_columns(None)), [6, 3])
    r.check("COUNT_VALUES_ROWS blank-missing", f(*_columns(u"")), [6, 3])
    r.check("COUNT_VALUES_ROWS placeholder-missing",
            f(*_columns(p._PLACEHOLDER)), [6, 3])
    r.check("COUNT_VALUES_ROWS empty row counts 0",
            f(*[[None], [u""], [p._PLACEHOLDER]]), [0])


# Current size of each eval namespace.  ONE place on purpose: an absolute
# count is a shared, moving target, so per-slice copies of it are guaranteed
# to break the moment the next slice registers anything (S2 broke S1's copy
# immediately).  Bump these here as slices land; the per-slice tests below
# assert only the names they are responsible for.
#
#   52 baseline -> 54 (S1: AVG_ROWS, COUNT_VALUES_ROWS)
#              -> 55 (S2: CF_GATE, also +1 on the scalar table)
#              -> 61 (S3: six regression SE / CI wrappers)
#              -> 62 (S2 revised: CF_GATE dropped, BAND + GATE added,
#                     both tables -- the single-threshold rule was wrong)
#              -> 64 (S7: GROUP_CI_LOW / GROUP_CI_HIGH, array table only)
#              -> 65 (BASELINE_BYlist, array table only -- a different
#                     backlog: 稳定性基线取值 S1)
#              -> 66 (ROUND_UP, array table only -- completes the
#                     rounding family; array table because that is
#                     where ROUND / ROUND_EVEN already live)
#              -> 67 (ROUND_DOWN, array table only -- rs_stab_pct1's
#                     truncate-don't-carry requirement, mirrors ROUND_UP)
#              -> 69 (XAGG_KEYS, APPEND -- array table only; row-space
#                     builders for cross-AS aggregation, 跨AS聚合 S1)
#              -> 74 (XAGG_AVG/_RSD/_MAX/_MIN/_COUNT -- array table only;
#                     ride S1's XAGG_\w+ entry in _ARRAY_FN_RE, no regex
#                     change needed, 跨AS聚合 S2)
#              -> 79 (XAGG_AVG_OFSUM/_RSD_OFSUM/_MAX_OFSUM/_MIN_OFSUM/
#                     _COUNT_OFSUM -- array table only, all literal-arg
#                     "no array deps" like XAGG_KEYS; 跨AS聚合 S3)
#   (no arrow: this one moved the SCALAR table only) the rounding and
#              formatting family -- ROUND / ROUND_EVEN / ROUND_UP /
#              ROUND_DOWN / FORMAT -- was hoisted to module level so the
#              scalar engine could reference it too, taking that table 26
#              -> 31 and leaving _SAFE at 79.  Recorded late: the count had
#              been red ever since, which is how a shared counter fails --
#              everybody reads it, nobody owns it.
#              -> 88 (V16 引擎能力: XAGG_KEYS2 / XAGG_KEYS_WHERE2 /
#                     XAGG_NTH2 / XAGG_AVG2 / _RSD2 / _MAX2 / _MIN2 /
#                     _COUNT2 / INDEX_BY_GROUP -- array table only, the
#                     dual-key branch; 裁决 §7 ②③④⑤)
#              -> 97 (去重族 + LOOKUP2: DISTINCT_SEQlist /
#                     GROUP_REPORT_TOPlist / DISTINCT_RSD / _RANGE / _MAX /
#                     _MIN / _AVG / _COUNT on the array table, LOOKUP2 on
#                     BOTH -- the scalar table therefore goes 31 -> 32,
#                     the first time it has moved since the rounding hoist)
#              -> 98 (修约位数随值传递 S1: _Fixed on BOTH tables -- not a
#                     formula function, it is what repr(_Fixed) spells, so
#                     an inlined rounded column evals back; scalar 32 -> 33)
#              -> 99 (S4: GROUP_AVG_TOPlist -- array table only, it is a
#                     GROUP_*list; 有关物质 20260923 裁决 Q1 / §6-③)
#              -> 100 (S5: EARLIEST_TIME -- array table only; it is only
#                     meaningful as TIME_ELAPSED_HOURS's base, 裁决 §6-⑤)
EXPECTED_SAFE_ENTRIES = 100
EXPECTED_SCALAR_ENTRIES = 33


def test_registry_totals(p, r):
    """Both namespaces are exactly the size the slices account for."""
    r.check("_SAFE entry count",
            len(_registry_keys(p, "_SAFE")), EXPECTED_SAFE_ENTRIES)
    r.check("safe_globals entry count",
            len(_registry_keys(p, "safe_globals")), EXPECTED_SCALAR_ENTRIES)


def test_s1_registration(p, r):
    """S1: registered in the array table, and named so dispatch finds them."""
    safe = _registry_keys(p, "_SAFE")
    for name in ("AVG_ROWS", "COUNT_VALUES_ROWS"):
        r.check("%s registered in _SAFE" % name, name in safe, True)

    # The _ROWS suffix is what routes these to the array path.  Without it
    # they reach the per-element path, which short-circuits a row to "---" as
    # soon as one cell is missing -- silently defeating both functions.
    array_fn_re = re.compile(
        r'(GROUP_\w+(?:list)?|\w+_ROWS|RESULT_STATUS|TIME_ELAPSED_HOURS'
        r'|COALESCE|SHIFT)\s*\(')
    src = open(p.__source_path__, "rb").read().decode("utf-8")
    r.check("dispatch regex unchanged in source",
            array_fn_re.pattern.replace("\\\\", "\\") in src
            or u"|\\w+_ROWS|" in src, True)
    for name in ("AVG_ROWS", "COUNT_VALUES_ROWS"):
        r.check("%s takes the array path" % name,
                bool(array_fn_re.search(u"%s([a],[b])" % name)), True)


def test_band(p, r):
    """S2: the correction-factor band -- inside [low, high] use `inside`."""
    f = p._band
    CF = (0.8, 1.2, 1.0)   # the method's correction-factor rule

    # Outside the band, in EITHER direction, the measured factor applies.
    r.check("BAND(1.5) above band", f(1.5, *CF), 1.5)
    r.check("BAND(2.0) above band", f(2.0, *CF), 2.0)
    # ★ Below the band the value is KEPT.  A one-sided "x > 1.2" reading
    # would return 1.0 here; that is the case the two rules disagree on.
    r.check("BAND(0.7) below band keeps 0.7", f(0.7, *CF), 0.7)
    r.check("BAND(0.7) is not 1.0", f(0.7, *CF) == 1.0, False)

    # Inside the band the substitute is used.
    r.check("BAND(1.1) inside", f(1.1, *CF), 1.0)
    r.check("BAND(0.9) inside", f(0.9, *CF), 1.0)
    r.check("BAND(1.0) inside", f(1.0, *CF), 1.0)

    # ★ Both ends inclusive -- the method says "含边界".
    r.check("BAND(0.8) low edge is inside", f(0.8, *CF), 1.0)
    r.check("BAND(1.2) high edge is inside", f(1.2, *CF), 1.0)
    # And just outside the edges the value survives.
    r.check("BAND(0.7999) just below edge", f(0.7999, *CF), 0.7999)
    r.check("BAND(1.2001) just above edge", f(1.2001, *CF), 1.2001)

    # Real looked-up factors from the gap document (both land inside).
    r.check("BAND(0.920112627205) Z7", f(0.920112627205, *CF), 1.0)
    r.check("BAND(0.844329782844) Z13", f(0.844329782844, *CF), 1.0)

    # Text-valued input arrives from the engine often enough to matter.
    r.check("BAND(u'1.5')", f(u"1.5", *CF), 1.5)
    r.check("BAND(u'0.9')", f(u"0.9", *CF), 1.0)

    # Missing passes through: "never entered" is not "close enough to ignore".
    r.check("BAND placeholder passes through",
            f(p._PLACEHOLDER, *CF), p._PLACEHOLDER)
    r.check("BAND sentinel passes through", f(p._MISSING, *CF), p._MISSING)
    r.check("BAND placeholder is not replaced by 1.0",
            f(p._PLACEHOLDER, *CF) == 1.0, False)

    # Not missing, not comparable -> no result rather than a fabricated one.
    r.check("BAND(u'abc')", f(u"abc", *CF), p._PLACEHOLDER)

    # Every bound is required and must be numeric (Py2 would compare a number
    # against text without complaining and send every row one way).
    r.raises("BAND missing args", TypeError, f, 1.5, 0.8)
    r.raises("BAND text low", ValueError, f, 1.5, u"abc", 1.2, 1.0)
    r.raises("BAND text inside", ValueError, f, 1.5, 0.8, 1.2, u"abc")
    # An inverted band would match nothing and silently do nothing.
    r.raises("BAND inverted band", ValueError, f, 1.0, 1.2, 0.8, 1.0)


def test_gate(p, r):
    """S2: the reporting-limit gate -- keep from `threshold` upwards."""
    f = p._gate
    LIM = (0.05, 0)   # impurities >= 0.05% count toward the total

    r.check("GATE(0.06) above limit", f(0.06, *LIM), 0.06)
    r.check("GATE(1.2) well above", f(1.2, *LIM), 1.2)
    r.check("GATE(0.049) below limit", f(0.049, *LIM), 0)
    r.check("GATE(0.0) below limit", f(0.0, *LIM), 0)

    # ★ Inclusive: exactly at the limit the value is KEPT.  This is the
    # boundary that runs the opposite way from BAND's, and the reason the
    # two are separate functions.
    r.check("GATE(0.05) at limit is kept", f(0.05, *LIM), 0.05)
    r.check("GATE(0.05) is not zeroed", f(0.05, *LIM) == 0, False)

    r.check("GATE(u'0.07')", f(u"0.07", *LIM), 0.07)
    r.check("GATE placeholder passes through",
            f(p._PLACEHOLDER, *LIM), p._PLACEHOLDER)
    r.check("GATE sentinel passes through", f(p._MISSING, *LIM), p._MISSING)
    r.check("GATE(u'abc')", f(u"abc", *LIM), p._PLACEHOLDER)

    r.raises("GATE missing args", TypeError, f, 0.06)
    r.raises("GATE text threshold", ValueError, f, 0.06, u"abc", 0)
    r.raises("GATE text below", ValueError, f, 0.06, 0.05, u"abc")


def test_s2_registration(p, r):
    """S2: both present in BOTH namespaces; CF_GATE is gone."""
    safe = _registry_keys(p, "_SAFE")
    scalar = _registry_keys(p, "safe_globals")
    for name in ("BAND", "GATE"):
        r.check("%s in _SAFE" % name, name in safe, True)
        r.check("%s in safe_globals" % name, name in scalar, True)

    # The superseded single-threshold gate must be gone, not left as a
    # second way to spell a rule that turned out to be wrong.
    src = open(p.__source_path__, "rb").read().decode("utf-8")
    r.check("CF_GATE no longer registered", "CF_GATE" in safe, False)
    r.check("CF_GATE gone from the source", u"CF_GATE" in src, False)
    r.check("_cf_gate gone from the module", hasattr(p, "_cf_gate"), False)

    # No _ROWS suffix: both are scalar and must stay on the per-element path.
    array_fn_re = re.compile(
        r'(GROUP_\w+(?:list)?|\w+_ROWS|RESULT_STATUS|TIME_ELAPSED_HOURS'
        r'|COALESCE|SHIFT)\s*\(')
    for name in ("BAND", "GATE"):
        r.check("%s does not take the array path" % name,
                bool(array_fn_re.search(u"%s(LOOKUP(1),0.8,1.2,1.0)" % name)),
                False)


# The linearity example from the gap document: Excel's Regression output for
# these six points is the reference the implementation has to reproduce.
# Tolerance is relative 1e-3 because the x values as published are truncated,
# so the last digits legitimately differ from Excel's full-precision run.
LIN_X = [1.1222, 2.2444, 3.3667, 4.4889, 6.7333, 13.4666]
LIN_Y = [5686.0, 11451.0, 17787.0, 24316.0, 36649.0, 74747.0]
EXCEL = {
    "slope": 5613.540395,
    "intercept": -958.8823529,
    "se_slope": 24.12190117,
    "se_intercept": 160.1485071,
    "slope_lo": 5546.567261,
    "slope_hi": 5680.51353,
    "intercept_lo": -1403.525892,
    "intercept_hi": -514.2388142,
}
TOL = 1e-3


def test_reg_stats(p, r):
    """S3: the fit and the residual variance behind every interval."""
    stats = p._reg_stats(LIN_Y, LIN_X)
    r.check("_reg_stats returns something", stats is not None, True)
    if stats is None:
        return
    slope, intercept, mse, sxx, xbar, n = stats
    r.check("slope", slope, EXCEL["slope"], tol=TOL)
    r.check("intercept", intercept, EXCEL["intercept"], tol=TOL)
    r.check("n", n, 6)
    r.check("MSE uses n-2", mse > 0, True)

    # Too few points for a residual estimate: df = n-2 must be >= 1.
    r.check("_reg_stats n=2 is None", p._reg_stats([1.0, 2.0], [1.0, 2.0]),
            None)
    r.check("_reg_stats n=3 is not None",
            p._reg_stats([1.0, 2.0, 3.0], [1.0, 2.0, 3.1]) is not None, True)
    # No line is determined when every x is the same.
    r.check("_reg_stats flat x is None",
            p._reg_stats([1.0, 2.0, 3.0], [5.0, 5.0, 5.0]), None)


def test_reg_param_se_and_ci(p, r):
    """S3: standard errors and the two-sided 95% bounds, against Excel."""
    r.check("SE(slope)", p._reg_param_se(LIN_Y, LIN_X, "slope"),
            EXCEL["se_slope"], tol=TOL)
    r.check("SE(intercept)", p._reg_param_se(LIN_Y, LIN_X, "intercept"),
            EXCEL["se_intercept"], tol=TOL)

    r.check("slope CI low", p._reg_param_ci(LIN_Y, LIN_X, "slope", -1),
            EXCEL["slope_lo"], tol=TOL)
    r.check("slope CI high", p._reg_param_ci(LIN_Y, LIN_X, "slope", 1),
            EXCEL["slope_hi"], tol=TOL)
    r.check("intercept CI low",
            p._reg_param_ci(LIN_Y, LIN_X, "intercept", -1),
            EXCEL["intercept_lo"], tol=TOL)
    r.check("intercept CI high",
            p._reg_param_ci(LIN_Y, LIN_X, "intercept", 1),
            EXCEL["intercept_hi"], tol=TOL)

    # ★ Assert the t value itself, not just the bound.  A wrong df paired
    # with a wrong SE can land close enough to slip past a tolerance check;
    # recovering t from the half-width pins down which row of the table was
    # actually read.
    centre, se, n = p._reg_param(LIN_Y, LIN_X, "slope")
    hi = p._reg_param_ci(LIN_Y, LIN_X, "slope", 1)
    r.check("df is n-2, so t = _T_95[4]", (hi - centre) / se, 2.776445,
            tol=1e-9)
    r.check("t used is NOT the mean-CI t (_T_95[5])",
            abs((hi - centre) / se - p._T_95[5]) < 1e-6, False)

    # Degrees of freedom at both ends of the table.
    y3, x3 = [1.0, 2.1, 2.9], [1.0, 2.0, 3.0]
    r.check("n=3 (df=1) computes",
            isinstance(p._reg_param_ci(y3, x3, "slope", 1), float), True)
    r.check("n=2 (df=0) is the placeholder",
            p._reg_param_ci([1.0, 2.0], [1.0, 2.0], "slope", 1),
            p._PLACEHOLDER)

    # 12 points -> df=10, the last row of the table: must still compute.
    y12 = [float(i) for i in range(1, 13)]
    x12 = [float(i) * 1.5 for i in range(1, 13)]
    y12[3] += 0.4  # keep some residual, or MSE is 0 and SE degenerates
    r.check("n=12 (df=10) still in table",
            isinstance(p._reg_param_ci(y12, x12, "slope", 1), float), True)

    # 13 points -> df=11, off the end: "---", never an extrapolated t.
    y13 = y12 + [13.5]
    x13 = x12 + [19.5]
    r.check("n=13 (df=11) is the placeholder",
            p._reg_param_ci(y13, x13, "slope", 1), p._PLACEHOLDER)


def test_ci_rows_wrappers(p, r):
    """S3: the six *_ROWS wrappers, rebuilt and actually called.

    The Backlog originally wrote these off as untestable.  They are not: each
    closes only over _rows_regression, which itself closes over nothing, so
    both can be rebuilt against the module namespace and run for real.  This
    is the part that catches a wrapper wired to the wrong parameter or the
    wrong sign -- mistakes that still return a plausible number.
    """
    rows_regression = rebuild(p, "_rows_regression", defaults=(2,))
    r.check("rebuilt _rows_regression", rows_regression is not None, True)
    if rows_regression is None:
        return
    deps = {"_rows_regression": rows_regression}

    # One row, six levels: Y columns first, then X columns.
    cols = [[y] for y in LIN_Y] + [[x] for x in LIN_X]

    expected = [
        ("_slope_se_rows", "se_slope"),
        ("_slope_ci_low_rows", "slope_lo"),
        ("_slope_ci_high_rows", "slope_hi"),
        ("_intercept_se_rows", "se_intercept"),
        ("_intercept_ci_low_rows", "intercept_lo"),
        ("_intercept_ci_high_rows", "intercept_hi"),
    ]
    for fn_name, key in expected:
        fn = rebuild(p, fn_name, freevars=deps)
        r.check("rebuilt %s" % fn_name, fn is not None, True)
        if fn is None:
            continue
        got = fn(*cols)
        r.check("%s row count" % fn_name, len(got), 1)
        r.check("%s value" % fn_name, got[0], EXCEL[key], tol=TOL)

    # ★ Y/X halves must not be swapped.  Regressing x on y also returns a
    # number, so only asymmetric data catches a transposed wrapper.
    swapped = [[x] for x in LIN_X] + [[y] for y in LIN_Y]
    slope_hi = rebuild(p, "_slope_ci_high_rows", freevars=deps)
    got_swapped = slope_hi(*swapped)[0]
    r.check("Y/X halves are not interchangeable",
            abs(got_swapped - EXCEL["slope_hi"]) < 1.0, False)

    # A row with only two surviving levels yields "---" (min_pairs=3).
    two = [[LIN_Y[0]], [LIN_Y[1]], [None], [LIN_X[0]], [LIN_X[1]], [None]]
    r.check("two levels -> placeholder",
            slope_hi(*two), [p._PLACEHOLDER])


def test_s3_registration(p, r):
    """S3: all six registered, and all six named to reach the array path."""
    safe = _registry_keys(p, "_SAFE")
    array_fn_re = re.compile(
        r'(GROUP_\w+(?:list)?|\w+_ROWS|RESULT_STATUS|TIME_ELAPSED_HOURS'
        r'|COALESCE|SHIFT)\s*\(')
    for name in ("SLOPE_SE_ROWS", "SLOPE_CI_LOW_ROWS", "SLOPE_CI_HIGH_ROWS",
                 "INTERCEPT_SE_ROWS", "INTERCEPT_CI_LOW_ROWS",
                 "INTERCEPT_CI_HIGH_ROWS"):
        r.check("%s registered" % name, name in safe, True)
        r.check("%s takes the array path" % name,
                bool(array_fn_re.search(u"%s([a],[b])" % name)), True)


DYNAMIC = u'LOOKUP([imp_src_as],"imp_correction_factor","imp_name",[imp_name],1.0)'
LITERAL = (u'LOOKUP("imp_linearity_shared","imp_correction_factor",'
           u'"imp_name",[imp_name],1.0)')


def test_lookup_dynamic_source_detection(p, r):
    """S4: tell a run-time source apart from a literal one."""
    f = p._lookup_has_dynamic_source

    r.check("dynamic source detected", f(DYNAMIC), True)
    r.check("literal source not flagged", f(LITERAL), False)
    r.check("empty formula", f(u""), False)
    r.check("None formula", f(None), False)
    r.check("plain arithmetic", f(u"([a]+[b])/2"), False)

    # Spacing is analyst-typed, so the detector must not be fussy about it.
    r.check("spaced call", f(u"LOOKUP ( [kw], 'a', 'b', [c])"), True)
    r.check("single-quoted literal not flagged",
            f(u"LOOKUP('lit','a','b',[c])"), False)

    # A dynamic LOOKUP anywhere in a longer expression still counts.
    r.check("wrapped in BAND", f(u"BAND(%s, 0.8, 1.2, 1.0)" % DYNAMIC), True)


def test_literal_lookup_sources_unchanged(p, r):
    """S4: the branch must not disturb the parsing that already works.

    The literal path is what keeps every existing formula's propagation
    alive.  Breaking it while fixing the dynamic case would trade a known
    silent failure for a much bigger one.
    """
    f = p._extract_lookup_sources

    r.check("literal source still extracted",
            f(LITERAL), set([u"imp_linearity_shared"]))
    r.check("dynamic source yields nothing (unchanged)", f(DYNAMIC), set())
    r.check("two literals both found",
            f(u'LOOKUP("a","t","k",[x]) + LOOKUP("b","t","k",[x])'),
            set([u"a", u"b"]))
    r.check("empty formula", f(u""), set())


def test_dependent_lookup_branch_wired(p, r):
    """S4: the conservative branch is actually in the dependency scan.

    The scan is _TreeIndex (built once per settle; it replaced the per-step
    _dependent_sibling_analyses).  It needs live Analysis objects to do
    anything useful, so what is checked here is that it reads both
    predicates; the behavioural half is test_settle.py and, on a real
    Analysis Service, S6.
    """
    code = p._TreeIndex.__init__.__code__
    for name in ("_extract_lookup_sources", "_lookup_has_dynamic_source"):
        r.check("dependency scan calls %s" % name, name in code.co_names, True)

    # The dynamic branch must be gated on a cross-referenceable change of the
    # source; ungated, every unrelated edit would drag dynamic-source
    # siblings through a recalculation.
    readers = p._TreeIndex.readers.__code__
    r.check("dynamic branch is gated",
            "xref_changed" in readers.co_varnames
            and "_dynamic" in readers.co_names, True)


# Nine recovery values: mean 100.0, sample SD 1.3693064.
# Half-width = _T_95[8] * SD / sqrt(9) = 2.306004 * 1.3693064 / 3 = 1.0525.
NINE = [98.0, 99.0, 100.0, 101.0, 102.0, 98.5, 99.5, 100.5, 101.5]
NINE_MEAN = 100.0
NINE_LO = 98.9475
NINE_HI = 101.0525


def _rebuild_group_ci(p):
    """Rebuild the two ungrouped CI helpers, bottom-up through their cells."""
    agg_stdev = rebuild(p, "_agg_stdev")
    if agg_stdev is None:
        return None, None
    agg_ci = rebuild(p, "_agg_ci", freevars={"_agg_stdev": agg_stdev})
    if agg_ci is None:
        return None, None
    deps = {"_agg_ci": agg_ci, "_nums_only": rebuild(p, "_nums_only")}
    return (rebuild(p, "_group_ci_low", freevars=deps),
            rebuild(p, "_group_ci_high", freevars=deps))


def test_group_ci_whole_column(p, r):
    """S7: CI of the mean over the whole column, no grouping key."""
    lo_fn, hi_fn = _rebuild_group_ci(p)
    r.check("rebuilt GROUP_CI_LOW", lo_fn is not None, True)
    r.check("rebuilt GROUP_CI_HIGH", hi_fn is not None, True)
    if lo_fn is None or hi_fn is None:
        return

    lo, hi = lo_fn(NINE), hi_fn(NINE)
    r.check("GROUP_CI_LOW over nine values", lo, NINE_LO, tol=1e-6)
    r.check("GROUP_CI_HIGH over nine values", hi, NINE_HI, tol=1e-6)

    # ★ Recover t from the half-width.  A mean's interval uses df = n-1;
    # the regression parameter intervals (S3) use n-2.  Both read _T_95, so
    # asserting only the bound would not catch a slip between the two rows.
    import math
    sd = math.sqrt(sum((v - NINE_MEAN) ** 2 for v in NINE) / (len(NINE) - 1))
    t_used = (hi - NINE_MEAN) / (sd / math.sqrt(len(NINE)))
    r.check("df is n-1, so t = _T_95[8]", t_used, 2.306004, tol=1e-9)
    r.check("t is NOT _T_95[7] (the neighbouring row)",
            abs(t_used - p._T_95[7]) < 1e-6, False)

    # Grouping keys are accepted and ignored, like GROUP_AVG and friends.
    r.check("keys are ignored", lo_fn(NINE, ["a"] * 9, ["b"] * 9), lo,
            tol=1e-12)

    # Missing / non-numeric cells are skipped, not counted.
    r.check("skips non-numeric",
            lo_fn(NINE + [u"", None, u"---", u"abc"]), lo, tol=1e-12)

    # Fewer than two values leaves the interval undefined -> "---", not 0.
    r.check("n=1 is the placeholder", lo_fn([5.0]), p._PLACEHOLDER)
    r.check("n=0 is the placeholder", lo_fn([]), p._PLACEHOLDER)
    r.check("n=1 is not 0", lo_fn([5.0]) == 0, False)

    # Table edges: df 10 is the last row, df 11 is off the end.
    eleven = [float(i) for i in range(11)]      # n=11 -> df=10, in table
    twelve = [float(i) for i in range(12)]      # n=12 -> df=11, off the end
    r.check("n=11 (df=10) still computes",
            isinstance(lo_fn(eleven), float), True)
    r.check("n=12 (df=11) is the placeholder", lo_fn(twelve), p._PLACEHOLDER)


def test_s7_registration(p, r):
    """S7: registered in the array table only, and reachable by dispatch."""
    safe = _registry_keys(p, "_SAFE")
    scalar = _registry_keys(p, "safe_globals")
    array_fn_re = re.compile(
        r'(GROUP_\w+(?:list)?|\w+_ROWS|RESULT_STATUS|TIME_ELAPSED_HOURS'
        r'|COALESCE|SHIFT)\s*\(')
    for name in ("GROUP_CI_LOW", "GROUP_CI_HIGH"):
        r.check("%s in _SAFE" % name, name in safe, True)
        r.check("%s not in safe_globals" % name, name in scalar, False)
        r.check("%s takes the array path" % name,
                bool(array_fn_re.search(u"%s([a])" % name)), True)


# =============================================================================
# BASELINE_BYlist -- the stability "percent of time zero" column.
# Backlog: Docs/Cal增加/maitux.calcenhance-稳定性基线取值-Backlog.md (S1)
# =============================================================================
#
# The eleven rows below are the analysts' own S1919 record, both injections
# of one sample, transcribed unchanged from 需求与方案 §1.1.  Its last column
# was filled in by the instrument operator, by hand, before this function
# existed -- so the expected numbers are not a restatement of what the code
# does.  They are the thing the code has to reproduce.
#
# Peak 6 (RRT 1.38) is the whole point: it appears at 8h and has no row at
# T0.  The operator left its cell EMPTY.  A "first value in the group"
# implementation returns 100.0 there instead -- correct-looking, unflagged,
# wrong.

S1919_AREA = [
    # T0 -- 2026/5/13 20:47.  RRT 0.14 / 0.71 / 1.00 / 1.33 / 1.40
    1691.0, 6290.0, 13068724.0, 1616.0, 3265.0,
    # 8h -- 2026/5/14 04:51.  RRT 0.14 / 0.71 / 1.00 / 1.33 / 1.38 / 1.41
    1600.0, 6450.0, 13076197.0, 1954.0, 1402.0, 3369.0,
]
S1919_HOURS = [0.0] * 5 + [8.0] * 6
# Peak identity, the column `imp_pct_group` will hold.  Names cannot do this
# job: six of these eleven rows are all called 未知杂质.
S1919_PEAK = [u"1", u"2", u"3", u"4", u"5",
              u"1", u"2", u"3", u"4", u"6", u"5"]

# Written down before the first run (Backlog gate ①).
S1919_BASELINE = [
    1691.0, 6290.0, 13068724.0, 1616.0, 3265.0,
    1691.0, 6290.0, 13068724.0, 1616.0, u"---", 3265.0,
]
S1919_DEVIATION_8H = [94.6, 102.5, 100.1, 120.9, u"---", 103.2]


class _FakeOwner(object):
    """Only the `id` the duplicate warning quotes."""

    id = "S1919-R01-imp_stability_cold"


def _rebuild_baseline(p, owner):
    """Rebuild BASELINE_BYlist bottom-up through its two cells."""
    warn_fn = rebuild(p, "_baseline_duplicate_warn", freevars={"self": owner})
    if warn_fn is None:
        return None
    return rebuild(p, "_baseline_bylist", freevars={
        "_norm_key": rebuild(p, "_norm_key"),
        "_baseline_duplicate_warn": warn_fn,
    })


def _rebuild_round_even(p):
    """ROUND_EVEN, wherever it is defined today.

    It used to live inside the calculatedlist engine and had to be rebuilt
    out of the enclosing code object.  It has since been hoisted to module
    level (so the scalar engine can reference it too), where it is simply an
    attribute -- and `rebuild` then returns None, which this test read as
    "the function is gone".  Prefer the attribute, keep the rebuild as the
    fallback: either way what gets tested is the shipped function.
    """
    fn = getattr(p, "_round_half_even", None)
    if fn is not None:
        return fn
    # The pre-hoist path: it recurses, and Python 2 has no writable cell,
    # so the self-reference goes in as a trampoline pointed at the real
    # function once it exists.  Only the list branch follows it.
    box = {}
    fn = rebuild(p, "_round_half_even", defaults=(0,), freevars={
        "_round_half_even": lambda *a, **kw: box["fn"](*a, **kw),
        "_dec_quantize": rebuild(p, "_dec_quantize")})
    box["fn"] = fn
    return fn


def _rebuild_round_up(p):
    """ROUND_UP, wherever it is defined today.

    It used to live inside the calculatedlist engine and had to be rebuilt
    out of the enclosing code object.  It has since been hoisted to module
    level (so the scalar engine can reference it too), where it is simply an
    attribute -- and `rebuild` then returns None, which this test read as
    "the function is gone".  Prefer the attribute, keep the rebuild as the
    fallback: either way what gets tested is the shipped function.
    """
    fn = getattr(p, "_round_up", None)
    if fn is not None:
        return fn
    # Pre-hoist path -- same trampoline as _rebuild_round_even.
    box = {}
    fn = rebuild(p, "_round_up", defaults=(0,), freevars={
        "_round_up": lambda *a, **kw: box["fn"](*a, **kw),
        "_dec_quantize": rebuild(p, "_dec_quantize")})
    box["fn"] = fn
    return fn


def test_round_up(p, r):
    """ROUND_UP: 只进不舍, and -- the point of it -- it maps over a list.

    The function exists because `ceil(RSD_ROWS(...)*10)/10` in a formula
    crashes: the array function returns a list, `list * 10` is Python list
    repetition, and math.ceil then throws "a float is required", which the
    engine surfaces as "---" for the whole column.  So the list branch is
    the case under test, not a nicety.
    """
    safe = _registry_keys(p, "_SAFE")
    r.check("ROUND_UP registered in _SAFE", "ROUND_UP" in safe, True)

    f = _rebuild_round_up(p)
    r.check("rebuilt ROUND_UP", f is not None, True)
    if f is None:
        return

    # -- scalars -------------------------------------------------------
    # 1.606 is the RSD the 2026-09-11 simulated run actually produced from
    # areas 100/102/101/103/104/100; loq_rsd should report 1.7.
    r.check("1.606 -> 1.7", f(1.606, 1), 1.7)
    r.check("1.601 -> 1.7", f(1.601, 1), 1.7)
    # No remainder means no carry -- 只进不舍 is not "always add one".
    r.check("1.6 stays 1.6", f(1.6, 1), 1.6)
    r.check("2.0 stays 2.0", f(2.0, 1), 2.0)
    r.check("0.01 -> 0.1", f(0.01, 1), 0.1)
    r.check("digits=0", f(1.0001, 0), 2.0)

    # -- the list branch, i.e. what GROUP_RSDlist / RSD_ROWS hand it ----
    r.check("maps over a list",
            f([1.606, 2.301, 0.05], 1), [1.7, 2.4, 0.1])

    # -- non-numeric members degrade per element, not per column -------
    r.check("placeholder per element",
            f([1.606, None, u"", u"N.D."], 1),
            [1.7, p._PLACEHOLDER, p._PLACEHOLDER, p._PLACEHOLDER])
    r.check("scalar non-numeric", f(u"N.D.", 1), p._PLACEHOLDER)

    # -- away from zero, NOT toward +inf -------------------------------
    # Pins the documented decision: ceil(-1.51) would give -1.5.  Every
    # caller today is a percentage or an RSD and never negative, so this
    # only bites a future one -- which is exactly why it is nailed down.
    r.check("negative rounds away from zero", f(-1.51, 1), -1.6)


def _rebuild_round_down(p):
    """ROUND_DOWN, wherever it is defined today.

    It used to live inside the calculatedlist engine and had to be rebuilt
    out of the enclosing code object.  It has since been hoisted to module
    level (so the scalar engine can reference it too), where it is simply an
    attribute -- and `rebuild` then returns None, which this test read as
    "the function is gone".  Prefer the attribute, keep the rebuild as the
    fallback: either way what gets tested is the shipped function.
    """
    fn = getattr(p, "_round_down", None)
    if fn is not None:
        return fn
    # Pre-hoist path -- same trampoline as _rebuild_round_even.
    box = {}
    fn = rebuild(p, "_round_down", defaults=(0,), freevars={
        "_round_down": lambda *a, **kw: box["fn"](*a, **kw),
        "_dec_quantize": rebuild(p, "_dec_quantize")})
    box["fn"] = fn
    return fn


def test_round_down(p, r):
    """ROUND_DOWN: 只舍不进, truncate toward zero -- rs_stab_pct1's actual
    ask (保留一位小数、后面位数舍弃不进位), which none of ROUND / ROUND_EVEN /
    ROUND_UP express.  Mirrors test_round_up: the list branch is the case
    that matters, because RSD_ROWS / GROUP_RSDlist hand this a list, and
    bare floor() crashes on it the same way bare ceil() crashed ROUND_UP's
    caller before this function existed.
    """
    safe = _registry_keys(p, "_SAFE")
    r.check("ROUND_DOWN registered in _SAFE", "ROUND_DOWN" in safe, True)

    f = _rebuild_round_down(p)
    r.check("rebuilt ROUND_DOWN", f is not None, True)
    if f is None:
        return

    # -- scalars -------------------------------------------------------
    r.check("1.606 -> 1.6", f(1.606, 1), 1.6)
    r.check("1.699 -> 1.6", f(1.699, 1), 1.6)
    # Already at the target precision -- truncating nothing is not carrying.
    r.check("1.6 stays 1.6", f(1.6, 1), 1.6)
    r.check("2.0 stays 2.0", f(2.0, 1), 2.0)
    r.check("0.09 -> 0.0", f(0.09, 1), 0.0)
    r.check("digits=0", f(1.9999, 0), 1.0)

    # -- the list branch, i.e. what GROUP_RSDlist / RSD_ROWS hand it ----
    r.check("maps over a list",
            f([1.606, 2.699, 0.09], 1), [1.6, 2.6, 0.0])

    # -- non-numeric members degrade per element, not per column -------
    r.check("placeholder per element",
            f([1.606, None, u"", u"N.D."], 1),
            [1.6, p._PLACEHOLDER, p._PLACEHOLDER, p._PLACEHOLDER])
    r.check("scalar non-numeric", f(u"N.D.", 1), p._PLACEHOLDER)

    # -- toward zero, NOT toward -inf ----------------------------------
    # Pins the documented decision: floor(-1.69) would give -1.7 (ROUND_FLOOR
    # semantics). ROUND_DOWN truncates symmetrically around zero, so -1.69
    # gives -1.6, matching the away-from-zero pairing ROUND_UP already has.
    r.check("negative truncates toward zero", f(-1.69, 1), -1.6)


def test_baseline_bylist(p, r):
    """S1: the baseline is the earliest RUN, not each group's first row."""
    logger = install_engine_stubs()
    owner = _FakeOwner()
    f = _rebuild_baseline(p, owner)
    r.check("rebuilt BASELINE_BYlist", f is not None, True)
    if f is None:
        return

    # -- ① the analysts' record, end to end ----------------------------
    got = f(S1919_AREA, S1919_HOURS, S1919_PEAK)
    r.check("S1919 baseline column", got, S1919_BASELINE)

    round_even = _rebuild_round_even(p)
    r.check("rebuilt ROUND_EVEN", round_even is not None, True)
    if round_even is not None:
        deviation = []
        for index in range(5, 11):
            base = got[index]
            if base == p._PLACEHOLDER:
                deviation.append(p._PLACEHOLDER)
            else:
                deviation.append(
                    round_even(S1919_AREA[index] / base * 100, 1))
        r.check("S1919 8h deviation column", deviation, S1919_DEVIATION_8H)

    # -- ② the ordinary case: broadcast the baseline to every row ------
    #    Three runs of one peak -- every row reads the same baseline.
    r.check("broadcast to the whole group",
            f([10.0, 12.0, 14.0], [0.0, 4.0, 8.0], [u"p", u"p", u"p"]),
            [10.0, 10.0, 10.0])

    # -- ③ a peak that is absent from the baseline run -----------------
    #    Kept apart from ② on purpose: this is the failure the function
    #    exists to prevent, and merging it into a happy-path case is how
    #    it would go unnoticed.
    late = f([10.0, 12.0, 7.0], [0.0, 8.0, 8.0], [u"p", u"p", u"new"])
    r.check("new peak has no baseline", late[2], p._PLACEHOLDER)
    r.check("new peak is NOT its own value", late[2] == 7.0, False)
    r.check("new peak is NOT zero", late[2] == 0, False)
    r.check("new peak is NOT the main peak's baseline", late[2] == 10.0, False)
    r.check("the established peak is unaffected", late[:2], [10.0, 10.0])

    # -- ④ global minimum, not the group's own minimum -----------------
    #    Same trap as ③ approached from the other side: here the late
    #    group has TWO runs of its own, so "the group's earliest row"
    #    is a perfectly available answer -- and the wrong one.
    spread = f([10.0, 5.0, 12.0, 6.0],
               [0.0, 8.0, 16.0, 16.0],
               [u"p", u"late", u"p", u"late"])
    r.check("group minimum is not the baseline", spread[1], p._PLACEHOLDER)
    r.check("late group stays blank on its later run",
            spread[3], p._PLACEHOLDER)
    r.check("late group did not fall back to 5.0", spread[1] == 5.0, False)

    #    And the sequence column does not have to start at 0: injection
    #    numbers count from 1.  A `== 0` baseline test would blank
    #    everything here.
    ones = f([10.0, 11.0], [1.0, 2.0], [u"p", u"p"])
    r.check("sequence starting at 1 still finds a baseline", ones,
            [10.0, 10.0])

    # -- ⑤ composite keys ----------------------------------------------
    #    Two key columns combine into one key, exactly as GROUP_*list.
    composite = f([10.0, 100.0, 12.0, 130.0],
                  [0.0, 0.0, 8.0, 8.0],
                  [u"未知杂质", u"未知杂质"] * 2,
                  [u"low", u"high", u"low", u"high"])
    r.check("composite key keeps the levels apart",
            composite, [10.0, 100.0, 10.0, 100.0])
    #    Collapse it to the name alone and the two levels merge -- which
    #    is what makes the second key column load-bearing, not decoration.
    collapsed = f([10.0, 100.0, 12.0, 130.0],
                  [0.0, 0.0, 8.0, 8.0],
                  [u"未知杂质"] * 4)
    r.check("one key column merges them", collapsed,
            [10.0, 10.0, 10.0, 10.0])

    # -- ⑥ edges --------------------------------------------------------
    blank_seq = f([10.0, 12.0], [u"", u""], [u"p", u"p"])
    r.check("empty sequence column blanks the output", blank_seq,
            [p._PLACEHOLDER] * 2)
    r.check("empty sequence does NOT promote row 0",
            blank_seq[0] == 10.0, False)
    r.check("non-numeric sequence column blanks the output",
            f([10.0, 12.0], [u"abc", p._PLACEHOLDER], [u"p", u"p"]),
            [p._PLACEHOLDER] * 2)
    #    A missing value ON the baseline run is skipped the way the
    #    GROUP_* family skips it -- the group simply has no baseline.
    r.check("missing baseline value is skipped",
            f([u"", 12.0], [0.0, 8.0], [u"p", u"p"]),
            [p._PLACEHOLDER, p._PLACEHOLDER])
    #    ...but a later missing value costs the group nothing.
    r.check("missing later value keeps the baseline",
            f([10.0, u"", 12.0], [0.0, 8.0, 8.0], [u"p", u"p", u"p"]),
            [10.0, 10.0, 10.0])
    r.check("empty input", f([], [], []), [])
    #    A scalar sequence means one single run: every row is baseline.
    r.check("scalar sequence broadcasts",
            f([10.0, 20.0], 0.0, [u"a", u"b"]), [10.0, 20.0])

    # -- ⑦ two rows of one group inside the baseline run ---------------
    before = len(logger.lines)
    dup = f([10.0, 40.0, 12.0], [0.0, 0.0, 8.0], [u"p", u"p", u"p"])
    r.check("earliest row wins", dup, [10.0, 10.0, 10.0])
    r.check("the later duplicate is not used", dup[0] == 40.0, False)
    new_lines = logger.lines[before:]
    r.check("one warn line", len(new_lines), 1)
    r.check("the warn names the function",
            bool(new_lines) and "BASELINE_BYlist" in new_lines[0], True)
    r.check("the warn names the analysis",
            bool(new_lines) and owner.id in new_lines[0], True)

    #    One line per GROUP, not per row.  A key column filled with one
    #    value on every row is an easy mistake to make, and a per-row
    #    line would put one entry per table row into the log on every
    #    evaluation -- enough noise to bury the finding itself.
    before = len(logger.lines)
    flat = f([10.0, 20.0, 30.0, 40.0], [0.0] * 4, [u"same"] * 4)
    r.check("all four read the first row", flat, [10.0] * 4)
    r.check("four duplicate rows still log one line",
            len(logger.lines) - before, 1)
    r.check("the line names every ignored row",
            "2, 3, 4" in logger.lines[-1], True)

    #    The key is analyst text and is routinely CJK.  Py2 turns a
    #    careless %-format here into UnicodeDecodeError, which would
    #    replace the warning with a traceback -- R13.
    before = len(logger.lines)
    cjk = f([10.0, 40.0, 12.0], [0.0, 0.0, 8.0], [u"未知杂质"] * 3)
    r.check("CJK duplicate still resolves", cjk, [10.0, 10.0, 10.0])
    r.check("CJK duplicate logged once", len(logger.lines) - before, 1)
    r.check("CJK key survives into the warn",
            u"未知杂质".encode("utf-8") in logger.lines[-1], True)


def test_baseline_registration(p, r):
    """S1: array table only, and named in the dispatch regex by hand."""
    safe = _registry_keys(p, "_SAFE")
    scalar = _registry_keys(p, "safe_globals")
    r.check("BASELINE_BYlist in _SAFE", "BASELINE_BYlist" in safe, True)
    r.check("BASELINE_BYlist not in safe_globals",
            "BASELINE_BYlist" in scalar, False)

    # ★ The name does not begin with GROUP_ and does not end in _ROWS, so
    # the family patterns do NOT catch it.  Assert that directly: this is
    # the one-line omission that would send it down the per-element path,
    # where it sees a single scalar and can never find the baseline row.
    family_only = re.compile(r'(GROUP_\w+(?:list)?|\w+_ROWS)\s*\(')
    r.check("the family patterns do not cover it",
            bool(family_only.search(u"BASELINE_BYlist([a],[b],[c])")), False)

    src = open(p.__source_path__, "rb").read().decode("utf-8")
    r.check("named in the dispatch regex in source",
            u"|BASELINE_BYlist" in src, True)
    array_fn_re = re.compile(
        r'(GROUP_\w+(?:list)?|\w+_ROWS|RESULT_STATUS|TIME_ELAPSED_HOURS'
        r'|COALESCE|SHIFT|BASELINE_BYlist)\s*\(')
    r.check("BASELINE_BYlist takes the array path",
            bool(array_fn_re.search(u"BASELINE_BYlist([a],[b],[c])")), True)

    # It must not be wired through _group_apply: that helper has no
    # sequence dimension, so a group absent from the baseline run would
    # aggregate its OWN rows and come back as a ratio of 100.0.
    code = _find_code(p, "_baseline_bylist")
    r.check("found the code object", code is not None, True)
    if code is not None:
        r.check("does not call _group_apply",
                "_group_apply" in (code.co_names + code.co_freevars), False)


def test_baseline_through_the_engine(p, r):
    """S1: drive the REAL engine, not a rebuilt closure.

    Everything above calls the function directly, which cannot see the one
    mistake that would hurt most: _ARRAY_FN_RE decides array path vs
    per-element path by NAME, and BASELINE_BYlist matches none of the
    family patterns.  Left out of that regex it would be handed one scalar
    at a time and could never find the baseline row.  Only the engine
    proves the wiring.

    It also pins the spelling.  The array path substitutes whole columns
    and evaluates ONCE, so `[g_area] / BASELINE_BYlist(...)` is a list
    divided by a list -- a TypeError that blanks the column.  The baseline
    has to land in its own interim field first.  That is not a quirk of
    this function; it is how every array-path function composes.
    """
    import json

    install_engine_stubs()
    base_call = (u"BASELINE_BYlist([g_area],[imp_stab_time],"
                 u"[imp_pct_group])")

    def columns():
        return [
            {"keyword": "g_area", "title": u"峰面积", "result_type": "list",
             "value": json.dumps(S1919_AREA)},
            {"keyword": "imp_stab_time", "title": u"时间",
             "result_type": "list", "value": json.dumps(S1919_HOURS)},
            {"keyword": "imp_pct_group", "title": u"峰组",
             "result_type": "list", "value": json.dumps(S1919_PEAK)},
        ]

    def run(extra):
        _, analyses = build_sample([{
            "as_id": "AS1", "service_kw": "stab",
            "fields": columns() + extra}])
        out = evaluate(p, analyses, ("AS1",))
        return dict((k.split(".", 1)[1], json.loads(v))
                    for k, v in out.items() if v)

    # -- the spelling that works -------------------------------------
    two_column = run([
        {"keyword": "imp_base", "title": u"0点峰面积",
         "result_type": "calculatedlist", "formula": base_call},
        {"keyword": "imp_deviation", "title": u"与0点的比值",
         "result_type": "calculatedlist",
         "formula": u"ROUND_EVEN([g_area]/[imp_base]*100, 1)"},
    ])
    r.check("engine: baseline column", two_column.get("imp_base"),
            S1919_BASELINE)
    # 修约位数随值传递 S2: a ROUND_EVEN(...,1) column is stored as its
    # fixed-point text (storage form A'); the numbers are the same.
    r.check("engine: deviation column", two_column.get("imp_deviation"),
            [u"100.0"] * 5 + [v if v == u"---" else u"%.1f" % v
                              for v in S1919_DEVIATION_8H])
    # ★ The new peak has to reach the RESULT as a blank.  The per-element
    # path propagates the placeholder for free -- but only because the
    # baseline really is "---" there, which is the whole point.
    r.check("engine: the 8h-only peak stays blank",
            two_column.get("imp_deviation")[9], u"---")

    # -- the spelling that does NOT work, pinned on purpose -----------
    one_liner = run([
        {"keyword": "imp_deviation", "title": u"与0点的比值",
         "result_type": "calculatedlist",
         "formula": u"ROUND_EVEN([g_area]/%s*100, 1)" % base_call},
    ])
    r.check("engine: inlining the call blanks the whole column",
            one_liner.get("imp_deviation"), [u"---"] * 11)

    # The README may SHOW the broken spelling -- it is worth showing --
    # but only next to the warning.  What it must never do is present it
    # as the recipe, which is how it was written before this ran.
    readme = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(p.__source_path__))),
        "..", "..", "README.md")
    readme = os.path.normpath(readme)
    r.check("README found at %s" % readme, os.path.exists(readme), True)
    if os.path.exists(readme):
        text = open(readme, "rb").read().decode("utf-8")
        r.check("README gives the two-field recipe",
                u"ROUND_EVEN([g_area]/[imp_base]*100, 1)" in text, True)
        r.check("README warns against the one-liner",
                u"不能写成一行" in text, True)


def _xagg_fixture():
    """Sibling data for the XAGG_KEYS / APPEND unit tests, built by hand
    rather than through build_sample() -- these are direct-call tests of
    the closures, not of the engine, so the fixture only needs to look
    like what _collect_cross_referenceable_data() would have returned.

        std   -- has imp_name flagged, 6 raw values with one repeat
                 (Z7 twice) to exercise dedup + first-seen order together
        std2  -- has imp_name flagged, overlaps std on "Z14"
        std3  -- EXISTS in the sample (existing_services) but imp_name is
                 NOT in its sibling_data entry -- the "field exists on
                 the AS but nobody ticked cross_referenceable" case
        ghost_as -- requested by name in some tests but never a sibling
                 at all -- the "source AS was never run" case
    """
    sibling_data = {
        u"std": {u"imp_name": [u"Z7", u"Z10", u"Z7", u"Z13", u"B", u"Z14"]},
        u"std2": {u"imp_name": [u"Z14", u"NEW1"]},
    }
    existing_services = set([u"std", u"std2", u"std3"])
    return sibling_data, existing_services


def _rebuild_xagg(p, owner, sibling_data, existing_services):
    """Rebuild XAGG_KEYS / APPEND bottom-up through their shared cells."""
    norm_key = rebuild(p, "_norm_key")
    xagg_warn = rebuild(p, "_xagg_warn")
    resolve_sources = rebuild(p, "_xagg_resolve_sources", freevars={
        "self": owner, "_xagg_warn": xagg_warn})
    collect = rebuild(p, "_xagg_collect", freevars={
        "self": owner,
        "_xagg_existing_services": existing_services,
        "sibling_data": sibling_data,
        "_xagg_resolve_sources": resolve_sources,
        "_xagg_warn": xagg_warn,
    })
    xagg_keys = rebuild(p, "_xagg_keys", freevars={
        "_xagg_collect": collect, "_norm_key": norm_key})
    append_fn = rebuild(p, "_append", freevars={"_norm_key": norm_key})
    return xagg_keys, append_fn


def test_xagg_keys_and_append(p, r):
    """S1 (跨AS聚合): XAGG_KEYS defines the row space, APPEND adds the
    literal total row -- see needs doc §3.1/§3.2 and Backlog S1."""
    logger = install_engine_stubs()
    owner = _FakeOwner()
    sibling_data, existing_services = _xagg_fixture()
    xagg_keys, append_fn = _rebuild_xagg(p, owner, sibling_data, existing_services)
    r.check("rebuilt XAGG_KEYS", xagg_keys is not None, True)
    r.check("rebuilt APPEND", append_fn is not None, True)
    if xagg_keys is None or append_fn is None:
        return

    # -- ①（先写死预期）+ ② dedup and first-seen order ------------------
    #    std's raw column has Z7 twice; the result must still be 5, in the
    #    order the names first appeared, and must not contain S1919 (this
    #    fixture never mentions it -- the point is that XAGG_KEYS only
    #    ever echoes what it was given, it does not know about "the main
    #    component" as a special case).
    base = xagg_keys(u"imp_name", u"std")
    r.check("single source: five distinct rows",
            base, [u"Z7", u"Z10", u"Z13", u"B", u"Z14"])
    r.check("does not contain the main component",
            u"S1919" in base, False)

    # -- ③ multi-source merge: overlap collapses, new rows append --------
    merged = xagg_keys(u"imp_name", u"std", u"std2")
    r.check("two sources merge, overlap not duplicated", merged,
            [u"Z7", u"Z10", u"Z13", u"B", u"Z14", u"NEW1"])

    # -- ④ APPEND: one literal row, new list, original untouched ---------
    before_base = list(base)
    appended = append_fn(base, u"总杂（指定杂质合计）")
    r.check("APPEND: six rows, total row last",
            appended, before_base + [u"总杂（指定杂质合计）"])
    r.check("APPEND does not mutate its input list", base, before_base)

    # -- ⑤ ★ field exists on the AS but is not cross_referenceable -------
    #    Kept apart from ⑥ on purpose (Backlog S1 risk): this must warn,
    #    ⑥ must not.
    before = len(logger.lines)
    unflagged = xagg_keys(u"imp_name", u"std3")
    r.check("unflagged field -> placeholder, not empty/zero",
            unflagged, [p._PLACEHOLDER])
    new_lines = logger.lines[before:]
    r.check("unflagged field warns exactly once", len(new_lines), 1)
    r.check("warn names the function",
            bool(new_lines) and "XAGG_KEYS" in new_lines[0], True)
    r.check("warn names the field",
            bool(new_lines) and "imp_name" in new_lines[0], True)
    r.check("warn names the offending source",
            bool(new_lines) and "std3" in new_lines[0], True)

    #    One good source plus one unflagged source still fails the WHOLE
    #    result -- a config mistake is not something to paper over by
    #    quietly reporting on fewer sources than the formula asked for.
    before = len(logger.lines)
    mixed = xagg_keys(u"imp_name", u"std", u"std3")
    r.check("one unflagged source fails the combined result too",
            mixed, [p._PLACEHOLDER])
    r.check("mixed case still warns exactly once",
            len(logger.lines) - before, 1)

    # -- ⑥ source AS absent from the sample entirely: silent -------------
    before = len(logger.lines)
    absent = xagg_keys(u"imp_name", u"ghost_as")
    r.check("absent source AS -> placeholder", absent, [p._PLACEHOLDER])
    r.check("absent source AS does NOT warn",
            len(logger.lines), before)

    #    Partial existence is tolerated: an absent source is a normal
    #    "not run yet", so it is skipped rather than failing the sources
    #    that DO exist (design decision recorded in _xagg_collect's
    #    docstring; not literally spelled out in the needs doc, which
    #    only tests the single-source case for ⑥).
    before = len(logger.lines)
    partial = xagg_keys(u"imp_name", u"std", u"ghost_as")
    r.check("one absent source among several does not fail the rest",
            partial, [u"Z7", u"Z10", u"Z13", u"B", u"Z14"])
    r.check("partial existence does not warn", len(logger.lines), before)

    # -- ⑦ same source AS given twice: dedup + exactly one warn ----------
    before = len(logger.lines)
    dup = xagg_keys(u"imp_name", u"std", u"std")
    r.check("duplicate source: result unaffected",
            dup, [u"Z7", u"Z10", u"Z13", u"B", u"Z14"])
    new_lines = logger.lines[before:]
    r.check("duplicate source warns exactly once", len(new_lines), 1)
    r.check("dup warn names the function",
            bool(new_lines) and "XAGG_KEYS" in new_lines[0], True)
    r.check("dup warn names the repeated source",
            bool(new_lines) and "std" in new_lines[0], True)


def test_xagg_row_space_registration(p, r):
    """S1: XAGG_KEYS / APPEND take the array path despite having NO
    [bracket] refs of their own -- see the "no array deps" branch fix in
    patches.py (list results used to be squeezed into a one-element
    list) and the _ARRAY_FN_RE addition (for the OTHER call shape, an
    existing list field appended to directly: APPEND([field], "x"))."""
    safe = _registry_keys(p, "_SAFE")
    for name in ("XAGG_KEYS", "APPEND"):
        r.check("%s registered in _SAFE" % name, name in safe, True)

    # The pre-existing family patterns (as of BASELINE_BYlist) must NOT
    # cover either name -- if they already did, the two dedicated fixes
    # in this slice would not be provably necessary.
    family_only = re.compile(
        r'(GROUP_\w+(?:list)?|\w+_ROWS|RESULT_STATUS|TIME_ELAPSED_HOURS'
        r'|COALESCE|SHIFT|BASELINE_BYlist)\s*\(')
    for name in ("XAGG_KEYS", "APPEND"):
        r.check("pre-existing family patterns do not cover %s" % name,
                bool(family_only.search(u"%s(a,b)" % name)), False)

    src = open(p.__source_path__, "rb").read().decode("utf-8")
    r.check("XAGG_\\w+ named in the dispatch regex in source",
            u"|XAGG_\\w+" in src, True)
    # Named in the alternation -- NOT necessarily last in it.  Asserting
    # "|APPEND)" made this test fail the day another name was appended
    # after it (INDEX_BY_GROUP, V16), which says nothing about APPEND.
    r.check("APPEND named in the dispatch regex in source",
            u"|APPEND" in src, True)

    array_fn_re = re.compile(
        r'(GROUP_\w+(?:list)?|\w+_ROWS|RESULT_STATUS|TIME_ELAPSED_HOURS'
        r'|COALESCE|SHIFT|BASELINE_BYlist|XAGG_\w+|APPEND)\s*\(')
    for formula in (u'XAGG_KEYS("imp_name","std")',
                    u'APPEND(XAGG_KEYS("imp_name","std"), "x")',
                    u'APPEND([imp_x], 99)'):
        r.check("takes the array path: %s" % formula,
                bool(array_fn_re.search(formula)), True)


def test_xagg_through_the_engine(p, r):
    """S1: drive the REAL engine on both call shapes that matter.

    1. The needs-doc shape -- APPEND(XAGG_KEYS(...), "literal") -- has NO
       [bracket] refs at all, so it never reaches _ARRAY_FN_RE; it is the
       "no array deps" branch's list-vs-scalar fix that this proves,
       end to end, including the literal CJK total-row name written
       straight into the formula text (the R13 risk _append's docstring
       records: eval() on the unicode formula hands that literal back as
       raw UTF-8 bytes, not unicode, confirmed empirically in this
       container -- if _norm_key were dropped from _append, this
       assertion would still show the right CHARACTERS today and then
       fail every later comparison against a proper unicode row name
       without any error anywhere).
    2. APPEND([existing_list_field], literal) -- HAS a [bracket] ref, so
       it depends on APPEND being in _ARRAY_FN_RE.  Left out, this would
       take the per-element path and call APPEND once per existing row
       with a bare scalar, producing a list of 3 two-element lists
       instead of one 4-element column.
    """
    import json

    install_engine_stubs()

    def run(std_name_value, stat_fields):
        _, analyses = build_sample([
            {"as_id": "STD", "service_kw": "std", "fields": [
                {"keyword": "imp_name", "title": u"物质名称",
                 "result_type": "list", "value": json.dumps(std_name_value),
                 "cross_referenceable": True},
            ]},
            {"as_id": "STAT", "service_kw": "stat", "fields": stat_fields},
        ])
        out = evaluate(p, analyses, ("STD", "STAT"))
        return dict((k.split(".", 1)[1], json.loads(v))
                    for k, v in out.items() if v)

    # -- shape 1: the needs-doc row-space recipe --------------------------
    row_space_formula = (
        u'APPEND(XAGG_KEYS("imp_name","std"), "总杂（指'
        u'定杂质合计）")')
    out1 = run([u"Z7", u"Z10", u"Z13", u"B", u"Z14"], [
        {"keyword": "imp_ip_name", "title": u"统计项",
         "result_type": "calculatedlist", "formula": row_space_formula},
    ])
    r.check("engine: row space is six rows, not squeezed to one",
            len(out1.get("imp_ip_name") or []), 6)
    r.check("engine: row space content, CJK total row intact",
            out1.get("imp_ip_name"),
            [u"Z7", u"Z10", u"Z13", u"B", u"Z14", u"总杂（指定杂质合计）"])

    # -- shape 2: APPEND against an existing bracket-referenced column ---
    out2 = run([u"Z7"], [
        {"keyword": "imp_x", "title": u"x", "result_type": "list",
         "value": json.dumps([1.0, 2.0, 3.0])},
        {"keyword": "imp_y", "title": u"y",
         "result_type": "calculatedlist",
         "formula": u"APPEND([imp_x], 99)"},
    ])
    r.check("engine: APPEND on a bracket ref is ONE call for the column",
            out2.get("imp_y"), [1.0, 2.0, 3.0, 99.0])


# ---- S2: XAGG_<OP> -- per-key aggregate across sibling AS -----------------
#
# Two technicians' Z7 injections (needs doc §1.1's shape, not its literal
# numbers -- round figures chosen so the expected mean/RSD are computed
# independently below, in plain Python, rather than transcribed by hand).
Z7_CHROM = [10.0, 12.0, 11.0, 13.0, 9.0, 11.0]
Z7_SPIKED = [12.0, 12.5, 11.5, 12.0, 12.5, 11.5]


def _mean(ns):
    return sum(ns) / len(ns)


def _sample_stdev(ns):
    m = _mean(ns)
    return (sum((v - m) ** 2 for v in ns) / (len(ns) - 1)) ** 0.5


def _rsd_pct(ns):
    return _sample_stdev(ns) / _mean(ns) * 100.0


def _xagg_op_fixture():
    """chrom + spiked mimic the needs doc's two technicians on Z7 --
    single source gives n=6, both together give n=12 (Backlog S2
    judgement 2).  MISS / ALLMISS / ZEROMEAN (chrom only) exercise the
    four missing-value states (judgement 6).  GHOST never appears in
    either source at all (judgement 4)."""
    sibling_data = {
        u"chrom": {
            u"imp_name": (
                [u"Z7"] * 6 + [u"MISS"] * 3 + [u"ALLMISS"] * 2 +
                [u"ZEROMEAN"] * 2),
            u"imp_pct_c": (
                Z7_CHROM + [5.0, u"", None] + [u"", None] + [0.0, 0.0]),
        },
        u"spiked": {
            u"imp_name": [u"Z7"] * 6,
            u"imp_pct_c": Z7_SPIKED,
        },
    }
    existing_services = set([u"chrom", u"spiked"])
    return sibling_data, existing_services


def _rebuild_xagg_ops(p, owner, sibling_data, existing_services):
    """Rebuild XAGG_AVG/_RSD/_MAX/_MIN/_COUNT bottom-up through their
    shared cells.  Returns (ops_by_name, group_apply) -- the latter so
    callers can also rebuild GROUP_*list for the equivalence test."""
    norm_key = rebuild(p, "_norm_key")
    # _group_apply's 4th positional arg (`empty`) has a default in the
    # source (empty=_PLACEHOLDER) -- rebuild() does not carry defaults
    # across unless told to, so GROUP_AVGlist's 3-arg call would
    # otherwise blow up with "takes exactly 4 arguments (3 given)".
    group_apply = rebuild(p, "_group_apply", freevars={"_norm_key": norm_key},
                          defaults=(p._PLACEHOLDER,))
    agg_stdev = rebuild(p, "_agg_stdev")
    agg_rsd = rebuild(p, "_agg_rsd", freevars={"_agg_stdev": agg_stdev})
    xagg_warn = rebuild(p, "_xagg_warn")
    resolve_sources = rebuild(p, "_xagg_resolve_sources", freevars={
        "self": owner, "_xagg_warn": xagg_warn})
    collect = rebuild(p, "_xagg_collect", freevars={
        "self": owner,
        "_xagg_existing_services": existing_services,
        "sibling_data": sibling_data,
        "_xagg_resolve_sources": resolve_sources,
        "_xagg_warn": xagg_warn,
    })
    xagg_op = rebuild(p, "_xagg_op", freevars={
        "_group_apply": group_apply,
        "_norm_key": norm_key,
        "_xagg_collect": collect,
        "_xagg_warn": xagg_warn,
        "self": owner,
    })
    ops = {
        "avg": rebuild(p, "_xagg_avg", freevars={"_xagg_op": xagg_op}),
        "rsd": rebuild(p, "_xagg_rsd", freevars={
            "_xagg_op": xagg_op, "_agg_rsd": agg_rsd}),
        "max": rebuild(p, "_xagg_max", freevars={"_xagg_op": xagg_op}),
        "min": rebuild(p, "_xagg_min", freevars={"_xagg_op": xagg_op}),
        "count": rebuild(p, "_xagg_count", freevars={"_xagg_op": xagg_op}),
    }
    return ops, group_apply


def test_xagg_op_direct(p, r):
    """S2 (跨AS聚合): XAGG_AVG/_RSD/_MAX/_MIN/_COUNT, direct calls."""
    install_engine_stubs()
    owner = _FakeOwner()
    sibling_data, existing_services = _xagg_op_fixture()
    ops, _ = _rebuild_xagg_ops(p, owner, sibling_data, existing_services)
    for name in ("avg", "rsd", "max", "min", "count"):
        r.check("rebuilt XAGG_%s" % name.upper(), ops[name] is not None, True)

    row_keys = [u"Z7", u"GHOST", u"MISS", u"ALLMISS", u"ZEROMEAN"]
    combined = Z7_CHROM + Z7_SPIKED

    # -- ①（先写死预期）+ ② source count decides n, not a data column -----
    avg_single = ops["avg"](u"imp_pct_c", u"imp_name", row_keys, u"chrom")
    avg_combined = ops["avg"](
        u"imp_pct_c", u"imp_name", row_keys, u"chrom", u"spiked")
    r.check("n=6 (chrom only): Z7 mean",
            avg_single[0], _mean(Z7_CHROM), tol=1e-9)
    r.check("n=12 (chrom+spiked): Z7 mean",
            avg_combined[0], _mean(combined), tol=1e-9)
    r.check("adding a source actually changes the aggregate",
            avg_single[0] == avg_combined[0], False)

    count_single = ops["count"](u"imp_pct_c", u"imp_name", row_keys, u"chrom")
    count_combined = ops["count"](
        u"imp_pct_c", u"imp_name", row_keys, u"chrom", u"spiked")
    r.check("COUNT n=6 with one source", count_single[0], 6)
    r.check("COUNT n=12 with two sources", count_combined[0], 12)

    # -- ③ mean / RSD / max / min, independently computed ----------------
    rsd_combined = ops["rsd"](
        u"imp_pct_c", u"imp_name", row_keys, u"chrom", u"spiked")
    max_combined = ops["max"](
        u"imp_pct_c", u"imp_name", row_keys, u"chrom", u"spiked")
    min_combined = ops["min"](
        u"imp_pct_c", u"imp_name", row_keys, u"chrom", u"spiked")
    r.check("n=12 Z7 RSD", rsd_combined[0], _rsd_pct(combined), tol=1e-9)
    r.check("n=12 Z7 max", max_combined[0], max(combined))
    r.check("n=12 Z7 min", min_combined[0], min(combined))

    # -- ④ ★ key absent from EVERY source: '---' for every op, incl COUNT --
    r.check("GHOST avg -> placeholder", avg_combined[1], p._PLACEHOLDER)
    r.check("GHOST rsd -> placeholder", rsd_combined[1], p._PLACEHOLDER)
    r.check("GHOST max -> placeholder", max_combined[1], p._PLACEHOLDER)
    r.check("GHOST min -> placeholder", min_combined[1], p._PLACEHOLDER)
    r.check("GHOST count -> placeholder, NOT 0", count_combined[1],
            p._PLACEHOLDER)

    # -- ⑥ the four missing-value states (chrom only) --------------------
    avg_chrom = ops["avg"](u"imp_pct_c", u"imp_name", row_keys, u"chrom")
    rsd_chrom = ops["rsd"](u"imp_pct_c", u"imp_name", row_keys, u"chrom")
    count_chrom = ops["count"](u"imp_pct_c", u"imp_name", row_keys, u"chrom")

    # MISS: one real value survives out of three -- skip missing cells,
    # still compute from what is left.
    r.check("MISS: one survivor -- avg", avg_chrom[2], 5.0)
    r.check("MISS: <2 survivors -- rsd is placeholder",
            rsd_chrom[2], p._PLACEHOLDER)
    r.check("MISS: count of survivors", count_chrom[2], 1)

    # ALLMISS: the key IS matched (rows exist), but nothing numeric is
    # behind it -- '---' for avg/rsd, and COUNT is a definite 0 (NOT the
    # same failure as GHOST, which never matched at all -- judgement 4).
    r.check("ALLMISS: avg is placeholder", avg_chrom[3], p._PLACEHOLDER)
    r.check("ALLMISS: count is 0, not placeholder", count_chrom[3], 0)

    # ZEROMEAN: mean is exactly 0.0 -- rsd is placeholder (division by
    # zero would otherwise look like a real, if enormous, number).
    r.check("ZEROMEAN: avg is 0.0", avg_chrom[4], 0.0)
    r.check("ZEROMEAN: rsd is placeholder (mean==0)",
            rsd_chrom[4], p._PLACEHOLDER)
    r.check("ZEROMEAN: count is 2", count_chrom[4], 2)


def test_xagg_op_reuses_group_apply(p, r):
    """S2: XAGG_AVG/_RSD must BE _group_apply's own contract, not a
    second, rewritten copy of it (needs doc §3.6 point 1)."""
    code = _find_code(p, "_xagg_op")
    r.check("found _xagg_op", code is not None, True)
    if code is not None:
        r.check("_xagg_op calls _group_apply (closes over it)",
                "_group_apply" in code.co_freevars, True)

    install_engine_stubs()
    owner = _FakeOwner()
    sibling_data, existing_services = _xagg_op_fixture()
    ops, group_apply = _rebuild_xagg_ops(p, owner, sibling_data, existing_services)
    agg_stdev = rebuild(p, "_agg_stdev")
    agg_rsd = rebuild(p, "_agg_rsd", freevars={"_agg_stdev": agg_stdev})
    group_avglist = rebuild(p, "_group_avglist",
                             freevars={"_group_apply": group_apply})
    group_rsdlist = rebuild(p, "_group_rsdlist", freevars={
        "_group_apply": group_apply, "_agg_rsd": agg_rsd})

    combined = Z7_CHROM + Z7_SPIKED
    same_key = [u"Z7"] * len(combined)
    group_avg = group_avglist(combined, same_key)[0]
    group_rsd = group_rsdlist(combined, same_key)[0]

    xagg_avg = ops["avg"](
        u"imp_pct_c", u"imp_name", [u"Z7"], u"chrom", u"spiked")[0]
    xagg_rsd = ops["rsd"](
        u"imp_pct_c", u"imp_name", [u"Z7"], u"chrom", u"spiked")[0]

    r.check("XAGG_AVG matches GROUP_AVGlist on the same 12 values",
            xagg_avg, group_avg, tol=1e-12)
    r.check("XAGG_RSD matches GROUP_RSDlist on the same 12 values",
            xagg_rsd, group_rsd, tol=1e-12)


def test_xagg_op_scope_inherited_from_s1(p, r):
    """S2: XAGG_<OP> reads sibling data through the SAME _xagg_collect
    path S1 already proved goes through _sample_tree_analyses (whole
    sample tree, partitions included -- same scope as LOOKUP).  Not a
    new code path, so partition-crossing is not re-derived from scratch
    here; what matters is that S2 did not bypass it."""
    code = _find_code(p, "_xagg_op")
    r.check("found _xagg_op", code is not None, True)
    if code is not None:
        r.check("_xagg_op fetches through _xagg_collect (S1's helper)",
                "_xagg_collect" in code.co_freevars, True)
        r.check("_xagg_op does not call _sample_tree_analyses directly "
                "(reuses S1's sibling_data/existing_services instead)",
                "_sample_tree_analyses" in (code.co_names + code.co_freevars),
                False)


def test_xagg_op_registration(p, r):
    """S2: registered in _SAFE; rides S1's XAGG_\\w+ entry in
    _ARRAY_FN_RE -- no regex change needed for this slice."""
    safe = _registry_keys(p, "_SAFE")
    for name in ("XAGG_AVG", "XAGG_RSD", "XAGG_MAX", "XAGG_MIN",
                 "XAGG_COUNT"):
        r.check("%s registered in _SAFE" % name, name in safe, True)

    array_fn_re = re.compile(
        r'(GROUP_\w+(?:list)?|\w+_ROWS|RESULT_STATUS|TIME_ELAPSED_HOURS'
        r'|COALESCE|SHIFT|BASELINE_BYlist|XAGG_\w+|APPEND)\s*\(')
    for name in ("XAGG_AVG", "XAGG_RSD", "XAGG_MAX", "XAGG_MIN",
                 "XAGG_COUNT"):
        r.check("%s takes the array path via S1's XAGG_\\w+ entry" % name,
                bool(array_fn_re.search(u"%s(a,b,[c],d)" % name)), True)


def test_xagg_op_through_the_engine(p, r):
    """S2: drive the REAL engine -- the needs-doc shape,
    XAGG_AVG("imp_pct_c","imp_name",[imp_ip_name],"chrom","spiked"),
    with the row space itself (S1's XAGG_KEYS/APPEND) computed on the
    SAME analysis one field earlier.  This needs the engine's own
    cross-pass convergence (imp_ip_name is written by the "no array
    deps" branch, which does not update list_arrays/str_arrays within
    the same pass -- see the S1 Backlog note on that branch): the first
    pass computes imp_ip_name, and only a LATER pass re-parses its now-
    stored value into str_arrays for imp_ip_avg12 to reference through
    [imp_ip_name].  Passing only one pass here would show imp_ip_avg12
    stuck at its prior (empty) value -- this is what makes it an engine
    test rather than a direct-call one."""
    import json

    install_engine_stubs()

    def run(stat_fields):
        _, analyses = build_sample([
            {"as_id": "CHROM", "service_kw": "chrom", "fields": [
                {"keyword": "imp_name", "title": u"物质名称",
                 "result_type": "list",
                 "value": json.dumps([u"Z7"] * 6),
                 "cross_referenceable": True},
                {"keyword": "imp_pct_c", "title": u"含量",
                 "result_type": "list",
                 "value": json.dumps(Z7_CHROM),
                 "cross_referenceable": True},
            ]},
            {"as_id": "SPIKED", "service_kw": "spiked", "fields": [
                {"keyword": "imp_name", "title": u"物质名称",
                 "result_type": "list",
                 "value": json.dumps([u"Z7"] * 6),
                 "cross_referenceable": True},
                {"keyword": "imp_pct_c", "title": u"含量",
                 "result_type": "list",
                 "value": json.dumps(Z7_SPIKED),
                 "cross_referenceable": True},
            ]},
            {"as_id": "STAT", "service_kw": "stat", "fields": stat_fields},
        ])
        out = evaluate(p, analyses, ("CHROM", "SPIKED", "STAT"), passes=4)
        return dict((k.split(".", 1)[1], json.loads(v))
                    for k, v in out.items() if v)

    row_space_formula = u'APPEND(XAGG_KEYS("imp_name","chrom"), "TOTAL")'
    avg_formula = (u'XAGG_AVG("imp_pct_c","imp_name",[imp_ip_name],'
                   u'"chrom","spiked")')
    out = run([
        {"keyword": "imp_ip_name", "title": u"统计项",
         "result_type": "calculatedlist", "formula": row_space_formula},
        {"keyword": "imp_ip_avg12", "title": u"合并均值",
         "result_type": "calculatedlist", "formula": avg_formula},
    ])
    r.check("engine: row space", out.get("imp_ip_name"), [u"Z7", u"TOTAL"])
    combined = Z7_CHROM + Z7_SPIKED
    got = out.get("imp_ip_avg12") or []
    r.check("engine: XAGG_AVG row count", len(got), 2)
    if len(got) == 2:
        r.check("engine: Z7 combined mean", got[0], _mean(combined), tol=1e-9)
        r.check("engine: TOTAL row (no such key anywhere) -> placeholder",
                got[1], p._PLACEHOLDER)


def test_xagg_readme(p, r):
    """S1+S2+S3: README documents all three function groups, and
    specifically the distinctions that are easy to lose in a future
    edit -- 'matched zero rows' (COUNT -> '---') is not the same
    failure as 'matched rows with nothing numeric in them' (COUNT ->
    0), at BOTH reduction levels (XAGG_<OP> and XAGG_<OP>_OFSUM).
    Modelled on test_baseline_through_the_engine's README checks."""
    readme = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(p.__source_path__))),
        "..", "..", "README.md")
    readme = os.path.normpath(readme)
    r.check("README found at %s" % readme, os.path.exists(readme), True)
    if not os.path.exists(readme):
        return
    text = open(readme, "rb").read().decode("utf-8")
    for name in ("XAGG_KEYS", "APPEND", "XAGG_AVG", "XAGG_RSD", "XAGG_MAX",
                 "XAGG_MIN", "XAGG_COUNT", "XAGG_AVG_OFSUM", "XAGG_RSD_OFSUM",
                 "XAGG_MAX_OFSUM", "XAGG_MIN_OFSUM", "XAGG_COUNT_OFSUM"):
        r.check("README mentions %s" % name, name in text, True)
    r.check("README explains the two different '---' sources for XAGG_KEYS",
            u"未勾" in text and u"根本不存在" in text, True)
    r.check("README keeps the COUNT 'matched zero' vs 'matched but blank' "
            u"distinction", u"匹配到了行" in text and u"根本不存在" in text,
            True)
    r.check("README warns against COALESCE on the gate column",
            u"不要对" in text and u"做 `COALESCE` 兜底" in text, True)
    r.check("README documents OFSUM's three '---'/0 states",
            u"名单" in text and u"按份求和" in text, True)
    r.check("README's COALESCE section states the CORRECTED guard rule "
            u"(0 and '---' both invalidate a row, not just '---')",
            u"不是一个 > 0 的正整数" in text, True)
    r.check("README documents the known undetected-substance == total "
            u"broadcast cost",
            u"广播机制的必然结果" in text and u"取到的是总杂的标量" in text,
            True)


# ---- S3: XAGG_<OP>_OFSUM -- sum per sample, THEN aggregate across samples --
#
# Four synthetic samples (Backlog S3's worked example): P1/P2 from "chrom",
# P3/P4 from "spiked", differing peak counts (3/2/2/3), each carrying one
# substance NOT on the Z7/Z10 whitelist (OTHER/OTHER2/OTHER3) that must be
# excluded from the sum.  P5 (chrom) is a fifth sample whose one whitelisted
# peak has no numeric value at all -- it must vanish from the final
# aggregate AND from COUNT, without needing its own separate test.
SUMS_OFSUM = [3.0, 3.0, 9.0, 13.0]  # P1, P2, P3, P4 sums; P5 excluded


def _xagg_ofsum_fixture():
    sibling_data = {
        u"std": {u"imp_name": [u"Z7", u"Z10"]},
        u"chrom": {
            u"g_sample_id": [u"P1", u"P1", u"P1", u"P2", u"P2", u"P5"],
            u"imp_name": [u"Z7", u"Z10", u"OTHER", u"Z7", u"OTHER2", u"Z7"],
            u"imp_pct_c": [1.0, 2.0, 100.0, 3.0, 200.0, u""],
        },
        u"spiked": {
            u"g_sample_id": [u"P3", u"P3", u"P4", u"P4", u"P4"],
            u"imp_name": [u"Z7", u"Z10", u"Z7", u"Z10", u"OTHER3"],
            u"imp_pct_c": [4.0, 5.0, 6.0, 7.0, 300.0],
        },
    }
    existing_services = set([u"std", u"chrom", u"spiked"])
    return sibling_data, existing_services


def _rebuild_xagg_ofsum(p, owner, sibling_data, existing_services):
    """Rebuild XAGG_<OP>_OFSUM bottom-up through their shared cells."""
    norm_key = rebuild(p, "_norm_key")
    group_apply = rebuild(p, "_group_apply", freevars={"_norm_key": norm_key},
                          defaults=(p._PLACEHOLDER,))
    nums_only = rebuild(p, "_nums_only")
    agg_stdev = rebuild(p, "_agg_stdev")
    agg_rsd = rebuild(p, "_agg_rsd", freevars={"_agg_stdev": agg_stdev})
    xagg_warn = rebuild(p, "_xagg_warn")
    resolve_sources = rebuild(p, "_xagg_resolve_sources", freevars={
        "self": owner, "_xagg_warn": xagg_warn})
    collect = rebuild(p, "_xagg_collect", freevars={
        "self": owner,
        "_xagg_existing_services": existing_services,
        "sibling_data": sibling_data,
        "_xagg_resolve_sources": resolve_sources,
        "_xagg_warn": xagg_warn,
    })
    xagg_ofsum = rebuild(p, "_xagg_ofsum", freevars={
        "_group_apply": group_apply,
        "_norm_key": norm_key,
        "_nums_only": nums_only,
        "_xagg_collect": collect,
        "_xagg_warn": xagg_warn,
        "self": owner,
    })
    return {
        "avg": rebuild(p, "_xagg_avg_ofsum",
                       freevars={"_xagg_ofsum": xagg_ofsum}),
        "rsd": rebuild(p, "_xagg_rsd_ofsum", freevars={
            "_xagg_ofsum": xagg_ofsum, "_agg_rsd": agg_rsd}),
        "max": rebuild(p, "_xagg_max_ofsum",
                       freevars={"_xagg_ofsum": xagg_ofsum}),
        "min": rebuild(p, "_xagg_min_ofsum",
                       freevars={"_xagg_ofsum": xagg_ofsum}),
        "count": rebuild(p, "_xagg_count_ofsum",
                         freevars={"_xagg_ofsum": xagg_ofsum}),
    }


def _call_ofsum(fn, sibling_data_key_field=u"imp_name"):
    return fn(u"imp_pct_c", u"g_sample_id", sibling_data_key_field, u"std",
              u"chrom", u"spiked")


def test_xagg_ofsum_direct(p, r):
    """S3 (跨AS聚合): XAGG_<OP>_OFSUM, direct calls on the synthetic
    4(+1 blank)-sample fixture (Backlog S3's worked example)."""
    install_engine_stubs()
    owner = _FakeOwner()
    sibling_data, existing_services = _xagg_ofsum_fixture()
    ops = _rebuild_xagg_ofsum(p, owner, sibling_data, existing_services)
    for name in ("avg", "rsd", "max", "min", "count"):
        r.check("rebuilt XAGG_%s_OFSUM" % name.upper(),
                ops[name] is not None, True)

    # -- ①（先写死预期）+ ② COUNT counts SAMPLES, not rows -----------------
    # Raw rows: chrom 6 + spiked 5 = 11.  Whitelist-matched rows: 4 (chrom:
    # P1xZ7,P1xZ10,P2xZ7,P5xZ7) + 4 (spiked: P3xZ7,P3xZ10,P4xZ7,P4xZ10) = 8.
    # Distinct sample GROUPS: 5 (P1..P5).  The right answer is 4 -- P5's
    # group exists but contributed no number, so it must not count either.
    got_count = _call_ofsum(ops["count"])
    r.check("COUNT_OFSUM is the sample count with usable data (4)",
            got_count, 4)
    r.check("COUNT_OFSUM is NOT total raw rows (11)", got_count == 11, False)
    r.check("COUNT_OFSUM is NOT whitelist-matched ROWS (8)",
            got_count == 8, False)
    r.check("COUNT_OFSUM is NOT total sample GROUPS incl. the blank one (5)",
            got_count == 5, False)

    # -- ⑥ mean / rsd / max / min, independently computed ----------------
    got_avg = _call_ofsum(ops["avg"])
    got_rsd = _call_ofsum(ops["rsd"])
    got_max = _call_ofsum(ops["max"])
    got_min = _call_ofsum(ops["min"])
    r.check("AVG_OFSUM", got_avg, _mean(SUMS_OFSUM), tol=1e-9)
    r.check("RSD_OFSUM", got_rsd, _rsd_pct(SUMS_OFSUM), tol=1e-9)
    r.check("MAX_OFSUM", got_max, max(SUMS_OFSUM))
    r.check("MIN_OFSUM", got_min, min(SUMS_OFSUM))

    # -- ④ whitelist filtering actually changes the outcome ---------------
    # (the fixture already excludes OTHER/OTHER2/OTHER3 from every sum --
    # prove that is not a no-op by widening the whitelist and checking the
    # numbers move.)
    sibling_open, existing_open = _xagg_ofsum_fixture()
    sibling_open[u"std"][u"imp_name"] = [u"Z7", u"Z10", u"OTHER", u"OTHER2",
                                          u"OTHER3"]
    ops_open = _rebuild_xagg_ofsum(p, owner, sibling_open, existing_open)
    got_open_max = _call_ofsum(ops_open["max"])
    r.check("widening the whitelist changes the result "
            "(filtering is not a no-op)", got_open_max == got_max, False)
    r.check("widening it to admit OTHER3 raises P4's sum to 313.0 -- "
            "becomes the new max", got_open_max, 6.0 + 7.0 + 300.0)

    # -- ⑤ differing peak counts per sample do not skew individual sums --
    # already structural: P1 has 3 raw peaks, P2 has 2, P3 has 2, P4 has
    # 3 -- SUMS_OFSUM matching exactly above proves each sample's sum
    # depends only on ITS OWN whitelisted rows, not on peak count.

    # -- ⑦ the three '---' states, kept apart ------------------------------
    # (a) collect failure: the whitelist source does not exist at all.
    got_ghost_wl = ops["count"](u"imp_pct_c", u"g_sample_id", u"imp_name",
                                 u"ghost_std", u"chrom", u"spiked")
    r.check("(a) unreadable whitelist source -> COUNT is placeholder, "
            "not 0", got_ghost_wl, p._PLACEHOLDER)

    # (b) whitelist loads, but literally nothing in the data matches it.
    sibling_none, existing_none = _xagg_ofsum_fixture()
    sibling_none[u"std"][u"imp_name"] = [u"NOTHING_MATCHES"]
    ops_none = _rebuild_xagg_ofsum(p, owner, sibling_none, existing_none)
    r.check("(b) zero matches: avg is placeholder",
            _call_ofsum(ops_none["avg"]), p._PLACEHOLDER)
    r.check("(b) zero matches: COUNT is 0, not placeholder",
            _call_ofsum(ops_none["count"]), 0)

    # (c) a matched sample (P5) with nothing numeric behind it: already
    # baked into the main fixture.  COUNT==4 above already proves it is
    # excluded; this adds that it does not drag the mean toward 0 either.
    r.check("(c) the blank sample (P5) does not pull the mean toward 0",
            got_avg > 0, True)


def test_xagg_ofsum_reuses_group_apply(p, r):
    """S3: the first reduction (sum per sample) must BE _group_apply;
    the second reduction (aggregate across samples) must NOT be another
    call to it -- that would re-group the per-sample sums instead of
    just reducing them, a different and wrong operation."""
    code = _find_code(p, "_xagg_ofsum")
    r.check("found _xagg_ofsum", code is not None, True)
    if code is not None:
        r.check("_xagg_ofsum calls _group_apply for the per-sample sum",
                "_group_apply" in code.co_freevars, True)
        r.check("the second reduction goes through _nums_only, not a "
                "second _group_apply call",
                "_nums_only" in code.co_freevars, True)


def test_xagg_ofsum_registration(p, r):
    """S3: registered in _SAFE; needs NO _ARRAY_FN_RE change -- every
    argument is a string literal (like XAGG_KEYS in S1), so these
    formulas land in the "no array deps" branch, never the array path."""
    safe = _registry_keys(p, "_SAFE")
    for name in ("XAGG_AVG_OFSUM", "XAGG_RSD_OFSUM", "XAGG_MAX_OFSUM",
                 "XAGG_MIN_OFSUM", "XAGG_COUNT_OFSUM"):
        r.check("%s registered in _SAFE" % name, name in safe, True)


def test_xagg_ofsum_through_the_engine(p, r):
    """S3: drive the REAL engine -- a literal-only OFSUM formula takes
    the "no array deps" branch (same as XAGG_KEYS, S1) and must come
    back as a proper scalar, JSON-serialised as a ONE-element list (the
    shape needs doc §3.5's COALESCE broadcast depends on)."""
    import json

    install_engine_stubs()

    def run(stat_fields):
        _, analyses = build_sample([
            {"as_id": "STD", "service_kw": "std", "fields": [
                {"keyword": "imp_name", "title": u"物质名称",
                 "result_type": "list", "value": json.dumps([u"Z7", u"Z10"]),
                 "cross_referenceable": True},
            ]},
            {"as_id": "CHROM", "service_kw": "chrom", "fields": [
                {"keyword": "g_sample_id", "title": u"样品号",
                 "result_type": "list",
                 "value": json.dumps([u"P1", u"P1", u"P1", u"P2", u"P2"]),
                 "cross_referenceable": True},
                {"keyword": "imp_name", "title": u"物质名称",
                 "result_type": "list",
                 "value": json.dumps(
                     [u"Z7", u"Z10", u"OTHER", u"Z7", u"OTHER2"]),
                 "cross_referenceable": True},
                {"keyword": "imp_pct_c", "title": u"含量",
                 "result_type": "list",
                 "value": json.dumps([1.0, 2.0, 100.0, 3.0, 200.0]),
                 "cross_referenceable": True},
            ]},
            {"as_id": "SPIKED", "service_kw": "spiked", "fields": [
                {"keyword": "g_sample_id", "title": u"样品号",
                 "result_type": "list",
                 "value": json.dumps([u"P3", u"P3", u"P4", u"P4", u"P4"]),
                 "cross_referenceable": True},
                {"keyword": "imp_name", "title": u"物质名称",
                 "result_type": "list",
                 "value": json.dumps(
                     [u"Z7", u"Z10", u"Z7", u"Z10", u"OTHER3"]),
                 "cross_referenceable": True},
                {"keyword": "imp_pct_c", "title": u"含量",
                 "result_type": "list",
                 "value": json.dumps([4.0, 5.0, 6.0, 7.0, 300.0]),
                 "cross_referenceable": True},
            ]},
            {"as_id": "STAT", "service_kw": "stat", "fields": stat_fields},
        ])
        out = evaluate(p, analyses, ("STD", "CHROM", "SPIKED", "STAT"))
        return dict((k.split(".", 1)[1], json.loads(v))
                    for k, v in out.items() if v)

    avg_formula = (u'XAGG_AVG_OFSUM("imp_pct_c","g_sample_id","imp_name",'
                   u'"std","chrom","spiked")')
    count_formula = (u'XAGG_COUNT_OFSUM("imp_pct_c","g_sample_id","imp_name",'
                     u'"std","chrom","spiked")')
    # This fixture drops P5 (the blank sample) for simplicity -- P1..P4
    # are unchanged, so SUMS_OFSUM still applies.
    out = run([
        {"keyword": "imp_ip_total_avg", "title": u"总杂均值",
         "result_type": "calculatedlist", "formula": avg_formula},
        {"keyword": "imp_ip_total_n", "title": u"总杂 n",
         "result_type": "calculatedlist", "formula": count_formula},
    ])
    got = out.get("imp_ip_total_avg") or []
    r.check("engine: AVG_OFSUM is a one-element list", len(got), 1)
    if got:
        r.check("engine: AVG_OFSUM value", got[0], _mean(SUMS_OFSUM),
                tol=1e-9)
    got_n = out.get("imp_ip_total_n") or []
    r.check("engine: COUNT_OFSUM is a one-element list", len(got_n), 1)
    if got_n:
        r.check("engine: COUNT_OFSUM value is 4, not 9 raw source rows",
                got_n[0], 4)


# ---- S4: COALESCE(XAGG_AVG, XAGG_AVG_OFSUM) -- combining the two branches --
#
# No new patches.py functions: COALESCE and every XAGG_* it composes already
# existed after S1-S3.  This slice exists to verify the COMPOSITION, and it
# overturned the Backlog's own pre-written judgement -- see the module
# docstrings below and the Backlog / needs-doc 【实测更正】 for the story.


def test_xagg_coalesce(p, r):
    """S4: drive the REAL engine on needs doc §3.5's exact composition,
    with substance C fully undetected by BOTH technicians.

    This is the test that overturned Backlog S4's original judgement
    ("that row must NOT equal the total row").  It does, and it must --
    COALESCE falls through to the OFSUM scalar for ANY row XAGG_AVG
    could not answer, undetected-substance rows included, and that
    scalar is the SAME number for every row it is broadcast to.  The
    real guard is not "the raw value differs from the total" (it does
    not), it is "XAGG_COUNT correctly marks that row as not to be
    trusted" -- checked against BOTH of its failure shapes, '---' and 0,
    not just '---' as the needs doc originally said.
    """
    import json

    install_engine_stubs()

    _, analyses = build_sample([
        {"as_id": "STD", "service_kw": "std", "fields": [
            {"keyword": "imp_name", "title": u"物质名称",
             "result_type": "list", "value": json.dumps([u"A", u"B", u"C"]),
             "cross_referenceable": True},
        ]},
        {"as_id": "CHROM", "service_kw": "chrom", "fields": [
            {"keyword": "g_sample_id", "title": u"样品号",
             "result_type": "list", "value": json.dumps([u"S1"] * 3),
             "cross_referenceable": True},
            {"keyword": "imp_name", "title": u"物质名称",
             "result_type": "list", "value": json.dumps([u"A", u"B", u"C"]),
             "cross_referenceable": True},
            {"keyword": "imp_pct_c", "title": u"含量", "result_type": "list",
             "value": json.dumps([1.0, 2.0, u""]),
             "cross_referenceable": True},
        ]},
        {"as_id": "SPIKED", "service_kw": "spiked", "fields": [
            {"keyword": "g_sample_id", "title": u"样品号",
             "result_type": "list", "value": json.dumps([u"S2"] * 3),
             "cross_referenceable": True},
            {"keyword": "imp_name", "title": u"物质名称",
             "result_type": "list", "value": json.dumps([u"A", u"B", u"C"]),
             "cross_referenceable": True},
            {"keyword": "imp_pct_c", "title": u"含量", "result_type": "list",
             "value": json.dumps([3.0, 4.0, u""]),
             "cross_referenceable": True},
        ]},
        {"as_id": "STAT", "service_kw": "stat", "fields": [
            {"keyword": "imp_ip_name", "title": u"统计项",
             "result_type": "calculatedlist",
             "formula": u'APPEND(XAGG_KEYS("imp_name","std"), "总杂")'},
            {"keyword": "imp_ip_avg", "title": u"均值",
             "result_type": "calculatedlist",
             "formula": (
                 u'COALESCE('
                 u'XAGG_AVG("imp_pct_c","imp_name",[imp_ip_name],'
                 u'"chrom","spiked"),'
                 u'XAGG_AVG_OFSUM("imp_pct_c","g_sample_id","imp_name",'
                 u'"std","chrom","spiked"))')},
            {"keyword": "imp_ip_hit", "title": u"命中数",
             "result_type": "calculatedlist",
             "formula": (u'XAGG_COUNT("imp_pct_c","imp_name",[imp_ip_name],'
                         u'"chrom","spiked")')},
        ]},
    ])
    raw = evaluate(p, analyses, ("STD", "CHROM", "SPIKED", "STAT"), passes=4)
    out = dict((k.split(".", 1)[1], json.loads(v))
               for k, v in raw.items() if v)

    names = out.get("imp_ip_name")
    avg = out.get("imp_ip_avg")
    hit = out.get("imp_ip_hit")

    r.check("row space: A, B, C, TOTAL", names, [u"A", u"B", u"C", u"总杂"])

    # -- ①②预期反转 + 风险 2 复现 -----------------------------------------
    r.check("A: XAGG_AVG answers directly, no fallthrough", avg[0], 2.0)
    r.check("B: XAGG_AVG answers directly, no fallthrough", avg[1], 3.0)
    r.check("★ C (fully undetected) EQUALS the TOTAL row -- the known "
            "COALESCE-broadcast cost, not something to chase away",
            avg[2], avg[3])
    r.check("C's value is literally the OFSUM total (5.0)", avg[2], 5.0)

    # -- ③ the corrected guard rule vs the original (wrong) wording -------
    r.check("hit column: A/B matched with data, C matched with none, "
            "TOTAL never matched at all", hit, [2, 2, 0, p._PLACEHOLDER])

    def trustworthy(h):
        """Corrected rule (Backlog S4 judgement 3 / needs doc §6 risk 2
        【实测更正】): trustworthy only when hit is a positive number.
        Both 0 and '---' mean "do not read this row"."""
        return isinstance(h, (int, float)) and h > 0

    def trustworthy_original_wording(h):
        """The needs doc's ORIGINAL wording ("除总杂外任何一行显示 '---'
        即作废") -- checks only for the placeholder.  Kept here so the
        test demonstrates the gap instead of only asserting the fix."""
        return h != p._PLACEHOLDER

    r.check("corrected guard: A/B trustworthy, C/TOTAL are not",
            [trustworthy(h) for h in hit], [True, True, False, False])
    r.check("★ the ORIGINAL needs-doc wording wrongly calls C trustworthy",
            [trustworthy_original_wording(h) for h in hit],
            [True, True, True, False])
    r.check("the two guard rules disagree on C -- concrete proof the "
            "original wording had a gap, not just an assertion",
            trustworthy(hit[2]) == trustworthy_original_wording(hit[2]),
            False)

    # -- ⑤ COALESCE argument order is precedence: front branch wins first -
    r.check("front-branch answers are not overwritten by the fallback "
            "(A is 2.0, not 5.0)", avg[0] == avg[3], False)


def test_xagg_coalesce_no_new_code(p, r):
    """S4: this slice adds no new patches.py functions -- COALESCE and
    every XAGG_* it composes already existed after S1-S3 (Backlog S4
    states this in its own 状态 line; this is the code-level check)."""
    safe = _registry_keys(p, "_SAFE")
    for name in ("COALESCE", "XAGG_AVG", "XAGG_AVG_OFSUM", "XAGG_COUNT",
                 "XAGG_KEYS", "APPEND"):
        r.check("%s already registered (no new registration in S4)" % name,
                name in safe, True)


def test_fixed_s1(p, r):
    """修约位数随值传递 S1: the rounding family returns a _Fixed.

    Criteria ①-⑨ of the S1 slice in
    Docs/Cal增加/maitux.calcenhance-修约位数随值传递-Backlog.md; the ②.2 /
    ②.3 tables are 修约与显示口径.md §2.2 / §2.3 cell for cell.
    """
    import copy
    import json
    import pickle

    F = p._Fixed

    # ① the three text spellings agree
    for value, digits, want in ((1609.0, 0, "1609"), (3.1, 3, "3.100")):
        x = F(value, digits)
        r.check("① str(_Fixed(%r,%d))" % (value, digits), str(x), want)
        r.check("① unicode(_Fixed(%r,%d))" % (value, digits),
                unicode(x), unicode(want))
        r.check("① u'%%s' %% _Fixed(%r,%d)" % (value, digits),
                u"%s" % x, unicode(want))

    # ② still a float, never text -- the array engine classifies on this
    x = F(3.1, 3)
    r.check("② isinstance float", isinstance(x, float), True)
    r.check("② not basestring", isinstance(x, (str, unicode)), False)

    # ③ arithmetic gives a PLAIN float: the places do not spread
    r.check("③ _Fixed / 2 is float", type(x / 2) is float, True)
    r.check("③ _Fixed * 100 is float", type(x * 100) is float, True)
    r.check("③ _Fixed + _Fixed is float", type(x + x) is float, True)

    # ④ numeric comparison and ordering
    r.check("④ 3.100 > 5.0 is False", x > 5.0, False)
    ordered = sorted([F(10.0, 1), F(9.0, 1)])
    r.check("④ sorted numerically", [float(v) for v in ordered], [9.0, 10.0])

    # ⑤ deepcopy / pickle round trips keep digits and do not raise
    for label, dup in (("deepcopy", lambda v: copy.deepcopy(v)),
                       ("pickle", lambda v: pickle.loads(pickle.dumps(v))),
                       ("pickle-2", lambda v: pickle.loads(
                           pickle.dumps(v, 2)))):
        try:
            y = dup(x)
            r.check("⑤ %s keeps type" % label, type(y) is F, True)
            r.check("⑤ %s keeps digits" % label, y.digits, 3)
            r.check("⑤ %s keeps text" % label, str(y), "3.100")
        except Exception as err:
            r.check("⑤ %s raised" % label, repr(err), None)
    r.check("⑤ deepcopy of an interim dict holding one",
            str(copy.deepcopy({"value": [x]})["value"][0]), "3.100")

    # ⑥ 口径 §2.2: digits=0 never shows ".0"
    half_up, half_even = p._round_half_up, p._round_half_even
    table_0 = [
        (1609, "1609", "1609"), (1609.0, "1609", "1609"),
        (u"1609", "1609", "1609"), (1609.4, "1609", "1609"),
        (1609.5, "1610", "1610"), (2.5, "3", "2"), (3.5, "4", "4"),
    ]
    for value, want_up, want_even in table_0:
        r.check("⑥ ROUND(%r,0)" % (value,), str(half_up(value, 0)), want_up)
        r.check("⑥ ROUND_EVEN(%r,0)" % (value,),
                str(half_even(value, 0)), want_even)

    # ⑦ 口径 §2.3: digits=3 keeps trailing zeros
    table_3 = [
        (3.1, "3.100"), (3.100, "3.100"), (u"3.100", "3.100"),
        (3.0, "3.000"), (0.04, "0.040"),
    ]
    for value, want in table_3:
        r.check("⑦ ROUND(%r,3)" % (value,), str(half_up(value, 3)), want)
        r.check("⑦ ROUND_EVEN(%r,3)" % (value,),
                str(half_even(value, 3)), want)
    r.check("⑦ ROUND_UP(1.601,1)", str(p._round_up(1.601, 1)), "1.7")
    r.check("⑦ ROUND_DOWN(1.69,2)", str(p._round_down(1.69, 2)), "1.69")
    r.check("⑦ ROUND_DOWN(1.6,2)", str(p._round_down(1.6, 2)), "1.60")

    # ⑧ the placeholder is not wrapped
    got = half_even(u"---", 3)
    r.check("⑧ ROUND_EVEN('---',3) is the placeholder", got, u"---")
    r.check("⑧ ... and not a _Fixed", isinstance(got, F), False)
    r.check("⑧ list maps element-wise",
            [str(v) for v in half_even([3.1, u"---"], 3)],
            ["3.100", "---"])

    # ⑨ S1 must not change array storage: json still writes the float
    r.check("⑨ json.dumps unchanged", json.dumps([F(1609.0, 0)]), "[1609.0]")

    # repr() must round-trip through the array engine's eval, and must not
    # be an int literal (Py2 `1609/2` would be integer division).
    back = eval(repr([F(1609.0, 0), F(3.1, 3)]), {"_Fixed": F})
    r.check("repr round-trips digits", [str(v) for v in back],
            ["1609", "3.100"])
    r.check("repr is not an int literal", eval(repr(F(1609.0, 0)),
                                               {"_Fixed": F}) / 2, 804.5)

    # Negative digits round to tens but still print as an integer
    r.check("ROUND(1609,-1)", str(half_up(1609, -1)), "1610")


def test_fixed_s2_helpers(p, r):
    """修约位数随值传递 S2: revive / serialise, the two halves of form A'."""
    import json

    F, revive = p._Fixed, p._revive_fixed
    # 需求与方案 §2.3 table, plus the zero that `or` would have dropped
    for text, want in ((u"1609", "1609"), (u"3.100", "3.100"),
                       (u"1609.50", "1609.50"), (u"-958.88", "-958.88"),
                       (u"0.00", "0.00"), ("12.5", "12.5")):
        got = revive(text)
        r.check("revive %r is _Fixed" % text, isinstance(got, F), True)
        r.check("revive %r text" % text, str(got) if got is not None
                else None, want)
    # §6.3: anything that is not a plain fixed-point literal stays as is
    for text in (u"---", u"1,609", u" 12", u"12 ", u"1e3", u"+5", u"007",
                 u"", u"ND", u"＜0.05%", u"未知杂质", u"S1919-Z",
                 u"0." + u"1" * 20):
        r.check("revive %r -> None" % text, revive(text), None)
    for value in (1609.0, 3, None, [u"1"]):
        r.check("revive non-text %r -> None" % (value,), revive(value), None)

    # _stored_number: text keeps places, JSON numbers stay plain floats
    r.check("_stored_number(u'0.00') keeps digits",
            str(p._stored_number(u"0.00")), "0.00")
    r.check("_stored_number(1609.0) plain", type(p._stored_number(1609.0)),
            float)

    # _dumps_fixed: only _Fixed cells change
    r.check("_dumps_fixed mixed",
            p._dumps_fixed([F(1609.0, 0), 1609.0, u"---", u"＜0.05%",
                            F(0.0, 2)]),
            json.dumps([u"1609", 1609.0, u"---", u"＜0.05%", u"0.00"]))
    unrounded = [0.1 + 0.2, 1.0 / 3, 97816.0, 1e-7]
    r.check("_dumps_fixed of an unrounded column is json.dumps, byte for "
            "byte", p._dumps_fixed(unrounded), json.dumps(unrounded))

    # _num_or_none carries a _Fixed; _dec_quantize still rounds it
    x = F(3.1, 3)
    r.check("_num_or_none keeps _Fixed", p._num_or_none(x) is x, True)
    r.check("ROUND_EVEN of a _Fixed", str(p._round_half_even(x, 1)), "3.1")
    r.check("ROUND of a revived text", str(p._round_half_up(
        revive(u"2.50"), 0)), "3")


def test_fixed_s2_through_the_engine(p, r):
    """修约位数随值传递 S2: form A' end to end through the real engine.

    ④ is 口径 §2.4: BASELINE_BYlist over the hand-typed g_area must hand
    back exactly what was typed.  ③ is the slice's one way to break the
    feature: a rounded column stored as TEXT must still feed arithmetic.
    """
    import json

    install_engine_stubs()
    area = [u"1609", u"1484", u"55697", u"1609.50", u"1600", u"1480",
            u"55000", u"1610.0"]
    hours = [u"0", u"0", u"0", u"0", u"2", u"2", u"2", u"2"]
    peak = [u"A", u"B", u"C", u"D", u"A", u"B", u"C", u"D"]
    names = [u"未知杂质", u"S1919-Z", u"未知杂质", u"S1919-Z",
             u"未知杂质", u"S1919-Z", u"未知杂质", u"S1919-Z"]

    def run(passes=3):
        _, analyses = build_sample([{
            "as_id": "AS1", "service_kw": "s2fixed",
            "fields": [
                {"keyword": "g_area", "result_type": "list",
                 "value": json.dumps(area)},
                {"keyword": "imp_stab_time", "result_type": "list",
                 "value": json.dumps(hours)},
                {"keyword": "imp_pct_group", "result_type": "list",
                 "value": json.dumps(peak)},
                {"keyword": "imp_name", "result_type": "list",
                 "value": json.dumps(names)},
                {"keyword": "imp_base", "result_type": "calculatedlist",
                 "formula": u"BASELINE_BYlist([g_area],[imp_stab_time],"
                            u"[imp_pct_group])"},
                {"keyword": "imp_deviation", "result_type": "calculatedlist",
                 "formula": u"ROUND_EVEN([g_area]/[imp_base]*100, 1)"},
                {"keyword": "imp_ratio_raw", "result_type": "calculatedlist",
                 "formula": u"[g_area]/[imp_base]*100"},
                {"keyword": "imp_dev_half", "result_type": "calculatedlist",
                 "formula": u"[imp_deviation] / 2"},
                {"keyword": "imp_dev_max", "result_type": "calculatedlist",
                 "formula": u"GROUP_MAXlist([imp_deviation],[imp_pct_group])"},
                {"keyword": "imp_by_hour", "result_type": "calculatedlist",
                 "formula": u"GROUP_SUMlist([g_area],[imp_stab_time])"},
                {"keyword": "imp_name_copy", "result_type": "calculatedlist",
                 "formula": u"[imp_name]"},
            ]}])
        return analyses, evaluate(p, analyses, ("AS1",), passes=passes)

    analyses, out = run()
    got = dict((k.split(".", 1)[1], json.loads(v))
               for k, v in out.items() if v)

    # ④ a pure carry comes back exactly as typed
    r.check("④ BASELINE_BYlist carries g_area as typed",
            got.get("imp_base"), area[:4] * 2)
    # ① a rounded column is stored as fixed-point text
    r.check("① ROUND_EVEN column stored as text",
            got.get("imp_deviation"),
            [u"100.0"] * 4 + [u"99.4", u"99.7", u"98.7", u"100.0"])
    # ② an unrounded column is still JSON numbers, byte for byte what
    #    json.dumps of the plain computation gives
    want_raw = [a / b * 100 for a, b in zip(
        [float(v) for v in area], [float(v) for v in area[:4] * 2])]
    r.check("② unrounded column untouched", out.get("AS1.imp_ratio_raw"),
            json.dumps(want_raw))
    # ③ a text-stored rounded column still feeds arithmetic (not '---')
    r.check("③ downstream of the rounded column computes",
            got.get("imp_dev_half"),
            [50.0] * 4 + [49.7, 49.85, 49.35, 50.0])
    # selection keeps the places, arithmetic does not
    r.check("GROUP_MAXlist of a rounded column keeps places",
            got.get("imp_dev_max"), [u"100.0"] * 8)
    r.check("GROUP_SUMlist is computed, so plain",
            [type(v) for v in got.get("imp_by_hour", [])], [float] * 8)
    # text keys "0"/"2" still group (the _norm_key spelling)
    r.check("GROUP_SUMlist by a text key still groups",
            got.get("imp_by_hour")[0],
            1609 + 1484 + 55697 + 1609.5)
    # names are not mistaken for numbers
    r.check("name column not wrapped", got.get("imp_name_copy"), names)

    # stable: one more pass writes nothing new (the text identity §4.1
    # rests on "same inputs -> same bytes")
    before = dict((i["keyword"], i["value"])
                  for i in analyses["AS1"].getInterimFields())
    p._evaluate_interims_ordered(analyses["AS1"])
    after = dict((i["keyword"], i["value"])
                 for i in analyses["AS1"].getInterimFields())
    r.check("a further pass changes no stored byte", after == before, True)


def test_fixed_s2_result_status(p, r):
    """S2 follow-up: RESULT_STATUS passes a rounded number through WITH its
    places -- "先修约、再分档" is how every 报告值 column is written, and
    the 0.10-not-0.1 display (裁决 H5) lives or dies here."""
    import json

    install_engine_stubs()
    _, analyses = build_sample([{
        "as_id": "AS1", "service_kw": "s2rs", "fields": [
            {"keyword": "imp_pct", "result_type": "list",
             "value": json.dumps([u"0.1", u"0.0449", u"0.01", u"1.2"])},
            {"keyword": "loq", "result_type": "", "value": u"0.05"},
            {"keyword": "lod", "result_type": "", "value": u"0.02"},
            {"keyword": "imp_pct_round", "result_type": "calculatedlist",
             "formula": u"ROUND_EVEN([imp_pct], 2)"},
            {"keyword": "imp_report", "result_type": "calculatedlist",
             "formula": u"RESULT_STATUS([imp_pct_round],[loq],[lod])"},
        ]}])
    out = evaluate(p, analyses, ("AS1",))
    r.check("RESULT_STATUS keeps the rounded places, labels as before",
            json.loads(out.get("AS1.imp_report") or "[]"),
            [u"0.10", u"＜0.05%", u"ND", u"1.20"])


def test_fixed_s2_cross_as(p, r):
    """S2 (2026-09-24 addition): the cross-AS collector keeps places too."""
    import json

    install_engine_stubs()
    _, analyses = build_sample([
        {"as_id": "SRC", "service_kw": "src_as", "fields": [
            {"keyword": "cf", "result_type": "calculated",
             "formula": u"ROUND_EVEN([cf_raw], 2)",
             "cross_referenceable": True},
            {"keyword": "cf_raw", "result_type": "", "value": u"1.0"},
            {"keyword": "rep", "result_type": "list",
             "value": json.dumps([u"0.10", u"0.15"]),
             "cross_referenceable": True},
            # a key column typed as TEXT: reads back as _Fixed "1" / "2"
            {"keyword": "rk", "result_type": "list",
             "value": json.dumps([u"1", u"2"]),
             "cross_referenceable": True},
        ]},
        {"as_id": "DST", "service_kw": "dst_as", "fields": [
            # ... matched against JSON NUMBERS here: "1.0" / "2.0" as text
            {"keyword": "g_x", "result_type": "list",
             "value": json.dumps([1.0, 2.0])},
            {"keyword": "g_one", "result_type": "", "value": u"2"},
            {"keyword": "cf_lookup", "result_type": "calculatedlist",
             "formula": u'LOOKUP("src_as","cf","cf","")'},
            {"keyword": "cf_scalar", "result_type": "calculated",
             "formula": u'LOOKUP("src_as","cf","cf","")'},
            {"keyword": "rep_lookup", "result_type": "calculatedlist",
             "formula": u'LOOKUP("src_as","rep","rk",[g_x])'},
            {"keyword": "rep_lookup2", "result_type": "calculatedlist",
             "formula": u'LOOKUP2("src_as","rep","rk",[g_x],"rk",[g_x])'},
            {"keyword": "rep_scalar", "result_type": "calculated",
             "formula": u'LOOKUP("src_as","rep","rk",[g_one])'},
        ]},
    ])
    out = evaluate(p, analyses, ("SRC", "DST"))
    r.check("source scalar stored with places", out.get("SRC.cf"), u"1.00")
    r.check("LOOKUP into a list keeps the places",
            json.loads(out.get("DST.cf_lookup") or "[]"), [u"1.00"])
    r.check("LOOKUP into a scalar keeps the places",
            out.get("DST.cf_scalar"), u"1.00")
    # the key spelling: text "1" on one side, number 1.0 on the other,
    # must still meet (_key_text) -- and the value keeps its places
    r.check("LOOKUP text key vs number key still matches",
            json.loads(out.get("DST.rep_lookup") or "[]"), [u"0.10", u"0.15"])
    r.check("LOOKUP2 text key vs number key still matches",
            json.loads(out.get("DST.rep_lookup2") or "[]"),
            [u"0.10", u"0.15"])
    r.check("scalar engine LOOKUP (float key) vs text key",
            out.get("DST.rep_scalar"), u"0.15")


def test_fixed_s1_scalar_engine(p, r):
    """S1 ⑩ (rewritten): the SCALAR engine stores the fixed-point text.

    "Scalar is free" (Backlog S1): _stringify_result ends in str(result),
    and str(_Fixed) is already the fixed-point text.  lims-dev has no
    scalar ROUND field with digits != 1 (42 Calculations checked on
    2026-09-24), so this is where the claim is actually observed.
    """
    install_engine_stubs()
    _, analyses = build_sample([{
        "as_id": "AS1", "service_kw": "s1scalar",
        "fields": [
            {"keyword": "x", "result_type": "", "value": u"1609.4"},
            {"keyword": "y", "result_type": "", "value": u"3.1"},
            {"keyword": "r0", "result_type": "calculated",
             "formula": u"ROUND_EVEN([x], 0)"},
            {"keyword": "r3", "result_type": "calculated",
             "formula": u"ROUND_EVEN([y], 3)"},
            {"keyword": "half", "result_type": "calculated",
             "formula": u"[r3] / 2"},
        ]}])
    out = evaluate(p, analyses, ("AS1",))
    r.check("⑩ scalar ROUND_EVEN(1609.4,0) stored", out.get("AS1.r0"),
            "1609")
    r.check("⑩ scalar ROUND_EVEN(3.1,3) stored", out.get("AS1.r3"),
            "3.100")
    # read back as a plain float: arithmetic on it is ordinary
    r.check("⑩ downstream of a rounded scalar is ordinary",
            out.get("AS1.half"), "1.55")


def test_fixed_s1_through_the_engine(p, r):
    """S1: a rounded column feeding another ARRAY formula still evaluates.

    The array path inlines columns with repr(), so _Fixed has to be
    resolvable in _SAFE or the downstream column becomes "---".
    """
    import json

    install_engine_stubs()
    _, analyses = build_sample([{
        "as_id": "AS1", "service_kw": "s1fixed",
        "fields": [
            {"keyword": "g_area", "result_type": "list",
             "value": json.dumps([u"100.04", u"200.06", u"300"])},
            {"keyword": "g_grp", "result_type": "list",
             "value": json.dumps([u"A", u"A", u"B"])},
            {"keyword": "rnd", "result_type": "calculatedlist",
             "formula": u"ROUND_EVEN([g_area], 1)"},
            {"keyword": "grp_sum", "result_type": "calculatedlist",
             "formula": u"GROUP_SUMlist([rnd], [g_grp])"},
        ]}])
    out = evaluate(p, analyses, ("AS1",))
    got = dict((k.split(".", 1)[1], json.loads(v))
               for k, v in out.items() if v)
    # S1 left array STORAGE alone; S2 writes a rounded column as its
    # fixed-point text (storage form A').
    r.check("engine: rounded column stored as text (S2)", out.get("AS1.rnd"),
            '["100.0", "200.1", "300.0"]')
    r.check("engine: rounded column stored",
            [float(v) for v in got.get("rnd", [])], [100.0, 200.1, 300.0])
    r.check("engine: downstream array formula not blanked",
            [round(float(v), 6) for v in got.get("grp_sum", [])],
            [300.1, 300.1, 300.0])


def test_earliest_time_s5(p, r):
    """S5 (修约位数随值传递 Backlog): EARLIEST_TIME as TIME_ELAPSED_HOURS's base.

    供试品溶液稳定性-2/-3: hours counted from the earliest injection of the
    segment chosen in 「稳定性来源」, not from this segment's own first row.
    """
    import json

    install_engine_stubs()
    formula = (u'TIME_ELAPSED_HOURS([imp_stab2_inj_time], 1, '
               u'EARLIEST_TIME([imp_stab2_source], "imp_inj_time"))')

    def run(cold_times, source=u"imp_stability_cold", own=None,
            f=formula):
        _, analyses = build_sample([
            {"as_id": "COLD", "service_kw": "imp_stability_cold", "fields": [
                {"keyword": "imp_inj_time", "result_type": "list",
                 "value": json.dumps(cold_times),
                 "cross_referenceable": True}]},
            {"as_id": "RT", "service_kw": "imp_stability_rt", "fields": [
                {"keyword": "imp_inj_time", "result_type": "list",
                 "value": json.dumps([u"2026-05-13 08:00"]),
                 "cross_referenceable": True}]},
            {"as_id": "S2", "service_kw": "imp_stab_sample2", "fields": [
                {"keyword": "imp_stab2_source", "result_type": "select",
                 "value": source},
                {"keyword": "imp_stab2_inj_time", "result_type": "list",
                 "value": json.dumps(own or [u"2026-05-14 20:13",
                                             u"2026-05-15 02:13"])},
                {"keyword": "imp_stab2_time", "result_type": "calculatedlist",
                 "formula": f}]},
        ])
        out = evaluate(p, analyses, ("COLD", "RT", "S2"))
        return json.loads(out.get("S2.imp_stab2_time") or "null")

    cold = [u"2026-05-12 20:13", u"2026-05-12 18:13", u"2026-05-13 20:13"]
    # t0 = the COLD segment's earliest (18:13 on the 12th), not its first row
    r.check("S5 hours from the selected segment's earliest injection",
            run(cold), [u"50.0", u"56.0"])
    r.check("S5 the dropdown decides: RT gives a different t0",
            run(cold, source=u"imp_stability_rt"), [u"36.2", u"42.2"])
    r.check("S5 literal source works the same way",
            run(cold, f=formula.replace(u"[imp_stab2_source]",
                                        u'"imp_stability_cold"')),
            [u"50.0", u"56.0"])
    # ★ no fallback: a source with no times must not become "hours since my
    # own first row" ([0.0, 6.0]) -- that would read as perfectly ordinary
    r.check("S5 empty source -> column '---' (no fallback to own t0)",
            run([]), [u"---", u"---"])
    r.check("S5 no source selected -> '---'", run(cold, source=u""),
            [u"---", u"---"])
    r.check("S5 slash timestamp in the source is refused, not skipped",
            run([u"2026/05/12 18:13", u"2026-05-12 20:13"]),
            [u"---", u"---"])

    # dependency: editing the chosen segment must re-evaluate this AS
    r.check("S5 dynamic source is a dependency",
            p._lookup_has_dynamic_source(formula), True)
    r.check("S5 literal source is extracted",
            u"imp_stability_cold" in p._extract_lookup_sources(
                u'EARLIEST_TIME("imp_stability_cold", "imp_inj_time")'),
            True)
    r.check("S5 registered in _SAFE", "EARLIEST_TIME" in
            _registry_keys(p, "_SAFE"), True)


def main():
    p = load_patches()
    print("IMPORT OK  (no Zope instance started)")
    print("  source under test: %s" % p.__source_path__)

    r = Results()
    test_module_level_visibility(p, r)
    test_num_or_none(p, r)
    test_t_95_table(p, r)
    test_hoisted_names_resolve_as_globals(p, r)
    test_rows_regression_runs(p, r)
    test_avg_rows(p, r)
    test_count_values_rows(p, r)
    test_registry_totals(p, r)
    test_s1_registration(p, r)
    test_band(p, r)
    test_gate(p, r)
    test_s2_registration(p, r)
    test_reg_stats(p, r)
    test_reg_param_se_and_ci(p, r)
    test_ci_rows_wrappers(p, r)
    test_s3_registration(p, r)
    test_lookup_dynamic_source_detection(p, r)
    test_literal_lookup_sources_unchanged(p, r)
    test_dependent_lookup_branch_wired(p, r)
    test_group_ci_whole_column(p, r)
    test_s7_registration(p, r)
    test_round_up(p, r)
    test_round_down(p, r)
    test_fixed_s1(p, r)
    test_fixed_s1_scalar_engine(p, r)
    test_fixed_s2_helpers(p, r)
    test_fixed_s2_through_the_engine(p, r)
    test_fixed_s2_result_status(p, r)
    test_fixed_s2_cross_as(p, r)
    test_earliest_time_s5(p, r)
    test_fixed_s1_through_the_engine(p, r)
    test_baseline_bylist(p, r)
    test_baseline_registration(p, r)
    test_baseline_through_the_engine(p, r)
    test_xagg_keys_and_append(p, r)
    test_xagg_row_space_registration(p, r)
    test_xagg_through_the_engine(p, r)
    test_xagg_op_direct(p, r)
    test_xagg_op_reuses_group_apply(p, r)
    test_xagg_op_scope_inherited_from_s1(p, r)
    test_xagg_op_registration(p, r)
    test_xagg_op_through_the_engine(p, r)
    test_xagg_ofsum_direct(p, r)
    test_xagg_ofsum_reuses_group_apply(p, r)
    test_xagg_ofsum_registration(p, r)
    test_xagg_ofsum_through_the_engine(p, r)
    test_xagg_coalesce(p, r)
    test_xagg_coalesce_no_new_code(p, r)
    test_xagg_readme(p, r)
    return r.report(
        "S0-S7 engine helpers + BASELINE_BYlist + XAGG row space + "
        "XAGG_<OP> + XAGG_<OP>_OFSUM + COALESCE composition")


if __name__ == "__main__":
    sys.exit(main())
