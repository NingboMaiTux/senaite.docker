"""摸底文件差异对比服务：两份快照 → 类型/字段级差异报告。"""

from __future__ import annotations

from infrastructure.config_repository import ConfigRepository


class DiffService:
    def __init__(self, repo=None):
        self._repo = repo or ConfigRepository()

    def diff(
        self, site_a: str, inv_a: str, site_b: str, inv_b: str
    ) -> dict:
        snap_a = self._repo.get_inventory(site_a, inv_a)
        snap_b = self._repo.get_inventory(site_b, inv_b)
        if not snap_a: return {"error": "摸底文件 A 不存在"}
        if not snap_b: return {"error": "摸底文件 B 不存在"}

        types_a = (snap_a.get("summary") or {}).get("types") or {}
        types_b = (snap_b.get("summary") or {}).get("types") or {}

        all_types = sorted(set(types_a) | set(types_b))

        type_diffs = []
        for tid in all_types:
            ta = types_a.get(tid)
            tb = types_b.get(tid)
            if ta is None:
                type_diffs.append({"typeId": tid, "change": "removed", "title": tb.get("title", "") if tb else ""})
                continue
            if tb is None:
                type_diffs.append({"typeId": tid, "change": "added", "title": ta.get("title", "")})
                continue

            fields_a = {f["name"] for f in (ta.get("fields") or []) if f.get("name")}
            fields_b = {f["name"] for f in (tb.get("fields") or []) if f.get("name")}
            added = sorted(fields_a - fields_b)
            removed = sorted(fields_b - fields_a)

            fw_a = ta.get("framework")
            fw_b = tb.get("framework")
            fw_changed = fw_a != fw_b

            if added or removed or fw_changed:
                type_diffs.append({
                    "typeId": tid,
                    "change": "modified",
                    "title": ta.get("title", ""),
                    "addedFields": added,
                    "removedFields": removed,
                    "frameworkA": fw_a,
                    "frameworkB": fw_b,
                })

        return {
            "base": {"site": site_a, "inventory": inv_a, "createdAt": snap_a.get("createdAt", "")},
            "target": {"site": site_b, "inventory": inv_b, "createdAt": snap_b.get("createdAt", "")},
            "typeCountA": len(types_a),
            "typeCountB": len(types_b),
            "typeDiffs": type_diffs,
        }
