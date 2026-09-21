# -*- coding: utf-8 -*-
"""用户自建字段标签的翻译：本包自注册一个 ITranslationDomain

**标准 gettext 在这里走不通**：字段是运行时通过网页建出来的，不可能预先准备
`.po`；运行时写 `.po` / `.mo` 也没用——已注册的 catalog 不会重新加载，按仓库
规则 R8 得重启容器才生效。所以文案必须**作为数据存**，跟字段定义放在一起。

做法：翻译域在 Zope 里就是一个实现了 ``translate()`` 的 utility，接口并没有
规定它必须查 `.mo`。本包注册一个域（``maitux.dynamicfields.labels``），它的
``translate()`` 转而查配置库。

回报是整条渲染链自动就对了——z3c.form 标签、AT widget label、模板
``i18n:translate``——这些渲染器一行都不用改。本模块只用到 zope.i18n，
与 senaite.core 无关。

★ 两条硬约束，违反了会在生产上翻车：

1. **不能在构建 schema 时把当前语言的文案烤进 title。**
   schema 是构建一次然后缓存的，不是每请求构建。烤进去的后果是"第一个发起
   请求的人的语言变成之后所有人看到的语言"，而且单人测试百分之百测不出来。
   ``Message`` 是延迟求值对象，查表发生在渲染那一刻、带着当时那个 request
   的语言——这才是对的。

2. **msgid 和 default 一律 ASCII，中文只活在配置库里。**
   漏翻的地方至少显示正常英文而非乱码；更要紧的是 Py2 下非 ASCII 的 msgid
   撞上 ``str()`` 或 ascii 解码会直接抛异常（见 INNOCARE.arextension
   patches.py 里那段 UnicodeDecodeError 兜底）。
"""
from zope.i18n.interfaces import ITranslationDomain
from zope.interface import implementer

from maitux.dynamicfields import LABELS_DOMAIN
from maitux.dynamicfields import labelMessageFactory
from maitux.dynamicfields import storage

try:
    from bika.lims import api
except ImportError:  # pragma: no cover
    api = None


#: msgid 前缀
KIND_LABEL = "label"
KIND_DESCRIPTION = "desc"
KIND_OPTION = "opt"


# --------------------------------------------------------------------------
# msgid 构造
# --------------------------------------------------------------------------

def make_msgid(kind, field_id, extra=None):
    """msgid 全 ASCII。用字段 id 而不是字段名——改名不会丢文案"""
    parts = [str(kind), str(field_id)]
    if extra is not None:
        parts.append(str(extra))
    return ":".join(parts)


def parse_msgid(msgid):
    """msgid -> (kind, field_id, extra)；不是本域的返回 (None, None, None)"""
    try:
        parts = str(msgid).split(":")
    except Exception:
        return None, None, None
    if len(parts) == 2:
        return parts[0], parts[1], None
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    return None, None, None


def label_message(record):
    """字段标签的 Message。**延迟求值**，不要在这里拿当前语言"""
    return labelMessageFactory(
        make_msgid(KIND_LABEL, record.get("id")),
        default=ascii_fallback(record, KIND_LABEL))


def description_message(record):
    return labelMessageFactory(
        make_msgid(KIND_DESCRIPTION, record.get("id")),
        default=ascii_fallback(record, KIND_DESCRIPTION))


def option_message(record, key):
    return labelMessageFactory(
        make_msgid(KIND_OPTION, record.get("id"), key),
        default=safe_ascii(key))


def safe_ascii(value):
    """把任意值压成 ASCII unicode。非 ASCII 一律丢掉——default 绝不能带中文"""
    if value is None:
        return u""
    try:
        if not isinstance(value, unicode):  # noqa: F821  (Py2)
            value = unicode(value, "utf-8", "ignore")  # noqa: F821
    except NameError:  # pragma: no cover - Py3
        value = u"%s" % value
    except Exception:
        return u""
    return value.encode("ascii", "ignore").decode("ascii")


def ascii_fallback(record, kind):
    """default 值：优先英文文案，没有就用字段名。保证永远是 ASCII"""
    mapping = record.get("labels") if kind == KIND_LABEL \
        else record.get("descriptions")
    mapping = mapping or {}
    for lang in ("en", "en-us", "en-gb"):
        text = mapping.get(lang)
        if text:
            ascii_text = safe_ascii(text)
            if ascii_text.strip():
                return ascii_text
    if kind == KIND_LABEL:
        return safe_ascii(record.get("name") or u"")
    return u""


# --------------------------------------------------------------------------
# 语言归一化
# --------------------------------------------------------------------------

def normalize_language(lang):
    """``zh_CN`` / ``zh-CN`` / ``zh-cn`` 一律归一成 ``zh-cn``

    现有每个 addon 都铺四份 locale 目录（en / zh / zh-cn / zh_CN）就是在硬扛
    这件事。存成数据以后归一一次就够了。
    """
    if not lang:
        return u""
    try:
        text = lang if isinstance(lang, type(u"")) else lang.decode("utf-8", "ignore")
    except Exception:
        return u""
    return text.strip().replace(u"_", u"-").lower()


def base_language(lang):
    """``zh-cn`` -> ``zh``；本来就是基础语言时原样返回"""
    normalized = normalize_language(lang)
    return normalized.split(u"-")[0] if u"-" in normalized else normalized


def language_candidates(lang, site_default=None):
    """查表顺序：精确 -> 基础语言（zh-cn -> zh）-> 站点默认 -> 其基础语言

    只**收窄**，不放宽。放宽（zh -> zh-cn）要看实际存了哪些语言，
    所以在 match_language() 里做。
    """
    candidates = []

    def push(value):
        value = normalize_language(value)
        if value and value not in candidates:
            candidates.append(value)

    push(lang)
    push(base_language(lang))
    push(site_default)
    push(base_language(site_default))
    return candidates


def match_language(texts, lang, site_default=None):
    """从 {归一化语言: 文案} 里挑一条；挑不到返回 None

    查找顺序（前三步针对请求语言，之后才轮到站点默认）：

    1. 精确匹配             ``zh-cn`` -> ``zh-cn``
    2. 收窄到基础语言       ``zh-cn`` -> ``zh``
    3. **放宽到同族变体**   ``zh``    -> ``zh-cn``   ← 浏览器发裸 zh 很常见
    4. 站点默认语言及其基础语言
    5. 任意一条非空 —— 绝不允许标签渲染成空白

    第 3 步是实测补的：只做收窄的话，请求 ``zh`` 而库里存的是 ``zh-cn`` 时会
    一路掉到站点默认（英文），中文站点上看到英文标签。
    """
    if not texts:
        return None

    requested = normalize_language(lang)
    for candidate in (requested, base_language(requested)):
        if candidate and texts.get(candidate):
            return texts[candidate]

    # 放宽：请求 zh，库里有 zh-cn / zh-tw，挑基础语言相同的第一条
    base = base_language(requested)
    if base:
        for key in sorted(texts.keys()):
            if texts[key] and base_language(key) == base:
                return texts[key]

    for candidate in (normalize_language(site_default),
                      base_language(site_default)):
        if candidate and texts.get(candidate):
            return texts[candidate]

    for key in sorted(texts.keys()):
        if texts[key]:
            return texts[key]
    return None


def get_site_languages(portal=None):
    """站点实际启用的语言。配置页按它动态生成输入框，不写死中 / 英"""
    default = [u"zh-cn", u"en"]
    if api is None:
        return default
    try:
        tool = api.get_tool("portal_languages")
    except Exception:
        return default
    if tool is None:
        return default
    try:
        languages = [normalize_language(l)
                     for l in (tool.getSupportedLanguages() or [])]
    except Exception:
        return default
    languages = [l for l in languages if l]
    return languages or default


def get_default_language(portal=None):
    if api is None:
        return u"en"
    try:
        tool = api.get_tool("portal_languages")
        if tool is not None:
            return normalize_language(tool.getDefaultLanguage()) or u"en"
    except Exception:
        pass
    return u"en"


def get_request_language(request):
    """当前请求的语言。Plone 的语言协商会把它放在 request 的 LANGUAGE 上"""
    if request is None:
        return u""
    try:
        return normalize_language(request.get("LANGUAGE", None))
    except Exception:
        return u""


# --------------------------------------------------------------------------
# 翻译域实现
# --------------------------------------------------------------------------

@implementer(ITranslationDomain)
class DynamicLabelsDomain(object):
    """查配置库而不是 .mo 的翻译域

    注册为**具名 utility**（name = 域名），``zope.i18n.translate`` 就是按域名
    找 utility 的。
    """

    domain = LABELS_DOMAIN

    def translate(self, msgid, mapping=None, context=None,
                  target_language=None, default=None, msgid_plural=None,
                  default_plural=None, number=None):
        try:
            return self._translate(msgid, context, target_language, default)
        except Exception:
            # 翻译永远不许把页面搞挂：兜底回 default 或 msgid 本身
            if default is not None:
                return default
            return msgid

    # ----------------------------------------------------------------

    def _translate(self, msgid, context, target_language, default):
        kind, field_id, extra = parse_msgid(msgid)
        if kind is None:
            return default if default is not None else msgid

        record = storage.get_record(field_id)
        if record is None:
            # 字段已被删除，但页面上还残留着引用
            return default if default is not None else msgid

        texts = self._texts_for(record, kind, extra)
        if not texts:
            return self._fallback(record, kind, extra, default, msgid)

        lang = target_language or get_request_language(context)
        matched = match_language(texts, lang, get_default_language())
        if matched:
            return matched
        return self._fallback(record, kind, extra, default, msgid)

    def _texts_for(self, record, kind, extra):
        """取出 {归一化语言: 文案}"""
        if kind == KIND_LABEL:
            raw = record.get("labels") or {}
        elif kind == KIND_DESCRIPTION:
            raw = record.get("descriptions") or {}
        elif kind == KIND_OPTION:
            raw = {}
            for option in record.get("options") or []:
                if str(option.get("key")) == str(extra):
                    raw = option.get("labels") or {}
                    break
        else:
            raw = {}
        texts = {}
        for lang, text in raw.items():
            key = normalize_language(lang)
            if key and text:
                texts[key] = text
        return texts

    def _fallback(self, record, kind, extra, default, msgid):
        if default:
            return default
        if kind == KIND_OPTION:
            return extra or msgid
        if kind == KIND_DESCRIPTION:
            return u""
        return record.get("name") or msgid


#: ZCML 注册的就是这个实例
dynamic_labels_domain = DynamicLabelsDomain()


# --------------------------------------------------------------------------
# 给视图用的直接取值（不经翻译域，省一层）
# --------------------------------------------------------------------------

def pick_text(mapping, lang, fallback=u""):
    """按语言回落链从 {lang: text} 里挑一个。绝不返回空白（除非全空）"""
    if not mapping:
        return fallback
    texts = {}
    for key, value in mapping.items():
        normalized = normalize_language(key)
        if normalized and value:
            texts[normalized] = value
    if not texts:
        return fallback
    matched = match_language(texts, lang, get_default_language())
    return matched if matched else fallback
