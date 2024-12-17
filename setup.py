#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""imports"""
import sys
from pathlib import Path

from setuptools import find_packages, setup

# make sure to keep python version in numerical order
SUPPORTED_PYTHON_VERSIONS = ["3.9", "3.10", "3.11", "3.12", "3.13"]
CLASSIFIERS = [
    "Operating System :: OS Independent",
] + [
    "Programming Language :: Python :: " + version
    for version in SUPPORTED_PYTHON_VERSIONS
]
CWD = Path(__file__).resolve().parent

if (
    f"{sys.version_info.major}.{sys.version_info.minor}"
    not in SUPPORTED_PYTHON_VERSIONS
):
    raise RuntimeError(
        f"Unsupported version of Python detected: {sys.version_info.major}.{sys.version_info.minor}\n"
        f"reCBZ2 requires Python {', '.join(SUPPORTED_PYTHON_VERSIONS)}."
    )

__version__ = (CWD / "reCBZ2" / "__init__.py").read_text(encoding="utf-8").split('"')[1]


def _strip(file_name: str) -> str:
    """
    Strip text from a file

    :param str file_name: path to the filename to strip
    :return: stripped text from the provided file
    :rtype: str
    """
    return (CWD / file_name).read_text(encoding="utf-8").strip()


setup(
    name="reCBZ2",
    version=__version__,
    author="avalonv",
    license="GPL-3.0",
    description="Utility for repacking and optimizing manga & comic book archives",
    long_description="README.md",
    long_description_content_type="text/markdown",
    url="https://github.com/BelardoA/reCBZ2",
    packages=find_packages(),
    include_package_data=True,
    setup_requires=["setuptools>=61.0.0", "rich==12.6.0"],
    install_requires=_strip("requirements.txt").split(),
    python_requires=f">={SUPPORTED_PYTHON_VERSIONS[0]}, <{str(int(SUPPORTED_PYTHON_VERSIONS[-1].split('.')[0]) + 1)}",
    classifiers=CLASSIFIERS,
    entry_points={
        "console_scripts": [
            "reCBZ = reCBZ2.__main__:main",
        ],
    },
)
