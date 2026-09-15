from setuptools import find_packages
from setuptools import setup

setup(
    name="INNOCARE.labid",
    version="1.0.0",
    description="Lab ID field on the Laboratory (INNOCARE)",
    long_description="",
    author="Maitux Team",
    author_email="dev@maitux.com",
    url="https://example.invalid/INNOCARE.labid",
    packages=find_packages("src"),
    package_dir={"": "src"},
    namespace_packages=["INNOCARE"],
    include_package_data=True,
    zip_safe=False,
    install_requires=[
        "setuptools",
        "senaite.core",
        "plone.behavior",
        "plone.dexterity",
        "plone.supermodel",
        "zope.interface",
    ],
)
