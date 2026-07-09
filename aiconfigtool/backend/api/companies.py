"""公司资源 handler — 完整 CRUD。"""

from __future__ import annotations

from infrastructure.config_repository import ConfigRepository
from shared import errors
from shared.result import Result

_repo = ConfigRepository()


def list_companies(**_):
    return Result.success(_repo.list_companies())


def get_company(params, **_):
    code = params["code"]
    c = _repo.get_company(code)
    if c is None:
        return Result.failure("公司不存在: %s" % code, code=errors.NOT_FOUND)
    return Result.success(c)


def create_company(params, body, **_):
    body = body or {}
    code = body.get("code")
    if not code:
        return Result.failure("缺少 code", code=errors.VALIDATION_ERROR)
    _repo.save_company(code, dict(body))
    return Result.success(body)


def update_company(params, body, **_):
    code = params["code"]
    existing = _repo.get_company(code)
    if existing is None:
        return Result.failure("公司不存在: %s" % code, code=errors.NOT_FOUND)
    merged = dict(existing)
    if body:
        merged.update(body)
    _repo.save_company(code, merged)
    return Result.success(merged)


def delete_company(params, **_):
    code = params["code"]
    if _repo.get_company(code) is None:
        return Result.failure("公司不存在: %s" % code, code=errors.NOT_FOUND)
    _repo.delete_company(code)
    return Result.success(None)


def register(router) -> None:
    router.get("/api/companies", list_companies)
    router.post("/api/companies", create_company)
    router.get("/api/companies/{code}", get_company)
    router.put("/api/companies/{code}", update_company)
    router.delete("/api/companies/{code}", delete_company)
