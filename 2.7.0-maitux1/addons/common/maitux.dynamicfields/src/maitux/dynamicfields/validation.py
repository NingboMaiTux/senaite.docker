# -*- coding: utf-8 -*-
"""字段定义校验

校验必须在**写入路径**上，不能只靠界面控制显隐——模板管渲染，构造请求可以
绕过它（与 maitux.reviewerassignment 里那条同源的教训）。
"""
import re

from maitux.dynamicfields import config
from maitux.dynamicfields import storage

_NAME_RE = re.compile(config.FIELD_NAME_PATTERN)
_OPTION_RE = re.compile(config.OPTION_KEY_PATTERN)


def validate_record(record, portal=None, existing_id=None,
                    skip_uniqueness=False):
    """返回问题列表；空列表 = 通过

    :param existing_id: 编辑时传本条 id，避免跟自己冲突
    :param skip_uniqueness: 导入时用——同批次内的先后顺序不该判为冲突
    """
    problems = []

    portal_type = record.get("portal_type")
    if not portal_type:
        problems.append(u"必须指定目标对象")
    elif portal_type in config.EXCLUDED_TYPES:
        problems.append(u"对象类型 %s 已被明确排除，不能加字段" % portal_type)
    elif portal_type not in config.ALLOWED_TYPES:
        problems.append(u"对象类型 %s 不在支持清单内" % portal_type)

    name = record.get("name") or ""
    if not name:
        problems.append(u"必须填字段名")
    elif not _NAME_RE.match(name):
        problems.append(
            u"字段名只能是 ASCII 小写字母开头、由小写字母/数字/下划线组成，"
            u"长度 2-50：%s" % name)
    elif name in config.RESERVED_NAMES:
        problems.append(u"%s 是保留名，不能用作字段名" % name)

    field_type = record.get("type")
    if field_type not in config.FIELD_TYPE_IDS:
        problems.append(u"字段类型不合法：%s" % field_type)

    if not _has_any_label(record):
        problems.append(u"至少要填一种语言的标签")

    problems.extend(_validate_type_specific(record, field_type))

    if portal_type and name and not skip_uniqueness:
        problems.extend(
            _validate_uniqueness(portal_type, name, portal, existing_id))

    if portal_type and existing_id is None and not skip_uniqueness:
        problems.extend(_validate_quota(portal_type, portal))

    return problems


# --------------------------------------------------------------------------

def _has_any_label(record):
    labels = record.get("labels") or {}
    for value in labels.values():
        if value and u"%s" % value.strip():
            return True
    return False


def _validate_type_specific(record, field_type):
    problems = []

    if field_type in config.TYPES_WITH_OPTIONS:
        options = record.get("options") or []
        if not options:
            problems.append(u"固定选项类型必须至少配一个选项")
        seen = set()
        for option in options:
            key = (option or {}).get("key") or ""
            if not key:
                problems.append(u"选项的存储值不能为空")
                continue
            if not _OPTION_RE.match(key):
                # 设计红线：一旦把中文存进对象，这份数据永远翻译不了，
                # 索引、导出、统计也全部锁死在中文上
                problems.append(
                    u"选项存储值必须是 ASCII（字母数字、下划线、连字符）："
                    u"%s —— 中文只能填在标签里" % key)
                continue
            if key in seen:
                problems.append(u"选项存储值重复：%s" % key)
            seen.add(key)
            if not _option_has_label(option):
                problems.append(u"选项 %s 至少要填一种语言的标签" % key)

    if field_type == config.TYPE_REFERENCE:
        allowed = record.get("allowed_types") or []
        if not allowed:
            problems.append(u"对象引用类型必须指定允许的对象类型")

    if field_type in config.TYPES_NUMERIC:
        minimum = record.get("min")
        maximum = record.get("max")
        if minimum is not None and maximum is not None:
            try:
                if float(minimum) > float(maximum):
                    problems.append(u"最小值不能大于最大值")
            except (TypeError, ValueError):
                problems.append(u"最小值 / 最大值必须是数字")

    regex = record.get("regex")
    if regex:
        try:
            re.compile(regex)
        except Exception as exc:
            problems.append(u"校验正则不合法：%s" % exc)
        if not _regex_msg_ok(record):
            problems.append(u"填了校验正则就必须填校验失败提示")

    if record.get("show_list") and not record.get("metadata"):
        problems.append(
            u"要在列表页显示，必须同时勾选「创建 metadata 列」"
            u"——没有它列表页取不到值")

    return problems


def _option_has_label(option):
    labels = (option or {}).get("labels") or {}
    for value in labels.values():
        if value and u"%s" % value.strip():
            return True
    return False


def _regex_msg_ok(record):
    messages = record.get("regex_msg") or {}
    for value in messages.values():
        if value and u"%s" % value.strip():
            return True
    return False


def _validate_uniqueness(portal_type, name, portal, existing_id):
    """与原生字段、其它 add-on 字段、本包已有字段都不得重名"""
    problems = []

    for record in storage.get_records_for_type(portal_type, portal):
        if record.get("name") == name and record.get("id") != existing_id:
            problems.append(u"该对象上已经有一个叫 %s 的自定义字段" % name)
            break

    # 原生字段 / 其它 add-on 的字段
    try:
        from maitux.dynamicfields import introspect
        foreign = introspect.get_foreign_field_names(portal_type)
    except Exception:
        foreign = set()
    if name in foreign:
        problems.append(
            u"%s 上已经存在同名字段（原生或其它 add-on 提供），换一个名字"
            % portal_type)

    return problems


def _validate_quota(portal_type, portal):
    problems = []
    if storage.count_for_type(portal_type, portal) >= config.MAX_FIELDS_PER_TYPE:
        problems.append(
            u"单个对象最多 %s 个自定义字段，已达上限"
            % config.MAX_FIELDS_PER_TYPE)
    if storage.count_all(portal) >= config.MAX_FIELDS_TOTAL:
        problems.append(
            u"全站最多 %s 个自定义字段，已达上限" % config.MAX_FIELDS_TOTAL)
    return problems
