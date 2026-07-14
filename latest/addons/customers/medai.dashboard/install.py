#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""Install medai.dashboard addon into a Senaite Docker container.

Usage:
    docker exec <container> python /path/to/medai.dashboard/install.py
    docker restart <container>
    # Then go to QuickInstaller and install the addon.
"""
import os
import sys

# Standard Senaite Docker paths
SENAITE_HOME = "/home/senaite/senaitelims"
SRC_PATH = os.path.join(SENAITE_HOME, "src", "medai.dashboard", "src")
INTERPRETER_PATH = os.path.join(SENAITE_HOME, "parts", "instance", "bin", "interpreter")
EGG_LINK_PATH = os.path.join(SENAITE_HOME, "develop-eggs", "medai.dashboard.egg-link")
SLUGS_DIR = os.path.join(SENAITE_HOME, "parts", "instance", "etc", "package-includes")


def _package_dir():
    """Return the directory containing this script."""
    return os.path.dirname(os.path.abspath(__file__))


def ensure_dir(path):
    """Create directory if it doesn't exist."""
    if not os.path.exists(path):
        try:
            os.makedirs(path)
            print("Created directory:", path)
        except Exception as e:
            print("WARNING: could not create", path, "-", e)


def fix_interpreter():
    """Add medai.dashboard to Zope interpreter's sys.path."""
    if not os.path.exists(INTERPRETER_PATH):
        print("Interpreter not found at", INTERPRETER_PATH, "- skipping.")
        return True  # not fatal

    with open(INTERPRETER_PATH, 'r') as f:
        content = f.read()

    if "medai.dashboard" in content:
        print("Interpreter already has medai.dashboard. Skipping.")
        return True

    insert_line = "  '{}',\n".format(SRC_PATH)
    old = "sys.path[0:0] = [\n"
    new = old + insert_line
    content = content.replace(old, new, 1)

    with open(INTERPRETER_PATH, 'w') as f:
        f.write(content)

    print("Interpreter updated with medai.dashboard path.")
    return True


def create_egg_link():
    """Create egg-link for medai.dashboard."""
    if os.path.exists(EGG_LINK_PATH):
        print("Egg-link already exists.")
        return True
    try:
        pkg_dir = os.path.dirname(_package_dir())
        ensure_dir(os.path.dirname(EGG_LINK_PATH))
        with open(EGG_LINK_PATH, 'w') as f:
            f.write(pkg_dir + "\n")
        print("Egg-link created at", pkg_dir)
        return True
    except Exception as e:
        print("ERROR creating egg-link:", e)
        return True


def create_zcml_slugs():
    """Create ZCML slug so QuickInstaller can discover the addon."""
    ensure_dir(SLUGS_DIR)

    config_file = os.path.join(SLUGS_DIR, "150-medai.dashboard-configure.zcml")
    if not os.path.exists(config_file):
        with open(config_file, "w") as f:
            f.write('<configure xmlns="http://namespaces.zope.org/zope">\n')
            f.write('  <include package="medai.dashboard" />\n')
            f.write('</configure>\n')
        print("ZCML configure slug created.")

    # No overrides.zcml -- JS resource override uses browser layer
    # (..interfaces.IMedAIDashboardLayer) for site-level isolation.
    return True


if __name__ == "__main__":
    print("=== Setting up medai.dashboard ===")
    fix_interpreter()
    create_egg_link()
    create_zcml_slugs()
    print("All setup steps completed.")
