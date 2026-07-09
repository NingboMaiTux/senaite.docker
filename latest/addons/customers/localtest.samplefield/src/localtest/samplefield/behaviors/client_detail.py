# -*- coding: utf-8 -*-
from plone.autoform.interfaces import IFormFieldProvider
from plone.supermodel import model
from zope import schema
from zope.interface import provider


@provider(IFormFieldProvider)
class IClientDetail(model.Schema):
    detail = schema.TextLine(title=u"为 Client 添加字段 detail", required=False)
