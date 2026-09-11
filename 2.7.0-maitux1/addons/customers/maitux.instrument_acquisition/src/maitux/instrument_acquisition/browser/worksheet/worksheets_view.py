# -*- coding: utf-8 -*-
"""Worksheets 列表视图适配器：底部工具栏注入「仪器采集」动作

使用 senaite.app.listing 官方提供的 `IListingViewAdapter` 订阅者扩展点：

- 不覆盖 WorksheetsView（避免 browser:page permission 依赖与 ZCML 加载顺序问题）
- 任何 Worksheets 列表（含 review state 过滤页签）底部工具栏都会出现
  「仪器采集」按钮，点击后由 workflow action 适配器校验只能单选并进入采集页

★ **必须在 `before_render()` 里判 browser layer**（R14 / lint 的
`E17_UI_INJECTION_UNGATED`）。这个订阅者的签名是
`(IListingView, IWorksheets)` —— **不含 request**，所以 ZCML 里无处插
`layer=`，而 ZCML 是全局加载的：不判 layer 的话，**没装本 addon 的站点
也会看到「仪器采集」按钮**（本机四个站点实测都泄漏了）。
"""

from zope.interface import implements

from senaite.app.listing.interfaces import IListingViewAdapter

from maitux.instrument_acquisition.interfaces import (
    IInstrumentAcquisitionLayer,
)


ACQUISITION_TRANSITION_ID = "instrument_acquisition"


class ListingViewAdapter(object):
    """为 Worksheets 列表注入「仪器采集」底部动作按钮"""

    implements(IListingViewAdapter)

    def __init__(self, view, context):
        self.view = view
        self.context = context

    def _is_addon_installed(self):
        """本 addon 的 browser layer 是否在当前站点生效

        layer 由 `profiles/default/browserlayer.xml` 在装 profile 时挂上，
        所以"层在不在"等价于"这个站点装了没装"。
        """
        request = getattr(self.view, "request", None)
        if request is None:
            request = getattr(self.context, "REQUEST", None)
        if request is None:
            return False
        return IInstrumentAcquisitionLayer.providedBy(request)

    def before_render(self):
        # ★ 没装本 addon 的站点：什么都不注入（见模块 docstring）
        if not self._is_addon_installed():
            return
        transition = {
            "id": ACQUISITION_TRANSITION_ID,
            "title": u"仪器采集",
        }
        for review_state in self.view.review_states:
            review_state.setdefault("custom_transitions", []).append(transition)
        # 确保显示勾选列与底部工作流按钮区
        self.view.show_select_column = True
        self.view.show_workflow_action_buttons = True

    def folder_item(self, obj, item, index):
        return item
