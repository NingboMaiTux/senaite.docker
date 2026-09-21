# -*- coding: utf-8 -*-
from setuptools import setup, find_packages

version = "1.0.0"

setup(
    name="maitux.dynamicfields",
    version=version,
    description="Dynamic field management for SENAITE (Archetypes + Dexterity)",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    classifiers=[
        "Framework :: Plone",
        "Programming Language :: Python :: 2.7",
    ],
    keywords="senaite lims fields dexterity archetypes",
    author="MAITUX",
    url="https://github.com/NingboMaiTux/senaite.docker",
    license="GPLv2",
    packages=find_packages("src", exclude=["ez_setup"]),
    package_dir={"": "src"},
    namespace_packages=["maitux"],
    include_package_data=True,
    zip_safe=False,
    install_requires=[
        "setuptools",
        "senaite.core",
        "archetypes.schemaextender",
    ],
    entry_points="""
    [z3c.autoinclude.plugin]
    target = plone
    """,
)
