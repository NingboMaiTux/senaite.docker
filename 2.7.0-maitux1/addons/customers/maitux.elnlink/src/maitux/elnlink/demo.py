# -*- coding: utf-8 -*-
"""Seed / reset of the MaiLIMS half of the MaiELN x MaiLIMS integrated demo
(spec "MaiLIMS x MaiELN Integrated Demo Specification V1.0", sections
3-5, 12-15, 24-26).

Idempotent: every object is looked up before it is created, so the seed
can run any number of times. Only master data lives here; the samples of
the demo states are created by MaiELN through the JSON API, so the
sample ids are minted by this LIMS's ID server and are the same string
on both sides. `reset` deletes those samples and rewinds the counter.

Pure functions over the portal: the browser views call them, and so can
`bin/instance run` for development.
"""
import os
from datetime import datetime

from bika.lims import api
from plone import api as ploneapi
from senaite.core.idserver import idserver
from senaite.core.interfaces import INumberGenerator
from zope.component import getUtility

from maitux.elnlink import logger

# Demo users share one password, taken from the container environment so
# no credential sits in the repository (R17); the MaiELN seed passes the
# same value through its own environment.
DEMO_PASSWORD = os.environ.get("ELN_DEMO_PASSWORD", "")
# The ID server only offers a 2-digit {year}; the 4-digit year is baked into
# the form at seed time (SMP-2026-001823 as the spec writes it).
SAMPLE_ID_FORM = "SMP-%s-{seq:06d}"
SAMPLE_ID_SPLIT = 2
SAMPLE_SEQ_START = 1822  # the first demo sample is SMP-<year>-001823
SAMPLE_PREFIX = "SMP-"

PROJECT_ID = "PRJ-KRAS-001"
PROJECT_TITLE = "KRAS G12D Inhibitor Discovery"
CLIENT_ID = "INC-MEDCHEM"
CLIENT_NAME = "InnoCare Medicinal Chemistry"
SAMPLE_TYPE = "Synthetic Compound"

DEPARTMENTS = (
    # id, title, manager username
    ("MEDCHEM", "Medicinal Chemistry", "chenwei"),
    ("ANACHEM", "Analytical Chemistry", "wangjing"),
)

USERS = (
    # username, fullname, email, department id, groups, lab contact?
    ("chenwei", "Dr. Chen Wei", "chen.wei@example.com", "MEDCHEM", ("Clients",), True),
    ("liming", "Li Ming", "li.ming@example.com", "ANACHEM", ("Analysts", "LabClerks"), True),
    ("wangjing", "Wang Jing", "wang.jing@example.com", "ANACHEM", ("LabManagers", "Verifiers"), True),
)

SERVICES = (
    {
        "keyword": "HPLC_PURITY",
        "title": "HPLC Purity",
        "description": "HPLC Purity - Generic RP-HPLC; Agilent 1290 Infinity II; C18; UV 254 nm",
        "unit": "%",
        "string_result": False,
        "interims": [
            {"keyword": "main_peak_rt", "title": "Main peak RT (min)", "value": "", "unit": "min"},
            {"keyword": "largest_impurity", "title": "Largest impurity (%)", "value": "", "unit": "%"},
            {"keyword": "impurity_rt", "title": "Impurity RT (min)", "value": "", "unit": "min"},
        ],
    },
    {
        "keyword": "LCMS_IDENTITY",
        "title": "LC-MS Identity",
        "description": "LC-MS Identity Confirmation - expected MW vs observed [M+H]+",
        "unit": "",
        "string_result": True,
        "interims": [
            {"keyword": "expected_mw", "title": "Expected MW", "value": "", "unit": ""},
            {"keyword": "observed_mh", "title": "Observed [M+H]+", "value": "", "unit": ""},
        ],
    },
    {
        "keyword": "STABILITY_40_75",
        "title": "Stability Screening 40C/75%RH",
        "description": "Accelerated stability screening 40C / 75% RH, Day 0 / 7 / 14; result = Day 14 main impurity (%)",
        "unit": "%",
        "string_result": False,
        "interims": [
            {"keyword": "day0_purity", "title": "Day 0 purity (%)", "value": "", "unit": "%"},
            {"keyword": "day0_impurity", "title": "Day 0 main impurity (%)", "value": "", "unit": "%"},
            {"keyword": "day7_purity", "title": "Day 7 purity (%)", "value": "", "unit": "%"},
            {"keyword": "day7_impurity", "title": "Day 7 main impurity (%)", "value": "", "unit": "%"},
            {"keyword": "day14_purity", "title": "Day 14 purity (%)", "value": "", "unit": "%"},
            {"keyword": "day14_impurity", "title": "Day 14 main impurity (%)", "value": "", "unit": "%"},
        ],
    },
)

# Specification for the demo sample type: the Day-14 impurity above 2.0 %
# is out of range, which the LIMS shows as an alert and MaiELN as OOT.
SPEC_TITLE = "INC-KRAS-042 stability screening"
SPEC_RANGES = (
    {"keyword": "STABILITY_40_75", "min": "0", "max": "2.0", "warn_min": "", "warn_max": "", "hidemin": "", "hidemax": "", "rangecomment": "Main impurity must stay below 2.0 % through Day 14"},
    {"keyword": "HPLC_PURITY", "min": "95", "max": "100", "warn_min": "", "warn_max": "", "hidemin": "", "hidemax": "", "rangecomment": "Purity >= 95 %"},
)


# --- helpers ---------------------------------------------------------------


def _first(container, portal_type, **match):
    """First child of `container` with this portal_type whose attributes /
    field values equal `match`."""
    for obj in container.objectValues():
        if api.get_portal_type(obj) != portal_type:
            continue
        ok = True
        for key, wanted in match.items():
            value = None
            for candidate in ("get" + key, key, key.lower()):
                attr = getattr(obj, candidate, None)
                if attr is None:
                    continue
                value = attr() if callable(attr) else attr
                break
            if value != wanted:
                ok = False
                break
        if ok:
            return obj
    return None


def _catalog_first(portal_type, **query):
    query["portal_type"] = portal_type
    for catalog in ("senaite_catalog_setup", "portal_catalog"):
        try:
            brains = api.search(query, catalog)
        except Exception:
            brains = []
        if brains:
            return api.get_object(brains[0])
    return None


# --- pieces ----------------------------------------------------------------


def ensure_users(portal, log):
    created = {}
    if not DEMO_PASSWORD:
        raise ValueError("ELN_DEMO_PASSWORD is not set in the LIMS environment; demo users need a password")
    for username, fullname, email, _dept, groups, _lab in USERS:
        user = ploneapi.user.get(username=username)
        if user is None:
            user = ploneapi.user.create(username=username, email=email, password=DEMO_PASSWORD, properties={"fullname": fullname})
            log.append("user %s created" % username)
        else:
            user.setProperties(fullname=fullname, email=email)
        for group in groups:
            try:
                ploneapi.group.add_user(groupname=group, username=username)
            except Exception as exc:
                log.append("group %s for %s: %r" % (group, username, exc))
        created[username] = user
    return created


def ensure_lab_contacts(portal, log):
    setup = api.get_setup()
    folder = setup.bika_labcontacts
    contacts = {}
    for username, fullname, email, _dept, _groups, is_lab in USERS:
        if not is_lab:
            continue
        parts = fullname.replace("Dr. ", "").split(" ", 1)
        first, last = parts[0], parts[1] if len(parts) > 1 else ""
        contact = _first(folder, "LabContact", Username=username)
        if contact is None:
            contact = api.create(folder, "LabContact", Firstname=first, Surname=last, Username=username, EmailAddress=email)
            log.append("lab contact %s created" % fullname)
        contacts[username] = contact
    return contacts


def ensure_departments(portal, log, lab_contacts):
    folder = portal.setup.departments
    departments = {}
    for dept_id, title, manager in DEPARTMENTS:
        dept = _first(folder, "Department", Title=title)
        if dept is None:
            dept = api.create(folder, "Department", title=title, department_id=dept_id, manager=lab_contacts[manager])
            log.append("department %s created" % title)
        departments[dept_id] = dept
    # every lab contact belongs to its department
    for username, _fullname, _email, dept_id, _groups, is_lab in USERS:
        contact = lab_contacts.get(username)
        if contact is None or dept_id not in departments:
            continue
        try:
            contact.setDepartments([departments[dept_id]])
            contact.setDefaultDepartment(departments[dept_id])
        except Exception as exc:
            log.append("department for %s: %r" % (username, exc))
    return departments


def ensure_client(portal, log, users):
    client = _catalog_first("Client", getClientID=CLIENT_ID) or _first(portal.clients, "Client", ClientID=CLIENT_ID)
    if client is None:
        client = api.create(portal.clients, "Client", Name=CLIENT_NAME, ClientID=CLIENT_ID)
        log.append("client %s created" % CLIENT_NAME)
    contact = _first(client, "Contact", Username="chenwei")
    if contact is None:
        contact = api.create(client, "Contact", salutation="Dr.", firstname="Chen", surname="Wei", email_address="chen.wei@example.com")
        log.append("client contact Dr. Chen Wei created")
    user = users.get("chenwei")
    if user is not None:
        try:
            if not contact.getUsername():
                contact.setUser(user)
                log.append("contact linked to user chenwei")
        except Exception as exc:
            log.append("link chenwei: %r" % exc)
    return client, contact


def ensure_sample_type(portal, log):
    folder = portal.setup.sampletypes
    sample_type = _first(folder, "SampleType", Title=SAMPLE_TYPE)
    if sample_type is None:
        sample_type = api.create(folder, "SampleType", title=SAMPLE_TYPE, prefix="SMP", min_volume="1 mg", retention_period={"days": 365, "hours": 0, "minutes": 0})
        log.append("sample type %s created" % SAMPLE_TYPE)
    return sample_type


def ensure_services(portal, log, departments):
    setup = api.get_setup()
    categories = portal.setup.analysiscategories
    category = _first(categories, "AnalysisCategory", Title="Analytical Chemistry")
    if category is None:
        category = api.create(categories, "AnalysisCategory", title="Analytical Chemistry", department=departments["ANACHEM"])
        log.append("analysis category created")
    services = {}
    folder = setup.bika_analysisservices
    for spec in SERVICES:
        service = _first(folder, "AnalysisService", Keyword=spec["keyword"])
        if service is None:
            service = api.create(
                folder, "AnalysisService",
                title=spec["title"], Keyword=spec["keyword"], Category=category, Unit=spec["unit"],
                PointOfCapture="lab", Department=departments["ANACHEM"],
                description=spec["description"],
            )
            log.append("service %s created" % spec["keyword"])
        try:
            # StringResult is read-only for api.edit; the mutator works.
            service.setStringResult(spec["string_result"])
            # One decimal for the numeric results (96.7 %, 2.4 %) - the stock
            # precision of 0 would print 97.
            service.setPrecision(1)
            service.setInterimFields([dict(i, hidden=False, wide=False) for i in spec["interims"]])
            service.setDescription(spec["description"])
            service.reindexObject()
        except Exception as exc:
            log.append("interims %s: %r" % (spec["keyword"], exc))
        services[spec["keyword"]] = service
    return services


def ensure_specification(portal, log, sample_type):
    setup = api.get_setup()
    folder = setup.bika_analysisspecs
    spec = _first(folder, "AnalysisSpec", Title=SPEC_TITLE)
    if spec is None:
        spec = api.create(folder, "AnalysisSpec", title=SPEC_TITLE, SampleType=sample_type)
        log.append("specification created")
    try:
        spec.setResultsRange([dict(r) for r in SPEC_RANGES])
        spec.reindexObject()
    except Exception as exc:
        log.append("results range: %r" % exc)
    return spec


def ensure_project(portal, log, client):
    projects = getattr(portal, "projects", None)
    if projects is None:
        log.append("maitux.projects not installed: no Project created")
        return None
    # Plone lower-cases content ids, so match on the client project id
    project = _first(projects, "Project", client_project_id=PROJECT_ID) or projects.get(PROJECT_ID.lower())
    if project is None:
        project = api.create(projects, "Project", id=PROJECT_ID.lower(), title=PROJECT_TITLE, client=api.get_uid(client), client_project_id=PROJECT_ID, description="MaiELN x MaiLIMS integrated demo project (synthetic data)")
        log.append("project %s created" % PROJECT_ID)
    return project


def ensure_sample_id_format(portal, log):
    setup = api.get_setup()
    formats = [dict(f) for f in setup.getIDFormatting()]
    entry = {"form": sample_id_form(), "portal_type": "AnalysisRequest", "prefix": "analysisrequest", "sequence_type": "generated", "split_length": SAMPLE_ID_SPLIT, "counter_type": "", "counter_reference": "", "context": ""}
    others = [f for f in formats if f.get("portal_type") != "AnalysisRequest"]
    setup.setIDFormatting(others + [entry])
    log.append("sample id format %s" % sample_id_form())
    rewind_sample_counter(log)


def sample_id_form():
    return SAMPLE_ID_FORM % datetime.now().year


def sample_counter_key():
    prefix = idserver.slice(sample_id_form(), separator="-", end=SAMPLE_ID_SPLIT)
    return idserver.make_storage_key("analysisrequest", prefix)


def next_sample_id():
    return sample_id_form().format(seq=SAMPLE_SEQ_START + 1)


def rewind_sample_counter(log):
    generator = getUtility(INumberGenerator)
    key = sample_counter_key()
    generator.set_number(key, SAMPLE_SEQ_START)
    log.append("counter %s = %s" % (key, SAMPLE_SEQ_START))


def demo_samples(portal):
    query = {"portal_type": "AnalysisRequest", "sort_on": "created"}
    out = []
    for brain in api.search(query, "senaite_catalog_sample"):
        if api.get_id(brain).startswith(SAMPLE_PREFIX):
            out.append(api.get_object(brain))
    return out


# --- entry points -----------------------------------------------------------


def seed(portal):
    log = []
    users = ensure_users(portal, log)
    lab_contacts = ensure_lab_contacts(portal, log)
    departments = ensure_departments(portal, log, lab_contacts)
    client, contact = ensure_client(portal, log, users)
    sample_type = ensure_sample_type(portal, log)
    services = ensure_services(portal, log, departments)
    specification = ensure_specification(portal, log, sample_type)
    project = ensure_project(portal, log, client)
    ensure_sample_id_format(portal, log)
    result = {
        "client_uid": api.get_uid(client),
        "client_path": api.get_path(client),
        "contact_uid": api.get_uid(contact),
        "sample_type_uid": api.get_uid(sample_type),
        "specification_uid": api.get_uid(specification),
        "project_uid": api.get_uid(project) if project else None,
        "project_url": api.get_url(project) if project else None,
        "services": dict((k, api.get_uid(v)) for k, v in services.items()),
        "departments": dict((k, api.get_uid(v)) for k, v in departments.items()),
        "users": list(users.keys()),
        "next_sample_id": next_sample_id(),
        "log": log,
    }
    logger.info("elnlink demo seed: %s", "; ".join(log))
    return result


def reset(portal):
    log = []
    deleted = []
    for sample in demo_samples(portal):
        sample_id = api.get_id(sample)
        try:
            parent = api.get_parent(sample)
            parent.manage_delObjects([sample_id])
            deleted.append(sample_id)
        except Exception as exc:
            log.append("delete %s: %r" % (sample_id, exc))
    rewind_sample_counter(log)
    logger.info("elnlink demo reset: deleted %s; %s", deleted, "; ".join(log))
    return {"deleted": deleted, "log": log, "next_sample_id": next_sample_id()}
