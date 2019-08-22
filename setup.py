#!/usr/bin/env python3

"""A setuptools based setup module.

See:
https://packaging.python.org/guides/distributing-packages-using-setuptools/
"""

import os.path

from setuptools import setup, find_packages


def read_file(file_name: str) -> str:
    """Read file that is placed in the same directory as this `setup.py`
    module.

    :param file_name: File name, should not be a path.
    :return: File content as string.
    """
    project_root = os.path.abspath(os.path.dirname(__file__))
    file_path = os.path.join(project_root, file_name)

    with open(file_path) as file:
        return file.read()


setup(
    name="geni",
    version="0.1.0.dev3",
    description=("Gentoo installer - bootstraps chroot and executes commands "
                 "in chroot "),
    long_description=read_file("README.md"),
    long_description_content_type='text/markdown',
    author="aidecoe",
    author_email="aidecoe@aidecoe.name",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: System Administrators",
        "Topic :: System :: Installation/Setup",
        "License :: OSI Approved :: GNU General Public License v3 or later "\
        "(GPLv3+)",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
    ],
    keywords="gentoo installer chroot",
    packages=find_packages(),
    python_requires=">=3.6, <4",
    install_requires=[
        "arrow",
        "plumbum",
        "portalocker",
        "requests",
    ],
    extras_require={
        "dev": ["mypy",
                "pylint"],
    },
    entry_points={
        "console_scripts": [
            "geni = geni:Geni.run",
        ],
    },
    include_package_data=True,
    project_urls={
        "Bug Reports": "https://github.com/aidecoe/geni/issues",
        "Source": "https://github.com/aidecoe/geni",
    },
)
