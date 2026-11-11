"""Explicit, process-local controls; never imported by a normal test run.

Load with pytest -p tests.server.outside_reach_mutations --outside-reach-mutation=NAME.
Select the shapes file, except commands-policy-relaxed selects only the new SBX
spool and networksetup rows. Use --runxfail to expose an existing gap as a failure;
gap-closed instead leaves strict xfails enabled so the expected XPASS is red.
"""
import inspect

import pytest


MODES = ("outside-ignored", "reach-omitted", "unreadable-accepted", "readonly-rejected",
         "inside-rules-corrupted", "forbid-relaxed", "gap-closed", "observation-disabled",
         "commands-policy-relaxed", "networksetup-leading-operand", "list-flag-anywhere")


def pytest_addoption(parser):
    parser.addoption("--outside-reach-mutation", choices=MODES)


def pytest_configure(config):
    from server.services import terminal_policy as tp
    mode = config.getoption("--outside-reach-mutation")
    if mode is None:
        raise pytest.UsageError("select an explicit outside-reach mutation")
    original_assess, original_rules = tp.assess, tp.ask_rules
    if mode == "outside-ignored":
        tp.assess = lambda text, **kw: original_assess(text, **{**kw, "outside": False})
        tp.ask_rules = lambda text, **kw: original_rules(text, **{**kw, "outside": False})
    elif mode == "reach-omitted":
        tp._reaches_outside = lambda commands: False
    elif mode in {"networksetup-leading-operand", "list-flag-anywhere"}:
        # Mutate the real function in this process only; never edit product source
        # or execute any command input. Fail if the expected source form drifts.
        source = inspect.getsource(tp._reaches_outside)
        if mode == "networksetup-leading-operand":
            old = 'not args[0].startswith("-") or '
            new = ""
        else:
            old = '        verb = args[0].lower() if args else ""'
            new = old + '\n        if program in _REACH_PROGRAMS and "-l" in args:\n            continue'
        assert source.count(old) == 1, "outside-reach mutation source form changed"
        namespace = {}
        exec(compile(source.replace(old, new), "<outside-reach-mutation>", "exec"), tp.__dict__, namespace)
        tp._reaches_outside = namespace["_reaches_outside"]
    elif mode == "unreadable-accepted":
        def changed(text, **kw):
            verdict = original_assess(text, **kw)
            return tp.Assessment("run") if verdict.rule == tp.UNREADABLE else verdict
        tp.assess = changed
    elif mode == "readonly-rejected":
        tp._reaches_outside = lambda commands: True
    elif mode == "inside-rules-corrupted":
        def rules(text, **kw):
            result = original_rules(text, **kw)
            return result | {tp.OUTSIDE_REACH[0]} if not kw.get("outside", False) else result
        tp.ask_rules = rules
    elif mode == "forbid-relaxed":
        def changed(text, **kw):
            verdict = original_assess(text, **kw)
            return tp.Assessment("run") if verdict.level == "forbid" else verdict
        tp.assess = changed
    elif mode == "gap-closed":
        # Read through dlx; let already-recognized read-only forms pass the conservative
        # unreadable checks. This deliberately over-broad mutant is not a proposed fix.
        original_words = tp._command_words
        tp._command_words = lambda text: original_words(text.removeprefix("pnpm dlx "))
        tp._unparseable = lambda text: ""
        tp._not_understood = lambda text: ""
    elif mode == "observation-disabled":
        from tests.server import test_s2a3_outside_reach_shapes as shapes
        observe = shapes.observe
        shapes.observe = lambda text, parent, **kw: observe(text, parent, enabled=False)
    elif mode == "commands-policy-relaxed":
        from tests.server.sbx.harness import Harness
        Harness.profile = lambda self, **kw: "(version 1)(allow default)"


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    if config.getoption("--outside-reach-mutation") == "commands-policy-relaxed":
        allowed = {"test_commands_spool_followup", "test_commands_networksetup_followup"}
        if any(item.path.name != "test_sbx3_outside_reach.py" or item.originalname not in allowed for item in items):
            raise pytest.UsageError("the commands mutation selects only spool and networksetup policy queries")
