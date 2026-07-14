# -*- coding: utf-8 -*-
"""Check actual portal type of setup objects."""
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

# Check portal_types for Setup and BikaSetup
for pt in ('Setup', 'BikaSetup', 'Bika Setup'):
    code, body = get_url("%s/portal_types/%s/manage_propertiesForm" % (base, pt))
    if code == 200:
        print("=== %s FTI exists ===" % pt)
        # Extract behaviors
        b_match = re.search(r'name="behaviors[^"]*"[^>]*>([^<]+)', body)
        if b_match:
            print("  Behaviors: %s" % b_match.group(1))
    else:
        print("=== %s FTI: HTTP %d ===" % (pt, code))

# Check the actual setup object at portal root
code, body = get_url("%s/setup/manage_propertiesForm" % base)
print("\n=== /setup: HTTP %d ===" % code)
if code == 200:
    # Find meta_type or portal_type
    mt = re.search(r'Meta.?[Tt]ype.*?value="([^"]+)"', body)
    pt2 = re.search(r'portal.?[Tt]ype.*?value="([^"]+)"', body)
    print("  meta_type: %s" % (mt.group(1) if mt else 'NOT FOUND'))
    print("  portal_type: %s" % (pt2.group(1) if pt2 else 'NOT FOUND'))

# Check bika_setup
code2, body2 = get_url("%s/bika_setup/manage_propertiesForm" % base)
print("\n=== /bika_setup: HTTP %d ===" % code2)
if code2 == 200:
    mt2 = re.search(r'Meta.?[Tt]ype.*?value="([^"]+)"', body2)
    pt3 = re.search(r'portal.?[Tt]ype.*?value="([^"]+)"', body3) if 2>1 else None
    print("  meta_type: %s" % (mt2.group(1) if mt2 else 'NOT FOUND'))
