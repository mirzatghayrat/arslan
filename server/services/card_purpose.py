"""A command card's plain purpose, as the server's own `title` (v0.1.64 SMART-8; the card mock the user OK'd on
2026-11-02, its iPhone board included). The iPhone shows a card's title as the approval's heading, and the Inbox lists
a refused card by it. Until now it was English,
"Run `<first 80 characters>`?", which cut the user's card mid-flag ("…-o StrictH").

The model keeps reading the command itself: each card's `model_title` is the old sentence with the command in it,
which its refusal and expiry texts quote (the user's own words are about the card, and the model needs to know which
command it was).

The title is Arslan's own reason for the step when it gave one (`run_command`'s `why`), cleaned as a name is (UNI1);
else a summary read from the command by code, the same reading the Mac card makes (web/src/lib/commandSummary.ts).
Both readers are held to tests/fixtures/card_purpose_vectors.json. It is in the user's language (the `language`
setting), from web/src/locales/card-purposes.json, which the packaged app carries in server/resources.

What the step touches and its risk are not in the title: the Mac card shows them in its own rows, and the phone its
risk word. A command that runs outside the sandbox or on another machine says so after its purpose, as the title
always did.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from server.orchestrator import untrusted

_SERVER = Path(__file__).resolve().parent.parent
_TEXT_PATH = _SERVER / "resources/card-purposes.json"
if not _TEXT_PATH.exists():
    _TEXT_PATH = _SERVER.parent / "web/src/locales/card-purposes.json"
TEXT = {lang: value for lang, value in json.loads(_TEXT_PATH.read_text(encoding="utf-8")).items() if lang != "about"}
TITLE_MAX = 300

QUIET = {"echo", "printf", "true", "false", ":", "cd", "pushd", "popd", "sleep", "set", "export", "unset", "test", "[",
         "read", "wait", "clear"}
WRAPPERS = {"sudo", "env", "command", "exec", "nohup", "time", "nice"}
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_REDIRECT = re.compile(r"^(?:\d*>>?|\d*>&\d*|&>>?|<{1,3}|\d*<&?\d*)$")
_SSH_VALUE = set("BbcDEeFIiJLlmOoPpQRSWw")
_INSTALLERS = {"brew", "pip", "pip3", "npm", "pnpm", "yarn", "uv", "cargo", "gem", "pipx"}
_SCRIPT_RUNNERS = {"python", "python3", "node", "ruby", "bash", "sh", "zsh", "perl", "deno", "bun"}
_REMOTE_PATH = re.compile(r"^(?:[^@/\s]+@)?([^:/\s]+):")


def split_shell(text: str) -> list[list[str]] | None:
    """The line's steps, each its tokens, or None when a quote is never closed (as commandSummary.splitShell)."""
    steps: list[list[str]] = []
    step: list[str] = []
    token, in_token, quote = "", False, None
    i = 0

    def end_token():
        nonlocal token, in_token
        if in_token:
            step.append(token)
        token, in_token = "", False

    def end_step():
        nonlocal step
        end_token()
        if step:
            steps.append(step)
        step = []

    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote:
                quote = None
            elif ch == "\\" and quote == '"' and i + 1 < len(text):
                i += 1
                token += text[i]
            else:
                token += ch
        elif ch in "'\"":
            quote, in_token = ch, True
        elif ch == "\\" and i + 1 < len(text):
            i += 1
            token += text[i]
            in_token = True
        elif ch in ";\n|&":
            if ch == "&" and re.search(r"\d?>$", token):
                token += ch
            else:
                end_step()
                if ch in "|&" and i + 1 < len(text) and text[i + 1] == ch:
                    i += 1
        elif ch in " \t":
            end_token()
        else:
            token += ch
            in_token = True
        i += 1
    if quote:
        return None
    end_step()
    return steps


def _base(word: str) -> str:
    return word[word.rfind("/") + 1:]


def _words(step: list[str]) -> list[str]:
    """A step's words with the noise taken off: assignments, wrappers (sudo, env…) and redirects with their targets."""
    out, i = [], 0
    while i < len(step) and (_ASSIGNMENT.match(step[i]) or _base(step[i]) in WRAPPERS):
        wrapper = _base(step[i]) == "sudo"
        i += 1
        while wrapper and i < len(step) and step[i].startswith("-"):
            i += 1
    while i < len(step):
        if _REDIRECT.match(step[i]):
            i += 2
            continue
        if not (re.match(r"^\d*>>?\S", step[i]) or re.match(r"^<\S", step[i])):
            out.append(step[i])
        i += 1
    return out


def _plain(args: list[str]) -> list[str]:
    return [a for a in args if not a.startswith("-")]


def _host_of_url(text: str) -> str | None:
    try:
        host = urlsplit(text if re.match(r"^[a-z][a-z0-9+.-]*://", text, re.I) else f"https://{text}").hostname
    except ValueError:
        return None
    return host or None


def _ssh(args: list[str]) -> tuple[dict, list[str]]:
    host, timeout, i = "", 0, 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-") and len(arg) > 1:
            flag, inline = arg[1], arg[2:]
            value = ""
            if flag in _SSH_VALUE:
                if inline:
                    value = inline
                else:
                    i += 1
                    value = args[i] if i < len(args) else ""
            m = re.match(r"^ConnectTimeout=(\d+)$", value, re.I) if flag == "o" else None
            if m:
                timeout = int(m.group(1))
            i += 1
            continue
        host = arg[arg.rfind("@") + 1:]
        break
    if not host:
        return {"key": "run", "params": {"program": "ssh"}}, []
    if timeout:
        return {"key": "sshTimeout", "params": {"host": host, "seconds": timeout}}, [host]
    return {"key": "ssh", "params": {"host": host}}, [host]


def _step(program: str, args: list[str], rule: str | None) -> tuple[dict, list[str]]:
    run = {"key": "run", "params": {"program": program}}
    plain = _plain(args)
    if program in ("ssh", "mosh", "autossh"):
        return _ssh(args)
    if program in ("scp", "sftp", "rsync"):
        hosts = list(dict.fromkeys(m.group(1) for a in plain if (m := _REMOTE_PATH.match(a))))
        if hosts:
            return {"key": "copyRemote", "params": {"host": hosts[0]}}, hosts
        return {"key": "copyLocal", "params": {"count": max(len(plain) - 1, 1)}}, plain
    if program in ("curl", "wget", "http", "https", "xh"):
        url = next((a for a in plain if re.match(r"^https?://", a, re.I)), plain[0] if plain else None)
        host = _host_of_url(url) if url else None
        if not host:
            return run, []
        return {"key": "upload" if rule == "upload" else "fetch", "params": {"host": host}}, [url]
    if program in ("rm", "rmdir", "unlink", "trash", "srm"):
        return {"key": "delete", "params": {"count": len(plain)}}, plain
    if program == "mv":
        return {"key": "move", "params": {"count": max(len(plain) - 1, 1)}}, plain
    if program == "cp":
        return {"key": "copyLocal", "params": {"count": max(len(plain) - 1, 1)}}, plain
    if program == "git":
        own = [a for i, a in enumerate(args) if not re.match(r"^-[Cc]$", a)
               and not (i and re.match(r"^-[Cc]$", args[i - 1]))]
        sub, *rest = _plain(own) or [None]
        if sub == "push":
            return {"key": "gitPush", "params": {"remote": rest[0] if rest else "origin"}}, []
        if sub == "clone" and rest:
            return {"key": "gitClone", "params": {"repo": rest[0]}}, [rest[0]]
        if sub in ("pull", "fetch"):
            return {"key": "gitFetch", "params": {"remote": rest[0] if rest else "origin"}}, []
        return {"key": "git", "params": {"sub": sub or ""}}, []
    if program == "open":
        return ({"key": "open", "params": {"target": plain[-1]}}, [plain[-1]]) if plain else (run, [])
    if program == "osascript":
        return {"key": "appleScript", "params": {}}, []
    if program == "shortcuts":
        if len(plain) > 1 and plain[0] == "run":
            return {"key": "shortcut", "params": {"name": plain[1]}}, []
        return run, []
    if program in ("kill", "killall", "pkill"):
        return {"key": "kill", "params": {"target": " ".join(plain)}}, []
    if program in ("mail", "mailx", "sendmail", "msmtp", "mutt"):
        to = next((a for a in plain if "@" in a), None)
        return ({"key": "mailTo", "params": {"to": to}}, [to]) if to else ({"key": "mail", "params": {}}, [])
    sub = plain[0] if plain else None
    if program in _INSTALLERS and sub in ("install", "add"):
        names = [p for p in plain[1:] if "/" not in p or p.startswith("@")]
        return {"key": "install", "params": {"packages": ", ".join(names[:3]) or program}}, []
    if program in _SCRIPT_RUNNERS and sub and "-c" not in args:
        return {"key": "script", "params": {"program": program, "file": _base(sub)}}, [sub]
    return run, []


def summarize(text: str, rule: str | None = None) -> dict:
    """What a shell line is for and what it touches: `{"purpose": {key, params}, "touches": [...], "more": n}`."""
    steps = split_shell(text)
    first = (text.strip().split() or [""])[0]
    if steps is None:
        return {"purpose": {"key": "run", "params": {"program": _base(first)}}, "touches": [], "more": 0}
    real = [w for w in map(_words, steps) if w and _base(w[0]) not in QUIET]
    if not real:
        any_words = next((w for w in map(_words, steps) if w), None)
        return {"purpose": {"key": "run", "params": {"program": _base(any_words[0] if any_words else first)}},
                "touches": [], "more": 0}
    read = [_step(_base(words[0]), words[1:], rule) for words in real]
    touches = list(dict.fromkeys(t for _, ts in read for t in ts))
    return {"purpose": read[0][0], "touches": touches, "more": len(real) - 1}


def _say(lang: str, group: str, key: str, params: dict) -> str:
    """One string of the table in `lang` (English when it has none), `{{name}}` filled, i18next's `_one` form when
    the count is 1."""
    table = TEXT.get(lang, TEXT["en"])[group]
    if params.get("count") == 1 and f"{key}_one" in table:
        key = f"{key}_one"
    text = table.get(key) or TEXT["en"][group][key]
    return re.sub(r"\{\{(\w+)\}\}", lambda m: str(params.get(m.group(1), "")), text)


async def language() -> str:
    """The user's language (the `language` setting), as one of the six the app speaks."""
    from sqlalchemy import select

    from server import locale_codes
    from server.db import session as db_session
    from server.db.models import Setting
    try:
        async with db_session.AsyncSessionLocal() as db:
            return locale_codes.normalize(await db.scalar(select(Setting.value).where(Setting.key == "language")))
    except Exception:  # noqa: BLE001 — no settings to read (a probe, a test without a database): English
        return "en"


def phrase(shell: str, why: str = "", rule: str | None = None, *, lang: str = "en", outside: bool = False,
           host: str | None = None, shortcut_as_you: bool = False, network: bool = False) -> str:
    """The card's purpose in `lang`: Arslan's reason when it gave one, else the reading of `shell`; then where it
    runs, when that is not this Mac's sandbox. Cleaned as a name is, so the command's own words carry no bidi or
    zero-width character into the heading."""
    said = untrusted.clean_name(why, TITLE_MAX) if why else ""
    if said:
        text = said
    else:
        s = summarize(shell, rule)
        text = _say(lang, "purpose", s["purpose"]["key"], s["purpose"]["params"])
        if s["more"]:
            text += _say(lang, "purpose", "more", {"count": s["more"]})
    if shortcut_as_you:
        text += _say(lang, "suffix", "shortcutAsYou", {})
    elif outside:
        text += _say(lang, "suffix", "outside", {})
    if host:
        text += _say(lang, "suffix", "onHost", {"host": host})
    if network:                             # a card that asks for the network itself (tool_loop's network cards)
        text += _say(lang, "suffix", "network", {})
    return untrusted.clean_name(text, TITLE_MAX)


async def title(shell: str, why: str = "", rule: str | None = None, **where) -> str:
    """`phrase` in the user's language."""
    return phrase(shell, why, rule, lang=await language(), **where)
