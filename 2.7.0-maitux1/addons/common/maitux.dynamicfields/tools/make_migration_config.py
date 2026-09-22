# -*- coding: utf-8 -*-
"""把各 add-on 加在**现有** SENAITE 对象上的字段翻译成本包的配置 JSON

用途
----
验证「这个 addon 能不能替代手写的 schemaextender / behavior」。产物导进
配置页之后，把对应 add-on 停掉，那些字段应该照旧存在、照旧能填。

覆盖范围
--------
全仓库扫过一遍，**给现有类型加字段**的只有这几个（自建内容类型的包
——maitux.stock / maitux.stability / maitux.glossary /
maitux.hazardcategories / maitux.oauth2.0——不在此列，本包也做不了）：

===========================  ==============  ====  ====
add-on                        目标类型         机制   字段
===========================  ==============  ====  ====
INNOCARE.arextension          AnalysisRequest  AT    14
INNOCARE.autoreceive          Client           AT     1
INNOCARE.labid                Laboratory       DX     1
maitux.reviewerassignment     Worksheet        DX     1
maitux.worksheetfields        Worksheet        DX     2
maitux.instrument_acquisition Instrument       AT     1
===========================  ==============  ====  ====

**故意不迁的一个**：INNOCARE.autoreceive 的 ``ReceivedByName``。它覆写了
``get()``，值每次实时算出来、根本不入库（见该包 extenders/
analysisrequest.py）。本包造的是真正存值的字段，迁过来只会得到一个
永远空白的框 —— 那比没有更糟。

**字段能迁，行为不能迁**
------------------------
下面这几个字段本身迁得过来，但真正干活的逻辑在各自 add-on 里，停掉
add-on 之后字段还在、功能没了。别把「字段还在」当成「功能还在」：

- ``AutoReceive``（Client）：勾上自动接收样品 —— 干活的是 autoreceive 的
  事件订阅者
- ``lab_id``（Laboratory）：用作新样品 ID 的前缀 —— 生成逻辑在 labid 里
- ``reviewer_userid``（Worksheet）：审核人，驱动过滤和权限判断
- ``ParsingTemplate``（Instrument）：仪器采集时用哪张解析模板

真正「纯数据、停掉 add-on 也不影响」的是 arextension 那 14 个，和
worksheetfields 那 2 个（它们自己的 docstring 就写明只作追溯记录、
不参与任何自动指派）。

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

T = config.TYPE_TEXT
TA = config.TYPE_TEXTAREA
D = config.TYPE_DATE
R = config.TYPE_REFERENCE
C = config.TYPE_CHOICE
B = config.TYPE_BOOL

#: (字段名, 类型, 中文, 英文, 中文说明, 英文说明, 必填, 额外)
AREXTENSION = [
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

#: INNOCARE.autoreceive 加在客户上的开关。
#: 不含同包的 ReceivedByName —— 那是覆写 get() 的计算字段，见模块 docstring。
AUTORECEIVE = [
    ("AutoReceive", B, u"自动接收样品",
     u"Auto Receive Samples",
     u"勾上后，该客户的样品在"
     u"登记时自动接收，跳过"
     u"接收步骤。",
     u"Checked: samples of this client are received automatically when "
     u"they are registered, skipping the receive step.", False, {}),
]

#: INNOCARE.labid 加在实验室上的 Lab ID（新样品 ID 的前缀）
LABID = [
    ("lab_id", T, u"实验室代码", u"Lab ID",
     u"用作新样品 ID 的前缀。",
     u"Laboratory identifier, used as the prefix of new sample IDs.",
     False, {}),
]

#: maitux.reviewerassignment + maitux.worksheetfields 加在工作表上的
WORKSHEET = [
    ("reviewer_userid", T, u"审核人", u"Reviewer",
     u"存放指定审核人的用户 ID，"
     u"用于过滤和权限判断。",
     u"Stores the assigned reviewer's user ID for filtering and "
     u"permission checks.", False, {}),
    ("instruments", R, u"仪器", u"Instruments",
     u"与本工作表关联的多台"
     u"仪器，仅作追溯记录，"
     u"不会自动指派给其中的"
     u"检验项。",
     u"Multiple instruments associated with this worksheet. Stored for "
     u"traceability; they are not assigned automatically to the "
     u"contained analyses.", False,
     {"allowed_types": ["Instrument"], "multi": True}),
    ("stock_batches", R, u"库存批次", u"Stock Batches",
     u"与本工作表关联的多个"
     u"库存批次（来自 maitux.stock）。",
     u"Multiple Stock Batch objects associated with this worksheet "
     u"(from the maitux.stock module).", False,
     {"allowed_types": ["StockBatch"], "multi": True}),
]

#: maitux.instrument_acquisition 加在仪器上的解析模板
INSTRUMENT = [
    ("ParsingTemplate", R, u"解析模板",
     u"Parsing Template",
     u"仪器采集时使用哪张"
     u"解析模板。",
     u"Which Instrument Parsing Template to use when acquiring data.",
     False, {"allowed_types": ["InstrumentParsingTemplate"]}),
]

#: (portal_type, 来源 add-on, 字段表)
GROUPS = [
    ("AnalysisRequest", "INNOCARE.arextension", AREXTENSION),
    ("Client", "INNOCARE.autoreceive", AUTORECEIVE),
    ("Laboratory", "INNOCARE.labid", LABID),
    ("Worksheet", "maitux.reviewerassignment + maitux.worksheetfields",
     WORKSHEET),
    ("Instrument", "maitux.instrument_acquisition", INSTRUMENT),
]


def build_group(portal_type, source, rows, out, problems):
    for order, row in enumerate(rows, start=1):
        name, ftype, zh, en, zh_desc, en_desc, required, extra = row
        record = storage.defaults(portal_type, name, ftype)
        record["id"] = "mig-%s-%s" % (portal_type.lower(), name.lower())
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
        # 一律 default：AnalysisRequest 本来就不支持分组，其余几个类型
        # 也没必要为迁移自造分组。
        record["fieldset"] = "default"
        record["order"] = order
        record["creator"] = "addon-migration"
        # 留个来源标记，导入后在配置页上能看出这条是从哪个 add-on 平移过来的
        record["source_addon"] = source
        record.update(extra)

        found = validation.validate_record(record, skip_uniqueness=True)
        if found:
            problems.append(u"%s.%s: %s" % (portal_type, name, u"; ".join(
                u"%s" % p for p in found)))
        out.append(record)


def build():
    out = []
    problems = []
    for portal_type, source, rows in GROUPS:
        build_group(portal_type, source, rows, out, problems)
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
        "exported": "generated by tools/make_migration_config.py",
        "revision": 0,
        "fields": records,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if argv:
        with io.open(argv[0], "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.write(u"\n")
        for portal_type, source, rows in GROUPS:
            print((u"  %-16s %2d 个   <- %s"
                   % (portal_type, len(rows), source)).encode("utf-8"))
        print((u"已写出 %s（共 %d 个字段，全部通过本包校验）"
               % (argv[0], len(records))).encode("utf-8"))
    else:
        print(text.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
