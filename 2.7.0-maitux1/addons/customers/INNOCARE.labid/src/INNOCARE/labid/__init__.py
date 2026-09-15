# -*- coding: utf-8 -*-
import logging

from zope.i18nmessageid import MessageFactory

LABID_DOMAIN = "INNOCARE.labid"
_ = MessageFactory(LABID_DOMAIN)
logger = logging.getLogger(LABID_DOMAIN)
