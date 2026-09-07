# -*- coding: utf-8 -*-
"""模块配置常量"""

PROJECTNAME = "maitux.worksheetfields"

# Worksheet 多选行为（行为名 = FTI behaviors 列表中的条目）
WORKSHEET_MULTISELECT_BEHAVIOR = \
    "maitux.worksheetfields.behavior.worksheetmultiselect"

# 新字段名（在 Worksheet 对象上以属性方式存储，值均为 UID 列表）
INSTRUMENTS_FIELD = "instruments"
STOCK_BATCHES_FIELD = "stock_batches"

# 依赖模块
STOCK_DISTRIBUTION_NAME = "maitux.stock"
STOCK_BATCH_PORTAL_TYPE = "StockBatch"
INSTRUMENT_PORTAL_TYPE = "Instrument"

# Worksheet 可编辑（可分配仪器/批次）的工作流状态
EDITABLE_WORKSHEET_STATES = ("open", "to_be_verified")
