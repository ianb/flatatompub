from setuptools import setup, find_packages
import sys, os

version = '0.1'

setup(name='FlatAtomPub',
      version=version,
      description="Simple implementation of AtomPub (aka Atom Publishing Protocol)",
      long_description="""\
""",
      classifiers=[], # Get strings from http://pypi.python.org/pypi?%3Aaction=list_classifiers
      keywords='atom atompub app wsgi web',
      author='Ian Bicking',
      author_email='ianb@colorstudy.com',
      url='',
      license='MIT',
      packages=find_packages(exclude=['ez_setup', 'examples', 'tests']),
      include_package_data=True,
      zip_safe=False,
      install_requires=[
        'WebOb',
        'WebTest',
        'decorator',
        'dtopt',
        'uuid',
        'TaggerClient',
      ],
      dependency_links=[
        'http://svn.pythonpaste.org/Paste/WebOb/trunk#egg=WebOb-dev',
        'http://svn.pythonpaste.org/Paste/WebTest/trunk#egg=WebTest-dev',
        'http://zesty.ca/python/uuid.py#egg=uuid-dev',
        'https://svn.openplans.org/svn/TaggerClient/trunk#egg=TaggerClient-dev',
      ],
      entry_points="""
      [paste.app_factory]
      main = flatatompub.wsgiapp:make_app

      [flatatompub.index_factory]
      simple = flatatompub.naiveindex:make_index
      """,
      )
