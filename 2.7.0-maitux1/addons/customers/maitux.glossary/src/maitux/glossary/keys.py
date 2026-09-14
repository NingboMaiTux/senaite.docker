# -*- coding: utf-8 -*-
#
# 纯函数：安全取字符 + 确定性行 ID
#
# 这个模块**不 import 任何 Zope / senaite 模块**，因此可以在没有 Zope
# 的环境里直接导入（离线自检 tests/run_offline.py 依赖这一点）。

import hashlib
import re
import sys

from maitux.glossary.config import ID_HASH_LEN
from maitux.glossary.config import ID_SLUG_MAX

#: py2 的 unicode / py3 的 str —— 本模块要在两种解释器下都能被离线自检导入
if sys.version_info[0] < 3:  # pragma: no cover
    _TEXT_TYPES = (str, unicode)  # noqa: F821
    _BYTES_TYPES = (str,)
else:  # pragma: no cover
    _TEXT_TYPES = (str,)
    _BYTES_TYPES = (bytes,)

#: ID 里允许出现的字符。keyword 的合法字符是 [A-Za-z\w\d\-_]，
#: 其中 \w 在 unicode 下**包含 CJK**（见 analysisservice.RX_SERVICE_KEYWORD），
#: 所以非 ASCII 一律换成 "_"。
#: 注意：这里**不能**写 ``ur"..."``（py2 合法、py3 是 SyntaxError），
#: 把 ``-`` 放在字符类末尾就不需要转义了。
RX_UNSAFE_ID = re.compile(u"[^A-Za-z0-9_-]")


def safe_unicode(value):
    """None/str/bytes/unicode -> unicode（py2、py3 都可用）。

    Py2 下对可能含非 ASCII 的值一律走这里，不用 ``str()``（规则 R13）。
    解码顺序保持老行为：先 utf-8，失败再 latin-1 兜底（别改成 replace，
    那是另一种语义）。
    """
    if value is None:
        return u""
    if isinstance(value, _TEXT_TYPES) and not isinstance(value, bytes):
        return value
    if isinstance(value, (_BYTES_TYPES + (bytearray,))):
        raw = bytes(value)
        try:
            return raw.decode("utf-8")
        except Exception:
            try:
                return raw.decode("latin-1", "replace")
            except Exception:
                return u""
    return u"%s" % (value,)


def text(value):
    """取字段值为去空白的 unicode。"""
    return safe_unicode(value).strip()


def make_entry_id(analysis_keyword, calc_keyword):
    """由 (analysis_keyword, calc_keyword) 计算确定性 ID。

    形如 ``imp_specificity-1a2b3c4d``：

      - 前缀是 analysis_keyword 的 slug，**只为人眼识别**（ZMI / URL）
      - 后缀是整对 key 的 md5 前 8 位 —— **唯一性由它保证**

    为什么不能只用 ``a__b`` 这类拼接：keyword 的合法字符里包含 ``_``，
    所以 ``a__b`` + ``c`` 与 ``a`` + ``b__c`` 会拼成同一个 ID。
    用 ``\\x00`` 分隔后再哈希，彻底避免这种歧义。

    确定性 ID 的两个好处（对应需求里的两条）：
      - 幂等：同一组合重复同步不会产生第二行
      - O(1) 定位：同步查"这行存不存在"直接 ``_getOb``，不用遍历/索引
    """
    analysis_keyword = text(analysis_keyword)
    calc_keyword = text(calc_keyword)
    raw = u"%s\x00%s" % (analysis_keyword, calc_keyword)
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()
    slug = RX_UNSAFE_ID.sub(u"_", analysis_keyword)
    slug = slug[:ID_SLUG_MAX].strip(u"_")
    return u"%s-%s" % (slug or u"kw", digest[:ID_HASH_LEN])
