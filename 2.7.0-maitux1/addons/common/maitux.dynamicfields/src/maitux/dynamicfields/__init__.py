# -*- coding: utf-8 -*-
"""maitux.dynamicfields —— SENAITE 动态字段管理

管理员在后台配置页上给 SENAITE 对象增删自定义字段，不写代码、不重建镜像、
不重启容器。同时支持 Archetypes（schemaextender）与 Dexterity（behavior）
两套机制。

两个翻译域，职责不同，不要混：

- ``maitux.dynamicfields``        配置页自身的界面文案，走常规 .po/.mo
- ``maitux.dynamicfields.labels`` 用户建的字段标签，走本包自注册的
  ITranslationDomain（见 i18n.py），文案存配置库、不落 .po
"""
from zope.i18nmessageid import MessageFactory

PROJECTNAME = "maitux.dynamicfields"

#: 配置页界面文案的域（常规 gettext）
DOMAIN = "maitux.dynamicfields"

#: 用户自建字段标签的域（本包自己实现的翻译域）
LABELS_DOMAIN = "maitux.dynamicfields.labels"

dynamicfieldsMessageFactory = MessageFactory(DOMAIN)
_ = dynamicfieldsMessageFactory

#: 动态标签用的 Message 工厂。msgid 一律 ASCII，中文只存配置库里
#: （Py2 下非 ASCII 的 msgid 撞上 str() 或 ascii 解码会直接抛异常）
labelMessageFactory = MessageFactory(LABELS_DOMAIN)


def initialize(context):
    """Zope 2 产品初始化入口（本包无 AT 内容类型，留空即可）"""
    pass
