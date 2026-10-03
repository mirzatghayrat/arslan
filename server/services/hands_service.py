"""Arslan Hands' state in the backend (0.1.53): its switch and never-list, who
was asked about what, the Stop latch, the trace, and what counts as high-risk.

Settings live in `<data>/hands/settings.json` (not settings_service: 0.1.52 and
0.1.53 ship in parallel and must not collide). The built-in never-list and app
tiers come from `desktop/hands/policy.json` — the file the helper compiles in —
so Settings shows exactly the list Hands enforces. The backend can only add to
it (the user's own "never touch" entries); Hands enforces the built-in list on
its own side regardless of what the backend sends.

Grants are in memory only: looking at an app is asked once per conversation,
acting in an app once per background job; a high-risk action every time.
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

TRACE_DAYS = 7
MAX_NEVER = 200

_lock = threading.Lock()
_looked: set[tuple[str, str]] = set()          # (conversation id, bundle id)
_acting: dict[str, set[str]] = {}              # job id → bundle ids allowed
_sessions: dict[str, str] = {}                 # job id → agent-desktop session (cursor)
_stopped: set[str] = set()                     # job ids that were running at a Stop
_permission_asked = False


# ── settings ─────────────────────────────────────────────────────────────────

def _dir() -> Path:
    from server import config
    return Path(config.data_dir()) / "hands"


def _private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def settings() -> dict:
    try:
        raw = json.loads((_dir() / "settings.json").read_text())
    except (OSError, ValueError):
        raw = {}
    never = raw.get("never") if isinstance(raw, dict) else None
    return {
        "enabled": bool(raw.get("enabled", True)) if isinstance(raw, dict) else True,
        "cursor": bool(raw.get("cursor", True)) if isinstance(raw, dict) else True,
        "never": [str(n)[:120] for n in never if isinstance(n, str) and n.strip()][:MAX_NEVER]
                 if isinstance(never, list) else [],
    }


def update_settings(*, enabled: bool | None = None, cursor: bool | None = None,
                    never: list[str] | None = None) -> dict:
    current = settings()
    if enabled is not None:
        current["enabled"] = bool(enabled)
    if cursor is not None:
        current["cursor"] = bool(cursor)
    if never is not None:
        seen: list[str] = []
        for item in never:
            item = " ".join(str(item).split())[:120]
            if item and item.lower() not in (s.lower() for s in seen):
                seen.append(item)
        current["never"] = seen[:MAX_NEVER]
    folder = _private_dir(_dir())
    tmp = folder / "settings.json.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(current, f)
    os.replace(tmp, folder / "settings.json")
    return current


# ── the shared policy file ───────────────────────────────────────────────────

def _policy_path() -> Path:
    server_dir = Path(__file__).resolve().parent.parent
    packaged = server_dir / "resources" / "hands" / "policy.json"     # PyInstaller datas
    return packaged if packaged.is_file() else server_dir.parent / "desktop" / "hands" / "policy.json"


def policy() -> dict:
    return json.loads(_policy_path().read_text())


def _matches(group: dict, bundle_id: str, name: str) -> bool:
    for pattern in group.get("bundle_ids", []):
        if pattern.endswith(".*"):
            prefix = pattern[:-2].lower()
            if bundle_id.lower() == prefix or bundle_id.lower().startswith(prefix + "."):
                return True
        elif bundle_id and bundle_id.lower() == pattern.lower():
            return True
    return any(n.lower() == name.strip().lower() for n in group.get("names", []))


def sends_on_return(bundle_id: str, name: str) -> bool:
    return _matches(policy()["sends_on_return"], bundle_id, name)


def built_in_lists() -> dict:
    """What Settings shows: the never-list and the two limited tiers, by label."""
    p = policy()
    return {"never": [g["label"] for g in p["denied"]],
            "look_only": [g["label"] for g in p["look_only"]],
            "click_only": [g["label"] for g in p["click_only"]]}


# ── when to ask ──────────────────────────────────────────────────────────────

_RISKY_WORDS = re.compile(
    r"\b(delete|remove|erase|trash|discard|send|submit|pay|purchase|buy|order|checkout|check out|transfer|"
    r"sign|post|publish|confirm|eliminar|borrar|enviar|pagar|comprar|transferir|löschen|entfernen|senden|"
    r"absenden|bezahlen|kaufen|überweisen|supprimer|effacer|envoyer|payer|acheter|virement|soumettre|publier)\b"
    r"|删除|移除|清空|发送|提交|付款|支付|购买|下单|转账|汇款|发布|確認購入|削除|送信|支払|購入|振込|提出|投稿",
    re.I)
_RISKY_KEYS = {"cmd+delete", "cmd+backspace", "cmd+shift+delete", "cmd+shift+backspace", "cmd+shift+d",
               "cmd+return", "cmd+enter", "cmd+option+delete", "cmd+alt+delete"}


def risky_label(label: str | None) -> bool:
    """A button or menu item whose real label (read from the app, not the model's
    words) deletes, sends, pays, buys, transfers or submits."""
    return bool(label) and bool(_RISKY_WORDS.search(str(label)))


def risky_keys(keys: str, *, bundle_id: str, app: str) -> bool:
    keys = keys.strip().lower()
    if keys in _RISKY_KEYS:
        return True
    return keys in ("return", "enter") and sends_on_return(bundle_id, app)


def risky_text(text: str, *, bundle_id: str, app: str) -> bool:
    """Typed text ending in a newline sends in messaging and mail apps."""
    return text.endswith("\n") and sends_on_return(bundle_id, app)


def looked(conversation_id: str, bundle_id: str) -> bool:
    with _lock:
        return (conversation_id, bundle_id) in _looked


def allow_look(conversation_id: str, bundle_id: str) -> None:
    with _lock:
        _looked.add((conversation_id, bundle_id))


def may_act(job_id: str, bundle_id: str) -> bool:
    with _lock:
        return bundle_id in _acting.get(job_id, set())


def allow_act(job_id: str, bundle_id: str) -> None:
    with _lock:
        _acting.setdefault(job_id, set()).add(bundle_id)


def session_for(job_id: str) -> str | None:
    with _lock:
        return _sessions.get(job_id)


def remember_session(job_id: str, session: str) -> None:
    with _lock:
        _sessions[job_id] = session


def forget_job(job_id: str) -> str | None:
    """A job ended: its grants and Stop mark go; returns its cursor session to end."""
    with _lock:
        _acting.pop(job_id, None)
        _stopped.discard(job_id)
        return _sessions.pop(job_id, None)


# ── Stop ─────────────────────────────────────────────────────────────────────

def stop_running_jobs() -> list[str]:
    """Every job running now refuses further Hands calls (jobs started later do not)."""
    from server.services import background_jobs
    running = [job_id for job_id, job in background_jobs._jobs.items() if job.phase != "finished"]
    with _lock:
        _stopped.update(running)
        _stopped.update(_sessions)
    return running


def stopped(job_id: str | None) -> bool:
    with _lock:
        return job_id is not None and job_id in _stopped


def permission_prompt_once() -> bool:
    """True the first time in this process: Hands asks macOS to show its prompt once."""
    global _permission_asked
    with _lock:
        first, _permission_asked = not _permission_asked, True
    return first


# ── trace ────────────────────────────────────────────────────────────────────

def _trace_dir() -> Path:
    return _private_dir(_private_dir(_dir()) / "trace")


def prune_trace(today: date | None = None) -> None:
    today = today or date.today()
    folder = _dir() / "trace"
    if not folder.is_dir():
        return
    for path in folder.glob("*.jsonl"):
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if (today - day).days >= TRACE_DAYS:
            path.unlink(missing_ok=True)


def trace(entry: dict) -> None:
    """Append one Hands call (0600 file, 0700 folder). Never typed text: its length."""
    now = datetime.now(timezone.utc)
    line = json.dumps({"at": now.isoformat(timespec="seconds"), **entry}, ensure_ascii=False)
    path = _trace_dir() / f"{now.date().isoformat()}.jsonl"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a") as f:
        f.write(line + "\n")
    prune_trace(now.date())


def read_trace(days: int = TRACE_DAYS, limit: int = 500) -> list[dict]:
    folder = _dir() / "trace"
    if not folder.is_dir():
        return []
    cutoff = date.today() - timedelta(days=min(max(days, 1), TRACE_DAYS) - 1)
    out: list[dict] = []
    for path in sorted(folder.glob("*.jsonl"), reverse=True):
        try:
            if date.fromisoformat(path.stem) < cutoff:
                continue
            lines = path.read_text().splitlines()
        except (ValueError, OSError):
            continue
        for line in reversed(lines):
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
            if len(out) >= limit:
                return out
    return out


def _reset_for_tests() -> None:
    global _permission_asked
    with _lock:
        _looked.clear()
        _acting.clear()
        _sessions.clear()
        _stopped.clear()
        _permission_asked = False

