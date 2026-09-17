# -*- coding: utf-8 -*-
"""Control panel for the 竹云统一登录 settings."""

from Products.statusmessages.interfaces import IStatusMessage
from plone import api
from plone.app.registry.browser import controlpanel
from z3c.form import button

from maitux.oauth2 import _
from maitux.oauth2 import config
from maitux.oauth2 import safe_text
from maitux.oauth2.browser.views import disable_csrf
from maitux.oauth2.interfaces import IOAuth2Settings


class OAuth2SettingsEditForm(controlpanel.RegistryEditForm):
    schema = IOAuth2Settings
    schema_prefix = "maitux.oauth2"
    label = _(u"竹云统一登录 (OAuth 2.0)")

    # 继承来的“保存”“取消”要先复制出来，否则下面那个装饰器会在子类上另起一套
    # buttons，把它们俩顶掉。
    buttons = controlpanel.RegistryEditForm.buttons.copy()
    handlers = controlpanel.RegistryEditForm.handlers.copy()

    def updateWidgets(self, *args, **kwargs):
        super(OAuth2SettingsEditForm, self).updateWidgets(*args, **kwargs)
        # z3c.form falls back to `field.default` whenever the stored value
        # equals missing_value (u"" for our text fields), so a field the admin
        # deliberately cleared would come back showing the shipped default --
        # even though the runtime correctly treats it as empty.  Make the form
        # agree with what is actually stored.
        content = self.getContent()
        for name in list(self.widgets):
            if getattr(content, name, None) == u"":
                widget = self.widgets[name]
                if widget.value not in (None, u""):
                    widget.value = u""

    def applyChanges(self, data):
        # The password widget deliberately never renders its stored value, so
        # `client_secret` arrives empty on every single save.  Treat "left
        # blank" as "keep what is stored" -- otherwise saving any unrelated
        # setting silently wipes the secret.
        if not (data.get("client_secret") or u"").strip():
            data.pop("client_secret", None)
        return super(OAuth2SettingsEditForm, self).applyChanges(data)

    def getContent(self):
        # plone.app.registry's getContent() calls forInterface() WITHOUT
        # check=False, so one schema field that has no registry record yet
        # (i.e. a field added after this profile was installed) raises
        # KeyError and 500s the whole settings page.  Self-heal instead of
        # forcing a profile re-import.
        if config.ensure_records() or config.normalize_text_records():
            # A legitimate ZODB write on a GET, on a Manage-portal-only page.
            disable_csrf(self.request)
        return super(OAuth2SettingsEditForm, self).getContent()

    #: 装机当天填完配置就想把人拉进来，没人愿意等今晚两点（自动调度见
    #: scheduler.py）。先保存再同步：否则刚填的 app_id / 凭据还没落库，
    #: 同步拿旧配置去跑，报错报得莫名其妙。
    @button.buttonAndHandler(_(u"保存并立即同步"), name="sync_now")
    def handle_sync_now(self, action):
        data, errors = self.extractData()
        if errors:
            self.status = self.formErrorsMessage
            return
        self.applyChanges(data)

        from maitux.oauth2 import sync
        messages = IStatusMessage(self.request)
        try:
            stats = sync.sync_users(api.portal.get())
        except Exception as exc:
            # 同步是一长串网络调用，出什么都不该把配置页打成 500 —— 配置刚
            # 保存好，用户得能看见页面才知道保存成功了。
            messages.addStatusMessage(u"同步失败：%s" % safe_text(exc), "error")
            self.request.response.redirect(self.request.getURL())
            return

        problems = stats.get("errors") or []
        if problems and not stats.get("accounts_total"):
            # 一个人都没拉到：开关没开、或者竹云那边没通。报第一条原因，
            # 别拿一串 0 去糊弄人。
            messages.addStatusMessage(
                u"同步没有进行：%s" % problems[0], "error")
        else:
            summary = (u"同步完成：竹云授权名单 %s 人，新建 %s、关联 %s、"
                       u"停用 %s、恢复 %s、更新 %s。"
                       % (stats.get("accounts_total"), stats.get("created"),
                          stats.get("linked"), stats.get("disabled"),
                          stats.get("reenabled"), stats.get("updated")))
            if problems:
                summary += u"另有 %s 条问题，详见下方“上次同步结果”。" % len(problems)
            messages.addStatusMessage(summary, "warning" if problems else "info")

        # 先跳转再渲染：表单的只读字段（上次同步时间 / 上次同步结果）是在
        # 按钮处理之前就取好值的，不跳转的话页面上还是上一次的结果。
        self.request.response.redirect(self.request.getURL())

    @property
    def description(self):
        portal_url = api.portal.get().absolute_url()
        # Exactly the value the login flow will send, so it can be copied
        # verbatim into the 竹云 application's trusted callback list.
        callback = config.callback_url(portal_url, self.request)
        lines = [
            u"① 把这个回调地址交给竹云登记（照抄，不要改）：%s" % callback,
            u"② 管理员本地登录入口（绕过统一登录，万一被锁在外面用）："
            u"%s/@@oauth2-local-login" % portal_url,
            u"③ 手动触发用户同步：%s/@@oauth2-sync-users" % portal_url,
        ]
        overridden = sorted([name for name in config.FIELDS
                             if config.env_value(name) is not None])
        if overridden:
            lines.append(
                u"⚠ 以下配置项被容器环境变量覆盖，本页面上改了也不生效："
                u"%s（环境变量是整个容器共享的，多站点部署请不要用它设置"
                u"站点相关的项）" % u"、".join(overridden))
        return u" | ".join(lines)


class OAuth2SettingsView(controlpanel.ControlPanelFormWrapper):
    form = OAuth2SettingsEditForm
