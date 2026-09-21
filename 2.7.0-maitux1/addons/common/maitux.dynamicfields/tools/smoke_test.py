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
    "show_edit", "show_view", "show_list", "list_default",
    # 数据约束
    "required", "readonly", "multi",
    # 类型专属
    "option_key", "allowed_types", "include_inactive",
    "min", "max", "precision", "maxlen", "regex", "default",
    # 工作流与检索
    "states", "index", "metadata",
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
for prefix in ("label", "desc", "option_label", "regex_msg"):
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

print()
print("=" * 66)
if FAILED:
    print("FAILED: %s" % ", ".join(FAILED))
    sys.exit(1)
print("全部通过")
sys.exit(0)
