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
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))

#: 真实模块，由 :func:`_install_stubs` 填上
users = None
sync = None
storage = None
FakeClient = None

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


class FakeApi(object):
    env = _Env()
    user = _UserApi()
    group = _GroupApi()
    portal = _PortalApi()


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

def _install_stubs():
    global users, sync, storage, FakeClient, _STUBS_INSTALLED
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

    client_mod = types.ModuleType("maitux.oauth2.client")

    class _FakeClient(object):
        """竹云 stand-in.  The real HTTP layer is covered by zhuyun-api-test."""

        accounts = []
        directory = {}

        def eiam_token(self):
            return u"token"

        def iter_app_accounts(self, token=None):
            for account in _FakeClient.accounts:
                yield account

        def get_user_by_username(self, name, token=None):
            return _FakeClient.directory.get(name)

    client_mod.BCastleClient = _FakeClient
    sys.modules["maitux.oauth2.client"] = client_mod
    oauth2.client = client_mod
    FakeClient = _FakeClient

    sync = imp.load_source("maitux.oauth2.sync", os.path.join(HERE, "sync.py"))


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


if __name__ == "__main__":
    _live = _zope_is_live()
    if _live:
        sys.stderr.write(
            "%s already imported -- run this standalone, not inside Zope.\n"
            % ", ".join(_live))
        sys.exit(2)
    _install_stubs()
    unittest.main(verbosity=2)
