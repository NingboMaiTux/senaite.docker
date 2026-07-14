# -*- coding: utf-8 -*-

from setuptools import find_packages, setup

setup(
    name="medai.autopublish",
    version="0.1.0",
    description="Auto-publish + report_drafting workflow extension for Senaite samples",
    packages=find_packages("src"),
    package_dir={"": "src"},
    namespace_packages=["medai"],
    include_package_data=True,
    package_data={
        "medai.autopublish": [
            "*.zcml",
            "profiles/default/*.xml",
            "profiles/default/*.txt",
            "profiles/default/types/*.xml",
            "profiles/default/workflows/*/definition.xml",
            "profiles/uninstall/*.xml",
            "profiles/uninstall/*.txt",
            "profiles/uninstall/types/*.xml",
        ],
    },
    zip_safe=False,
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
