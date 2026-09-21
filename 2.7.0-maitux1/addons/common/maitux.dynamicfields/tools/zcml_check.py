# -*- coding: utf-8 -*-
"""ZCML 加载检查：在镜像里真的把本包的 configure.zcml 走一遍

为什么单独做这件事：本仓库的失败大多是**静默**的（规则 R9），而 ZCML 错误是
其中最恶劣的一类——它在**启动期**报错，站点直接起不来，日志里还只有一串
看不懂的 ComponentLookupError / ValueError。等重建完镜像再发现，一轮就是
几十分钟。

这个脚本实际抓到过一条：``browser:page`` 用 ``cmf.ManagePortal`` 时，如果没有
先 ``<include package="Products.CMFCore" file="permissions.zcml" />``，在某些
加载顺序下会报 ``ValueError: ('Undefined permission ID', 'cmf.ManagePortal')``。
本包靠 z3c.autoinclude 加载，顺序不保证，所以那一行是必须的（R1 的同一套路）。

用法（在仓库根目录跑）::

    docker run --rm \\
      -v "$PWD/2.7.0-maitux1/addons/common/maitux.dynamicfields:/opt/addons/common/maitux.dynamicfields:ro" \\
      -e PYTHONIOENCODING=utf-8 \\
      --entrypoint /home/senaite/senaitelims/bin/zopepy \\
      <镜像> /opt/addons/common/maitux.dynamicfields/tools/zcml_check.py

注意：这只覆盖**注册阶段**。页面能不能正常渲染仍要重建镜像后在站点上走一遍
（验证判据见 README §8）。
"""
from __future__ import print_function

import glob
import os
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

from zope.configuration import xmlconfig  # noqa: E402

# ★ 两个坑叠在一起，缺一个这个检查就是摆设：
#
# 坑 1：只加载 meta.zcml 查不出注册冲突。必须把**会跟本包撞车的那条注册**
#       也放进来。本包的 IBehaviorAssignable 签名与
#       plone.dexterity/configure.zcml:42 完全相同
#       ((IDexterityContent,) -> IBehaviorAssignable, name=u'')。
#
# 坑 2：光放进来还不够——**两条必须处在同级 include**。ZCML 的冲突消解规则是
#       「一方 includepath 是另一方的前缀时，视为合法覆盖，不报冲突」。
#       把 dexterity 那条直接写在 wrapper 字符串里，它的 includepath 是
#       ('<string>',)，正好是本包 ('<string>', '.../configure.zcml') 的前缀，
#       于是冲突被静默吞掉、脚本照报 PASS。实测踩过：注入冲突后仍然全绿。
#       所以这里把它写进一个临时 .zcml 再 include，两条同级，冲突才现形。
#
# 改这段之前先跑一次反向验证：把 adapter 注册塞回 configure.zcml，
# 这个脚本必须变红。变不红就说明 harness 又退化成摆设了。

import tempfile  # noqa: E402

_STUB = """<configure xmlns="http://namespaces.zope.org/zope">
  <!-- plone.dexterity/configure.zcml:42 的那条，一字不差 -->
  <adapter factory="plone.dexterity.behavior.DexterityBehaviorAssignable" />
</configure>"""

_stub_dir = tempfile.mkdtemp(prefix="mdf-zcml-")
_stub_path = os.path.join(_stub_dir, "dexterity_stub.zcml")
with open(_stub_path, "w") as _fh:
    _fh.write(_STUB)

WRAPPER = """<configure xmlns="http://namespaces.zope.org/zope">
  <include package="Products.Five" file="meta.zcml" />
  <include package="zope.browserpage" file="meta.zcml" />
  <include package="zope.viewlet" file="meta.zcml" />
  <include package="zope.i18n" file="meta.zcml" />
  <include package="plone.behavior" file="meta.zcml" />

  <include file="%s" />
  <include package="maitux.dynamicfields" />
</configure>""" % _stub_path

#: overrides 单独跑：ZCML 的 overrides 阶段与 configure 阶段本来就是分开的
OVERRIDES = """<configure xmlns="http://namespaces.zope.org/zope">
  <includeOverrides package="maitux.dynamicfields" file="overrides.zcml" />
</configure>"""


def main():
    try:
        context = xmlconfig.string(WRAPPER)
    except Exception as exc:
        print("[FAIL] ZCML 加载失败：%s" % type(exc).__name__)
        print(str(exc)[:4000])
        return 1
    print("[PASS] configure.zcml 加载通过（含 dexterity 的同签名注册，冲突查得出）")

    try:
        xmlconfig.string(OVERRIDES, context=context)
    except Exception as exc:
        print("[FAIL] overrides.zcml 加载失败：%s" % type(exc).__name__)
        print(str(exc)[:4000])
        return 1
    print("[PASS] overrides.zcml 加载通过")

    from zope.component import getSiteManager
    from zope.component import queryUtility
    from zope.i18n.interfaces import ITranslationDomain

    failed = 0

    domain = queryUtility(
        ITranslationDomain, name="maitux.dynamicfields.labels")
    if domain is None:
        print("[FAIL] 动态标签翻译域没注册上")
        failed += 1
    else:
        print("[PASS] 翻译域已注册：%s" % domain.domain)

    factories = sorted(set([
        r.factory.__name__
        for r in getSiteManager().registeredAdapters()
        if getattr(r, "factory", None) is not None
        and getattr(r.factory, "__module__", "").startswith(
            "maitux.dynamicfields")]))
    expected = ["DynamicFieldsAssignable", "DynamicFieldsExtender"]
    for name in expected:
        if name in factories:
            print("[PASS] 适配器已注册：%s" % name)
        else:
            print("[FAIL] 适配器没注册上：%s" % name)
            failed += 1

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
