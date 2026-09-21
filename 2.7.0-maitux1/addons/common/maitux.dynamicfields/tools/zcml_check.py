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

WRAPPER = """<configure xmlns="http://namespaces.zope.org/zope">
  <include package="Products.Five" file="meta.zcml" />
  <include package="zope.browserpage" file="meta.zcml" />
  <include package="zope.viewlet" file="meta.zcml" />
  <include package="zope.i18n" file="meta.zcml" />
  <include package="plone.behavior" file="meta.zcml" />
  <include package="maitux.dynamicfields" />
</configure>"""


def main():
    try:
        xmlconfig.string(WRAPPER)
    except Exception as exc:
        print("[FAIL] ZCML 加载失败：%s" % type(exc).__name__)
        print(str(exc)[:4000])
        return 1
    print("[PASS] ZCML 加载通过")

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
