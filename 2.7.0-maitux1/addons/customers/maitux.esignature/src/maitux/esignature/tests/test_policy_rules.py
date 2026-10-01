# -*- coding: utf-8 -*-
"""规则表与"签名人不得为申请人"校验的单元测试。

这些用例刻意不依赖 Zope：`services/rules.py` 和 `services/signflow.py`
都是纯函数模块，用按路径加载的方式即可在 Python 2.7 / 3.x 下运行。
"""

import os
import sys
import unittest


def load_module_from_path(file_path, name):
    """按文件路径加载模块，兼容 Python 2.7 / 3.x。"""
    try:
        import importlib.util
    except ImportError:
        import imp
        return imp.load_source(name, file_path)

    spec = importlib.util.spec_from_file_location(name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_rules_module():
    file_path = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "services", "rules.py"))
    return load_module_from_path(file_path, "test_esignature_rules_module")


def load_signflow_module():
    file_path = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "services", "signflow.py"))
    return load_module_from_path(file_path, "test_esignature_signflow_module")


RULES = load_rules_module()
SIGNFLOW = load_signflow_module()


class TestDisallowInitiatorRule(unittest.TestCase):
    """规则表要能存下并读回 disallow_initiator。"""

    def test_default_is_false(self):
        rule = RULES.normalize_rule({
            "portal_type": "StockUsageRequest",
            "transition_id": "approve",
        })
        self.assertFalse(rule["disallow_initiator"])

    def test_accepts_string_flags(self):
        for raw in ("1", "true", "yes", "on", True):
            rule = RULES.normalize_rule({"disallow_initiator": raw})
            self.assertTrue(rule["disallow_initiator"], raw)
        for raw in ("0", "false", "no", "off", False):
            rule = RULES.normalize_rule({"disallow_initiator": raw})
            self.assertFalse(rule["disallow_initiator"], raw)

    def test_round_trip_keeps_flag(self):
        """控制面板保存是一次序列化往返，标志位不能被丢掉。"""
        source = [{
            "portal_type": "StockUsageRequest",
            "workflow_id": "senaite_stockusagerequest_workflow",
            "transition_id": "approve",
            "signature_required": True,
            "require_countersign": True,
            "disallow_initiator": True,
            "meaning_required": True,
            "reason_required": True,
        }]
        text = RULES.dumps_policy_rules(source)
        loaded = RULES.loads_policy_rules(text)
        self.assertEqual(len(loaded), 1)
        self.assertTrue(loaded[0]["require_countersign"])
        self.assertTrue(loaded[0]["disallow_initiator"])


class TestSignerAgainstInitiator(unittest.TestCase):
    """双人复核时，两个账号都不能是申请人。"""

    def test_disabled_switch_always_passes(self):
        self.assertIsNone(SIGNFLOW.check_signers_against_initiator(
            ["applicant"], "applicant", enabled=False))

    def test_unknown_initiator_is_fail_closed(self):
        self.assertIsNotNone(SIGNFLOW.check_signers_against_initiator(
            ["op1", "op2"], "", enabled=True))

    def test_primary_signer_cannot_be_initiator(self):
        message = SIGNFLOW.check_signers_against_initiator(
            ["applicant", "op2"], "applicant", enabled=True)
        self.assertIsNotNone(message)
        self.assertIn("applicant", message)

    def test_countersigner_cannot_be_initiator(self):
        """这是守卫看不到的那一半：复核人也不能是申请人。"""
        message = SIGNFLOW.check_signers_against_initiator(
            ["op1", "applicant"], "applicant", enabled=True)
        self.assertIsNotNone(message)

    def test_two_other_operators_pass(self):
        self.assertIsNone(SIGNFLOW.check_signers_against_initiator(
            ["op1", "op2"], "applicant", enabled=True))

    def test_empty_signers_pass(self):
        self.assertIsNone(SIGNFLOW.check_signers_against_initiator(
            [], "applicant", enabled=True))


if __name__ == "__main__":
    unittest.main()
