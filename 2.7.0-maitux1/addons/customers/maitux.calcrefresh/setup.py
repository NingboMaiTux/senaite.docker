# -*- coding: utf-8 -*-
from setuptools import setup, find_packages

version = "1.0.0"

setup(
    name="maitux.calcrefresh",
    version=version,
    description="SENAITE Worksheet calculation snapshot refresh and interim export",
    author="MAITUX",
    author_email="dev@maitux.com",
    license="GPLv2",
    packages=find_packages("src", exclude=["ez_setup"]),
    package_dir={"": "src"},
    namespace_packages=["maitux"],
    include_package_data=True,
    zip_safe=False,
    install_requires=[
        "setuptools",
        "senaite.core",
    ],
    entry_points="""
    """,
)
