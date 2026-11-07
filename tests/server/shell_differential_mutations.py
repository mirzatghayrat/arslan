"""Opt-in, process-local negative controls; no product source file is edited.

Usage with HOME pinned to a disposable directory:
python -m pytest tests/server/test_shell_grammar_differential.py -k shell_invocations \
-p tests.server.shell_differential_mutations --shell-differential-mutation=D-OMIT-ACCEPT
For an H-* control, select test_observation_is_contained_and_real instead.
Every selected case must fail. Normal test runs never load this plugin.
"""
import os
import signal

import pytest


MODES = ("D-OMIT-ACCEPT", "H-WRITE", "H-READ", "H-EXEC", "H-NET", "H-KILL", "H-SCRIPT-INPUT")


def pytest_addoption(parser):
    parser.addoption("--shell-differential-mutation", choices=MODES)


def pytest_configure(config):
    from tests.server import shell_differential_support as support
    from tests.server import test_shell_grammar_differential as gates
    from server.services import shell_grammar
    mode = config.getoption("--shell-differential-mutation")
    if mode is None:
        raise pytest.UsageError("choose --shell-differential-mutation when loading this plugin")
    if mode == 'D-OMIT-ACCEPT':
        seed = next(s for s in support.SEEDS if s.text == 'git status')
        gates.SEEDS = (seed,)
        targets = {support.variant(f, seed.text) for f in support.FAMILIES}
        original = shell_grammar.read
        def changed(text):
            if text in targets:
                return shell_grammar.Reading(understood=True, commands=())
            return original(text)
        shell_grammar.read = changed
    elif mode in {'H-WRITE', 'H-EXEC', 'H-NET', 'H-READ'}:
        original = support.ShellRun.__init__
        def changed(self, *args, **kwargs):
            original(self, *args, **kwargs)
            if mode == 'H-WRITE':
                self.profile += f'(allow file-write* {support.subpath(self.root.parent)})\n'
            if mode == 'H-READ':
                self.profile += f'(allow file-read* {support.subpath(self.root.parent)})\n'
            if mode == 'H-EXEC':
                self.profile += '(allow process-exec (literal "/usr/bin/touch"))\n'
            if mode == 'H-NET':
                self.profile += '(allow network-outbound (remote tcp "localhost:*"))\n'
        support.ShellRun.__init__ = changed
    elif mode == 'H-SCRIPT-INPUT':
        support.STUB_NAMES += sorted(support.SCRIPT_INPUTS)
    elif mode == 'H-KILL':
        original = os.killpg
        groups = []
        def parent_only(pid, sig):
            groups.append(pid)
            os.kill(pid, sig)
        os.killpg = parent_only
        config._s2a_cleanup = (original, groups)
        import tempfile
        previous_exit = tempfile.TemporaryDirectory.__exit__
        def cleanup_first(self, *args):
            for group in groups:
                try:
                    original(group, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            return previous_exit(self, *args)
        tempfile.TemporaryDirectory.__exit__ = cleanup_first


def pytest_runtest_teardown(item):
    if cleanup := getattr(item.config, '_s2a_cleanup', None):
        original, groups = cleanup
        os.killpg = original
        for group in groups:
            try:
                original(group, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    mode = config.getoption("--shell-differential-mutation")
    function = ("test_shell_invocations_are_in_the_reading" if mode == "D-OMIT-ACCEPT"
                else "test_observation_is_contained_and_real")
    if any(item.path.name != "test_shell_grammar_differential.py" or item.originalname != function
           for item in items):
        raise pytest.UsageError("select only the differential control named in the plugin usage")
