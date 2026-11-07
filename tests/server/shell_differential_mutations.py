"""Opt-in, process-local negative controls; no product source file is edited.

Usage with HOME pinned to a disposable directory:
python -m pytest tests/server/test_shell_grammar_differential.py -k shell_invocations \
-p tests.server.shell_differential_mutations --shell-differential-mutation=D-OMIT-ACCEPT
The original H-* controls select test_observation_is_contained_and_real.
D-FILE-OMIT selects file_family and path; D-FILE-FIX selects file_family and
script (each strict XPASS must fail). H-FILE-* select file_observation_control;
D-PIPE-OMIT/H-PIPE-STUB select plain_pipeline; H-PATH-WITHHOLD selects
path_arguments (H-WRAPPER-PATH/SUFFIX also select it). Every selected case
must fail. No normal run loads this plugin.
"""
import os
import signal

import pytest


MODES = ("D-OMIT-ACCEPT", "H-WRITE", "H-READ", "H-EXEC", "H-NET", "H-KILL", "H-SCRIPT-INPUT",
         "D-FILE-OMIT", "D-FILE-FIX", "H-FILE-OBSERVATION", "H-FILE-SETUP",
         "D-PIPE-OMIT", "H-PIPE-STUB", "H-PATH-WITHHOLD", "H-WRAPPER-PATH", "H-WRAPPER-SUFFIX")


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
    elif mode in {"D-FILE-OMIT", "D-FILE-FIX", "D-PIPE-OMIT"}:
        original = shell_grammar.read
        def changed(text):
            reading = original(text)
            if mode == "D-FILE-FIX":
                return shell_grammar.Reading(understood=False, why="mutation: named scripts refused")
            if reading.understood:
                return shell_grammar.Reading(understood=True, commands=())
            return reading
        shell_grammar.read = changed
    elif mode == "H-FILE-OBSERVATION":
        original = support.ShellRun.run
        def changed(self, *args, **kwargs):
            names, expired, code = original(self, *args, **kwargs)
            return set(), expired, code
        support.ShellRun.run = changed
    elif mode == "H-FILE-SETUP":
        original = gates.file_variant
        def changed(family, seed, run):
            text = original(family, seed, run)
            for path in (run.root / "tools", run.root / "links" / seed.text.split()[0],
                         run.root / "case.sh", run.root / "child" / "case.sh"):
                path.unlink(missing_ok=True)
            # The writer itself is the setup for this family.
            return text.split("; ", 1)[-1] if family == "written-script" else text
        gates.file_variant = changed
    elif mode == "H-PIPE-STUB":
        support.WRAPPERS.pop("cat")
    elif mode == "H-WRAPPER-SUFFIX":
        gates.withheld = lambda text: "unlogged-wrapper-path" if text.endswith(".sh") else support.withheld(text)
    elif mode == "H-WRAPPER-PATH":
        gates.withheld = lambda text: ""
    elif mode == "H-PATH-WITHHOLD":
        gates.withheld = lambda text: "path" if "/" in text or "~" in text else support.withheld(text)
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
    selections = {
        "D-OMIT-ACCEPT": "test_shell_invocations_are_in_the_reading",
        "D-FILE-OMIT": "test_file_family", "D-FILE-FIX": "test_file_family",
        "H-FILE-OBSERVATION": "test_file_observation_control",
        "H-FILE-SETUP": "test_file_observation_control",
        "D-PIPE-OMIT": "test_plain_pipeline_is_compared",
        "H-PIPE-STUB": "test_plain_pipeline_is_compared",
        "H-PATH-WITHHOLD": "test_path_arguments_are_not_blanket_withheld",
        "H-WRAPPER-PATH": "test_path_arguments_are_not_blanket_withheld",
        "H-WRAPPER-SUFFIX": "test_path_arguments_are_not_blanket_withheld",
    }
    function = selections.get(mode, "test_observation_is_contained_and_real")
    if any(item.path.name != "test_shell_grammar_differential.py" or item.originalname != function
           for item in items):
        raise pytest.UsageError("select only the differential control named in the plugin usage")
