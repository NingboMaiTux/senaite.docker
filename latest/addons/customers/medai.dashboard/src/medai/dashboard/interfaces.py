# -*- coding: utf-8 -*-
"""Browser layer for medai.dashboard."""

from senaite.core.interfaces import ISenaiteCore


class IMedAIDashboardLayer(ISenaiteCore):
    """Marker interface activated when medai.dashboard is installed.

    Ensures JS resource overrides and view customizations are site-level,
    not global across all Plone sites in the Zope instance.
    """
