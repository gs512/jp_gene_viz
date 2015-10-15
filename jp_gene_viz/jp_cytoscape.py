from __future__ import print_function # For py 2.7 compat

from IPython.display import display, Javascript
import ipywidgets as widgets
from traitlets import Unicode, Float, List, Dict
import json
import os
import pprint
import types

def load_javascript_support(verbose=False):
    """
    Install javascript support required for this module into the notebook.
    """
    my_dir = os.path.dirname(__file__)
    for filename in ["cytoscape.js", "jp_cytoscape.js"]:
        js_filename = os.path.join(my_dir, filename)
        assert os.path.exists(js_filename)
        if verbose:
            print("loading javascript from", repr(js_filename))
        display(Javascript(js_filename))


def validate_commands(commands, top=True):
    """
    Validate command sequence ala send_commands.
    """
    return [validate_command(x, top) for x in commands]


def validate_command(command, top=True):
    """
    Simple sanity checks on commands to the javascript view
    as described in the send_commands docstring.
    """
    if isinstance(command, CommandMaker):
        command = command.cmd()
    if type(command) is types.ListType:
        indicator = command[0]
        remainder = command[1:]
        if indicator == "fun":
            name = remainder[0]
            args = remainder[1:]
            assert type(name) is types.StringType, (
                "function name must be string " + repr(name))
            args = validate_commands(args, top=False)
            remainder = [name] + args
        elif indicator == "method":
            target = remainder[0]
            name = remainder[1]
            args = remainder[2:]
            assert type(name) is types.StringType, (
                "method name must be string " + repr(name))
            target = validate_command(target)
            args = validate_commands(args, top=False)
            remainder = [target, name] + args
        elif indicator == "list":
            remainder = validate_commands(remainder, top=False)
        elif indicator == "dict":
            [d] = remainder
            d = dict((k, validate_command(d[k], top=False)) for k in d)
            remainder = [d]
        elif indicator == "id":
            # Any json value is okay
            assert len(remainder) == 1, (
                "id takes one object only. " + repr(remainder))
        else:
            raise ValueError("bad indicator " + repr(indicator))
        command = [indicator] + remainder
    elif top:
        assert type(command) is types.ListType, (
            "top level command must be list " + repr(command))
    return command

class CytoscapeWidget(widgets.DOMWidget):
    """
    Jupyter notebook widget which presents a Cytoscope.js visualization.
    """

    _view_name = Unicode("CytoScapeView", sync=True)

    # The list of commands for view to execute (see send_commands)
    # form: [counter, commands]
    # counter is used for bookkeeping.
    commands = List([], sync=True)

    # List of results from command execution
    results = List([], sync=True)

    event_data = Dict({}, sync=True)

    width = Unicode("100px", sync=True)

    height = Unicode("100px", sync=True)

    def __init__(self, *pargs, **kwargs):
        super(CytoscapeWidget, self).__init__(*pargs, **kwargs)
        self.commands_count = 0
        self.count_to_results_callback = {}

    def js(self):
        """Return a command maker convenience."""
        return CommandMaker()

    def send(self, command, results_callback=None):
        """
        Send one command using the send_commands protocol.
        """
        return self.send_commands([command], results_callback)

    def send_commands(self, commands_iter, results_callback=None):
        """
        Send a batch sequence of commands as json lists to the javascript view.
        The commands_iter are executed in the cytoscape context $cy using a recursive
        functional mini interpreter I which translates JSON objects to javascript
        actions.

        I(["fun", name, arg0, arg1...]) --> $cy.name(I(arg0), I(arg1)...)
        I(["method", target, name, arg0...]) --> I(target).name(I(arg0)...)
        I(["id", x]) --> x (untranslated json object)
        I(["list", x0, x1, ..]) --> [I(x0), I(x1), ...] (translated sequence)
        I(["dict", {k0: x0, ...}]) --> {k0: I(x0), ...} (translated dict)
        I(not_a_list) --> not_a_list (untranslated value)

        For example to invoke cy.$("#j").addClass("funny") use command
        ["method", ["fun", "$", "#j"], "addClass", "funny"]

        The results of the command sequence are passed from the javascript view
        except that results which are not json compatible are mapped to None.
        If provided results_callback(results) is called for results of a command.

        Functions are found the cytoscape visualization instance, or if they
        are not available there, they are found in the cytoscape namespace.
        For example js.stylesheet(...) will be found in the cytoscape namespace.
        """
        count = self.commands_count
        self.commands_count = count + 1
        commands = validate_commands(list(commands_iter))
        # send commands to view by modifying the commands trait.
        self.commands = [count, commands]

    def fix(self, keep_elements=False):
        """
        Convenience function: make mouse events respond to scrolling properly.
        and optionally delete all elements of the network.
        """
        self.send(self.js().fix())


SPECIAL_NAMES = {"DOLLAR": "$"}

def translate_name(name):
    """
    Translate from special name like DOLLAR to javascript
    name which is not syntactically acceptible in python like $
    """
    return SPECIAL_NAMES.get(name, name)


class CommandMaker(object):

    def __getattr__(self, name):
        return FunctionMaker(name)

    def cmd(self):
        raise ValueError("cmd not defined for " + repr(self))

class FunctionMaker(CommandMaker):

    def __init__(self, name):
        self.name = translate_name(name)

    def __call__(self, *args):
        return CallMaker("fun", self.name, *args)

class CallMaker(CommandMaker):
    def __init__(self, kind, *args):
        self.kind = kind
        self.args = quoteLists(args)
    def cmd(self):
        return [self.kind] + list(self.args)
    def __getattr__(self, name):
        return MethodMaker(self, name)

class MethodMaker(CommandMaker):

    def __init__(self, target, name):
        self.target = target
        self.name = translate_name(name)

    def __call__(self, *args):
        return CallMaker("method", self.target, self.name, *args)

class LiteralListMaker(CommandMaker):
    def __init__(self, L):
        self.L = list(L)
    def cmd(self):
        return ["list"] + self.L

def quoteLists(args):
    result = []
    for x in args:
        if type(x) is types.ListType:
            x = LiteralListMaker(x)
        result.append(x)
    return result

