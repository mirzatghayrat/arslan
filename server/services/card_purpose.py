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
            "builtin": "",
            "timeout": "ks", "xargs": "adEILnPs", "caffeinate": "tw", "stdbuf": ""}
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_FD_DUP = re.compile(r"^[0-9]*[<>]&(?:[0-9]+|-)$")
_OUT = re.compile(r"^(?:[0-9]*|&)>>?\|?$")
_OUT_ATTACHED = re.compile(r"^(?:[0-9]*|&)>>?\|?([^>&|].*)$")
_IN = re.compile(r"^[0-9]*<(?:<<?|>)?-?$")
_IN_ATTACHED = re.compile(r"^[0-9]*<{1,3}-?\S")
_NOT_A_FILE = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"}
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
STAKES = {"overNetwork": 9, "delete": 9, "deleteSome": 9, "findDelete": 9, "gitPush": 7, "kill": 6, "appleScript": 5,
          "shortcut": 5, "install": 5, "write": 4, "move": 4, "open": 3, "copyLocal": 3, "gitClone": 3, "gitFetch": 2,
          "script": 2}


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
            opens = nxt == "(" and text[i + 2:i + 3] != "(" and (
                ch == "$" or (not quote and (ch in "<>" or (ch == "=" and not in_token))))
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
    i, listed, assigns = 0, False, []
    raw = _program_of(next((tk for tk in rest if not _ASSIGNMENT.match(tk)), ""))
    while True:
        while i < len(rest) and _ASSIGNMENT.match(rest[i]):
            assigns.append(rest[i].split("=", 1)[0])
            i += 1
        name = _base(rest[i]) if i < len(rest) else ""
        if name not in WRAPPERS:
            break
        # `env -S "…"` runs the string as a command line; keep env so _inline_line reads it (Astra r2, 1).
        if name == "env" and (rest[i + 1] if i + 1 < len(rest) else "") in ("-S", "--split-string"):
            break
        if name == "command" and re.match(r"^-[vV]$", rest[i + 1] if i + 1 < len(rest) else ""):
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
            "inputs": inputs, "assigns": assigns, "raw": raw, "listed": listed}


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
    if w["program"] == "eval":
        return " ".join(w["args"]) if w["args"] else None
    if w["program"] == "trap" and w["args"] and w["args"][0] != "-":
        return w["args"][0]
    if w["program"] == "env":
        at = next((k for k, a in enumerate(w["args"]) if a in ("-S", "--split-string")), -1)
        if at >= 0:
            return w["args"][at + 1] if at + 1 < len(w["args"]) else None
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


def _reading(key: str, params: dict, hosts=(), local=(), inner: dict | None = None, *, unsure: bool = False) -> dict:
    purpose = {"key": key, "params": params}
    if inner is not None:
        purpose["inner"] = inner
    return {"purpose": purpose, "hosts": list(hosts), "local": list(local), "unsure": unsure}


def _run(program: str) -> dict:
    return _reading("run", {"program": program})


def _over_network(program: str) -> dict:
    """SMART-8 (#688/#689 reviews, Astra's two rounds; the user asked for the simpler version): a step that reaches another machine is
    read only as a fixed line — no host, no file — because what it sends cannot be told from the command. `unsure` is
    set, so the risk row and the card say so, and the Mac card shows the whole command."""
    return _reading("overNetwork", {"program": program}, unsure=True)


#: Programs that reach another machine; a step of one is never read past "uses the network".
_NETWORK = {"curl", "wget", "http", "https", "xh", "nc", "ncat", "netcat", "socat", "telnet", "ftp", "tftp", "lftp",
            "smbclient", "sftp", "ssh", "mosh", "autossh", "scp", "rsync", "mail", "mailx", "sendmail", "msmtp",
            "mutt", "aws", "gcloud", "gsutil", "gh", "az", "rclone", "s3cmd", "dig", "nslookup", "host", "ping",
            "traceroute", "openssl", "ssh-copy-id", "docker", "podman", "kubectl", "twine", "azcopy"}
#: Interpreters whose inline code (`-c`, `-e`, `--eval` in any attached form) could reach the network (Astra 7).
_INLINE_CODE = {"python": r"^-[A-Za-z]*c", "python2": r"^-[A-Za-z]*c", "python3": r"^-[A-Za-z]*c",
                "node": r"^(?:-[A-Za-z]*[ep]|--eval|--print)", "perl": r"^-[A-Za-z]*[eE]", "ruby": r"^-[A-Za-z]*e",
                "php": r"^-[A-Za-z]*r", "bun": r"^(?:-e|--eval)", "deno": r"^eval$"}


_NAMES_ONLY = {"echo", "printf", "grep", "egrep", "fgrep", "rg", "man", "which", "type", "whence", "apropos"}


def _names_only(w: dict) -> bool:
    """A step whose own program only names things (`grep curl`, `command -v curl`) does not run its arguments."""
    program, args = w["program"], w["args"]
    if program in _NAMES_ONLY:
        return True
    if program == "command" and re.match(r"^-[vV]$", args[0] if args else ""):
        return True
    if program == "brew" and (args[0] if args else "") in ("info", "search"):
        return True
    return False


#: Common commands whose operands are files or data, never programs — their reading is kept, not scanned (Astra r2).
_BENIGN_LOCAL = {"ls", "touch", "chmod", "chown", "chgrp", "mkdir", "ln", "tar", "stat", "file", "head", "tail", "wc",
                 "sort", "uniq", "cut", "du", "basename", "dirname", "realpath", "readlink", "cmp", "diff", "nl", "tac",
                 "rev", "vim", "vi", "nano", "emacs", "code", "subl", "pico", "ed", "vimdiff", "mate"}
#: A benign command's option that makes it run another program (tar's compressor, an editor's command): the step may
#: run anything, so it reads overNetwork; the value is not parsed (Astra r2 delta).
_BENIGN_EXEC = {"tar": r"^(?:-I|(?:--use-compress-program|--to-command)(?:=|$))",
                "vim": r"^(?:-c|--cmd|\+)", "vi": r"^(?:-c|--cmd|\+)", "vimdiff": r"^(?:-c|--cmd|\+)",
                "emacs": r"^--eval(?:=|$)", "sort": r"^--compress-program(?:=|$)", "ed": r"^!"}


def _requote(tok: str) -> str:
    """Re-quote a token so a slice of tokens can be read as a command line again (for `find -exec`): a word with a
    space or other shell metacharacter is single-quoted; a plain word is left as is (Astra r2 delta³)."""
    return tok if re.match(r"^[A-Za-z0-9_@%^:=+,./~-]+$", tok) else "'" + tok.replace("'", "'\\''") + "'"


def _buried_network(w: dict) -> str | None:
    """The network program a step runs, wherever it sits (a wrapper option not modeled, `find -exec`, a compound);
    each token is matched by its basename, lower-cased, so `Curl` is caught too (Astra r2, F1/F2). A path or URL
    operand is not a program."""
    toks = [w["program"], *w["args"]]
    for i, tok in enumerate(toks):
        if i > 0 and ("/" in tok or _URL_LIKE.match(tok)):
            continue
        name = _base(tok).lower()
        if name in _NETWORK:
            return name
        if name in _INLINE_CODE and i + 1 < len(toks) and re.match(_INLINE_CODE[name], toks[i + 1]):
            return name
    return None


def _step(w: dict) -> dict:
    """One step's purpose and what it touches. A step that reaches another machine is read only as overNetwork."""
    program = w["program"].lower()                                         # the binary a case-insensitive volume runs
    args = w["args"]
    plain = _plain(args)
    if not program:
        return _over_network(w.get("raw") or "command")                   # a wrapper took everything (Astra r2, 1)
    if program in _NETWORK:
        return _over_network(program)                                      # the program itself reaches the network
    if program in _INLINE_CODE and any(re.match(_INLINE_CODE[program], a) for a in args):
        return _over_network(program)
    if program == "cat":
        return _reading("run", {"program": program}, [], plain)
    if program in _DELETERS:
        if plain or not w["listed"]:
            return _reading("delete", {"count": len(plain)}, [], plain)
        return _reading("deleteSome", {})
    if program == "find":
        end = next((k for k, a in enumerate(args) if re.match(r"^[-(!)]", a)), -1)
        roots = args if end < 0 else args[:end]
        # Every -exec/-execdir/-ok/-okdir action (up to its ;/+) is a command find runs; read each as its own line so
        # a wrapper, a shell, a second action or an interpreter flag anywhere in it is caught (Astra r2 delta³).
        deletes = "-delete" in args
        for i, a in enumerate(args):
            if not re.match(r"^-(?:exec|execdir|ok|okdir)$", a):
                continue
            slice_: list[str] = []
            j = i + 1
            while j < len(args) and args[j] not in (";", "+"):
                slice_.append(args[j])
                j += 1
            if not slice_:
                continue
            r = _read(" ".join(_requote(t) for t in slice_), [])
            if r and r["unsure"]:
                return _over_network(str(r["purpose"]["params"].get("program") or program))
            if r and r["purpose"]["key"] in ("delete", "deleteSome", "findDelete"):
                deletes = True
        if deletes:
            return _reading("findDelete", {"where": ", ".join(roots) or "."}, [], roots)
        return _reading("run", {"program": program}, [], roots)
    if program == "mv":
        return _reading("move", {"count": max(len(plain) - 1, 1)}, [], plain)
    if program == "cp":
        return _reading("copyLocal", {"count": max(len(plain) - 1, 1)}, [], plain)
    if program == "tee":
        return _reading("write", {"target": plain[0]}, [], plain) if plain else _run(program)
    if program == "git":
        if (any(re.match(r"^-c$", a) or re.match(r"^--(?:config|upload-pack|receive-pack)(?:=|$)", a) for a in args)
                or any(re.match(r"^GIT_(?:SSH|SSH_COMMAND|PROXY_COMMAND)$", v) for v in w.get("assigns", []))):
            return _over_network("git")                                    # -c / hooks can run any program (Astra r2, 3)
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
    if program in _BENIGN_EXEC and any(re.match(_BENIGN_EXEC[program], a) for a in args):
        return _over_network(program)                                      # an option that runs another program
    sub = plain[0] if plain else None
    if (program in ("npm", "pnpm", "yarn", "cargo") and sub == "publish") or (program == "gem" and sub == "push"):
        return _over_network(program)                                      # uploads to a registry
    if program in _INSTALLERS and sub in ("install", "add"):
        names = [n for n in plain[1:] if "/" not in n or n.startswith("@")]
        return _reading("install", {"packages": ", ".join(names[:3]) or program})
    if (program in _SCRIPT_RUNNERS and sub and not any(a in ("-c", "-e", "-m") for a in args)
            and not re.match(r"^(?:[<>$]\(|`)", sub)):
        return _reading("script", {"program": program, "file": _base(sub)}, [], [sub])
    # Astra r2: scan only an unknown program — a launcher, a compound, a function body, a keyword — for a network
    # program it runs. A names-only step and the file-reading commands in _BENIGN_LOCAL keep their reading.
    if not _names_only(w) and program not in _BENIGN_LOCAL:
        buried = _buried_network(w)
        if buried:
            return _over_network(buried)
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


def _flatten(steps: list[dict], container: dict | None, out: list[dict], ctx: dict) -> None:
    """`ctx`: the shell a step runs in; a `$(…)` or `sh -c '…'` starts its own, so a `cd` inside it stays there."""
    prev = None
    for step in steps:
        node = {"w": _words(step["tokens"]), "from": prev if step["piped"] else None, "container": container,
                "merged": False, "run": False, "ctx": ctx}
        line = _inline_line(node["w"])
        inner = None if line is None else _parse(line)
        if inner:
            _flatten(inner, container, out, {"parent": ctx})              # `sh -c '…'`: its line, read once
        else:
            _flatten(step["subs"], node, out, {"parent": ctx})            # what runs inside it runs first
            out.append(node)
        prev = node


def _read(text: str, rules: list[str]) -> dict | None:
    """The line read: its purpose, what it touches, how many real steps it has, and whether a transfer in it was not
    fully read (`unsure`)."""
    steps = _parse(text)
    if steps is None:
        return None
    nodes: list[dict] = []
    _flatten(steps, None, nodes, {"parent": None})
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
    dirs: dict[int, str | None] = {}

    def dir_of(ctx):
        if ctx is None:
            return None
        return dirs[id(ctx)] if id(ctx) in dirs else dir_of(ctx["parent"])
    real = []
    for node in nodes:
        w = node["w"]
        program, args, writes = w["program"], w["args"], w["writes"]
        folder = dir_of(node["ctx"])
        if program in ("cd", "pushd"):
            to = next((a for a in args if a == "-" or not a.startswith("-")), "~")   # `cd -`: a folder not named
            dirs[id(node["ctx"])] = None if to == "-" else _rebase(folder, to)
            continue
        if program == "popd":
            dirs[id(node["ctx"])] = None
            continue
        wrapped = not program and w.get("raw", "") in WRAPPERS         # `sudo`, `timeout 5` alone (Astra r2, 1)
        quiet = program in QUIET or (not program and not wrapped)
        if node["merged"] or (quiet and not writes):
            continue
        r = _reading("write", {"target": writes[0]}) if quiet else _step(w)
        local = _unique([_rebase(folder, p) for p in [*r["local"], *writes]])
        if r["purpose"]["key"] == "write":
            r["purpose"] = {"key": "write", "params": {"target": _rebase(folder, str(r["purpose"]["params"]["target"]))}}
        r["local"] = local
        real.append(r)
    if not real:
        first = next((n["w"]["program"] for n in nodes if n["w"]["program"]), "")
        return {"purpose": {"key": "run", "params": {"program": first}}, "hosts": [], "local": [], "real": 0,
                "unsure": False}
    lead = real[0]
    for r in real[1:]:
        if STAKES.get(r["purpose"]["key"], 1) > STAKES.get(lead["purpose"]["key"], 1):
            lead = r
    return {"purpose": lead["purpose"], "hosts": _unique(h for r in real for h in r["hosts"]),
            "local": _unique(p for r in real for p in r["local"]), "real": len(real),
            "unsure": any(r["unsure"] for r in real)}


def summarize(text: str, rules: str | list[str] | None = None) -> dict:
    """What a shell line is for and what it touches: `{"purpose": {key, params[, inner]}, "touches": [...], "more": n,
    "unsure": bool}`, as web/src/lib/commandSummary.ts reads it (both are held to
    tests/fixtures/card_purpose_vectors.json). `unsure`: a transfer in it was not fully read, so it may send local
    data. `rules`: the server's terminal rules for the line (one, or several)."""
    listed = [rules] if isinstance(rules, str) else list(rules or [])
    r = _read(text, listed)
    if r is None:
        return {"purpose": {"key": "run", "params": {"program": _base((text.strip().split() or [""])[0])}},
                "touches": [], "more": 0, "unsure": False}
    outside = [p for p in r["local"] if re.match(r"^(?:/|~|\$|\.\.(?:/|$))", p) or _REMOTE_PATH.match(p)]
    return {"purpose": r["purpose"], "touches": _unique([*r["hosts"], *outside, *r["local"]]),
            "more": max(r["real"] - 1, 0), "unsure": r["unsure"]}


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
    s = summarize(shell, rules)
    on_network = s["purpose"]["key"] == "overNetwork"              # the reading already says it uses the network
    if shortcut_as_you:
        facts.append(_say(lang, "fact", "shortcutAsYou", {}))
    elif outside:
        facts.append(_say(lang, "fact", "outside", {}))
    elif unsandboxed:
        facts.append(_say(lang, "fact", "noSandbox", {}))
    if host:
        facts.append(_say(lang, "fact", "onHost", {"host": untrusted.clean_name(host, 80)}))
    if network and not on_network:
        facts.append(_say(lang, "fact", "network", {}))
    if s["unsure"] and not on_network:                            # a step behind the lead uses the network
        facts.append(_say(lang, "fact", "unsure", {}))
    join = _say(lang, "fact", "join", {})
    lead = untrusted.clean_name(join.join(facts), PHONE_MAX) if facts else ""
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
