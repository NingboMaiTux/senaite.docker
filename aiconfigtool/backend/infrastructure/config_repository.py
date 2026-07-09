"""配置文件仓库：读写工作空间下的 JSON 配置（stdlib json，零依赖）。

对应技术设计文档 8.1 的目录结构：
    data/companies/{code}/company.json
    data/sites/{code}/config.json
    data/sites/{code}/inventories/{id}.json

JSON 键采用 camelCase，与前端 domain 类型直接对齐，省去转换层。
当前先实现读取（骨架期需要），写入随业务逐步补齐。
"""

from __future__ import annotations

import json
import os
from typing import Optional


def _default_workspace() -> str:
    """默认工作空间：优先环境变量，否则 backend/../data。"""
    env = os.environ.get("AICONFIG_WORKSPACE")
    if env:
        return env
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(backend_dir, "..", "data")


class ConfigRepository:
    def __init__(self, base_dir: Optional[str] = None) -> None:
        self._base = os.path.abspath(base_dir or _default_workspace())

    # ── 路径 ──
    def _companies_dir(self) -> str:
        return os.path.join(self._base, "companies")

    def _sites_dir(self) -> str:
        return os.path.join(self._base, "sites")

    # ── 通用 ──
    @staticmethod
    def _read_json(path: str) -> Optional[dict]:
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _list_subdirs(path: str) -> list[str]:
        if not os.path.isdir(path):
            return []
        return sorted(
            name
            for name in os.listdir(path)
            if os.path.isdir(os.path.join(path, name))
        )

    # ── 公司 ──
    def list_companies(self) -> list[dict]:
        out: list[dict] = []
        for code in self._list_subdirs(self._companies_dir()):
            data = self._read_json(
                os.path.join(self._companies_dir(), code, "company.json")
            )
            if data:
                out.append(data)
        return out

    def get_company(self, code: str) -> Optional[dict]:
        return self._read_json(
            os.path.join(self._companies_dir(), code, "company.json")
        )

    def save_company(self, code: str, data: dict) -> None:
        path = os.path.join(self._companies_dir(), code, "company.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as h:
            json.dump(data, h, ensure_ascii=False, indent=2)

    def delete_company(self, code: str) -> None:
        import shutil
        d = os.path.join(self._companies_dir(), code)
        if os.path.isdir(d):
            shutil.rmtree(d)

    # ── 站点 ──
    def list_all_sites(self) -> list[dict]:
        out: list[dict] = []
        for code in self._list_subdirs(self._sites_dir()):
            data = self._read_json(
                os.path.join(self._sites_dir(), code, "config.json")
            )
            if data:
                out.append(data)
        return out

    def list_sites(self, company_code: str) -> list[dict]:
        return [
            s for s in self.list_all_sites() if s.get("companyCode") == company_code
        ]

    def get_site(self, code: str) -> Optional[dict]:
        return self._read_json(
            os.path.join(self._sites_dir(), code, "config.json")
        )

    def save_site(self, code: str, site_data: dict) -> None:
        path = os.path.join(self._sites_dir(), code, "config.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as h:
            json.dump(site_data, h, ensure_ascii=False, indent=2)

    def delete_site(self, code: str) -> None:
        import shutil
        d = os.path.join(self._sites_dir(), code)
        if os.path.isdir(d):
            shutil.rmtree(d)

    # ── Inventory 摸底文件 ──
    def _inventories_dir(self, site_code: str) -> str:
        return os.path.join(self._sites_dir(), site_code, "inventories")

    def list_inventories(self, site_code: Optional[str] = None) -> list[dict]:
        codes = (
            [site_code] if site_code else self._list_subdirs(self._sites_dir())
        )
        out: list[dict] = []
        for code in codes:
            inv_dir = self._inventories_dir(code)
            if not os.path.isdir(inv_dir):
                continue
            for name in sorted(os.listdir(inv_dir)):
                if not name.endswith(".json"):
                    continue
                data = self._read_json(os.path.join(inv_dir, name))
                if data:
                    # 列表视图去掉体积大的 summary，只留元信息
                    out.append({k: v for k, v in data.items() if k != "summary"})
        return out

    def get_inventory(self, site_code: str, inventory_id: str) -> Optional[dict]:
        """含 summary 的完整摸底快照（Gate1 冲突校验用）。"""
        return self._read_json(
            os.path.join(self._inventories_dir(site_code), inventory_id + ".json")
        )

    def save_inventory(self, site_code: str, snapshot: dict) -> None:
        inv_dir = self._inventories_dir(site_code)
        os.makedirs(inv_dir, exist_ok=True)
        path = os.path.join(inv_dir, snapshot["id"] + ".json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, ensure_ascii=False, indent=2)

    def delete_inventory(self, site_code: str, inventory_id: str) -> bool:
        path = os.path.join(self._inventories_dir(site_code), inventory_id + ".json")
        if os.path.isfile(path):
            os.remove(path)
            return True
        return False
