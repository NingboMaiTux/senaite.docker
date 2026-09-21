# -*- coding: utf-8 -*-
"""把 INNOCARE.arextension 加在样品上的 14 个字段翻译成本包的配置 JSON

用途
----
验证「这个 addon 能不能替代手写的 schemaextender」。产物导进配置页之后，
把 INNOCARE.arextension 停掉，样品上那 14 个字段应该照旧存在、照旧能填。

跑法（要在镜像里跑，脚本要 import 本包做校验）：

    docker run --rm --entrypoint /home/senaite/senaitelims/bin/zopepy \\
      -v <本包路径>:/opt/addons/common/maitux.dynamicfields \\
      <镜像> /opt/addons/common/maitux.dynamicfields/tools/make_arextension_config.py \\
      /opt/addons/common/maitux.dynamicfields/arextension_fields.json

字段清单是从
``addons/customers/INNOCARE.arextension/src/INNOCARE/arextension/extenders/
analysisrequest.py`` 逐条抄下来的，中文标签取自同包 locales/zh_CN 的 .po。

**已知的表达不了的地方**（导入后行为会和原 addon 有出入，别当成 bug）：

1. ``SampleProperties`` 原本的引用查询带
   ``usage_scope: [both, ar, ar_only]`` 过滤 —— 本包的「对象引用」只能限定
   portal_type，限不了自定义索引。导入后这个控件会列出**全部**
   HazardCategory，不只是标了 AR 范围的那些。
2. ``searchable=True``：原 addon 把这些字段塞进了 SearchableText。本包用
   「建索引 / 建元数据列」两个开关，粒度不同，这里一律不开 —— 要的话在
   配置页上逐个勾。
3. ``ARSchemaModifier`` 改了三个**原生**字段的标签（ClientReference →
   批号、Contact → 申请人、StorageLocation → 预留位置）。那是改原生字段，
   不是加字段，本包管不到，停掉 arextension 之后这三个标签会变回英文原名。
"""
from __future__ import print_function

import glob
import io
import json
import sys

import pkg_resources

for pattern in ("/home/senaite/senaitelims/eggs/cp27mu/*.egg",
                "/home/senaite/senaitelims/eggs/*.egg",
                "/home/senaite/senaitelims/develop-eggs/*.egg"):
    for path in sorted(glob.glob(pattern)):
        pkg_resources.working_set.add_entry(path)

sys.path.insert(0, "/opt/addons/common/maitux.dynamicfields/src")

from maitux.dynamicfields import config        # noqa: E402
from maitux.dynamicfields import storage       # noqa: E402
from maitux.dynamicfields import validation    # noqa: E402

TYPE = "AnalysisRequest"

T = config.TYPE_TEXT
TA = config.TYPE_TEXTAREA
D = config.TYPE_DATE
R = config.TYPE_REFERENCE
C = config.TYPE_CHOICE

#: (字段名, 类型, 中文, 英文, 中文说明, 英文说明, 必填, 额外)
FIELDS = [
    ("ProjectNo", R, u"项目", u"Project", u"", u"", False,
     {"allowed_types": ["Project"]}),
    ("MaterialCode", T, u"物料代码", u"Material Code",
     u"物料代码", u"Material Code", False, {}),
    ("MaterialName", T, u"物料名称", u"Material Name",
     u"物料名称", u"Material Name", True, {}),
    ("Strength", T, u"规格/浓度", u"Strength",
     u"规格 / 说明", u"Strength / Specification", False, {}),
    ("ManufactureDate", D, u"生产日期", u"Manufacture Date",
     u"生产日期", u"Manufacture Date", False, {}),
    ("Quantity", T, u"数量", u"Quantity",
     u"数量", u"Quantity", False, {}),
    ("Unit", T, u"单位", u"Unit", u"单位", u"Unit", False, {}),
    ("SampleStatus", R, u"样品状态", u"Sample Status",
     u"", u"", False, {"allowed_types": ["SampleMatrix"]}),
    ("StorageConditions", R, u"储存条件",
     u"Storage Conditions", u"", u"", False,
     {"allowed_types": ["SamplePreservation", "StorageCondition",
                        "SampleCondition"]}),
    ("SampleProperties", R, u"样品性质", u"Sample Properties",
     u"", u"", False, {"allowed_types": ["HazardCategory"], "multi": True}),
    ("SampleRetainer", T, u"样品保留人",
     u"Sample Retainer", u"样品保留人",
     u"Sample Retainer", False, {}),
    ("RetentionTime", D, u"保留时间", u"Retention Time",
     u"保留时间", u"Retention Time", False, {}),
    ("SampleRecovery", C, u"样品回收", u"Sample Recovery",
     u"是否回收样品", u"Sample Recovery Description",
     False,
     {"options": [
         {"key": "yes", "labels": {"zh_CN": u"是", "en": u"Yes"}},
         {"key": "no", "labels": {"zh_CN": u"否", "en": u"No"}},
     ]}),
    ("SafetyPrecautions", TA, u"安全注意事项",
     u"Safety Precautions",
     u"安全注意事项或评论",
     u"Safety Precautions or Comments", False, {}),
]


def build():
    out = []
    problems = []
    for order, row in enumerate(FIELDS, start=1):
        name, ftype, zh, en, zh_desc, en_desc, required, extra = row
        record = storage.defaults(TYPE, name, ftype)
        record["id"] = "arext-%s" % name.lower()
        record["labels"] = {"zh_CN": zh, "en": en}
        record["descriptions"] = {}
        if zh_desc or en_desc:
            record["descriptions"] = {"zh_CN": zh_desc, "en": en_desc}
        record["required"] = required
        record["readonly"] = False
        record["show_edit"] = True
        record["show_view"] = True
        # 列表列默认不开：原 addon 也没往列表里加列。要试新做的「列表列」，
        # 在配置页上给某个字段勾「列表列」+「元数据列」即可。
        record["show_list"] = False
        record["list_default"] = False
        record["index"] = False
        record["metadata"] = False
        record["fieldset"] = "default"      # AnalysisRequest 不支持分组
        record["order"] = order
        record["creator"] = "arextension-migration"
        record.update(extra)

        found = validation.validate_record(record, skip_uniqueness=True)
        if found:
            problems.append(u"%s: %s" % (name, u"; ".join(
                u"%s" % p for p in found)))
        out.append(record)
    return out, problems


def main(argv):
    records, problems = build()
    # 这两处一定要 u"" 前缀：不加的话格式串是 bytes，% unicode 之后
    # .encode() 会触发隐式 ASCII 解码，直接 UnicodeDecodeError。
    # 本仓库踩过不止一次，见 smoke_test 第 7 / 9 节。
    for line in problems:
        print((u"校验没过 %s" % line).encode("utf-8"), file=sys.stderr)
    if problems:
        return 1

    payload = {
        "version": 1,
        "exported": "generated by tools/make_arextension_config.py",
        "revision": 0,
        "fields": records,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if argv:
        with io.open(argv[0], "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.write(u"\n")
        print((u"已写出 %s（%d 个字段，全部通过本包校验）"
               % (argv[0], len(records))).encode("utf-8"))
    else:
        print(text.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
