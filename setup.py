#!/usr/bin/python3
# SPDX-License-Identifier: MIT

from setuptools import setup

setup(
    name="delegation-demo",
    version="0.1",
    description="Demo application showcasing cgroup delegation on RHEL/CentOS 7 and later",
    url="https://github.com/msekletar/delegation-demo",
    maintainer="Michal Sekletár",
    maintainer_email="sekletar.m@gmail.com",
    license="MIT",
    python_requires=">=3.6",
    scripts = ["bin/demo.py"],
    install_requires=[
        'psutil',
        'dbus-python',
        ""
    ]
)
