#!/usr/bin/env python
from setuptools import setup

requires = ['boto']

setup(
    name='tiopatinhas',
    version='1.0.0',
    author='Chaordic Systems',
    description='An Amazon Autoscaling companion that uses the Spot Market',
    license='Open Source',
    install_requires=requires,
    packages=['tp'],
    package_data={'tp': ['tp.conf']},
    long_description=open('README.md').read(),
    zip_safe=False,
    url='https://www.github.com/chaordic/tiopatinhas/',
    scripts=['tp/tp.py']
)