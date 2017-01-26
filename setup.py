#!/usr/bin/env python
from setuptools import setup

requires = ['boto', 'simplejson']

setup(
    name='tiopatinhas',
    version='1.0.3',
    author='Chaordic Systems',
    description='An Amazon Autoscaling companion that uses the Spot Market',
    license='Open Source',
    install_requires=requires,
    packages=['tp'],
    package_data={'tp': ['tp.conf.template']},
    long_description=open('README.md').read(),
    data_files=[('', ['LICENSE']), ('', ['CHANGELOG.md'])],
    zip_safe=False,
    url='https://www.github.com/chaordic/tiopatinhas/',
    scripts=['tp/tp.py']
)
