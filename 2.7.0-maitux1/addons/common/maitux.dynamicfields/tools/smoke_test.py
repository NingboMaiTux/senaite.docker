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


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print("[%s] %s %s" % (status, name, detail))
    if not condition:
        FAILED.append(name)


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
check("保留名被拒绝",
      any(u"保留名" in p for p in validation.validate_record(bad, skip_uniqueness=True)))

bad2 = storage.defaults("Client", "grade", config.TYPE_CHOICE)
bad2["labels"] = {"en": u"X"}
bad2["options"] = [{"key": u"甲级", "labels": {"zh-cn": u"甲级"}}]
problems2 = validation.validate_record(bad2, skip_uniqueness=True)
check("Choice 的中文 key 被拒绝（设计红线）",
      any(u"ASCII" in p for p in problems2))

bad3 = storage.defaults("Client", "x_list", config.TYPE_TEXT)
bad3["labels"] = {"en": u"X"}
bad3["show_list"] = True
bad3["metadata"] = False
check("勾了列表列但没勾 metadata 被拒绝",
      any(u"metadata" in p for p in validation.validate_record(bad3, skip_uniqueness=True)))

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
if FAILED:
    print("FAILED: %s" % ", ".join(FAILED))
    sys.exit(1)
print("全部通过")
sys.exit(0)
