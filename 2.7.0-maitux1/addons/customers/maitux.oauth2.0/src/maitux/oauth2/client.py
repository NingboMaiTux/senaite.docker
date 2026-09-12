# -*- coding: utf-8 -*-
"""Client for the Bamboocloud (竹云) IDaaS OAuth 2.0 and EIAM APIs.

Endpoints implemented (see https://open.bccastle.com/development/):

* ``GET  /api/v1/oauth2/authorize``  获取标准授权码
* ``POST /api/v1/oauth2/token``      获取 Access Token
* ``GET  /api/v1/oauth2/userinfo``   获取用户信息
* ``POST /api/v1/oauth2/introspect`` 检查 Token 有效性
* ``GET  /api/v1/logout``            全局退出
* ``POST /api/v2/tenant/token``      EIAM 鉴权 (client_credentials)
* ``GET  /api/v2/tenant/applications/{app_id}/accounts``  应用账号列表
* ``POST /api/v2/tenant/users/user-by-username``          按用户名获取用户详情
* ``POST /api/v2/sdk/login``                              用户名+密码登录（电子签名二次验证）

The tenant-wide ``GET /api/v2/tenant/users`` is deliberately *not* implemented.
It answers with every employee on the tenant -- a few thousand records carrying
ID card numbers, mobiles and home addresses -- when the LIMS is only entitled to
the few dozen people the customer's IT has authorised for this application.  So
the sync asks which accounts are authorised first, then fetches exactly those
directory records one by one.
"""

from six.moves.urllib.parse import urlencode

from maitux.oauth2 import config
from maitux.oauth2 import logger
from maitux.oauth2.httputils import HttpError
from maitux.oauth2.httputils import basic_auth_header
from maitux.oauth2.httputils import request_json


class OAuth2Error(Exception):
    """竹云 answered with an OAuth2 error payload."""

    def __init__(self, error, description=None, status=None):
        message = error or u"unknown_error"
        if description:
            message = u"%s: %s" % (message, description)
        super(OAuth2Error, self).__init__(message)
        self.error = error
        self.description = description
        self.status = status


def _error_from(data, status):
    error = data.get("error") or data.get("error_code")
    if not error:
        return None
    description = data.get("error_description") or data.get("error_msg")
    return OAuth2Error(error, description, status)


class BCastleClient(object):
    """Thin, stateless wrapper around the 竹云 HTTP API."""

    def __init__(self):
        self.client_id = config.get("client_id") or u""
        self.client_secret = config.get("client_secret") or u""
        self.timeout = config.get("request_timeout") or 15
        self.verify_ssl = bool(config.get("verify_ssl"))
        self.use_system_proxy = bool(config.get("use_system_proxy"))

    # -- helpers ------------------------------------------------------

    @property
    def _basic_auth(self):
        return basic_auth_header(self.client_id, self.client_secret)

    def _call(self, url, method="GET", form=None, json_body=None, headers=None):
        if not url:
            raise HttpError(u"竹云接口地址未配置")
        status, data = request_json(
            url,
            method=method,
            form=form,
            json_body=json_body,
            headers=headers,
            timeout=self.timeout,
            verify_ssl=self.verify_ssl,
            use_system_proxy=self.use_system_proxy,
        )
        error = _error_from(data, status)
        if error is not None:
            raise error
        if status < 200 or status >= 300:
            raise HttpError(
                u"竹云接口返回 HTTP %s" % status, status=status, body=data)
        return data

    # -- OAuth2 login -------------------------------------------------

    def authorize_url(self, state, redirect_uri):
        """Build the 竹云 authorisation URL the browser is sent to."""
        params = [
            ("response_type", "code"),
            ("client_id", self.client_id),
        ]
        if redirect_uri:
            params.append(("redirect_uri", redirect_uri))
        scope = config.get("scope")
        if scope:
            params.append(("scope", scope))
        if state:
            params.append(("state", state))
        return u"%s?%s" % (config.endpoint("authorize_path"), urlencode(params))

    def exchange_code(self, code, redirect_uri):
        """授权码换 access_token."""
        form = {"grant_type": "authorization_code", "code": code}
        if redirect_uri:
            form["redirect_uri"] = redirect_uri
        return self._call(
            config.endpoint("token_path"),
            method="POST",
            form=form,
            headers={"Authorization": self._basic_auth},
        )

    def get_userinfo(self, access_token):
        """携带 access_token 获取用户身份."""
        return self._call(
            config.endpoint("userinfo_path"),
            headers={"Authorization": u"Bearer %s" % access_token},
        )

    def introspect(self, token):
        """检查 token 是否仍然有效."""
        return self._call(
            config.endpoint("introspect_path"),
            method="POST",
            form={"token": token, "token_type_hint": "access_token"},
            headers={"Authorization": self._basic_auth},
        )

    def logout_url(self, redirect_url):
        """竹云全局退出地址."""
        url = config.endpoint("idp_logout_path")
        if not url:
            return u""
        params = []
        if redirect_url:
            params.append(("redirect_url", redirect_url))
        if self.client_id:
            params.append(("client_id", self.client_id))
        if params:
            url = u"%s?%s" % (url, urlencode(params))
        return url

    # -- EIAM (daily user sync) ---------------------------------------

    def eiam_token(self):
        """client_credentials token for the 身份管理 API."""
        data = self._call(
            config.endpoint("eiam_token_path"),
            method="POST",
            form={"grant_type": "client_credentials"},
            headers={"Authorization": self._basic_auth},
        )
        token = data.get("access_token")
        if not token:
            raise HttpError(u"EIAM 鉴权接口未返回 access_token", body=data)
        return token

    def _eiam_headers(self, token):
        return {
            "Authorization": u"Bearer %s" % token,
            "Content-Type": "application/json; charset=utf-8",
        }

    def iter_app_accounts(self, token=None, page_size=None):
        """Yield the accounts authorised for *this* application.

        This is the list the customer's IT curates in 竹云: only these people
        are entitled to the LIMS.  It is two orders of magnitude smaller than
        the tenant directory -- tens of rows against thousands -- which is why
        the sync starts here.

        Each row carries ``account_name`` (equal to the directory's
        ``user_name``), ``name``, ``disabled`` and ``account_type``; there is no
        ``external_id`` and no mail address, so :meth:`get_user_by_username`
        supplies the rest.
        """
        token = token or self.eiam_token()
        app_id = (config.get("app_id") or u"").strip()
        if not app_id:
            raise HttpError(u"未配置 AppId，无法读取应用账号列表")
        page_size = page_size or config.get("sync_page_size") or 100
        page_size = max(10, min(100, int(page_size)))

        headers = self._eiam_headers(token)
        base = config.endpoint("eiam_app_accounts_path").replace(u"{app_id}", app_id)

        offset = 0
        seen = 0
        total = None
        while True:
            url = u"%s?%s" % (
                base, urlencode([("offset", offset), ("limit", page_size)]))
            data = self._call(url, headers=headers)
            accounts = data.get("accounts") or []
            if total is None:
                total = data.get("total")
            for account in accounts:
                if isinstance(account, dict):
                    seen += 1
                    yield account

            if len(accounts) < page_size:
                break
            offset += 1
            if total is not None and seen >= total:
                break
            if offset > 1000:  # pragma: no cover - runaway guard
                logger.error("App account pagination did not terminate, aborting")
                break

    # -- SDK login (e-signature password check) ------------------------

    def _sdk_headers(self):
        """Headers the 用户接口 (SDK) family requires.

        竹云 documents X-client-id, X-device-fingerprint, X-operating-sys-version
        and X-agent as mandatory, and it means it: a request carrying only
        X-client-id is rejected with ``SDK.COMMON.1003 设备信息不完整`` -- verified
        against the customer's production tenant.  Note the authentication here
        is the header, *not* HTTP Basic: this family does not use the OAuth2
        client credentials.
        """
        return {
            "X-client-id": self.client_id,
            "X-device-fingerprint": (
                config.get("sdk_device_fingerprint") or u"maitux-lims"),
            "X-operating-sys-version": (
                config.get("sdk_os_version") or u"linux"),
            "X-agent": config.get("sdk_user_agent") or u"MaituxLIMS",
            "X-L": u"zh",
        }

    def sdk_login(self, user_name, password):
        """Check one login name / password pair against 竹云.

        Used by the electronic signature re-authentication, which has to prove
        the person at the keyboard really is who the session says -- the local
        account cannot answer that, its password is a random string nobody
        knows (see ``users.random_password``).

        Returns the decoded body on success; ``status`` says what kind of
        success it is (``SUCCESS``, ``PASSWORD_WARN``, ``PASSWORD_EXPIRED``,
        ``MFA_AUTH``, ``ACCESS_DENIED``).  A wrong password raises
        :class:`OAuth2Error` with ``error`` = ``SDK.LOGIN.1005`` and a
        description that carries the remaining attempt count.

        NOTE: every failure here consumes one of the account's 竹云 login
        attempts, and running out locks the account across *every* company
        system, not just the LIMS.  Callers must throttle -- see
        ``maitux.oauth2.reauth``.
        """
        return self._call(
            config.endpoint("sdk_login_path"),
            method="POST",
            json_body={"user_name": user_name, "password": password},
            headers=self._sdk_headers(),
        )

    #: 竹云 answers a lookup for an unknown login name with this error code.
    UNKNOWN_USER_ERROR = u"USER.0001"

    def get_user_by_username(self, user_name, token=None):
        """Directory record for one login name, or ``None`` when unknown.

        Unlike the tenant user list this returns a single person, so the sync
        never downloads the personal data of employees who have no business
        being in the LIMS.
        """
        if not user_name:
            return None
        token = token or self.eiam_token()
        try:
            return self._call(
                config.endpoint("eiam_user_by_username_path"),
                method="POST",
                json_body={"user_name": user_name},
                headers=self._eiam_headers(token),
            )
        except OAuth2Error as exc:
            if (exc.error or u"").strip().upper() == self.UNKNOWN_USER_ERROR:
                # Authorised for the application but no longer in the directory:
                # a leaver whose app account has not been cleaned up yet.
                return None
            raise
