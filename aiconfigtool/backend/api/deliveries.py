"""交付管理 handler：扫描 output/projects/。"""

from __future__ import annotations

import json
import os
import shutil

from shared import errors
from shared.result import Result


def _output_dir():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(os.path.dirname(root), "output", "projects")


def list_deliveries(query, **_):
    base = _output_dir()
    results: list[dict] = []
    if not os.path.isdir(base):
        return Result.success(results)

    # 加载公司名映射
    from infrastructure.config_repository import ConfigRepository
    repos = ConfigRepository()
    companies = {c["code"]: c.get("name", c["code"]) for c in repos.list_companies()}

    for name in os.listdir(base):
        proj = os.path.join(base, name)
        if not os.path.isdir(proj):
            continue
        manifest_path = os.path.join(proj, "evidence", "manifest.json")
        zip_path = os.path.join(proj, name + ".zip")
        if os.path.isfile(manifest_path):
            with open(manifest_path, encoding="utf-8") as h:
                m = json.load(h)
            cc = m.get("companyCode", "")
            zip_size = os.path.getsize(zip_path) if os.path.isfile(zip_path) else 0
            results.append({
                "id": name,
                "addonName": m.get("addon", name),
                "version": m.get("version", ""),
                "companyCode": cc,
                "companyName": companies.get(cc, cc),
                "siteCode": m.get("siteCode", ""),
                "fileCount": m.get("fileCount", 0),
                "packageSizeKb": max(1, zip_size // 1024),
                "generatedAt": m.get("generatedAt", ""),
                "status": "packaged" if os.path.isfile(zip_path) else "validated",
            })
    results.sort(key=lambda r: r.get("generatedAt", ""), reverse=True)
    return Result.success(results)


def delete_delivery(params, **_):
    pid = params["id"]
    proj = os.path.join(_output_dir(), pid)
    if not os.path.isdir(proj):
        return Result.failure("交付记录不存在: %s" % pid, code=errors.NOT_FOUND)
    shutil.rmtree(proj)
    return Result.success(None)


def register(router) -> None:
    router.get("/api/deliveries", list_deliveries)
    router.delete("/api/deliveries/{id}", delete_delivery)
