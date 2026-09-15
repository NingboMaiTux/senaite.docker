from setuptools import find_packages
from setuptools import setup


setup(
    name="INNOCARE.autoreceive",
    version="1.0.0",
    description="Client based auto reception of samples for INNOCARE",
    packages=find_packages("src"),
    package_dir={"": "src"},
    namespace_packages=["INNOCARE"],
    include_package_data=True,
    zip_safe=False,
    install_requires=[
        "setuptools",
        "senaite.core",
        "archetypes.schemaextender",
        "senaite.app.listing",
    ],
    entry_points="""
    [z3c.autoinclude.plugin]
    target = plone
    """,
)
