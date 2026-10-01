# -*- coding: utf-8 -*-
"""电子签名双人同页校验辅助函数。"""


def _normalize_user_id(user_id):
    return (user_id or "").strip()


def check_signers_against_initiator(signer_user_ids,
                                    initiator_user_id,
                                    enabled=True):
    """校验签名人（可能有两个）都不是单据发起人。

    为什么必须由签名页来做这个校验：单人签名时工作流守卫能拦住"自己审自己"，
    但双人复核的第二个账号是在同一个页面里提交的——守卫只看得到当前登录用户，
    看不到复核人。所以规则表里的 ``disallow_initiator`` 只能在这里落地。

    返回 ``None`` 表示通过，否则返回给用户看的错误消息（中文）。
    """
    if not enabled:
        return None
    initiator = _normalize_user_id(initiator_user_id)
    if not initiator:
        # fail-closed：拿不到发起人就宁可拒绝，也不放过潜在的"自己签自己"。
        return u"无法确定单据发起人，出于合规要求已拒绝本次电子签名。"
    for signer in signer_user_ids or []:
        signer = _normalize_user_id(signer)
        if signer and signer == initiator:
            return (
                u"电子签名必须由非申请人完成：申请人账号（{}）不能作为"
                u"签名人或复核人。"
            ).format(initiator)
    return None


def authenticate_countersign_users(provider,
                                   primary_user_id,
                                   primary_password,
                                   secondary_user_id,
                                   secondary_password,
                                   request_context=None):
    """在同一个界面里一次性校验两个操作员账号密码。"""
    primary_user_id = _normalize_user_id(primary_user_id)
    secondary_user_id = _normalize_user_id(secondary_user_id)

    if not primary_user_id:
        return {
            "authenticated": False,
            "failure_reason": "missing_primary_user_id",
        }
    if not primary_password:
        return {
            "authenticated": False,
            "failure_reason": "missing_primary_password",
        }
    if not secondary_user_id:
        return {
            "authenticated": False,
            "failure_reason": "missing_secondary_user_id",
        }
    if not secondary_password:
        return {
            "authenticated": False,
            "failure_reason": "missing_secondary_password",
        }
    if primary_user_id == secondary_user_id:
        # 双人复核必须是两个不同账号，避免同一人重复签名。
        return {
            "authenticated": False,
            "failure_reason": "same_signer_not_allowed",
        }

    primary_result = provider.authenticate_user(
        primary_user_id,
        primary_password,
        request_context=request_context,
    )
    if not primary_result.get("authenticated"):
        return {
            "authenticated": False,
            "failure_reason": "primary_auth_failed",
            "provider_failure_reason": primary_result.get("failure_reason"),
            "primary_user_id": primary_user_id,
        }

    secondary_result = provider.authenticate_user(
        secondary_user_id,
        secondary_password,
        request_context=request_context,
    )
    if not secondary_result.get("authenticated"):
        return {
            "authenticated": False,
            "failure_reason": "secondary_auth_failed",
            "provider_failure_reason": secondary_result.get("failure_reason"),
            "primary_user_id": primary_user_id,
            "secondary_user_id": secondary_user_id,
        }

    return {
        "authenticated": True,
        "failure_reason": None,
        "primary_user_id": primary_user_id,
        "secondary_user_id": secondary_user_id,
        "primary_auth_backend_id": primary_result.get("backend_id"),
        "secondary_auth_backend_id": secondary_result.get("backend_id"),
    }
