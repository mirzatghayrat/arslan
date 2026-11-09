"""Opt-in, process-local folder controls; product files are never patched.

Load with -p tests.server.folder_tracking_mutations and --folder-mutation=NAME.
Run the folder tests with --tb=no for failure counts. The five R2 controls each
have a named parametrized witness; FOLD controls exercise the structural cases.
The eight BASE controls reconstruct the original behavior categories: the earlier
mutation definitions were not retained in the repository or review attachment.
"""
import functools
import inspect
import textwrap
import types

import pytest


MODES = (
    "R2-SUBSTITUTION-WORK", "R2-SHELL-WORK", "R2-IGNORE-READ-WRITE",
    "R2-RELATIVE-HOME", "R2-LAST-FOLDER", "FOLD-NONE", "FOLD-DROP-LEADING",
    "BASE-DROP-MOVES", "BASE-DROP-FAILED", "BASE-OR-EXACT", "BASE-PIPE-LEAK",
    "BASE-SUBSHELL-LEAK", "BASE-BACKGROUND-LEAK", "BASE-DROP-WRITES", "BASE-DROP-POLICY",
)


def pytest_addoption(parser):
    parser.addoption("--folder-mutation", choices=MODES)


def _replace(patch, owner, name, old, new, *, count=1):
    original = getattr(owner, name)
    original = getattr(original, "__wrapped__", original)
    source = textwrap.dedent(inspect.getsource(original))
    assert source.count(old) == count, (name, old)
    namespace = dict(original.__globals__)
    exec(compile(source.replace(old, new), original.__code__.co_filename, "exec"), namespace)
    changed = namespace[name]
    body = getattr(changed, "__wrapped__", changed)
    # Keep the live globals: each test installs stand-in rules after plugin configuration.
    replacement = types.FunctionType(body.__code__, original.__globals__, name, body.__defaults__, body.__closure__)
    replacement.__kwdefaults__ = body.__kwdefaults__
    if hasattr(changed, "__wrapped__"):
        replacement = functools.lru_cache(maxsize=64)(replacement)
    patch.setattr(owner, name, replacement)


def pytest_configure(config):
    from server.services import shell_grammar as sg, terminal_policy as tp

    mode = config.getoption("--folder-mutation")
    if mode is None:
        raise pytest.UsageError("choose --folder-mutation when loading this plugin")
    patch = pytest.MonkeyPatch()
    config.add_cleanup(patch.undo)
    reader = sg._Reader
    if mode == "R2-SUBSTITUTION-WORK":
        _replace(patch, reader, "_dollar", "in_substitution=True, here=self.here", "in_substitution=True")
    elif mode == "R2-SHELL-WORK":
        _replace(patch, reader, "_program", ", here=self.here", "")
    elif mode == "R2-IGNORE-READ-WRITE":
        _replace(patch, reader, "_redirection", 'op != "<"', 'op not in ("<", "<>")')
    elif mode == "R2-RELATIVE-HOME":
        _replace(patch, reader, "_change_folder", 'value.startswith(("/", "~"))', 'value.startswith("/")')
    elif mode == "R2-LAST-FOLDER":
        _replace(patch, tp, "_after_moves", "for f in moved for w in operands", "for f in moved[-1:] for w in operands")
    elif mode == "FOLD-NONE":
        patch.setattr(sg, "_logical_folder", lambda folder: folder)
    elif mode == "FOLD-DROP-LEADING":
        def drops_leading(folder):
            # A faulty fold treats home as a path component and discards outside parents.
            folded = sg.posixpath.normpath(folder)
            while folded == ".." or folded.startswith("../"):
                folded = folded[3:]
            return "" if folded == "." else folded

        patch.setattr(sg, "_logical_folder", drops_leading)
    elif mode == "BASE-DROP-MOVES":
        patch.setattr(reader, "_change_folder", lambda *args: None)
    elif mode == "BASE-DROP-FAILED":
        _replace(patch, reader, "_change_folder", "self.failed | self.here, moved", "self.failed, moved")
    elif mode == "BASE-OR-EXACT":
        _replace(patch, reader, "_and_or", 'exact = self.take() == ("op", "&&") and exact',
                 'self.take()\n        exact = True')
    elif mode == "BASE-PIPE-LEAK":
        _replace(patch, reader, "_pipeline", "self.here, self.failed = before", "pass", count=2)
    elif mode == "BASE-SUBSHELL-LEAK":
        _replace(patch, reader, "_subshell", "self.here, self.failed = before", "pass")
    elif mode == "BASE-BACKGROUND-LEAK":
        _replace(patch, reader, "list_until", "self.here, self.failed = before", "pass")
    elif mode == "BASE-DROP-WRITES":
        _replace(patch, reader, "_redirection", "self.out.writes.append((word.text, tuple(sorted(self.here))))", "pass")
    elif mode == "BASE-DROP-POLICY":
        _replace(patch, tp, "_after_moves", "return outside, protected", "return False, False")
    tp._after_moves.cache_clear()
    config.add_cleanup(tp._after_moves.cache_clear)
