# -*- coding: utf-8 -*-
from setuptools import setup, find_packages

setup(
    name='maitux.worksheetfields',
    version='1.0.0',
    description="Worksheet multi-select fields (Instruments & Stock Batches) "
                "for SENAITE",
    long_description=open("README.md").read(),
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
