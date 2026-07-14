# -*- coding: utf-8 -*-
"""Diagnostic script to check addon installation state via HTTP."""
import urllib2
import base64
import re

AUTH = base64.b64encode(b"admin:admin")

def get_url(url, auth=AUTH):
    req = urllib2.Request(url)
    req.add_header("Authorization", "Basic %s" % auth)
    try:
        r = urllib2.urlopen(req)
        return r.code, r.read()
    except urllib2.HTTPError as e:
        return e.code, e.read()

def check(site):
    base = "http://localhost:8080/%s" % site
    print("=== Site: %s ===" % site)

    # Check QuickInstaller page
    code, body = get_url("%s/prefs_install_products_form" % base)
    print("  QI page: HTTP %d" % code)

    # Check which addons are installed
    if "medai.autopublish" in body:
        # Look for checkbox state
        m = re.search(r'medai\.autopublish.*?checked', body, re.DOTALL)
        print("  medai.autopublish: %s" % ("INSTALLED" if m else "in page but not checked"))
    else:
        print("  medai.autopublish: NOT FOUND on QI page")

    if "medai.reportsportal" in body:
        m = re.search(r'medai\.reportsportal.*?checked', body, re.DOTALL)
        print("  medai.reportsportal: %s" % ("INSTALLED" if m else "in page but not checked"))
    else:
        print("  medai.reportsportal: NOT FOUND on QI page")

    # Try to access the analysis_reports folder directly  
    code2, body2 = get_url("%s/analysis_reports" % base)
    print("  /analysis_reports: HTTP %d" % code2)

    # Check portal_types for Setup FTI behaviors
    code3, body3 = get_url("%s/portal_types/Setup/manage_propertiesForm" % base)
    print("  Setup FTI management: HTTP %d" % code3)
    if "report_drafting" in body3.lower() or "IReportDraftingSetup" in body3:
        print("  Setup behavior: FOUND report_drafting")
    else:
        print("  Setup behavior: NOT FOUND (or no access)")

check("senaite8")
check("senaite-official")
