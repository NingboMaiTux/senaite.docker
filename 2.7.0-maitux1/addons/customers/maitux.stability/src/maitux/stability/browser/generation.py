# -*- coding: utf-8 -*-
"""阶段 4：**到期自动登样的定时入口**（供外部 cron 调用）。

用法（crontab，每 10 分钟一次；是否真的生成由站点配置 `auto_create_time` 决定）::

    */10 * * * * curl -s -u admin:admin \
      "http://127.0.0.1:8081/lims/stability_studies/200_stability_plans/@@generate_due_stability_samples" \
      >> /var/log/senaite/stability_autocreate.log 2>&1

设计要点（开发计划 §8.3，都是硬要求）：

1. **crontab 不写死时刻**：本视图读站点配置 `auto_create_time`（默认 08:00），
   高频调用、由配置决定是否到点 —— 改时刻只需改配置，不用动服务器；
2. **幂等必须绝对可靠**：判据只看"该行的 `analysis_request` 有没有值"
   （见 `samplegeneration.generate_due_samples` 的说明），重复/并发调用不会重复建样；
3. **每次调用给出可读摘要**（扫了几个方案 / 建了几个样品 / 跳了几个），
   写日志 + 作为纯文本响应返回，便于在 cron 日志里排查。

认证（⚠️ 本包有 `package-includes` slug，`cmf.*` 权限**不能**写进 ZCML，见开发规则 R1）：

* ZCML 里用通用的 `zope2.View`；
* 真正的门在 Python 侧：要求 **`ManageSampleAutomation`** 权限（与"自动登样开关"
  同一个权限，也就是"权限可配置"的那个落点）；
* 可选用 `local_only=1` 把调用者限制在 `127.0.0.1`（只在想收紧时显式打开）。
"""

from bika.lims import api
from bika.lims.api.security import check_permission
from plone.protect.interfaces import IDisableCSRFProtection
from Products.Five.browser import BrowserView
from zope.interface import alsoProvides

from maitux.stability import automation
from maitux.stability.permissions import ManageSampleAutomation
from maitux.stability.permissions import permission_name
from maitux.stability.samplegeneration import generate_due_samples


def _as_bool(value, default=False):
    """``1/true/yes/on`` -> True（表单与 URL 参数两种形态都认）。"""
    if value is None:
        return default
    text = api.safe_unicode(value).strip().lower()
    if text in (u"",):
        return default
    return text in (u"1", u"true", u"yes", u"on")


def _as_int(value):
    try:
        return int(api.safe_unicode(value).strip())
    except Exception:
        return None


class GenerateDueSamplesView(BrowserView):
    """``@@generate_due_stability_samples``：到期自动登样的定时入口。"""

    def __call__(self):
        # 定时任务用 curl / wget 调用，没有表单令牌 —— 关掉 CSRF 校验
        # （与 maitux.stock 的 @@sync_expired_batches 同一做法）。
        alsoProvides(self.request, IDisableCSRFProtection)
        self.request.response.setHeader(
            "Content-Type", "text/plain; charset=utf-8")

        form = getattr(self.request, "form", {}) or {}

        if _as_bool(form.get("local_only"), False) and not self.is_local():
            return self.fail(u"refused: not a local call "
                             u"(REMOTE_ADDR=%s)" % self.remote_addr())

        # 站点总开关：关着就什么都不做（"全站急停"）—— 但要明确回报，便于排查
        if not automation.is_site_enabled():
            return self.report([
                u"site_enabled=0",
                u"nothing to do: the site wide switch "
                u"(auto_create_enabled) is off",
            ])

        # 权限：与"自动登样开关"同一个权限（权限可配置的落点）
        if not self.can_manage():
            return self.fail(u"refused: 'ManageSampleAutomation' permission "
                             u"required (user=%s)" % self.current_user())

        result = generate_due_samples(
            self.context,
            self.request,
            dry_run=_as_bool(form.get("dry_run"), False),
            limit=_as_int(form.get("limit")),
            generated_by=u"scheduler",
            respect_time=_as_bool(form.get("respect_time"), True),
        )

        lines = [
            u"now=%s" % result.get("now"),
            u"dry_run=%s" % (1 if result.get("dry_run") else 0),
            u"respect_time=%s generation_time=%s lead_days=%s"
            % (1 if result.get("respect_time") else 0,
               result.get("generation_time"), result.get("lead_days")),
            u"scanned_plans=%s enabled_plans=%s due_rows=%s created=%s failed=%s"
            % (result.get("scanned_plans"), result.get("enabled_plans"),
               result.get("due_rows"), result.get("created"),
               result.get("failed")),
        ]
        skipped = result.get("skipped") or {}
        if skipped:
            lines.append(u"skipped=%s" % u" ".join(
                u"%s:%s" % (key, skipped[key]) for key in sorted(skipped)))
        for plan_id, message in (result.get("errors") or []):
            lines.append(u"error:%s:%s" % (plan_id, message))
        if _as_bool(form.get("verbose"), False):
            for detail in result.get("plans") or []:
                lines.append(
                    u"plan:%s enabled=%s due=%s created=%s failed=%s%s"
                    % (detail.get("plan_id"),
                       1 if detail.get("enabled") else 0,
                       detail.get("due_seqs") or [],
                       detail.get("created"), detail.get("failed"),
                       (u" skipped=%s" % detail.get("skipped"))
                       if detail.get("skipped") else u""))
        return self.report(lines)

    # ------------------------------------------------------------------ helpers
    def report(self, lines):
        return u"\n".join(api.safe_unicode(line) for line in lines) + u"\n"

    def fail(self, message):
        self.request.response.setStatus(403)
        return self.report([u"error:%s" % message])

    def can_manage(self):
        # ★ 权限名必须先解析成 Zope 真正认的名字（title 形式），
        #   否则非 Manager 用户一律被拒（admin 能过只是因为 Zope 对 Manager 硬编码放行）。
        #   见 maitux/stability/permissions.py 的模块注释与 permission_name()。
        if check_permission(permission_name(ManageSampleAutomation), self.context):
            return True
        # 管理员兜底：权限记录缺失/未授角色时（例如 profile 没重跑），
        # 至少不能让定时任务静默失效 —— Manager 角色仍然放行。
        try:
            from plone import api as ploneapi
            user = ploneapi.user.get_current()
            return "Manager" in set(user.getRolesInContext(self.context))
        except Exception:
            return False

    def current_user(self):
        try:
            from plone import api as ploneapi
            return api.safe_unicode(ploneapi.user.get_current().getId())
        except Exception:
            return u"?anonymous"

    def remote_addr(self):
        try:
            return api.safe_unicode(self.request.get("REMOTE_ADDR") or u"")
        except Exception:
            return u""

    def is_local(self):
        return self.remote_addr() in (u"127.0.0.1", u"::1", u"localhost")
