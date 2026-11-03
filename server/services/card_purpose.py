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
risk word. Where it runs (outside the sandbox, with no sandbox, on another machine) and whether it uses the network
are the code's facts, so they lead the title in a fixed form ("Outside the sandbox · Uses the network · …"), and only
the purpose is cut to fit the phone's heading (#689 review 1).
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
#: The phone shows a title as the approval's heading, cut at 200 (FrameMapper.swift); the whole title fits in it.
PHONE_MAX = 200
#: The facts' separator and the marks that look like it (U+00B7, U+2022, U+2027, U+2219, U+22C5, U+30FB, U+FF65),
#: which the model's words may not use.
_SEPARATORS = re.compile("[" + "".join(map(chr, (0xB7, 0x2022, 0x2027, 0x2219, 0x22C5, 0x30FB, 0xFF65))) + "]")

QUIET = {"echo", "printf", "true", "false", ":", "cd", "pushd", "popd", "sleep", "set", "export", "unset", "test", "[",
         "read", "wait", "clear"}
#: Programs that run the rest of their words as another program, each with its options that take a value.
WRAPPERS = {"sudo": "CDghpRrTUu", "env": "CSu", "command": "", "exec": "a", "nohup": "", "time": "", "nice": "n",
            "timeout": "ks", "xargs": "adEILnPs", "caffeinate": "tw", "stdbuf": ""}
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_FD_DUP = re.compile(r"^[0-9]*[<>]&(?:[0-9]+|-)$")
_OUT = re.compile(r"^(?:[0-9]*|&)>>?\|?$")
_OUT_ATTACHED = re.compile(r"^(?:[0-9]*|&)>>?\|?([^>&|].*)$")
_IN = re.compile(r"^[0-9]*<(?:<<?|>)?-?$")
_IN_ATTACHED = re.compile(r"^[0-9]*<{1,3}-?\S")
_NOT_A_FILE = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"}
_SSH_VALUE = set("BbcDEeFIiJLlmOoPpQRSWw")
_COPY_VALUE = {"scp": "cFiJlOoPS", "sftp": "BbcDFiJlOoPRS", "rsync": "e"}
_INSTALLERS = {"brew", "pip", "pip3", "npm", "pnpm", "yarn", "uv", "cargo", "gem", "pipx"}
_SCRIPT_RUNNERS = {"python", "python3", "node", "ruby", "bash", "sh", "zsh", "perl", "deno", "bun"}
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
_RUNS_CODE = _SHELLS | {"python", "python2", "python3", "node", "perl", "ruby", "php", "deno", "bun", "source", ".",
                        "eval"}
_FETCHERS = {"curl", "wget", "http", "https", "xh"}
_DELETERS = {"rm", "rmdir", "unlink", "trash", "srm"}
_PATH_LIKE = re.compile(r"^(?:/|~|\.{1,2}/|\$HOME\b|\$\{HOME\})", re.A)
_URL_LIKE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)
_REMOTE = re.compile(r"^(?:[^@/\s]+@)?([^:/\s]+):")
_REMOTE_PATH = re.compile(r"^[^/:\s]+:")
#: What is most at stake in a step, by its purpose: the step with the most names the line (ties: the first).
STAKES = {"fetchRun": 10, "delete": 9, "deleteSome": 9, "findDelete": 9, "mailTo": 8, "mail": 8, "mailFile": 8,
          "upload": 8, "uploadFile": 8,
          "onHost": 7, "gitPush": 7, "kill": 6, "copyRemote": 6, "ssh": 5, "sshTimeout": 5, "appleScript": 5,
          "shortcut": 5, "install": 5, "write": 4, "move": 4, "open": 3, "copyLocal": 3, "gitClone": 3, "fetch": 2,
          "gitFetch": 2, "script": 2}


def _closing(text: str, open_at: int) -> int:
    """The index of the `)` that closes the `(` at `open_at`, quotes skipped, or -1."""
    depth, quote, j = 1, None, open_at + 1
    while j < len(text):
        c = text[j]
        if quote:
            if c == quote:
                quote = None
            elif c == "\\" and quote == '"':
                j += 1
        elif c in "'\"":
            quote = c
        elif c == "\\":
            j += 1
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return -1


def _parse(text: str) -> list[dict] | None:
    """The line's steps (`tokens`, `piped`, and `subs`: the steps it runs inside it), or None when a quote or a `$(`
    is never closed (as commandSummary's `parse`)."""
    steps: list[dict] = []
    step = {"tokens": [], "piped": False, "subs": []}
    token, in_token, quote, i = "", False, None, 0

    def end_token():
        nonlocal token, in_token
        if in_token:
            step["tokens"].append(token)
        token, in_token = "", False

    def end_step(piped: bool):
        nonlocal step
        end_token()
        if step["tokens"] or step["subs"]:
            steps.append(step)
        step = {"tokens": [], "piped": piped, "subs": []}

    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if quote != "'":
            opens = nxt == "(" and text[i + 2:i + 3] != "(" and (ch == "$" or (not quote and ch in "<>"))
            if opens or ch == "`":
                end = text.find("`", i + 1) if ch == "`" else _closing(text, i + 1)
                if end < 0:
                    return None
                inner = _parse(text[i + 1 if ch == "`" else i + 2:end])
                if inner is None:
                    return None
                step["subs"].extend(inner)
                token += text[i:end + 1]
                in_token, i = True, end + 1
                continue
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
        elif ch == "&" and (re.search(r"[0-9]?>$", token) or (not in_token and nxt == ">")):
            token += ch
            in_token = True
        elif ch in ";\n|&":
            end_step(ch == "|" and nxt != "|")
            if ch in "|&" and (nxt == ch or (ch == "|" and nxt == "&")):
                i += 1
        elif ch in " \t":
            end_token()
        else:
            token += ch
            in_token = True
        i += 1
    if quote:
        return None
    end_step(False)
    return steps


def split_shell(text: str) -> list[list[str]] | None:
    """The line's steps as words, the steps run inside a step before it; None when a quote is never closed."""
    steps = _parse(text)
    if steps is None:
        return None
    out: list[list[str]] = []

    def walk(items):
        for s in items:
            walk(s["subs"])
            out.append(s["tokens"])
    walk(steps)
    return out


def _base(word: str) -> str:
    return word[word.rfind("/") + 1:]


def _program_of(word: str) -> str:
    """A program word by its file name; one that is itself a substitution (`$(curl …)`) is kept whole."""
    return word if re.match(r"^(?:\$\(|`)", word) else _base(word)


def _plain(args: list[str]) -> list[str]:
    return [a for a in args if not a.startswith("-")]


def _unique(items) -> list:
    return list(dict.fromkeys(items))


def _words(tokens: list[str]) -> dict:
    """A step's program and arguments with the noise taken off: redirects (an output one's file is kept as a write),
    assignments and wrappers with their options. `listed`: xargs gives it its operands."""
    rest, writes, inputs, i = [], [], [], 0

    def write(target):
        if target and target not in _NOT_A_FILE:
            writes.append(target)

    def read_from(source):
        if source and source not in _NOT_A_FILE and source != "/dev/stdin":
            inputs.append(source)
    while i < len(tokens):
        tk = tokens[i]
        if re.match(r"^[<>]\(", tk):
            rest.append(tk)
        elif _FD_DUP.match(tk):
            pass
        elif _OUT.match(tk):
            i += 1
            write(tokens[i] if i < len(tokens) else None)
        elif _IN.match(tk):
            if re.match(r"^[0-9]*<$", tk):                                # a heredoc's word is no file
                read_from(tokens[i + 1] if i + 1 < len(tokens) else None)
            i += 1
        elif m := _OUT_ATTACHED.match(tk):
            write(m.group(1))
        elif _IN_ATTACHED.match(tk):
            m = re.match(r"^[0-9]*<([^<].*)$", tk)
            read_from(m.group(1) if m else None)
        else:
            rest.append(tk)
        i += 1
    i, listed = 0, False
    while True:
        while i < len(rest) and _ASSIGNMENT.match(rest[i]):
            i += 1
        name = _base(rest[i]) if i < len(rest) else ""
        if name not in WRAPPERS:
            break
        i += 1
        listed = listed or name == "xargs"
        while i < len(rest) and rest[i].startswith("-") and rest[i] != "-":
            flag = rest[i]
            i += 1
            if flag == "--":
                break
            if not flag.startswith("--") and len(flag) == 2 and flag[1] in WRAPPERS[name]:
                i += 1
        if name == "timeout" and i < len(rest):
            i += 1                                                         # its duration
    return {"program": _program_of(rest[i]) if i < len(rest) else "", "args": rest[i + 1:], "writes": writes,
            "inputs": inputs, "listed": listed}


def _inline_line(w: dict) -> str | None:
    """The command line a shell's `-c` (or `watch`) runs, or None."""
    if w["program"] in _SHELLS:
        at = next((k for k, a in enumerate(w["args"]) if re.match(r"^-[a-z]*c[a-z]*$", a, re.I)), -1)
        return w["args"][at + 1] if 0 <= at < len(w["args"]) - 1 else None
    if w["program"] == "watch":
        args = list(w["args"])
        while args and args[0].startswith("-"):
            flag = args.pop(0)
            if re.match(r"^-[ndq]$", flag) and args:
                args.pop(0)
        return " ".join(args) if args else None
    return None


def _reads_code(w: dict) -> bool:
    """Whether a program reads the code it runs from its input (`| sh`, `| python3 -`), not a file or `-c`."""
    if w["program"] not in _RUNS_CODE:
        return False
    for a in w["args"]:
        if a == "--":
            return True
        if (re.match(r"^-[a-z]*[cme]$", a, re.I) and w["program"] not in _SHELLS) or re.match(r"^-[a-z]*c[a-z]*$", a, re.I):
            return False
        if a in ("-s", "-"):
            return True
        if not a.startswith("-"):
            return False                                                   # a script file
    return True


def _host_of_url(text: str) -> str | None:
    try:
        host = urlsplit(text if _URL_LIKE.match(text) else f"https://{text}").hostname
    except ValueError:
        return None
    return host or None


def _reading(key: str, params: dict, hosts=(), local=(), inner: dict | None = None, sent=()) -> dict:
    """`sent`: the files an upload or an email sends (#688 review, the second round): the title names them."""
    purpose = {"key": key, "params": params}
    if inner is not None:
        purpose["inner"] = inner
    return {"purpose": purpose, "hosts": list(hosts), "local": list(local), "sent": list(sent)}


#: How each of curl's and wget's sending options names its file: `@f` (data), `name@f` (named), `k=@f` or `k=<f`
#: (form), or the value itself (file).
_SENDS = {"-d": "data", "--data": "data", "--data-binary": "data", "--json": "data", "--data-urlencode": "named",
          "-F": "form", "--form": "form", "-T": "file", "--upload-file": "file", "--post-file": "file",
          "--body-file": "file"}
_CURL_VALUE = "AbcCdDeEFHKmoPQrTuUwxXyYz"


def _flag_of(word: str) -> tuple[str, str | None]:
    """The flag a word is, with its value when it carries one (`--data=@f`, `-d@f`)."""
    if m := re.match(r"^(--[a-z-]+)=(.*)$", word):
        return m.group(1), m.group(2)
    return (word[:2], word[2:]) if re.match(r"^-[dFT].", word) else (word, None)


def _sending(args: list[str], inputs: list[str]) -> tuple[bool, list[str]]:
    """Whether an upload sends at all, even with no file named, and the files it sends; `-` is its input (`< f`)."""
    files, sends, i = [], False, 0
    while i < len(args):
        flag, inline = _flag_of(args[i])
        kind = _SENDS.get(flag)
        if kind:
            sends = True
            if inline is None:
                i += 1
                inline = args[i] if i < len(args) else ""
            m = (None if kind == "file" else re.search(r"=[@<]([^;]*)", inline) if kind == "form"
                 else re.match(r"^[^=@]*@(.*)$", inline) if kind == "named" else re.match(r"^@(.*)$", inline))
            file = inline if kind == "file" else (m.group(1) if m else None)
            if file == "-":
                files.extend(inputs)
            elif file:
                files.append(file)
        i += 1
    return sends, _unique(files)


def _run(program: str) -> dict:
    return _reading("run", {"program": program})


def _operands(args: list[str], valued: str) -> list[str]:
    """Skips an option's value where the program takes one, so the operands are what is left."""
    out, i = [], 0
    while i < len(args):
        a = args[i]
        if a.startswith("-") and len(a) > 1:
            if len(a) == 2 and a[1] in valued:
                i += 1
        else:
            out.append(a)
        i += 1
    return out


def _ssh(program: str, args: list[str], rules: list[str]) -> dict:
    timeout, i = 0, 0
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
            m = re.match(r"^ConnectTimeout=([0-9]+)$", value, re.I) if flag == "o" else None
            if m:
                timeout = int(m.group(1))
            i += 1
            continue
        host = arg[arg.rfind("@") + 1:]
        remote = args[i + 1:]
        if remote[:1] == ["--"]:
            remote = remote[1:]
        # #688 review 6d: words after the host are a command that runs there, read as its own line.
        there = _read(" ".join(remote), rules) if remote else None
        if there and there["real"]:
            return _reading("onHost", {"host": host}, [host, *there["hosts"]], [f"{host}:{p}" for p in there["local"]],
                            inner=there["purpose"])
        if timeout:
            return _reading("sshTimeout", {"host": host, "seconds": timeout}, [host])
        return _reading("ssh", {"host": host}, [host])
    return _run(program)


def _step(w: dict, rules: list[str]) -> dict:
    """One step's purpose and what it touches: `hosts` (other machines, web and mail addresses) and `local` (paths on
    the machine it runs on). `rules`: the server's terminal rules for the line (upload, git-push…)."""
    program, args = w["program"], w["args"]
    plain = _plain(args)
    if program in ("ssh", "mosh", "autossh"):
        return _ssh(program, args, rules)
    if program in ("scp", "sftp", "rsync"):
        ops = _operands(args, _COPY_VALUE[program])
        hosts = _unique(m.group(1) for a in ops if (m := _REMOTE.match(a)))
        if hosts:
            return _reading("copyRemote", {"host": hosts[0]}, hosts, [a for a in ops if not _REMOTE.match(a)])
        return _reading("copyLocal", {"count": max(len(ops) - 1, 1)}, [], ops)
    if program in _FETCHERS:
        url = next((a for a in plain if re.match(r"^https?://", a, re.I)),
                   next((a for a in _operands(args, _CURL_VALUE) if not a.startswith("@")), None))
        host = _host_of_url(url) if url else None
        if not host:
            return _run(program)
        sends, files = _sending(args, w["inputs"])
        return _reading("upload" if sends or "upload" in rules else "fetch", {"host": host}, [url], sent=files)
    if program == "cat":
        return _reading("run", {"program": program}, [], plain)
    if program in _DELETERS:
        if plain or not w["listed"]:
            return _reading("delete", {"count": len(plain)}, [], plain)
        return _reading("deleteSome", {})
    if program == "find":
        end = next((k for k, a in enumerate(args) if re.match(r"^[-(!)]", a)), -1)
        roots = args if end < 0 else args[:end]
        exe = next((k for k, a in enumerate(args) if re.match(r"^-(?:exec|execdir|ok|okdir)$", a)), -1)
        if "-delete" in args or (exe >= 0 and _base(args[exe + 1] if exe + 1 < len(args) else "") in _DELETERS):
            return _reading("findDelete", {"where": ", ".join(roots) or "."}, [], roots)
        return _reading("run", {"program": program}, [], roots)
    if program == "mv":
        return _reading("move", {"count": max(len(plain) - 1, 1)}, [], plain)
    if program == "cp":
        return _reading("copyLocal", {"count": max(len(plain) - 1, 1)}, [], plain)
    if program == "tee":
        return _reading("write", {"target": plain[0]}, [], plain) if plain else _run(program)
    if program == "git":
        own = [a for k, a in enumerate(args) if not re.match(r"^-[Cc]$", a)
               and not (k and re.match(r"^-[Cc]$", args[k - 1]))]
        sub, *rest = _plain(own) or [None]
        if sub == "push":
            return _reading("gitPush", {"remote": rest[0] if rest else "origin"})
        if sub == "clone" and rest:
            return _reading("gitClone", {"repo": rest[0]}, [rest[0]])
        if sub in ("pull", "fetch"):
            return _reading("gitFetch", {"remote": rest[0] if rest else "origin"})
        return _reading("git", {"sub": sub or ""})
    if program == "open":
        if not plain:
            return _run(program)
        target = plain[-1]
        url = bool(_URL_LIKE.match(target))
        return _reading("open", {"target": target}, [target] if url else [], [] if url else [target])
    if program == "osascript":
        return _reading("appleScript", {})
    if program == "shortcuts":
        if len(plain) > 1 and plain[0] == "run":
            return _reading("shortcut", {"name": plain[1]})
        return _run(program)
    if program in ("kill", "killall", "pkill"):
        return _reading("kill", {"target": " ".join(plain)})
    if program in ("mail", "mailx", "sendmail", "msmtp", "mutt"):
        to = next((a for a in plain if "@" in a), None)
        attached = [args[k + 1] for k, a in enumerate(args) if re.match(r"^(?:-a|-A|--attach)$", a) and k + 1 < len(args)]
        sent = _unique([*attached, *w["inputs"]])
        return _reading("mailTo", {"to": to}, [to], sent=sent) if to else _reading("mail", {}, [], sent)
    sub = plain[0] if plain else None
    if program in _INSTALLERS and sub in ("install", "add"):
        names = [n for n in plain[1:] if "/" not in n or n.startswith("@")]
        return _reading("install", {"packages": ", ".join(names[:3]) or program})
    if (program in _SCRIPT_RUNNERS and sub and not any(a in ("-c", "-e", "-m") for a in args)
            and not re.match(r"^(?:[<>$]\(|`)", sub)):
        return _reading("script", {"program": program, "file": _base(sub)}, [], [sub])
    # #688 review 6i: an unknown program's operands that look like paths are what it touches.
    return _reading("run", {"program": program}, [], [a for a in plain if _PATH_LIKE.match(a)])


def _rebase(folder: str | None, path: str) -> str:
    """`path` as seen from `folder` (a `cd` before it), unless it is absolute, from home, a variable or remote."""
    if not folder or re.match(r"^(?:/|~|\$)", path) or _URL_LIKE.match(path) or _REMOTE_PATH.match(path):
        return path
    out: list[str] = []
    for part in f"{folder.rstrip('/')}/{path}".split("/"):
        if part == "." or (part == "" and out):
            continue
        if part == ".." and out and out[-1] not in ("..", "~", ""):
            out.pop()
        else:
            out.append(part)
    return "/".join(out) or "/"


def _flatten(steps: list[dict], container: dict | None, out: list[dict]) -> None:
    prev = None
    for step in steps:
        node = {"w": _words(step["tokens"]), "from": prev if step["piped"] else None, "container": container,
                "merged": False, "run": False}
        line = _inline_line(node["w"])
        inner = None if line is None else _parse(line)
        if inner:
            _flatten(inner, container, out)                                # `sh -c '…'`: its line, read once
        else:
            _flatten(step["subs"], node, out)                              # what runs inside it runs first
            out.append(node)
        prev = node


def _read(text: str, rules: list[str]) -> dict | None:
    """The line read: its purpose, what it touches, and how many real steps it has."""
    steps = _parse(text)
    if steps is None:
        return None
    nodes: list[dict] = []
    _flatten(steps, None, nodes)
    # #688 review 6e: a download whose output a program runs as code is one step.
    for node in nodes:
        if node["w"]["program"] not in _FETCHERS:
            continue
        n = node
        while n is not None:
            nxt = next((m for m in nodes if m["from"] is n), None)
            if nxt is None:
                break
            if _reads_code(nxt["w"]):
                node["run"], nxt["merged"] = True, True
                break
            n = nxt
        host = node["container"]
        if host is not None and (host["w"]["program"] in _RUNS_CODE or re.match(r"^[$`]", host["w"]["program"])
                                 or host["w"]["program"] == ""):
            node["run"], host["merged"] = True, True
    folder, real, seen = None, [], {}                                     # seen: the files each step names or reads

    def fed(node: dict) -> list[str]:
        """What steps piped into it, or run inside it, read."""
        out = [p for n in nodes if n["container"] is node for p in seen.get(id(n), [])]
        n = node["from"]
        while n is not None:
            out.extend(seen.get(id(n), []))
            n = n["from"]
        return _unique(out)
    for node in nodes:
        w = node["w"]
        program, args, writes = w["program"], w["args"], w["writes"]
        if program in ("cd", "pushd"):
            to = next((a for a in args if a == "-" or not a.startswith("-")), "~")   # `cd -`: a folder not named
            folder = None if to == "-" else _rebase(folder, to)
            continue
        if program == "popd":
            folder = None
            continue
        quiet = program in QUIET or not program
        if node["merged"] or (quiet and not writes):
            seen[id(node)] = [_rebase(folder, p) for p in w["inputs"]]
            continue
        r = _reading("write", {"target": writes[0]}) if quiet else _step(w, rules)
        if node["run"] and r["purpose"]["key"] in ("fetch", "upload"):
            r["purpose"] = {"key": "fetchRun", "params": {"host": r["purpose"]["params"]["host"]}}
        r["local"] = [_rebase(folder, p) for p in [*r["local"], *writes]]
        if r["purpose"]["key"] == "write":
            r["purpose"] = {"key": "write", "params": {"target": _rebase(folder, str(r["purpose"]["params"]["target"]))}}
        # #688 review, the second round: an upload or an email says which file it sends (named on it, its input, or a
        # step piped into it or run inside it). The model picks the host; the file is the one tell.
        sent = [_rebase(folder, p) for p in r.get("sent", [])]
        key = r["purpose"]["key"]
        if key in ("upload", "mailTo"):
            sent = sent or fed(node)
            if sent:
                file, params = ", ".join(sent[:3]), r["purpose"]["params"]
                r["purpose"] = ({"key": "uploadFile", "params": {"file": file, "host": params["host"]}} if key == "upload"
                                else {"key": "mailFile", "params": {"file": file, "to": params["to"]}})
        r["local"] = _unique([*r["local"], *sent])
        seen[id(node)] = [*r["local"], *(_rebase(folder, p) for p in w["inputs"])]
        r.pop("sent", None)
        real.append(r)
    if not real:
        first = next((n["w"]["program"] for n in nodes if n["w"]["program"]), "")
        return {"purpose": {"key": "run", "params": {"program": first}}, "hosts": [], "local": [], "real": 0}
    lead = real[0]
    for r in real[1:]:
        if STAKES.get(r["purpose"]["key"], 1) > STAKES.get(lead["purpose"]["key"], 1):
            lead = r
    return {"purpose": lead["purpose"], "hosts": _unique(h for r in real for h in r["hosts"]),
            "local": _unique(p for r in real for p in r["local"]), "real": len(real)}


def summarize(text: str, rules: str | list[str] | None = None) -> dict:
    """What a shell line is for and what it touches: `{"purpose": {key, params[, inner]}, "touches": [...],
    "more": n}`, as web/src/lib/commandSummary.ts reads it (both are held to tests/fixtures/card_purpose_vectors.json).
    `rules`: the server's terminal rules for the line (one, or several)."""
    listed = [rules] if isinstance(rules, str) else list(rules or [])
    r = _read(text, listed)
    if r is None:
        return {"purpose": {"key": "run", "params": {"program": _base((text.strip().split() or [""])[0])}},
                "touches": [], "more": 0}
    outside = [p for p in r["local"] if re.match(r"^(?:/|~|\$|\.\.(?:/|$))", p) or _REMOTE_PATH.match(p)]
    return {"purpose": r["purpose"], "touches": _unique([*r["hosts"], *outside, *r["local"]]),
            "more": max(r["real"] - 1, 0)}


def _say(lang: str, group: str, key: str, params: dict) -> str:
    """One string of the table in `lang` (English when it has none), `{{name}}` filled, i18next's `_one` form when
    the count is 1."""
    table = TEXT.get(lang, TEXT["en"])[group]
    if params.get("count") == 1 and f"{key}_one" in table:
        key = f"{key}_one"
    text = table.get(key) or TEXT["en"][group][key]
    return re.sub(r"\{\{(\w+)\}\}", lambda m: str(params.get(m.group(1), "")), text)


def _purpose(lang: str, purpose: dict) -> str:
    """A purpose in `lang`: a step run on another machine says that step inside its own sentence."""
    params = dict(purpose["params"])
    if "inner" in purpose:
        params["what"] = _purpose(lang, purpose["inner"])
    return _say(lang, "purpose", purpose["key"], params)


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


def phrase(shell: str, why: str = "", rules: str | list[str] | None = None, *, lang: str = "en",
           outside: bool = False, unsandboxed: bool = False, host: str | None = None, shortcut_as_you: bool = False,
           network: bool = False) -> str:
    """The card's title in `lang`: first the code's facts, where it runs when that is not this Mac's sandbox and
    whether it uses the network, in a fixed form; then the code's reading of `shell`; then Arslan's reason when it
    gave one. The reason is cut first, then the reading, so the whole title fits the phone's heading (PHONE_MAX) and
    no fact is pushed off it (#689 review 1 and its second round). Cleaned as a name is, so neither the model's words
    nor the command's carry a bidi or zero-width character into the heading."""
    facts = []
    if shortcut_as_you:
        facts.append(_say(lang, "fact", "shortcutAsYou", {}))
    elif outside:
        facts.append(_say(lang, "fact", "outside", {}))
    elif unsandboxed:
        facts.append(_say(lang, "fact", "noSandbox", {}))
    if host:
        facts.append(_say(lang, "fact", "onHost", {"host": untrusted.clean_name(host, 80)}))
    if network:
        facts.append(_say(lang, "fact", "network", {}))
    join = _say(lang, "fact", "join", {})
    lead = untrusted.clean_name(join.join(facts), PHONE_MAX) if facts else ""
    s = summarize(shell, rules)
    reading = untrusted.clean_name(
        _purpose(lang, s["purpose"]) + (_say(lang, "purpose", "more", {"count": s["more"]}) if s["more"] else ""), TITLE_MAX)
    # The model's words never take the facts' form: a separator, or one that looks like it, is a comma in them.
    said = _SEPARATORS.sub(",", untrusted.clean_name(why, TITLE_MAX)) if why else ""
    room = PHONE_MAX - (len(lead) + len(join) if lead else 0)
    # #689 review, the second round: Arslan's words are never the only description, so the code's reading comes
    # before them; the reason is cut first, then the reading, never the facts.
    if said and room - len(reading) - len(join) >= 2:
        text = reading + join + _cut(said, room - len(reading) - len(join))
    else:
        text = _cut(reading, room)
    return f"{lead}{join}{text}" if lead else text


def _cut(text: str, room: int) -> str:
    return text if len(text) <= room else text[:max(room - 1, 0)].rstrip() + "\u2026"


async def title(shell: str, why: str = "", rules: str | list[str] | None = None, **where) -> str:
    """`phrase` in the user's language."""
    return phrase(shell, why, rules, lang=await language(), **where)
