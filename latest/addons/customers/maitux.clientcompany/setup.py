import os
from setuptools import find_packages
from setuptools import setup


setup(
    name="maitux.clientcompany",
    version="0.1.0",
    description="Add Company field to SENAITE clients",
    long_description="",
    author="Maitux Team",
    author_email="dev@maitux.com",
    url="https://example.invalid/maitux.clientcompany",
    packages=find_packages("src"),
    package_dir={"": "src"},
    namespace_packages=["maitux"],
    include_package_data=True,
    zip_safe=False,
    install_requires=[
        "setuptools",
        "senaite.core",
        "senaite.lims",
        "archetypes.schemaextender",
        "zope.interface",
    ],
    entry_points="""
    [z3c.autoinclude.plugin]
    target = plone
    """,
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Web Environment",
        "Framework :: Plone",
        "Framework :: Plone :: 5.2",
        "Framework :: Zope2",
        "Programming Language :: Python",
    ],
)
