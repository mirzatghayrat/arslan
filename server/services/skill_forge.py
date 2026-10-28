"""Skills Arslan writes: the checks, the card and the row (v0.1.64 CAP2a).

`validate` is the shape every SKILL.md body Arslan stores must have (skill_import and
expert_conversion use it too).

`propose` is what the model's `create_skill` tool does. When the user asks to keep a way of working
("save what we just did as a skill"), the model writes the SKILL.md, and the user sees all of it on a
card in the Arslan window that asked: the install card's channel (`confirm_command.ask_capability`,
never the phone, the Inbox or the island). Only their yes writes it, as a skill that is on at once; a
no or no answer leaves nothing but its ledger row. With nobody to ask (a background job or a scheduled
run) nothing is saved and no draft is kept. A skill that would come with files (scripts, references)
is refused before any card: that waits for v0.1.65's "for you to look at".

`register` writes the row, for the card and for a converted former expert. Its category is
`AUTHORED`, or `AUTHORED_OUTSIDE` when the card said the conversation had read outside content (the
user's decision on #472 F1): read_skill then reads it like an imported skill, framed, and the turn that
reads it counts as having read outside content. The seeder reads both as the user's skill (D7): a
retirement never deletes it.

This replaces the Skill Forge page, its candidates and the curator (sessions.md §11). The
`skill_candidates` table stays until CAP2b, which gives the skills promoted from it the same mark.
"""
from __future__ import annotations

import os
import re
import unicodedata

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from server.db import session as db_session
from server.db.models import SkillPack

MAX_SKILL_BYTES = 15 * 1024  # Hermes hygiene: skills stay <=15 KB
_MIN_BODY_CHARS = 80
_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_KEY_MAX = 60           # SkillPack.key
_NAME_MAX = 100         # SkillPack.name
_LINE_MAX = 300         # the description and the reason, as the card shows them
#: The category of a skill Arslan wrote and the user kept (the card's yes, or converting a former
#: expert): the seeder's D7 mark of a user's skill (`seeder._USERS_SKILL`). No seed ever had it.
AUTHORED = "authored"
#: The same, saved from a card that said the conversation had read outside content (#472 F1): read like an
#: imported skill. Both are `WRITTEN`, the seeder's mark.
AUTHORED_OUTSIDE = "authored-outside"
WRITTEN = (AUTHORED, AUTHORED_OUTSIDE)
#: What an earlier turn's `<turn_tools>` block says when it read outside content, or when the block was cut
#: and may have (server/orchestrator/turn_tools.py `_line` and `block`; `turn_tools.OUTSIDE` and the S64-0b
#: headers are added where they are read, below).
_HISTORY_OUTSIDE = ("external content, source only", "more tool calls")
#: A body that relies on files of its own, the way an imported skill's does (skill_import: run_python's
#: `skill_script`, read_skill's `references/` section, the "Bundled" headings). This tool writes text only.
_USES_FILES = re.compile(r"skill_script|[\"']?section[\"']?\s*:\s*[\"']references/|^#+\s*bundled\s+(?:scripts|references)",
                         re.I | re.M)
#: Invisible, though not in a "C" category: variation selectors, the combining grapheme joiner, the Hangul
#: fillers and the blank braille pattern (#472 review F4). A name made only of these would show blank.
_INVISIBLE = re.compile("[\u034f\u115f\u1160\u2800\u3164\uffa0\ufe00-\ufe0f\U000e0100-\U000e01ef]")
#: The longest run of white space kept inside a line, and the leading indentation kept as written: code and
#: YAML nest deep, and their indentation is their meaning (#472 recheck R1).
_RUN_MAX = 16
_INDENT_MAX = 64


def validate(key: str, name: str, description: str, body: str) -> list[str]:
    """Return human-readable validation errors (empty list = valid)."""
    errors: list[str] = []
    if not key or not _KEY_RE.match(key):
        errors.append("key must be non-empty lowercase letters, digits and hyphens (e.g. 'my-skill')")
    if not (name or "").strip():
        errors.append("name is required")
    if not (description or "").strip():
        errors.append("description is required")
    body = body or ""
    if "## Trigger" not in body:
        errors.append("body must contain a '## Trigger' section")
    if len(body) < _MIN_BODY_CHARS:
        errors.append(f"body is too short (need at least {_MIN_BODY_CHARS} characters)")
    if len(body.encode("utf-8")) > MAX_SKILL_BYTES:
        errors.append(f"body exceeds {MAX_SKILL_BYTES // 1024} KB limit")
    return errors


def _visible(text, keep: str = "") -> str:
    """Without control or format characters (a bidi override, a zero-width space) but those in `keep`, and
    without the other invisible ones: the card shows exactly what is stored."""
    return _INVISIBLE.sub("", "".join(ch for ch in str(text or "")
                                      if ch in keep or not unicodedata.category(ch).startswith("C")))


def _tidy(body: str) -> str:
    """Blank padding cannot push the end of the text out of sight in the card's box (#472 review F5, recheck
    R1): the Unicode line and paragraph separators become line breaks (read_skill splits on them too), no
    line ends in white space, at most one blank line in a row, leading indentation is kept as written up to
    `_INDENT_MAX` characters, and a run of white space inside a line stops at `_RUN_MAX`. Any white space
    counts, not only spaces and tabs. The card shows, and the skill keeps, the tidied text."""
    lines = []
    for line in body.replace("\u2028", "\n").replace("\u2029", "\n").split("\n"):
        line = line.rstrip()
        text = line.lstrip()
        lines.append(line[:len(line) - len(text)][:_INDENT_MAX]
                     + re.sub(r"[^\S\n]{%d,}" % (_RUN_MAX + 1), " " * _RUN_MAX, text))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


def _line(text, limit: int) -> str:
    return " ".join(_visible(text).split())[:limit]


def _files_stored(key: str) -> bool:
    """Whether skill_import left anything under this key's folder; a dangling link counts (#472 F8)."""
    from server.registry.executors import _skill_scripts_root
    return os.path.lexists(_skill_scripts_root() / key)


async def _conversation_read_outside(conversation_id: str | None) -> bool:
    """Whether an earlier turn of this conversation read outside content (#472 F2, R3): "save what we just
    did" usually comes in the turn after the page. Read from what the history keeps: a `<turn_tools>` line
    (an outside tool, a cut block, or the turn's own mark for an attachment or OCR text), a job's result
    posted under S64-0b's header, or a rolling summary marked as folding one in. With the tools summary
    switched off there is nothing to read, so the answer is yes (the safe side).
    DELETE-BY: when INB2's `runs.read_outside` lands (#475): read that instead."""
    if not conversation_id:
        return False
    from server.db.models import ArslanMessage, ArslanSummary
    from server.orchestrator import turn_tools, untrusted
    if not turn_tools.enabled():
        return True
    phrases = (*_HISTORY_OUTSIDE, turn_tools.OUTSIDE, untrusted.JOB_RESULT_FROM_OUTSIDE)
    async with db_session.AsyncSessionLocal() as db:
        hit = await db.scalar(select(ArslanMessage.id).where(
            ArslanMessage.conversation_id == conversation_id, ArslanMessage.role == "arslan",
            or_(*(ArslanMessage.content.contains(phrase) for phrase in phrases))).limit(1))
        if hit is None:
            hit = await db.scalar(select(ArslanSummary.id).where(
                ArslanSummary.conversation_id == conversation_id,
                ArslanSummary.summary.contains(untrusted.SUMMARY_FROM_OUTSIDE)).limit(1))
    return hit is not None


async def register(*, key: str, name: str, description: str, body: str, outside: bool) -> bool:
    """Write the skill, on and equippable at once (the registry reads SkillPack directly). `outside` (no
    default: every caller says where the text came from) marks it to be read like an imported skill (#472
    F1, recheck). False when the key is taken: nothing is overwritten."""
    try:
        async with db_session.AsyncSessionLocal() as db:
            if await db.get(SkillPack, key) is not None:
                return False
            db.add(SkillPack(key=key, name=name, category=AUTHORED_OUTSIDE if outside else AUTHORED,
                             description=description, tier="safe", status="registered", body=body, enabled=True))
            await db.commit()
    except IntegrityError:          # the same key written meanwhile
        return False
    return True


async def propose(args: dict, *, conversation_id: str | None, ask) -> dict:
    """The model's `create_skill`. Returns the tool result (and `refresh: True` once the skill is saved, so
    the loop re-reads its tools and read_skill lists it).

    DELETE-BY: v0.1.65, when "for you to look at" lands (CAP card): a skill Arslan writes then waits there for
    the user's review instead of this card's direct save."""
    key = str(args.get("key") or "").strip()
    name = _line(args.get("name"), _NAME_MAX)
    description = _line(args.get("description"), _LINE_MAX)
    body = _tidy(_visible(args.get("body"), keep="\n\t"))
    tidied = body != str(args.get("body") or "").strip() + "\n"
    why = _line(args.get("why"), _LINE_MAX)
    errors = validate(key, name, description, body) + (
        [f"key is at most {_KEY_MAX} characters"] if len(key) > _KEY_MAX else [])
    if errors:
        return {"ok": False, "error": "not saved: " + "; ".join(errors)}
    if _USES_FILES.search(body):
        return {"ok": False, "error": "not saved: a skill with scripts or attached files cannot be saved yet "
                                      "(v0.1.65). Write the method as text only, or tell the user."}
    if _files_stored(key):
        # A removed import's files stay on disk; read_skill and run_python would serve them with this key.
        return {"ok": False, "error": f"not saved: files are already stored under the key '{key}'; pick another key"}
    async with db_session.AsyncSessionLocal() as db:
        if await db.get(SkillPack, key) is not None:
            return {"ok": False, "error": f"not saved: a skill with the key '{key}' exists; pick another key"}
    from server.orchestrator import untrusted
    from server.services import approvals, background_jobs, permissions
    # The ledger keeps the key, the name and the model's reason; never the body.
    request = permissions.Request(kind="capability", target=f"skill:{key}", title=f"Save the skill {name}?"[:200],
                                  detail=why)
    context = permissions.Context(conversation_id, job_id=background_jobs._inside_job.get())
    if ask is None:
        if permissions.current_asker() is None:
            # A scheduled run: listed in the Inbox (S1). A background job writes no row (it shows no card).
            await permissions.refuse_unattended(request, context)
        return {"ok": False, "not_saved": True,
                "note": "Nobody to ask here (a background job or a scheduled run), so nothing was saved and no "
                        "draft is kept. Offer to save it when the user is in the conversation."}
    card = {"kind": AUTHORED, "key": key, "name": name, "description": description, "body": body, "why": why,
            # This conversation read a page, a file or another tool's result, in this turn or an earlier one:
            # the text may carry what that said. The saved skill keeps it (#472 F1, F2).
            "outside": untrusted.external_seen() or await _conversation_read_outside(conversation_id)}
    approvals.LAST_OUTCOME.set(None)          # only this card's own outcome may read as expired
    decision = await ask(card)
    await permissions.record_card_outcome(request, context, approved=bool(decision.get("approved")),
                                          expired=approvals.LAST_OUTCOME.get() == "expired")
    if not decision.get("approved"):
        outcome = approvals.LAST_OUTCOME.get() or "declined"
        return {"ok": False, "declined": True,
                "note": f"The user did not save it ({outcome}). Do not propose it again now."}
    if not await register(key=key, name=name, description=description, body=body, outside=card["outside"]):
        return {"ok": False, "error": f"not saved: a skill with the key '{key}' was added meanwhile"}
    return {"ok": True, "saved": key, "refresh": True, **({"tidied": True} if tidied else {}),
            "note": "Saved and switched on. Read it with read_skill when work it covers comes up."
                    + (" Hidden characters or blank padding were taken out first: the saved text is what the "
                       "user saw, and read_skill returns it." if tidied else "")}
