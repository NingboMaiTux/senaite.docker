# -*- coding: utf-8 -*-
"""到期提醒判定的单元测试（纯逻辑，不依赖 Zope）。

覆盖需求里最容易出错的边界：
  * 已过期            -> expired（红色）
  * 正好第 N 天       -> reminder（黄色，含边界）
  * 刚过 N 天         -> 不提醒
  * 未配置 / 0        -> 用默认值 / 关闭提醒
  * 没有到期日        -> 不提醒
"""

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
        import importlib.util as _iu
    except ImportError:
        import imp
        return imp.load_source(name, file_path)

    spec = _iu.spec_from_file_location(name, file_path)
    module = _iu.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_expiryreminder_module():
    """加载 expiryreminder 模块，桩掉 Zope 相关依赖。"""
    bika_module = types.ModuleType("bika")
    lims_module = types.ModuleType("bika.lims")
    lims_module.api = Namespace(
        is_object=lambda obj: obj is not None and not isinstance(obj, dict),
        get_review_status=lambda obj: getattr(obj, "review_state", u"active"),
        safe_unicode=lambda value: u"" if value is None else u"{}".format(value),
    )
    sys.modules["bika"] = bika_module
    sys.modules["bika.lims"] = lims_module

    i18n_module = types.ModuleType("maitux.stock.i18n")
    i18n_module.translate_stock = lambda msgid, default=None, context=None: (
        default if default is not None else msgid)
    expiry_module = types.ModuleType("maitux.stock.stockbatchexpiry")
    expiry_module.is_due_for_expiry = (
        lambda batch, now=None: bool(getattr(batch, "expired", False)))
    # 中文注释：Zope 的 DateTime 在测试环境里没有，用最小替身：
    # 只要求"能构造 + 能相减得到天数"。
    class FakeDateTime(object):
        def __init__(self, value=None):
            # 允许再包装（to_datetime 会 DateTime(value) 再包一层）
            self.value = getattr(value, "value", value)

        def __sub__(self, other):
            other_value = getattr(other, "value", other)
            return float(self.value) - float(other_value)

    datetime_module = types.ModuleType("DateTime")
    datetime_module.DateTime = FakeDateTime
    sys.modules["DateTime"] = datetime_module
    sys.modules["maitux"] = types.ModuleType("maitux")
    sys.modules["maitux.stock"] = types.ModuleType("maitux.stock")
    sys.modules["maitux.stock.i18n"] = i18n_module
    sys.modules["maitux.stock.stockbatchexpiry"] = expiry_module

    file_path = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "expiryreminder.py"))
    return load_module_from_path(file_path, "test_expiryreminder_module")


MODULE = load_expiryreminder_module()


class TestComputeReminderState(unittest.TestCase):

    def test_expired(self):
        state, days = MODULE.compute_reminder_state(-3, 30)
        self.assertEqual(state, MODULE.STATE_EXPIRED)
        self.assertEqual(days, -3)

    def test_exactly_zero_days_is_expired(self):
        state, _days = MODULE.compute_reminder_state(0, 30)
        self.assertEqual(state, MODULE.STATE_EXPIRED)

    def test_inside_window(self):
        state, _days = MODULE.compute_reminder_state(5, 30)
        self.assertEqual(state, MODULE.STATE_REMINDER)

    def test_boundary_exactly_n_days(self):
        """正好第 N 天要提醒（<= 而不是 <）。"""
        state, _days = MODULE.compute_reminder_state(30, 30)
        self.assertEqual(state, MODULE.STATE_REMINDER)

    def test_just_outside_window(self):
        state, _days = MODULE.compute_reminder_state(30.5, 30)
        self.assertEqual(state, u"")

    def test_zero_days_means_disabled(self):
        state, _days = MODULE.compute_reminder_state(5, 0)
        self.assertEqual(state, u"")
        # 但已过期仍然要标红
        state, _days = MODULE.compute_reminder_state(-1, 0)
        self.assertEqual(state, MODULE.STATE_EXPIRED)

    def test_missing_config_uses_default(self):
        state, _days = MODULE.compute_reminder_state(
            MODULE.DEFAULT_REMINDER_DAYS - 1, None)
        self.assertEqual(state, MODULE.STATE_REMINDER)

    def test_no_days_left(self):
        state, days = MODULE.compute_reminder_state(None, 30)
        self.assertEqual(state, u"")
        self.assertIsNone(days)


class TestGetReminderDays(unittest.TestCase):

    def test_explicit_value(self):
        stock = Namespace(expiry_reminder_days=7)
        self.assertEqual(MODULE.get_reminder_days(stock), 7)

    def test_zero_is_kept(self):
        """0 = 关闭提醒，不能被默认值覆盖。"""
        stock = Namespace(expiry_reminder_days=0)
        self.assertEqual(MODULE.get_reminder_days(stock), 0)

    def test_missing_attribute_uses_default(self):
        """老对象没有这个字段时用默认值。"""
        self.assertEqual(MODULE.get_reminder_days(Namespace()),
                         MODULE.DEFAULT_REMINDER_DAYS)
        self.assertEqual(MODULE.get_reminder_days(None),
                         MODULE.DEFAULT_REMINDER_DAYS)


class TestGetBatchReminder(unittest.TestCase):

    def _batch(self, days_left, expired=False, review_state=u"active"):
        # expiry 与 now 都用假的 DateTime：相减得到"还剩多少天"
        return Namespace(expiry_date=MODULE.DateTime(days_left),
                         expired=expired, review_state=review_state)

    def _now(self):
        return MODULE.DateTime(0)

    def test_expired_batch(self):
        batch = self._batch(-1, expired=True)
        info = MODULE.get_batch_reminder(batch, stock=Namespace(
            expiry_reminder_days=30), now=self._now())
        self.assertEqual(info["state"], MODULE.STATE_EXPIRED)
        self.assertEqual(info["row_class"], MODULE.ROW_CLASS_EXPIRED)
        self.assertEqual(info["badge_class"], u"badge-danger")
        self.assertTrue(info["badge_text"])

    def test_reminder_batch(self):
        batch = self._batch(3.2)
        info = MODULE.get_batch_reminder(batch, stock=Namespace(
            expiry_reminder_days=30), now=self._now())
        self.assertEqual(info["state"], MODULE.STATE_REMINDER)
        self.assertEqual(info["row_class"], MODULE.ROW_CLASS_REMINDER)
        self.assertEqual(info["badge_class"], u"badge-warning")
        # 3.2 天应向上取整成 4
        self.assertIn(u"4", info["badge_text"])

    def test_batch_outside_window(self):
        batch = self._batch(90)
        info = MODULE.get_batch_reminder(batch, stock=Namespace(
            expiry_reminder_days=30), now=self._now())
        self.assertEqual(info["state"], u"")
        self.assertEqual(info["row_class"], u"")

    def test_destroyed_batch_is_not_reminded(self):
        batch = self._batch(-1, expired=True, review_state=u"destroyed")
        info = MODULE.get_batch_reminder(batch, stock=Namespace(
            expiry_reminder_days=30), now=self._now())
        self.assertEqual(info, {
            "state": u"", "days_left": None, "row_class": u"",
            "badge_text": u"", "badge_class": u"",
        })

    def test_no_expiry_date(self):
        batch = Namespace(expiry_date=None, expired=False,
                          review_state=u"active")
        info = MODULE.get_batch_reminder(batch, stock=None, now=self._now())
        self.assertEqual(info["state"], u"")
        self.assertEqual(MODULE.reminder_badge_html(info), u"")

    def test_badge_html(self):
        html = MODULE.reminder_badge_html({
            "badge_text": u"x", "badge_class": u"badge-warning"})
        self.assertIn(u"badge-warning", html)
        self.assertIn(u"x", html)


class TestDefaultExpiryFromStock(unittest.TestCase):
    """主数据上的到期日只作"新建批次时的默认值"，绝不覆盖批次已填的值。"""

    def test_prefills_when_batch_has_no_expiry(self):
        batch = Namespace(expiry_date=None)
        stock = Namespace(expiry_date=u"2027-01-01")
        self.assertTrue(MODULE.default_expiry_from_stock(batch, stock=stock))
        self.assertEqual(batch.expiry_date, u"2027-01-01")

    def test_does_not_overwrite_batch_value(self):
        batch = Namespace(expiry_date=u"2026-05-05")
        stock = Namespace(expiry_date=u"2027-01-01")
        self.assertFalse(MODULE.default_expiry_from_stock(batch, stock=stock))
        self.assertEqual(batch.expiry_date, u"2026-05-05")

    def test_no_stock_value(self):
        batch = Namespace(expiry_date=None)
        self.assertFalse(MODULE.default_expiry_from_stock(
            batch, stock=Namespace(expiry_date=None)))
        self.assertIsNone(batch.expiry_date)

    def test_no_stock(self):
        batch = Namespace(expiry_date=None)
        # 没有 stock 时不应抛错（get_batch_stock 桩返回 None）
        self.assertFalse(MODULE.default_expiry_from_stock(batch, stock=None))

    def test_missing_stock_resolver_is_safe(self):
        batch = Namespace(expiry_date=None)
        self.assertFalse(MODULE.default_expiry_from_stock(batch))


if __name__ == "__main__":
    unittest.main()
