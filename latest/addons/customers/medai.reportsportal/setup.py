# -*- coding: utf-8 -*-

from setuptools import find_packages, setup

setup(
    name="medai.reportsportal",
    version="0.1.0",
    description="Global Analysis Reports sidebar entry for Senaite",
    packages=find_packages("src"),
    package_dir={"": "src"},
    namespace_packages=["medai"],
    include_package_data=True,
    package_data={
        "medai.reportsportal": [
            "*.zcml",
            "profiles/default/*.xml",
            "profiles/default/*.txt",
            "profiles/uninstall/*.xml",
            "profiles/uninstall/*.txt",
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
