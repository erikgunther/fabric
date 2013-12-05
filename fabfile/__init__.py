"""
Fabric's own fabfile.
"""

from __future__ import with_statement

import nose

from fabric.api import abort, local, task, sudo, env

import docs
import tag
import time
from utils import msg

env.hosts = ['localhost','127.0.0.1']

@task
def dummy():

    from fabric.api import run, puts
    puts("Start")
    local("echo '1 Dummy done!'")
    run("echo '2 Dummy done!'")
    time.sleep(4)
    sudo("echo '3 Dummy done!'")
    local("echo '4 Dummy done!'")


@task
def dummy_all():

    from fabric.api import execute, hide
    execute(dummy)



@task(default=True)
def test(args=None):
    """
    Run all unit tests and doctests.

    Specify string argument ``args`` for additional args to ``nosetests``.
    """
    default_args = "-sv --with-doctest --nologcapture --with-color"
    default_args += (" " + args) if args else ""
    nose.core.run_exit(argv=[''] + default_args.split())


@task
def upload():
    """
    Build, register and upload to PyPI
    """
    with msg("Uploading to PyPI"):
        local('python setup.py sdist register upload')


@task
def release(force='no'):
    """
    Tag, push tag to Github, & upload new version to PyPI.
    """
    tag.tag(force=force, push='yes')
    upload()
