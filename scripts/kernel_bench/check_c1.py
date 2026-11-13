"""C1 checker: a tested fix, not a list of guesses (fixture_c1's stub; harness plan §4.1, capability set).

Score 3 needs all of:
- `tested_fix`: the stub's own log has an iPhone request to the link with force_deeplink=true that got the 200
  scheme page. Server state, so an answer that names the fix without trying it fails.
- `compared`: the log has the link requested with an iPhone and with an Android user agent.
- `names_fix`: the reply names force_deeplink=true (or `force_deeplink` set to true / 1). The stub answers no other
  change, so this is the fix.
- `cites`: the reply gives the before and after statuses it saw (301 and 200).
- not `hands_back`: the reply doesn't ask the user (or someone) to run a check a request to the stub could have
  answered (a trailing slash, the macros, a user agent, curl), and doesn't ask for results to be sent back.
- not `hedged_fix`: no sentence naming the fix calls it a guess, unverified, untested, maybe or possible. Saying
  real-device behaviour is still unverified is allowed.
- `hedged` below 2: at most one hedged sentence (possible cause, might, could be, my guess, unverified, ...) outside
  real-device caveats, so a list of open hypotheses fails.
Else 2 for a tested and named fix, 1 for both platforms compared, 0 otherwise. The draft's judge step (a model
reading the answer against the rubric) is not built: the deterministic rules above are the whole check for now.
"""
from __future__ import annotations

import re

FIX = re.compile(r"force_deeplink\s*(?:=|:|\bto\b|\bas\b)\s*[`'\"]?(?:true|1)\b", re.I)
HEDGE = re.compile(r"\b(possible|possibly|might|maybe|may be|could be|guess|unverified|not (?:yet )?verified|"
                   r"untested|not (?:yet )?tested|likely cause)\b", re.I)
REAL_DEVICE = re.compile(r"\breal (?:device|iphone|phone)s?\b|\bphysical device|\bon a device\b", re.I)
ASK = re.compile(r"\b(please|could you|can you|would you|have (?:ops|your|the|someone)|ask (?:ops|your|the|someone))\b"
                 r"[^.\n]{0,120}\b(run|test|try|check|curl|request)\b", re.I)
STUB_ANSWERABLE = re.compile(r"trailing slash|macro|user[- ]agent|\bUA\b|curl|step", re.I)
RESULTS_BACK = re.compile(r"\b(send|share|report|post)\b[^.\n]{0,30}\b(results?|output|what you (?:see|get))\b|"
                          r"\blet me know\b[^.\n]{0,30}\b(results?|what happens)\b", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


def _sentences(reply: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(reply or "") if s.strip()]


def check(reply: str, requests: list[dict]) -> dict:
    link = [r for r in requests if r.get("path") == "/abc1" or str(r.get("path", "")).startswith("/abc1/")]
    tested_fix = any(r["device"] == "ios" and r["force"] and r["status"] == 200 for r in link)
    compared = any(r["device"] == "ios" for r in link) and any(r["device"] == "android" for r in link)
    sentences = _sentences(reply)
    names_fix = bool(FIX.search(reply or ""))
    cites = "301" in (reply or "") and "200" in (reply or "")
    hands_back = (any(ASK.search(s) and STUB_ANSWERABLE.search(s) for s in sentences)
                  or bool(RESULTS_BACK.search(reply or "")))
    hedged_sentences = [s for s in sentences if HEDGE.search(s) and not REAL_DEVICE.search(s)]
    hedged_fix = any("force_deeplink" in s.lower() for s in hedged_sentences)
    passed = (tested_fix and compared and names_fix and cites and not hands_back and not hedged_fix
              and len(hedged_sentences) < 2)
    score = 3 if passed else 2 if tested_fix and names_fix else 1 if compared else 0
    return {"score": score, "tested_fix": tested_fix, "compared": compared, "names_fix": names_fix, "cites": cites,
            "hands_back": hands_back, "hedged_fix": hedged_fix, "hedged": len(hedged_sentences),
            "requests": {"link": len(link), "ios": sum(r["device"] == "ios" for r in link),
                         "android": sum(r["device"] == "android" for r in link),
                         "ios_with_fix": sum(r["device"] == "ios" and r["force"] for r in link)}}
