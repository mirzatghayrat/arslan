"""Text-only policy contracts for forbidden commands across reader limits.

No generated text is executed. The matrix varies one rule-derived command,
one padding mechanism, one boundary and one enclosing position at a time.
The existing shell-text suite owns spelling/separator variants; these cases
pin the policy verdict in enclosing constructs and at both sides of each edge.
"""
import json
import shlex

import pytest

from server.services import shell_text
from server.services import terminal_policy as tp

# Canonical operands taken from the five forbid rule definitions. The plain
# controls below establish both the family and the exact rule before padding.
COMMANDS = {
    **{f"wipe-{name}": " ".join(("rm", "-rf", target))
       for name, target in (("home", "~"), ("root", "/"))},
    "shutdown": "shutdown -h now",
    "sudo": "sudo true",
    "raw-disk": "dd if=sample of=/dev/disk2",
}
# Fixed boundary values, independent of the product constants: changing a
# product limit must not silently regenerate the test's expected boundary.
LIMITS = {"nested": 6, "backticks": 32, "blanks": 64,
          "newlines": 16, "all-substitutions": 256, "ifs": 64}
BOUNDARIES = ("below", "edge", "past")
POSITIONS = ("top", "shell-argument", "launcher-argument", "subshell", "group",
             "then", "do", "quoted-substitution")
XFAIL_REASON = "forbid lost past a reader limit; fixed by the reader-stall follow-up"
# Only independently measured base failures belong here; no verdict is used to
# choose a marker at collection time.
_MEASURED_LIMITS = ("nested", "backticks", "blanks", "newlines", "all-substitutions", "ifs")
_MEASURED_RULES = ("wipe-home", "wipe-root", "shutdown", "raw-disk")
_ENCLOSED = ("shell-argument", "launcher-argument", "subshell", "group", "then", "do", "quoted-substitution")
GAPS = frozenset(
    f"{rule}/{limit}/{boundary}/{position}"
    for rule in _MEASURED_RULES for limit in _MEASURED_LIMITS
    for boundary in ("edge", "past") for position in _ENCLOSED
) | frozenset(
    f"{rule}/newlines/below/{position}"
    for rule in _MEASURED_RULES for position in _ENCLOSED if position != "shell-argument"
) | frozenset(
    f"sudo/{limit}/{boundary}/{position}"
    for limit in _MEASURED_LIMITS for boundary in ("edge", "past")
    for position in ("group", "then", "do")
) | frozenset(f"sudo/newlines/below/{position}" for position in ("group", "then", "do"))


def amount(limit, boundary):
    # Backtick pairs keep all three texts balanced: 30, 32, 34 characters.
    step = 2 if limit == "backticks" else 1
    return LIMITS[limit] + {"below": -step, "edge": 0, "past": step}[boundary]


def padding(limit, n):
    if limit == "nested":
        return "echo " + "$(" * n + ":" + ")" * n
    if limit == "backticks":
        return "echo " + "``" * (n // 2)
    if limit == "blanks":
        return "echo" + " " * n + "pad"
    if limit == "newlines":
        return ":" + "\n" * n + ":"
    if limit == "all-substitutions":
        return "echo " + "$(:)" * n
    if limit == "ifs":
        return "echo" + "${IFS}" * n + "pad"
    raise ValueError(limit)


def shaped(command, limit, boundary, position):
    n = amount(limit, boundary)
    # The enclosing substitution itself contributes one opener and one total.
    if position == "quoted-substitution" and limit in {"nested", "all-substitutions"}:
        n -= 1
    prefix = padding(limit, n) + "; "
    body = prefix + command
    return {
        "top": lambda: body,
        "shell-argument": lambda: "bash -c " + shlex.quote(body),
        "launcher-argument": lambda: "watch " + shlex.quote(body),
        "subshell": lambda: prefix + "(" + command + ")",
        "group": lambda: prefix + "{ " + command + "; }",
        "then": lambda: prefix + "if true; then " + command + "; fi",
        "do": lambda: prefix + "for item in once; do " + command + "; done",
        "quoted-substitution": lambda: 'echo "$(' + body + ')"',
    }[position]()


def key(rule, limit, boundary, position):
    return "/".join((rule, limit, boundary, position))


def cases():
    for rule in COMMANDS:
        for limit in LIMITS:
            for boundary in BOUNDARIES:
                for position in POSITIONS:
                    case_id = key(rule, limit, boundary, position)
                    yield pytest.param(rule, limit, boundary, position, id=case_id,
                        marks=pytest.mark.xfail(strict=True, raises=AssertionError, reason=XFAIL_REASON)
                        if case_id in GAPS else ())


@pytest.mark.parametrize("rule", COMMANDS)
def test_plain_family_names_its_forbid(rule):
    verdict = tp.assess(COMMANDS[rule])
    assert (verdict.level, verdict.rule) == ("forbid", rule)
    assert verdict.reason


@pytest.mark.parametrize("rule,limit,boundary,position", tuple(cases()))
def test_forbid_survives_limit_and_position(rule, limit, boundary, position, record_property):
    text = shaped(COMMANDS[rule], limit, boundary, position)
    # A too-long refusal is not evidence that the family's own rule survived.
    if len(text) > tp.MAX_COMMAND_CHARS:
        pytest.fail("generator exceeded the policy text budget")
    verdict = tp.assess(text)
    record_property("case_id", key(rule, limit, boundary, position))
    record_property("actual", json.dumps([verdict.level, verdict.rule]))
    assert (verdict.level, verdict.rule) == ("forbid", rule)


@pytest.mark.parametrize("limit", LIMITS)
@pytest.mark.parametrize("boundary", BOUNDARIES)
@pytest.mark.parametrize("position", POSITIONS)
def test_harmless_in_the_same_shape_is_not_forbidden(limit, boundary, position):
    assert tp.assess(shaped("echo safe", limit, boundary, position)).level != "forbid"


@pytest.mark.parametrize("limit", LIMITS)
@pytest.mark.parametrize("boundary", BOUNDARIES)
def test_limit_edge_uses_fixed_inputs(limit, boundary, record_property):
    text = padding(limit, amount(limit, boundary))
    verdict = tp.assess(text)
    record_property("policy_at_edge", json.dumps([verdict.level, verdict.rule]))
    # This is the raw/normalized reader boundary. Synthesized command-start
    # newlines can make a policy form cross it sooner; no run verdict is assumed.
    assert shell_text.too_complex(text) is (boundary != "below")
    assert verdict.level != "forbid"


@pytest.mark.parametrize("limit", LIMITS)
@pytest.mark.parametrize("boundary", BOUNDARIES)
@pytest.mark.parametrize("quote", ("'", '"'), ids=("single", "double"))
def test_quoted_separator_remains_data(limit, boundary, quote):
    # Use a command-position rule: sudo's existing semicolon
    # matching is deliberately broader and is not the quoted-data control.
    data = "marker; " + COMMANDS["wipe-home"]
    text = padding(limit, amount(limit, boundary)) + "; echo " + quote + data + quote
    assert tp.assess(text).level != "forbid"
