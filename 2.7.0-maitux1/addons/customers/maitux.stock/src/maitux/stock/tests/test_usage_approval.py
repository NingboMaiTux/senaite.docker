# -*- coding: utf-8 -*-
"""领用申请/审批的领域逻辑测试。

沿用本仓库既有做法（见 test_stockbatch_actions.py）：不启动 Zope，
把外部依赖桩化后按文件路径加载被测模块。

注意：运行环境是 Python 2.7，这里不使用 types.SimpleNamespace /
importlib.util / unittest.mock 等仅 Python 3 可用的设施。
"""
import os
import sys
import types
import unittest
from decimal import Decimal


# get_object_by_uid / get_user 使用的表
OBJECTS = {}
USERS = {}


class Namespace(object):
    """Python 2.7 下替代 types.SimpleNamespace 的最小实现。"""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def load_module_from_path(file_path, name):
    try:
        import importlib.util
    except ImportError:
        import imp
        return imp.load_source(name, file_path)

    spec = importlib.util.spec_from_file_location(name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_stubs():
    """给 usageapproval / guards 提供最小可用的外部依赖。"""
    api_module = Namespace(
        safe_unicode=lambda value: u"" if value is None else u"{}".format(value),
        get_uid=lambda obj: getattr(obj, "uid", u""),
        get_title=lambda obj: getattr(obj, "title", u"") if obj is not None else u"",
        get_object_by_uid=lambda uid, default=None: OBJECTS.get(uid, default),
        get_user=lambda userid: USERS.get(userid),
        get_portal=lambda: None,
        get_current_user=lambda: None,
        get_user_fullname=lambda user: getattr(user, "fullname", u""),
        get_review_status=lambda obj: getattr(obj, "review_state", u""),
    )

    sys.modules["bika"] = types.ModuleType("bika")
    sys.modules["bika.lims"] = types.ModuleType("bika.lims")
    sys.modules["bika.lims"].api = api_module
    sys.modules["bika.lims"].bikaMessageFactory = lambda msg: msg
    sys.modules["bika.lims.api"] = api_module

    sys.modules["senaite"] = types.ModuleType("senaite")
    sys.modules["senaite.core"] = types.ModuleType("senaite.core")
    sys.modules["senaite.core"].logger = Namespace(
        info=lambda *a, **kw: None,
        warn=lambda *a, **kw: None,
        warning=lambda *a, **kw: None,
        error=lambda *a, **kw: None,
        exception=lambda *a, **kw: None,
    )
    api_core = types.ModuleType("senaite.core.api")
    api_core.dtime = Namespace(now=lambda: u"2026-01-01T00:00:00")
    sys.modules["senaite.core.api"] = api_core

    # usageapproval 模块级 from DateTime import DateTime（写审计快照时的时间戳）
    class FakeDateTime(object):
        def ISO(self):
            return u"2026-01-01T00:00:00+00:00"

    datetime_module = types.ModuleType("DateTime")
    datetime_module.DateTime = FakeDateTime
    sys.modules["DateTime"] = datetime_module

    sys.modules["maitux"] = types.ModuleType("maitux")
    sys.modules["maitux.stock"] = types.ModuleType("maitux.stock")

    config_module = types.ModuleType("maitux.stock.config")
    config_module.CONSUME_COUNTERSIGN_ROLES = (
        u"LabManager", u"InventoryAdministrator")
    config_module.USAGE_REQUEST_SIGNED_TRANSITIONS = (u"submit", u"approve", u"reject")
    config_module.USAGE_REQUEST_TYPE = "StockUsageRequest"
    config_module.USAGE_REQUEST_WORKFLOW = "senaite_stockusagerequest_workflow"
    sys.modules["maitux.stock.config"] = config_module

    expiry_module = types.ModuleType("maitux.stock.stockbatchexpiry")
    # 由每个用例通过 EXPIRED / BLOCKED 集合控制
    expiry_module.is_due_for_expiry = (
        lambda batch, now=None: getattr(batch, "expired", False))
    expiry_module.get_operation_block_message = (
        lambda batch, now=None: getattr(batch, "block_message", u""))
    sys.modules["maitux.stock.stockbatchexpiry"] = expiry_module


def load_usageapproval():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.abspath(os.path.join(here, "..", "usageapproval.py"))
    module = load_module_from_path(path, "test_usageapproval_module")
    # guards.py 会 `from maitux.stock.usageapproval import ...`，
    # 这里把加载好的模块注册进去，保证是同一个实例（同一份白名单常量）。
    sys.modules["maitux.stock.usageapproval"] = module
    return module


def load_guards():
    if "maitux.stock.usageapproval" not in sys.modules:
        load_usageapproval()
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.abspath(os.path.join(here, "..", "guards.py"))
    return load_module_from_path(path, "test_guards_module")


class DummyStock(object):
    def __init__(self, requires=True, title=u"Reagent"):
        self.title = title
        self.consume_requires_countersign = requires


class DummyUnit(object):
    def __init__(self, title=u"mL"):
        self.title = title


class DummyBatch(object):
    def __init__(self, uid, current=u"10.00", batch_id=u"RM-001/1",
                 stock_uid=u"", unit_uid=u""):
        self.uid = uid
        self.title = batch_id
        self.batch_id = batch_id
        self.stock = stock_uid
        self.unit = unit_uid
        self.current_amount = current
        self.usage_records = []
        self.expired = False
        self.block_message = u""
        self.reindexed = 0

    def reindexObject(self):
        self.reindexed += 1


class DummyUser(object):
    def __init__(self, userid, roles=(), fullname=u""):
        self.userid = userid
        self.roles = list(roles)
        self.fullname = fullname

    def getRolesInContext(self, context):
        return list(self.roles)


class DummyRequest(object):
    """领用申请单（只带被测逻辑用得到的部分）。"""

    def __init__(self, lines=None, request_id=u"SUR-00001", applicant=u"alice"):
        self.lines = list(lines or [])
        self.request_id = request_id
        self.applicant = applicant
        self.applicant_fullname = u"Alice"
        self.signature_log = []


class TestUsageApproval(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        install_stubs()
        cls.mod = load_usageapproval()

    def setUp(self):
        OBJECTS.clear()
        USERS.clear()

    # ---- 基础工具 ----
    def test_to_decimal(self):
        self.assertEqual(self.mod.to_decimal(u"1.50"), Decimal("1.50"))
        self.assertEqual(self.mod.to_decimal(None), Decimal("0.00"))
        self.assertEqual(self.mod.to_decimal(u"abc"), Decimal("0.00"))
        self.assertEqual(self.mod.to_decimal(Decimal("2")), Decimal("2"))

    def test_first_uid(self):
        self.assertEqual(self.mod.first_uid(u"uid-1"), u"uid-1")
        self.assertEqual(self.mod.first_uid([u"uid-2"]), u"uid-2")
        self.assertEqual(self.mod.first_uid(u"uid-3\nuid-4"), u"uid-3")
        self.assertEqual(self.mod.first_uid(None), u"")

    # ---- 是否需要签名 ----
    def test_stock_requires_signature_handles_none(self):
        self.assertFalse(self.mod.stock_requires_signature(None))

    def test_batch_requires_signature_resolves_stock(self):
        OBJECTS[u"stock-a"] = DummyStock(requires=True)
        OBJECTS[u"stock-b"] = DummyStock(requires=False)
        self.assertTrue(self.mod.batch_requires_signature(
            DummyBatch(u"b1", stock_uid=u"stock-a")))
        self.assertFalse(self.mod.batch_requires_signature(
            DummyBatch(u"b2", stock_uid=u"stock-b")))
        self.assertFalse(self.mod.batch_requires_signature(
            DummyBatch(u"b3", stock_uid=u"")))

    def test_any_batch_requires_signature(self):
        OBJECTS[u"stock-a"] = DummyStock(requires=True)
        OBJECTS[u"stock-b"] = DummyStock(requires=False)
        batch_a = DummyBatch(u"b1", stock_uid=u"stock-a")
        batch_b = DummyBatch(u"b2", stock_uid=u"stock-b")
        self.assertTrue(self.mod.any_batch_requires_signature([batch_a, batch_b]))
        self.assertFalse(self.mod.any_batch_requires_signature([batch_b]))
        self.assertFalse(self.mod.any_batch_requires_signature([]))

    # ---- 申请人 / 审批人 ----
    def test_is_applicant(self):
        request = DummyRequest(applicant=u"alice")
        self.assertTrue(self.mod.is_applicant(request, u"alice"))
        self.assertFalse(self.mod.is_applicant(request, u"bob"))
        self.assertFalse(self.mod.is_applicant(request, u""))
        self.assertFalse(self.mod.is_applicant(request, None))

    def test_check_approver_rejects_applicant(self):
        request = DummyRequest(applicant=u"alice")
        USERS[u"alice"] = DummyUser(u"alice", roles=[u"LabManager"])
        message = self.mod.check_approver(request, u"alice")
        self.assertIn(u"不能是申请人本人", message)

    def test_check_approver_rejects_user_without_role(self):
        request = DummyRequest(applicant=u"alice")
        USERS[u"carol"] = DummyUser(u"carol", roles=[u"Member"])
        message = self.mod.check_approver(request, u"carol")
        self.assertIn(u"不具备审批角色", message)

    def test_check_approver_accepts_allowed_role(self):
        request = DummyRequest(applicant=u"alice")
        USERS[u"bob"] = DummyUser(u"bob", roles=[u"InventoryAdministrator"])
        self.assertEqual(self.mod.check_approver(request, u"bob"), u"")

    def test_check_approver_without_whitelist_only_blocks_applicant(self):
        self.mod.CONSUME_COUNTERSIGN_ROLES = ()
        try:
            request = DummyRequest(applicant=u"alice")
            USERS[u"carol"] = DummyUser(u"carol", roles=[u"Member"])
            self.assertEqual(self.mod.check_approver(request, u"carol"), u"")
            self.assertIn(u"不能是申请人本人",
                          self.mod.check_approver(request, u"alice"))
        finally:
            self.mod.CONSUME_COUNTERSIGN_ROLES = (
                u"LabManager", u"InventoryAdministrator")

    # ---- 明细 ----
    def test_build_line_snapshots_master_data(self):
        OBJECTS[u"stock-a"] = DummyStock(title=u"Reagent")
        OBJECTS[u"unit-a"] = DummyUnit(title=u"mL")
        batch = DummyBatch(u"b1", batch_id=u"RM-001/1",
                           stock_uid=u"stock-a", unit_uid=u"unit-a")
        line = self.mod.build_line(batch, Decimal("2.50"), u"routine")
        self.assertEqual(line["batch_uid"], u"b1")
        self.assertEqual(line["batch_id"], u"RM-001/1")
        self.assertEqual(line["stock_title"], u"Reagent")
        self.assertEqual(line["unit_title"], u"mL")
        self.assertEqual(line["requested_quantity"], Decimal("2.50"))
        self.assertEqual(line["remarks"], u"routine")

    def test_group_requested_quantity_merges_same_batch(self):
        lines = [
            {"batch_uid": u"b1", "requested_quantity": Decimal("1.00")},
            {"batch_uid": u"b1", "requested_quantity": Decimal("2.00")},
            {"batch_uid": u"b2", "requested_quantity": Decimal("0.50")},
        ]
        totals = self.mod.group_requested_quantity(lines)
        self.assertEqual(totals[u"b1"], Decimal("3.00"))
        self.assertEqual(totals[u"b2"], Decimal("0.50"))

    # ---- 校验 ----
    def test_validate_lines_ok(self):
        OBJECTS[u"b1"] = DummyBatch(u"b1", current=u"10.00")
        lines = [{"batch_uid": u"b1", "batch_id": u"RM-001/1",
                  "requested_quantity": Decimal("2.00")}]
        self.assertEqual(self.mod.validate_lines(lines), [])

    def test_validate_lines_missing_batch(self):
        lines = [{"batch_uid": u"nope", "batch_id": u"X",
                  "requested_quantity": Decimal("1.00")}]
        errors = self.mod.validate_lines(lines)
        self.assertEqual(len(errors), 1)
        self.assertIn(u"not found", errors[0][1])

    def test_validate_lines_rejects_non_positive_quantity(self):
        OBJECTS[u"b1"] = DummyBatch(u"b1")
        lines = [{"batch_uid": u"b1", "batch_id": u"RM-001/1",
                  "requested_quantity": Decimal("0.00")}]
        errors = self.mod.validate_lines(lines)
        self.assertIn(u"greater than 0", errors[0][1])

    def test_validate_lines_rejects_expired(self):
        batch = DummyBatch(u"b1")
        batch.expired = True
        OBJECTS[u"b1"] = batch
        lines = [{"batch_uid": u"b1", "batch_id": u"RM-001/1",
                  "requested_quantity": Decimal("1.00")}]
        errors = self.mod.validate_lines(lines)
        self.assertIn(u"expired", errors[0][1])

    def test_validate_lines_reports_block_message(self):
        batch = DummyBatch(u"b1")
        batch.block_message = u"Batch is destroyed"
        OBJECTS[u"b1"] = batch
        lines = [{"batch_uid": u"b1", "batch_id": u"RM-001/1",
                  "requested_quantity": Decimal("1.00")}]
        errors = self.mod.validate_lines(lines)
        self.assertEqual(errors[0][1], u"Batch is destroyed")

    def test_validate_lines_rejects_over_current_amount(self):
        OBJECTS[u"b1"] = DummyBatch(u"b1", current=u"1.00")
        lines = [{"batch_uid": u"b1", "batch_id": u"RM-001/1",
                  "requested_quantity": Decimal("2.00")}]
        errors = self.mod.validate_lines(lines)
        self.assertIn(u"exceeds the current amount", errors[0][1])

    def test_validate_lines_sums_multiple_lines_of_same_batch(self):
        """同一批次写两行，必须按合计校验余量（否则可绕过上限）。"""
        OBJECTS[u"b1"] = DummyBatch(u"b1", current=u"3.00")
        lines = [
            {"batch_uid": u"b1", "batch_id": u"RM-001/1",
             "requested_quantity": Decimal("2.00")},
            {"batch_uid": u"b1", "batch_id": u"RM-001/1",
             "requested_quantity": Decimal("2.00")},
        ]
        errors = self.mod.validate_lines(lines)
        self.assertEqual(len(errors), 1)
        self.assertIn(u"exceeds the current amount", errors[0][1])

    # ---- 流水 ----
    def test_append_usage_record(self):
        batch = DummyBatch(u"b1")
        batch.usage_records = [{"operation_type": u"create"}]
        records = self.mod.append_usage_record(
            batch, now=u"2026-01-01T00:00:00", operator=u"alice", qty=2,
            remarks=u"x", second_operator=u"bob", request_id=u"SUR-00001")
        self.assertEqual(len(records), 2)
        entry = records[-1]
        self.assertEqual(entry["operation_type"], u"consume")
        self.assertEqual(entry["operator"], u"alice")
        self.assertEqual(entry["second_operator"], u"bob")
        self.assertEqual(entry["request_id"], u"SUR-00001")
        self.assertEqual(entry["quantity"], 2)

    def test_append_usage_record_does_not_mutate_existing(self):
        original = [{"operation_type": u"create"}]
        batch = DummyBatch(u"b1")
        batch.usage_records = original
        self.mod.append_usage_record(batch, request_id=u"SUR-1")
        self.assertEqual(len(original), 1)

    def test_append_usage_record_handles_bad_value(self):
        batch = DummyBatch(u"b1")
        batch.usage_records = u"not-a-list"
        records = self.mod.append_usage_record(batch)
        self.assertEqual(len(records), 1)

    # ---- 扣减 ----
    def make_line(self, uid, quantity, batch_id=u"RM-001/1"):
        return {"batch_uid": uid, "batch_id": batch_id,
                "requested_quantity": Decimal(quantity)}

    def test_deduct_request_lines_applies_quantities_and_records(self):
        batch_a = DummyBatch(u"b1", current=u"10.00", batch_id=u"RM-001/1")
        batch_b = DummyBatch(u"b2", current=u"5.00", batch_id=u"RM-002/1")
        OBJECTS[u"b1"] = batch_a
        OBJECTS[u"b2"] = batch_b
        request = DummyRequest(lines=[
            self.make_line(u"b1", u"2.00"),
            self.make_line(u"b2", u"1.50", batch_id=u"RM-002/1"),
        ], request_id=u"SUR-00007", applicant=u"alice")

        deducted = self.mod.deduct_request_lines(
            request, approver_user_id=u"bob")

        self.assertEqual(deducted, 2)
        self.assertEqual(batch_a.current_amount, Decimal("8.00"))
        self.assertEqual(batch_b.current_amount, Decimal("3.50"))
        record = batch_a.usage_records[-1]
        self.assertEqual(record["operator"], u"alice")        # 领用人 = 申请人
        self.assertEqual(record["second_operator"], u"bob")   # 审核人
        self.assertEqual(record["request_id"], u"SUR-00007")
        self.assertEqual(record["quantity"], Decimal("2.00"))
        self.assertEqual(batch_a.reindexed, 1)

    def test_deduct_request_lines_sums_same_batch(self):
        batch = DummyBatch(u"b1", current=u"10.00")
        OBJECTS[u"b1"] = batch
        request = DummyRequest(lines=[
            self.make_line(u"b1", u"2.00"),
            self.make_line(u"b1", u"3.00"),
        ])
        self.assertEqual(self.mod.deduct_request_lines(request), 2)
        self.assertEqual(batch.current_amount, Decimal("5.00"))
        self.assertEqual(len(batch.usage_records), 2)

    def test_deduct_request_lines_raises_without_mutating(self):
        """校验不通过时必须整体不动（不能扣一半）。"""
        batch_a = DummyBatch(u"b1", current=u"10.00")
        batch_b = DummyBatch(u"b2", current=u"1.00")
        OBJECTS[u"b1"] = batch_a
        OBJECTS[u"b2"] = batch_b
        request = DummyRequest(lines=[
            self.make_line(u"b1", u"2.00"),
            self.make_line(u"b2", u"5.00"),   # 超过余量
        ])
        self.assertRaises(ValueError, self.mod.deduct_request_lines, request)
        # 必须一行都没扣：数量与流水都保持原样
        self.assertEqual(self.mod.to_decimal(batch_a.current_amount),
                         Decimal("10.00"))
        self.assertEqual(self.mod.to_decimal(batch_b.current_amount),
                         Decimal("1.00"))
        self.assertEqual(batch_a.usage_records, [])


class TestUsageRequestGuard(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        install_stubs()
        cls.mod = load_guards()

    def setUp(self):
        OBJECTS.clear()
        USERS.clear()

    def make_guard(self, current_user_id, request):
        guard = self.mod.StockUsageRequestGuard(request)
        guard.current_user_id = lambda: current_user_id
        return guard

    def test_submit_only_by_applicant(self):
        request = DummyRequest(applicant=u"alice")
        self.assertTrue(self.make_guard(u"alice", request).guard(u"submit"))
        self.assertFalse(self.make_guard(u"bob", request).guard(u"submit"))

    def test_retract_only_by_applicant(self):
        request = DummyRequest(applicant=u"alice")
        self.assertTrue(self.make_guard(u"alice", request).guard(u"retract"))
        self.assertFalse(self.make_guard(u"bob", request).guard(u"retract"))

    def test_approve_blocked_for_applicant(self):
        request = DummyRequest(applicant=u"alice")
        USERS[u"alice"] = DummyUser(u"alice", roles=[u"LabManager"])
        self.assertFalse(self.make_guard(u"alice", request).guard(u"approve"))

    def test_approve_blocked_without_role(self):
        request = DummyRequest(applicant=u"alice")
        USERS[u"carol"] = DummyUser(u"carol", roles=[u"Member"])
        self.assertFalse(self.make_guard(u"carol", request).guard(u"approve"))

    def test_approve_allowed_for_other_user_with_role(self):
        OBJECTS[u"b1"] = DummyBatch(u"b1", current=u"10.00")
        request = DummyRequest(
            applicant=u"alice",
            lines=[{"batch_uid": u"b1", "batch_id": u"RM-001/1",
                    "requested_quantity": Decimal("1.00")}])
        USERS[u"bob"] = DummyUser(u"bob", roles=[u"InventoryAdministrator"])
        self.assertTrue(self.make_guard(u"bob", request).guard(u"approve"))

    def test_approve_blocked_when_lines_not_deductible(self):
        """余量不足时，审核按钮对应的守卫必须为 False。"""
        OBJECTS[u"b1"] = DummyBatch(u"b1", current=u"1.00")
        request = DummyRequest(
            applicant=u"alice",
            lines=[{"batch_uid": u"b1", "batch_id": u"RM-001/1",
                    "requested_quantity": Decimal("5.00")}])
        USERS[u"bob"] = DummyUser(u"bob", roles=[u"InventoryAdministrator"])
        self.assertFalse(self.make_guard(u"bob", request).guard(u"approve"))

    def test_reject_does_not_require_deductible_lines(self):
        """驳回不扣库存，所以即便余量不足也允许驳回。"""
        OBJECTS[u"b1"] = DummyBatch(u"b1", current=u"1.00")
        request = DummyRequest(
            applicant=u"alice",
            lines=[{"batch_uid": u"b1", "batch_id": u"RM-001/1",
                    "requested_quantity": Decimal("5.00")}])
        USERS[u"bob"] = DummyUser(u"bob", roles=[u"InventoryAdministrator"])
        self.assertTrue(self.make_guard(u"bob", request).guard(u"reject"))

    def test_unknown_transition_is_allowed(self):
        request = DummyRequest(applicant=u"alice")
        self.assertTrue(self.make_guard(u"bob", request).guard(u"something"))


if __name__ == "__main__":
    unittest.main()
