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
    "R3-NO-LSTAT", "R3-LAST-COMPONENT", "R3-MISSING-SAFE", "R3-ERROR-SAFE", "R3-HOME-CLAMP",
    "R4-NO-VETO", "R4-FIRST-ONLY", "R4-PIPELINE", "R4-SUBSHELL", "R4-SUBSTITUTION",
    "R4-NESTED-SHELL", "R4-BACKGROUND", "R4-BLOCKLIST", "R4-NO-REDIRECTION", "R4-NO-OPTIONS",
    "R4-PROTOTYPE", "R4-NO-ANCHOR", "R4-NUL", "R4-ANCHOR-LAST", "R4-ANCHOR-LATE",
    "BASE-DROP-MOVES", "BASE-DROP-FAILED", "BASE-OR-EXACT", "BASE-PIPE-LEAK",
    "BASE-SUBSHELL-LEAK", "BASE-BACKGROUND-LEAK", "BASE-DROP-WRITES", "BASE-DROP-POLICY",
    "GIT-ALLOWED",
)


def pytest_addoption(parser):
    parser.addoption("--folder-mutation", choices=MODES)


def _replace(patch, owner, name, old, new, *, count=1):
    original = getattr(owner, name)
    original = getattr(original, "__wrapped__", original)
    source = getattr(original, "__mutation_source__", None) or textwrap.dedent(inspect.getsource(original))
    assert source.count(old) == count, (name, old)
    namespace = dict(original.__globals__)
    exec(compile(source.replace(old, new), original.__code__.co_filename, "exec"), namespace)
    changed = namespace[name]
    body = getattr(changed, "__wrapped__", changed)
    # Keep the live globals: each test installs stand-in rules after plugin configuration.
    replacement = types.FunctionType(body.__code__, original.__globals__, name, body.__defaults__, body.__closure__)
    replacement.__kwdefaults__ = body.__kwdefaults__
    replacement.__mutation_source__ = source.replace(old, new)
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
    if mode == "GIT-ALLOWED":
        # Restore exactly the removed status/log/diff proof, process-locally.
        patch.setattr(tp, "_FOLD_GIT_OPTIONS", {
            "status": frozenset({"--short", "--porcelain", "--branch", "-s", "-b", "--untracked-files=no"}),
            "log": frozenset({"--oneline", "--stat", "--name-only", "--no-patch", "--no-ext-diff", "--no-textconv"}),
            "diff": frozenset({"--stat", "--name-only", "--name-status", "--cached", "--staged", "--no-ext-diff", "--no-textconv"}),
        }, raising=False)
        _replace(patch, tp, "_fold_effect_safe", "if name in _FOLD_READ_OPTIONS:",
                 'if name == "git":\n'
                 '        if not args or args[0] not in _FOLD_GIT_OPTIONS:\n'
                 '            return False\n'
                 '        options = _FOLD_GIT_OPTIONS[args.pop(0)]\n'
                 '    elif name in _FOLD_READ_OPTIONS:')
    elif mode == "R4-NO-VETO":
        patch.setattr(tp, "_fold_effects_allow", lambda *args: True)
    elif mode == "R4-FIRST-ONLY":
        patch.setattr(tp, "_fold_effects_allow", lambda reading, point: tp._fold_effect_safe(reading.effects[0]))
    elif mode == "R4-PIPELINE":
        _replace(patch, reader, "_pipeline", "for start, end in segments:",
                 'for start, end in segments[:-1]:\n        self.out.effects[start:end] = [("true",)] * (end - start)\n    for start, end in segments:')
    elif mode in ("R4-SUBSHELL", "R4-SUBSTITUTION", "R4-NESTED-SHELL"):
        method = {"R4-SUBSHELL": "_subshell", "R4-SUBSTITUTION": "_dollar", "R4-NESTED-SHELL": "_program"}[mode]
        original = getattr(reader, method)
        def hidden(self, *args):
            if mode == "R4-NESTED-SHELL" and args[0] not in ("bash", "sh"):
                return original(self, *args)
            start = len(self.out.effects) - (mode == "R4-NESTED-SHELL")
            result = original(self, *args)
            self.out.effects[start:] = [("true",)] * (len(self.out.effects) - start)
            return result
        patch.setattr(reader, method, hidden)
    elif mode == "R4-BACKGROUND":
        _replace(patch, reader, "list_until", "self.here, self.failed = before",
                 'self.out.effects[effect_start:] = [("true",)] * (len(self.out.effects) - effect_start)\n                self.here, self.failed = before')
    elif mode == "R4-BLOCKLIST":
        original = tp._fold_effect_safe
        patch.setattr(tp, "_fold_effect_safe", lambda words: original(words) or bool(words and words[0].startswith("zz-")))
    elif mode == "R4-NO-REDIRECTION":
        _replace(patch, reader, "_redirection", "self.out.effects.append(None)", 'self.out.effects.append(("true",))')
    elif mode == "R4-NO-OPTIONS":
        _replace(patch, tp, "_fold_effect_safe", "operands = False", "return True\n    operands = False")
    elif mode == "R4-PROTOTYPE":
        patch.setattr(tp, "_fold_effect_safe", lambda words: bool(words and words[0] in tp._FOLD_BUILTINS))
        original = tp._fold_effects_allow
        patch.setattr(tp, "_fold_effects_allow", lambda reading, point: not reading.writes and original(reading, point))
    elif mode == "R4-NO-ANCHOR":
        patch.setattr(tp, "_valid_fold_anchor", lambda cwd: cwd)
    elif mode == "R4-NUL":
        _replace(patch, tp, "_valid_fold_anchor", ' or "\\0" in path', '')
        _replace(patch, tp, "_valid_fold_anchor", "OSError, ValueError, TypeError", "OSError, TypeError")
    elif mode == "R4-ANCHOR-LAST":
        def last_anchor(cwd):
            try:
                return cwd if tp.stat.S_ISDIR(tp.os.lstat(cwd).st_mode) else None
            except (OSError, ValueError, TypeError):
                return None
        patch.setattr(tp, "_valid_fold_anchor", last_anchor)
    elif mode == "R4-ANCHOR-LATE":
        _replace(patch, tp, "_after_moves", "if not anchor_checked:",
                 "_safe_fold_prefix(prefix, cwd, checked)\n        if not anchor_checked:")
    elif mode == "R2-SUBSTITUTION-WORK":
        _replace(patch, reader, "_dollar", "in_substitution=True, here=self.here", "in_substitution=True")
    elif mode == "R2-SHELL-WORK":
        _replace(patch, reader, "_program", ", here=self.here", "")
    elif mode == "R2-IGNORE-READ-WRITE":
        _replace(patch, reader, "_redirection", 'op != "<"', 'op not in ("<", "<>")')
    elif mode == "R2-RELATIVE-HOME":
        _replace(patch, reader, "_change_folder", 'value.startswith(("/", "~"))', 'value.startswith("/")')
    elif mode == "R2-LAST-FOLDER":
        _replace(patch, tp, "_after_moves", "for f in moved for w in operands", "for f in moved[-1:] for w in operands")
    elif mode == "R3-NO-LSTAT":
        patch.setattr(tp, "_safe_fold_prefix", lambda *args: True)
    elif mode == "R3-LAST-COMPONENT":
        _replace(patch, tp, "_safe_fold_prefix", 'if key not in checked:',
                 'if key != prefix:\n            continue\n        if key not in checked:')
    elif mode == "R3-MISSING-SAFE":
        _replace(patch, tp, "_safe_fold_prefix", 'except OSError:',
                 'except FileNotFoundError:\n                checked[key] = True\n            except OSError:')
    elif mode == "R3-ERROR-SAFE":
        _replace(patch, tp, "_safe_fold_prefix", 'except OSError:\n                checked[key] = False',
                 'except OSError:\n                checked[key] = True')
    elif mode == "R3-HOME-CLAMP":
        _replace(patch, sg, "_logical_folder", 'collapsed[2:] if home else collapsed', 'folder[2:] if home else collapsed')
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
