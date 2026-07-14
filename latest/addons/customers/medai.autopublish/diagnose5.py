# -*- coding: utf-8 -*-
"""Final diagnostic: check checkbox HTML and try direct folder creation."""
import urllib2, base64, re

AUTH = base64.b64encode(b"admin:admin")

def get_url(url, data=None):
    req = urllib2.Request(url, data)
    req.add_header("Authorization", "Basic %s" % AUTH)
    try:
        r = urllib2.urlopen(req)
        return r.code, r.read()
    except urllib2.HTTPError as e:
        return e.code, e.read()

site = "senaite8"
base = "http://localhost:8080/%s" % site

# 1. Check the full checkbox HTML
code, body = get_url("%s/setup/edit" % base)
idx = body.find('IReportDraftingSetup')
snippet = body[idx:idx+800]
# Find the input element
input_match = re.search(r'<input[^>]*report_drafting[^>]*>', snippet)
print("=== Checkbox input ===")
if input_match:
    print(input_match.group(0))
else:
    # Show all line breaks and tags
    print(snippet[:800])

# 2. Check if field is in unnamed fieldset (default/Sampling tab)
# Find fieldset before report_drafting
fs_start = body.rfind('<fieldset', 0, idx)
fs_snippet = body[fs_start:fs_start+100]
print("\n=== Enclosing fieldset ===")
print(fs_snippet)

# 3. Try to create analysis_reports folder via manage_addFolder
# First get auth token from the page
code2, body2 = get_url("%s/overview" % base)
auth_match = re.search(r'_authenticator.*?value="([^"]+)"', body2)
if auth_match:
    token = auth_match.group(1)
    # Try creating folder via POST
    import urllib
    data = urllib.urlencode({
        'id': 'analysis_reports',
        'type_name': 'Folder',
        '_authenticator': token,
    })
    code3, body3 = get_url("%s/portal_factory/Folder/analysis_reports/@@edit" % base)
    print("\n=== Folder creation attempt ===")
    print("portal_factory: HTTP %d" % code3)
    
    # Try manage_addFolder directly
    url4 = "%s/manage_addProduct/OFSP/manage_addFolder" % base
    data4 = urllib.urlencode({
        'id': 'analysis_reports',
        '_authenticator': token,
    })
    code4, body4 = get_url(url4, data4)
    print("manage_addFolder: HTTP %d" % code4)
    if code4 == 302:
        print("  Redirect to: %s" % body4)
