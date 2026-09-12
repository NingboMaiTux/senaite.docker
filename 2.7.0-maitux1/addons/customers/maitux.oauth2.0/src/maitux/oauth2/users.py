# -*- coding: utf-8 -*-
"""Local account resolution / creation / activation state.

Account states used by this add-on:

``待授权``   created by SSO and never touched by an administrator: no role
             beyond the base Plone ones and no group other than the pending
             group.  Login is refused with the "wait for the administrator"
             page.
``已授权``   an administrator granted any LIMS role or any real group --
             normal login.
``已停用``   the member property ``maitux_oauth2_disabled`` is True, set by the
             daily sync when 竹云 reports the user as disabled/locked/gone.
"""

import binascii
import os
import re

from Products.CMFCore.utils import getToolByName
from plone import api

from maitux.oauth2 import config
from maitux.oauth2 import logger
from maitux.oauth2 import safe_text
from maitux.oauth2 import storage

PROP_SUBJECT = "maitux_oauth2_subject"
PROP_DISABLED = "maitux_oauth2_disabled"
PROP_DISABLED_REASON = "maitux_oauth2_disabled_reason"
PROP_LAST_SYNC = "maitux_oauth2_last_sync"
PROP_LAST_LOGIN = "maitux_oauth2_last_login"
PROP_REVOKED_GROUPS = "maitux_oauth2_revoked_groups"

MEMBERDATA_PROPERTIES = (
    (PROP_SUBJECT, "string", ""),
    (PROP_DISABLED, "boolean", False),
    (PROP_DISABLED_REASON, "string", ""),
    (PROP_LAST_SYNC, "string", ""),
    (PROP_LAST_LOGIN, "string", ""),
    (PROP_REVOKED_GROUPS, "string", ""),
)

#: Roles every authenticated Plone user carries -- they do not count as
#: "the administrator has granted access".
BASE_ROLES = frozenset(["Member", "Authenticated", "Anonymous"])

#: Roles that mark an account as one that administers this LIMS.
#:
#: The 竹云 authorisation list covers lab staff, so an administrator is
#: routinely absent from it -- ours certainly is.  Disabling accounts on that
#: basis alone would therefore lock the site's own maintainers out on the very
#: first nightly run, and with every group stripped there would be nobody left
#: who could put it right through the web.  So the sync never touches them.
PROTECTED_ROLES = frozenset(["Manager", "Site Administrator"])

_USERNAME_INVALID = re.compile(r"[^a-z0-9._@-]+")


class AccountError(Exception):
    """The account cannot be used for login."""


def normalize_username(raw):
    """Turn a 竹云 login name into something Plone accepts as a user id."""
    value = (raw or u"").strip().lower()
    value = _USERNAME_INVALID.sub(u"-", value).strip(u"-.")
    prefix = (config.get("username_prefix") or u"").strip().lower()
    if prefix:
        value = prefix + value
    return value[:120]


def build_email(username, claimed):
    if claimed:
        return claimed
    domain = (config.get("fallback_email_domain") or u"sso.local").strip().lstrip("@")
    return u"%s@%s" % (username, domain)


def random_password():
    return binascii.hexlify(os.urandom(24)).decode("ascii")


# ---------------------------------------------------------------------------
# member helpers
# ---------------------------------------------------------------------------


def get_member(portal, userid):
    # The SSO callback runs as Anonymous, so member lookups have to adopt a
    # role that is allowed to see other members.
    if not userid:
        return None
    membership = getToolByName(portal, "portal_membership")
    with api.env.adopt_roles(["Manager"]):
        return membership.getMemberById(userid)


def member_property(member, name, default=None):
    if member is None:
        return default
    try:
        value = member.getProperty(name, default)
    except Exception:
        return default
    return default if value is None else value


def set_member_properties(portal, userid, properties):
    """Set member properties -- callers are often anonymous, so adopt Manager."""
    member = get_member(portal, userid)
    if member is None:
        return False
    try:
        with api.env.adopt_roles(["Manager"]):
            member.setMemberProperties(properties)
    except Exception as exc:
        logger.warning("Could not update properties of %s: %s",
                       userid, safe_text(exc))
        return False
    return True


def groups_of(portal, userid):
    try:
        with api.env.adopt_roles(["Manager"]):
            groups = api.group.get_groups(username=userid)
    except Exception:
        return []
    return [group.getId() for group in groups if group is not None]


def is_disabled(member):
    return bool(member_property(member, PROP_DISABLED, False))


def is_protected(portal, userid):
    """True when the daily sync must leave this account alone.

    Covers anyone holding an administrative role (see :data:`PROTECTED_ROLES`)
    plus whatever ``sync_protected_users`` lists -- an escape hatch for service
    accounts and for an administrator who happens to hold no role directly but
    inherits one through a group.
    """
    member = get_member(portal, userid)
    if member is None:
        return False
    try:
        roles = set(member.getRoles() or [])
    except Exception:
        roles = set()
    if roles & PROTECTED_ROLES:
        return True
    protected = [(u"%s" % x).strip()
                 for x in (config.get("sync_protected_users") or [])]
    return userid in protected


def is_pending(portal, member):
    """True while an SSO created account has not been touched by an admin yet.

    Deliberately fails *closed*: an account only stops being pending once the
    administrator has actually granted something -- any role beyond the base
    Plone ones, or membership of any group other than the pending group.  So a
    failed "add to pending group" during creation cannot silently let an
    unauthorised user in.
    """
    if member is None:
        return False
    if config.get("auto_activate"):
        return False
    if not member_property(member, PROP_SUBJECT, u""):
        # Not an SSO managed account -- none of our business.
        return False
    if set(member.getRoles() or []) - BASE_ROLES:
        return False

    ignored = set(["AuthenticatedUsers"])
    pending_group = (config.get("pending_group") or u"").strip()
    if pending_group:
        ignored.add(pending_group)
    if set(groups_of(portal, member.getId())) - ignored:
        return False
    return True


# ---------------------------------------------------------------------------
# resolution / creation
# ---------------------------------------------------------------------------


def resolve_user(portal, subject, username, fullname, email):
    """Find (or create) the local account for a 竹云 identity, at login time.

    Returns the local user id.  Raises :class:`AccountError` when the identity
    cannot be turned into a usable local account.
    """
    return _resolve(portal, subject, username, fullname, email,
                    may_create=bool(config.get("auto_create_user")))[0]


def provision_user(portal, subject, username, fullname, email):
    """Create the local account *before* the person has ever logged in.

    The daily sync calls this for everyone on the 竹云 authorisation list, so an
    administrator can grant LIMS roles up front instead of having to wait for
    each person's first login.  The account is created exactly as a login would
    create it -- 待授权, no roles -- so provisioning grants nobody anything.

    Whether it runs at all is governed by ``sync_create_missing``; the caller
    checks that.  ``auto_create_user`` is deliberately not consulted here: that
    setting is about what an *unknown* person may do at the login screen, which
    is a different question from pre-creating accounts for a list the customer
    has explicitly authorised.

    Returns ``(userid, action)``.  A provisioning pass must never abort because
    one row is odd, so anything :func:`resolve_user` would refuse is logged and
    reported as ``(None, "error")`` instead of raising.
    """
    try:
        return _resolve(portal, subject, username, fullname, email,
                        may_create=True)
    except AccountError as exc:
        logger.warning("Cannot provision %s (subject=%s): %s",
                       username, subject, safe_text(exc))
        return None, "error"


def _resolve(portal, subject, username, fullname, email, may_create):
    """Shared core of :func:`resolve_user` and :func:`provision_user`.

    Returns ``(userid, action)`` where *action* is one of ``existing``,
    ``linked`` or ``created``.
    """
    userid = storage.get_userid(portal, subject)
    if userid and get_member(portal, userid) is not None:
        _touch(portal, userid, subject, fullname, email)
        return userid, "existing"

    if userid:
        # Mapping points at a member that has been deleted in the meantime.
        logger.warning(
            "Dropping stale SSO mapping %s -> %s (member is gone)", subject, userid)
        storage.forget(portal, subject)

    candidate = normalize_username(username) or normalize_username(subject)
    if not candidate:
        raise AccountError(u"竹云未返回可用的用户名")

    existing = get_member(portal, candidate)
    if existing is not None:
        bound = member_property(existing, PROP_SUBJECT, u"")
        if bound and bound != subject:
            # The local name is already taken by a *different* IdP identity.
            # Deliberately refuse instead of inventing a name like "zs2":
            # a silently generated id hides a real data problem and leaves an
            # account nobody can attribute to a person.
            logger.error(
                "Refusing login: local name %s is already bound to IdP identity "
                "%s, cannot use it for %s", candidate, bound, subject)
            raise AccountError(
                u"本地用户名 %s 已经绑定了另一个竹云账号，无法为当前用户创建账号。"
                u"请管理员处理后重试（可重命名本地账号，或在插件配置里调整"
                u"“登录名字段”/“本地用户名前缀”）。" % candidate)
        if config.get("link_existing_by_username"):
            # Not bound to anyone yet: adopt the pre-existing local account
            # (e.g. one that was created by hand before SSO was switched on).
            storage.set_userid(portal, subject, candidate)
            _touch(portal, candidate, subject, fullname, email)
            logger.info("Linked IdP identity %s to existing member %s",
                        subject, candidate)
            return candidate, "linked"
        logger.error(
            "Refusing login: local member %s already exists and "
            "link_existing_by_username is off", candidate)
        raise AccountError(
            u"本地已存在用户名 %s，且未开启“按用户名关联已有账号”，"
            u"无法自动建号。请管理员处理。" % candidate)

    if not may_create:
        raise AccountError(
            u"LIMS 中不存在对应账号，且系统未开启自动建号，请联系管理员。")

    return create_user(portal, subject, candidate, fullname, email), "created"



def create_user(portal, subject, userid, fullname, email):
    """Create the local member and put it in the right group."""
    try:
        with api.env.adopt_roles(["Manager"]):
            api.user.create(
                username=userid,
                email=build_email(userid, email),
                password=random_password(),
                roles=("Member",),
                properties={
                    "fullname": fullname or userid,
                    PROP_SUBJECT: subject,
                    PROP_DISABLED: False,
                },
            )
    except Exception as exc:
        logger.error("Could not create member %s for subject %s: %s",
                     userid, subject, safe_text(exc))
        raise AccountError(u"创建本地账号失败：%s" % safe_text(exc))

    storage.set_userid(portal, subject, userid)

    if config.get("auto_activate"):
        for group in (config.get("default_groups") or []):
            add_to_group(portal, group, userid)
        logger.info(u"Created SSO member %s (subject=%s) as active", userid, subject)
    else:
        pending_group = (config.get("pending_group") or u"").strip()
        if pending_group:
            add_to_group(portal, pending_group, userid, create_missing=True)
        logger.info(u"Created SSO member %s (subject=%s) awaiting authorisation",
                    userid, subject)

    if config.get("create_labcontact"):
        create_labcontact(portal, userid, fullname, email)

    return userid


def _touch(portal, userid, subject, fullname, email):
    """Keep the stored identity in sync with what 竹云 just told us."""
    member = get_member(portal, userid)
    if member is None:
        return
    properties = {}
    if member_property(member, PROP_SUBJECT, u"") != subject:
        properties[PROP_SUBJECT] = subject
    if fullname and member_property(member, "fullname", u"") != fullname:
        properties["fullname"] = fullname
    if email and member_property(member, "email", u"") != email:
        properties["email"] = email
    if properties:
        set_member_properties(portal, userid, properties)


def add_to_group(portal, groupname, userid, create_missing=False):
    """Add *userid* to *groupname*.  Returns whether it worked."""
    groupname = (groupname or u"").strip()
    if not groupname:
        return False
    try:
        with api.env.adopt_roles(["Manager"]):
            group = api.group.get(groupname=groupname)
            if group is None:
                if not create_missing:
                    logger.warning("Group %s does not exist, skipping", groupname)
                    return False
                api.group.create(
                    groupname=groupname,
                    title=u"待授权（统一登录）",
                    description=u"maitux.oauth2 自动创建。组内用户尚未获得 LIMS 权限。",
                    roles=[],
                )
            api.group.add_user(groupname=groupname, username=userid)
    except Exception as exc:
        logger.warning("Could not add %s to group %s: %s",
                       userid, groupname, safe_text(exc))
        return False
    return True


def create_labcontact(portal, userid, fullname, email):
    """Best effort LabContact creation -- never blocks the login."""
    try:
        from bika.lims import api as lims_api
    except ImportError:  # pragma: no cover
        logger.warning("bika.lims.api not importable, skipping LabContact")
        return None

    folder = None
    for path in (("bika_setup", "bika_labcontacts"), ("setup", "labcontacts")):
        obj = portal
        for name in path:
            obj = getattr(obj, name, None)
            if obj is None:
                break
        if obj is not None:
            folder = obj
            break
    if folder is None:
        logger.warning("No LabContacts folder found, skipping LabContact for %s",
                       userid)
        return None

    try:
        with api.env.adopt_roles(["Manager"]):
            for contact in folder.objectValues():
                getter = getattr(contact, "getUsername", None)
                if callable(getter) and getter() == userid:
                    return contact

            parts = (fullname or userid).split(None, 1)
            contact = lims_api.create(
                folder, "LabContact",
                Firstname=parts[0],
                Surname=parts[1] if len(parts) > 1 else u"",
                EmailAddress=email or u"")

            link = getattr(contact, "linkUser", None)
            if callable(link):
                link(userid)
            else:
                setter = getattr(contact, "setUser", None)
                if callable(setter):
                    setter(userid)
            logger.info("Created LabContact for %s", userid)
            return contact
    except Exception as exc:
        logger.warning("Could not create LabContact for %s: %s",
                       userid, safe_text(exc))
        return None


# ---------------------------------------------------------------------------
# enable / disable (used by the daily sync)
# ---------------------------------------------------------------------------


def disable_user(portal, userid, reason, timestamp):
    """Mark a member as disabled and strip everything it could still do.

    Administrators are exempt -- see :func:`is_protected`.
    """
    member = get_member(portal, userid)
    if member is None:
        return False
    if is_protected(portal, userid):
        logger.info(u"Not disabling protected member %s (would have been: %s)",
                    userid, reason)
        return False
    already = is_disabled(member)
    properties = {
        PROP_DISABLED: True,
        PROP_DISABLED_REASON: reason or u"",
        PROP_LAST_SYNC: timestamp,
    }
    if not already:
        # Record what was taken away *on the transition only*.  Disabling an
        # account that is already disabled would otherwise overwrite the real
        # group list with the empty one it has by then, and the user could
        # never be restored to what they had.
        properties[PROP_REVOKED_GROUPS] = u",".join(revoke_access(portal, userid))
    set_member_properties(portal, userid, properties)
    if not already:
        logger.info(u"Disabled SSO member %s (%s)", userid, reason)
    return not already


def enable_user(portal, userid, timestamp):
    """Switch a disabled member back on, groups included.

    Clearing the flag is not enough: :func:`disable_user` removed every group
    the member was in, so without putting those back "re-enabled" would in
    practice mean "can log in and do nothing", and the account would fall back
    to 待授权 as if it were brand new.  The groups taken away are replayed from
    ``PROP_REVOKED_GROUPS``.

    The local password stays as :func:`revoke_access` left it: these accounts
    authenticate through 竹云 and never use it.
    """
    member = get_member(portal, userid)
    if member is None:
        return False
    changed = is_disabled(member)
    if not changed:
        set_member_properties(portal, userid, {PROP_LAST_SYNC: timestamp})
        return False

    # Read before clearing -- set_member_properties writes through to the member.
    revoked = member_property(member, PROP_REVOKED_GROUPS, u"") or u""
    set_member_properties(portal, userid, {
        PROP_LAST_SYNC: timestamp,
        PROP_DISABLED: False,
        PROP_DISABLED_REASON: u"",
        PROP_REVOKED_GROUPS: u"",
    })
    restored, lost = restore_access(portal, userid, revoked)
    if lost:
        logger.warning(
            u"Re-enabled SSO member %s; restored groups: %s; these no longer "
            u"exist and could not be restored: %s",
            userid, u", ".join(restored) or u"(none)", u", ".join(lost))
    else:
        logger.info(u"Re-enabled SSO member %s; restored groups: %s",
                    userid, u", ".join(restored) or u"(none)")
    return True


def revoke_access(portal, userid):
    """Belt and braces: no groups and an unusable password.

    竹云 has no leaver webhook, so once the daily sync notices a leaver we make
    the account inert instead of relying only on the per-request check.

    Returns the group names that were actually removed -- sorted, so the value
    stored on the member reads the same way twice -- so the caller can remember
    them for :func:`restore_access`.
    """
    removed = []
    with api.env.adopt_roles(["Manager"]):
        for groupname in groups_of(portal, userid):
            if groupname in ("AuthenticatedUsers",):
                continue
            try:
                api.group.remove_user(groupname=groupname, username=userid)
                removed.append(groupname)
            except Exception as exc:
                logger.warning("Could not remove %s from %s: %s",
                               userid, groupname, safe_text(exc))
        removed.sort()
        acl_users = getToolByName(portal, "acl_users")
        users_plugin = getattr(acl_users, "source_users", None)
        if users_plugin is not None and users_plugin.getUserById(userid):
            try:
                users_plugin.doChangeUser(userid, random_password())
            except Exception as exc:
                logger.warning("Could not reset password of %s: %s",
                               userid, safe_text(exc))
    return removed


def restore_access(portal, userid, revoked):
    """Put back the groups :func:`revoke_access` removed.

    Returns ``(restored, lost)``.  A group that has been deleted in the
    meantime cannot be restored and is reported rather than recreated: guessing
    at a group an administrator deleted on purpose would hand out permissions
    nobody asked for.
    """
    names = [x.strip() for x in (revoked or u"").replace(u"\n", u",").split(u",")
             if x.strip()]
    restored, lost = [], []
    for name in names:
        if add_to_group(portal, name, userid):
            restored.append(name)
        else:
            lost.append(name)
    return restored, lost
