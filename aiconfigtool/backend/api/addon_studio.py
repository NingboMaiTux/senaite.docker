"""Addon 工坊 handler：解析需求 / 冲突校验 / 生成 / 下载。"""

from __future__ import annotations

import os

from engines.ai.deterministic import DeterministicEngine
from engines.delivery.package_export import DeliveryEngine
from engines.generator.addon_generator import AddonGenerator
from infrastructure.config_repository import ConfigRepository
from services.validation_service import ValidationService
from shared import errors
from shared.result import Result

_repo = ConfigRepository()
_validation = ValidationService(_repo)
_deterministic = DeterministicEngine()
_delivery = DeliveryEngine()


def _load_summary(site_code, inventory_ref):
    snapshot = _repo.get_inventory(site_code, inventory_ref)
    if snapshot is None:
        return None, Result.failure(
            "摸底文件不存在: %s / %s" % (site_code, inventory_ref),
            code=errors.NOT_FOUND,
            suggestion="请先对该站点发起摸底",
        )
    return snapshot.get("summary") or {}, None


def parse_requirement(body, **_):
    """自然语言 → change_spec。body: { siteCode, inventoryRef, text }"""
    body = body or {}
    site_code = body.get("siteCode")
    inventory_ref = body.get("inventoryRef")
    text = body.get("text") or ""
    if not site_code or not inventory_ref:
        return Result.failure("缺少 siteCode 或 inventoryRef", code=errors.VALIDATION_ERROR)
    summary, err = _load_summary(site_code, inventory_ref)
    if err:
        return err
    return _deterministic.parse_to_change_spec(text, site_code, inventory_ref, summary)


def conflict_check(body, **_):
    """Gate1 冲突校验。body: { siteCode, inventoryRef, changes }"""
    body = body or {}
    site_code = body.get("siteCode")
    inventory_ref = body.get("inventoryRef")
    changes = body.get("changes") or []
    if not site_code or not inventory_ref:
        return Result.failure("缺少 siteCode 或 inventoryRef", code=errors.VALIDATION_ERROR)
    return _validation.conflict_check(site_code, inventory_ref, changes)


def generate(body, **_):
    """完整生成闭环：Gate1 冲突校验 → 生成源码 → Gate2 → 打包。

    body: { siteCode, inventoryRef, changes, meta:{namespace,functionName,version,description} }
    """
    body = body or {}
    site_code = body.get("siteCode")
    inventory_ref = body.get("inventoryRef")
    changes = body.get("changes") or []
    meta = body.get("meta") or {}
    if not (site_code and inventory_ref and changes and meta.get("functionName")):
        return Result.failure(
            "缺少 siteCode/inventoryRef/changes/meta.functionName",
            code=errors.VALIDATION_ERROR,
        )

    # 1. Gate1 冲突校验（生成前强制）
    gate1 = _validation.conflict_check(site_code, inventory_ref, changes)
    if gate1.is_failure():
        return gate1
    if not gate1.value["passed"]:
        return Result.failure(
            "存在冲突，无法生成。请返回调整需求。",
            code=errors.CHANGE_SPEC_INVALID,
            details={"checks": gate1.value["checks"]},
        )

    # 2. 生成源码
    summary, err = _load_summary(site_code, inventory_ref)
    if err:
        return err
    gen = AddonGenerator(meta, changes, summary).generate()
    if gen.is_failure():
        return gen

    # 3. Gate2 + 打包
    site = _repo.get_site(site_code) or {}
    change_spec = {
        "version": "1.0",
        "siteCode": site_code,
        "companyCode": site.get("companyCode", ""),
        "inventoryRef": inventory_ref,
        "changes": changes,
    }
    delivered = _delivery.deliver(
        gen.value["fullName"],
        gen.value["version"],
        gen.value["files"],
        change_spec,
        gate1.value,
    )
    return delivered


def download(params, **_):
    """下载生成的 ZIP。params: { packageId }。"""
    package_id = params["packageId"]
    # __file__ = backend/api/addon_studio.py → dirname×3 → aiconfigtool/
    root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    zip_path = os.path.join(root, "output", "projects", package_id, package_id + ".zip")
    if not os.path.isfile(zip_path):
        return Result.failure("产物不存在: %s" % package_id, code=errors.NOT_FOUND)
    return Result.success({"__file__": zip_path, "filename": package_id + ".zip"})


def install_verify(body, **_):
    """测试站点安装 + 验证。body: { fullName, version, siteCode, testSiteCode }"""
    from services.install_service import InstallService
    svc = InstallService()
    body = body or {}
    for k in ("fullName", "version", "siteCode", "testSiteCode"):
        if not body.get(k):
            return Result.failure("缺少 %s" % k, code=errors.VALIDATION_ERROR)
    return svc.install_and_verify(
        body["fullName"], body["version"], body["siteCode"], body["testSiteCode"])


def deploy_doc(params, **_):
    """下载部署指南 DEPLOY.md。"""
    package_id = params["packageId"]
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    md_path = os.path.join(root, "output", "projects", package_id, "实施部署指南.md")
    if not os.path.isfile(md_path):
        md_path = os.path.join(root, "output", "projects", package_id, "DEPLOY.md")
    if not os.path.isfile(md_path):
        return Result.failure("部署指南不存在", code=errors.NOT_FOUND)
    return Result.success({"__file__": md_path, "filename": "deploy-guide.md"})


def cleanup_addon(body, **_):
    """彻底清理测试站点上的 Addon：Plone 卸载 + 删源码 + 删 cfg + buildout + docker restart。"""
    from services.install_service import InstallService
    svc = InstallService()
    body = body or {}
    addon = body.get("addonName")
    site_code = body.get("siteCode")
    if not addon or not site_code:
        return Result.failure("缺少 addonName 或 siteCode", code=errors.VALIDATION_ERROR)
    return svc.cleanup(addon, site_code)


def register(router) -> None:
    router.post("/api/addon-studio/parse-requirement", parse_requirement)
    router.post("/api/addon-studio/conflict-check", conflict_check)
    router.post("/api/addon-studio/generate", generate)
    router.get("/api/addon-studio/download/{packageId}", download)
    router.post("/api/addon-studio/install-verify", install_verify)
    router.post("/api/addon-studio/cleanup", cleanup_addon)
    router.get("/api/addon-studio/deploy-doc/{packageId}", deploy_doc)
