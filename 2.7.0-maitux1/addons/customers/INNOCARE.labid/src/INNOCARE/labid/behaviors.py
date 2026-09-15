# -*- coding: utf-8 -*-
"""Laboratory（Setup -> Laboratory Information）的 Lab ID 扩展字段。

Laboratory 在 senaite.core 2.x 是 Dexterity 内容类型（schema 为
``senaite.core.content.laboratory.ILaboratorySchema``），
``archetypes.schemaextender`` 对它无效。因此这里按 senaite.core 自己给
Dexterity 内容追加字段（labels 字段）的同一套路，用 ``plone.behavior``
提供一个附加 schema：``plone:behavior`` 注册 behavior 本体，
``assignable.py`` 负责把它动态挂到 Laboratory 上。

字段值以普通属性形式存放在 Laboratory 对象上（Dexterity 原生行为），
所以卸载本 add-on 不会删除已填写的值，重新装回后原样可见。
"""
from plone.autoform.interfaces import IFormFieldProvider
from plone.supermodel import model
from zope import schema
from zope.interface import implementer
from zope.interface import provider

from INNOCARE.labid import _


@provider(IFormFieldProvider)
class ILabIDSchema(model.Schema):
    """Lab ID 字段的 schema
    """

    lab_id = schema.TextLine(
        title=_(u"Lab ID"),
        description=_(
            u"Laboratory identifier, used as the prefix of new sample IDs"),
        required=False,
    )


@implementer(ILabIDSchema)
class LabIDSchema(object):
    """behavior 工厂，同时负责把字段读写转发到底层 Laboratory 对象。

    ★ 必须有下面这层转发（不能只留 ``__init__``）：
    z3c.form 的 IDataManager（``z3c/form/datamanager.py`` 的
    ``AttributeField``）读写的是 ``self.field.interface(context)`` —— 也就是
    本类的实例，**不是** Laboratory 对象本身：:

        context = self.field.interface(context)   # ILabIDSchema(laboratory)
        getattr(context, "lab_id") / setattr(context, "lab_id", value)

    少了这层转发，保存时值只会写到这个临时实例上，请求结束即丢，
    页面刷新后字段仍是空的（表单返回 302 不报错，属静默失效）。
    plone.app.dexterity 的 ``MetadataBaseBehavior``、senaite.core 的
    ``LabelSchema`` 都是同样的写法。
    """

    def __init__(self, context):
        self.context = context

    def _get_lab_id(self):
        return getattr(self.context, "lab_id", None)

    def _set_lab_id(self, value):
        self.context.lab_id = value

    lab_id = property(_get_lab_id, _set_lab_id)
