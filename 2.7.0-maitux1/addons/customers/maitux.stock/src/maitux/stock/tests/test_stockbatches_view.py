# -*- coding: utf-8 -*-
import os
import sys
import types
import unittest

class Namespace(object):
    """Python 2.7 下替代 types.SimpleNamespace 的最小实现。"""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def load_module_from_path(file_path, name):
    """按路径加载模块，兼容 Python 2.7（imp）与 3.x（importlib.util）。"""
    try:
        import importlib.util
    except ImportError:
        import imp
        return imp.load_source(name, file_path)

    spec = importlib.util.spec_from_file_location(name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_stockbatches_module():
    """加载 stockbatches 模块，并用最小桩替换外部依赖。"""
    uid_map = {}
    api_module = Namespace(
        safe_unicode=lambda value: u"" if value is None else u"{}".format(value),
        get_path=lambda context: "/stub",
        get_url=lambda context: "/stub",
        get_title=lambda obj: getattr(obj, "title", u"") if obj else u"",
        get_object=lambda obj: obj,
        get_object_by_uid=lambda uid, default=None: uid_map.get(uid, default),
        get_review_status=lambda obj: getattr(obj, "review_state", u""),
        # 中文注释："审核领用"入口会读当前用户（判断是不是审批角色），
        # 桩里返回一个固定账号即可，测试本身不校验账号。
        get_current_user=lambda: Namespace(
            getId=lambda: u"reviewer"),
        get_user_id=lambda: u"reviewer",
        get_uid=lambda obj: getattr(obj, "uid", u""),
    )

    sys.modules["bika"] = types.ModuleType("bika")
    sys.modules["bika.lims"] = types.ModuleType("bika.lims")
    sys.modules["bika.lims"].api = api_module
    sys.modules["bika.lims.api"] = api_module

    utils_module = types.ModuleType("bika.lims.utils")
    utils_module.get_link = lambda href, value, csrf=False: value
    sys.modules["bika.lims.utils"] = utils_module

    listing_module = types.ModuleType("senaite.app.listing")
    class FakeListingView(object):
        def __init__(self, context, request):
            self.context = context
            self.request = request
            self.review_state = {}
            self.columns = {}
        def get_catalog_query(self, **kw):
            return {}
        def folderitems(self):
            return []
        def folderitem(self, obj, item, index):
            return item
    listing_module.ListingView = FakeListingView
    sys.modules["senaite"] = types.ModuleType("senaite")
    sys.modules["senaite.app"] = types.ModuleType("senaite.app")
    sys.modules["senaite.app.listing"] = listing_module

    dtime_module = types.ModuleType("senaite.core.api")
    dtime_module.dtime = Namespace(to_ansi=lambda value, show_time=True: value)
    sys.modules["senaite.core"] = types.ModuleType("senaite.core")
    sys.modules["senaite.core.api"] = dtime_module

    expiry_module = types.ModuleType("maitux.stock.stockbatchexpiry")
    expiry_module.REVIEW_STATE_EXPIRED = u"expired"
    expiry_module.is_due_for_expiry = (
        lambda batch, now=None: bool(getattr(batch, "is_due_for_expiry", False))
    )
    actions_module = types.ModuleType("maitux.stock.browser.stockbatchactions")
    actions_module.ACTION_CONSUME = "stockbatch_consume"
    actions_module.ACTION_SPLIT = "stockbatch_split"
    actions_module.ACTION_RETURN = "stockbatch_return"
    actions_module.ACTION_DESTROY = "stockbatch_destroy"
    actions_module.ACTION_STOCKTAKE = "stockbatch_stocktake"
    actions_module.ACTION_PRINT = "stockbatch_print"
    # 中文注释：stockbatches.py 现在还会导入"审核领用"动作 id，
    # 桩模块漏了它会导致 ImportError（测试直接报错，而不是断言失败）。
    actions_module.ACTION_REVIEW_USAGE = "stockbatch_review_usage"
    actions_module.get_transition_items_for_action_ids = (
        lambda action_ids: [{"id": action_id, "title": action_id} for action_id in action_ids]
    )
    actions_module.get_transition_items_for_batch = (
        lambda batch, now=None: [{"id": getattr(batch, "transition_id", u"stockbatch_print"),
                                  "title": getattr(batch, "transition_id", u"stockbatch_print")}]
    )
    actions_module.get_allowed_action_ids_for_batches = (
        lambda batches, now=None: list(getattr(batches[0], "allowed_action_ids", [])) if batches else []
    )
    sys.modules["maitux"] = types.ModuleType("maitux")
    sys.modules["maitux.stock"] = types.ModuleType("maitux.stock")
    sys.modules["maitux.stock.browser"] = types.ModuleType("maitux.stock.browser")
    sys.modules["maitux.stock.browser.stockbatchactions"] = actions_module
    sys.modules["maitux.stock.stockbatchexpiry"] = expiry_module

    # 中文注释：批次列表还会用到"领用申请"这一侧的三个函数（审核入口列/页签）。
    # 这里给最小桩：默认没有待审核申请，相关列/页签即为空。
    approval_module = types.ModuleType("maitux.stock.usageapproval")
    approval_module.check_approver = (
        lambda usage_request, user_id=None: (True, u"")
    )
    approval_module.find_pending_requests = lambda **kwargs: []
    approval_module.find_pending_requests_for_batch = (
        lambda batch, user_id=None, **kwargs: []
    )
    sys.modules["maitux.stock.usageapproval"] = approval_module

    # 中文注释：列表视图现在通过 maitux.stock.i18n.translate_stock 取文案，
    # 桩里给个"原样返回 msgid"的实现即可（测试不校验译文）。
    i18n_module = types.ModuleType("maitux.stock.i18n")
    i18n_module.translate_stock = (
        lambda msgid, default=None, context=None:
        (default if default is not None else msgid)
    )
    i18n_module.message = lambda msgid, default=None: msgid
    sys.modules["maitux.stock.i18n"] = i18n_module

    # 中文注释：批次列表还会用到"到期提醒"辅助函数（行着色 + 徽标）。
    # 桩里给默认"不提醒"的实现，行着色逻辑另有 test_expiry_reminder.py 覆盖。
    reminder_module = types.ModuleType("maitux.stock.expiryreminder")
    reminder_module.get_batch_reminder = (
        lambda batch, stock=None, now=None: {
            "state": u"", "days_left": None, "row_class": u"",
            "badge_text": u"", "badge_class": u""}
    )
    reminder_module.reminder_badge_html = lambda info: u""
    sys.modules["maitux.stock.expiryreminder"] = reminder_module

    file_path = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "browser", "stockbatches.py"))
    module = load_module_from_path(file_path, "test_stockbatches_module")
    module._test_uid_map = uid_map
    return module


class DummyBatch(object):
    """用于验证列表页签过滤逻辑的最小批次对象。"""

    def __init__(self, is_due_for_expiry=False, transition_id=u"stockbatch_print",
                 allowed_action_ids=None):
        self.is_due_for_expiry = is_due_for_expiry
        self.transition_id = transition_id
        self.allowed_action_ids = allowed_action_ids or []


class TestStockBatchesView(unittest.TestCase):

    def setUp(self):
        self.stockbatches = load_stockbatches_module()

    def test_active_tab_hides_due_batches(self):
        """Active 页签不应显示已经到期的批次。"""
        batch = DummyBatch(is_due_for_expiry=True)

        visible = self.stockbatches.is_batch_visible_in_tab(
            batch,
            review_state_id="default",
        )

        self.assertFalse(visible)

    def test_expired_tab_keeps_due_batches(self):
        """Expired 页签仍然需要显示已到期批次。"""
        batch = DummyBatch(is_due_for_expiry=True)

        visible = self.stockbatches.is_batch_visible_in_tab(
            batch,
            review_state_id="expired",
        )

        self.assertTrue(visible)

    def test_all_tab_keeps_checkbox_for_expired_rows(self):
        """All 页签中的过期批次也应保留复选框。"""
        show_select = self.stockbatches.should_show_select_for_batch(
            review_state_id="all",
            status=u"expired",
        )

        self.assertTrue(show_select)

    def test_default_tab_declares_standard_transitions(self):
        """Active 页签应直接使用标准 listing transitions 配置。"""
        view = self.stockbatches.StockBatchesView(object(), {})

        default_state = [rv for rv in view.review_states if rv["id"] == "default"][0]
        self.assertEqual(
            [item["id"] for item in default_state["transitions"]],
            [
                "stockbatch_consume",
                "stockbatch_split",
                "stockbatch_return",
                "stockbatch_stocktake",
                "stockbatch_destroy",
                "stockbatch_print",
            ],
        )

    def test_default_tab_selected_active_batch_returns_custom_actions(self):
        """Active 页签选择 active 批次时应返回自定义批量动作。"""
        batch = DummyBatch(allowed_action_ids=[
            "stockbatch_consume",
            "stockbatch_split",
            "stockbatch_return",
            "stockbatch_stocktake",
            "stockbatch_destroy",
            "stockbatch_print",
        ])
        self.stockbatches._test_uid_map["UID-1"] = batch
        view = self.stockbatches.StockBatchesView(object(), {})
        view.review_state = {"id": "default", "transitions": [
            {"id": "stockbatch_consume"},
            {"id": "stockbatch_split"},
            {"id": "stockbatch_return"},
            {"id": "stockbatch_stocktake"},
            {"id": "stockbatch_destroy"},
            {"id": "stockbatch_print"},
        ]}

        transitions = view.get_allowed_transitions_for(["UID-1"])

        self.assertEqual(
            [item["id"] for item in transitions],
            [
                "stockbatch_consume",
                "stockbatch_split",
                "stockbatch_return",
                "stockbatch_stocktake",
                "stockbatch_destroy",
                "stockbatch_print",
            ],
        )

    def test_all_tab_selected_active_batch_keeps_all_custom_actions(self):
        """All 页签选择 active 批次时不应退化成只剩 workflow destroy。"""
        batch = DummyBatch(allowed_action_ids=[
            "stockbatch_consume",
            "stockbatch_split",
            "stockbatch_return",
            "stockbatch_stocktake",
            "stockbatch_destroy",
            "stockbatch_print",
        ])
        self.stockbatches._test_uid_map["UID-2"] = batch
        view = self.stockbatches.StockBatchesView(object(), {})
        view.review_state = {"id": "all", "transitions": []}

        transitions = view.get_allowed_transitions_for(["UID-2"])

        self.assertEqual(
            [item["id"] for item in transitions],
            [
                "stockbatch_consume",
                "stockbatch_split",
                "stockbatch_return",
                "stockbatch_stocktake",
                "stockbatch_destroy",
                "stockbatch_print",
            ],
        )
