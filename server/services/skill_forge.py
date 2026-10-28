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
`AUTHORED`, which the seeder reads as the user's skill (D7): a retirement never deletes it.

This replaces the Skill Forge page, its candidates and the curator (sessions.md §11). The
`skill_candidates` table stays until CAP2b, which gives the skills promoted from it the same mark.
"""
from __future__ import annotations

import re
import unicodedata

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
#: A body that relies on files of its own, the way an imported skill's does (skill_import: run_python's
#: `skill_script`, read_skill's `references/` section, the "Bundled" headings). This tool writes text only.
_USES_FILES = re.compile(r"skill_script|[\"']?section[\"']?\s*:\s*[\"']references/|^#+\s*bundled\s+(?:scripts|references)",
                         re.I | re.M)


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
    """Without control or format characters (a bidi override, a zero-width space) but those in `keep`: the
    card shows exactly what is stored."""
    return "".join(ch for ch in str(text or "") if ch in keep or not unicodedata.category(ch).startswith("C"))


def _line(text, limit: int) -> str:
    return " ".join(_visible(text).split())[:limit]


def _files_folder(key: str):
    """Where skill_import stores a skill's scripts and references (`executors._skill_scripts_root`)."""
    from server import config
    return config.data_dir() / "skill_scripts" / key


async def register(*, key: str, name: str, description: str, body: str) -> bool:
    """Write the skill, on and equippable at once (the registry reads SkillPack directly). False when the key
    is taken: nothing is overwritten."""
    try:
        async with db_session.AsyncSessionLocal() as db:
            if await db.get(SkillPack, key) is not None:
                return False
            db.add(SkillPack(key=key, name=name, category=AUTHORED, description=description, tier="safe",
                             status="registered", body=body, enabled=True))
            await db.commit()
    except IntegrityError:          # the same key written meanwhile
        return False
    return True


async def propose(args: dict, *, conversation_id: str | None, ask) -> dict:
    """The model's `create_skill`. Returns the tool result (and `refresh: True` once the skill is saved, so
    the loop re-reads its tools and read_skill lists it)."""
    key = str(args.get("key") or "").strip()
    name = _line(args.get("name"), _NAME_MAX)
    description = _line(args.get("description"), _LINE_MAX)
    body = _visible(args.get("body"), keep="\n\t").strip() + "\n"
    why = _line(args.get("why"), _LINE_MAX)
    errors = validate(key, name, description, body) + (
        [f"key is at most {_KEY_MAX} characters"] if len(key) > _KEY_MAX else [])
    if errors:
        return {"ok": False, "error": "not saved: " + "; ".join(errors)}
    if _USES_FILES.search(body):
        return {"ok": False, "error": "not saved: a skill with scripts or attached files cannot be saved yet "
                                      "(v0.1.65). Write the method as text only, or tell the user."}
    if _files_folder(key).exists():
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
            # This turn read a page, a file or another tool's result: the text may carry what that said.
            "outside": untrusted.external_seen()}
    approvals.LAST_OUTCOME.set(None)          # only this card's own outcome may read as expired
    decision = await ask(card)
    await permissions.record_card_outcome(request, context, approved=bool(decision.get("approved")),
                                          expired=approvals.LAST_OUTCOME.get() == "expired")
    if not decision.get("approved"):
        outcome = approvals.LAST_OUTCOME.get() or "declined"
        return {"ok": False, "declined": True,
                "note": f"The user did not save it ({outcome}). Do not propose it again now."}
    if not await register(key=key, name=name, description=description, body=body):
        return {"ok": False, "error": f"not saved: a skill with the key '{key}' was added meanwhile"}
    return {"ok": True, "saved": key, "refresh": True,
            "note": "Saved and switched on. Read it with read_skill when work it covers comes up."}
