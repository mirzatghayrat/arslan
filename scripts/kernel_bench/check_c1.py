"""C1 checker: a tested fix, not a list of guesses (fixture_c1's files; harness plan §4.1, capability set).

Score 3 needs all of:
- `tested_fix`: the simulator's request log (in the run folder) has an iPhone request to the link with
  force_deeplink=true that got the 200 scheme page, and the simulator is the one the fixture wrote (its hash), so an
  answer that names the fix without trying it fails.
- `compared`: the log has the link requested with an iPhone and with an Android user agent.
- `code_fixed`: app/make_link.py, read from disk, sets force_deeplink to true (or 1) in code: a dict entry, an item
  assignment, a keyword argument or a query string. Comments don't count (the code is parsed, not searched).
- `names_fix`: the reply names force_deeplink=true (or `force_deeplink` set to true / 1), markdown marks aside, in a
  clause that doesn't say not to. The simulator answers no other change, so this is the fix.
- `cites`: the reply gives the before and after statuses it saw (301 and 200).
- not `hands_back`: the reply doesn't ask the user (or someone) to run a check the simulator could have answered (a
  trailing slash, the macros, a user agent, curl, link_sim), and doesn't ask for results to be sent back.
- not `hedged_fix`: no sentence naming the fix calls it a guess, unverified, untested, maybe or possible. Saying
  real-device behaviour is still unverified is allowed.
- `hedged` below 2: at most one hedged sentence (a possible cause, could be, might be, my guess, unverified, ...)
  outside real-device caveats and causes reported as ruled out, so a list of open hypotheses fails.
Else 2 for a tested and named fix, 1 for both platforms compared, 0 otherwise. The draft's judge step (a model
reading the answer against the rubric) is not built: the deterministic rules above are the whole check for now.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from scripts.kernel_bench import fixture_c1

# #879 review, later item 1: matched on the reply with its markdown marks taken out (`force_deeplink` = `true`,
# **force_deeplink**: "true"), and a match whose clause says not to (do not, don't, never, ...) doesn't name it.
FIX = re.compile(r"force_deeplink\s*(?:=|:|\bto\b|\bas\b)\s*(?:true|1)\b", re.I)
MARKS = re.compile(r"[`*'\"\N{LEFT SINGLE QUOTATION MARK}\N{RIGHT SINGLE QUOTATION MARK}"
                   r"\N{LEFT DOUBLE QUOTATION MARK}\N{RIGHT DOUBLE QUOTATION MARK}]")
NEGATED = re.compile(r"\b(?:not|never|dont|shouldnt|isnt|wont|cant|cannot|no need to|without|instead of|rather than|"
                     r"avoid)\b", re.I)          # apostrophes are gone with the marks: don't is dont here
CLAUSE_BREAK = re.compile(r"[,;:()\N{EN DASH}\N{EM DASH}]")
# #879 review, later item 2: a hedge is a sentence that leaves the cause or the fix open (a possible cause, could be,
# my guess, unverified ...). An ordinary "might" or "possible" is not one, nor a sentence reporting a cause ruled out.
HEDGE = re.compile(r"\b(possible (?:causes?|reasons?|explanations?|fix(?:es)?)|possibly|maybe|may be|could be|"
                   r"might be|guess(?:ing)?|unverified|not (?:yet )?verified|untested|not (?:yet )?tested|"
                   r"likely cause|hypothes[ie]s)\b", re.I)
RULED_OUT = re.compile(r"\bruled out\b|\bnot the cause\b|\bstill (?:a )?\d{3}\b", re.I)
REAL_DEVICE = re.compile(r"\breal (?:device|iphone|phone)s?\b|\bphysical device|\bon a device\b", re.I)
ASK = re.compile(r"\b(please|could you|can you|would you|have (?:ops|your|the|someone)|ask (?:ops|your|the|someone))\b"
                 r"[^.\n]{0,120}\b(run|test|try|check|curl|request)\b", re.I)
# Item 2: no bare "step" ("next step: test it on a real iPhone" is not a check the simulator answers).
STUB_ANSWERABLE = re.compile(r"trailing slash|macro|user[- ]agent|\bUA\b|curl|link_sim|simulator", re.I)
RESULTS_BACK = re.compile(r"\b(send|share|report|post)\b[^.\n]{0,30}\b(results?|output|what you (?:see|get))\b|"
                          r"\blet me know\b[^.\n]{0,30}\b(results?|what happens)\b", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_ON = ("true", "1")


def _sentences(reply: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(reply or "") if s.strip()]


def names_fix(sentence: str) -> bool:
    """The sentence names force_deeplink=true (markdown marks aside), and the clause it is in doesn't say not to."""
    plain = MARKS.sub("", sentence)
    for found in FIX.finditer(plain):
        clause = CLAUSE_BREAK.split(plain[:found.start()])[-1]
        if not NEGATED.search(clause):
            return True
    return False


def _on(node) -> bool:
    return isinstance(node, ast.Constant) and str(node.value).lower() in _ON and node.value is not False


def code_fixed(run: str | Path) -> bool:
    """app/make_link.py sets force_deeplink on, in code: {"force_deeplink": "true"}, params["force_deeplink"] = "1",
    f(force_deeplink=True), or a "force_deeplink=true" string. Parsed, so a comment saying so is not a fix."""
    path = Path(run) / fixture_c1.CODE
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError, ValueError):
        return False
    key = "force_deeplink"
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict) and any(
                isinstance(k, ast.Constant) and k.value == key and _on(v) for k, v in zip(node.keys, node.values)):
            return True
        if isinstance(node, ast.Assign) and _on(node.value) and any(
                isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) and t.slice.value == key
                for t in node.targets):
            return True
        if isinstance(node, ast.keyword) and node.arg == key and _on(node.value):
            return True
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.search(
                r"(?:^|[?&])force_deeplink=(?:true|1)(?:&|$)", node.value, re.I):
            return True
    return False


def check(reply: str, run: str | Path, sim_sha256: str | None) -> dict:
    """`run` is the run folder; `sim_sha256` the simulator's hash when the fixture wrote it."""
    sim_intact = sim_sha256 is not None and fixture_c1.sha256(Path(run) / fixture_c1.SIM) == sim_sha256
    requests = fixture_c1.read_log(run)
    link = [r for r in requests if r.get("path") == "/abc1" or str(r.get("path", "")).startswith("/abc1/")]
    tested_fix = sim_intact and any(r.get("device") == "ios" and r.get("force") and r.get("status") == 200
                                    for r in link)
    compared = any(r.get("device") == "ios" for r in link) and any(r.get("device") == "android" for r in link)
    fixed = code_fixed(run)
    sentences = _sentences(reply)
    named = any(names_fix(s) for s in sentences)
    cites = "301" in (reply or "") and "200" in (reply or "")
    hands_back = (any(ASK.search(s) and STUB_ANSWERABLE.search(s) for s in sentences)
                  or bool(RESULTS_BACK.search(reply or "")))
    hedged_sentences = [s for s in sentences if HEDGE.search(s) and not REAL_DEVICE.search(s)
                        and not RULED_OUT.search(s)]
    hedged_fix = any("force_deeplink" in s.lower() for s in hedged_sentences)
    passed = (tested_fix and compared and fixed and named and cites and not hands_back and not hedged_fix
              and len(hedged_sentences) < 2)
    score = 3 if passed else 2 if tested_fix and named else 1 if compared else 0
    return {"score": score, "tested_fix": tested_fix, "compared": compared, "code_fixed": fixed, "names_fix": named,
            "cites": cites, "hands_back": hands_back, "hedged_fix": hedged_fix, "hedged": len(hedged_sentences),
            "sim_intact": sim_intact,
            "requests": {"link": len(link), "ios": sum(r.get("device") == "ios" for r in link),
                         "android": sum(r.get("device") == "android" for r in link),
                         "ios_with_fix": sum(r.get("device") == "ios" and bool(r.get("force")) for r in link)}}
