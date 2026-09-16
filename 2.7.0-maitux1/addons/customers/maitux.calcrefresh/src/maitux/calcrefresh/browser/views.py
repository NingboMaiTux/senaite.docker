# -*- coding: utf-8 -*-
"""Worksheet calculation refresh and interim export views.

Feature B (refresh_calculation): re-link analyses to the current Calculation,
preserving entered interim values (SPEC: scope 功能 B).

Feature C (export_interims): dump interim values as CSV (single AS via
?keyword=) or ZIP (all AS, no keyword), for native /import round-trip or
archival (SPEC: scope 功能 C).
"""

import csv
import datetime
import io
import json
import zipfile

from bika.lims import api
from Products.Five.browser import BrowserView

CALCULATED_TYPES = ("calculated", "calculatedlist")


def _to_str(value):
    """Normalize a value to a byte ``str`` (Py2 unicode boundary)."""
    if isinstance(value, unicode):
        return value.encode("utf-8")
    return value


def _ascii(value):
    """Coerce a cell value to an ASCII byte string for CSV output."""
    if value is None:
        return ""
    if isinstance(value, unicode):
        return value.encode("ascii", "replace")
    return str(value)


class RefreshCalculationView(BrowserView):
    """In-place calculation snapshot refresh, preserving entered interims."""

    ALLOWED_STATES = ("unassigned", "assigned")

    def __call__(self):
        keyword = (self.request.form.get("keyword") or "").strip()
        if not keyword:
            # 止血：空 keyword = 整表刷新，会把实例 CPU 打满（WS-009 实测 100%）。
            # 强制要求 ?keyword=<AS keyword>，只刷新单个 AS。
            self.request.response.setStatus(400)
            self.request.response.setHeader("Content-Type", "application/json")
            return json.dumps({
                "error": "keyword_required",
                "message": "keyword is required to refresh a single AS; "
                           "whole-worksheet refresh is disabled",
            })

        analyses = self.context.getAnalyses()
        keyword = _to_str(keyword)
        analyses = [a for a in analyses
                    if _to_str(a.getKeyword()) == keyword]

        refreshed = []
        rejected = []
        skipped = []
        seen = set()

        for analysis in analyses:
            state = api.get_review_status(analysis)
            if state not in self.ALLOWED_STATES:
                rejected.append({
                    "keyword": _to_str(analysis.getKeyword()),
                    "state": state,
                })
                continue

            outcome = self._refresh_one(analysis)
            if outcome == "refreshed":
                refreshed.append(_to_str(analysis.getKeyword()))
                self._recalculate_dependents(analysis, seen)
            else:
                skipped.append({
                    "keyword": _to_str(analysis.getKeyword()),
                    "reason": outcome,
                })

        self.request.response.setHeader("Content-Type", "application/json")
        return json.dumps({
            "refreshed": refreshed,
            "rejected": rejected,
            "skipped": skipped,
        })

    def _refresh_one(self, analysis):
        service = analysis.getAnalysisService()
        calc = service.getCalculation() if service else None
        if not calc:
            return "no_calculation"

        # 1. read old interim values (keyword -> value)
        old_vals = {}
        for item in analysis.getInterimFields():
            kw = item.get("keyword")
            if kw:
                old_vals[kw] = item.get("value", "")

        # 2. re-link to the latest Calculation (stamps snapshot + merges
        #    calc interims, overwriting values with template defaults)
        analysis.setCalculation(calc)

        # 3. write back the old values per keyword; locked fields are
        #    preserved by maitux.calcenhance's _preserve_locked_interims,
        #    renamed keywords simply no longer match and drop their value
        for kw, val in old_vals.items():
            analysis.setInterimValue(kw, val)

        # 4. recalculate with the fresh snapshot
        analysis.calculateResult(override=True)
        analysis.reindexObject()
        return "refreshed"

    def _recalculate_dependents(self, analysis, seen):
        """Recalculate downstream analyses in the same sample that depend on
        this analysis's service (mirrors importer.calculateTotalResults)."""
        service = analysis.getAnalysisService()
        if not service:
            return
        sample_uid = analysis.getRequestUID()
        for other in self.context.getAnalyses():
            if other.UID() == analysis.UID():
                continue
            if other.getRequestUID() != sample_uid:
                continue
            calc = other.getCalculation()
            if not calc:
                continue
            if service not in calc.getDependentServices():
                continue
            if other.UID() in seen:
                continue
            seen.add(other.UID())
            other.calculateResult(override=True)
            other.reindexObject(idxs=["Result"])
            self._recalculate_dependents(other, seen)


class ExportInterimsView(BrowserView):
    """Export interim values as CSV (single AS) or ZIP (all AS)."""

    def __call__(self):
        keyword = (self.request.form.get("keyword") or "").strip()
        if keyword:
            return self._export_single(_to_str(keyword))
        return self._export_zip()

    def _analyses_for(self, keyword):
        analyses = self.context.getAnalyses()
        if not keyword:
            return analyses
        return [a for a in analyses
                if _to_str(a.getKeyword()) == keyword]

    def _interim_map(self, analysis):
        m = {}
        for item in analysis.getInterimFields():
            kw = item.get("keyword")
            if kw:
                m[kw] = item.get("value", "")
        return m

    def _interim_keywords(self, analyses):
        """Ordered union of interim keywords across analyses, skipping
        calculated / calculatedlist."""
        keywords = []
        seen = set()
        for a in analyses:
            for item in a.getInterimFields():
                kw = item.get("keyword")
                if not kw or item.get("result_type") in CALCULATED_TYPES:
                    continue
                if kw in seen:
                    continue
                seen.add(kw)
                keywords.append(kw)
        return keywords

    def _build_csv(self, analyses, keyword):
        keywords = self._interim_keywords(analyses)
        header = ["sample_id"] + list(keywords)

        buf = io.BytesIO()
        writer = csv.writer(buf)
        writer.writerow([_ascii(c) for c in header])
        for a in analyses:
            imap = self._interim_map(a)
            row = [_ascii(a.getRequestID())]
            for kw in keywords:
                row.append(_ascii(imap.get(kw, "")))
            writer.writerow(row)

        # manifest: first cell "end" makes the parser skip the line
        # (two_dimension.py splitline), kept last so it is never a header
        writer.writerow(["end", self._manifest_cell(analyses, keyword)])
        return buf.getvalue()

    def _manifest_cell(self, analyses, keyword):
        version = 0
        if analyses:
            service = analyses[0].getAnalysisService()
            calc = service.getCalculation() if service else None
            if calc:
                version = api.get_version(calc) or 0
        site = api.get_portal().getId()
        date = datetime.date.today().isoformat()
        return "# calc={} version={} exported={} site={}".format(
            keyword, version, date, site)

    def _export_single(self, keyword):
        analyses = self._analyses_for(keyword)
        filename = "{}_{}.csv".format(self.context.getId(), keyword)
        content = self._build_csv(analyses, keyword)

        response = self.request.response
        response.setHeader("Content-Type", "text/csv; charset=utf-8")
        response.setHeader(
            "Content-Disposition",
            "attachment; filename=\"{}\"".format(filename))
        return content

    def _export_zip(self):
        groups = {}
        for a in self.context.getAnalyses():
            kw = _to_str(a.getKeyword())
            groups.setdefault(kw, []).append(a)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for kw, items in sorted(groups.items()):
                filename = "{}_{}.csv".format(self.context.getId(), kw)
                zf.writestr(filename, self._build_csv(items, kw))

        filename = "{}_interims.zip".format(self.context.getId())
        response = self.request.response
        response.setHeader("Content-Type", "application/zip")
        response.setHeader(
            "Content-Disposition",
            "attachment; filename=\"{}\"".format(filename))
        return buf.getvalue()
