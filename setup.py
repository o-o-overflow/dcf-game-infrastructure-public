import os
import subprocess


from setuptools import setup
from setuptools import find_packages
packages = find_packages()

# XXX: also see the dockerfile
setup(
      name='ooogame',
      python_requires='>3.8',
      version='0.02',
      packages=packages,
      install_requires=[
          'requests',
          'flask',
          'flask-restful',
          'nose',
          'python-dateutil',
          'sqlalchemy',
          'Flask-SQLAlchemy',
          'Flask-Migrate',
          'pyyaml',
          'coverage',
          'dpkt',
          'pyfakefs',
          'docker',
          'redis',
          'fakeredis',
          'Flask-RQ2',
          'kubernetes',
          'coloredlogs',
      ],
      extras_require={
          "mysql": ["mysqlclient"]
      },
      dependency_links=[
      ],
)
