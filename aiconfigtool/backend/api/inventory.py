"""Inventory 摸底文件 handler。"""

from __future__ import annotations

from infrastructure.config_repository import ConfigRepository
from services.inventory_service import InventoryService
from services.diff_service import DiffService
from shared import errors
from shared.result import Result

_repo = ConfigRepository()
_service = InventoryService(_repo)
_diff = DiffService(_repo)


def list_inventories(query, **_):
    site_code = query.get("siteCode")
    return Result.success(_repo.list_inventories(site_code))


def run_inventory(body, **_):
    body = body or {}
    site_code = body.get("siteCode")
    if not site_code:
        return Result.failure("缺少 siteCode", code=errors.VALIDATION_ERROR)
    return _service.scan_site(site_code)


def diff_inventory(body, **_):
    """对比两个摸底文件。body: { siteA, invA, siteB, invB }"""
    body = body or {}
    for k in ("siteA", "invA", "siteB", "invB"):
        if not body.get(k):
            return Result.failure("缺少 %s" % k, code=errors.VALIDATION_ERROR)
    if body["siteA"] == body["siteB"] and body["invA"] == body["invB"]:
        return Result.failure("不能对比同一个摸底文件", code=errors.VALIDATION_ERROR)
    result = _diff.diff(body["siteA"], body["invA"], body["siteB"], body["invB"])
    if "error" in result:
        return Result.failure(result["error"], code=errors.NOT_FOUND)
    return Result.success(result)


def register(router) -> None:
    router.get("/api/inventories", list_inventories)
    router.post("/api/inventory/run", run_inventory)
    router.post("/api/inventory/diff", diff_inventory)
