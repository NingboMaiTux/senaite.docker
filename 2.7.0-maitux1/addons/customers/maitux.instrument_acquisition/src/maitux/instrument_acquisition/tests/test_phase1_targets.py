# -*- coding: utf-8 -*-
"""采集目标位推导测试（interim 标记 → 目标位定义）

纯单元测试：不依赖 Zope 运行环境。
为避免触发包级 __init__（引入 bika.lims 等 Zope 依赖），
直接按文件路径加载 phase1_targets.py。

★ 重点覆盖三类**静默失败**的入口（Backlog S5 裁决⑥、S1 的 `<NO_VALUE>` 发现）：
- `<NO_VALUE>` 是真值，不能当成"已配置"
- 只配一半 / 角色拼错要留痕（回调被调用），不能静默丢
- `acquisition_group` 的类型不确定（int / float / str 都可能）
"""

import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODULE_PATH = os.path.join(_HERE, "..", "services", "phase1_targets.py")


def _load_source(name, path):
    """按文件路径加载模块（py2 用 imp；py3.12+ 用 importlib.util）"""
    try:
        import imp
        return imp.load_source(name, path)
    except ImportError:
        import importlib.util
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


_targets = _load_source("maitux_phase1_targets_test", _MODULE_PATH)


def _interim(keyword, title=u"", role=None, group=None, result_type=u"numeric"):
    """造一条 interim dict；role/group 传 None 表示该键**不存在**"""
    item = {
        "keyword": keyword,
        "title": title or keyword,
        "result_type": result_type,
        "value": u"",
    }
    if role is not None:
        item[_targets.ACQUISITION_ROLE_KEY] = role
    if group is not None:
        item[_targets.ACQUISITION_GROUP_KEY] = group
    return item


class CleanMarkTest(unittest.TestCase):
    """`_clean_mark`：把标记值归一，`<NO_VALUE>` 与空白都当未填写"""

    def test_no_value_marker_is_empty(self):
        # ★ 这是 S1 发现的那个坑：它是**真值**，不归一就会被当成已配置
        self.assertEqual(_targets._clean_mark(u"<NO_VALUE>"), u"")
        self.assertEqual(_targets._clean_mark("<NO_VALUE>"), u"")

    def test_blank_and_none(self):
        self.assertEqual(_targets._clean_mark(None), u"")
        self.assertEqual(_targets._clean_mark(u""), u"")
        self.assertEqual(_targets._clean_mark(u"   "), u"")

    def test_bool_is_not_a_mark(self):
        # 标记误配到勾选列时不能被当成角色/组号
        self.assertEqual(_targets._clean_mark(True), u"")
        self.assertEqual(_targets._clean_mark(False), u"")

    def test_numbers_and_strip(self):
        self.assertEqual(_targets._clean_mark(1), u"1")
        self.assertEqual(_targets._clean_mark(1.0), u"1.0")
        self.assertEqual(_targets._clean_mark(u"  name  "), u"name")


class ReadGroupTest(unittest.TestCase):
    """`read_acquisition_group`：0 = 不参与；兼容 int / float / str"""

    def test_openpyxl_type_variants(self):
        for raw, expected in ((1, 1), (1.0, 1), (u"1", 1), (u"1.0", 1),
                              ("2", 2), (3, 3)):
            self.assertEqual(
                _targets.read_acquisition_group(
                    _interim("k", group=raw)), expected,
                u"group=%r 应解析成 %r" % (raw, expected))

    def test_zero_and_negative_mean_not_participating(self):
        for raw in (0, u"0", 0.0, -1, u"-2"):
            self.assertEqual(
                _targets.read_acquisition_group(_interim("k", group=raw)), 0)

    def test_garbage_and_no_value(self):
        for raw in (u"<NO_VALUE>", u"", u"abc", None, True):
            self.assertEqual(
                _targets.read_acquisition_group(_interim("k", group=raw)), 0)

    def test_missing_key(self):
        self.assertEqual(_targets.read_acquisition_group(_interim("k")), 0)


class ReadRoleTest(unittest.TestCase):

    def test_known_roles(self):
        self.assertEqual(
            _targets.read_acquisition_role(_interim("k", role=u"name")),
            _targets.ROLE_NAME)
        self.assertEqual(
            _targets.read_acquisition_role(_interim("k", role=u"WEIGHT")),
            _targets.ROLE_WEIGHT)

    def test_unknown_or_no_value(self):
        for raw in (u"area", u"<NO_VALUE>", u"", None):
            self.assertEqual(
                _targets.read_acquisition_role(_interim("k", role=raw)), u"")


class BuildDefinitionsTest(unittest.TestCase):
    """`build_definitions_for_interims`：标记 → 目标位定义"""

    def test_case1_scalar_one_name_two_weights(self):
        """情况1：1 个名称 + 2 个重量，同一组（3 列单行）"""
        interims = [
            _interim(u"imp_main_name", u"主成分名称", u"name", 1, u"string"),
            _interim(u"imp_dilution", u"稀释倍数"),          # 纯计算字段
            _interim(u"std1_weight", u"对照品1称样量(mg)", u"weight", 1),
            _interim(u"std2_weight", u"对照品2称样量(mg)", u"weight", 1),
        ]
        definitions = _targets.build_definitions_for_interims(interims)
        self.assertEqual(len(definitions), 3)
        # 名称在前、重量在后；同角色多字段按快照出现序
        self.assertEqual([d["interim_keyword"] for d in definitions],
                         [u"imp_main_name", u"std1_weight", u"std2_weight"])
        # 标题取 interim 自己的 title —— 能区分对照品 1 / 2
        self.assertEqual(definitions[1]["display_title"],
                         u"对照品1称样量(mg)")
        self.assertEqual(definitions[2]["display_title"],
                         u"对照品2称样量(mg)")
        # 角色推导出的元数据
        self.assertEqual(definitions[0]["value_type"], "string")
        self.assertFalse(definitions[0]["allow_multi_assign"])
        self.assertTrue(definitions[0]["manual_input"])
        self.assertEqual(definitions[1]["value_type"], "float")
        self.assertTrue(definitions[1]["allow_multi_assign"])
        self.assertFalse(definitions[1]["manual_input"])
        for definition in definitions:
            self.assertEqual(definition["acquisition_group"], 1)
            self.assertEqual(definition["target_key"],
                             definition["interim_keyword"])

    def test_any_number_of_weights_in_one_group(self):
        """★ 对重量个数免疫（Backlog S5 判据②b）

        「固定 5 列」只约束表头；一组里 1 / 2 / 3 / 7 个 `weight` 都要能装下
        （模板在「重量」格内纵向堆叠）。这里断言推导层不设上限、次序稳定。
        """
        for count in (1, 2, 3, 7):
            interims = [_interim(u"the_name", u"名称", u"name", 1, u"string")]
            for i in range(count):
                interims.append(_interim(
                    u"w%d" % i, u"称样量%d" % i, u"weight", 1))
            definitions = _targets.build_definitions_for_interims(interims)
            weights = [d for d in definitions
                       if d["acquisition_role"] == _targets.ROLE_WEIGHT]
            self.assertEqual(len(weights), count,
                             u"%d 个重量字段应全部保留" % count)
            # 名称恒在最前，重量按快照出现序
            self.assertEqual(definitions[0]["interim_keyword"], u"the_name")
            self.assertEqual([d["interim_keyword"] for d in weights],
                             [u"w%d" % i for i in range(count)])

    def test_case2_list_name_and_weight(self):
        """情况2：list 型的名称 + 重量（2 列多行）"""
        interims = [
            _interim(u"imp_name", u"物质名称", u"name", 1, u"list"),
            _interim(u"imp_weight", u"称样量(mg)", u"weight", 1, u"list"),
        ]
        definitions = _targets.build_definitions_for_interims(interims)
        self.assertEqual(len(definitions), 2)
        self.assertEqual([d["result_type"] for d in definitions],
                         [u"list", u"list"])

    def test_group_zero_is_skipped_silently(self):
        """`acquisition_group = 0` 的字段不参与，且**不该报警**"""
        warned = []
        interims = [
            _interim(u"pure_calc", u"纯计算"),
            _interim(u"zero_group", u"标了0", u"", 0),
        ]
        definitions = _targets.build_definitions_for_interims(
            interims, on_invalid=lambda kw, reason: warned.append(kw))
        self.assertEqual(definitions, [])
        self.assertEqual(warned, [])

    def test_no_value_pair_is_skipped_silently(self):
        """两个标记都是 `<NO_VALUE>`（点过保存的 Calculation）→ 静默跳过

        ★ 不归一的话 role 是非空字符串、group 也是真值，这个字段会被
        当成"已配置的采集目标"渲染出来 —— 正是 S2 误报 13 个字段的那个 bug。
        """
        warned = []
        interims = [_interim(u"f", u"字段", u"<NO_VALUE>", u"<NO_VALUE>")]
        definitions = _targets.build_definitions_for_interims(
            interims, on_invalid=lambda kw, reason: warned.append(kw))
        self.assertEqual(definitions, [])
        self.assertEqual(warned, [])

    def test_half_configured_is_reported(self):
        """只配了一半 → 跳过但**必须留痕**（R9）"""
        warned = []
        interims = [
            _interim(u"only_role", u"只有角色", u"weight", None),
            _interim(u"only_group", u"只有组号", None, 1),
            _interim(u"bad_role", u"角色拼错", u"wieght", 1),
        ]
        definitions = _targets.build_definitions_for_interims(
            interims, on_invalid=lambda kw, reason: warned.append(kw))
        self.assertEqual(definitions, [])
        self.assertEqual(sorted(warned),
                         [u"bad_role", u"only_group", u"only_role"])

    def test_multiple_groups_kept_apart(self):
        interims = [
            _interim(u"n1", u"名称1", u"name", 1, u"list"),
            _interim(u"w1", u"重量1", u"weight", 1, u"list"),
            _interim(u"n2", u"名称2", u"name", 2, u"list"),
            _interim(u"w2", u"重量2", u"weight", 2, u"list"),
        ]
        definitions = _targets.build_definitions_for_interims(interims)
        groups = {}
        for definition in definitions:
            groups.setdefault(definition["acquisition_group"], []).append(
                definition["interim_keyword"])
        self.assertEqual(sorted(groups.keys()), [1, 2])
        self.assertEqual(sorted(groups[1]), [u"n1", u"w1"])
        self.assertEqual(sorted(groups[2]), [u"n2", u"w2"])

    def test_empty_and_none_interims(self):
        self.assertEqual(_targets.build_definitions_for_interims(None), [])
        self.assertEqual(_targets.build_definitions_for_interims([]), [])

    def test_missing_keyword_is_skipped(self):
        self.assertEqual(
            _targets.build_definitions_for_interims(
                [_interim(u"", u"无 keyword", u"name", 1)]), [])

    def test_title_falls_back_to_keyword(self):
        definitions = _targets.build_definitions_for_interims(
            [{"keyword": u"kw_only",
              _targets.ACQUISITION_ROLE_KEY: u"name",
              _targets.ACQUISITION_GROUP_KEY: 1}])
        self.assertEqual(definitions[0]["display_title"], u"kw_only")


class RoleMetaTest(unittest.TestCase):

    def test_vocabulary_is_exactly_two_roles(self):
        # 需求方案 §4.1 只定义了 name / weight 两个取值
        self.assertEqual(sorted(_targets.ACQUISITION_ROLE_META),
                         [_targets.ROLE_NAME, _targets.ROLE_WEIGHT])

    def test_meta_keys_complete(self):
        for role, meta in _targets.ACQUISITION_ROLE_META.items():
            for key in ("display_order", "value_type",
                        "allow_multi_assign", "manual_input"):
                self.assertIn(key, meta, u"%s 缺 %s" % (role, key))

    def test_name_sorts_before_weight(self):
        self.assertLess(
            _targets.ACQUISITION_ROLE_META[_targets.ROLE_NAME]["display_order"],
            _targets.ACQUISITION_ROLE_META[_targets.ROLE_WEIGHT]["display_order"])


class ArrayResultTypeTest(unittest.TestCase):

    def test_array_types(self):
        for rt in ("list", "multiselect", "multiselect_duplicates",
                   "multichoice", u"LIST", u"  list  "):
            self.assertTrue(_targets.is_array_result_type(rt), rt)

    def test_scalar_types(self):
        for rt in ("numeric", "string", "select", "calculated", u"", None):
            self.assertFalse(_targets.is_array_result_type(rt), rt)


class TargetKeyTest(unittest.TestCase):

    def test_make_and_parse_target_key(self):
        target_key = _targets.make_target_key("uid-123", "imp_weight")
        analysis_uid, keyword = _targets.parse_target_key(target_key)
        self.assertEqual(analysis_uid, "uid-123")
        self.assertEqual(keyword, "imp_weight")

    def test_make_and_parse_with_seq(self):
        target_key = _targets.make_target_key("uid-123", "imp_weight", 2)
        self.assertEqual(_targets.parse_target_key_full(target_key),
                         ("uid-123", "imp_weight", 2))
        # 不带序号的两段式 = 基础行 seq 0
        self.assertEqual(
            _targets.parse_target_key_full(
                _targets.make_target_key("uid-123", "imp_weight")),
            ("uid-123", "imp_weight", 0))

    def test_parse_target_key_invalid(self):
        self.assertEqual(_targets.parse_target_key(""), (None, None))
        self.assertEqual(_targets.parse_target_key("no-separator"), (None, None))
        self.assertEqual(_targets.parse_target_key("uid:"), (None, None))
        self.assertEqual(_targets.parse_target_key(":kw"), (None, None))

    def test_parse_target_key_bad_seq(self):
        self.assertEqual(_targets.parse_target_key_full("uid:kw:x"),
                         (None, None, None))


class ConstantsTest(unittest.TestCase):

    def test_token_constant(self):
        self.assertTrue(_targets.PHASE1_INGEST_TOKEN)

    def test_annotation_keys(self):
        self.assertTrue(_targets.PHASE1_ANNOTATION_KEY)
        self.assertTrue(_targets.PHASE1_SESSION_INDEX_KEY)

    def test_mark_keys_match_calcenhance_subfields(self):
        # 这两个名字必须与 maitux.calcenhance 注册的 subfield 完全一致，
        # 否则标记读不到而且**不报错**
        self.assertEqual(_targets.ACQUISITION_ROLE_KEY, "acquisition_role")
        self.assertEqual(_targets.ACQUISITION_GROUP_KEY, "acquisition_group")

    def test_no_hardcoded_target_keywords_left(self):
        """★ 回归判据：写死的 T_name / T_weight 不能再出现"""
        for name in ("T_NAME_KEYWORD", "T_WEIGHT_KEYWORD",
                     "PHASE1_KEYWORDS", "PHASE1_TARGET_DEFINITIONS"):
            self.assertFalse(hasattr(_targets, name),
                             u"%s 应已随 S5 删除" % name)


if __name__ == "__main__":
    unittest.main()
