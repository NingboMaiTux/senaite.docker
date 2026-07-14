# -*- coding: utf-8 -*-

from bika.lims import api


def post_install(portal_setup):
    """Runs after the last import step of the *default* profile.

    monkey-patches are already applied when medai.dashboard is imported
    (see __init__.py).  Nothing extra needed here.
    """
    pass


def post_uninstall(portal_setup):
    """Runs after the last import step of the *uninstall* profile.

    Uninstalling cannot undo monkey-patches without a restart, but
    removing the GS profile cleans up the addon from the control panel.
    """
    pass
