# -*- coding: utf-8 -*-
"""GenericSetup upgrade steps for maitux.worksheetfilter."""

import logging

logger = logging.getLogger("maitux.worksheetfilter")

PROFILE_ID = "profile-maitux.worksheetfilter:default"


def import_registry(tool):
    """(Re)import the addon's registry records into the site.

    Idempotent: the importer adds the records the schema declares and leaves
    the values a site has already stored alone.
    """
    tool.runImportStepFromProfile(PROFILE_ID, "plone.app.registry",
                                  run_dependencies=False)
    logger.info("maitux.worksheetfilter: registry records imported")
