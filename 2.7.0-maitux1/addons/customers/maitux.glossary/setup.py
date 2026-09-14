# -*- coding: utf-8 -*-
from setuptools import setup, find_packages

setup(
    name='maitux.glossary',
    version='1.0.0',
    description="Inspection item keyword zh/en glossary (MaituxLIMS)",
    long_description=(
        "Maintains the Chinese/English glossary for inspection item keywords, "
        "keyed by (Analysis Keyword, calculation interim keyword). The middle "
        "table is kept in sync with the site on every visit of its listing "
        "view: rows are only appended, combinations that disappear from the "
        "site are marked inactive, and combinations that reappear become "
        "active again."
    ),
    packages=find_packages("src"),
    package_dir={"": "src"},
    namespace_packages=['maitux'],
    include_package_data=True,
    zip_safe=False,
    install_requires=[
        'setuptools',
        'senaite.core',
    ],
    entry_points="""
    [z3c.autoinclude.plugin]
    target = plone
    """,
)
