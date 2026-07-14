# -*- coding: utf-8 -*-

from setuptools import find_packages, setup

setup(
    name="medai.dashboard",
    version="0.1.0",
    description="Dashboard enhancements for Analyst role in Senaite",
    packages=find_packages("src"),
    package_dir={"": "src"},
    namespace_packages=["medai"],
    include_package_data=True,
    zip_safe=False,
    package_data={
        "medai.dashboard": [
            "*.zcml",
            "profiles/default/*.xml",
            "profiles/uninstall/*.xml",
            "browser/static/js/*.js",
            "locales/*/LC_MESSAGES/*.po",
        ],
    },
    install_requires=[
        "setuptools",
        "senaite.core",
        "senaite.lims",
    ],
    entry_points="""
    [z3c.autoinclude.plugin]
    target = plone
    """,
)
