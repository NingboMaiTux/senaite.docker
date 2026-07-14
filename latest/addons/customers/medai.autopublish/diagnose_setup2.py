# -*- coding: utf-8 -*-
"""Check actual portal_type of /bika_setup object."""
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
base = "http://localhost:8080/%s" % site

# Check BikaSetup FTI behaviors
print("=== BikaSetup FTI ===")
code, body = get_url("%s/portal_types/BikaSetup/manage_propertiesForm" % base)
if code == 200:
    import re
    b_match = re.search(r'name="behaviors[^"]*"[^>]*>([^<]+)', body)
    if b_match:
        print("  Behaviors: %s" % b_match.group(1))
    else:
        # Try textarea
        ta_match = re.search(r'<textarea[^>]*name="behaviors[^"]*"[^>]*>(.*?)</textarea>', body, re.DOTALL)
        if ta_match:
            print("  Behaviors: %s" % ta_match.group(1).strip())
else:
    print("  HTTP %d" % code)

# Check what's at /bika_setup
print("\n=== /bika_setup object ===")
code2, body2 = get_url("%s/bika_setup" % base)
import re
# Look for portal_type in the page
pt = re.search(r'portal_type["\s:=]+["\']?(\w+)', body2)
if pt:
    print("  portal_type (from page): %s" % pt.group(1))

# Check manage_propertiesForm of bika_setup
code3, body3 = get_url("%s/bika_setup/manage_propertiesForm" % base)
print("  manage_propertiesForm: HTTP %d" % code3)
if code3 == 200:
    mt = re.search(r'Meta.?[Tt]ype.*?value="([^"]+)"', body3)
    pt2 = re.search(r'portal.?[Tt]ype.*?value="([^"]+)"', body3)
    print("  meta_type: %s" % (mt.group(1) if mt else 'NOT FOUND'))
    print("  portal_type: %s" % (pt2.group(1) if pt2 else 'NOT FOUND'))
    # Check behaviors textarea
    b2 = re.search(r'<textarea[^>]*name="behaviors[^"]*"[^>]*>(.*?)</textarea>', body3, re.DOTALL)
    if b2:
        print("  behaviors: %s" % b2.group(1).strip())
