"""INB9-a (v0.1.64): the acceptance sheet an unattended run ends with.

Three lists, appended to a background job's one result message (`background_jobs._report`), sub-sessions' jobs
included; a sub-session's summary turn in its commander gets none. A turn the user is present for gets none, and a
scheduled run gets its own in INB9-b.

- ✅ verified: a `deterministic` check that `passed`, naming what it looked at (the file it found, or its rule's
  target) and the validator's code. Nothing else is ever here: a check only a model passed is not verified
  (`AcceptanceCheck.critical_is_not_model_only`).
- 👀 for you to look at: a `human` check, which no run can pass. A job's `glance` criteria, at most `MAX_GLANCES`.
- ⚠️ not verified: everything else, each with why: not run, did not pass, not reached, only the model's own
  judgement, or a glance past the cap. A sub-session's written files are listed here: written, never re-checked.

The descriptions are the model's words and may echo outside content: the caller frames the whole message as it frames
the result (`untrusted.job_result`), and nothing here feeds a TaskSpec or memory.
"""
from __future__ import annotations

from dataclasses import dataclass

#: A job's `glance` criteria are human checks, at most this many; the rest are model checks the sheet marks.
MAX_GLANCES = 2
#: The id prefix every `glance` criterion gets, human or past the cap (`background_jobs.criteria_to_acceptance`).
GLANCE = "glance-"
ANSWER = "answer-delivered"


@dataclass(frozen=True)
class Line:
    check_id: str | None
    text: str
    evidence: str | None = None     # ✅: the path found, or the rule's target
    code: str | None = None         # the validator's code (✅, and ⚠️ for a check that ran or was not run)
    note: str | None = None         # ⚠️: why, a runtime_messages key


def _target(rule: dict | None) -> str | None:
    rule = rule or {}
    if rule.get("target"):
        return str(rule["target"])
    contains = rule.get("contains") or ()
    return str(contains[0]) if contains else None


def _why(check: dict, status: str | None) -> str:
    if str(check.get("id") or "").startswith(GLANCE):
        return "sheet_more_glances"
    if status is None:
        return "sheet_not_reached"
    if status == "passed":
        return "sheet_model_only"
    return "sheet_failed" if status == "failed" else "sheet_not_run"


def columns(acceptance: list[dict], results: dict, report: dict | None, *,
            files: list[str] | tuple = ()) -> tuple[list[Line], list[Line], list[Line]]:
    """(verified ✅, glance 👀, unverified ⚠️) from a run's checks (`acceptance`), their statuses (`results`, check id
    -> status) and its validation report (codes, and the path a file_saved check found)."""
    details = {item.get("check_id"): item for item in (report or {}).get("checks") or () if isinstance(item, dict)}
    verified: list[Line] = []
    glance: list[Line] = []
    unverified: list[Line] = []
    for check in acceptance:
        check_id = check.get("id")
        status, detail = results.get(check_id), details.get(check_id) or {}
        text = str(check.get("description") or "")
        if check.get("evaluator") == "deterministic" and status == "passed":
            verified.append(Line(check_id, text, evidence=detail.get("path") or _target(check.get("rule")),
                                 code=detail.get("code")))
        elif check.get("evaluator") == "human":
            glance.append(Line(check_id, text))
        else:
            why = _why(check, status)
            unverified.append(Line(check_id, text, note=why,
                                   code=detail.get("code") if why in {"sheet_failed", "sheet_not_run"} else None))
    unverified += [Line(None, f"`{_tick(path)}`", note="sheet_file_unchecked") for path in files]
    return verified, glance, unverified


def _tick(value: str) -> str:
    return str(value).replace("`", "'")


def render(acceptance: list[dict], results: dict, report: dict | None, locale: str, *,
           files: list[str] | tuple = ()) -> str:
    """The sheet as Markdown: one bold heading per list that has lines, in the user's language."""
    from server.services.runtime_messages import render as words
    verified, glance, unverified = columns(acceptance, results, report, files=files)

    def line(item: Line) -> str:
        text = words("sheet_answer", locale) if item.check_id == ANSWER else item.text
        if item.evidence:
            text += f" — `{_tick(item.evidence)}`"
        if item.note:
            text += f" — {words(item.note, locale)}"
        return f"- {text}" + (f" ({item.code})" if item.code else "")

    blocks = [f"**{words(heading, locale)}**\n" + "\n".join(map(line, items))
              for heading, items in (("sheet_verified", verified), ("sheet_glance", glance),
                                     ("sheet_unverified", unverified)) if items]
    return "\n\n".join(blocks)
