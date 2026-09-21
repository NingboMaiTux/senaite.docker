from setuptools import find_packages
from setuptools import setup

setup(
    name="maitux.elnlink",
    version="1.0.0",
    description="MaiELN link: source experiment on samples, deep links, approved-result push, demo seed",
    long_description="",
    author="Maitux Team",
    author_email="dev@maitux.com",
    url="https://example.invalid/maitux.elnlink",
    packages=find_packages("src"),
    package_dir={"": "src"},
    namespace_packages=["maitux"],
    include_package_data=True,
    zip_safe=False,
    install_requires=[
        "setuptools",
        "senaite.core",
        "archetypes.schemaextender",
        "plone.api",
        "zope.interface",
    ],
)
