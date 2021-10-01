#!/usr/bin/env python
import os
import codecs
from setuptools import setup


def read(fname):
    file_path = os.path.join(os.path.dirname(__file__), fname)
    return codecs.open(file_path, encoding="utf-8").read()


setup(
    name="pytest-requests",
    version="0.4.0",
    author="Mario Cesar Senoranis Ayala",
    author_email="mariocesar@humanzilla.com",
    maintainer="Mario Cesar Senoranis Ayala",
    maintainer_email="mariocesar@humanzilla.com",
    license="MIT",
    url="https://github.com/mariocesar/pytest-requests",
    description="A simple plugin to use with pytest",
    long_description=read("README.rst"),
    py_modules=["pytest_python_requests"],
    python_requires=">=3.6",
    install_requires=["pytest>=3.5.0", "pyyaml", "pydash", "trafaret>=2.0.0", "requests"],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Framework :: Pytest",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Testing",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python :: Implementation :: PyPy",
        "Operating System :: OS Independent",
        "License :: OSI Approved :: MIT License",
    ],
    entry_points={"pytest11": ["requests = pytest_python_requests"]},
)
