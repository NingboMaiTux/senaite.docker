# -*- coding: utf-8 -*-
"""functions.json <-> the shipped patches.py (函数清单 S2).

Run inside the container (Python 2.7):

    MSYS_NO_PATHCONV=1 docker cp tests/ maituxlimslatest:/tmp/ce_tests/
    MSYS_NO_PATHCONV=1 docker exec maituxlimslatest python /tmp/ce_tests/test_function_manifest.py

Exit code 0 means every case passed.

Why this exists next to calcfuncs.py
------------------------------------
The host-side reader (.claude/skills/senaite-config-guide/tools/calcfuncs.py)
already refuses to load a manifest that disagrees with patches.py -- but only
for someone who runs the pipeline.  Somebody who adds a function to the engine
and only runs this package's tests would never see it.  This file makes the
same textual check in the container's Python 2, against the SHIPPED files, so
"added to the engine, forgot the manifest" goes red here too.

What it checks (mechanical fields only -- names, tables, array_path; shape /
params / purpose / since are human-decided and nothing in the code can confirm
them, SPEC Q4):

    every engine name is in the manifest          (one assertion per name)
    every manifest name is in an engine table     (one assertion per name)
    tables  == where the name is registered       (one per name)
    array_path == _ARRAY_FN_RE.search(name + "(") (one per name)
    + engine_version == setup.py, _Fixed is the real module-level
      class and is flagged internal, purpose reads back as unicode (R13),
      exactly one _ARRAY_FN_RE definition.

One assertion per name is deliberate: a mutation (delete DISTINCT_RANGE, add
FOO, flip SHIFT.array_path) turns exactly ONE line red and names the function,
instead of one "sets differ" line that says nothing.

Paths: CALCENHANCE_PATCHES (as harness.py) and CALCENHANCE_MANIFEST (as
calcfuncs.py; default = functions.json beside patches.py).
"""

from __future__ import print_function

import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import DEFAULT_PATCHES, Results, load_patches  # noqa: E402
from test_engine import _registry_keys  # noqa: E402

TABLES = ("scalar", "list")


def _paths(p):
    src_path = os.environ.get("CALCENHANCE_PATCHES") or DEFAULT_PATCHES
    manifest = os.environ.get("CALCENHANCE_MANIFEST") or os.path.join(
        os.path.dirname(src_path), "functions.json")
    setup = os.path.join(os.path.dirname(src_path), "..", "..", "..", "setup.py")
    return src_path, manifest, setup


def _array_fn_re(src):
    """_ARRAY_FN_RE = re.compile(r'...' r'...') -> (compiled, number of definitions)."""
    defs = list(re.finditer(r"_ARRAY_FN_RE\s*=\s*re\.compile\(", src))
    if not defs:
        return None, 0
    pos, parts = defs[0].end(), []
    lit = re.compile(r"\s*r(['\"])((?:(?!\1).)*)\1")
    while True:
        m = lit.match(src, pos)
        if not m:
            break
        parts.append(m.group(2))
        pos = m.end()
    return re.compile(u"".join(parts)), len(defs)


# The three constants sit in both tables but are not functions; calcfuncs.py
# and check_v10.py drop them the same way.
CONSTANTS = set([u"True", u"False", u"None"])


def _engine(p):
    scalar = set(_registry_keys(p, "safe_globals")) - CONSTANTS
    lst = set(_registry_keys(p, "_SAFE")) - CONSTANTS
    out = {}
    for n in scalar | lst:
        out[n] = [t for t, s in zip(TABLES, (scalar, lst)) if n in s]
    return out


def test_names(p, r, man, engine):
    fns = man["functions"]
    for n in sorted(engine):
        r.check(u"engine name %s is in the manifest" % n, n in fns, True)
    for n in sorted(fns):
        r.check(u"manifest name %s is in an engine table" % n, n in engine, True)


def test_tables(p, r, man, engine):
    fns = man["functions"]
    for n in sorted(set(fns) & set(engine)):
        r.check(u"%s tables" % n, fns[n].get("tables"), engine[n])


def test_array_path(p, r, man, engine, arr):
    fns = man["functions"]
    for n in sorted(set(fns) & set(engine)):
        r.check(u"%s array_path" % n, fns[n].get("array_path"),
                bool(arr.search(n + u"(")))


def test_misc(p, r, man, engine, n_defs, setup_path):
    fns = man["functions"]
    # No separate "entry count == 97" assertion: the two per-name directions in
    # test_names already make the name sets equal, and a count line would only
    # turn the same mistake red twice (it did, on the first mutation run).
    ver = re.search(r"""^version\s*=\s*['"]([^'"]+)['"]""",
                    io.open(setup_path, encoding="utf-8").read(), re.M)
    r.check(u"engine_version == setup.py version",
            man.get("engine_version"), ver and ver.group(1))
    r.check(u"_Fixed is the real module-level class and is flagged internal",
            (isinstance(getattr(p, "_Fixed", None), type),
             fns.get("_Fixed", {}).get("internal")), (True, True))
    # R13: Py2 json hands back unicode; a label built from it must not blow up
    words = [w for e in fns.values() for w in e.get("purpose", [])]
    ok = bool(words) and all(isinstance(w, type(u"")) for w in words)
    try:
        u"%s" % u", ".join(words)
    except UnicodeError:
        ok = False
    r.check(u"purpose reads back as unicode under Py2 (R13)", ok, True)
    r.check(u"exactly one _ARRAY_FN_RE definition", n_defs, 1)


def main():
    p = load_patches()
    print("IMPORT OK  (no Zope instance started)")
    print("  source under test: %s" % p.__source_path__)
    src_path, manifest, setup = _paths(p)
    print("  manifest under test: %s" % manifest)

    man = json.load(io.open(manifest, encoding="utf-8"))
    src = io.open(p.__source_path__, encoding="utf-8").read()
    arr, n_defs = _array_fn_re(src)
    engine = _engine(p)

    r = Results()
    test_names(p, r, man, engine)
    test_tables(p, r, man, engine)
    if arr is not None:
        test_array_path(p, r, man, engine, arr)
    test_misc(p, r, man, engine, n_defs, setup)
    return r.report(u"function manifest <-> patches.py")


if __name__ == "__main__":
    sys.exit(main())
