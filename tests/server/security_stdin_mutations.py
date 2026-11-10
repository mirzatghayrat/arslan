"""Opt-in, process-local negative controls for the stdin/transport regression file."""
import inspect

import pytest

MODES = ("IGNORE-I", "ALLOW-STDIN", "SKIP-FLOOR", "IGNORE-OUTSIDE", "DROP-RAW-TRANSPORT", "REFUSE-ARGV")


def pytest_addoption(parser):
    parser.addoption("--security-stdin-mutation", choices=MODES)


def pytest_configure(config):
    from server.services import shell_grammar as sg, shell_text as st, terminal_policy as tp
    mode = config.getoption("--security-stdin-mutation")
    if mode is None:
        raise pytest.UsageError("choose --security-stdin-mutation when loading this plugin")
    patch = pytest.MonkeyPatch()
    config.add_cleanup(patch.undo)
    if mode == "IGNORE-I":
        source = inspect.getsource(sg.security_operation)
        assert source.count("interactive = True") == 1
        namespace = {}
        exec(compile(source.replace("interactive = True", "interactive = False"), "<IGNORE-I>", "exec"), namespace)
        patch.setattr(sg, "security_operation", namespace["security_operation"])
    elif mode == "ALLOW-STDIN":
        original = sg.security_operation
        patch.setattr(sg, "security_operation", lambda args: (original(args)[0], False))
    elif mode == "REFUSE-ARGV":
        original = sg.security_operation
        patch.setattr(sg, "security_operation", lambda args: (original(args)[0], True))
    elif mode == "SKIP-FLOOR":
        patch.setattr(tp, "_forbid", lambda text, texts: None)
    elif mode == "IGNORE-OUTSIDE":
        original = tp.assess
        patch.setattr(tp, "assess", lambda text, *, cwd=None, outside=False: original(text, cwd=cwd))
    else:
        source = inspect.getsource(st._command_detection_variants)
        line = "    yield from _payload_variants(command, fresh)\n"
        assert source.count(line) == 1
        namespace = dict(vars(st))
        exec(compile(source.replace(line, ""), "<DROP-RAW-TRANSPORT>", "exec"), namespace)
        patch.setattr(st, "_command_detection_variants", namespace["_command_detection_variants"])
    for module in (sg, st, tp):
        for value in vars(module).values():
            clear = getattr(value, "cache_clear", None)
            if clear:
                clear()
