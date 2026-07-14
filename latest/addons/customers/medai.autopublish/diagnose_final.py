# -*- coding: utf-8 -*-
"""Re-verify setup edit form HTML and check /setup vs /bika_setup."""
import urllib2, base64, re

AUTH = base64.b64encode(b"admin:admin")

def get_url(url):
    req = urllib2.Request(url)
    req.add_header("Authorization", "Basic %s" % AUTH)
    try:
        r = urllib2.urlopen(req)
        return r.code, r.read()
    except urllib2.HTTPError as e:
        return e.code, e.read()

site = "senaite8"
base = "http://localhost:8080/%s" % site

# 1. Check /setup/edit for report_drafting
print("=== /setup/edit ===")
code, body = get_url("%s/setup/edit" % base)
print("HTTP %d, len=%d" % (code, len(body)))
idx = body.find('IReportDraftingSetup')
print("IReportDraftingSetup at char: %d" % idx)
if idx > 0:
    snippet = body[idx:idx+500]
    print(snippet[:500])
    # Check for checkbox input
    cb = re.search(r'<input[^>]*report_drafting[^>]*>', body[idx:idx+1000])
    print("Checkbox found: %s" % (cb is not None))

# 2. Check /bika_setup/edit for report_drafting
print("\n=== /bika_setup/edit ===")
code2, body2 = get_url("%s/bika_setup/edit" % base)
print("HTTP %d, len=%d" % (code2, len(body2)))
idx2 = body2.find('IReportDraftingSetup')
print("IReportDraftingSetup at char: %d" % idx2)

# 3. Check what /setup actually resolves to
print("\n=== /setup (view) redirect check ===")
code3, body3 = get_url("%s/setup" % base)
# Check if it's a redirect
print("HTTP %d" % code3)

# 4. Check the portal_types to see all Setup-like types
print("\n=== Available Setup FTI types ===")
code4, body4 = get_url("%s/portal_types/manage_main" % base)
for name in ('Setup', 'BikaSetup', 'BikaSetUp', 'bika_setup'):
    if name in body4:
        print("  %s: FOUND" % name)
    else:
        print("  %s: NOT in list" % name)
