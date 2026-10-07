# -*- coding: utf-8 -*-
"""maitux.elnlink -- the MaiLIMS half of the MaiELN <-> MaiLIMS demo link.

What it adds to the LIMS (nothing is removed or changed in senaite.core):

* AR (sample) extension fields that record which MaiELN experiment the
  sample came from (ELNExperimentNo / Title / URL / Scientist /
  Department). They are set through the JSON API by MaiELN when a sample
  is registered and never edited in the LIMS UI.
* A "Source Experiment (MaiELN)" card on the sample view with an
  "Open Experiment in MaiELN" deep link (the LIMS -> ELN direction).
* An event subscriber that pushes an analysis to MaiELN whenever it is
  submitted / verified / retracted, so approved results show up in the
  ELN without polling (the ELN also pulls, so a missed push is harmless).
* Two Manager-only demo views, @@eln-demo-seed and @@eln-demo-reset,
  that create the master data of the "KRAS G12D Inhibitor Discovery"
  demo (users, departments, client, sample type, analysis services,
  specification, project, SMP-{year}-{seq:06d} sample ids) and return
  the LIMS to the demo's initial state.
"""
import logging
import os

from zope.i18nmessageid import MessageFactory

DOMAIN = "maitux.elnlink"
_ = MessageFactory(DOMAIN)
logger = logging.getLogger(DOMAIN)

# Where MaiELN's backend is reached from inside the LIMS container (the
# result push) and where a browser reaches the MaiELN UI (deep links).
ELN_API_BASE = os.environ.get("ELN_API_BASE", "http://mainotebook-backend:8000")
ELN_PUBLIC_URL = os.environ.get("ELN_PUBLIC_URL", "http://localhost:5173")
ELN_INTEGRATION_TOKEN = os.environ.get("ELN_INTEGRATION_TOKEN", "")
