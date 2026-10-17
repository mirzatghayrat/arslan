"""T10 long log: in a 5,000-line generated log, find the first cause of a later run of failures.

The log has noise, an early harmless warning, the cause (a refused connection to one
replica) and, from then on, a run of failed jobs; a second, unrelated error comes after
the failures start. 3 = the reply names the cause's line (±2) and the cause; 1 = only
one of the two; 0 = neither.
"""
from __future__ import annotations

import random
import re
from pathlib import Path

LINES = 5000
CAUSE = "ERROR db.pool: connection refused by replica-2 (ECONNREFUSED 10.0.4.12:5432)"
KEYWORDS = ("econnrefused", "connection refused", "replica-2")


def fixture(run: str, seed: int | None = None) -> dict:
    rng = random.Random(seed)
    cause_at = rng.randint(1500, 3000)
    lines = []
    for n in range(1, LINES + 1):
        ts = f"2026-10-14T{8 + n // 3600:02d}:{n // 60 % 60:02d}:{n % 60:02d}Z"
        if n == cause_at:
            text = CAUSE
        elif n == 400:
            text = "WARN cache: eviction rate above 5% (expected during warm-up)"
        elif n == cause_at + 900:
            text = "ERROR mailer: template 'weekly' missing a footer"
        elif n > cause_at and n % 7 == 0:
            text = f"ERROR jobs: job {10000 + n} failed: upstream unavailable (db)"
        else:
            text = f"INFO worker-{n % 4}: processed batch {n} in {rng.randint(20, 90)} ms"
        lines.append(f"{ts} {text}")
    (Path(run) / "service.log").write_text("\n".join(lines) + "\n")
    return {"cause_line": cause_at}            # kept by the runner, never in the agent's folder


# A 3–4 digit number that is not part of a longer number, a decimal, a date ("2026-10-14")
# or an address ("10.0.4.12:5432"). Allowed right after it: "." or ":" ("line 1775.",
# grep -n's "1775:…").
LINE_NUMBER = re.compile(r"(?<![\d.:\-])(\d{3,4})(?!\d)(?!\.\d)(?!-)")


def check(run: str, reply: str, params: dict) -> dict:
    want = params["cause_line"]
    numbers = {int(x) for x in LINE_NUMBER.findall(reply or "")}
    line_ok = any(abs(x - want) <= 2 for x in numbers)
    cause_ok = any(k in (reply or "").lower() for k in KEYWORDS)
    return {"score": 3 if line_ok and cause_ok else 1 if (line_ok or cause_ok) else 0,
            "line_ok": line_ok, "cause_ok": cause_ok, "cause_line": want}
