# -*- coding: utf-8 -*-
"""Load the real patches.py under Python 2.7 without starting Zope.

Why this exists
---------------
Every formula function in this package lives in patches.py, which imports
bika.lims, Products.Archetypes and zope.event at module scope.  Importing it
normally therefore drags in the whole Zope stack, and the obvious alternative
-- running the code through ``bin/instance run`` -- starts a SECOND Zope
process inside a 1024MB container and gets both of them OOM-killed (see
CLAUDE.md section 4).  Neither is usable as a test harness.

Stubbing those three modules is enough: patches.py executes nothing at import
time except constants, function definitions and class definitions.  The
monkey-patching itself happens in apply_patches(), which is only called at
startup and is never called here.

So this harness tests THE SHIPPED FILE, not a transcription of it.  That
distinction is the whole point: a hand-copied function body drifts away from
the original the moment somebody edits one and not the other, and the test
keeps passing while the shipped code is broken.  (load_patches does copy the
file to a scratch directory before importing -- see the comment there -- but
it copies at load time from the real path, so no drift is possible.)

Run it inside the container, which is the only place a Python 2.7 lives:

    MSYS_NO_PATHCONV=1 docker cp tests/ maituxlimslatest:/tmp/ce_tests/
    MSYS_NO_PATHCONV=1 docker exec maituxlimslatest python /tmp/ce_tests/test_engine.py

Limits
------
Only MODULE-LEVEL names are reachable.  Anything defined inside
_evaluate_calculatedlist_interims (its 1200-line body) is a closure and cannot
be imported -- that is precisely why the shared helpers were hoisted.  Nested
wrappers still have to be verified on a real Analysis Service.
"""

from __future__ import print_function

import imp
import os
import shutil
import sys
import tempfile
import types

DEFAULT_PATCHES = (
    "/opt/addons/customers/maitux.calcenhance"
    "/src/maitux/calcenhance/patches.py"
)


def _stub(name, attrs=None):
    """Register a placeholder module so a module-scope import succeeds."""
    module = types.ModuleType(name)
    for key, value in (attrs or {}).items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def load_patches(path=None):
    """Import the real patches.py and hand back the module object."""
    path = path or os.environ.get("CALCENHANCE_PATCHES") or DEFAULT_PATCHES
    if not os.path.exists(path):
        raise RuntimeError(
            "patches.py not found at %s -- pass a path or set "
            "CALCENHANCE_PATCHES" % path)

    # Load a byte-for-byte copy in a scratch directory rather than the file
    # in place.  Two reasons, both learned the hard way on the first run:
    #
    #   - imp.load_source drops a .pyc beside the source, and that source is
    #     the bind-mounted addon the live instance imports from.  A test run
    #     should not write bytecode into the tree someone is editing.
    #   - once such a .pyc exists, load_source reports __file__ as the .pyc
    #     and it stops being obvious whether the test read the current source
    #     or cached bytecode.  That ambiguity is the exact trap CLAUDE.md
    #     flags for C4_SOURCE_IMPORTABLE, and it has no place in a harness
    #     whose whole job is to prove what the real file does.
    #
    # The copy is made from the target at load time, so it cannot drift the
    # way a hand-maintained duplicate would.
    sys.dont_write_bytecode = True
    scratch = tempfile.mkdtemp(prefix="calcenhance_")
    copy_path = os.path.join(scratch, "patches_under_test.py")
    shutil.copyfile(path, copy_path)

    # Only the three module-scope imports need standing in for.  Everything
    # else patches.py touches is imported lazily inside functions.
    _stub("bika")
    _stub("bika.lims", {
        "bikaMessageFactory": lambda s: s,
        "logger": None,
    })
    _stub("Products")
    _stub("Products.Archetypes")
    _stub("Products.Archetypes.event", {"ObjectEditedEvent": object})
    _stub("zope")
    _stub("zope.event", {"notify": lambda *a, **kw: None})

    module = imp.load_source("calcenhance_patches_under_test", copy_path)
    # Point callers at the real file, not the scratch copy: the source-text
    # assertions have to read what is actually shipped.
    module.__source_path__ = path
    return module


def _make_cell(value):
    """A closure cell holding `value` (Python 2 has no cell constructor)."""
    return (lambda v: (lambda: v))(value).__closure__[0]


def walk_code(code):
    """Every code object nested inside `code`, itself included."""
    yield code
    for const in code.co_consts:
        if hasattr(const, "co_name"):
            for sub in walk_code(const):
                yield sub


def rebuild(module, name, freevars=None, defaults=None, root=None):
    """Rebuild a function nested inside the engine so it can be called.

    The formula helpers live inside _evaluate_calculatedlist_interims, a
    1200-line function, so they cannot be imported.  Their code objects can
    be, though: a nested function is just a code object sitting in the
    enclosing function's co_consts, and binding it to the module namespace
    reproduces the original exactly -- same bytecode, same globals.

    Helpers that reference a sibling nested function close over it, so pass
    those in `freevars` as {name: already-rebuilt function}; the cells are
    assembled in the order co_freevars declares.  Bottom-up, that reaches
    every helper in the file.

    Returns None when no such nested function exists, so a rename shows up as
    a failed assertion rather than a silently skipped test.
    """
    root = root or module._evaluate_calculatedlist_interims
    for code in walk_code(root.__code__):
        if code.co_name != name:
            continue
        supplied = freevars or {}
        missing = [fv for fv in code.co_freevars if fv not in supplied]
        if missing:
            raise RuntimeError(
                "%s closes over %s -- rebuild those first and pass them in"
                % (name, ", ".join(missing)))
        cells = tuple(_make_cell(supplied[fv]) for fv in code.co_freevars)
        return types.FunctionType(
            code, module.__dict__, name, defaults, cells)
    return None


class Results(object):
    """Counts and reports assertions.

    Deliberately not unittest: this has to run as a bare script inside the
    container, and the output has to be readable in a docker exec log.
    """

    def __init__(self):
        self.passed = 0
        self.failures = []

    def check(self, label, got, want, tol=None):
        """Assert got == want, or |got-want| within a relative tolerance."""
        if tol is None:
            ok = (got == want)
        else:
            try:
                ok = abs(got - want) <= tol * abs(want)
            except TypeError:
                ok = False
        if ok:
            self.passed += 1
        else:
            self.failures.append((label, got, want))
        return ok

    def raises(self, label, exc_type, fn, *args, **kwargs):
        """Assert that calling fn raises exc_type."""
        try:
            got = fn(*args, **kwargs)
        except exc_type:
            self.passed += 1
            return True
        except Exception as err:
            self.failures.append(
                (label, "raised %s: %s" % (type(err).__name__, err),
                 "raise %s" % exc_type.__name__))
            return False
        self.failures.append(
            (label, "returned %r" % (got,), "raise %s" % exc_type.__name__))
        return False

    def report(self, title):
        total = self.passed + len(self.failures)
        print("")
        print("%s: %d/%d passed" % (title, self.passed, total))
        for label, got, want in self.failures:
            print("  FAIL %s" % label)
            print("       got  %r" % (got,))
            print("       want %r" % (want,))
        return 0 if not self.failures else 1
