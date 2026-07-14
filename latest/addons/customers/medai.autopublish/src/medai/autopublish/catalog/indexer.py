# -*- coding: utf-8 -*-
"""Catalog indexers for department-aware filtering."""

from bika.lims.interfaces import IAnalysis
from bika.lims.interfaces import IAnalysisRequest
from plone.indexer import indexer
from senaite.core.interfaces.catalog import IAnalysisCatalog
from senaite.core.interfaces.catalog import ISampleCatalog


@indexer(IAnalysisRequest, ISampleCatalog)
def department_uids(instance):
    """Return department UIDs for all Analyses on this AR.

    This allows filtering Samples by the current user's department:
    an Analyst sees only Samples that have Analyses in their department(s).
    LabManager and Manager see all Samples (no filter applied).

    :param instance: AnalysisRequest
    :returns: list of department UIDs
    """
    uids = set()
    for analysis in instance.getAnalyses(full_objects=True):
        department = analysis.getDepartment()
        if department:
            uids.add(department.UID())
    return list(uids)


@indexer(IAnalysis, IAnalysisCatalog)
def getDepartmentUID(instance):
    """Return the UID of the Department this Analysis belongs to.

    :param instance: Analysis
    :returns: department UID string, or empty string
    """
    department = instance.getDepartment()
    if department:
        return department.UID()
    return ""
