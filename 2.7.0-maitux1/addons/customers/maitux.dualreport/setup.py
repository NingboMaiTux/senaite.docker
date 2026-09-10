# -*- coding: utf-8 -*-
from setuptools import setup, find_packages

setup(
    name='maitux.dualreport',
    version='1.0.0',
    description="Dual PDF/Word report output for senaite.impress (MaituxLIMS)",
    long_description=(
        "Allows publishing/saving Analysis Request reports either as PDF "
        "(unchanged WeasyPrint pipeline) or as an editable Word (.docx) "
        "document generated from the very same rendered report HTML, so the "
        "Word layout stays as close as possible to the PDF output."
    ),
    packages=find_packages("src"),
    package_dir={"": "src"},
    namespace_packages=['maitux'],
    include_package_data=True,
    zip_safe=False,
    install_requires=[
        'setuptools',
        'senaite.core',
        'senaite.impress',
    ],
    entry_points="""
    [z3c.autoinclude.plugin]
    target = plone
    """,
)
