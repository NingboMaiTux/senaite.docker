# -*- coding: utf-8 -*-
import logging

from zope.i18nmessageid import MessageFactory

AUTORECEIVE_DOMAIN = "INNOCARE.autoreceive"
_ = MessageFactory(AUTORECEIVE_DOMAIN)
logger = logging.getLogger(AUTORECEIVE_DOMAIN)
