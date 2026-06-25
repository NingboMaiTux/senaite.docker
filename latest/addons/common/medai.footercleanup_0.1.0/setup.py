import os
from setuptools import find_packages, setup


setup(
    name="medai.footercleanup",
    version="0.1.0",
    description="MedAI footer cleanup add-on for SENAITE",
    long_description=open("README.rst").read() if os.path.exists("README.rst") else "",
    author="MedAI Team",
    author_email="dev@medai.com",
    url="https://github.com/medai/medai.footercleanup",
    packages=find_packages("src"),
    package_dir={"": "src"},
    namespace_packages=["medai"],
    include_package_data=True,
    package_data={
        "medai.footercleanup": [
            "*.zcml",
            "browser/*.zcml",
            "browser/templates/*.pt",
            "profiles/default/*.xml",
            "profiles/default/*.txt",
            "profiles/default/*.py",
            "profiles/uninstall/*.xml",
            "profiles/uninstall/*.txt",
        ]
    },
    zip_safe=False,
    install_requires=[
        "setuptools",
        "senaite.core",
        "senaite.lims",
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
        "Intended Audience :: Developers",
        "License :: OSI Approved :: GNU General Public License v2 (GPLv2)",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
)
