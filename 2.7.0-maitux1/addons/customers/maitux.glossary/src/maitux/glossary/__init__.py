# -*- coding: utf-8 -*-
#
# maitux.glossary - 检查项目 keyword 中英文对照表（中间表）
#
# 本包**不注册任何 monkey-patch**，也不改站点既有行为：
#   - 内容类型 GlossaryEntry / GlossaryEntries
#   - 一个 listing 界面（进页面即与站点对账同步）
#   - 一个只读查表 API（maitux.glossary.api）
#
# 需求与结构见 项目文档/keyword对照表/结构定稿.md

import logging

try:
    from zope.i18nmessageid import MessageFactory
except ImportError:  # pragma: no cover - 离线自检用降级（同 maitux.dualreport）
    def MessageFactory(domain):
        """让纯逻辑模块在没有 Zope 的环境里也能 import。"""
        def factory(msgid, *args, **kw):
            return msgid
        return factory

PROJECTNAME = "maitux.glossary"
_ = MessageFactory(PROJECTNAME)
logger = logging.getLogger(PROJECTNAME)
