# -*- coding: utf-8 -*-
"""Directly create analysis_reports folder via Zope management."""
import urllib2, base64, urllib, re

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

# First get the authenticator token
code, body = get_url("%s/setup" % base)
token_match = re.search(r'_authenticator.*?value="([^"]+)"', body)
token = token_match.group(1) if token_match else ""
print("Token: %s" % (token[:20] if token else "NOT FOUND"))

# Try manage_addFolder
url = "%s/manage_addProduct/OFSP/manage_addFolder" % base
data = urllib.urlencode({
    'id': 'analysis_reports',
    '_authenticator': token,
})
code2, body2 = get_url(url, data)
print("manage_addFolder: HTTP %d" % code2)
if code2 in (200, 302):
    print("  Success (redirect or OK)")
elif code2 == 401:
    print("  Unauthorized - token issue")
else:
    print("  Response: %s" % body2[:200])

# Also try the management interface method
url3 = "%s/manage_main" % base
code3, body3 = get_url(url3)
token2 = re.search(r'_authenticator.*?value="([^"]+)"', body3)
token2_val = token2.group(1) if token2 else token
print("\nZMI token: %s" % (token2_val[:20] if token2_val else "NOT FOUND"))

# Try creating via portal_factory
url4 = "%s/portal_factory/Folder/analysis_reports/@@edit" % base
code4, body4 = get_url(url4)
print("portal_factory: HTTP %d" % code4)

# Verify if folder exists
code5, body5 = get_url("%s/analysis_reports" % base)
print("analysis_reports access: HTTP %d" % code5)
