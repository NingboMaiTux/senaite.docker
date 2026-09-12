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
EXPECTED_SAFE_ENTRIES = 66
EXPECTED_SCALAR_ENTRIES = 26


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

    _dependent_sibling_analyses needs live Analysis objects, so it cannot be
    called here; what can be checked is that it reads both predicates.  The
    behavioural half -- edit the source, watch the downstream change -- is
    S6, on a real Analysis Service.
    """
    code = p._dependent_sibling_analyses.__code__
    for name in ("_extract_lookup_sources", "_lookup_has_dynamic_source",
                 "_is_cross_referenceable_source"):
        r.check("dependency scan calls %s" % name, name in code.co_names, True)

    # The dynamic branch must be gated on this analysis being a possible
    # source; ungated, every unrelated edit would drag dynamic-source
    # siblings through a recalculation.
    src = open(p.__source_path__, "rb").read().decode("utf-8")
    r.check("dynamic branch is gated",
            u"may_be_dynamic_source\n" in src
            or u"may_be_dynamic_source" in src, True)


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
    """Rebuild ROUND_EVEN, which recurses and so closes over itself.

    Python 2 has no writable cell, so the self-reference goes in as a
    trampoline that is pointed at the real function once it exists.  Only
    the list branch follows it; the scalar calls below never do.
    """
    box = {}
    fn = rebuild(p, "_round_half_even", defaults=(0,), freevars={
        "_round_half_even": lambda *a, **kw: box["fn"](*a, **kw),
        "_dec_quantize": rebuild(p, "_dec_quantize")})
    box["fn"] = fn
    return fn


def _rebuild_round_up(p):
    """Rebuild ROUND_UP.  Same shape as _rebuild_round_even: it recurses on
    the list branch, so the self-reference goes in as a trampoline."""
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
    r.check("engine: deviation column", two_column.get("imp_deviation"),
            [100.0] * 5 + S1919_DEVIATION_8H)
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
    test_baseline_bylist(p, r)
    test_baseline_registration(p, r)
    test_baseline_through_the_engine(p, r)
    return r.report("S0-S7 engine helpers + BASELINE_BYlist")


if __name__ == "__main__":
    sys.exit(main())
