# -*- coding: utf-8 -*-
u"""每日用户同步的单元测试 —— 不需要 Plone，不需要网络，不需要竹云。

怎么跑
------

用容器里那个解释器（Python 2.7）直接跑这个文件即可::

    python src/maitux/oauth2/tests.py

或者挑一部分::

    python src/maitux/oauth2/tests.py AdminProtectionTests
    python src/maitux/oauth2/tests.py -v

为什么要自己造桩
----------------

这个 add-on 的 ``users.py`` 依赖 ``plone.api`` 和 ``Products.CMFCore``，离开
Zope 根本 import 不了；而同步逻辑（谁该建号、谁该停用、什么时候必须罢工）恰恰是
最该测、也最不该靠「部署上去点一下」来验的部分。所以这里用几十行假对象顶掉
``plone.api`` / ``Products.CMFCore.utils``，再把**真实的** ``users.py`` 和
``sync.py`` 按文件路径加载进来跑。被测的是真代码，不是复刻品。

``BCastleClient`` 被整体换成假的：网络层由 ``zhuyun-api-test`` 那套工具对着真
环境验证，这里只管拿到数据之后的决策。

安全阀
------

只有当 ``plone.api`` / ``Zope2`` 等**尚未被 import** 时才会安装这些桩。装了
Plone 的解释器本身没问题（buildout 那个解释器就是这样，也正是推荐用它跑的原因）；
真正危险的是在**已经有人在用** ``plone.api`` 的进程里把它换掉 —— 比如
``bin/instance run`` 或正在服务的实例。检测到那种情况就直接跳过。
"""

import imp
import json
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))

#: 真实模块，由 :func:`_install_stubs` 填上
users = None
sync = None
storage = None
reauth = None
client = None
FakeClient = None

#: 宿主上不一定有 zope.interface（比如裸的 Python 2.7）。有就用真的。
try:
    import zope.interface as _zope_interface
except ImportError:
    _zope_interface = None

#: 桩装过没有。必须记一笔：装完之后 sys.modules 里就有 plone.api 和
#: maitux.oauth2.users 了，正是 :func:`_zope_is_live` 用来判断「Zope 活着」的
#: 标志物 —— 不记的话，第二次检查会把自己装的桩当成真环境而跳过全部测试。
_STUBS_INSTALLED = False


#: Having Plone importable proves nothing -- the buildout's own interpreter has
#: it, and running the file with that interpreter is exactly the intended use.
#: What must never happen is swapping plone.api out from under code that is
#: already using it, i.e. inside `bin/instance run` or a live instance.  That
#: shows up as the real modules being *imported*, not merely importable.
_LIVE_ZOPE_MARKERS = ("plone.api", "Products.CMFPlone", "Zope2",
                      "maitux.oauth2.users")


def _zope_is_live():
    return [name for name in _LIVE_ZOPE_MARKERS if name in sys.modules]


# ---------------------------------------------------------------------------
# 假世界
# ---------------------------------------------------------------------------

class Group(object):
    def __init__(self, gid, roles=()):
        self.id = gid
        self.members = set()
        self.roles = set(roles)

    def getId(self):
        return self.id


class Member(object):
    def __init__(self, uid, props=None, roles=()):
        self.id = uid
        self.props = dict(props or {})
        self.direct_roles = set(roles) | set(["Member", "Authenticated"])

    def getId(self):
        return self.id

    def getProperty(self, name, default=None):
        return self.props.get(name, default)

    def setMemberProperties(self, mapping):
        self.props.update(mapping)

    def getRoles(self):
        """Direct roles plus whatever the member's groups grant."""
        roles = set(self.direct_roles)
        for group in WORLD.groups.values():
            if self.id in group.members:
                roles |= group.roles
        return sorted(roles)


class World(object):
    """Stands in for the bits of a Plone site the sync touches."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.members = {}
        self.groups = {}
        self.passwords = {}

    def add_member(self, uid, props=None, roles=(), groups=()):
        self.members[uid] = Member(uid, props, roles)
        self.passwords[uid] = u"original"
        for gid in groups:
            self.groups.setdefault(gid, Group(gid)).members.add(uid)
        return self.members[uid]

    def add_group(self, gid, roles=()):
        self.groups[gid] = Group(gid, roles)
        return self.groups[gid]

    def groups_of(self, uid):
        return sorted(g.id for g in self.groups.values() if uid in g.members)


WORLD = World()
SETTINGS = {}
PORTAL = object()


# ---------------------------------------------------------------------------
# 假 plone.api / CMFCore
# ---------------------------------------------------------------------------

class _AdoptRoles(object):
    def __init__(self, roles):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Env(object):
    adopt_roles = staticmethod(lambda roles: _AdoptRoles(roles))


class _UserApi(object):
    @staticmethod
    def create(username=None, email=None, password=None, roles=(),
               properties=None):
        props = dict(properties or {})
        props.setdefault("email", email)
        return WORLD.add_member(username, props, roles)


class _GroupApi(object):
    @staticmethod
    def get(groupname=None):
        return WORLD.groups.get(groupname)

    @staticmethod
    def create(groupname=None, title=None, description=None, roles=()):
        return WORLD.add_group(groupname, roles)

    @staticmethod
    def add_user(groupname=None, username=None):
        WORLD.groups[groupname].members.add(username)

    @staticmethod
    def remove_user(groupname=None, username=None):
        WORLD.groups[groupname].members.discard(username)

    @staticmethod
    def get_groups(username=None):
        return [g for g in WORLD.groups.values() if username in g.members]


class _PortalApi(object):
    @staticmethod
    def get():
        return PORTAL


class _CurrentUser(object):
    """谁登录着 —— 由测试直接设置。"""

    userid = None


class FakeApi(object):
    env = _Env()
    user = _UserApi()
    group = _GroupApi()
    portal = _PortalApi()


def _get_current():
    if _CurrentUser.userid is None:
        return None
    return WORLD.members.get(_CurrentUser.userid)


_UserApi.get_current = staticmethod(_get_current)


class FakeTransport(object):
    """顶替 httputils.request_json，记下发出去的请求，回放预设的响应。

    只换掉最外面那一层网络调用，``client.py`` 里拼请求头、拼 body、解析错误码
    的代码都跑真的 —— 「设备信息请求头有没有带全」这种事只有这样才测得到。
    """

    def __init__(self):
        self.calls = []
        self.reply = (200, {})

    def __call__(self, url, method="GET", form=None, json_body=None,
                 headers=None, **kwargs):
        self.calls.append({
            "url": url,
            "method": method,
            "form": form,
            "json": json_body,
            "headers": dict(headers or {}),
        })
        if callable(self.reply):
            return self.reply(self.calls[-1])
        return self.reply

    @property
    def last(self):
        return self.calls[-1] if self.calls else None


class _Membership(object):
    def getMemberById(self, uid):
        return WORLD.members.get(uid)


class _SourceUsers(object):
    def getUserById(self, uid):
        return WORLD.members.get(uid)

    def doChangeUser(self, uid, password):
        WORLD.passwords[uid] = password


class _AclUsers(object):
    source_users = _SourceUsers()


def _get_tool_by_name(context, name, default=None):
    if name == "portal_membership":
        return _Membership()
    if name == "acl_users":
        return _AclUsers()
    return default


class _SilentLogger(object):
    """The code under test logs a lot; none of it belongs in test output."""

    def info(self, msg, *a, **k):
        pass

    warning = error = debug = info


# ---------------------------------------------------------------------------
# 装桩 + 加载真实模块
# ---------------------------------------------------------------------------

def _install_zope_interface():
    u"""没有真的就造一个够用的 —— ``implementer`` 在这里只是个记号。"""
    if _zope_interface is not None:
        from zope.interface.interface import InterfaceClass
        return InterfaceClass("IReAuthenticationProvider")

    interface_mod = types.ModuleType("zope.interface")
    interface_mod.implementer = lambda *ifaces: (lambda cls: cls)
    interface_mod.Interface = object
    zope_pkg = sys.modules.get("zope") or types.ModuleType("zope")
    zope_pkg.interface = interface_mod
    sys.modules["zope"] = zope_pkg
    sys.modules["zope.interface"] = interface_mod
    return object


def _install_stubs():
    global users, sync, storage, reauth, client, FakeClient, _STUBS_INSTALLED
    if _STUBS_INSTALLED:
        return
    _STUBS_INSTALLED = True

    plone_pkg = types.ModuleType("plone")
    plone_pkg.api = FakeApi
    sys.modules["plone"] = plone_pkg
    sys.modules["plone.api"] = FakeApi

    utils = types.ModuleType("Products.CMFCore.utils")
    utils.getToolByName = _get_tool_by_name
    sys.modules["Products"] = types.ModuleType("Products")
    sys.modules["Products.CMFCore"] = types.ModuleType("Products.CMFCore")
    sys.modules["Products.CMFCore.utils"] = utils

    maitux = types.ModuleType("maitux")
    oauth2 = types.ModuleType("maitux.oauth2")
    oauth2.logger = _SilentLogger()
    oauth2.safe_text = lambda v: u"%s" % v
    maitux.oauth2 = oauth2
    sys.modules["maitux"] = maitux
    sys.modules["maitux.oauth2"] = oauth2

    _marker = object()
    cfg = types.ModuleType("maitux.oauth2.config")

    def _get(name, default=_marker):
        if name in SETTINGS:
            return SETTINGS[name]
        return None if default is _marker else default

    cfg.get = _get
    cfg.is_enabled = lambda: bool(SETTINGS.get("enabled", True))
    cfg.set_value = lambda name, value: SETTINGS.__setitem__(name, value)

    def _base_url():
        url = (SETTINGS.get("provider_url") or u"").strip()
        if url and "://" not in url:
            url = u"https://" + url
        return url.rstrip("/")

    def _endpoint(name):
        path = (_get(name) or u"").strip()
        if not path:
            return u""
        if "://" in path:
            return path
        if not path.startswith("/"):
            path = u"/" + path
        return _base_url() + path

    cfg.base_url = _base_url
    cfg.endpoint = _endpoint
    sys.modules["maitux.oauth2.config"] = cfg
    oauth2.config = cfg

    store = types.ModuleType("maitux.oauth2.storage")
    store.MAP = {}
    store.get_userid = lambda portal, subject: store.MAP.get(subject)
    store.set_userid = lambda portal, subject, uid: store.MAP.__setitem__(
        subject, uid)
    store.forget = lambda portal, subject: store.MAP.pop(subject, None)
    store.items = lambda portal: sorted(store.MAP.items())
    sys.modules["maitux.oauth2.storage"] = store
    oauth2.storage = store
    storage = store

    users = imp.load_source("maitux.oauth2.users", os.path.join(HERE, "users.py"))
    oauth2.users = users

    # httputils 和 client 只依赖标准库和 six，可以加载真的。网络那一层
    # (request_json) 由每个测试自己换掉，见 :class:`FakeTransport`。
    httputils = imp.load_source("maitux.oauth2.httputils",
                                os.path.join(HERE, "httputils.py"))
    oauth2.httputils = httputils
    client = imp.load_source("maitux.oauth2.client", os.path.join(HERE, "client.py"))
    oauth2.client = client

    # 同步那部分不关心 HTTP，给它一个纯数据的替身。sync.py 在 import 时就把
    # BCastleClient 绑进了自己的全局名字空间，所以这里替换它自己的引用。
    class _FakeClient(object):
        accounts = []
        directory = {}

        def eiam_token(self):
            return u"token"

        def iter_app_accounts(self, token=None):
            for account in _FakeClient.accounts:
                yield account

        def get_user_by_username(self, name, token=None):
            return _FakeClient.directory.get(name)

    FakeClient = _FakeClient

    sync = imp.load_source("maitux.oauth2.sync", os.path.join(HERE, "sync.py"))
    sync.BCastleClient = _FakeClient

    # 电子签名的二次验证 provider。它在 import 时就要拿到 maitux.esignature 的
    # 契约接口，所以那个包也得先顶上；真装了 esignature 的环境里用真的。
    iface = _install_zope_interface()
    if "maitux.esignature.interfaces" not in sys.modules:
        esig = types.ModuleType("maitux.esignature")
        esig_interfaces = types.ModuleType("maitux.esignature.interfaces")
        esig_interfaces.IReAuthenticationProvider = iface
        esig.interfaces = esig_interfaces
        sys.modules["maitux.esignature"] = esig
        sys.modules["maitux.esignature.interfaces"] = esig_interfaces

    reauth = imp.load_source("maitux.oauth2.reauth",
                             os.path.join(HERE, "reauth.py"))


def setUpModule():
    live = [] if _STUBS_INSTALLED else _zope_is_live()
    if live:
        raise unittest.SkipTest(
            "%s already imported -- this process is running Zope. These tests "
            "replace plone.api with fakes and would corrupt a live site; run "
            "the file standalone instead." % ", ".join(live))
    _install_stubs()


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS = {
    "enabled": True,
    "sync_enabled": True,
    "sync_create_missing": True,
    "sync_deactivate_missing": True,
    "sync_max_missing_percent": 50,
    "sync_update_properties": True,
    "sync_user_id_field": u"external_id,user_id",
    "sync_protected_users": [],
    "auto_create_user": True,
    "auto_activate": False,
    "link_existing_by_username": True,
    "pending_group": u"sso-pending",
    "default_groups": [],
    "create_labcontact": False,
    "username_prefix": u"",
    "fallback_email_domain": u"sso.local",
}


def person(user_name, external_id, disabled=False, locked=False,
           account_disabled=False, name=None, email=None):
    u"""一个人的两面：应用授权名单里的一行 + 用户目录里的档案。"""
    account = {"account_name": user_name, "name": name or user_name,
               "disabled": account_disabled, "account_type": "BASIC_ACCOUNT"}
    record = {"user_name": user_name, "external_id": external_id,
              "user_id": u"UID-" + external_id, "name": name or user_name,
              "email": email or (user_name + u"@example.com"),
              "disabled": disabled, "locked": locked}
    return account, record


class SyncTestCase(unittest.TestCase):

    def setUp(self):
        WORLD.reset()
        storage.MAP.clear()
        SETTINGS.clear()
        SETTINGS.update(DEFAULT_SETTINGS)
        FakeClient.accounts = []
        FakeClient.directory = {}

    def roster(self, *people, **kw):
        u"""把若干 :func:`person` 的结果装进竹云侧。"""
        FakeClient.accounts = [a for a, _ in people]
        FakeClient.directory = dict((r["user_name"], r) for _, r in people)
        if kw.get("drop_from_directory"):
            for name in kw["drop_from_directory"]:
                FakeClient.directory.pop(name, None)

    def authorise_only(self, *user_names):
        u"""缩小授权名单，模拟 IT 收回权限或人员离职。"""
        FakeClient.accounts = [a for a in FakeClient.accounts
                               if a["account_name"] in user_names]

    def run_sync(self, dry_run=False):
        return sync.sync_users(PORTAL, dry_run=dry_run)

    def prop(self, userid, name, default=None):
        return WORLD.members[userid].props.get(name, default)


# ---------------------------------------------------------------------------
# 建号
# ---------------------------------------------------------------------------

class ProvisioningTests(SyncTestCase):

    def test_creates_an_account_for_every_authorised_person(self):
        self.roster(person(u"mengc", u"602908626"),
                    person(u"duj2", u"644874618"))
        stats = self.run_sync()

        self.assertEqual(stats["remote_total"], 2)
        self.assertEqual(stats["created"], 2)
        self.assertEqual(sorted(WORLD.members), [u"duj2", u"mengc"])
        self.assertEqual(stats["disabled"], 0)

    def test_new_accounts_land_in_the_pending_group_with_no_roles(self):
        u"""提前建号不能顺手发权限 —— 等管理员分配。"""
        self.roster(person(u"mengc", u"602908626"))
        self.run_sync()

        self.assertEqual(WORLD.groups_of(u"mengc"), [u"sso-pending"])
        self.assertEqual(WORLD.members[u"mengc"].getRoles(),
                         ["Authenticated", "Member"])

    def test_identity_and_mail_come_from_the_directory(self):
        self.roster(person(u"mengc", u"602908626", email=u"m@innocare.com"))
        self.run_sync()

        self.assertEqual(sorted(storage.MAP), [u"602908626"])
        self.assertEqual(self.prop(u"mengc", "email"), u"m@innocare.com")

    def test_running_twice_changes_nothing(self):
        self.roster(person(u"mengc", u"602908626"))
        self.run_sync()
        stats = self.run_sync()

        self.assertEqual(stats["created"], 0)
        self.assertEqual(stats["disabled"], 0)
        self.assertEqual(stats["reenabled"], 0)

    def test_people_blocked_in_the_idp_get_no_account(self):
        u"""竹云说这人停用/锁定，就别建了 —— 建出来也是当场停用。"""
        self.roster(person(u"a1", u"1", disabled=True),
                    person(u"a2", u"2", locked=True),
                    person(u"a3", u"3", account_disabled=True),
                    person(u"a4", u"4"))
        stats = self.run_sync()

        self.assertEqual(stats["created"], 1)
        self.assertEqual(sorted(WORLD.members), [u"a4"])

    def test_provisioning_can_be_switched_off(self):
        SETTINGS["sync_create_missing"] = False
        self.roster(person(u"mengc", u"602908626"))
        stats = self.run_sync()

        self.assertEqual(stats["created"], 0)
        self.assertEqual(WORLD.members, {})


# ---------------------------------------------------------------------------
# 停用 / 恢复
# ---------------------------------------------------------------------------

class LifecycleTests(SyncTestCase):

    def test_leaver_is_disabled_and_stripped(self):
        self.roster(person(u"mengc", u"1"), person(u"duj2", u"2"))
        self.run_sync()
        WORLD.add_group(u"LabManagers").members.add(u"mengc")

        self.authorise_only(u"duj2")
        stats = self.run_sync()

        self.assertEqual(stats["missing"], 1)
        self.assertEqual(stats["disabled"], 1)
        self.assertTrue(self.prop(u"mengc", users.PROP_DISABLED))
        self.assertEqual(WORLD.groups_of(u"mengc"), [])
        self.assertNotEqual(WORLD.passwords[u"mengc"], u"original")

    def test_the_groups_taken_away_are_remembered(self):
        self.roster(person(u"mengc", u"1"), person(u"duj2", u"2"))
        self.run_sync()
        WORLD.add_group(u"LabManagers").members.add(u"mengc")

        self.authorise_only(u"duj2")
        self.run_sync()

        self.assertEqual(self.prop(u"mengc", users.PROP_REVOKED_GROUPS),
                         u"LabManagers,sso-pending")

    def test_coming_back_restores_the_groups(self):
        u"""只清停用标记是不够的：那等于「能登录但什么都干不了」。"""
        self.roster(person(u"mengc", u"1"), person(u"duj2", u"2"))
        self.run_sync()
        WORLD.add_group(u"LabManagers").members.add(u"mengc")
        self.authorise_only(u"duj2")
        self.run_sync()

        self.roster(person(u"mengc", u"1"), person(u"duj2", u"2"))
        stats = self.run_sync()

        self.assertEqual(stats["reenabled"], 1)
        self.assertFalse(self.prop(u"mengc", users.PROP_DISABLED))
        self.assertEqual(WORLD.groups_of(u"mengc"),
                         [u"LabManagers", u"sso-pending"])
        self.assertEqual(self.prop(u"mengc", users.PROP_REVOKED_GROUPS), u"")

    def test_disabling_twice_does_not_forget_the_original_groups(self):
        u"""第二次停用时用户组已经是空的，别把记录覆盖掉。"""
        self.roster(person(u"mengc", u"1"), person(u"duj2", u"2"))
        self.run_sync()
        WORLD.add_group(u"LabManagers").members.add(u"mengc")
        self.authorise_only(u"duj2")
        self.run_sync()
        self.run_sync()

        self.assertEqual(self.prop(u"mengc", users.PROP_REVOKED_GROUPS),
                         u"LabManagers,sso-pending")

    def test_a_deleted_group_is_reported_not_recreated(self):
        u"""管理员删掉的组不能凭空造回来 —— 那是在乱发权限。"""
        self.roster(person(u"mengc", u"1"), person(u"duj2", u"2"))
        self.run_sync()
        WORLD.add_group(u"LabManagers").members.add(u"mengc")
        self.authorise_only(u"duj2")
        self.run_sync()
        del WORLD.groups[u"LabManagers"]

        self.roster(person(u"mengc", u"1"), person(u"duj2", u"2"))
        self.run_sync()

        self.assertEqual(WORLD.groups_of(u"mengc"), [u"sso-pending"])

    def test_idp_disabled_flag_disables_locally(self):
        self.roster(person(u"mengc", u"1"), person(u"duj2", u"2"))
        self.run_sync()

        self.roster(person(u"mengc", u"1", disabled=True),
                    person(u"duj2", u"2"))
        stats = self.run_sync()

        self.assertEqual(stats["disabled"], 1)
        self.assertTrue(self.prop(u"mengc", users.PROP_DISABLED))


# ---------------------------------------------------------------------------
# 管理员保护
# ---------------------------------------------------------------------------

class AdminProtectionTests(SyncTestCase):
    u"""竹云的授权名单是给实验室人员的，管理员通常不在上面。

    照着名单停用，第一晚就会把管理员自己锁在门外 —— 而且用户组全被摘掉之后，
    网页上就没人能改回来了。
    """

    def _admin(self, uid=u"limsadmin", roles=("Manager",), groups=(),
               subject=u"ADMIN-1"):
        WORLD.add_member(uid, {users.PROP_SUBJECT: subject},
                         roles=roles, groups=groups)
        storage.MAP[subject] = uid
        return uid

    def test_manager_is_never_disabled(self):
        self.roster(person(u"duj2", u"2"))
        self._admin(groups=[u"Administrators"])
        stats = self.run_sync()

        self.assertEqual(stats["protected"], 1)
        self.assertEqual(stats["missing"], 0)
        self.assertFalse(self.prop(u"limsadmin", users.PROP_DISABLED, False))
        self.assertEqual(WORLD.groups_of(u"limsadmin"), [u"Administrators"])

    def test_an_admin_disabled_by_an_earlier_run_is_repaired(self):
        self.roster(person(u"duj2", u"2"))
        self._admin()
        WORLD.members[u"limsadmin"].props[users.PROP_DISABLED] = True
        self.run_sync()

        self.assertFalse(self.prop(u"limsadmin", users.PROP_DISABLED))

    def test_a_role_inherited_from_a_group_also_protects(self):
        self.roster(person(u"duj2", u"2"))
        WORLD.add_group(u"SiteOps", roles=["Site Administrator"])
        self._admin(uid=u"opsuser", roles=(), groups=[u"SiteOps"],
                    subject=u"OPS-1")
        stats = self.run_sync()

        self.assertEqual(stats["protected"], 1)
        self.assertFalse(self.prop(u"opsuser", users.PROP_DISABLED, False))

    def test_explicitly_listed_accounts_are_protected(self):
        u"""给服务账号，以及停用后角色会跟着丢失的人留的后路。"""
        SETTINGS["sync_protected_users"] = [u"svc-robot"]
        self.roster(person(u"duj2", u"2"))
        self._admin(uid=u"svc-robot", roles=(), subject=u"SVC-1")
        stats = self.run_sync()

        self.assertEqual(stats["protected"], 1)
        self.assertFalse(self.prop(u"svc-robot", users.PROP_DISABLED, False))

    def test_disable_user_refuses_directly(self):
        u"""保护写在 users.disable_user 里，不是只在 sync 里绕过。"""
        self._admin()
        changed = users.disable_user(PORTAL, u"limsadmin", u"任何理由", u"now")

        self.assertFalse(changed)
        self.assertFalse(self.prop(u"limsadmin", users.PROP_DISABLED, False))


# ---------------------------------------------------------------------------
# 安全保护
# ---------------------------------------------------------------------------

class CircuitBreakerTests(SyncTestCase):
    u"""本地存的唯一 ID 一旦和竹云对不上，每个账号看起来都像离职的。

    朴素的规则会在一晚上把整个用户库停掉，所以缺失比例不合理时必须罢工。
    """

    def _populate(self, count=8):
        people = [person(u"u%d" % i, u"%d" % i) for i in range(count)]
        self.roster(*people)
        self.run_sync()
        return people

    def test_an_empty_authorisation_list_aborts_deactivation(self):
        self._populate()
        FakeClient.accounts = []
        stats = self.run_sync()

        self.assertTrue(stats["aborted_deactivation"])
        self.assertEqual(stats["disabled"], 0)
        self.assertTrue(stats["errors"])

    def test_too_many_missing_aborts_deactivation(self):
        people = self._populate()
        self.authorise_only(people[0][0]["account_name"])
        stats = self.run_sync()

        self.assertTrue(stats["aborted_deactivation"])
        self.assertEqual(stats["disabled"], 0)

    def test_a_handful_of_leavers_still_goes_through(self):
        u"""8 个人里走 2 个是正常人事变动，不该触发保险。"""
        people = self._populate()
        self.authorise_only(*[p[0]["account_name"] for p in people[:6]])
        stats = self.run_sync()

        self.assertEqual(stats["disabled"], 2)
        self.assertFalse(stats["aborted_deactivation"])

    def test_deactivation_can_be_switched_off(self):
        people = self._populate()
        SETTINGS["sync_deactivate_missing"] = False
        self.authorise_only(*[p[0]["account_name"] for p in people[:6]])
        stats = self.run_sync()

        self.assertEqual(stats["missing"], 2)
        self.assertEqual(stats["disabled"], 0)


# ---------------------------------------------------------------------------
# 报告与边界
# ---------------------------------------------------------------------------

class ReportTests(SyncTestCase):

    def test_dry_run_writes_nothing(self):
        self.roster(person(u"newbie", u"99"))
        stats = self.run_sync(dry_run=True)

        self.assertEqual(stats["created"], 1)
        self.assertEqual(WORLD.members, {})
        self.assertTrue(stats["dry_run"])

    def test_a_person_missing_from_the_directory_is_reported_not_fatal(self):
        u"""在授权名单里但目录查不到 = 应用账号没清理干净的离职者。"""
        self.roster(person(u"ghost", u"7"), person(u"real", u"8"),
                    drop_from_directory=[u"ghost"])
        stats = self.run_sync()

        self.assertEqual(stats["accounts_total"], 2)
        self.assertEqual(stats["remote_total"], 1)
        self.assertEqual(len(stats["errors"]), 1)
        self.assertEqual(sorted(WORLD.members), [u"real"])

    def test_there_is_no_counter_called_enabled(self):
        u"""配置项里已经有个 enabled（总开关），同名计数没人分得清。"""
        self.roster(person(u"mengc", u"1"))
        stats = self.run_sync()

        self.assertNotIn("enabled", stats)
        self.assertIn("reenabled", stats)

    def test_unmatched_sample_carries_ids_not_personal_data(self):
        self.roster(person(u"mengc", u"1"), person(u"duj2", u"2"))
        self.run_sync()
        self.authorise_only(u"duj2")
        stats = self.run_sync()

        self.assertEqual(stats["unmatched_sample"], [u"1"])

    def test_a_stale_mapping_is_dropped(self):
        u"""映射还在、成员已经被手工删掉：忘掉它，别当成离职者。"""
        storage.MAP[u"GONE"] = u"ghost-member"
        self.roster(person(u"duj2", u"2"))
        stats = self.run_sync()

        self.assertNotIn(u"GONE", storage.MAP)
        self.assertEqual(stats["missing"], 0)

    def test_the_master_switch_stops_everything(self):
        SETTINGS["enabled"] = False
        self.roster(person(u"mengc", u"1"))
        stats = self.run_sync()

        self.assertEqual(stats["created"], 0)
        self.assertEqual(WORLD.members, {})
        self.assertTrue(stats["errors"])


# ---------------------------------------------------------------------------
# 电子签名二次验证
# ---------------------------------------------------------------------------

def id_token_for(user_name):
    u"""造一个竹云那样的 id_token：身份埋在 payload.api 里，要解两层。"""
    import base64
    inner = json.dumps({"name": u"x", "mobile": u"", "id": u"UID",
                        "userName": user_name, "email": u"x@example.com"})
    payload = json.dumps({"iss": u"Issuer", "api": inner})
    encoded = base64.urlsafe_b64encode(payload.encode("utf-8")).rstrip(b"=")
    return u"header." + encoded.decode("ascii") + u".signature"


class ReAuthTestCase(unittest.TestCase):

    def setUp(self):
        WORLD.reset()
        storage.MAP.clear()
        SETTINGS.clear()
        SETTINGS.update(DEFAULT_SETTINGS)
        SETTINGS.update({
            "provider_url": u"https://passport.example.com",
            "sdk_login_path": u"/api/v2/sdk/login",
            "client_id": u"CLIENT",
            "client_secret": u"SECRET",
            "sdk_device_fingerprint": u"fp",
            "sdk_os_version": u"linux",
            "sdk_user_agent": u"MaituxLIMS",
            "esign_max_attempts": 3,
            "esign_cooldown_seconds": 60,
            "esign_min_remaining_attempts": 3,
            "request_timeout": 15,
            "verify_ssl": True,
            "use_system_proxy": False,
        })
        reauth._FAILURES.clear()

        self.transport = FakeTransport()
        client.request_json = self.transport

        WORLD.add_member(u"mengc", {users.PROP_USERNAME: u"mengc"})
        _CurrentUser.userid = u"mengc"
        self.provider = reauth.BCastleReAuthenticationProvider()

    def tearDown(self):
        _CurrentUser.userid = None

    def reply_ok(self, user_name=u"mengc", status=u"SUCCESS"):
        self.transport.reply = (200, {"status": status,
                                      "session_token": u"s",
                                      "expire": 604800,
                                      "id_token": id_token_for(user_name)})

    def reply_error(self, code, message):
        self.transport.reply = (400, {"error_code": code, "error_msg": message})

    def verify(self, password=u"pw", user_id=u"mengc"):
        return self.provider.authenticate_current_user(user_id, password)


class PasswordCheckTests(ReAuthTestCase):

    def test_a_correct_password_authenticates(self):
        self.reply_ok()
        result = self.verify()

        self.assertTrue(result["authenticated"])
        self.assertEqual(result["backend_id"], "bccastle")
        self.assertIsNone(result["failure_reason"])

    def test_a_password_about_to_expire_still_signs(self):
        u"""快过期不是错密码，拦下来只会耽误工作。"""
        self.reply_ok(status=u"PASSWORD_WARN")
        self.assertTrue(self.verify()["authenticated"])

    def test_an_expired_password_does_not_sign(self):
        self.reply_ok(status=u"PASSWORD_EXPIRED")
        result = self.verify()

        self.assertFalse(result["authenticated"])
        self.assertIn(u"已过期", result["failure_reason"])

    def test_mfa_and_access_denied_do_not_sign(self):
        for status in (u"MFA_AUTH", u"ACCESS_DENIED"):
            self.reply_ok(status=status)
            reauth._FAILURES.clear()
            self.assertFalse(self.verify()["authenticated"], status)

    def test_an_unknown_status_is_refused_not_accepted(self):
        u"""没见过的状态一律当失败 —— 签名这种事不能猜。"""
        self.reply_ok(status=u"SOMETHING_NEW")
        self.assertFalse(self.verify()["authenticated"])

    def test_a_wrong_password_fails(self):
        self.reply_error(u"SDK.LOGIN.1005", u"无效的用户名或密码。 剩余登录尝试次数:8")
        result = self.verify()

        self.assertFalse(result["authenticated"])
        self.assertIn(u"密码错误", result["failure_reason"])

    def test_an_empty_password_never_reaches_the_idp(self):
        result = self.verify(password=u"")

        self.assertFalse(result["authenticated"])
        self.assertEqual(self.transport.calls, [])

    def test_the_request_carries_every_mandatory_header(self):
        u"""少一个设备头，竹云就回 SDK.COMMON.1003，实测过。"""
        self.reply_ok()
        self.verify()

        sent = self.transport.last
        self.assertEqual(sent["url"],
                         u"https://passport.example.com/api/v2/sdk/login")
        self.assertEqual(sent["method"], "POST")
        for header in ("X-client-id", "X-device-fingerprint",
                       "X-operating-sys-version", "X-agent"):
            self.assertIn(header, sent["headers"])
        self.assertEqual(sent["headers"]["X-client-id"], u"CLIENT")

    def test_the_password_goes_in_the_json_body_not_the_url(self):
        self.reply_ok()
        self.verify(password=u"hunter2")

        sent = self.transport.last
        self.assertEqual(sent["json"], {"user_name": u"mengc",
                                        "password": u"hunter2"})
        self.assertNotIn(u"hunter2", sent["url"])

    def test_a_network_failure_is_not_reported_as_a_wrong_password(self):
        u"""不然用户会去找一个其实没错的密码。"""
        def explode(call):
            raise client.HttpError(u"连不上")
        self.transport.reply = explode
        result = self.verify()

        self.assertFalse(result["authenticated"])
        self.assertIn(u"无法连接", result["failure_reason"])
        self.assertNotIn(u"密码错误", result["failure_reason"])

    def test_a_locked_account_says_so(self):
        self.reply_error(u"SDK.LOGIN.1003", u"用户已被锁定")
        result = self.verify()

        self.assertIn(u"锁定", result["failure_reason"])


class SignerIdentityTests(ReAuthTestCase):

    def test_the_session_user_must_match_for_a_single_signature(self):
        _CurrentUser.userid = u"someone-else"
        result = self.verify()

        self.assertFalse(result["authenticated"])
        self.assertEqual(self.transport.calls, [])

    def test_countersigning_does_not_require_the_session_user(self):
        u"""第二复核人本来就不是当前登录的人。"""
        WORLD.add_member(u"duj2", {users.PROP_USERNAME: u"duj2"})
        self.reply_ok(user_name=u"duj2")
        result = self.provider.authenticate_user(u"duj2", u"pw")

        self.assertTrue(result["authenticated"])

    def test_an_identity_mismatch_in_the_reply_is_refused(self):
        u"""竹云说认证通过的是另一个人 —— 签名归错人是审计追溯最致命的错。"""
        self.reply_ok(user_name=u"somebody-else")
        result = self.verify()

        self.assertFalse(result["authenticated"])
        self.assertIn(u"身份", result["failure_reason"])

    def test_the_idp_login_name_is_used_not_the_local_user_id(self):
        SETTINGS["username_prefix"] = u"sso_"
        WORLD.add_member(u"sso_zhangs", {users.PROP_USERNAME: u"zhangs"})
        _CurrentUser.userid = u"sso_zhangs"
        self.reply_ok(user_name=u"zhangs")

        result = self.provider.authenticate_current_user(u"sso_zhangs", u"pw")

        self.assertTrue(result["authenticated"])
        self.assertEqual(self.transport.last["json"]["user_name"], u"zhangs")

    def test_an_old_account_falls_back_to_stripping_the_prefix(self):
        u"""属性是后加的，老账号上没有。"""
        SETTINGS["username_prefix"] = u"sso_"
        WORLD.add_member(u"sso_legacy", {})
        _CurrentUser.userid = u"sso_legacy"
        self.reply_ok(user_name=u"legacy")

        self.provider.authenticate_current_user(u"sso_legacy", u"pw")

        self.assertEqual(self.transport.last["json"]["user_name"], u"legacy")


class LockoutProtectionTests(ReAuthTestCase):
    u"""竹云是公司统一登录：锁了账号，人连邮箱和 OA 都进不去。

    签名是高频操作，手滑很正常，所以 LIMS 必须比竹云先一步停下来。
    """

    def test_the_remaining_count_reaches_the_signer(self):
        self.reply_error(u"SDK.LOGIN.1005", u"无效的用户名或密码。 剩余登录尝试次数:8")
        reason = self.verify()["failure_reason"]

        self.assertIn(u"8", reason)
        self.assertIn(u"竹云", reason)

    def test_local_throttle_stops_calling_the_idp(self):
        self.reply_error(u"SDK.LOGIN.1005", u"无效的用户名或密码。 剩余登录尝试次数:8")
        for _ in range(3):
            self.verify()
        calls_before = len(self.transport.calls)

        result = self.verify()

        self.assertEqual(len(self.transport.calls), calls_before)
        self.assertIn(u"暂停验证", result["failure_reason"])

    def test_a_low_remaining_count_stops_immediately(self):
        u"""竹云自己报的数字才是权威的，本地计数只是辅助。"""
        self.reply_error(u"SDK.LOGIN.1005", u"无效的用户名或密码。 剩余登录尝试次数:2")
        result = self.verify()

        self.assertIn(u"仅剩 2 次", result["failure_reason"])
        calls_before = len(self.transport.calls)
        self.verify()
        self.assertEqual(len(self.transport.calls), calls_before)

    def test_a_successful_check_clears_the_throttle(self):
        self.reply_error(u"SDK.LOGIN.1005", u"无效的用户名或密码。 剩余登录尝试次数:8")
        self.verify()
        self.verify()
        self.reply_ok()

        self.assertTrue(self.verify()["authenticated"])
        self.assertEqual(reauth.cooldown_remaining(u"mengc"), 0)

    def test_the_throttle_can_be_switched_off(self):
        SETTINGS["esign_max_attempts"] = 0
        SETTINGS["esign_min_remaining_attempts"] = 0
        self.reply_error(u"SDK.LOGIN.1005", u"无效的用户名或密码。 剩余登录尝试次数:8")
        for _ in range(5):
            self.verify()

        self.assertEqual(len(self.transport.calls), 5)

    def test_the_throttle_is_per_person(self):
        WORLD.add_member(u"duj2", {users.PROP_USERNAME: u"duj2"})
        self.reply_error(u"SDK.LOGIN.1005", u"无效的用户名或密码。 剩余登录尝试次数:8")
        for _ in range(3):
            self.verify()

        self.assertTrue(reauth.cooldown_remaining(u"mengc") > 0)
        self.assertEqual(reauth.cooldown_remaining(u"duj2"), 0)


class ReplyParsingTests(unittest.TestCase):

    def test_remaining_attempts_is_read_off_the_message(self):
        self.assertEqual(
            reauth.remaining_attempts(u"无效的用户名或密码。 剩余登录尝试次数:9"), 9)
        self.assertEqual(
            reauth.remaining_attempts(u"Invalid. Remaining attempts:10"), 10)

    def test_a_message_without_a_count_gives_none(self):
        u"""上游改了措辞只会少一句提示，不会算错。"""
        self.assertIsNone(reauth.remaining_attempts(u"用户已被锁定"))
        self.assertIsNone(reauth.remaining_attempts(u""))
        self.assertIsNone(reauth.remaining_attempts(None))

    def test_the_identity_is_dug_out_of_the_two_layer_id_token(self):
        self.assertEqual(reauth.identity_from_id_token(id_token_for(u"louxi")),
                         u"louxi")

    def test_a_broken_id_token_yields_nothing_rather_than_raising(self):
        for bad in (u"", u"not-a-jwt", u"a.b", None):
            self.assertEqual(reauth.identity_from_id_token(bad), u"")


if __name__ == "__main__":
    _live = _zope_is_live()
    if _live:
        sys.stderr.write(
            "%s already imported -- run this standalone, not inside Zope.\n"
            % ", ".join(_live))
        sys.exit(2)
    _install_stubs()
    unittest.main(verbosity=2)
