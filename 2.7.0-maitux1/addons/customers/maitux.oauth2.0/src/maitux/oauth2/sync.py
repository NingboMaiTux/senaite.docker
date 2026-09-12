# -*- coding: utf-8 -*-
"""Daily reconciliation against the 竹云 application authorisation list.

竹云 offers no leaver notification, so once a day we ask it who is currently
entitled to *this application* and bring the local accounts in line.  Two calls,
in this order:

1. ``GET /api/v2/tenant/applications/{app_id}/accounts`` -- the list the
   customer's IT curates.  A few dozen rows carrying no personal data.
2. ``POST /api/v2/tenant/users/user-by-username`` per row -- the directory
   record, which is where ``external_id`` (the identity stored at login) and the
   mail address live.

The tenant-wide user list is deliberately *not* used.  It has no filter beyond
``org_id``, so it answers with every employee on the tenant -- thousands of
records carrying ID card numbers, mobiles and addresses -- to find the few dozen
people who may actually use the LIMS.  Asking per authorised login name keeps
everyone else's data on 竹云's side.

What one pass does:

* on the list, no local account      -> create it (待授权), if enabled
* on the list, local account off     -> switch it back on, groups included
* no longer on the list              -> disable (leaver, or access revoked)
* administrators                     -> never touched, and un-disabled if they
                                        somehow got disabled before
"""

import json
from datetime import datetime

from maitux.oauth2 import config
from maitux.oauth2 import logger
from maitux.oauth2 import safe_text
from maitux.oauth2 import storage
from maitux.oauth2 import users
from maitux.oauth2.client import BCastleClient


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _is_truthy(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return u"%s" % value in (u"1", u"true", u"True", u"yes", u"Y")


def _identity_fields():
    """Directory fields that may hold the identity stored at login."""
    fields = [f.strip() for f in
              (config.get("sync_user_id_field") or u"").replace("\n", ",").split(",")
              if f.strip()]
    return fields or ["external_id", "user_id"]


def _blocked_reason(entry):
    """Why this authorised person must still not get in, or None."""
    record = entry["record"]
    if entry["account_disabled"]:
        return u"竹云已停用该应用账号"
    if _is_truthy(record.get("disabled")):
        return u"竹云已停用"
    if _is_truthy(record.get("locked")):
        return u"竹云已锁定"
    return None


def _fetch_authorised(client, stats):
    """``(index, people)`` for everyone 竹云 authorises for this application.

    *index* maps every identity field of every person to their entry, so a local
    account stores ``external_id`` or ``user_id`` and either one matches.
    """
    fields = _identity_fields()
    index = {}
    people = []
    accounts = 0

    # One EIAM token for the whole pass: it is valid for ~30 minutes and this
    # loop makes one request per authorised person.
    token = client.eiam_token()

    for account in client.iter_app_accounts(token=token):
        accounts += 1
        name = (account.get("account_name") or u"").strip()
        if not name:
            continue

        record = client.get_user_by_username(name, token=token)
        if record is None:
            # Authorised for the app but gone from the directory: a leaver whose
            # app account has not been cleaned up.  Not an error on our side,
            # but worth surfacing -- IT usually wants to tidy it up.
            stats["errors"].append(
                u"竹云授权名单中的 %s 在用户目录里不存在，已跳过。" % name)
            continue

        subject = u""
        for field in fields:
            value = record.get(field)
            if value not in (None, ""):
                subject = u"%s" % value
                break
        if not subject:
            stats["errors"].append(
                u"竹云用户 %s 没有返回 %s 中的任何一个字段，无法比对，已跳过。"
                % (name, u"/".join(fields)))
            continue

        entry = {
            "subject": subject,
            "user_name": name,
            "record": record,
            "account_disabled": _is_truthy(account.get("disabled")),
        }
        people.append(entry)
        for field in fields:
            value = record.get(field)
            if value not in (None, ""):
                index[u"%s" % value] = entry

    stats["accounts_total"] = accounts
    stats["remote_total"] = len(people)
    return index, people


#: A mass deactivation is by definition many accounts; below this the "missing
#: ratio" carries no signal (one genuine leaver out of two users is 50%).
MIN_MISSING_FOR_GUARD = 5


def _check_missing_is_plausible(stats, missing, tracked, remote_count):
    """Circuit breaker for the "not on the list -> disable" rule.

    The identifier stored at login (``userinfo.external_id``) is *assumed* to be
    the same value the directory returns.  If that assumption is ever wrong --
    or if 竹云 answers with a truncated authorisation list -- every local account
    looks like a leaver and the naive rule would disable the entire user base in
    one run.  So refuse to deactivate when an implausible share is missing, and
    say so loudly instead.

    Returns whether deactivating the missing accounts may proceed.
    """
    if not config.get("sync_deactivate_missing"):
        return False
    if not missing:
        return True

    if not remote_count:
        # An empty authorisation list is never a legitimate "everybody left";
        # it means the API answered with nothing useful.  Unconditional stop.
        stats["aborted_deactivation"] = True
        stats["errors"].append(
            u"安全保护已触发：竹云的应用授权名单返回 0 条记录，本次不停用任何账号。"
            u"请检查 AppId 是否正确，以及本应用是否具备 account_read / read 接口权限。")
        logger.error("Aborting deactivation: the app account list came back empty")
        return False

    limit = config.get("sync_max_missing_percent")
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 50
    if limit >= 100:                      # explicitly switched off
        return True

    percent = int(round(100.0 * missing / tracked)) if tracked else 100
    if missing < MIN_MISSING_FOR_GUARD or percent <= limit:
        return True

    stats["aborted_deactivation"] = True
    message = (
        u"安全保护已触发：本地 %s 个统一登录账号中有 %s 个（%s%%）不在竹云的应用"
        u"授权名单里，超过阈值 %s%%，因此本次**不停用任何账号**。"
        u"两种可能：一是登录时存下的唯一 ID 和竹云的 external_id / user_id 不是"
        u"同一个字段，请拿 unmatched_sample 里的值去核对；二是 IT 的授权名单还"
        u"没配全。确认无误后，把“允许缺失比例”调高再跑。"
        % (tracked, missing, percent, limit))
    stats["errors"].append(message)
    logger.error(
        "Aborting deactivation: %s/%s (%s%%) local SSO accounts are not on the "
        "authorisation list, limit is %s%%. Sample of unmatched ids: %s",
        missing, tracked, percent, limit, stats.get("unmatched_sample"))
    return False


def _provision(portal, people, stats, dry_run):
    """Create local accounts for authorised people who do not have one yet."""
    if not config.get("sync_create_missing"):
        return
    for entry in people:
        if _blocked_reason(entry):
            # Creating an account only to disable it in the same pass would
            # just produce noise; it gets created once 竹云 says they are active.
            continue
        userid = storage.get_userid(portal, entry["subject"])
        if userid and users.get_member(portal, userid) is not None:
            continue
        record = entry["record"]
        if dry_run:
            stats["created"] += 1
            continue
        created, action = users.provision_user(
            portal,
            entry["subject"],
            record.get("user_name") or entry["user_name"],
            record.get("name") or u"",
            record.get("email") or u"",
        )
        if action == "created":
            stats["created"] += 1
        elif action == "linked":
            stats["linked"] += 1
        elif created is None:
            stats["errors"].append(
                u"无法为竹云用户 %s 创建 LIMS 账号，详见日志。" % entry["user_name"])


def sync_users(portal, dry_run=False):
    """Run one synchronisation pass.  Returns a stats dict."""
    stats = {
        "started": _now(),
        "finished": None,
        "accounts_total": 0,
        "remote_total": 0,
        "local_total": 0,
        "created": 0,
        "linked": 0,
        "disabled": 0,
        # Deliberately not "enabled": that is also the name of the master
        # switch setting, and a counter sitting next to it in the same report
        # reads as if it were that switch.
        "reenabled": 0,
        "updated": 0,
        "unchanged": 0,
        "missing": 0,
        "protected": 0,
        "unmatched_sample": [],
        "aborted_deactivation": False,
        "errors": [],
        "dry_run": bool(dry_run),
    }

    if not config.is_enabled():
        stats["errors"].append(u"统一登录总开关未启用")
        stats["finished"] = _now()
        return stats
    if not config.get("sync_enabled"):
        stats["errors"].append(u"用户同步未启用")
        stats["finished"] = _now()
        return stats

    try:
        index, people = _fetch_authorised(BCastleClient(), stats)
    except Exception as exc:
        logger.error("Authorisation list sync failed: %s", safe_text(exc))
        stats["errors"].append(u"读取竹云应用授权名单失败：%s" % safe_text(exc))
        stats["finished"] = _now()
        _record(stats)
        return stats

    timestamp = _now()
    update_properties = bool(config.get("sync_update_properties"))

    # -- pass 1: give the authorised people a local account ---------------
    _provision(portal, people, stats, dry_run)

    # -- pass 2: classify everything without writing anything -------------
    mapping = storage.items(portal)
    stats["local_total"] = len(mapping)

    plan = []
    for subject, userid in mapping:
        member = users.get_member(portal, userid)
        if member is None:
            plan.append((subject, userid, "forget", None))
            continue
        if users.is_protected(portal, userid):
            # Administrators are not on the lab's authorisation list, and an
            # earlier run may already have disabled one: repair that instead of
            # leaving them locked out.
            plan.append((subject, userid, "protect", None))
            continue
        entry = index.get(u"%s" % subject)
        if entry is None:
            plan.append((subject, userid, "missing", None))
            continue
        reason = _blocked_reason(entry)
        if reason:
            plan.append((subject, userid, "disable", reason))
        else:
            plan.append((subject, userid, "keep", entry["record"]))

    missing = [row for row in plan if row[2] == "missing"]
    tracked = len([row for row in plan if row[2] not in ("forget", "protect")])
    stats["missing"] = len(missing)
    stats["protected"] = len([row for row in plan if row[2] == "protect"])
    # Opaque identifiers, no personal data -- these are what to compare against
    # the directory's `external_id` / `user_id` when diagnosing a mismatch.
    stats["unmatched_sample"] = [row[0] for row in missing[:5]]

    deactivate_missing = _check_missing_is_plausible(
        stats, len(missing), tracked, stats["remote_total"])

    # -- pass 3: apply ----------------------------------------------------
    for subject, userid, action, payload in plan:
        if action == "forget":
            logger.warning("SSO mapping %s -> %s has no member, dropping",
                           subject, userid)
            if not dry_run:
                storage.forget(portal, subject)
        elif action == "protect":
            if not dry_run and users.enable_user(portal, userid, timestamp):
                stats["reenabled"] += 1
                logger.warning(
                    u"Re-enabled protected member %s: an administrator must "
                    u"never be left disabled by the sync", userid)
        elif action == "missing":
            if deactivate_missing and not dry_run:
                if users.disable_user(
                        portal, userid, u"不在竹云的应用授权名单中", timestamp):
                    stats["disabled"] += 1
        elif action == "disable":
            if not dry_run and users.disable_user(
                    portal, userid, payload, timestamp):
                stats["disabled"] += 1
        else:
            if not dry_run and users.enable_user(portal, userid, timestamp):
                stats["reenabled"] += 1
            else:
                stats["unchanged"] += 1
            if update_properties and not dry_run:
                if _update_properties(portal, userid, payload):
                    stats["updated"] += 1

    stats["finished"] = _now()
    if not dry_run:
        _record(stats)
    logger.info(
        "IdP user sync finished: accounts=%(accounts_total)s "
        "resolved=%(remote_total)s local=%(local_total)s created=%(created)s "
        "disabled=%(disabled)s reenabled=%(reenabled)s missing=%(missing)s "
        "protected=%(protected)s",
        stats)
    return stats


def _update_properties(portal, userid, record):
    member = users.get_member(portal, userid)
    if member is None:
        return False
    properties = {}
    fullname = record.get("name") or record.get("user_name")
    email = record.get("email")
    if fullname and users.member_property(member, "fullname", u"") != fullname:
        properties["fullname"] = fullname
    if email and users.member_property(member, "email", u"") != email:
        properties["email"] = email
    if not properties:
        return False
    return users.set_member_properties(portal, userid, properties)


def _record(stats):
    summary = dict(stats)
    summary["errors"] = [u"%s" % e for e in stats.get("errors") or []]
    config.set_value("last_sync", u"%s" % (stats.get("finished") or _now()))
    try:
        dumped = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
        if isinstance(dumped, bytes):
            dumped = dumped.decode("utf-8", "replace")
        config.set_value("last_sync_result", dumped)
    except Exception as exc:  # pragma: no cover
        logger.warning("Could not store sync summary: %s", safe_text(exc))
