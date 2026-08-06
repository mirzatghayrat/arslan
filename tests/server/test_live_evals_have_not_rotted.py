"""The live-LLM evals are skipped everywhere. Keep them from rotting unnoticed.

`test_clarify_eval.py` and `test_escalation_eval.py` are gated on
ARSLAN_LIVE_LLM=1, which nothing sets — not CI, not a dev machine. Measured
2026-08-06: 12 tests skipped on Linux AND on macOS, i.e. they have never run
anywhere. Unlike the macOS suite, that is not a platform gap a new CI job fixes;
they cost real money to run, so they stay opt-in.

What makes opt-in dangerous is silence. An eval nobody executes drifts out of
sync with the code it calls, and the first person to finally set the env var gets
an AttributeError instead of a verdict — by which point the eval has been
decoration for months.

So this pins the CONTRACTS the evals depend on, without calling any model. It is
cheap, it runs on every push, and it fails the moment a rename makes those evals
unrunnable. That is the expiry mechanism: not a date someone has to remember, but
a test that speaks up on the commit that breaks it.

It deliberately does NOT assert eval CORRECTNESS — whether the router still
clarifies vague requests is a question only a real model can answer, and claiming
otherwise here would be the same "green means checked" illusion the skip already
created.
"""
from __future__ import annotations

import ast
import dataclasses
import importlib
import inspect
import pathlib

import pytest

from server.orchestrator import router
from server.orchestrator.escalation import classify

TESTS = pathlib.Path(__file__).parent


def test_the_evals_are_still_gated_the_way_this_file_assumes():
    """⓪ If the gate changed, every assertion below is about the wrong thing."""
    for name in ("test_clarify_eval.py", "test_escalation_eval.py"):
        src = (TESTS / name).read_text()
        assert "ARSLAN_LIVE_LLM" in src, f"{name} no longer gates on ARSLAN_LIVE_LLM"


def test_clarify_eval_can_still_call_what_it_calls():
    """`router.route(conversation_id, user_message)` awaited, returning `.action`."""
    assert inspect.iscoroutinefunction(router.route)
    params = list(inspect.signature(router.route).parameters)
    # The eval calls it positionally: router.route("eval", msg)
    assert params[:2] == ["conversation_id", "user_message"], params

    assert dataclasses.is_dataclass(router.RouterResult)
    fields = {f.name for f in dataclasses.fields(router.RouterResult)}
    assert "action" in fields, f"RouterResult lost `action`; the eval reads it. fields={fields}"


def test_escalation_eval_can_still_call_what_it_calls():
    """`classify(escalation: dict)` awaited, returning a dict with `allowed`."""
    assert inspect.iscoroutinefunction(classify)
    params = list(inspect.signature(classify).parameters)
    assert params == ["escalation"], params

    # The eval reads verdict["allowed"]. The return is an untyped dict, so the
    # key cannot come from the signature — walk the AST for `return {...}` and
    # look at the actual keys.
    #
    # NOT a source grep: the first attempt matched /"allowed":/ in the text and
    # passed off the module DOCSTRING, which says `{"allowed": bool, "why": str}`.
    # Renaming every real return key left it green. A grep that prose can satisfy
    # is not a check.
    tree = ast.parse(pathlib.Path(inspect.getsourcefile(classify)).read_text())
    fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "classify"),
        None,
    )
    assert fn is not None, "classify is no longer a module-level function in escalation.py"
    returned_keys = {
        k.value
        for node in ast.walk(fn)
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)
        for k in node.value.keys
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    }
    assert "allowed" in returned_keys, (
        f"classify no longer RETURNS an `allowed` key; the eval asserts on it. "
        f"returned keys: {sorted(returned_keys)}"
    )


@pytest.mark.parametrize(
    "name,expected_cases",
    [("test_clarify_eval.py", 6), ("test_escalation_eval.py", 6)],
)
def test_the_eval_corpora_did_not_quietly_empty(name: str, expected_cases: int):
    """A parametrised eval with an emptied corpus collects zero tests and looks fine.

    12 skipped is the number that was measured. If a corpus shrinks, the skip
    count drops and nobody notices, because nobody reads a skip count — that is
    the whole lesson of this round.
    """
    # Import the module and read the corpora, rather than counting lines that
    # look like entries. The first attempt counted source lines: `CLEAR = [] if
    # True else [ …items… ]` empties the corpus while every item line is still
    # in the file, and the line count stayed green.
    mod = importlib.import_module(f"tests.server.{name[:-3]}")
    corpora = {
        n: v for n, v in vars(mod).items()
        if n.isupper() and isinstance(v, list)
    }
    assert corpora, f"{name} exposes no upper-case list corpora to count"
    total = sum(len(v) for v in corpora.values())
    assert total >= expected_cases, (
        f"{name} lost eval cases: {total} across {list(corpora)}, "
        f"expected at least {expected_cases}"
    )
