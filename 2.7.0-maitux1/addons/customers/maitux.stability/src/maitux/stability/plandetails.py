# -*- coding: utf-8 -*-
"""方案明细行（``plan_details``）的**列清单与行构造** —— 唯一实现（纯逻辑）。

给谁用：

* 「复制方案」（``plan_copy.build_copy_rows``）：按列清单把历史行**补齐缺列**；
* 「新建方案」（``browser/add.py``）：预置一个 0 点行（B 方案，2026-09-30）。

为什么合成一个模块：两处都必须与 ``IStabilityPlanDetailSchema`` 的列全集一致，各写一份
必然漂移 —— **少一列就等于"每保存一次丢一次那个字段"**（本模块历史上真的丢过
``detail_uid`` / ``stock_batch`` / 登样审计，见 ``timepoints`` 的模块说明）。

依赖方向：本模块只依赖 ``timepoints``（同样是纯逻辑、不 import Zope），
``plan_copy`` 从这里取常量，避免两边各写一份。
"""

from maitux.stability.timepoints import INITIAL_MONTHS
from maitux.stability.timepoints import STATUS_PENDING
from maitux.stability.timepoints import new_detail_uid


# IStabilityPlanDetailSchema 的字段全集（列序即 DataGrid 的列序，追加在末尾最安全）。
# 复制时用它给历史行**补齐缺列** —— 少一列就等于"每保存一次丢一次那个字段"，
# 所以这里必须包含后面新增的隐藏列（``generated_at`` / ``generated_by``）。
DETAIL_ROW_KEYS = (
    "packaging_specification",
    "storage_condition",
    "orientation",
    "timepoint_days",
    "window_days",
    "sample_template",
    "analysis_request",
    "inspection_quantity",
    "batch",
    "detail_status",
    "notes",
    "detail_uid",
    "generated_at",
    "generated_by",
)

# 补齐缺列时的默认值（其余列缺省为空串）。
DETAIL_ROW_DEFAULTS = {
    "window_days": 0,
    "inspection_quantity": 0,
    "detail_status": STATUS_PENDING,
}

# 方向列的默认值（与 content/stabilityplan.py 的 ORIENTATION_VOCABULARY 一致）。
ORIENTATION_DEFAULT = u"upright"

# 「行上必须有、但**不是** schema 列」的字段：
#
# ``stock_batch``  方案明细的库存批次引用，由「样品放置」页写回，**没有对应的 schema 字段**
#                  （见 timepoints 的模块说明）。DataGrid 只提交 schema 里的列，
#                  所以它只能靠"保留字段兜底"续命；新建的行必须一开始就带上这个键。
EXTRA_ROW_KEYS = ("stock_batch",)


def new_detail_row(months=INITIAL_MONTHS, detail_uid=None, **overrides):
    """造一个**完整**的明细行（每一列都有值，可直接交给 DataGrid）。

    默认形态就是"新建方案时预置的那一行"：0 点、待放置、方向直立、没有任何关联。

    ``detail_uid`` 不传就现生成一个 —— 行的身份必须**从出生就有**：
    等第一次保存时再由订阅器补，中间任何按 uid 的操作（任务对账、关联写回）
    都会落空（见 ``timepoints`` 的模块说明）。
    """
    row = {}
    for key in DETAIL_ROW_KEYS:
        row[key] = DETAIL_ROW_DEFAULTS.get(key, u"")
    for key in EXTRA_ROW_KEYS:
        row[key] = u""
    row["timepoint_days"] = months
    row["orientation"] = ORIENTATION_DEFAULT
    row["detail_status"] = STATUS_PENDING
    row["detail_uid"] = detail_uid or new_detail_uid()
    for key, value in overrides.items():
        row[key] = value
    return row
