"""Opt-in process-local mutations; no product file is edited and no shell text runs.

Load with -p tests.server.quoted_args_file_run_mutations and choose
--quoted-file-mutation. Select only this change's text-only regression file.
ALLOW-PROGRAM-PATHS selects every_program_path; ALLOW-FILE-SCRIPTS selects
interpreter_file_families; DROP-NAMED-COMMANDS selects named_rules_read.
"""
import inspect
import textwrap

import pytest

MODES = ("ALLOW-PROGRAM-PATHS", "ALLOW-FILE-SCRIPTS", "DROP-NAMED-COMMANDS",
         "FLATTEN-OPERANDS", "DROP-REFUSED-PREFIX", "REFUSE-NON-SCRIPT-SUBCOMMANDS")


def pytest_addoption(parser):
    parser.addoption("--quoted-file-mutation", choices=MODES)


def pytest_configure(config):
    from server.services import shell_grammar as sg, terminal_policy as tp
    mode = config.getoption("--quoted-file-mutation")
    if mode is None:
        raise pytest.UsageError("choose --quoted-file-mutation when loading this plugin")
    if mode == "DROP-NAMED-COMMANDS":
        tp._command_words = lambda text: ()
    elif mode == "DROP-REFUSED-PREFIX":
        tp._command_words = lambda text: sg.read(text).commands
    elif mode == "REFUSE-NON-SCRIPT-SUBCOMMANDS":
        sg._NON_SCRIPT_SUBCOMMANDS = {}
    elif mode == "FLATTEN-OPERANDS":
        def flattened(words):
            command = " ".join(words)
            found = {key for key, pattern, _, masked in tp._FORBID_C
                     if not masked and key != "arslan-keys" and pattern.match(command)}
            found.update(key for key, pattern, _ in tp._ASK_C if pattern.match(command))
            if ((tp._DELETE_LINE.match(command) or tp._FIND_DELETE.match(command))
                    and tp._deletes_outside((command,))):
                found.add("delete-outside")
            return found
        tp._named_rules = flattened
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
        "FLATTEN-OPERANDS": "test_same_program_operands_keep_their_roles",
        "DROP-REFUSED-PREFIX": "test_quoted_rules_hold_before_every_refused_tail",
        "REFUSE-NON-SCRIPT-SUBCOMMANDS": "test_non_script_subcommands_stay_understood",
    }[config.getoption("--quoted-file-mutation")]
    if any(item.path.name != "test_quoted_args_file_run.py" or item.originalname != expected for item in items):
        raise pytest.UsageError("select only the mutation's named text-only family")
