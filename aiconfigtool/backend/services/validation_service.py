"""Gate1 冲突校验：change_spec vs 摸底能力。

回答用户最初的核心诉求——「需求和能力没有冲突才生成」。
校验点（针对 AddField）：
  1. 目标类型是否存在于摸底快照
  2. 要新增的字段名是否已存在（冲突）
  3. 字段类型是否在支持白名单内
  4. 字段名命名空间前缀（软提示，不阻断）
  5. 目标类型的框架（dexterity/archetypes/unknown）——决定后续生成路径
"""

from __future__ import annotations

from typing import Optional

from infrastructure.config_repository import ConfigRepository
from infrastructure.inventory_runner import InventoryRunner
from shared import errors
from shared.result import Result

# 支持的字段类型白名单（change_spec 里的 fieldType）
# 规范化：同时接受 Dexterity schema 名与 Archetypes Field 名
SUPPORTED_FIELD_TYPES = {
    "StringField",
    "TextField",
    "IntegerField",
    "FloatField",
    "BooleanField",
    "TextLine",
    "Text",
    "Int",
    "Float",
    "Bool",
}

# 命名空间前缀软提示（与设计一致：已从阻断放宽为警告）
NAMESPACE_PREFIXES = ("maitux", "maitux_")


class ValidationService:
    def __init__(self, repo: Optional[ConfigRepository] = None) -> None:
        self._repo = repo or ConfigRepository()

    def conflict_check(
        self, site_code: str, inventory_ref: str, changes: list[dict]
    ) -> Result:
        """对每个 change 逐项比对摸底能力，返回 ConflictCheckItem[] + 总体是否通过。"""
        snapshot = self._repo.get_inventory(site_code, inventory_ref)
        if snapshot is None:
            return Result.failure(
                "摸底文件不存在: %s / %s" % (site_code, inventory_ref),
                code=errors.NOT_FOUND,
                suggestion="请先对该站点发起摸底",
            )
        summary = snapshot.get("summary") or {}
        types = summary.get("types") or {}

        results: list[dict] = []
        for change in changes or []:
            results.append(self._check_one(change, types))

        passed = all(r["status"] == "ok" for r in results)
        return Result.success(
            {
                "checks": results,
                "passed": passed,
                "inventoryRef": inventory_ref,
                "siteCode": site_code,
            }
        )

    def _check_one(self, change: dict, types: dict) -> dict:
        change_type = change.get("changeType", "")
        type_id = change.get("typeId", "")
        field_name = change.get("fieldName", "")
        field_type = change.get("fieldType", "")
        target = "%s.%s" % (type_id, field_name) if field_name else type_id

        def conflict(msg: str) -> dict:
            return {
                "changeType": change_type,
                "target": target,
                "status": "conflict",
                "message": msg,
            }

        def ok(msg: str, framework: str = "") -> dict:
            item = {
                "changeType": change_type,
                "target": target,
                "status": "ok",
                "message": msg,
            }
            if framework:
                item["framework"] = framework
            return item

        # 目前 P0 只做 AddField；其他类型放行（后续补）
        if change_type != "AddField":
            return ok("暂未对该变更类型做冲突校验（P0 聚焦 AddField）")

        # 1. 类型存在？
        entity = types.get(type_id)
        if entity is None:
            return conflict(
                "目标类型 %s 不存在于摸底快照（共 %d 个类型）"
                % (type_id, len(types))
            )

        # 2. 字段冲突？
        existing = {f.get("name") for f in entity.get("fields") or []}
        if field_name in existing:
            return conflict(
                "字段 %s 已存在于 %s，无法重复新增" % (field_name, type_id)
            )

        # 3. 字段类型白名单
        if field_type and field_type not in SUPPORTED_FIELD_TYPES:
            return conflict(
                "字段类型 %s 暂不支持（支持：%s）"
                % (field_type, ", ".join(sorted(SUPPORTED_FIELD_TYPES)))
            )

        # 4. 命名空间前缀（软提示）
        prefix_note = ""
        if field_name and not field_name.startswith(NAMESPACE_PREFIXES):
            prefix_note = "；建议字段名加 maitux_ 前缀以符合命名规范"

        # 5. 框架
        framework = entity.get("framework", "unknown")
        return ok(
            "目标类型 %s（%s）存在，无同名字段，可安全新增%s"
            % (type_id, framework, prefix_note),
            framework=framework,
        )
