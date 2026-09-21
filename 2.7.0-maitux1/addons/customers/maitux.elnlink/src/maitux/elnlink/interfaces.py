# -*- coding: utf-8 -*-
from zope.publisher.interfaces.browser import IDefaultBrowserLayer


class IElnLinkLayer(IDefaultBrowserLayer):
    """Browser layer: installed with the profile, so the schema extension
    and the viewlet only exist on sites that installed maitux.elnlink."""
