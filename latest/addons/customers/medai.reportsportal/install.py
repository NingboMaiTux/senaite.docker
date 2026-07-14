#!/usr/bin/env python2
"""Install medai.reportsportal addon into a Senaite Docker container.

Usage:
    docker exec <container> python /path/to/medai.reportsportal/install.py
    docker restart <container>
    # Then go to QuickInstaller and install the addon.
"""
import os
import sys

# Standard Senaite Docker paths (adjust if your setup differs)
SENAITE_HOME = "/home/senaite/senaitelims"
SRC_PATH = os.path.join(SENAITE_HOME, "src", "medai.reportsportal", "src")
INTERPRETER_PATH = os.path.join(SENAITE_HOME, "parts", "instance", "bin", "interpreter")
EGG_LINK_PATH = os.path.join(SENAITE_HOME, "develop-eggs", "medai.reportsportal.egg-link")
SLUGS_DIR = os.path.join(SENAITE_HOME, "parts", "instance", "etc", "package-includes")


def _package_dir():
    """Return the directory containing this script."""
    return os.path.dirname(os.path.abspath(__file__))


def fix_interpreter():
    """Add medai.reportsportal to Zope interpreter's sys.path."""
    if not os.path.exists(INTERPRETER_PATH):
        print("ERROR: interpreter not found at", INTERPRETER_PATH)
        return False

    with open(INTERPRETER_PATH, 'r') as f:
        content = f.read()

    if "medai.reportsportal" in content:
        print("Interpreter already has medai.reportsportal. Skipping.")
        return True

    insert_line = "  '{}',\n".format(SRC_PATH)
    old = "sys.path[0:0] = [\n"
    new = old + insert_line
    content = content.replace(old, new, 1)

    with open(INTERPRETER_PATH, 'w') as f:
        f.write(content)

    print("Interpreter updated with medai.reportsportal path.")
    return True


def create_egg_link():
    """Create egg-link for medai.reportsportal."""
    if os.path.exists(EGG_LINK_PATH):
        print("Egg-link already exists.")
        return True
    try:
        pkg_dir = os.path.dirname(_package_dir())
        with open(EGG_LINK_PATH, 'w') as f:
            f.write(pkg_dir)
        print("Egg-link created at", pkg_dir)
        return True
    except Exception as e:
        print("ERROR creating egg-link:", e)
        return False


def create_zcml_slug():
    """Create ZCML slug so QuickInstaller can discover the addon."""
    config_file = os.path.join(SLUGS_DIR, "150-medai.reportsportal-configure.zcml")
    if not os.path.exists(config_file):
        with open(config_file, "w") as f:
            f.write('<configure xmlns="http://namespaces.zope.org/zope">\n')
            f.write('  <include package="medai.reportsportal" />\n')
            f.write('</configure>\n')
        print("ZCML configure slug created.")
    return True


if __name__ == "__main__":
    print("=== Setting up medai.reportsportal ===")
    ok1 = fix_interpreter()
    ok2 = create_egg_link()
    ok3 = create_zcml_slug()
    if ok1 and ok2 and ok3:
        print("All setup steps completed successfully.")
        print("Now restart the container and install via QuickInstaller.")
    else:
        print("Some steps had issues. Check output above.")
        sys.exit(1)
