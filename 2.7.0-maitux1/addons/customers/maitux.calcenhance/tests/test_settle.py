# -*- coding: utf-8 -*-
"""Tests for the settle loop (cross-analysis propagation) in patches.py.

Run inside the container (Python 2.7):

    MSYS_NO_PATHCONV=1 docker cp tests/ maituxlimslatest:/tmp/ce_tests/
    MSYS_NO_PATHCONV=1 docker exec maituxlimslatest python /tmp/ce_tests/test_settle.py

The fixture is the shape of the defect found on lims-dev / AA260914015
(Docs/保存性能及重新计算/证据-代码路径与实测.md §12): a source SRC, a
middle analysis MID that reads SRC, and a downstream DST that reads BOTH --
with DST ahead of MID in the sample's analysis list.  The old depth-first
walk evaluated DST from the new SRC and the old MID, then MID, and never
came back to DST.
"""

from __future__ import print_function

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import (  # noqa: E402
    Results, build_sample, evaluate, install_engine_stubs, load_patches)


def specs(src_value):
    key = json.dumps([u"x"])
    return [
        {"as_id": "SRC", "service_kw": "src_as",
         "fields": [
             {"keyword": "name", "result_type": "list", "value": key,
              "cross_referenceable": True},
             {"keyword": "v", "result_type": "list",
              "value": json.dumps([src_value]), "cross_referenceable": True},
         ]},
        # DST before MID on purpose -- see the module docstring.
        {"as_id": "DST", "service_kw": "dst_as",
         "fields": [
             {"keyword": "key", "result_type": "list", "value": key},
             {"keyword": "d", "result_type": "calculatedlist",
              "formula": u'LOOKUP("src_as","v","name",[key])'
                         u' + LOOKUP("mid_as","m","name",[key])'},
         ]},
        {"as_id": "MID", "service_kw": "mid_as",
         "fields": [
             {"keyword": "name", "result_type": "list", "value": key,
              "cross_referenceable": True},
             {"keyword": "key", "result_type": "list", "value": key},
             {"keyword": "m", "result_type": "calculatedlist",
              "cross_referenceable": True,
              "formula": u'LOOKUP("src_as","v","name",[key]) * 10'},
         ]},
    ]


ORDER = ("SRC", "DST", "MID")


def values(analyses):
    out = {}
    for as_id, analysis in analyses.items():
        for interim in analysis.getInterimFields():
            out["%s.%s" % (as_id, interim["keyword"])] = interim.get("value")
    return out


def settled_sample(p):
    """A sample already at its fixed point for v = 1."""
    _, analyses = build_sample(specs(u"1"))
    evaluate(p, analyses, ORDER, passes=4)
    return analyses


def write_v(p, analysis, value):
    """What a real write does, minus the patched setter: store, no eval."""
    before = p._published_map(analysis)
    interims = [dict(i) for i in analysis.getInterimFields()]
    for interim in interims:
        if interim["keyword"] == "v":
            interim["value"] = json.dumps([value])
    analysis.setInterimFields(interims)
    return before


def oracle(p, value):
    """Fixed point by definition: rebuild with the new input, sweep a lot."""
    _, analyses = build_sample(specs(value))
    evaluate(p, analyses, ORDER, passes=6)
    return values(analyses)


def _num(raw):
    try:
        return json.loads(raw)
    except Exception:
        return raw


def test_fixture_is_order_sensitive(p, r):
    """Validity gate: one walk in tree order must NOT reach the fixed point.

    If it did, the fixture would not exercise the defect, and the settle
    tests below would prove nothing.
    """
    analyses = settled_sample(p)
    write_v(p, analyses["SRC"], u"2")
    for as_id in ORDER:
        p._evaluate_interims_ordered(analyses[as_id])
    got = values(analyses)
    want = oracle(p, u"2")
    r.check("fixture: fixed point is DST.d = 2 + 20",
            _num(want["DST.d"]), [22.0])
    r.check("fixture: a single ordered walk leaves DST stale",
            got["DST.d"] != want["DST.d"], True)


def test_settle_reaches_fixed_point(p, r):
    analyses = settled_sample(p)
    before = write_v(p, analyses["SRC"], u"2")
    changed = p._settle([(analyses["SRC"], before)])
    got = values(analyses)
    want = oracle(p, u"2")
    r.check("settle: every value equals the fixed point", got, want)
    r.check("settle: reports MID and DST as changed, once each",
            sorted(a.id for a in changed), ["DST", "MID"])


def test_settle_twice_in_a_row(p, r):
    """Two writes, one settle each (= the per-field path): still the fixed point."""
    analyses = settled_sample(p)
    before = write_v(p, analyses["SRC"], u"5")
    p._settle([(analyses["SRC"], before)])
    before = write_v(p, analyses["SRC"], u"3")
    p._settle([(analyses["SRC"], before)])
    r.check("per-field: equals the fixed point of the last input",
            values(analyses), oracle(p, u"3"))


def test_no_change_no_work(p, r):
    """An evaluation that publishes nothing new queues nothing."""
    analyses = settled_sample(p)
    counts = dict((k, a.write_count) for k, a in analyses.items())
    before = p._published_map(analyses["SRC"])
    changed = p._settle([(analyses["SRC"], before)])
    r.check("unchanged source: nothing reported", changed, [])
    r.check("unchanged source: nothing written",
            dict((k, a.write_count) for k, a in analyses.items()), counts)


def test_not_editable_is_left_alone(p, r):
    analyses = settled_sample(p)
    frozen_before = values(analyses)["DST.d"]
    original = p._result_editable
    p._result_editable = lambda analysis: analysis.id != "DST"
    try:
        before = write_v(p, analyses["SRC"], u"2")
        changed = p._settle([(analyses["SRC"], before)])
    finally:
        p._result_editable = original
    got = values(analyses)
    r.check("frozen DST keeps its value", got["DST.d"], frozen_before)
    r.check("editable MID still follows",
            got["MID.m"], oracle(p, u"2")["MID.m"])
    r.check("only MID reported", [a.id for a in changed], ["MID"])
    r.check("skip is logged",
            any("no longer editable" in line and "DST" in line
                for line in LOGGER.lines), True)


def test_cycle_is_bounded(p, r):
    """A reads B reads A, never agreeing: the loop stops and says so."""
    key = json.dumps([u"x"])
    _, analyses = build_sample([
        {"as_id": "A", "service_kw": "a_as", "fields": [
            {"keyword": "name", "result_type": "list", "value": key,
             "cross_referenceable": True},
            {"keyword": "key", "result_type": "list", "value": key},
            {"keyword": "x", "result_type": "calculatedlist",
             "cross_referenceable": True, "value": json.dumps([1.0]),
             "formula": u'LOOKUP("b_as","y","name",[key]) + 1'},
        ]},
        {"as_id": "B", "service_kw": "b_as", "fields": [
            {"keyword": "name", "result_type": "list", "value": key,
             "cross_referenceable": True},
            {"keyword": "key", "result_type": "list", "value": key},
            {"keyword": "y", "result_type": "calculatedlist",
             "cross_referenceable": True, "value": json.dumps([1.0]),
             "formula": u'LOOKUP("a_as","x","name",[key]) + 1'},
        ]},
    ])
    del LOGGER.lines[:]
    p._settle([(analyses["A"], None)])
    r.check("cycle: terminates and warns",
            any("did not settle" in line for line in LOGGER.lines), True)
    r.check("cycle: bounded work",
            analyses["A"].write_count <= p._MAX_SETTLE_VISITS + 1, True)


def test_save_batch_settles_once(p, r):
    """_apply_save_queue: writes only store, one settle at the end."""
    analyses = settled_sample(p)
    by_uid = dict((a.UID(), a) for a in analyses.values())
    api = sys.modules["bika.lims.api"]
    api.get_object_by_uid = lambda uid: by_uid[uid]
    seen = []

    def set_field(obj, name, value):
        batch = p._save_batch()
        seen.append(batch is not None)
        before = p._published_map(obj)
        interims = [dict(i) for i in obj.getInterimFields()]
        for interim in interims:
            if interim["keyword"] == name:
                interim["value"] = value
        obj.setInterimFields(interims)
        # the patched setInterimFields does exactly this inside a batch
        batch.note(obj, before)
        return [obj]

    writes_before = dict((k, a.write_count) for k, a in analyses.items())
    updated = p._apply_save_queue(
        set_field, {"SRC": {"v": json.dumps([u"7"])}})
    r.check("batch: window open during the writes", seen, [True])
    r.check("batch: window closed afterwards", p._save_batch(), None)
    r.check("batch: fixed point", values(analyses), oracle(p, u"7"))
    r.check("batch: seed and both readers reported",
            sorted(o.id for o in updated), ["DST", "MID", "SRC"])
    r.check("batch: DST written once per settle visit, not per field",
            analyses["DST"].write_count - writes_before["DST"] <= 2, True)


def test_index_wiring(p, r):
    """_TreeIndex reads the same predicates the old scan did."""
    code = p._TreeIndex.__init__.__code__
    for name in ("_extract_lookup_sources", "_lookup_has_dynamic_source",
                 "_ORDER_TOKEN_RE"):
        r.check("index uses %s" % name, name in code.co_names, True)
    for name in ("_propagate_lookup_recalc", "_dependent_sibling_analyses",
                 "_finish_propagation"):
        r.check("old walk %s is gone" % name, hasattr(p, name), False)


def test_setter_markers(p, r):
    """The two contracts between the setters, pinned in the source."""
    src = open(p.__source_path__, "rb").read().decode("utf-8")
    r.check("setInterimFields marks itself as settling",
            u"patched_setInterimFields._maitux_settles = True" in src, True)
    r.check("setInterimValue asks for the marker",
            u'getattr(self.setInterimFields, "_maitux_settles", False)' in src,
            True)
    r.check("calculateResult defers inside a save",
            u"batch.holds(self)" in src, True)


LOGGER = None


def main():
    global LOGGER
    p = load_patches()
    LOGGER = install_engine_stubs()
    # harness stubs ObjectEditedEvent as `object`, which cannot take an arg
    p._ATObjectEditedEvent = lambda obj: obj
    print("IMPORT OK  (no Zope instance started)")
    print("  source under test: %s" % p.__source_path__)

    r = Results()
    test_fixture_is_order_sensitive(p, r)
    test_settle_reaches_fixed_point(p, r)
    test_settle_twice_in_a_row(p, r)
    test_no_change_no_work(p, r)
    test_not_editable_is_left_alone(p, r)
    test_cycle_is_bounded(p, r)
    test_save_batch_settles_once(p, r)
    test_index_wiring(p, r)
    test_setter_markers(p, r)
    return r.report("settle loop")


if __name__ == "__main__":
    sys.exit(main())
