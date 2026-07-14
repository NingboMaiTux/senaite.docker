# -*- coding: utf-8 -*-
"""Check Setup edit form HTML and try to create folder directly."""
import urllib2, base64

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

# 1. Check Setup edit form HTML for "sampling" fieldset and report_drafting
code, body = get_url("http://localhost:8080/%s/setup/edit" % site)
print("Setup edit: HTTP %d, len=%d" % (code, len(body)))

# Find sampling fieldset section
for kw in ('sampling', 'report_drafting', 'Enable Report', 'fieldset'):
    idx = body.find(kw)
    if idx > 0:
        snippet = body[max(0,idx-100):idx+200]
        print("\n--- '%s' at char %d ---" % (kw, idx))
        print(snippet[:400])
    else:
        print("\n--- '%s' NOT FOUND ---" % kw)

# 2. Check the actual behavior registrations on Setup via ZMI  
code2, body2 = get_url("http://localhost:8080/%s/portal_types/Setup/manage_propertiesForm" % site)
idx_b = body2.find("behaviors")
if idx_b > 0:
    print("\n=== Behaviors section ===")
    print(body2[idx_b:idx_b+600])
