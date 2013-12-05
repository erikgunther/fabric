"""
This will add a rest interface to fabric so that you can access your commands
from a webpage with eg handelbars.

The reson for this is to enable users to do a nicer and give more overview of
the functionallaty of the local fabric script.
"""
import sys
import inspect
import subprocess
import random
import time
import threading
import Queue
import uuid
from cStringIO import StringIO



from fabric.thread_handling import ThreadHandler
from fabric.io import output_loop, input_loop
from fabric.network import disconnect_all, ssh
from fabric.task_utils import crawl
from fabric.api import execute, env, abort, puts
from fabric.main import load_fabfile, find_fabfile, get_task_names
from fabric.main import parse_options, get_docstring,  _escape_split, env_options
import fabric.state as state
from flask import Flask, jsonify


FABRIC_REST = Flask(__name__)
FABRIC_REST.config['DEBUG'] = True
FABRIC_JOBS = {}



class AsynchronousFileReader(threading.Thread):
    '''
    Helper class to implement asynchronous reading of a file
    in a separate thread. Pushes read lines on a queue to
    be consumed in another thread.
    '''

    def __init__(self, fd, queue):
        assert isinstance(queue, Queue.Queue)
        assert callable(fd.readline)
        threading.Thread.__init__(self)
        self._fd = fd
        self._queue = queue

    def run(self):
        '''The body of the tread: read lines and put them on the queue.'''
        for line in iter(self._fd.readline, ''):
            self._queue.put(line)

    def eof(self):
        '''Check whether there is no more content to expect.'''
        return not self.is_alive() and self._queue.empty()


@FABRIC_REST.route('/')
def hello_world():
    return 'Hello World!'


@FABRIC_REST.route('/list')
def list():
    """
    Return a json-doc with all available tasks and documentation that
    can be executed.

    This will return a map where the key is the task to execute.

    Each task has 2 keywords:

    * docstring - to display the documentation
    * details - that give information about arguments to the task

    The details have 4 attributs:

    * args - list of all arguments.
    * detaults - list of all default values, note if this list is shorter than
    args. All default arguments come last in the argument list as normal in
    Python.
    * keywords - N/A
    * varargs - N/A

    """


    task_list = {}
    for task_name in get_task_names():
        command = crawl(task_name, state.commands)
        argspec = inspect.getargspec(command.wrapped)

        task_list[task_name] = {
            'docstring': get_docstring(task_name),
            'details' : argspec}
    return jsonify(task_list )


@FABRIC_REST.route('/task/<task>', methods=['POST', 'GET'])
def task(task):
    '''
    This will start the execution of an task. It will return a uuid that
    one later can check the status of the run.

    Its also possible to send the password for sudo and ssh commands but
    keep in mind the security problem of sending password over HTTP.
    If you send it use ?password=<password>

    '''

    global FABRIC_JOBS
    jobid = str(uuid.uuid1())
    jobid = '25';
    FABRIC_JOBS[jobid] = {}
    command = ['fab', '--abort-on-prompts']

    from flask import request
    password = request.args.get('password', '')
    if password:
        #Add password if added
        command.append('-p')
        command.append(password)

    command.append(task)

    FABRIC_JOBS[jobid]['command'] = command

    # Launch the command as subprocess.
    print "Will execute: {command}".format(command = command)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    FABRIC_JOBS[jobid]['process'] = process

    # Launch the asynchronous readers of the process' stdout and stderr.
    stdout_queue = Queue.Queue()
    stdout_reader = AsynchronousFileReader(process.stdout, stdout_queue)
    stdout_reader.start()
    FABRIC_JOBS[jobid]['stdout_reader'] = stdout_reader
    FABRIC_JOBS[jobid]['stdout_queue'] = stdout_queue

    stderr_queue = Queue.Queue()
    stderr_reader = AsynchronousFileReader(process.stderr, stderr_queue)
    stderr_reader.start()
    FABRIC_JOBS[jobid]['stderr_reader'] = stderr_reader
    FABRIC_JOBS[jobid]['stderr_queue'] = stderr_queue

    return jobid


@FABRIC_REST.route('/status/<jobid>')
def status(jobid):
    """
    Return status of current running process.

    It will give you the output:

    * done - Boolean if the task is done executing.
    * stdout - All output to stdout from the previous call to /status
    * stderr - Same as stdout but for stderr.

    If the task is done this will also close all filehandles for the job.

    """

    output = {
        'stdout':'',
        'stderr':'',
        'done': False}

    if jobid in FABRIC_JOBS:
        # Check the queues if we received some output (until there is nothing more to get).
        if not FABRIC_JOBS[jobid]['stdout_reader'].eof() or \
           not FABRIC_JOBS[jobid]['stderr_reader'].eof():
            # Show what we received from standard output.
            while not FABRIC_JOBS[jobid]['stdout_queue'].empty():
                line = FABRIC_JOBS[jobid]['stdout_queue'].get()
                output['stdout'] += line

            # Show what we received from standard error.
            while not FABRIC_JOBS[jobid]['stderr_queue'].empty():
                line = FABRIC_JOBS[jobid]['stderr_queue'].get()
                output['stderr'] += line
        else:
            # Let's be tidy and join the threads we've started.
            FABRIC_JOBS[jobid]['stdout_reader'].join()
            FABRIC_JOBS[jobid]['stderr_reader'].join()

            # Close subprocess' file descriptors.
            FABRIC_JOBS[jobid]['process'].stdout.close()
            FABRIC_JOBS[jobid]['process'].stderr.close()
            del FABRIC_JOBS[jobid]
            output['done'] = True

    else:
        output['done'] = True
    return jsonify(output)

def run_server():
    """
    This will init and start the fab rest server.
    """

    # Parse command line options
    _, options, _ = parse_options()

    # Allow setting of arbitrary env keys.
    # This comes *before* the "specific" env_options so that those may
    # override these ones. Specific should override generic, if somebody
    # was silly enough to specify the same key in both places.
    # E.g. "fab --set shell=foo --shell=bar" should have env.shell set to
    # 'bar', not 'foo'.
    for pair in _escape_split(',', options.env_settings):
        pair = _escape_split('=', pair)
        # "--set x" => set env.x to True
        # "--set x=" => set env.x to ""
        key = pair[0]
        value = True
        if len(pair) == 2:
            value = pair[1]
        state.env[key] = value

    # Update env with any overridden option values
    # NOTE: This needs to remain the first thing that occurs
    # post-parsing, since so many things hinge on the values in env.
    for option in env_options:
        state.env[option.dest] = getattr(options, option.dest)

    # Handle version number option
    if options.show_version:
        print("Fabric %s" % state.env.version)
        print("Paramiko %s" % ssh.__version__)
        sys.exit(0)

    # Find local fabfile path or abort
    fabfile = find_fabfile()
    if not fabfile:
        return "No fabfile specified"

    # Store absolute path to fabfile in case anyone needs it
    state.env.real_fabfile = fabfile

    # Load fabfile (which calls its module-level code, including
    # tweaks to env values) and put its commands in the shared commands
    # dict
    if fabfile:
        _, callables, _ = load_fabfile(fabfile)
        state.commands.update(callables)


    #print task('dummy')
    #Finally start the server
    FABRIC_REST.run()

