# -*- coding: utf-8 -*-
#
# 手动刷新：立刻与站点对账一次，回到列表页并给出结果提示。
#
# 列表页每次打开本来就会自动同步（见 browser/listing.py 的 __call__）；
# 这个按钮是给"我刚在站点上改了配置，想立刻看结果"的场景用的，
# 并且会**把结果摆在界面上**（portal status message），不用去翻日志。
#
# 权限用 zope2.View：需求是"任何能打开列表页的人都可触发"，
# 写入仍是提权执行（见 sync/runner.py），触发者会记入 last_sync_by 与日志。

from bika.lims import api
from plone import api as ploneapi
from zope.publisher.browser import BrowserView

from maitux.glossary import _
from maitux.glossary.sync.runner import run_sync
from maitux.glossary.utils import get_container


class GlossarySyncView(BrowserView):
    """手动触发一次同步，然后跳回列表页。"""

    def __call__(self):
        container = get_container()
        if container is None:
            ploneapi.portal.show_message(
                message=_(u"Keyword glossary container not found"),
                request=self.request, type=u"error")
            return self.request.response.redirect(
                api.get_url(api.get_portal()))

        outcome = run_sync(container)

        if outcome.ok:
            summary = outcome.plan.summary() if outcome.plan else u"-"
            message = _(
                u"Sync finished: ${summary} (${elapsed}s)",
                mapping={"summary": summary,
                         "elapsed": u"%.2f" % outcome.elapsed})
            kind = u"info"
        else:
            message = _(
                u"Sync failed: ${error}",
                mapping={"error": outcome.error or u"unknown"})
            kind = u"error"

        ploneapi.portal.show_message(
            message=message, request=self.request, type=kind)
        return self.request.response.redirect(api.get_url(container))
