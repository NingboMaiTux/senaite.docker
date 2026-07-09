"""Inventory 服务：对站点发起运行时摸底，落盘为快照。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from urllib.parse import urlsplit

from infrastructure.config_repository import ConfigRepository
from infrastructure.inventory_runner import InventoryRunner
from shared import errors
from shared.result import Result


def _split_url(url: str) -> tuple[str, str]:
    """http://host:port/senaite → (http://host:port, senaite)。"""
    parts = urlsplit(url)
    base = "%s://%s" % (parts.scheme, parts.netloc)
    site_id = parts.path.strip("/").split("/")[-1] if parts.path.strip("/") else ""
    return base, site_id


class InventoryService:
    def __init__(self, repo: Optional[ConfigRepository] = None) -> None:
        self._repo = repo or ConfigRepository()

    def scan_site(self, site_code: str) -> Result:
        from infrastructure.log_writer import get_log_writer
        log = get_log_writer()

        site = self._repo.get_site(site_code)
        if site is None:
            log.warn("pipeline", "摸底失败：站点不存在", site_code=site_code)
            return Result.failure(
                "站点不存在: %s" % site_code,
                code=errors.NOT_FOUND,
            )

        # 连接信息：优先 connection 字段，否则从 url 推断
        conn = site.get("connection") or {}
        if conn.get("baseUrl") and conn.get("senaiteSiteId"):
            base_url, site_id = conn["baseUrl"], conn["senaiteSiteId"]
        else:
            base_url, site_id = _split_url(site.get("url", ""))
        if not base_url or not site_id:
            return Result.failure(
                "站点缺少可用的连接信息（url/connection）",
                code=errors.SITE_CONNECTION_FAILED,
                suggestion="补全站点的 url 或 connection.baseUrl/senaiteSiteId",
            )

        runner = InventoryRunner(
            base_url,
            site_id,
            username=conn.get("authUser", "admin"),
            password=conn.get("authPassword", "admin"),
        )
        try:
            raw = runner.fetch_runtime()
        except Exception as exc:  # noqa: BLE001
            return Result.failure(
                "摸底失败：无法连接站点或端点未安装 - %s" % exc,
                code=errors.SITE_CONNECTION_FAILED,
                suggestion="确认站点在线、@@maitux-runtime-inventory 已安装、认证正确",
            )

        summary = InventoryRunner.summarize(raw)
        company = self._repo.get_company(site.get("companyCode", "")) or {}

        now = datetime.now()
        snapshot = {
            "id": "inv_" + now.strftime("%Y%m%d_%H%M%S"),
            "companyCode": site.get("companyCode", ""),
            "companyName": company.get("name", ""),
            "siteCode": site_code,
            "siteName": site.get("name", ""),
            "siteUrl": site.get("url", ""),
            "createdAt": now.strftime("%Y-%m-%d %H:%M"),
            "senaiteVersion": (raw.get("meta") or {}).get(
                "senaite_version", site.get("senaiteVersion", "")
            ),
            "entityCount": summary["typeCount"],
            "addonCount": len((raw.get("meta") or {}).get("addons", []) or []),
            "staleness": "fresh",
            "summary": summary,  # 供 Gate1 冲突校验
        }
        self._repo.save_inventory(site_code, snapshot)

        # 回写站点：更新 lastInventoryAt + 真实版本
        site["lastInventoryAt"] = snapshot["createdAt"]
        site["senaiteVersion"] = snapshot["senaiteVersion"]
        self._repo.save_site(site_code, site)

        # 返回不含 summary 的元信息（列表/前端用）
        return Result.success(
            {k: v for k, v in snapshot.items() if k != "summary"}
        )
