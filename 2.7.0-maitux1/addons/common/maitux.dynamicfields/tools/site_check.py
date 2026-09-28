# -*- coding: utf-8 -*-
"""在**运行中的站点**上逐个验证白名单里的每个对象类型

smoke_test.py 和 zcml_check.py 都不需要站点，覆盖不到「真实数据下会不会崩」。
这个脚本补那一块：对白名单里的每一个 portal_type，走一遍配置页实际用到的
全部代码路径，看哪个类型会炸。

为什么这件事必须自动化：36 个类型手工点一遍要几十分钟，而真正的风险不在
「加字段」本身（AT/DX 的字段构造跟 portal_type 无关，同一段代码），而在
**内省**——配置页要读每个类型的完整 schema（AT 要唤醒一个实例才能看到
extender 字段），某个类型读崩了，那一页就 500。

用法（容器必须是起着的）::

    docker exec <容器名> \\
      /home/senaite/senaitelims/bin/instance run \\
      /opt/addons/common/maitux.dynamicfields/tools/site_check.py [站点id]

站点 id 不传时自动找第一个 Plone 站点。本机是 lims2，生产是 lims。

**只读**：不写任何数据，不建字段，不动目录。可以在生产上跑。
"""
from __future__ import print_function

import sys
import traceback


def find_site(app, site_id=None):
    if site_id:
        return app[site_id]
    for obj_id in app.objectIds():
        obj = app[obj_id]
        if getattr(obj, "portal_type", None) in ("Plone Site", "Plone_Site"):
            return obj
        if getattr(obj, "meta_type", None) == "Plone Site":
            return obj
    raise RuntimeError("找不到 Plone 站点，请把站点 id 作为参数传进来")


def main(app, args):
    site_id = args[0] if args else None
    site = find_site(app, site_id)

    from zope.component.hooks import setSite
    setSite(site)
    print(u"站点: /%s\n" % site.getId())

    from maitux.dynamicfields import assignable
    from maitux.dynamicfields import atfields
    from maitux.dynamicfields import config
    from maitux.dynamicfields import dxfields
    from maitux.dynamicfields import introspect
    from maitux.dynamicfields import storage

    # 一条不落盘的假记录，用来验证字段构造这条路
    def probe(portal_type, field_type):
        rec = storage.defaults(portal_type, "probe_field", field_type)
        rec["labels"] = {"en": u"Probe"}
        if field_type == config.TYPE_CHOICE:
            rec["options"] = [{"key": "a", "labels": {"en": u"A"}}]
        if field_type == config.TYPE_REFERENCE:
            rec["allowed_types"] = [portal_type]
        return rec

    ok = bad = 0
    warn = []
    print(u"%-28s %-4s %-6s %-8s %-8s %s"
          % (u"portal_type", u"机制", u"实例", u"字段数", u"工作流", u"结果"))
    print(u"-" * 92)

    for portal_type in config.ALLOWED_TYPES:
        problems = []
        mechanism = instance = fields = states = None
        try:
            mechanism = introspect.get_mechanism(portal_type)
            if mechanism is None:
                print(u"%-28s %-4s %s" % (portal_type, u"-", u"站点上没有这个类型，跳过"))
                continue

            instance = introspect._find_instance(portal_type)

            # 配置页右栏就是走这条；AT 要唤醒实例才看得到 extender 字段
            grouped = introspect.group_fields(portal_type)
            fields = (len(grouped["own"]) + len(grouped["addon"])
                      + len(grouped["native"]))
            if fields == 0:
                problems.append(u"内省不到任何字段")

            states = len(introspect.get_workflow_states(portal_type))

            # 每种字段类型都造一遍，看有没有类型相关的构造失败
            for field_type in config.FIELD_TYPE_IDS:
                rec = probe(portal_type, field_type)
                builder = (atfields.build_field
                           if mechanism == introspect.MECH_AT
                           else dxfields.build_field)
                if builder(rec) is None:
                    problems.append(u"%s 构造失败" % field_type)

            # DX：本包的 assignable 有没有被别的 add-on 更具体的注册旁路掉
            if mechanism == introspect.MECH_DX and instance is not None:
                if assignable.is_assignable_active(instance) is False:
                    problems.append(u"assignable 被旁路（字段不会生效）")

        except Exception:
            problems.append(u"异常: %s" % traceback.format_exc().splitlines()[-1])

        mark = u"OK" if not problems else u"** " + u" / ".join(problems)
        if problems:
            bad += 1
            warn.append((portal_type, problems))
        else:
            ok += 1
        print(u"%-28s %-4s %-6s %-8s %-8s %s"
              % (portal_type, mechanism or u"?",
                 u"有" if instance is not None else u"无",
                 fields if fields is not None else u"?",
                 states if states is not None else u"?",
                 mark))

    print(u"\n" + u"=" * 92)
    print(u"正常 %d 个，有问题 %d 个" % (ok, bad))
    if warn:
        print(u"\n有问题的：")
        for portal_type, problems in warn:
            print(u"  %-28s %s" % (portal_type, u" / ".join(problems)))
        print(u"\n注意：「实例=无」时内省只能读注册表里的基础 schema，")
        print(u"读不到 extender / behavior 追加的字段，字段数偏少是正常的。")
    return 1 if bad else 0


if __name__ == "__main__":
    # bin/instance run 会把 app 注入全局
    try:
        _app = app  # noqa: F821
    except NameError:
        print(u"必须用 bin/instance run 跑这个脚本，不能直接 python 执行")
        sys.exit(2)
    sys.exit(main(_app, sys.argv[1:]))
