# -*- coding: utf-8 -*-
"""让稳定性容器类的 Title() 按当前语言翻译（与 maitux.stock.title 同一套路）。"""

import re

from bika.lims import api

from maitux.stability.i18n import translate_stability


# 复制方案名称的后缀分隔符与别名。
# 中文注释：``Copy`` 是英文 msgid（落库用），其余是历史数据的写法 ——
# 早期版本把翻译后的后缀直接存进了 Title，所以中文站复制出来的方案
# 切到英文站会一直显示"副本"。这里统一在渲染阶段换回当前语言。
COPY_SUFFIX_SEPARATOR = u" - "
COPY_SUFFIX_ALIASES = (
    u"Copy",
    u"副本",
    u"复制件",
    u"拷贝",
    u"拷貝",
)


def strip_copy_suffix(raw):
    """去掉名称末尾的"副本"后缀（任意语言写法），返回纯原标题。"""
    if not raw:
        return raw
    for alias in COPY_SUFFIX_ALIASES:
        marker = COPY_SUFFIX_SEPARATOR + alias
        if raw.endswith(marker):
            return raw[:-len(marker)]
    return raw


def localize_copy_suffix(raw):
    """把名称末尾的"副本"后缀换成当前语言的写法。

    只处理 ``原标题 - <后缀>`` 这一种形态，其它标题原样返回。
    """
    if not raw:
        return raw
    for alias in COPY_SUFFIX_ALIASES:
        marker = COPY_SUFFIX_SEPARATOR + alias
        if raw.endswith(marker):
            base = raw[:-len(marker)]
            return u"{0}{1}{2}".format(
                base, COPY_SUFFIX_SEPARATOR, translate_stability(u"Copy"))
    return raw


# 时间点任务标题的形态：``TP 1 (3 Months)``（subscribers.py 生成时写死英文）。
TASK_TITLE_PATTERN = re.compile(u"^TP (\\d+) \\((\\d+) Months\\)$")


def localize_task_title(raw):
    """把 ``TP 1 (3 Months)`` 按当前语言重写成 ``TP 1（3 个月）``。

    中文注释：时间点任务的 Title 是**生成时写死的英文**并存进了 ZODB，
    只做目录查询是查不到译文的，所以这里按形态识别后重建。
    """
    if not raw:
        return raw
    match = TASK_TITLE_PATTERN.match(raw)
    if not match:
        return raw
    pattern = translate_stability(u"TP {0} ({1} Months)")
    try:
        return pattern.format(match.group(1), match.group(2))
    except Exception:
        return raw


class TranslatableTitleMixin(object):
    """Title() 返回当前语言的标题；取不到译文时原样返回英文 msgid。

    **没有请求时不翻译**：安装/编目在 ``bin/instance run`` 里执行（无 request），
    此时必须让 uid_catalog 索引到原始英文 msgid，否则菜单会随编目时的语言变化。
    """

    def raw_title(self):
        value = getattr(self, "title", None)
        if value:
            return value
        getter = getattr(self, "getId", None)
        return getter() if callable(getter) else u""

    def Title(self):
        raw = self.raw_title()
        if not raw:
            return u""
        try:
            if api.get_request() is None:
                return raw
        except Exception:
            return raw
        return translate_stability(
            localize_task_title(localize_copy_suffix(raw))) or raw
