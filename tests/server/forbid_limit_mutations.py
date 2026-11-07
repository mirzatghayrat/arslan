"""Opt-in text-only mutations. No command text is executed; no product source is edited.

With HOME pinned, run python -m pytest tests/server/test_forbid_past_limits.py
-p tests.server.forbid_limit_mutations --forbid-mutation MODE.
DROP-FORBID selects plain_family or forbid_survives. RESTORE-FORBID selects
forbid_survives (the cases measured failing at b3e718c6, all passing since
#766's follow-up, must still pass). FORBID-ALL
selects harmless_in_the_same_shape. SPLIT-QUOTED-DATA selects quoted_separator.
RAISE-LIMIT/LOWER-LIMIT select limit_edge with --forbid-limit LIMIT.
The restore is a synthetic verdict oracle, not a proposed product fix.
"""
import pytest


MODES = ("DROP-FORBID", "RESTORE-FORBID", "FORBID-ALL", "SPLIT-QUOTED-DATA",
         "RAISE-LIMIT", "LOWER-LIMIT")
CONSTANTS = {"nested": "_MAX_NESTED_SUBSTITUTIONS", "backticks": "_MAX_BACKTICKS",
             "blanks": "_MAX_BLANK_RUN", "newlines": "_MAX_NEWLINES_IN_BLANK_RUN",
             "all-substitutions": "_MAX_DETECTION_SUBSTITUTIONS", "ifs": "_MAX_BLANK_RUN"}


def pytest_addoption(parser):
    parser.addoption("--forbid-mutation", choices=MODES)
    parser.addoption("--forbid-limit", choices=tuple(CONSTANTS))


def pytest_configure(config):
    from server.services import shell_text, terminal_policy as tp
    from tests.server import test_forbid_past_limits as gates
    mode = config.getoption("--forbid-mutation")
    if mode is None:
        raise pytest.UsageError("choose --forbid-mutation when loading the plugin")
    if mode == "DROP-FORBID":
        tp._forbid = lambda text, texts: None
    elif mode == "RESTORE-FORBID":
        targets = {}
        for case_id in gates.GAPS:
            rule, limit, boundary, position = case_id.split("/")
            targets[gates.shaped(gates.COMMANDS[rule], limit, boundary, position)] = rule
        original = tp._forbid
        def restored(text, texts):
            if text in targets:
                return tp.Assessment("forbid", targets[text], "mutation: restored family verdict")
            return original(text, texts)
        tp._forbid = restored
    elif mode == "FORBID-ALL":
        tp._forbid = lambda text, texts: tp.Assessment("forbid", "mutation", "all text refused")
    elif mode == "SPLIT-QUOTED-DATA":
        original = tp.assess
        tp.assess = lambda text: original(text.replace("'", "").replace('"', ""))
    else:
        limit = config.getoption("--forbid-limit")
        if limit is None:
            raise pytest.UsageError("a limit mutation needs --forbid-limit")
        constant = CONSTANTS[limit]
        step = 2 if limit == "backticks" and mode == "LOWER-LIMIT" else 1
        delta = step if mode == "RAISE-LIMIT" else -step
        setattr(shell_text, constant, getattr(shell_text, constant) + delta)
        for value in vars(shell_text).values():
            if hasattr(value, "cache_clear"):
                value.cache_clear()


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    mode = config.getoption("--forbid-mutation")
    functions = {
        "DROP-FORBID": {"test_plain_family_names_its_forbid", "test_forbid_survives_limit_and_position"},
        "RESTORE-FORBID": {"test_forbid_survives_limit_and_position"},
        "FORBID-ALL": {"test_harmless_in_the_same_shape_is_not_forbidden"},
        "SPLIT-QUOTED-DATA": {"test_quoted_separator_remains_data"},
        "RAISE-LIMIT": {"test_limit_edge_uses_fixed_inputs"},
        "LOWER-LIMIT": {"test_limit_edge_uses_fixed_inputs"},
    }
    if any(item.path.name != "test_forbid_past_limits.py" or item.originalname not in functions[mode]
           for item in items):
        raise pytest.UsageError("select only the text-only control named in the plugin usage")
    if mode in {"RAISE-LIMIT", "LOWER-LIMIT"}:
        limit = config.getoption("--forbid-limit")
        deselected = [item for item in items if item.callspec.params["limit"] != limit]
        items[:] = [item for item in items if item.callspec.params["limit"] == limit]
        config.hook.pytest_deselected(items=deselected)
