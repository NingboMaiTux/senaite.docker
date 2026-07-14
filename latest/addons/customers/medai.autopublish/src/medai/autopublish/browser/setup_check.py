# -*- coding: utf-8 -*-
"""BrowserView to check/fix medai.autopublish post_install state on 8084.

Access: /@@fix-medai-setup
"""

from Products.Five import BrowserView
from zope.component.hooks import getSite


REPORT_DRAFTING = "medai.autopublish.behaviors.report_drafting_setup.IReportDraftingSetup"
DEPT_FILTER = "medai.autopublish.behaviors.department_filter.IDepartmentFilterSetup"

# Required behaviors on SampleType FTI that must NOT be removed
SAMPLE_TYPE_REQUIRED_BEHAVIORS = [
    "bika.lims.interfaces.IAutoGenerateID",
    "bika.lims.interfaces.IMultiCatalogBehavior",
    "plone.app.referenceablebehavior.referenceable.IReferenceable",
]


def _get_types_tool():
    portal = getSite()
    return portal.portal_types


def _get_catalog(catalog_id):
    portal = getSite()
    return getattr(portal, catalog_id)


class FixMedaiSetupView(BrowserView):
    """Diagnose and fix medai.autopublish setup state."""

    def __call__(self):
        lines = ["<h2>medai.autopublish Setup Check / Fix</h2>", "<pre>"]
        portal = getSite()

        # --- Behaviors ---
        lines.append("=== Behaviors on Setup FTI ===")
        try:
            types_tool = portal.portal_types
            fti = types_tool.get("Setup")
            if fti is None:
                lines.append("  ERROR: FTI 'Setup' not found!")
            else:
                for label, behavior in [
                    ("report_drafting", REPORT_DRAFTING),
                    ("department_filter", DEPT_FILTER),
                ]:
                    if behavior in fti.behaviors:
                        lines.append("  %-25s : already bound" % label)
                    else:
                        behaviors = list(fti.behaviors)
                        behaviors.append(behavior)
                        fti.behaviors = tuple(behaviors)
                        lines.append("  %-25s : bound OK" % label)
        except Exception as e:
            lines.append("  ERR: %s" % e)

        # --- SampleType FTI behaviors (critical: IMultiCatalogBehavior!) ---
        lines.append("")
        lines.append("=== SampleType FTI Behaviors ===")
        try:
            st_fti = types_tool.get("SampleType")
            if st_fti is None:
                lines.append("  ERROR: FTI 'SampleType' not found!")
            else:
                current = list(st_fti.behaviors)
                lines.append("  Current behaviors: %s" % current)
                for rb in SAMPLE_TYPE_REQUIRED_BEHAVIORS:
                    if rb in current:
                        lines.append("  %-50s : OK" % rb)
                    else:
                        lines.append("  %-50s : MISSING - restoring..." % rb)
                        current.append(rb)
                if len(current) != len(st_fti.behaviors):
                    st_fti.behaviors = tuple(current)
                    lines.append("  Behaviors restored!")
                else:
                    lines.append("  All required behaviors present")
        except Exception as e:
            lines.append("  ERR: %s" % e)

        # --- Catalog indexes ---
        lines.append("")
        lines.append("=== Catalog Indexes ===")
        try:
            catalog_checks = [
                ("sample.department_uids",
                 "senaite_catalog_sample", "department_uids", "KeywordIndex"),
                ("analysis.getDepartmentUID",
                 "senaite_catalog_analysis", "getDepartmentUID", "FieldIndex"),
            ]
            for label, cat_id, idx_name, idx_type in catalog_checks:
                cat = getattr(portal, cat_id, None)
                if cat is None:
                    lines.append("  %-30s : catalog not found!" % label)
                elif idx_name in cat.indexes():
                    lines.append("  %-30s : already exists" % label)
                else:
                    cat.addIndex(idx_name, idx_type)
                    lines.append("  %-30s : added OK" % label)
        except Exception as e:
            lines.append("  ERR: %s" % e)

        # --- Auto Verify Samples ---
        lines.append("")
        lines.append("=== Auto Verify Samples ===")
        try:
            from bika.lims import api as bika_api
            setup = bika_api.get_senaite_setup()
            if getattr(setup, "getAutoVerifySamples", lambda: None)():
                lines.append("  AutoVerifySamples : already enabled")
            else:
                setup.setAutoVerifySamples(True)
                lines.append("  AutoVerifySamples : enabled OK")
        except Exception as e:
            lines.append("  ERR: %s" % e)

        # --- Entry folders ---
        lines.append("")
        lines.append("=== Entry Folders ===")
        try:
            for folder_id, title in sorted({
                "analysis_reports": "分析报告",
                "samples-to-verify": "待审核",
                "samples-to-approve": "待批准",
            }.items()):
                if folder_id in portal.objectIds():
                    try:
                        folder = getattr(portal, folder_id)
                        folder.setTitle(title)
                        folder.reindexObject()
                        lines.append("  %-25s : title updated" % folder_id)
                    except Exception as e2:
                        lines.append("  %-25s : ERR %s" % (folder_id, e2))
                else:
                    try:
                        portal.manage_addProduct["OFSP"].manage_addFolder(folder_id)
                        folder = getattr(portal, folder_id)
                        folder.setTitle(title)
                        folder.reindexObject()
                        lines.append("  %-25s : created OK" % folder_id)
                    except Exception as e2:
                        lines.append("  %-25s : ERR %s" % (folder_id, e2))
        except Exception as e:
            lines.append("  ERR: %s" % e)

        # --- Publisher role for clerk1 ---
        lines.append("")
        lines.append("=== User Roles ===")
        try:
            _ensure_publisher_role(portal, "clerk1", lines)
        except Exception as e:
            lines.append("  ERR: %s" % e)

        # --- Sample Type ---
        lines.append("")
        lines.append("=== Sample Types ===")
        try:
            _ensure_sample_type(portal, lines)
        except Exception as e:
            lines.append("  ERR: %s" % e)

        # --- Sample Template ---
        lines.append("")
        lines.append("=== Sample Templates ===")
        try:
            _ensure_sample_template(portal, lines)
        except Exception as e:
            lines.append("  ERR: %s" % e)

        # --- Catalog Diagnostic ---
        lines.append("")
        lines.append("=== Catalog Diagnostic ===")
        try:
            _run_catalog_diagnostic(portal, lines)
        except Exception as e:
            lines.append("  ERR: %s" % e)

        lines.append("</pre>")
        safe = []
        for item in lines:
            if isinstance(item, unicode):
                safe.append(item)
            else:
                safe.append(item.decode("utf-8", "replace"))
        return u"\n".join(safe)


def _ensure_publisher_role(portal, username, lines):
    """Grant Publisher role to the given user so they can perform the
    first-level publish (submit_for_report transition)."""
    acl = getattr(portal, "acl_users", None)
    if acl is None:
        lines.append("  ERR: acl_users not found")
        return
    user = acl.getUserById(username)
    if user is None:
        lines.append("  %-15s : user not found in acl_users" % username)
        return
    roles = list(user.getRoles())
    if "Publisher" in roles:
        lines.append("  %-15s : already has Publisher" % username)
    else:
        roles.append("Publisher")
        acl.userFolderEditUser(username, '', roles, [])
        lines.append("  %-15s : Publisher assigned OK" % username)


def _get_setup():
    """Get the Senaite setup object."""
    from bika.lims import api
    return api.get_senaite_setup()


def _ensure_sample_type(portal, lines):
    """Create SampleType if it does not exist,
    and enable auto_publish so verified samples skip Impress.
    """
    from bika.lims import api
    ST_TITLE = api.safe_unicode("原料检验")
    setup = api.get_senaite_setup()
    st_folder = getattr(setup, "sampletypes", None)
    if st_folder is None:
        lines.append("  ERR: sampletypes folder not found")
        return

    st_id = "rm-yljy"

    # If existing object has a garbled title, delete and recreate
    if st_id in st_folder.objectIds():
        st_obj = st_folder[st_id]
        current_title = st_obj.Title()
        if "\\u" in current_title:
            # Title is garbled (Unicode escapes as literal text), delete and recreate
            lines.append("  %-25s : exists but title garbled (%s)" %
                        (ST_TITLE, current_title[:40]))
            # Unindex first
            sc = api.get_tool("senaite_catalog_setup")
            if sc is not None:
                try:
                    path = "/".join(st_obj.getPhysicalPath())
                    sc.uncatalog_object(path)
                except Exception:
                    pass
            api.delete(st_obj, check_permissions=False)
            lines.append("  %-25s : deleted, will recreate" % ST_TITLE)
        else:
            lines.append("  %-25s : exists (id=%s, title OK)" % (ST_TITLE, st_id))
            # Enable auto_publish
            _set_auto_publish(st_obj, lines)
            st_obj.reindexObject()
            return

    # Create new
    try:
        st_obj = api.create(st_folder, "SampleType",
                            id=st_id,
                            title=ST_TITLE,
                            description="Raw material inspection")
        lines.append("  %-25s : created OK (id=%s)" % (ST_TITLE, st_id))
    except Exception as e:
        lines.append("  %-25s : ERR %s" % (ST_TITLE, e))
        return

    # Enable auto_publish
    _set_auto_publish(st_obj, lines)

    # Force catalog into senaite_catalog_setup (api.create may not fire
    # events that trigger initial cataloging; reindexObject won't help)
    sc = api.get_tool("senaite_catalog_setup")
    if sc is not None:
        path = "/".join(st_obj.getPhysicalPath())
        sc.catalog_object(st_obj, path)
        lines.append("  %-25s : cataloged into setup catalog" % "")
    st_obj.reindexObject()


def _set_auto_publish(st_obj, lines):
    """Enable auto_publish on a SampleType via behavior adapter."""
    try:
        from medai.autopublish.behaviors.auto_publish import IAutoPublishBehavior
        behavior = IAutoPublishBehavior(st_obj, None)
        if behavior is not None:
            if behavior.auto_publish == "enabled":
                lines.append("  %-25s : auto_publish already enabled" % "")
            else:
                behavior.auto_publish = "enabled"
                lines.append("  %-25s : auto_publish set to enabled" % "")
        else:
            lines.append("  %-25s : WARN IAutoPublishBehavior not bound" % "")
    except Exception as e:
        lines.append("  %-25s : ERR setting auto_publish: %s" % ("", e))


def _ensure_sample_template(portal, lines):
    """Create SampleTemplate if it does not exist."""
    from bika.lims import api
    TMPL_TITLE = api.safe_unicode("原料快速检验")
    setup = api.get_senaite_setup()
    st_folder = getattr(setup, "sampletypes", None)
    tmpl_folder = getattr(setup, "sampletemplates", None)
    if tmpl_folder is None:
        lines.append("  ERR: sampletemplates folder not found")
        return

    tmpl_id = "rm-yljy-01"

    # If existing object has garbled title, delete and recreate
    if tmpl_id in tmpl_folder.objectIds():
        tmpl_obj = tmpl_folder[tmpl_id]
        current_title = tmpl_obj.Title()
        if "\\u" in current_title:
            lines.append("  %-25s : exists but title garbled (%s)" %
                        (TMPL_TITLE, current_title[:40]))
            sc = api.get_tool("senaite_catalog_setup")
            if sc is not None:
                try:
                    sc.uncatalog_object("/".join(tmpl_obj.getPhysicalPath()))
                except Exception:
                    pass
            api.delete(tmpl_obj, check_permissions=False)
            lines.append("  %-25s : deleted, will recreate" % TMPL_TITLE)
        else:
            lines.append("  %-25s : exists (id=%s, title OK)" % (TMPL_TITLE, tmpl_id))
            return

    # Find the SampleType
    if st_folder is None or "rm-yljy" not in st_folder.objectIds():
        lines.append("  %-25s : SKIP (SampleType not found)" % TMPL_TITLE)
        return
    sampletype = st_folder["rm-yljy"]

    # Find 2 common analysis services via catalog
    sc = api.get_tool("senaite_catalog_setup")
    if sc is None:
        lines.append("  %-25s : SKIP (setup catalog not found)" % TMPL_TITLE)
        return

    service_uids = []
    for kw in ["pH", "Appearance", "HeavyMetals", "pH值", "外观", "重金属"]:
        brains = sc.searchResults(
            portal_type="AnalysisService",
            getKeyword=kw)
        if brains:
            uid = brains[0].UID
            if uid not in service_uids:
                service_uids.append(uid)
        if len(service_uids) >= 2:
            break

    if len(service_uids) < 1:
        lines.append("  %-25s : SKIP (no suitable analysis services found)" % TMPL_TITLE)
        return

    try:
        tmpl = api.create(tmpl_folder, "SampleTemplate",
                          id=tmpl_id,
                          title=TMPL_TITLE)
        tmpl.setSampleType(sampletype)
        tmpl.setServices(service_uids)
        tmpl.reindexObject()
        lines.append("  %-25s : created OK (id=%s, %d services)" %
                    (TMPL_TITLE, tmpl_id, len(service_uids)))
    except Exception as e:
        lines.append("  %-25s : ERR %s" % (TMPL_TITLE, e))


def _run_catalog_diagnostic(portal, lines):
    """Compare ZODB vs catalog for sampletypes and fix missing entries."""
    from bika.lims import api
    setup = api.get_senaite_setup()
    sc = api.get_tool("senaite_catalog_setup")
    if sc is None:
        lines.append("  senaite_catalog_setup not found!")
        return

    st_folder = setup.sampletypes

    # 1. Count objects in ZODB vs catalog
    zodb_ids = sorted(st_folder.objectIds())
    brains = sc.searchResults(portal_type="SampleType")
    cat_ids = sorted([b.getId for b in brains] if brains else [])

    lines.append("  ZODB  sampletypes: %d" % len(zodb_ids))
    lines.append("  CATALOG sampletypes: %d" % len(cat_ids))

    # Fix sampletemplates too
    tmpl_folder = setup.sampletemplates
    zodb_tmpl_ids = sorted(tmpl_folder.objectIds())
    tmpl_brains = sc.searchResults(portal_type="SampleTemplate")
    cat_tmpl_ids = sorted([b.getId for b in tmpl_brains] if tmpl_brains else [])

    lines.append("")
    lines.append("  Template ZODB : %d" % len(zodb_tmpl_ids))
    lines.append("  Template CAT  : %d" % len(cat_tmpl_ids))
    missing_tmpl = set(zodb_tmpl_ids) - set(cat_tmpl_ids)
    if missing_tmpl:
        lines.append("  ** Template MISSING: %s" % ", ".join(sorted(missing_tmpl)))
        for obj_id in sorted(missing_tmpl):
            obj = tmpl_folder[obj_id]
            path = "/".join(obj.getPhysicalPath())
            try:
                sc.catalog_object(obj, path)
                st_uid = getattr(obj, 'sampletype_uid', '?')
                lines.append("    + cataloged %s (st_uid=%s)" % (obj_id, st_uid[:12] + "..."))
            except Exception as exc:
                lines.append("    ! FAILED %s: %s" % (obj_id, exc))
    # Fix stale catalog entries (catalog has more than ZODB)
    stale = set(cat_tmpl_ids) - set(zodb_tmpl_ids)
    if stale:
        lines.append("  ** Stale CAT entries (not in ZODB): %s" % ", ".join(sorted(stale)))
        for obj_id in sorted(stale):
            try:
                path = "/".join(tmpl_folder.getPhysicalPath()) + "/" + obj_id
                sc.uncatalog_object(path)
                lines.append("    - uncataloged %s" % obj_id)
            except Exception as exc:
                lines.append("    ! FAILED %s: %s" % (obj_id, exc))
    else:
        lines.append("  all templates in catalog OK")

    # Also fix stale sampletypes in catalog
    stale_st = set(cat_ids) - set(zodb_ids)
    if stale_st:
        lines.append("  ** Stale ST entries: %s" % ", ".join(sorted(stale_st)))
        for obj_id in sorted(stale_st):
            try:
                path = "/".join(st_folder.getPhysicalPath()) + "/" + obj_id
                sc.uncatalog_object(path)
            except Exception:
                pass

    # Check template SampleType references
    lines.append("")
    lines.append("  Template -> SampleType references:")
    for obj_id in sorted(zodb_tmpl_ids):
        obj = tmpl_folder[obj_id]
        try:
            st = obj.getSampleType()
        except Exception as exc:
            lines.append("  ! %s: getSampleType() error: %s" % (obj_id, exc))
            continue
        if st is None:
            lines.append("  ! %s: SampleType None (dangling UID)" % obj_id)
        elif not st.Title() or "\\u" in st.Title():
            lines.append("  ! %s: SampleType title garbled: %r" % (obj_id, st.Title()))
        else:
            lines.append("  OK %s -> %s" % (obj_id, st.Title()))

    missing = set(zodb_ids) - set(cat_ids)
    if missing:
        lines.append("  ** MISSING from catalog: %s" % ", ".join(sorted(missing)))
        lines.append("  ** Fixing: cataloging missing objects...")
        for obj_id in sorted(missing):
            obj = st_folder[obj_id]
            path = "/".join(obj.getPhysicalPath())
            try:
                sc.catalog_object(obj, path)
                lines.append("    + cataloged %s (title=%r)" % (obj_id, obj.Title()))
            except Exception as exc:
                lines.append("    ! FAILED %s: %s" % (obj_id, exc))
    else:
        lines.append("  all sampletypes are in catalog OK")


class DebugInterimFieldsView(BrowserView):
    """Diagnose InterimFields differences between imported vs. manually-created
    Analysis Services.

    Access: /@@debug-interimfields
    """

    def __call__(self):
        lines = ["<h2>InterimFields Diagnostic</h2>", "<pre>"]
        portal = getSite()
        setup = portal.bika_setup
        as_folder = setup.bika_analysisservices
        calc_folder = setup.bika_calculations

        # --- List all Analysis Services ---
        lines.append("=== All Analysis Services ===")
        for obj in as_folder.objectValues():
            kw = obj.getKeyword()
            calc = obj.getCalculation()
            calc_uid = calc.UID() if calc else "None"
            interims = obj.getInterimFields()
            lines.append("  %-20s | calc=%s | interims_count=%d" %
                        (kw, calc_uid[:40] if calc else "None",
                         len(interims) if interims else 0))
            if interims:
                for im in interims:
                    hidden = im.get("hidden", False)
                    lines.append("    interim: kw=%s  hidden=%s  result_type=%s" %
                               (im.get("keyword", ""), hidden,
                                im.get("result_type", "")))

        # --- List all Calculations ---
        lines.append("")
        lines.append("=== All Calculations ===")
        for obj in calc_folder.objectValues():
            title = obj.Title()
            interims = obj.getInterimFields()
            lines.append("  %-30s | uid=%.30s | interims_count=%d" %
                        (title, obj.UID(), len(interims) if interims else 0))
            if interims:
                for im in interims:
                    hidden = im.get("hidden", False)
                    lines.append("    calc_interim: kw=%s  title=%s  hidden=%s  type=%s" %
                               (im.get("keyword", ""), im.get("title", ""),
                                hidden, im.get("type", "")))

        # --- Find first sample with analyses and check them ---
        lines.append("")
        lines.append("=== Sample Analyses (first 3 samples with analyses) ===")
        sc = portal.senaite_catalog_sample
        brains = sc.searchResults(portal_type="AnalysisRequest",
                                  review_state="sample_received",
                                  sort_on="created")
        count = 0
        for b in brains:
            if count >= 3:
                break
            ar = b.getObject()
            lines.append("")
            lines.append("  Sample: %s (id=%s)" % (ar.getId(), ar.getId()))
            for an in ar.objectValues("Analysis"):
                if not hasattr(an, "getKeyword"):
                    continue
                kw = an.getKeyword()
                calc = an.getCalculation()
                calc_title = calc.Title() if calc else "None"
                interims = an.getInterimFields()
                lines.append("    Analysis: %-25s calc=%s interims_count=%d" %
                           (kw, calc_title, len(interims) if interims else 0))
                if interims:
                    for im in interims:
                        hidden = im.get("hidden", False)
                        lines.append("      interim: kw=%-15s title=%-15s hidden=%s value=%s" %
                                   (im.get("keyword", ""), im.get("title", ""),
                                    hidden, im.get("value", "")[:30]))
            count += 1

        lines.append("</pre>")
        lines.append("<p><b>Hint:</b> Compare imported vs. manually-created services. "
                     "Look for c_hidden=True or missing getCalculation().</p>")
        safe = []
        for item in lines:
            if isinstance(item, unicode):
                safe.append(item)
            else:
                safe.append(item.decode("utf-8", "replace"))
        return u"\n".join(safe)
