"""
This will add a rest interface to fabric so that you can access your commands
from a webpage with eg handelbars.

The reson for this is to enable users to do a nicer and give more overview of
the functionallaty of the local fabric script.
"""
import sys
import inspect


from fabric.network import disconnect_all, ssh
from fabric.task_utils import crawl
from fabric.main import load_fabfile, find_fabfile, get_task_names
from fabric.main import parse_options, get_docstring,  _escape_split, env_options
import fabric.state as state
from flask import Flask, jsonify


FABRIC_REST = Flask(__name__)
FABRIC_REST.config['DEBUG'] = True


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


@FABRIC_REST.route('/task/<task>')
def task():
    """
    Execute the given task
    """



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



    #Finally start the server
    FABRIC_REST.run()


