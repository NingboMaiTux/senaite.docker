# -*- coding: utf-8 -*-
#
# maitux.glossary.sync - 进页面自动同步
#
# 拆分：
#   core.py    同步计划（纯逻辑，不 import Zope，离线可测）
#   reader.py  遍历站点，构建"站点上现在有哪些组合"的快照
#   runner.py  把计划落到中间表（提权写入、日志）
