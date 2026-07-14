#!/usr/bin/env python2
"""Setup medai.autopublish addon in the Zope interpreter after container restart.

Idempotent - safe to run multiple times. Graceful about missing paths.
"""
import os
import sys

# Hardcoded paths (same pattern as setup_calcenhance.py)
SENAITE_ROOT = "/home/senaite/senaitelims"
SRC_PATH = os.path.join(SENAITE_ROOT, "src", "medai.autopublish", "src")
INTERPRETER_PATH = os.path.join(SENAITE_ROOT, "parts", "instance", "bin", "interpreter")
EGG_LINK_PATH = os.path.join(SENAITE_ROOT, "develop-eggs", "medai.autopublish.egg-link")
SLUGS_DIR = os.path.join(SENAITE_ROOT, "parts", "instance", "etc", "package-includes")


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
    """Add medai.autopublish to Zope interpreter's sys.path."""
    if not os.path.exists(INTERPRETER_PATH):
        print("Interpreter not found at", INTERPRETER_PATH, "- skipping.")
        return True  # not fatal

    with open(INTERPRETER_PATH, 'r') as f:
        content = f.read()

    if "medai.autopublish" in content:
        print("Interpreter already has medai.autopublish. Skipping.")
        return True

    insert_line = "  '{}',\n".format(SRC_PATH)
    old = "sys.path[0:0] = [\n"
    new = old + insert_line
    content = content.replace(old, new, 1)

    with open(INTERPRETER_PATH, 'w') as f:
        f.write(content)

    print("Interpreter updated with medai.autopublish path.")
    return True


def create_egg_link():
    """Create egg-link for medai.autopublish."""
    if os.path.exists(EGG_LINK_PATH):
        print("Egg-link already exists.")
        return True
    try:
        pkg_dir = os.path.dirname(_package_dir())
        # Ensure parent directory exists
        ensure_dir(os.path.dirname(EGG_LINK_PATH))
        with open(EGG_LINK_PATH, 'w') as f:
            f.write(pkg_dir + "\n")
        print("Egg-link created at", pkg_dir)
        return True
    except Exception as e:
        print("ERROR creating egg-link:", e)
        return True  # not fatal for container startup


def remove_zcml_slugs():
    """Remove stale ZCML slugs."""
    for fname in ("100-medai.autopublish-configure.zcml",
                  "100-medai.autopublish-overrides.zcml"):
        fpath = os.path.join(SLUGS_DIR, fname)
        if os.path.exists(fpath):
            os.remove(fpath)
            print("Removed stale ZCML slug:", fname)


def create_zcml_slugs():
    """Create ZCML slugs so QuickInstaller can discover the addon."""
    ensure_dir(SLUGS_DIR)

    config_file = os.path.join(SLUGS_DIR, "100-medai.autopublish-configure.zcml")
    if not os.path.exists(config_file):
        with open(config_file, "w") as f:
            f.write('<configure xmlns="http://namespaces.zope.org/zope">\n')
            f.write('  <include package="medai.autopublish" />\n')
            f.write('</configure>\n')
        print("ZCML configure slug created.")

    overrides_file = os.path.join(SLUGS_DIR, "100-medai.autopublish-overrides.zcml")
    if not os.path.exists(overrides_file):
        with open(overrides_file, "w") as f:
            f.write('<configure xmlns="http://namespaces.zope.org/zope">\n')
            f.write('  <include package="medai.autopublish" file="overrides.zcml" />\n')
            f.write('</configure>\n')
        print("ZCML overrides slug created.")
    return True


if __name__ == "__main__":
    print("=== Setting up medai.autopublish ===")
    remove_zcml_slugs()
    fix_interpreter()
    create_egg_link()
    create_zcml_slugs()
    print("All setup steps completed.")
    # Never exit non-zero - entrypoint uses set -e
