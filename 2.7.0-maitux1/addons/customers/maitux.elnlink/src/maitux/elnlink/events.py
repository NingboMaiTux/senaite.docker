# -*- coding: utf-8 -*-
"""Push an analysis to MaiELN after a workflow transition.

Only samples that came from MaiELN (ELNExperimentNo set) are pushed. The
ELN decides what to show: a verified analysis is an approved result, a
submitted one is "pending approval", anything else is in progress. The
push is best effort - it never raises into the LIMS transaction and the
ELN also pulls on demand, so a missed push only delays the display.
"""
import json
import socket
import urllib2

from bika.lims import api
from DateTime import DateTime

from maitux.elnlink import ELN_API_BASE
from maitux.elnlink import ELN_INTEGRATION_TOKEN
from maitux.elnlink import logger

PUSH_TRANSITIONS = ("submit", "verify", "retract", "reject", "multi_verify")
TIMEOUT_SECONDS = 5


def _text(value):
    if value is None:
        return ""
    if isinstance(value, unicode):
        return value
    try:
        return unicode(value)
    except Exception:
        return ""


def _interims(analysis):
    out = []
    try:
        for item in analysis.getInterimFields() or []:
            out.append({
                "keyword": _text(item.get("keyword")),
                "title": _text(item.get("title")),
                "value": _text(item.get("value")),
                "unit": _text(item.get("unit")),
            })
    except Exception:
        pass
    return out


def _results_range(analysis):
    try:
        rr = analysis.getResultsRange() or {}
        return {"min": _text(rr.get("min")), "max": _text(rr.get("max")),
                "warn_min": _text(rr.get("warn_min")), "warn_max": _text(rr.get("warn_max"))}
    except Exception:
        return {}


def _out_of_range(analysis):
    try:
        from bika.lims.utils.analysis import is_out_of_range
        oor, _oos = is_out_of_range(analysis)
        return bool(oor)
    except Exception:
        return False


def build_payload(analysis, transition):
    sample = analysis.getRequest()
    service = analysis.getAnalysisService()
    actor = api.get_current_user()
    return {
        "sample_id": api.get_id(sample),
        "sample_uid": api.get_uid(sample),
        "sample_url": api.get_url(sample),
        "eln_experiment_no": _text(sample.getField("ELNExperimentNo").get(sample)),
        "analysis_uid": api.get_uid(analysis),
        "analysis_url": api.get_url(analysis),
        "keyword": _text(analysis.getKeyword()),
        "title": _text(api.get_title(service or analysis)),
        "unit": _text(analysis.getUnit()),
        "result": _text(analysis.getResult()),
        "formatted_result": _text(analysis.getFormattedResult()) if hasattr(analysis, "getFormattedResult") else _text(analysis.getResult()),
        "interims": _interims(analysis),
        "results_range": _results_range(analysis),
        "out_of_range": _out_of_range(analysis),
        "review_state": _text(api.get_workflow_status_of(analysis)),
        "transition": _text(transition),
        "actor": _text(actor.getId() if actor else ""),
        "actor_name": _text(actor.getProperty("fullname", "") if actor else ""),
        "analyst": _text(analysis.getAnalyst()),
        "verifiers": [_text(v) for v in (analysis.getVerificators() or [])],
        "timestamp": DateTime().ISO8601(),
    }


# The ELN is a sibling container on the compose network. The LIMS image
# carries http_proxy / https_proxy for its package mirrors; urllib2 would
# route this internal call through that proxy (observed: an empty 502
# from the proxy), so the push opener is built with no proxies at all.
_OPENER = urllib2.build_opener(urllib2.ProxyHandler({}))


def push(payload):
    url = "%s/api/integration/eln/result" % ELN_API_BASE.rstrip("/")
    data = json.dumps(payload)
    req = urllib2.Request(url, data=data, headers={
        "Content-Type": "application/json",
        "X-Integration-Token": ELN_INTEGRATION_TOKEN,
    })
    try:
        resp = _OPENER.open(req, timeout=TIMEOUT_SECONDS)
        logger.info("elnlink: pushed %s/%s (%s) -> HTTP %s", payload.get("sample_id"), payload.get("keyword"), payload.get("transition"), resp.getcode())
        return True
    except urllib2.HTTPError as exc:
        logger.warn("elnlink: ELN answered HTTP %s for %s/%s", exc.code, payload.get("sample_id"), payload.get("keyword"))
    except (urllib2.URLError, socket.timeout, socket.error) as exc:
        logger.warn("elnlink: ELN unreachable (%s); %s/%s not pushed", exc, payload.get("sample_id"), payload.get("keyword"))
    except Exception as exc:  # never let the push break the LIMS transaction
        logger.warn("elnlink: push failed: %r", exc)
    return False


def on_analysis_transition(analysis, event):
    try:
        transition = getattr(event, "transition", None)
        transition_id = getattr(transition, "id", None)
        if transition_id not in PUSH_TRANSITIONS:
            return
        sample = analysis.getRequest()
        if sample is None:
            return
        field = sample.getField("ELNExperimentNo")
        if field is None or not field.get(sample):
            return
        push(build_payload(analysis, transition_id))
    except Exception as exc:
        logger.warn("elnlink: subscriber error: %r", exc)
