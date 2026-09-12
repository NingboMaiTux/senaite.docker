# -*- coding: utf-8 -*-
u"""竹云-backed re-authentication for ``maitux.esignature``.

Why this exists
---------------

GMP / 21 CFR Part 11 signing asks the person at the keyboard to re-enter their
password, to prove the session was not left unattended.  ``maitux.esignature``
ships a provider that checks that password against the local PAS chain -- which
stops working the moment login moves to 竹云: the local account's password is a
random string generated at creation time (``users.random_password``) that nobody
has ever seen, so no human can ever type it.

So the check has to go back to the identity provider.  竹云 has no "verify this
password" endpoint as such; what it has is the 用户接口 (SDK) login:

    POST /api/v2/sdk/login   {"user_name": ..., "password": ...}

which is a full login and therefore answers exactly the question we need.
Documented at https://docs.bccastle.com/api/eiam/userapi/login/username-pwd.

(The OAuth2 password grant would have been the tidier route, but this tenant
answers ``unsupported_grant_type: Unauthorized grant type: password`` -- the
application is not authorised for it.  Verified against production.)

Which package this lives in
---------------------------

``maitux.esignature`` owns the ``IReAuthenticationProvider`` contract and says a
provider belongs "in whichever add-on knows that identity source".  This one is
here because this package owns the 竹云 connection settings.  The dependency
runs one way -- this module imports the contract, nothing in the signature
package knows 竹云 exists -- and the registration in ``configure.zcml`` is
conditional, so this add-on still installs on a site without e-signatures.

The account lockout problem
---------------------------

Every failed call here consumes one of the person's 竹云 login attempts, and
running out locks the account with ``SDK.LOGIN.1003``.  竹云 is the *company's*
single sign-on: that lockout takes the employee's mail, OA and everything else
down with the LIMS.  Signing is a routine, frequent action and people mistype,
so a naive pass-through would turn ordinary fumbling into a helpdesk ticket.

Two guards, deliberately different in kind:

* a local cooldown after a few consecutive failures, so repeated attempts stop
  reaching 竹云 at all.  Best effort only -- it lives in process memory, and a
  deployment running two Zope instances behind a load balancer has two of them.
* the count 竹云 itself reports ("剩余登录尝试次数:N").  That number is
  authoritative, shared, and needs no state on our side: when it drops to the
  configured floor we stop and tell the person to go sort their password out
  with 竹云 directly, leaving the last attempts for them.

The remaining count is also passed straight through to the signer, because
``maitux.esignature`` renders ``failure_reason`` verbatim -- so the warning
("还允许尝试 2 次") reaches the person who can act on it.
"""

import json
import time

from plone import api
from zope.interface import implementer

from maitux.esignature.interfaces import IReAuthenticationProvider

from maitux.oauth2 import config
from maitux.oauth2 import logger
from maitux.oauth2 import safe_text
from maitux.oauth2 import users
from maitux.oauth2.client import BCastleClient
from maitux.oauth2.client import OAuth2Error
from maitux.oauth2.httputils import HttpError

BACKEND_ID = "bccastle"

#: Login statuses that mean "the password was right".  PASSWORD_WARN is a
#: success with a nag attached -- refusing a signature over a password that is
#: merely *about* to expire would block work for no safety gain.
ACCEPTED_STATUSES = ("SUCCESS", "PASSWORD_WARN")

#: Statuses that are not failures of the password but still must not sign.
STATUS_REFUSALS = {
    "PASSWORD_EXPIRED": u"竹云密码已过期，请先到竹云修改密码后再签名",
    "MFA_AUTH": u"该账号要求二次认证，无法在此完成签名验证，请联系管理员",
    "ACCESS_DENIED": u"竹云拒绝了本次验证（拒绝访问）",
}

ERROR_MESSAGES = {
    u"SDK.LOGIN.1002": u"该账号在竹云未绑定本应用",
    u"SDK.LOGIN.1003": u"账号已被竹云锁定，请联系公司 IT 解锁",
    u"SDK.LOGIN.1004": u"竹云密码策略读取失败，请稍后再试",
    u"SDK.COMMON.1001": u"调用竹云缺少必填参数，请检查插件配置",
    u"SDK.COMMON.1003": u"调用竹云缺少设备信息请求头，请检查插件配置",
    u"SDK.COMMON.1012": u"ClientId 不正确或应用不存在，请检查插件配置",
    u"SDK.COMMON.1013": u"竹云中找不到该用户",
}

WRONG_PASSWORD = u"SDK.LOGIN.1005"


# ---------------------------------------------------------------------------
# result mappings
#
# Built by hand rather than imported from maitux.esignature.services.reauth:
# the contract is the interface and the shape of this mapping, and importing a
# concrete helper out of the other package would couple us to its internals.
# ---------------------------------------------------------------------------

def _success(user_id):
    return {
        "authenticated": True,
        "backend_id": BACKEND_ID,
        "user_id": user_id,
        "failure_reason": None,
    }


def _failure(user_id, reason):
    return {
        "authenticated": False,
        "backend_id": BACKEND_ID,
        "user_id": user_id,
        "failure_reason": reason,
    }


# ---------------------------------------------------------------------------
# local throttle
# ---------------------------------------------------------------------------

#: ``{竹云 login name: {"count": int, "until": epoch}}``.  Process local and
#: deliberately not persisted: this is a courtesy brake, not the real guard --
#: see the module docstring.  Writing a ZODB record on every mistyped password
#: would buy shared state at the price of a write conflict on a code path whose
#: whole job is to fail cleanly.
_FAILURES = {}

#: Entries are tiny, but a long-lived process would otherwise accumulate one
#: per person who ever mistyped.  Pruned opportunistically on write.
_PRUNE_AFTER = 3600


def _int_setting(name, fallback):
    try:
        value = int(config.get(name))
    except (TypeError, ValueError):
        return fallback
    return value


def _prune(now):
    for key in list(_FAILURES):
        if now - _FAILURES[key].get("seen", 0) > _PRUNE_AFTER:
            del _FAILURES[key]


def _state(name):
    return _FAILURES.get(name) or {"count": 0, "until": 0.0, "seen": 0.0}


def cooldown_remaining(name):
    """Seconds left before *name* may be checked against 竹云 again."""
    left = int(round(_state(name).get("until", 0.0) - time.time()))
    return left if left > 0 else 0


def note_failure(name):
    """Count a failed attempt, starting a cooldown once the limit is hit."""
    now = time.time()
    _prune(now)
    state = _state(name)
    state["count"] += 1
    state["seen"] = now
    limit = _int_setting("esign_max_attempts", 3)
    if limit > 0 and state["count"] >= limit:
        state["until"] = now + max(_int_setting("esign_cooldown_seconds", 60), 1)
        state["count"] = 0
    _FAILURES[name] = state


def start_cooldown(name):
    """Stop talking to 竹云 about *name* for a while, regardless of the count."""
    now = time.time()
    state = _state(name)
    state["count"] = 0
    state["seen"] = now
    state["until"] = now + max(_int_setting("esign_cooldown_seconds", 60), 1)
    _FAILURES[name] = state


def clear_failures(name):
    _FAILURES.pop(name, None)


# ---------------------------------------------------------------------------
# parsing 竹云 replies
# ---------------------------------------------------------------------------

def remaining_attempts(message):
    """The N out of "剩余登录尝试次数:N", or None.

    Parsed off the human readable message because 竹云 returns it nowhere else;
    a wording change upstream only costs us the warning, never correctness --
    everything that acts on it treats None as "unknown".
    """
    text = safe_text(message or u"")
    if u"尝试次数" not in text and u"attempt" not in text.lower():
        return None
    digits = u""
    for char in reversed(text.strip()):
        if char.isdigit():
            digits = char + digits
        elif digits:
            break
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def identity_from_id_token(id_token):
    """The ``userName`` 竹云 signed into the returned id_token, or ``u""``.

    The identity is not a top level field: it sits in the JWT payload under
    ``api``, which is itself a JSON *string*, so it takes two decodes to reach.
    The signature is not verified -- this value is only ever used to confirm
    竹云 answered about the account we asked about, over a channel that is
    already TLS-authenticated, and a mismatch is treated as a refusal.
    """
    token = safe_text(id_token or u"")
    parts = token.split(".")
    if len(parts) < 2:
        return u""
    segment = parts[1]
    padding = len(segment) % 4
    if padding:
        segment += u"=" * (4 - padding)
    try:
        import base64
        raw = base64.urlsafe_b64decode(segment.encode("ascii"))
        payload = json.loads(raw.decode("utf-8", "replace"))
        inner = json.loads(payload.get("api") or u"{}")
    except Exception as exc:
        logger.warning("Could not read the identity out of an id_token: %s",
                       safe_text(exc))
        return u""
    return safe_text(inner.get("userName") or u"")


# ---------------------------------------------------------------------------
# the provider
# ---------------------------------------------------------------------------

@implementer(IReAuthenticationProvider)
class BCastleReAuthenticationProvider(object):
    u"""Re-authenticate a signer against 竹云."""

    backend_id = BACKEND_ID
    title = u"竹云统一登录"

    def supports_interactive_reauth(self):
        return True

    def authenticate_current_user(self, user_id, credential,
                                  request_context=None):
        """Single signer: the account must be the one holding this session."""
        current = self._current_user_id()
        if not current or current != user_id:
            return _failure(user_id, u"当前登录用户与签名账号不一致")
        return self.verify(user_id, credential)

    def authenticate_user(self, user_id, credential, request_context=None):
        """Any account -- used for the second reviewer in a dual signature.

        Deliberately *not* tied to the session: the whole point is that somebody
        other than the person logged in puts their credentials in.
        """
        return self.verify(user_id, credential)

    # -- internals ----------------------------------------------------

    def _current_user_id(self):
        try:
            member = api.user.get_current()
        except Exception:  # pragma: no cover - no request, e.g. a script
            return None
        return member.getId() if member is not None else None

    def verify(self, user_id, credential):
        if not credential:
            return _failure(user_id, u"密码不能为空")

        try:
            portal = api.portal.get()
        except Exception as exc:  # pragma: no cover - outside a site
            logger.error("No portal while verifying a signature: %s",
                         safe_text(exc))
            return _failure(user_id, u"无法定位站点")

        name = users.idp_username(portal, user_id)
        if not name:
            return _failure(user_id, u"该账号没有对应的竹云登录名，无法验证")

        waiting = cooldown_remaining(name)
        if waiting:
            return _failure(
                user_id,
                u"密码连续错误，为保护您的公司账号已暂停验证，请 %d 秒后再试"
                % waiting)

        try:
            data = BCastleClient().sdk_login(name, credential)
        except OAuth2Error as exc:
            return self._from_error(user_id, name, exc)
        except HttpError as exc:
            # A network problem is not a wrong password: say so, so nobody goes
            # hunting for a password that was right all along.
            logger.error("竹云 unreachable while verifying %s: %s",
                         user_id, safe_text(exc))
            return _failure(user_id, u"无法连接竹云，请稍后再试或联系管理员")
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Unexpected error verifying %s: %s",
                         user_id, safe_text(exc))
            return _failure(user_id, u"验证过程出错，请联系管理员")

        return self._from_reply(user_id, name, data)

    def _from_reply(self, user_id, name, data):
        status = safe_text((data or {}).get("status") or u"").upper()

        if status not in ACCEPTED_STATUSES:
            refusal = STATUS_REFUSALS.get(status)
            if refusal is None:
                logger.error("竹云 answered with an unknown status %r for %s",
                             status, user_id)
                refusal = u"竹云返回了未知状态 %s，请联系管理员" % (status or u"(空)")
            return _failure(user_id, refusal)

        # 竹云 accepted a password -- but for whom?  If the reply is about
        # somebody else, the signature would be attributed to the wrong person,
        # which is the one failure mode an audit trail cannot survive.
        signed_in = identity_from_id_token(data.get("id_token"))
        if signed_in and signed_in.lower() != name.lower():
            logger.error(
                "竹云 authenticated %r while we asked about %r (local user %s)",
                signed_in, name, user_id)
            return _failure(user_id, u"竹云返回的身份与所验证的账号不一致")

        clear_failures(name)
        if status == u"PASSWORD_WARN":
            logger.info(u"Signature check passed for %s; 竹云 password expires soon",
                        user_id)
        return _success(user_id)

    def _from_error(self, user_id, name, exc):
        code = safe_text(exc.error or u"").strip().upper()
        message = safe_text(exc.description or u"")

        if code != WRONG_PASSWORD:
            logger.warning("竹云 refused the signature check for %s: %s %s",
                           user_id, code, message)
            return _failure(
                user_id,
                ERROR_MESSAGES.get(code) or (message or u"竹云验证失败 %s" % code))

        note_failure(name)
        left = remaining_attempts(message)
        if left is None:
            return _failure(user_id, u"密码错误")

        floor = _int_setting("esign_min_remaining_attempts", 3)
        if floor > 0 and left <= floor:
            # Stop before 竹云 locks them out of every company system.
            start_cooldown(name)
            logger.warning(
                "Pausing signature checks for %s: 竹云 reports only %s attempts left",
                user_id, left)
            return _failure(
                user_id,
                u"密码连续错误，竹云仅剩 %d 次尝试机会。为避免锁定您的公司账号，"
                u"LIMS 已暂停验证，请先到竹云确认密码后再签名" % left)

        return _failure(
            user_id,
            u"密码错误，还可尝试 %d 次；次数用尽将锁定您的竹云账号"
            u"（公司所有系统一并无法登录）" % left)
