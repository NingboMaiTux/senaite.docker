# -*- coding: utf-8 -*-
"""CSRF protection for the authorisation-code round trip.

The ``state`` parameter sent to 竹云 is a random nonce.  The same nonce -- plus
the URL the user originally wanted -- is stored in an HMAC signed, http-only
cookie.  On the callback both are compared, which makes a forged callback
useless.

A cookie is used on purpose: ``request.SESSION`` depends on the Zope temp
folder, which is not reliable in a RelStorage/PostgreSQL deployment.
"""

import base64
import binascii
import hashlib
import hmac
import json
import os

from maitux.oauth2 import config
from maitux.oauth2 import logger

STATE_COOKIE = "maitux_oauth2_state"
BYPASS_COOKIE = "maitux_oauth2_bypass"
#: One shot marker, set by the callback when it restarts a login whose state
#: did not check out.  Without it a state that never checks out would bounce
#: the browser between LIMS and 竹云 forever.
RETRY_COOKIE = "maitux_oauth2_retry"
#: How long a started login may stay unfinished.  The authorisation code
#: itself expires much sooner (5 minutes on 竹云), but a user who opens the
#: login page and only comes back later must not be met with a scary
#: "security check failed" page -- 15 minutes turned out to be too tight in
#: practice.  This is only the anti-CSRF nonce window; the cookie is cleared
#: as soon as the callback is processed.
COOKIE_MAX_AGE = 1800


def _as_bytes(value):
    if isinstance(value, bytes):
        return value
    return value.encode("utf-8")


def _b64encode(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value):
    value = _as_bytes(value)
    padding = b"=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _secret():
    secret = config.get("state_secret") or u""
    if not secret:
        # Never sign with an empty key.  ensure_secret() runs at install time;
        # this is only a safety net for sites installed before that step.
        secret = ensure_secret()
    return _as_bytes(secret)


def ensure_secret():
    """Create the signing secret if it does not exist yet.  Returns it."""
    secret = config.get("state_secret") or u""
    if secret:
        return secret
    secret = binascii.hexlify(os.urandom(32)).decode("ascii")
    if not config.set_value("state_secret", secret):
        logger.warning(
            "Could not persist state_secret -- state validation will fail "
            "across restarts until the add-on profile is installed")
    return secret


def _sign(payload):
    digest = hmac.new(_secret(), _as_bytes(payload), hashlib.sha256).digest()
    return _b64encode(digest)


def _compare(left, right):
    left = _as_bytes(left or u"")
    right = _as_bytes(right or u"")
    compare = getattr(hmac, "compare_digest", None)
    if compare is not None:
        return compare(left, right)
    # pragma: no cover - Python < 2.7.7
    if len(left) != len(right):
        return False
    result = 0
    for a, b in zip(bytearray(left), bytearray(right)):
        result |= a ^ b
    return result == 0


#: Public alias -- constant time string comparison for callers outside this
#: module (e.g. the sync token check).
compare = _compare


def make_state(came_from=None):
    """Return ``(state, cookie_value)``."""
    nonce = binascii.hexlify(os.urandom(16)).decode("ascii")
    payload = _b64encode(_as_bytes(json.dumps(
        {"n": nonce, "c": came_from or u""}, sort_keys=True)))
    return nonce, u"%s.%s" % (payload, _sign(payload))


def read_state(cookie_value, state_param):
    """Validate the callback and return ``came_from``.

    Raises ``ValueError`` when the state does not check out.
    """
    if not cookie_value:
        # An expired cookie is simply not sent, so this covers both "took too
        # long" and "cookies are blocked" -- name both, the user cannot tell.
        raise ValueError(
            u"state cookie 不在请求里：登录停留超过 %d 分钟已失效，"
            u"或浏览器阻止了 Cookie" % (COOKIE_MAX_AGE // 60))
    if not state_param:
        raise ValueError(u"回调缺少 state 参数")

    parts = cookie_value.rsplit(u".", 1)
    if len(parts) != 2:
        raise ValueError(u"state cookie 格式不正确")
    payload, signature = parts
    if not _compare(signature, _sign(payload)):
        raise ValueError(u"state 签名校验失败")

    try:
        data = json.loads(_b64decode(payload).decode("utf-8"))
    except (ValueError, TypeError, binascii.Error):
        raise ValueError(u"state 内容无法解析")

    if not _compare(data.get("n") or u"", state_param):
        raise ValueError(u"state 与本次登录请求不匹配")

    return data.get("c") or u""


def check_state(cookie_value, state_param, require_state=False):
    """Decide what to do with a callback.  Returns ``(came_from, note)``.

    ``came_from`` is ``None`` when the callback has to be refused, ``note`` is
    a one line reason for the log.

    The case worth explaining is "no cookie of ours".  It means this browser
    never started a login *here*, which happens routinely and legitimately:

    * the user came from the 竹云 Portal by clicking the LIMS icon.  竹云 does
      not have to send a ``state`` then, but nothing stops it from sending one
      of its own making either -- and we have nothing to compare that against.
    * the login started on a different origin than the registered
      ``redirect_uri`` points at: https vs http, domain vs IP, another port.
      A cookie belongs to the origin that set it, so it is simply not sent
      back, and the very first login of the day fails while the retry -- which
      starts from the callback origin -- works.  That is a deployment mistake
      worth fixing, but refusing the login does not help anyone find it.

    So a ``state`` we never issued carries exactly as much information as no
    ``state`` at all, and both are accepted on the same terms.
    ``require_state`` is the switch for sites that would rather refuse both.
    A cookie that *is* there and disagrees stays a hard failure: that is the
    forged callback the nonce exists for.
    """
    if not cookie_value:
        if require_state:
            return None, u"no state cookie of ours, and require_state is on"
        if state_param:
            return u"", (u"callback carries a state we never issued -- Portal "
                         u"initiated login, or the login started on another "
                         u"origin than redirect_uri")
        return u"", u"callback without state -- IdP initiated login"
    try:
        return read_state(cookie_value, state_param), u"state verified"
    except ValueError as exc:
        return None, u"state rejected: %s" % exc


def set_cookie(response, name, value, max_age=COOKIE_MAX_AGE, secure=None,
               path="/"):
    # SameSite=Lax on purpose: the state cookie has to survive the top level
    # redirect coming back from 竹云 (Lax does send cookies on cross site GET
    # navigations, Strict would not), and Lax works without Secure on http.
    kwargs = {"path": path, "http_only": True, "same_site": "Lax"}
    if max_age is not None:
        kwargs["max_age"] = max_age
    if secure:
        kwargs["secure"] = True
    try:
        response.setCookie(name, value, **kwargs)
    except TypeError:  # pragma: no cover - older ZPublisher signature
        response.setCookie(name, value, path=path)


def clear_cookie(response, name, path="/"):
    try:
        response.expireCookie(name, path=path)
    except Exception:  # pragma: no cover
        logger.warning("Could not expire cookie %s", name)
