import os
from setuptools import find_packages, setup


setup(
    name='localtest.samplefield',
    version="1.0.0",
    description="为 本地测试 生成的 Senaite Addon",
    long_description=open("README.rst").read() if os.path.exists("README.rst") else "",
    author="Maitux Team",
    author_email="dev@maitux.com",
    url='https://github.com/maitux/localtest.samplefield',
    packages=find_packages("src"),
    package_dir={"": "src"},
    namespace_packages=['localtest'],
    include_package_data=True,
    zip_safe=False,
    install_requires=["setuptools"],
    entry_points="""
    [z3c.autoinclude.plugin]
    target = plone
    """,
)
