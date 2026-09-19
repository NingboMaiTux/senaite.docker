# -*- coding: utf-8 -*-
"""Worksheet calculation refresh and interim export views.

Feature B (refresh_calculation): re-link analyses to the current Calculation,
preserving entered interim values (SPEC: scope 功能 B).

Feature C (export_interims): dump interim values as CSV (single AS via
?keyword=) or ZIP (all AS, no keyword), for native /import round-trip or
archival (SPEC: scope 功能 C).

CSV 一律写 **UTF-8 with BOM**；理由见 _UTF8_BOM 上方的注释。
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


# Excel（中文 Windows）打开无 BOM 的 UTF-8 CSV 会按 GBK 猜，中文全花；
# 带 BOM 它才认得出 UTF-8，而且另存时保持 UTF-8。这三个字节就是
# 「导出 -> Excel 填写 -> 导回」这条回路不掉编码的全部条件。
#
# 导入侧安全：BOM 落在表头第一格 sample_id 上，而 two_dimension.py 的
# parse_headerline 只取 splitted[1:]，那一列本来就被丢弃（已实测）。
_UTF8_BOM = b"\xef\xbb\xbf"


def _utf8(value):
    """Coerce a cell value to a UTF-8 byte string for CSV output.

    取代原来的 _ascii（`encode("ascii", "replace")`）。那一版把每个
    中文字符换成一个 `?` 然后照常导出，**没有任何提示**：
    文件看着是完整的，中文列全是问号，再导回去就把好数据
    覆盖成问号。interim 的字符串值由 RecordsField 存成 unicode
    （senaite/core/browser/fields/records.py 的 _decode_strings），
    所以这条路径是所有中文值的必经之地。
    """
    if value is None:
        return ""
    if isinstance(value, unicode):
        return value.encode("utf-8")
    if isinstance(value, bytes):
        return value
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

        all_analyses = self.context.getAnalyses()
        keyword = _to_str(keyword)
        targets = [a for a in all_analyses
                   if _to_str(a.getKeyword()) == keyword]

        refreshed = []
        rejected = []
        skipped = []
        refreshed_objs = []

        for analysis in targets:
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
                refreshed_objs.append(analysis)
            else:
                skipped.append({
                    "keyword": _to_str(analysis.getKeyword()),
                    "reason": outcome,
                })

        if refreshed_objs:
            self._recalculate_dependents(refreshed_objs, all_analyses)

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

    def _recalculate_dependents(self, refreshed_analyses, all_analyses):
        """Recalculate downstream analyses in the same sample that depend on
        the refreshed services (mirrors importer.calculateTotalResults).

        The previous version recursed once per dependency level and re-ran
        getAnalyses() / getCalculation() / getDependentServices() on every
        level -- O(N * depth) ZODB object wake-ups.  This version builds the
        sample / service / dependency index in one flat pass, then walks the
        dependents with a queue, so each analysis is woken once and each
        dependency edge is followed once.
        """
        by_uid = {}
        sample_of = {}
        service_uid_of = {}
        # service uid -> uids of the analyses that depend on that service
        dependents = {}

        for a in all_analyses:
            uid = a.UID()
            by_uid[uid] = a
            sample_of[uid] = a.getRequestUID()
            service = a.getAnalysisService()
            service_uid_of[uid] = api.get_uid(service) if service else None
            calc = a.getCalculation()
            if not calc:
                continue
            for dep_service in calc.getDependentServices():
                dep_uid = api.get_uid(dep_service)
                if dep_uid:
                    dependents.setdefault(dep_uid, []).append(uid)

        queue = [a.UID() for a in refreshed_analyses]
        done = set(queue)
        while queue:
            uid = queue.pop(0)
            suid = service_uid_of[uid]
            if not suid:
                continue
            sample_uid = sample_of[uid]
            for other_uid in dependents.get(suid, []):
                if other_uid in done:
                    continue
                if sample_of[other_uid] != sample_uid:
                    continue
                done.add(other_uid)
                other = by_uid[other_uid]
                other.calculateResult(override=True)
                other.reindexObject(idxs=["Result"])
                queue.append(other_uid)


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
        buf.write(_UTF8_BOM)
        writer = csv.writer(buf)
        writer.writerow([_utf8(c) for c in header])
        for a in analyses:
            imap = self._interim_map(a)
            row = [_utf8(a.getRequestID())]
            for kw in keywords:
                row.append(_utf8(imap.get(kw, "")))
            writer.writerow(row)

        # manifest: first cell "end" makes the parser skip the line
        # (two_dimension.py splitline), kept last so it is never a header
        writer.writerow(
            ["end", _utf8(self._manifest_cell(analyses, keyword))])
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
