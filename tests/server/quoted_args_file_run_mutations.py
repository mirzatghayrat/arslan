"""Opt-in process-local mutations; no product file is edited and no shell text runs.

Load with -p tests.server.quoted_args_file_run_mutations and choose
--quoted-file-mutation. Select only this change's text-only regression file.
ALLOW-PROGRAM-PATHS selects every_program_path; ALLOW-FILE-SCRIPTS selects
interpreter_file_families; DROP-NAMED-COMMANDS selects named_rules_read.
"""
import inspect
import textwrap

import pytest

MODES = ("ALLOW-PROGRAM-PATHS", "ALLOW-FILE-SCRIPTS", "DROP-NAMED-COMMANDS")


def pytest_addoption(parser):
    parser.addoption("--quoted-file-mutation", choices=MODES)


def pytest_configure(config):
    from server.services import shell_grammar as sg, terminal_policy as tp
    mode = config.getoption("--quoted-file-mutation")
    if mode is None:
        raise pytest.UsageError("choose --quoted-file-mutation when loading this plugin")
    if mode == "DROP-NAMED-COMMANDS":
        tp._command_texts = lambda text: ()
    elif mode == "ALLOW-PROGRAM-PATHS":
        source = textwrap.dedent(inspect.getsource(sg._Reader._started))
        source = source.replace('if "/" in name:', 'if False:', 1)
        namespace = {}
        exec(compile(source, "<ALLOW-PROGRAM-PATHS>", "exec"), vars(sg), namespace)
        sg._Reader._started = namespace["_started"]
    else:
        original = sg._Reader._program
        def program(self, base, args):
            if sg._INTERPRETER.fullmatch(base) and sg._names_something(args) and args[0].text != "eval":
                return
            return original(self, base, args)
        sg._Reader._program = program


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    expected = {
        "ALLOW-PROGRAM-PATHS": "test_every_program_path_is_unread",
        "ALLOW-FILE-SCRIPTS": "test_interpreter_file_families_are_unread",
        "DROP-NAMED-COMMANDS": "test_named_rules_read_quoted_words",
    }[config.getoption("--quoted-file-mutation")]
    if any(item.path.name != "test_quoted_args_file_run.py" or item.originalname != expected for item in items):
        raise pytest.UsageError("select only the mutation's named text-only family")
