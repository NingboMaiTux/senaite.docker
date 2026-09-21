# -*- coding: utf-8 -*-
"""常量：目标类型白名单、字段类型、保留名、上限

白名单依据镜像内 senaite.core 2.7.0 的 FTI ``meta_type`` 实测得出，但**机制
（AT / DX）不写在这里**——运行时查 FTI 决定（见 introspect.get_mechanism）。

理由见需求文档 §6「机制中立」：AT 那一批每出一个 senaite 版本就会短一截，
把机制写死在常量里，等于上游每迁移一个类型就要改所有站点的配置。
"""

#: 配置在 portal 上的 annotation key
ANNOTATION_KEY = "maitux.dynamicfields.config"

# --------------------------------------------------------------------------
# 目标类型白名单
# --------------------------------------------------------------------------

#: 第一优先级：v1 必须支持
PRIMARY_TYPES = (
    "AnalysisRequest",
    "Client",
    "Batch",
    "AnalysisService",
    "Instrument",
    "Method",
    "Worksheet",
    "SampleType",
    "SamplePoint",
    "Contact",
    "Supplier",
)

#: 第二优先级：同样开放，但默认排在后面
SECONDARY_TYPES = (
    "LabContact",
    "AnalysisSpec",
    "ReferenceSample",
    "ReferenceDefinition",
    "InstrumentCalibration",
    "InstrumentCertification",
    "InstrumentValidation",
    "InstrumentMaintenanceTask",
    "Attachment",
    "SampleTemplate",
    "WorksheetTemplate",
    "AnalysisProfile",
    "Laboratory",
    "Calculation",
    "Department",
    "AnalysisCategory",
    "StorageLocation",
    "SampleContainer",
    "SampleCondition",
    "SamplePreservation",
    "SamplingDeviation",
    "SampleMatrix",
    "SubGroup",
    "ContainerType",
)

ALLOWED_TYPES = PRIMARY_TYPES + SECONDARY_TYPES

#: 明确排除，不得出现在选择列表里。
#: Analysis 系列：每样品×每检测项一个对象，年百万量级，且只经
#: senaite.app.listing 渲染（列来自 self.columns，不读 schema），加了也看不见。
#: BikaSetup / ARTemplate / ARReport：已被 DX 的 Setup / SampleTemplate /
#: ResultsReport 取代，属 AT→DX 迁移遗留，选了字段死活不显示。
EXCLUDED_TYPES = (
    "Analysis",
    "DuplicateAnalysis",
    "ReferenceAnalysis",
    "RejectAnalysis",
    "BikaSetup",
    "ARTemplate",
    "ARReport",
    "Plone Site",
    "Plone_Site",
)

#: 业务名（中文）。取不到时回落 portal_type 本身
TYPE_TITLES = {
    "AnalysisRequest": u"样品 / 检验申请",
    "Client": u"客户",
    "Batch": u"批次 / 项目",
    "AnalysisService": u"检验项目",
    "Instrument": u"仪器",
    "Method": u"方法",
    "Worksheet": u"工作表",
    "SampleType": u"样品类型",
    "SamplePoint": u"采样点",
    "Contact": u"客户联系人",
    "Supplier": u"供应商",
    "LabContact": u"实验室人员",
    "AnalysisSpec": u"结果规格",
    "ReferenceSample": u"标准物质",
    "ReferenceDefinition": u"标准物质定义",
    "InstrumentCalibration": u"仪器校准",
    "InstrumentCertification": u"仪器证书",
    "InstrumentValidation": u"仪器验证",
    "InstrumentMaintenanceTask": u"仪器保养",
    "Attachment": u"附件",
    "SampleTemplate": u"样品模板",
    "WorksheetTemplate": u"工作表模板",
    "AnalysisProfile": u"分析套餐",
    "Laboratory": u"实验室信息",
    "Calculation": u"计算公式",
    "Department": u"部门",
    "AnalysisCategory": u"检验分类",
    "StorageLocation": u"存储位置",
    "SampleContainer": u"样品容器",
    "SampleCondition": u"样品状态",
    "SamplePreservation": u"样品保存",
    "SamplingDeviation": u"采样偏差",
    "SampleMatrix": u"样品基质",
    "SubGroup": u"子分组",
    "ContainerType": u"容器类型",
}

#: 配置页左侧的业务分组
TYPE_GROUPS = (
    (u"样品与检测", ("AnalysisRequest", "AnalysisService", "Batch", "Worksheet",
                     "AnalysisSpec", "AnalysisProfile", "SampleTemplate",
                     "WorksheetTemplate", "Attachment")),
    (u"客户与供应商", ("Client", "Contact", "Supplier")),
    (u"实验室资源", ("Instrument", "Method", "LabContact", "Laboratory",
                     "Calculation", "InstrumentCalibration",
                     "InstrumentCertification", "InstrumentValidation",
                     "InstrumentMaintenanceTask", "ReferenceSample",
                     "ReferenceDefinition")),
    (u"字典与模板", ("SampleType", "SamplePoint", "StorageLocation",
                     "SampleContainer", "SampleCondition",
                     "SamplePreservation", "SamplingDeviation",
                     "SampleMatrix", "SubGroup", "ContainerType",
                     "Department", "AnalysisCategory")),
)

# --------------------------------------------------------------------------
# 字段类型
# --------------------------------------------------------------------------

TYPE_TEXT = "text"
TYPE_TEXTAREA = "textarea"
TYPE_INT = "int"
TYPE_DECIMAL = "decimal"
TYPE_DATE = "date"
TYPE_DATETIME = "datetime"
TYPE_BOOL = "bool"
TYPE_CHOICE = "choice"
TYPE_REFERENCE = "reference"

#: (id, 中文名, 英文名)
FIELD_TYPES = (
    (TYPE_TEXT, u"单行文本", u"Text line"),
    (TYPE_TEXTAREA, u"多行文本", u"Text area"),
    (TYPE_INT, u"整数", u"Integer"),
    (TYPE_DECIMAL, u"小数", u"Decimal"),
    (TYPE_DATE, u"日期", u"Date"),
    (TYPE_DATETIME, u"日期时间", u"Date & time"),
    (TYPE_BOOL, u"布尔", u"Boolean"),
    (TYPE_CHOICE, u"固定选项", u"Choice"),
    (TYPE_REFERENCE, u"对象引用", u"Reference"),
)

FIELD_TYPE_IDS = tuple([t[0] for t in FIELD_TYPES])

#: 带「选项列表」的类型
TYPES_WITH_OPTIONS = (TYPE_CHOICE,)
#: 可多值的类型
TYPES_MULTIVALUED = (TYPE_CHOICE, TYPE_REFERENCE)
#: 数值类型
TYPES_NUMERIC = (TYPE_INT, TYPE_DECIMAL)

# --------------------------------------------------------------------------
# 校验
# --------------------------------------------------------------------------

#: 字段名正则：ASCII 小写字母开头，后接字母数字下划线
FIELD_NAME_PATTERN = r"^[a-z][a-z0-9_]{1,49}$"

#: 选项 key 正则。存储值必须是 ASCII——一旦存中文，这份数据永远翻译不了，
#: 索引、导出、统计也全部锁死在中文上（需求文档 §5.4 设计红线）
OPTION_KEY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$"

#: 保留名：与之重名会让对象的基本行为出问题
RESERVED_NAMES = frozenset([
    "id", "uid", "UID", "title", "Title", "description", "Description",
    "created", "modified", "creators", "creator", "Creator",
    "portal_type", "meta_type", "path", "getId", "getObject",
    "review_state", "workflow_history", "absolute_url", "aq_parent",
    "getPhysicalPath", "Schema", "schema", "__name__", "__parent__",
    "manage_options", "isPrincipiaFolderish", "REQUEST",
])

#: 数量上限（NFR-3）
MAX_FIELDS_PER_TYPE = 50
MAX_FIELDS_TOTAL = 500

#: 索引类型推荐
DEFAULT_INDEX_TYPES = {
    TYPE_TEXT: "FieldIndex",
    TYPE_TEXTAREA: "ZCTextIndex",
    TYPE_INT: "FieldIndex",
    TYPE_DECIMAL: "FieldIndex",
    TYPE_DATE: "DateIndex",
    TYPE_DATETIME: "DateIndex",
    TYPE_BOOL: "BooleanIndex",
    TYPE_CHOICE: "KeywordIndex",
    TYPE_REFERENCE: "KeywordIndex",
}
