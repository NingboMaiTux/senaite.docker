# -*- coding: utf-8 -*-
from setuptools import setup, find_packages

setup(
    name='maitux.stock',
    version='1.0.0',
    description="Stock Management for MAITUX",
    packages=find_packages("src"),
    package_dir={"": "src"},
    namespace_packages=['maitux'],
    include_package_data=True,
    zip_safe=False,
    install_requires=[
        'setuptools',
        'senaite.core',
        # 领用双人复核复用 maitux.esignature 的认证与签名留痕服务
        'maitux.esignature',
    ],
    entry_points="""
    [z3c.autoinclude.plugin]
    target = plone
    """,
)
