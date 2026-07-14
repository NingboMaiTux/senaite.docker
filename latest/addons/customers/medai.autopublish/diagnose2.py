# -*- coding: utf-8 -*-
"""Detailed diagnostic for QI page."""
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

# Check senaite8 QI page and extract medai sections
code, body = get_url("http://localhost:8080/senaite8/prefs_install_products_form")

# Find medai sections
for name in ('autopublish', 'reportsportal'):
    idx = body.find('medai.%s' % name)
    if idx > 0:
        snippet = body[max(0,idx-200):idx+500]
        # Replace HTML entities for readability
        snippet = snippet.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        print("\n--- medai.%s (around char %d) ---" % (name, idx))
        print(snippet[:700])
    else:
        print("\n--- medai.%s NOT FOUND in page ---" % name)

# Also check: is there an "Installed products" section?
idx_installed = body.find('Installed products')
print("\n--- 'Installed products' found at: %d ---" % idx_installed if idx_installed > 0 else 0)

# Check for "Available for install" 
idx_avail = body.find('available')
print("--- 'available' found at: %d ---" % (idx_avail if idx_avail > 0 else 0))
