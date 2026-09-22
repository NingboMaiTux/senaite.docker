# -*- coding: utf-8 -*-
"""maitux.dynamicfields 冒烟测试：在镜像的 zopepy 里跑，不需要起站点

覆盖的是最容易静默出错、手工点不出来的几条：

1. 存储 / 校验：字段名、保留名、Choice 的 key 必须 ASCII
2. 动态 DX schema 真的能造出来，字段顺序正确
3. ★ 同一个 schema 在不同语言的请求下渲染出不同标签
   —— 即"语言不能烤进缓存的 schema"，单人手测百分之百测不出来
4. behavior 工厂的属性转发（少了它保存的值会静默丢）
5. 脏配置不抛异常
"""
from __future__ import print_function

import glob
import sys

# zopepy 的 sys.path 只有 senaite.core。直接往 sys.path 追加不够——zope / plone
# 是命名空间包，一旦 zope.interface 先被导入，zope.__path__ 就定死了。走
# pkg_resources.working_set.add_entry()，它会顺带 fixup_namespace_packages。
import pkg_resources  # noqa: E402

for pattern in ("/home/senaite/senaitelims/eggs/cp27mu/*.egg",
                "/home/senaite/senaitelims/eggs/*.egg",
                "/home/senaite/senaitelims/develop-eggs/*.egg"):
    for path in sorted(glob.glob(pattern)):
        pkg_resources.working_set.add_entry(path)

sys.path.insert(0, "/opt/addons/common/maitux.dynamicfields/src")

FAILED = []


def _u(value):
    """任何东西 -> unicode。

    这个 helper 自己也踩过 Py2 的坑：格式串是 bytes、name 是 unicode、
    detail 是 utf-8 bytes，三者混进一个 % 里就会隐式 ASCII 解码然后炸。
    跟被测代码里那个 bug 同源。
    """
    if value is None:
        return u""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except Exception:
            return value.decode("utf-8", "ignore")
    try:
        return u"%s" % value
    except Exception:
        return u"<unprintable>"


def check(name, condition, detail=""):
    status = u"PASS" if condition else u"FAIL"
    line = u"[%s] %s %s" % (status, _u(name), _u(detail))
    print(line.encode("utf-8"))
    if not condition:
        FAILED.append(_u(name))


# --------------------------------------------------------------------------
# 假 portal：用内存字典冒充 annotation，避开起站点
# --------------------------------------------------------------------------

from zope.annotation.interfaces import IAnnotations       # noqa: E402
from zope.interface import implementer                    # noqa: E402

_STORE = {}


class FakePortal(object):
    pass


@implementer(IAnnotations)
class FakeAnnotations(dict):
    def __init__(self, context):
        dict.__init__(self)


from zope.component import provideAdapter, getGlobalSiteManager  # noqa: E402
from zope.interface import Interface                             # noqa: E402


class _Ann(object):
    def __init__(self, context):
        self.context = context

    def get(self, key, default=None):
        return _STORE.get(key, default)

    def __getitem__(self, key):
        return _STORE[key]

    def __setitem__(self, key, value):
        _STORE[key] = value

    def __contains__(self, key):
        return key in _STORE


provideAdapter(_Ann, adapts=(Interface,), provides=IAnnotations)

PORTAL = FakePortal()

from maitux.dynamicfields import storage        # noqa: E402
from maitux.dynamicfields import validation     # noqa: E402
from maitux.dynamicfields import i18n as mi18n  # noqa: E402
from maitux.dynamicfields import dxschema       # noqa: E402
from maitux.dynamicfields import config         # noqa: E402

# 让 storage 用我们的假 portal
storage.get_portal = lambda portal=None: PORTAL

print("=" * 66)
print("1. 存储与校验")
print("=" * 66)

rec = storage.defaults("Client", "credit_level", config.TYPE_CHOICE)
rec["labels"] = {"zh-cn": u"信用等级", "en": u"Credit Level"}
rec["options"] = [
    {"key": "a", "labels": {"zh-cn": u"甲级", "en": u"Grade A"}},
    {"key": "b", "labels": {"zh-cn": u"乙级", "en": u"Grade B"}},
]
problems = validation.validate_record(rec, skip_uniqueness=True)
check("合法记录通过校验", not problems, problems and str(problems[:1]) or "")

bad = storage.defaults("Client", "title", config.TYPE_TEXT)
bad["labels"] = {"en": u"X"}
# 消息已改成 Message，其值就是 msgid（英文 default 在 .po 里翻成中文）
check(u"保留名被拒绝",
      any(u"v_reserved" in u"%s" % p
          for p in validation.validate_record(bad, skip_uniqueness=True)))

bad2 = storage.defaults("Client", "grade", config.TYPE_CHOICE)
bad2["labels"] = {"en": u"X"}
bad2["options"] = [{"key": u"甲级", "labels": {"zh-cn": u"甲级"}}]
problems2 = validation.validate_record(bad2, skip_uniqueness=True)
check(u"Choice 的中文 key 被拒绝（设计红线）",
      any(u"v_option_ascii" in u"%s" % p for p in problems2))

bad3 = storage.defaults("Client", "x_list", config.TYPE_TEXT)
bad3["labels"] = {"en": u"X"}
bad3["show_list"] = True
bad3["metadata"] = False
check(u"勾了列表列但没勾 metadata 被拒绝",
      any(u"v_needs_metadata" in u"%s" % p
          for p in validation.validate_record(bad3, skip_uniqueness=True)))

rev_before = storage.get_revision()
storage.save_record(rec)
check("保存后 revision 自增", storage.get_revision() == rev_before + 1)
check("按类型能查回来", len(storage.get_records_for_type("Client")) == 1)

print()
print("=" * 66)
print("2. 动态 DX schema")
print("=" * 66)

text_rec = storage.defaults("Client", "contract_no", config.TYPE_TEXT)
text_rec["labels"] = {"zh-cn": u"合同编号", "en": u"Contract No."}
text_rec["order"] = 1
storage.save_record(text_rec)

schema = dxschema.get_schema("Client")
check("schema 造出来了", schema is not None)
if schema is not None:
    names = sorted(schema.names())
    check("两个字段都在", set(names) == set(["credit_level", "contract_no"]),
          str(names))
    from plone.autoform.interfaces import IFormFieldProvider
    check("schema 提供 IFormFieldProvider（否则表单取不到）",
          IFormFieldProvider.providedBy(schema))
    check("IFormFieldProvider(schema) 能取回自己",
          IFormFieldProvider(schema, None) is schema)

print()
print("=" * 66)
print("3. ★ 同一 schema，不同语言的请求要给出不同标签")
print("=" * 66)


class FakeRequest(dict):
    pass


from zope.i18n import translate as ztranslate  # noqa: E402
from zope.component import provideUtility      # noqa: E402
from zope.i18n.interfaces import ITranslationDomain  # noqa: E402

provideUtility(mi18n.dynamic_labels_domain, ITranslationDomain,
               name="maitux.dynamicfields.labels")

title = schema["credit_level"].title
check("title 是 Message（延迟求值）而不是已翻译的字符串",
      hasattr(title, "domain") and title.domain == "maitux.dynamicfields.labels",
      repr(title))

req_zh = FakeRequest()
req_zh["LANGUAGE"] = "zh-cn"
req_en = FakeRequest()
req_en["LANGUAGE"] = "en"

zh_text = ztranslate(title, context=req_zh)
en_text = ztranslate(title, context=req_en)
print("    zh-cn ->", zh_text.encode("utf-8"))
print("    en    ->", en_text.encode("utf-8"))
check("中文请求拿到中文", zh_text == u"信用等级")
check("英文请求拿到英文", en_text == u"Credit Level")
check("两种语言确实不同（语言没被烤进 schema）", zh_text != en_text)

# 归一化：zh_CN / zh-CN / zh 都要落到同一条
for variant in ("zh_CN", "zh-CN", "zh"):
    req = FakeRequest()
    req["LANGUAGE"] = variant
    got = ztranslate(title, context=req)
    check("语言写法 %s 归一化正确" % variant, got == u"信用等级",
          got.encode("utf-8"))

opt_msg = mi18n.option_message(storage.get_record_by_name("Client", "credit_level"), "a")
check("选项文案也分语言",
      ztranslate(opt_msg, context=req_zh) == u"甲级"
      and ztranslate(opt_msg, context=req_en) == u"Grade A")

print()
print("=" * 66)
print("4. behavior 工厂的属性转发")
print("=" * 66)


class FakeContent(object):
    portal_type = "Client"


obj = FakeContent()
behavior = dxschema.DynamicFieldsBehavior(obj)
behavior.contract_no = u"HT-2026-001"
check("写入转发到了底层对象（少了这层值会静默丢）",
      getattr(obj, "contract_no", None) == u"HT-2026-001")
check("读取也走底层对象", behavior.contract_no == u"HT-2026-001")

fresh = dxschema.DynamicFieldsBehavior(FakeContent())
check("没赋过值时回落默认值而不是抛 AttributeError",
      fresh.contract_no in (None, u""))

print()
print("=" * 66)
print(u"6. 九种字段类型：AT 和 DX 两条路都要能造出来")
print("=" * 66)

from maitux.dynamicfields import atfields   # noqa: E402
from maitux.dynamicfields import dxfields   # noqa: E402

check(u"Archetypes 可用（否则下面 AT 那一列没意义）", atfields.HAVE_AT)
check(u"senaite 字段可用（引用类型要用到）", atfields.HAVE_SENAITE)

for type_id, cn, en in config.FIELD_TYPES:
    rec = storage.defaults("Client", "probe_%s" % type_id, type_id)
    rec["labels"] = {"zh-cn": cn, "en": en}
    if type_id == config.TYPE_CHOICE:
        rec["options"] = [{"key": "a", "labels": {"zh-cn": u"甲", "en": u"A"}}]
    if type_id == config.TYPE_REFERENCE:
        rec["allowed_types"] = ["Client"]

    try:
        dx = dxfields.build_field(rec)
        dx_err = None
    except Exception as exc:
        dx, dx_err = None, repr(exc)
    try:
        at = atfields.build_field(rec)
        at_err = None
    except Exception as exc:
        at, at_err = None, repr(exc)

    check(u"%-8s DX 侧构造 (%s)" % (cn, dx.__class__.__name__ if dx else u"None"),
          dx is not None, dx_err or u"")
    check(u"%-8s AT 侧构造 (%s)" % (cn, at.__class__.__name__ if at else u"None"),
          at is not None, at_err or u"")

    # 标签必须是延迟求值的 Message，不能是已翻译的字符串
    if dx is not None:
        check(u"%-8s DX 标签是 Message" % cn,
              getattr(dx.title, "domain", None) == "maitux.dynamicfields.labels")
    if at is not None:
        label = at.widget.label
        check(u"%-8s AT 标签是 Message" % cn,
              getattr(label, "domain", None) == "maitux.dynamicfields.labels")
    # AT 侧必须带 add 键，否则样品新建页上不出现
    if at is not None:
        visible = at.widget.visible or {}
        check(u"%-8s AT visible 带 add 键（样品新建页要用）" % cn,
              visible.get("add") == "edit", repr(visible))

# 多值形态也要能造
for type_id in config.TYPES_MULTIVALUED:
    rec = storage.defaults("Client", "probe_multi_%s" % type_id, type_id)
    rec["labels"] = {"en": u"Multi"}
    rec["multi"] = True
    if type_id == config.TYPE_CHOICE:
        rec["options"] = [{"key": "a", "labels": {"en": u"A"}}]
    else:
        rec["allowed_types"] = ["Client"]
    check(u"%s 多值 DX 构造" % type_id, dxfields.build_field(rec) is not None)
    check(u"%s 多值 AT 构造" % type_id, atfields.build_field(rec) is not None)


print()
print("=" * 66)
print("5. 脏配置不许把页面搞挂")
print("=" * 66)

dirty = storage.defaults("NoSuchType", "ghost", "no_such_field_type")
dirty["labels"] = {"en": u"Ghost"}
storage.save_record(dirty)
try:
    result = dxschema.get_schema("NoSuchType")
    check("未知字段类型被跳过，不抛异常", result is None, repr(result))
except Exception as exc:
    check("未知字段类型被跳过，不抛异常", False, repr(exc))

try:
    still = dxschema.get_schema("Client")
    check("同类型的好字段不受脏记录连累",
          still is not None and len(still.names()) == 2)
except Exception as exc:
    check("同类型的好字段不受脏记录连累", False, repr(exc))


print()
print("=" * 66)
print(u"7. 视图层：request 里的中文是 bytes，不是 unicode")
print("=" * 66)
print(u"    —— 搜索框输中文就崩的那个 bug 的回归用例")
print()

# Py2 下 Zope 的 request 给回来的表单值常常是 utf-8 bytes 而不是 unicode。
# 对 bytes 调 .encode("utf-8") 会先用 ASCII 隐式解码 -> UnicodeDecodeError。
# 这一节就是复现那条路径。

from maitux.dynamicfields.browser import view as mdf_view  # noqa: E402
from maitux.dynamicfields import introspect as mdf_intro   # noqa: E402

CN_BYTES = u"样品".encode("utf-8")   # '样品' 的 utf-8 字节串
CN_TEXT = u"样品"


class FakeReq(dict):
    method = "GET"


for label, raw in ((u"bytes", CN_BYTES), (u"unicode", CN_TEXT)):
    req = FakeReq()
    req["q"] = raw
    req["fq"] = raw
    v = mdf_view.DynamicFieldsView(None, req)
    try:
        q = v.search_query()
        check(u"search_query 吃 %s 中文" % label,
              q == CN_TEXT, repr(q))
    except Exception as exc:
        check(u"search_query 吃 %s 中文" % label, False, repr(exc))
    try:
        fq = v.field_query()
        check(u"field_query 吃 %s 中文" % label, fq == CN_TEXT, repr(fq))
    except Exception as exc:
        check(u"field_query 吃 %s 中文" % label, False, repr(exc))
    try:
        suffix = v.link_suffix()
        check(u"link_suffix 吃 %s 中文（原 bug 就死在这）" % label,
              suffix.startswith(u"&q=") and u"%" in suffix, repr(suffix))
    except Exception as exc:
        check(u"link_suffix 吃 %s 中文（原 bug 就死在这）" % label,
              False, repr(exc))

# 关键字匹配两侧都可能是 bytes / unicode 混搭
try:
    check(u"_matches: bytes 关键字 vs unicode 文本",
          mdf_intro._matches(CN_BYTES, CN_TEXT))
    check(u"_matches: unicode 关键字 vs bytes 文本",
          mdf_intro._matches(CN_TEXT, CN_BYTES))
    check(u"_matches: 不匹配时返回 False",
          not mdf_intro._matches(CN_BYTES, u"Client"))
except Exception as exc:
    check(u"_matches 处理中文", False, repr(exc))

# 空关键字不能把所有东西过滤掉
check(u"空关键字放行全部", mdf_intro._matches(u"", u"anything"))
check(u"None 关键字放行全部", mdf_intro._matches(None, u"anything"))


print()
print("=" * 66)
print(u"8. 中英切换：界面文案不能写死成中文")
print("=" * 66)

import io     # noqa: E402
import os     # noqa: E402
import re     # noqa: E402

# --- 类型名按语言走 ---
for pt, zh, en in (("Client", u"\u5ba2\u6237", u"Client"),
                   ("Worksheet", u"\u5de5\u4f5c\u8868", u"Worksheet"),
                   ("AnalysisRequest", u"\u6837\u54c1 / \u68c0\u9a8c\u7533\u8bf7",
                    u"Sample / Analysis Request")):
    got_zh = mdf_intro.get_type_title(pt, u"zh-cn")
    got_en = mdf_intro.get_type_title(pt, u"en")
    check(u"%s 中文名" % pt, got_zh == zh, got_zh.encode("utf-8"))
    check(u"%s 英文名" % pt, got_en == en, got_en.encode("utf-8"))
    check(u"%s 中英确实不同" % pt, got_zh != got_en)

# 不在表里的类型回落 portal_type 本身，不能变成 None / 空
check(u"未知类型回落 portal_type",
      mdf_intro.get_type_title("NoSuchType", u"en") == "NoSuchType")

# --- 显示位置徽章按语言走 ---
from maitux.dynamicfields.browser.view import POSITION_SLOTS, _is_en  # noqa: E402
check(u"显示位置徽章是 (key, 中, 英) 三元组",
      all(len(t) == 3 for t in POSITION_SLOTS), repr(POSITION_SLOTS[0]))
check(u"_is_en 判定正确",
      _is_en(u"en") and not _is_en(u"zh-cn") and not _is_en(u"zh"))

# --- .po 里必须有译文 ---
import gettext  # noqa: E402
MO = ("/opt/addons/common/maitux.dynamicfields/src/maitux/dynamicfields/"
      "locales/zh_CN/LC_MESSAGES/maitux.dynamicfields.mo")
if os.path.exists(MO):
    cat = gettext.GNUTranslations(open(MO, "rb"))
    for mid in ("Dynamic Fields", "Search objects", "v_need_type",
                "field_saved", "mech_at", "deprecated", "idx_yes",
                "delete_confirm", "shadow_warning"):
        got = cat.ugettext(mid)
        check(u"zh_CN 译文存在: %s" % mid, got != mid, got.encode("utf-8"))
else:
    check(u"找得到编译好的 zh_CN .mo", False, MO)

# --- lint：模板里每条 i18n 文案都必须有 zh_CN 译文 ---
# 漏一条的后果不是报错，是中文界面上突然冒出一句英文，而且很可能正好是
# 那句关键提示。实测踩过：「Editable in workflow states (empty = any)」漏译，
# 用户看到英文标签 + 一个多选框，以为那是必填项。
TPL_PATH = ("/opt/addons/common/maitux.dynamicfields/src/maitux/"
            "dynamicfields/browser/templates/dynamicfields.pt")
PO_PATH = ("/opt/addons/common/maitux.dynamicfields/src/maitux/"
           "dynamicfields/locales/zh_CN/LC_MESSAGES/maitux.dynamicfields.po")
if os.path.exists(TPL_PATH) and os.path.exists(PO_PATH):
    _tpl = io.open(TPL_PATH, encoding="utf-8").read()
    _po = io.open(PO_PATH, encoding="utf-8").read()
    _ids = set()
    for _m in re.finditer(u'i18n:translate=""[^>]*>([^<]+)<', _tpl):
        _t = u" ".join(_m.group(1).split())
        if _t:
            _ids.add(_t)
    for _m in re.finditer(
            u'placeholder="([^"]+)"\\s*\n?\\s*i18n:attributes="placeholder"',
            _tpl):
        _ids.add(_m.group(1))
    _have = set()
    for _m in re.finditer(u'^msgid "(.*)"\\s*\nmsgstr "(.+)"', _po, re.M):
        if _m.group(2).strip():
            _have.add(_m.group(1))
    _missing = sorted([i for i in _ids if i not in _have])
    check(u"模板里每条 i18n 文案（%d 条）都有 zh_CN 译文" % len(_ids),
          not _missing,
          u"缺 %d 条，第一条: %s" % (len(_missing), _missing[0][:50])
          if _missing else u"")
else:
    check(u"找得到模板和 .po", False, TPL_PATH)

# --- lint：源码里不许再出现写死的中文界面文案 ---
# 白名单：这几处是刻意保留的中文字面量
ALLOWED = set([u"\u7f16", u"\u67e5", u"\u5217", u"\u62a5",   # 徽章单字，与 E/V/L/R 配对
               u"\u4e2d\u6587",                                # 语言选项自己的名字
               u"\u5176\u5b83"])                               # 分组兜底名（另有英文分支）
CN_RE = re.compile(u"[\u4e00-\u9fff]")
SRC_DIR = "/opt/addons/common/maitux.dynamicfields/src/maitux/dynamicfields"
offenders = []
for root, _dirs, files in os.walk(SRC_DIR):
    for name in files:
        if not name.endswith(".py"):
            continue
        # config.py 里的中文是 TYPE_TITLES / TYPE_GROUPS 的**双语对照表**
        # （每项都是 (中文, 英文) 元组，由 get_type_title 按语言取），
        # 不是写死的界面文案，跳过。
        if name == "config.py":
            continue
        path = os.path.join(root, name)
        text = io.open(path, encoding="utf-8").read()
        # 去掉 docstring 和注释——那些是给人看的，不是界面文案
        text = re.sub(u'"""[\\s\\S]*?"""', u"", text)
        text = u"\n".join([l for l in text.split(u"\n")
                           if not l.strip().startswith(u"#")])
        for lit in re.findall(u'u"([^"]*)"', text):
            if CN_RE.search(lit) and lit not in ALLOWED:
                offenders.append(u"%s: %s" % (name, lit[:40]))
check(u"源码里没有写死的中文界面文案（%d 处白名单除外）" % len(ALLOWED),
      not offenders,
      u"; ".join(offenders[:4]).encode("utf-8") if offenders else u"")


print()
print("=" * 66)
print(u"9. 完整保存路径：浏览器发来的中文是 bytes")
print("=" * 66)
print(u"    \u2014\u2014 \u201c\u6dfb\u52a0\u4e00\u4e2a\u5e26\u4e2d\u6587\u6807\u7b7e\u7684\u5b57\u6bb5\u201d \u5c31\u62a5 0xe6 \u7684\u56de\u5f52\u7528\u4f8b")
print()

# 完全照浏览器 POST 的样子构造：所有值都是 utf-8 bytes
class SaveReq(dict):
    method = "POST"


def b(text):
    return text.encode("utf-8")


form = SaveReq()
form["action"] = "save_field"
form["portal_type"] = "AnalysisRequest"
form["name"] = "testfield"
form["type"] = config.TYPE_CHOICE
form["fieldset"] = b(u"\u5408\u540c\u4e0e\u5546\u52a1")      # 合同与商务
form["order"] = "0"
form["label_en"] = "testfield"
form["label_zh_cn"] = b(u"\u6d4b\u8bd5\u5b57\u6bb5")          # 测试字段 <- 0xe6 开头
form["desc_en"] = "none"
form["desc_zh_cn"] = b(u"\u6ca1\u6709")                          # 没有
form["show_edit"] = "1"
form["show_view"] = "1"
form["option_key"] = ["a", "b"]
form["option_label_en"] = ["A", "B"]
form["option_label_zh_cn"] = [b(u"\u7532"), b(u"\u4e59")]        # 甲 / 乙
form["default"] = b(u"\u7532")
form["states"] = [b(u"sample_due")]

v = mdf_view.DynamicFieldsView(None, form)

try:
    common = v._read_common(form)
    ok_read = True
except Exception as exc:
    common = {}
    ok_read = False
    check(u"_read_common 吃 bytes 中文", False, repr(exc))
if ok_read:
    check(u"_read_common 吃 bytes 中文", True)
    labels = common.get("labels") or {}
    check(u"中文标签存成 unicode 而不是 bytes",
          isinstance(labels.get("zh-cn"), type(u"")),
          repr(labels.get("zh-cn")))
    check(u"中文标签内容正确",
          labels.get("zh-cn") == u"\u6d4b\u8bd5\u5b57\u6bb5",
          repr(labels.get("zh-cn")))
    check(u"fieldset 也归一成 unicode",
          isinstance(common.get("fieldset"), type(u"")),
          repr(common.get("fieldset")))

try:
    specific = v._read_type_specific(form, config.TYPE_CHOICE)
    check(u"_read_type_specific 吃 bytes 中文", True)
    opts = specific.get("options") or []
    check(u"选项中文标签存成 unicode",
          bool(opts) and isinstance(
              (opts[0].get("labels") or {}).get("zh-cn"), type(u"")),
          repr(opts[:1]))
except Exception as exc:
    specific = {}
    check(u"_read_type_specific 吃 bytes 中文", False, repr(exc))

# 校验这条路——原 bug 就死在 validation._has_any_label 里
rec = storage.defaults("AnalysisRequest", "testfield", config.TYPE_CHOICE)
rec.update(common)
rec.update(specific)
try:
    problems = validation.validate_record(rec, skip_uniqueness=True)
    check(u"validate_record 吃 bytes 中文不抛异常（原 bug 死在这）", True)
    check(u"带中文标签的记录能通过校验",
          not problems, u"; ".join([u"%s" % p for p in problems[:2]]))
except Exception as exc:
    check(u"validate_record 吃 bytes 中文不抛异常（原 bug 死在这）",
          False, repr(exc))

# --- 固定选项的默认值：界面上是在选项列表里点单选钮，提交的是**行号** ---
form2 = SaveReq()
form2["portal_type"] = "AnalysisRequest"
form2["name"] = "grade"
form2["type"] = config.TYPE_CHOICE
form2["label_en"] = "Grade"
form2["option_key"] = ["low", "mid", "high"]
form2["option_label_en"] = ["Low", "Mid", "High"]
form2["default_option"] = "1"          # 第 2 行 = mid

v2 = mdf_view.DynamicFieldsView(None, form2)
spec2 = v2._read_type_specific(form2, config.TYPE_CHOICE)
check(u"行号 1 映射回第二个选项的 key",
      spec2.get("default") == u"mid", repr(spec2.get("default")))

form2["default_option"] = ""
check(u"不选单选钮 = 没有默认值",
      v2._read_type_specific(form2, config.TYPE_CHOICE).get("default") == u"",
      repr(v2._read_type_specific(form2, config.TYPE_CHOICE).get("default")))

form2["default_option"] = "9"          # 越界
check(u"行号越界当没设，不写脏 key",
      v2._read_type_specific(form2, config.TYPE_CHOICE).get("default") == u"")

form2["default_option"] = "2"
form2["option_key"] = ["low", "mid", ""]   # 第 3 行 key 是空的
check(u"指向空 key 的行当没设",
      v2._read_type_specific(form2, config.TYPE_CHOICE).get("default") == u"")

# 绕过界面（导入 JSON / 脚本）塞一个不存在的 key，校验要挡住
rec_bad = storage.defaults("AnalysisRequest", "grade2", config.TYPE_CHOICE)
rec_bad["labels"] = {"en": u"Grade"}
rec_bad["options"] = [{"key": "low", "labels": {"en": u"Low"}}]
rec_bad["default"] = u"nonexistent"
check(u"默认值不是任何选项的 key 时被拒绝",
      any(u"v_default_not_option" in u"%s" % p
          for p in validation.validate_record(rec_bad, skip_uniqueness=True)))

rec_ok = dict(rec_bad)
rec_ok["default"] = u"low"
check(u"默认值是合法 key 时通过",
      not validation.validate_record(rec_ok, skip_uniqueness=True))

# 就算有人绕过边界直接塞 bytes 进记录，校验也不能炸（兜底那层）
raw = storage.defaults("Client", "rawbytes", config.TYPE_TEXT)
raw["labels"] = {"zh-cn": b(u"\u76f4\u63a5\u585e\u8fdb\u6765\u7684")}
try:
    validation.validate_record(raw, skip_uniqueness=True)
    check(u"绕过边界直接塞 bytes，校验也不炸（兜底层）", True)
except Exception as exc:
    check(u"绕过边界直接塞 bytes，校验也不炸（兜底层）", False, repr(exc))


print()
print("=" * 66)
print(u"10. 模板表单完整性：视图要读的输入框，模板里必须都有")
print("=" * 66)
print(u"    \u2014\u2014 \u6539\u6a21\u677f\u65f6\u6574\u4e2a\u8868\u5355\u683c\u88ab\u5220\u6389\u8fc7\uff0c\u9760\u4eba\u773c\u6ca1\u53d1\u73b0")
print()

TPL = ("/opt/addons/common/maitux.dynamicfields/src/maitux/dynamicfields/"
       "browser/templates/dynamicfields.pt")
tpl = io.open(TPL, encoding="utf-8").read()

# 视图在 _read_common / _read_type_specific / 各 action 里会读的输入名。
# 少一个 = 那项配置在界面上没法填，而且是静默的（视图读到 None 走默认值）。
REQUIRED = [
    # 基础
    "action", "portal_type", "name", "type", "fieldset", "order",
    # 前端显示
    # show_view 只在 AT 对象上渲染（DX 侧 dxschema 不读它），但模板里
    # 那个 tal:condition 为假时还有个同名隐藏域，所以字面量照样在。
    "show_edit", "show_view", "show_list", "list_default",
    # 数据约束
    "required", "readonly", "multi",
    # 类型专属
    "option_key", "default_option", "allowed_types", "include_inactive",
    "maxlen", "default",
    # 检索
    #
    # ★ 这份清单里**故意没有**下面这些，它们 2026-09-21 从界面上拿掉了，
    #   原因都一样：界面上有开关，底下没实现，勾了不报错也不生效。
    #
    #     states                  没有任何代码读
    #     regex / regex_msg_*     没有任何代码读
    #     min / max               只有 dxfields 读，AT 不读（样品就是 AT）
    #     precision               只有 atfields 读，DX 不读
    #
    #   show_list / list_default 曾经也在这个名单里，2026-09-21 由
    #   browser/listing.py 实现后放回上面的清单。
    #
    #   storage / view / validation / 导入导出都还支持这些键。真做出来了
    #   把界面放回来时，记得同时加回这份 REQUIRED 和下面的多语言模式清单。
    "index", "metadata",
    # 其它动作
    "field_id", "payload", "mode", "upload",
    # 搜索
    "q", "fq",
]
missing = [n for n in REQUIRED if (u'name="%s"' % n) not in tpl]
check(u"模板里 %d 个必需输入框一个不少" % len(REQUIRED),
      not missing, u"缺: %s" % u", ".join(missing) if missing else u"")

# 多语言输入框是按站点语言**动态拼**出来的（name string:label_${lang/slug}），
# 源码里不会出现 name="label_zh_cn" 这种字面量，所以查的是那个拼接模式
for prefix in ("label", "desc", "option_label"):
    pattern = u"name string:%s_${lang/slug}" % prefix
    check(u"多语言输入框模式 %s_*" % prefix, pattern in tpl, pattern)

# 视图方法被模板引用了，就必须真的存在（打错字是静默 500）。
# ★ 要拿**实例**判断：errors / messages 是 __init__ 里赋的实例属性，
#   用类去 hasattr 会漏报。
import re as _re  # noqa: E402

probe_view = mdf_view.DynamicFieldsView(None, FakeReq())
referenced = set(_re.findall(u"view/([a-z_]+)", tpl))
missing_methods = [m for m in sorted(referenced)
                   if not hasattr(probe_view, m)]
check(u"模板引用的 %d 个视图方法 / 属性都存在" % len(referenced),
      not missing_methods,
      u"缺: %s" % u", ".join(missing_methods) if missing_methods else u"")

# data-mdf-types 里写的类型 id 必须真的存在——打错一个字，那块就永远不显示，
# 而且是静默的（JS 找不到匹配就一直藏着）
declared = set()
for group in _re.findall(u'data-mdf-types="([^"]*)"', tpl):
    for one in group.split():
        declared.add(one)
bad_types = sorted([t for t in declared if t not in config.FIELD_TYPE_IDS])
check(u"data-mdf-types 里的 %d 个类型 id 都合法" % len(declared),
      not bad_types,
      u"非法: %s" % u", ".join(bad_types) if bad_types else u"")

# 九种类型每一种都要至少被某个块声明过，否则选了它界面上什么专属项都没有
# date / datetime 确实没有任何类型专属配置：没有选项列表、没有数值范围、
# 没有文本约束，dxfields/atfields 的 builder 也不读 default。所以它们不出现在
# data-mdf-types 里是对的。写成显式豁免而不是放宽规则——以后谁误删了某个
# 类型的专属块，这条照样会红。
NO_TYPE_SPECIFIC = set(["date", "datetime"])
uncovered = set([t for t in config.FIELD_TYPE_IDS if t not in declared])
check(u"除 date/datetime 外，每种类型都有专属配置块",
      uncovered == NO_TYPE_SPECIFIC,
      u"实际未覆盖: %s" % u", ".join(sorted(uncovered)))

# JS 要抓的那个 select id 必须在
check(u"字段类型 select 带 id（JS 靠它联动）",
      u'id="mdf_fieldtype"' in tpl)

# --------------------------------------------------------------------------
# 11. 模板要能真的编译
#
# 上面那些 lint 全是对模板做正则匹配，一个字符都没交给 TAL 引擎。所以
#   tal:attributes="id string:mdf_st_${python:st[0]}"
# 这种 **语法非法** 的表达式（string: 里的 $ 后面只能跟简单路径，不能跟
# python: 表达式）能一路过掉 132 条检查，直到 build 完打开页面才炸成
# ExpressionError。真出过一次，这一节就是为它加的。
#
# _cook_check() 走的是 HTML 解析器 + 真正的 zope.tales 引擎，编译期能发现的
# 错它都能发现：表达式语法、未知表达式类型、python: 里的语法错、同一个元素上
# 重复的 tal:* 属性（后者会被静默丢掉一个——delete 表单的确认框就这么丢过）。
#
# 边界：只编译不渲染，所以路径写错（view/typo）这类要到渲染才知道的错查不出来；
# HTML 结构错（标签没闭合）也查不出来，那是解析器容忍的。另外运行时实际跑的是
# Chameleon，这里用的是老引擎，两者对表达式的解析共用 zope.tales，但不排除
# 个别构造有出入——真遇到误报就在这儿记一笔豁免，别把整节关掉。
# --------------------------------------------------------------------------

from Products.PageTemplates.PageTemplateFile import (                # noqa: E402
    PageTemplateFile as _ZPTF)
import tempfile                                                      # noqa: E402


def _compile_errors(path):
    """编译一个 .pt，返回错误列表（空列表 = 干净）"""
    t = _ZPTF(path)
    t._cook_check()
    return list(getattr(t, "_v_errors", ()) or ())


def _compile_source(source):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "t.pt")
    io.open(p, "w", encoding="utf-8").write(source)
    return _compile_errors(p)


# --- 先自检：确认这个检查器对我犯过的错真的会红 ---
# 不自检的话，哪天 _v_errors 改了名字、或者 _cook_check 变成静默吞异常，
# 这一节会安静地永远通过 —— 比没有还糟。
SELFTEST = [
    (u"string: 里跟简单路径是合法的", True,
     u'<div tal:attributes="id string:x_${view/foo}">x</div>'),
    (u"单独用 python: 是合法的", True,
     u'<div tal:attributes="id python:\'x_%s\' % 1">x</div>'),
    (u"string: 里塞 python: 要报错", False,
     u'<div tal:attributes="id string:x_${python:st[0]}">x</div>'),
    (u"同元素两个 tal:attributes 要报错", False,
     u'<div tal:attributes="id string:a" tal:attributes="class string:b">x</div>'),
    (u"未知表达式类型要报错", False,
     u'<div tal:content="bogus:whatever">x</div>'),
    (u"python: 语法错要报错", False,
     u'<div tal:content="python:1 +* 2">x</div>'),
]
selftest_bad = []
for _label, _should_pass, _src in SELFTEST:
    _errs = _compile_source(_src)
    if (not _errs) != _should_pass:
        selftest_bad.append(_label)
check(u"模板编译检查器自检（%d 条正反用例）" % len(SELFTEST),
      not selftest_bad,
      u"失效: %s" % u", ".join(selftest_bad) if selftest_bad else u"")

# --- 再检真模板 ---
_tpl_dir = os.path.join(os.path.dirname(mdf_view.__file__), "templates")
_pts = sorted(glob.glob(os.path.join(_tpl_dir, "*.pt")))
check(u"找得到模板文件", bool(_pts), _tpl_dir)
for _pt in _pts:
    _errs = _compile_errors(_pt)
    check(u"%s 能编译" % os.path.basename(_pt),
          not _errs,
          u" | ".join(_u(e) for e in _errs))


print()
print("=" * 66)
print(u"12. 保存失败后的回填".encode("utf-8"))
print("=" * 66)
print(u"    —— 填了十几项、错一个字段名，整张表被清空重来是不能接受的".encode("utf-8"))
print()

# 回填全靠 view.failed_form 是否非空分岔。最容易错的是复选框：没勾的复选框
# 根本不提交，所以「表单里没这个 key」必须理解成「用户取消了」，而不是退回
# 默认值 —— 否则用户特意取掉的勾会自己回来。
#
# 顺带校一条 HTML pattern 和服务端正则必须同源：模板曾经写死成只允许小写，
# 服务端却允许 CamelCase，浏览器先把 Grade 挡下来，「迁移 arextension 同名
# 字段」根本做不到，而服务端测试全绿，查不出来。

import re as _re2                                                    # noqa: E402

v_fresh = mdf_view.DynamicFieldsView(None, SaveReq())

html_pat = v_fresh.name_pattern
check(u"HTML pattern 不带 ^ $（HTML 自带锚定）",
      not html_pat.startswith("^") and not html_pat.endswith("$"), html_pat)
for candidate, allowed in [("Grade", True), ("grade", True),
                           ("Grade_2", True), ("2grade", False),
                           ("gr ade", False)]:
    by_html = bool(_re2.match("^%s$" % html_pat, candidate))
    by_server = bool(_re2.match(config.FIELD_NAME_PATTERN, candidate))
    check(u"字段名 %s：前后端判定一致，且都%s"
          % (candidate, u"放行" if allowed else u"拦下"),
          by_html == by_server == allowed,
          u"html=%s server=%s" % (by_html, by_server))

check(u"未失败时 prefill 给默认值（正常打开抽屉是张空表）",
      v_fresh.prefill("name") == u"" and v_fresh.prefill("order", "0") == "0")
check(u"未失败时 prefill_check 按默认",
      v_fresh.prefill_check("show_edit", True) == "checked"
      and v_fresh.prefill_check("required") is None)
check(u"未失败时抽屉不重开", v_fresh.reopen_panel is False)

bad = SaveReq()
bad["action"] = "save_field"
bad["portal_type"] = "AnalysisRequest"
bad["name"] = "2bad"                      # 数字开头，一定过不了校验
bad["type"] = config.TYPE_CHOICE
bad["order"] = "7"
bad["label_zh_cn"] = b(u"等级")                    # 等级
bad["required"] = "1"
bad["option_key"] = ["low", "mid", "high"]
bad["option_label_zh_cn"] = [b(u"低"), b(u"中"), b(u"高")]
bad["default_option"] = "2"
# show_edit / show_view 故意不放 —— 模拟用户把默认勾上的两项取消掉

v_bad = mdf_view.DynamicFieldsView(None, bad)
v_bad.action_save_field(bad)

check(u"字段名非法确实报了错", bool(v_bad.errors))
check(u"失败后 failed_form 被留下", v_bad.failed_form is not None)
check(u"失败后抽屉会重开", v_bad.reopen_panel is True)
check(u"文本框回填", v_bad.prefill("name") == u"2bad")
check(u"有默认值的文本框回填用户填的，不是默认",
      v_bad.prefill("order", "0") == u"7")
check(u"中文回填不炸且正确",
      v_bad.prefill("label_zh_cn") == u"等级")
check(u"勾上的复选框回填为勾上",
      v_bad.prefill_check("required") == "checked")
check(u"★ 用户取消掉的默认勾选项，回填后仍然是取消的",
      v_bad.prefill_check("show_edit", True) is None)
check(u"下拉框回填选中项",
      v_bad.prefill_selected("type", config.TYPE_CHOICE) == "selected"
      and v_bad.prefill_selected("type", config.TYPE_TEXT) is None)
check(u"选项列表按行号回填",
      [v_bad.prefill_row("option_key", i) for i in range(4)]
      == [u"low", u"mid", u"high", u""])
check(u"选项中文标签按行号回填",
      v_bad.prefill_row("option_label_zh_cn", 2) == u"高")
check(u"默认值单选钮回填到用户选的那行，不是第一行",
      v_bad.prefill_radio("default_option", 2, False) == "checked"
      and v_bad.prefill_radio("default_option", 0, True) is None)

# 保存成功不该留下 failed_form，否则下次打开抽屉是上一次的内容
good = SaveReq()
good["action"] = "save_field"
good["portal_type"] = "AnalysisRequest"
good["name"] = "PrefillOK"
good["type"] = config.TYPE_TEXT
good["label_en"] = "Prefill OK"
v_good = mdf_view.DynamicFieldsView(None, good)
try:
    v_good.action_save_field(good)
except Exception:
    # 建索引那步在没有真站点的 zopepy 里可能起不来，不影响这一条的结论：
    # 校验过了就不该留回填。
    pass
check(u"合法输入不报错、也不留回填",
      not v_good.errors and v_good.failed_form is None,
      u"errors=%s" % (v_good.errors,))

# 光有 view 方法、没接到模板上，等于没做
for needle in ["view.prefill('name')", "view.prefill_check('required')",
               "view.prefill_row('option_key', n)",
               "view.prefill_selected('type'", "view/name_pattern",
               "view/reopen_panel"]:
    check(u"模板接上了 %s" % needle, needle in tpl)
check(u"模板里不再写死 name 的 pattern", 'pattern="[a-z]' not in tpl)


print()
print("=" * 66)
print(u"13. 列表列（IListingViewAdapter）".encode("utf-8"))
print("=" * 66)
print(u"    —— 这一段是 2026-09-21 补实现的，之前 show_list 存了没人读".encode("utf-8"))
print()

# 列表视图的列来自视图类里写死的 self.columns，跟 schema 无关，所以造字段
# 那条路管不到。新增的 browser/listing.py 用官方 IListingViewAdapter 往里插。
#
# 这一节要盯住三件事：
#   ① 门控：没配置列的列表（绝大多数）必须一列都不动。订阅者注册给了
#      **所有**列表，门控破了就是全站每张表都被塞东西。
#   ② toggle：list_default 要映射成列定义里的 toggle，不是「加不加这一列」。
#   ③ 固定选项列要显示**标签**不是存储值——列表里一片 low/mid/high 没人看得懂。

import collections as _coll                                          # noqa: E402
from zope.interface import implementer as _impl                      # noqa: E402
from senaite.app.listing.interfaces import IListingView              # noqa: E402
from maitux.dynamicfields.browser import listing as mdf_listing      # noqa: E402


@_impl(IListingView)
class FakeListing(object):
    """够 add_column() 用的最小列表视图（它会校验 IListingView）"""

    def __init__(self, portal_type=None):
        self.contentFilter = {} if portal_type is None else {
            "portal_type": portal_type}
        self.columns = _coll.OrderedDict([("Title", {"title": "Title"})])
        self.review_states = [
            {"id": "default", "title": "All", "columns": ["Title"]},
            {"id": "active", "title": "Active", "columns": ["Title"]},
        ]
        self.request = SaveReq()


class FakeBrain(object):
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


# --- 造两个配置：一个上列表，一个不上 ---
rec_col = storage.defaults("Batch", "ListedField", config.TYPE_CHOICE)
rec_col["labels"] = {"en": u"Grade", "zh_CN": u"等级"}     # 等级
rec_col["options"] = [
    {"key": "low", "labels": {"en": u"Low", "zh_CN": u"低"}},   # 低
    {"key": "high", "labels": {"en": u"High", "zh_CN": u"高"}},  # 高
]
rec_col["show_list"] = True
rec_col["list_default"] = True
rec_col["metadata"] = True
rec_col["order"] = 1
storage.save_record(rec_col)

rec_hidden = storage.defaults("Batch", "NotListed", config.TYPE_TEXT)
rec_hidden["labels"] = {"en": u"Hidden"}
rec_hidden["show_list"] = False
storage.save_record(rec_hidden)

rec_toggle = storage.defaults("Batch", "OffByDefault", config.TYPE_TEXT)
rec_toggle["labels"] = {"en": u"Off by default"}
rec_toggle["show_list"] = True
rec_toggle["list_default"] = False
rec_toggle["metadata"] = True
rec_toggle["order"] = 2
storage.save_record(rec_toggle)

# --- ① 门控：没配置的类型一列都不许动 ---
untouched = FakeListing("AnalysisProfile")
before_cols = list(untouched.columns.keys())
mdf_listing.DynamicFieldsListingAdapter(untouched, None).before_render()
check(u"★ 没配置列的类型：一列都没动（订阅者注册给所有列表，门控破了全站遭殃）",
      list(untouched.columns.keys()) == before_cols,
      u"%s" % (list(untouched.columns.keys()),))

no_filter = FakeListing(None)
mdf_listing.DynamicFieldsListingAdapter(no_filter, None).before_render()
check(u"contentFilter 里没有 portal_type 时也不动",
      list(no_filter.columns.keys()) == ["Title"])

# --- ② 配置了的类型：列插进去，顺序、标题、toggle 都要对 ---
listed = FakeListing("Batch")
adapter = mdf_listing.DynamicFieldsListingAdapter(listed, None)
adapter.before_render()
cols = list(listed.columns.keys())
check(u"两个 show_list 的字段都插进来了，没上列表的没进来",
      "ListedField" in cols and "OffByDefault" in cols
      and "NotListed" not in cols, u"%s" % (cols,))
check(u"列标题用的是标签不是字段名",
      listed.columns["ListedField"]["title"] in (u"Grade", u"等级"),
      u"%r" % (listed.columns["ListedField"]["title"],))
check(u"★ list_default 映射成 toggle（不是「加不加这一列」）",
      listed.columns["ListedField"]["toggle"] is True
      and listed.columns["OffByDefault"]["toggle"] is False)
check(u"不声明 index —— 没建索引的字段点表头会静默无反应",
      "index" not in listed.columns["ListedField"])
check(u"每个 review state 的 columns 里都加上了",
      all("ListedField" in s["columns"] for s in listed.review_states),
      u"%s" % ([s["columns"] for s in listed.review_states],))

# 列表可能带 portal_type 列表而不是单个字符串
multi = FakeListing(["Batch", "AnalysisProfile"])
mdf_listing.DynamicFieldsListingAdapter(multi, None).before_render()
check(u"portal_type 是列表时也认",
      "ListedField" in multi.columns)

# --- ③ 每一行的取值与呈现 ---
brain = FakeBrain(ListedField="low", OffByDefault=b"\xe6\xb5\x8b\xe8\xaf\x95")
item = adapter.folder_item(brain, {}, 0)
check(u"★ 固定选项显示标签，不是存储值 low",
      item["ListedField"] in (u"Low", u"低"), u"%r" % (item["ListedField"],))
check(u"brain 上的 utf-8 bytes 不炸（Py2 老坑）",
      item["OffByDefault"] == u"测试", u"%r" % (item["OffByDefault"],))

brain_bad = FakeBrain(ListedField="removed_key", OffByDefault=None)
item_bad = adapter.folder_item(brain_bad, {}, 0)
check(u"配置里已删的旧选项 key 原样显示，不显示空白",
      item_bad["ListedField"] == u"removed_key")
check(u"值为 None 时给空串，不是 'None'",
      item_bad["OffByDefault"] == u"")

check(u"布尔渲染成勾号",
      adapter._render({"type": config.TYPE_BOOL}, FakeBrain()) == u""
      and adapter._render(
          {"type": config.TYPE_BOOL, "name": "x"},
          FakeBrain(x=True)) == u"✓")
check(u"多值用逗号连起来",
      adapter._render({"type": config.TYPE_TEXT, "name": "x"},
                      FakeBrain(x=["a", "b"])) == u"a, b")

# 没配置列的列表上 folder_item 必须原样返回，不能白跑一圈
passthrough = mdf_listing.DynamicFieldsListingAdapter(
    FakeListing("AnalysisProfile"), None)
same = {"keep": 1}
check(u"没配置列时 folder_item 原样返回",
      passthrough.folder_item(FakeBrain(), same, 0) is same)

# 清掉这一节造的记录，免得影响后面（目前没有后续节，但别给以后挖坑）
for _r in (rec_col, rec_hidden, rec_toggle):
    storage.delete_record(_r["id"])


print()
print("=" * 66)
print(u"14. 迁移包：20 个字段 / 5 个对象，导进来能不能真的造出字段".encode("utf-8"))
print("=" * 66)
print(u"    —— 交付的 addon_fields.json 必须导得进、造得出，不能只是好看".encode("utf-8"))
print()

# tools/make_migration_config.py 生成的那份 JSON 是要交给实施人员在界面上
# 导入的。光「生成时通过校验」不够 —— 真正要证明的是：导进去之后，各类型
# 的 schema 上确实多出这些字段，类型和标签都对。
# 这一节把整条链路跑一遍：文件 -> import_json -> atfields/dxfields 造字段。
#
# 覆盖的是全仓库**给现有类型加字段**的 6 个 add-on。自建内容类型的包
# （stock / stability / glossary / hazardcategories / oauth2）不在范围内，
# 本包也做不了新建类型。

_pkg_root = os.path.dirname(os.path.dirname(mdf_view.__file__))      # .../browser -> dynamicfields
_json_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(_pkg_root))),
    "addon_fields.json")
check(u"交付的 JSON 文件在", os.path.exists(_json_path), _json_path)

if os.path.exists(_json_path):
    _payload = io.open(_json_path, encoding="utf-8").read()
    added, updated, skipped, errors = storage.import_json(_payload,
                                                          mode="merge")
    check(u"20 个字段全部导入成功，没有跳过、没有报错",
          added == 20 and skipped == 0 and not errors,
          u"added=%s updated=%s skipped=%s errors=%s"
          % (added, updated, skipped, [_u(e) for e in errors]))

    # 五个对象类型都要落到位 —— 只验样品的话，另外四个包白迁了。
    # 按 creator 限定：前面几节在 AnalysisRequest / Client 上也留了记录，
    # 不限定的话数出来的是「本节 + 前面几节」的总和。
    def _migrated(portal_type):
        return [r for r in storage.get_records_for_type(portal_type)
                if r.get("creator") == "addon-migration"]

    for _t, _n in (("AnalysisRequest", 14), ("Client", 1), ("Laboratory", 1),
                   ("Worksheet", 3), ("Instrument", 1)):
        _got = len(_migrated(_t))
        check(u"%s 上落了 %d 个字段" % (_t, _n), _got == _n, u"实际 %s" % _got)

    _recs = storage.get_records_for_type("AnalysisRequest")
    _by_name = dict((r.get("name"), r) for r in _recs)
    for _n in ("ProjectNo", "MaterialName", "SampleRecovery",
               "SampleProperties", "SafetyPrecautions", "ManufactureDate"):
        check(u"导入后配置库里有 %s" % _n, _n in _by_name)

    check(u"CamelCase 字段名活下来了（这是能平移 arextension 的前提）",
          all(_n in _by_name for _n in
              ("MaterialCode", "StorageConditions", "RetentionTime")))
    check(u"必填只有 MaterialName 一个",
          [n for n, r in _by_name.items() if r.get("required")]
          == ["MaterialName"],
          u"%s" % ([n for n, r in _by_name.items() if r.get("required")],))
    check(u"SampleProperties 是多值引用",
          _by_name["SampleProperties"].get("multi") is True
          and _by_name["SampleProperties"].get("allowed_types")
          == ["HazardCategory"])
    check(u"SampleRecovery 是固定选项，两个 ASCII key",
          [o["key"] for o in _by_name["SampleRecovery"].get("options") or []]
          == ["yes", "no"])

    # ★ 真正的终点：这些配置能不能变成 Archetypes 字段
    _built = []
    for _n in ("ProjectNo", "MaterialName", "SampleRecovery",
               "SafetyPrecautions", "ManufactureDate", "SampleProperties"):
        try:
            _f = atfields.build_field(_by_name[_n])
        except Exception as _exc:
            _f = None
            check(u"造 %s 时抛异常" % _n, False, u"%s" % _exc)
        _built.append((_n, _f))
    check(u"★ 六种类型的代表字段都造得出 AT 字段（样品是 Archetypes）",
          all(f is not None for _n, f in _built),
          u"造不出: %s" % ([n for n, f in _built if f is None],))
    check(u"字段名原样保留，没被小写化",
          all(getattr(f, "getName", lambda: None)() == n
              for n, f in _built if f is not None),
          u"%s" % ([(n, getattr(f, "getName", lambda: None)())
                    for n, f in _built if f is not None],))

    # ★ Worksheet / Laboratory 是 Dexterity，走的是另一条造字段的路。
    #   只验 AT 的话，另外那几个包的字段能不能真出来是不知道的。
    _ws = dict((r.get("name"), r)
               for r in storage.get_records_for_type("Worksheet"))
    _dx_built = []
    for _n in ("reviewer_userid", "instruments", "stock_batches"):
        try:
            _dx_built.append((_n, dxfields.build_field(_ws[_n])))
        except Exception as _exc:
            _dx_built.append((_n, None))
            check(u"造 DX 字段 %s 时抛异常" % _n, False, u"%s" % _exc)
    check(u"★ 工作表那 3 个字段造得出 DX 字段（Worksheet 是 Dexterity）",
          all(f is not None for _n, f in _dx_built),
          u"造不出: %s" % ([n for n, f in _dx_built if f is None],))
    check(u"两个多值引用的 allowed_types 没丢",
          _ws["instruments"].get("allowed_types") == ["Instrument"]
          and _ws["stock_batches"].get("allowed_types") == ["StockBatch"])

    check(u"每条都带来源标记，导入后看得出是从哪个 add-on 平移的",
          all(r.get("source_addon")
              for t in ("AnalysisRequest", "Client", "Laboratory",
                        "Worksheet", "Instrument")
              for r in _migrated(t)))

    # 收尾：把这一节导进来的记录删掉
    for _t in ("AnalysisRequest", "Client", "Laboratory", "Worksheet",
               "Instrument"):
        for _r in list(storage.get_records_for_type(_t)):
            if _r.get("creator") == "addon-migration":
                storage.delete_record(_r["id"])


print()
print("=" * 66)
if FAILED:
    print("FAILED: %s" % ", ".join(FAILED))
    sys.exit(1)
print("全部通过")
sys.exit(0)
