# -*- coding: utf-8 -*-
from setuptools import setup, find_packages

version = "1.0.1"

long_description = (
    open("README.rst").read() + "\n" +
    open("CHANGES.rst").read()
)

setup(
    name="senaite.smartsearch",
    version=version,
    description="智慧搜索 —— 在权限范围内一键搜索全部 SENAITE LIMS 数据",
    long_description=long_description,
    long_description_content_type="text/x-rst",
    classifiers=[
        "Framework :: Plone",
        "Framework :: Zope2",
        "Programming Language :: Python",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3",
    ],
    keywords="senaite lims search 智慧搜索 maitux",
    author="Ningbo MaiTuX Technology Co., Ltd.",
    author_email="dev@maitux.com",
    url="https://www.maitux.com",
    license="GPLv2",
    packages=find_packages("src", exclude=["ez_setup"]),
    namespace_packages=["senaite"],
    package_dir={"": "src"},
    include_package_data=True,
    zip_safe=False,
    install_requires=[
        "setuptools",
        "senaite.core",
    ],
    entry_points="""
    [z3c.autoinclude.plugin]
    target = plone
    """,
)
