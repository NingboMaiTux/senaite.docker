# -*- coding: utf-8 -*-
import logging

PRODUCT_NAME = "senaite.smartsearch"
logger = logging.getLogger(PRODUCT_NAME)


def initialize(context):
    logger.info("*** Initializing senaite.smartsearch (智慧搜索) ***")
