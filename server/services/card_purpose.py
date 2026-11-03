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
STAKES = {"fetchRun": 10, "delete": 9, "deleteSome": 9, "findDelete": 9, "unreadableSend": 9, "mailTo": 8, "mail": 8,
          "mailFile": 8, "mailFileMore": 8, "upload": 8, "uploadFile": 8, "uploadFileMore": 8,
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
    """A web address's host, read the same way here and in commandSummary.ts (#688 review, Astra 9): ASCII only, as
    written, lowercased; an IPv6 host keeps its brackets. No IDN, no `%` escape, no `_`, no IPv4 shorthand (`127.1`),
    no port that is not a number: such a host is not read at all, so its transfer is not read either."""
    m = re.match(r"^[a-z][a-z0-9+.-]*://([^/?#]*)", text, re.I) or re.match(r"^([^/?#]*)", text)
    auth = m.group(1) if m else ""
    auth = auth[auth.rfind("@") + 1:]
    if auth.startswith("["):
        close = auth.find("]")
        if close < 0:
            return None
        host, port = auth[:close + 1], auth[close + 1:]
        if not re.match(r"^\[[0-9a-fA-F:.]+\]$", host):
            return None
    else:
        colon = auth.find(":")
        host, port = (auth, "") if colon < 0 else (auth[:colon], auth[colon:])
        if not re.match(r"^[A-Za-z0-9.-]+$", host) or host.startswith(".") or ".." in host:
            return None
        if re.match(r"^[0-9.]+$", host) and not (re.match(r"^[0-9]{1,3}(?:\.[0-9]{1,3}){3}$", host)
                                                  and all(int(n) <= 255 for n in host.split("."))):
            return None
    if port and not re.match(r"^:[0-9]{0,5}$", port):
        return None
    return host.lower()


def _reading(key: str, params: dict, hosts=(), local=(), inner: dict | None = None, sent=(), *, stdin: bool = False,
             stdin_unsure: bool = False, unsure: bool = False) -> dict:
    """`sent`: the files a step sends, named on it. `stdin`: it sends its input too (`@-`, a mail's body).
    `stdin_unsure`: given an input, what it sends is not read (ssh). `unsure`: the step was not fully read (Astra)."""
    purpose = {"key": key, "params": params}
    if inner is not None:
        purpose["inner"] = inner
    return {"purpose": purpose, "hosts": list(hosts), "local": list(local), "sent": list(sent), "stdin": stdin,
            "stdin_unsure": stdin_unsure, "unsure": unsure}


def _run(program: str) -> dict:
    return _reading("run", {"program": program})


def _unsure(program: str, hosts=(), local=(), **kw) -> dict:
    """A transfer the reader cannot fully read: said so, never read as a download or a plain run (#688 review)."""
    return _reading("unreadableSend", {"program": program}, hosts, local, unsure=True, **kw)


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


def _longs(valued: str, flags: str) -> dict:
    return {**{f"--{n}": True for n in valued.split()}, **{f"--{n}": False for n in flags.split()}}


def _parse_opts(args: list[str], spec: dict) -> tuple[bool, list[tuple[str, str]], list[str]]:
    """A command's options by its own table: `ok` is false when one is not in it (or lacks its value). Short options
    may be bundled (`-sd @f`); `stop`: options end at the first operand (BSD getopt, as ssh and scp parse them)."""
    opts, ops, ok, i = [], [], True, 0
    while i < len(args):
        a = args[i]
        if a == "--":
            ops.extend(args[i + 1:])
            break
        if spec.get("multi") and re.match(spec["multi"], a):
            opts.append((a, ""))
        elif a.startswith("--"):
            eq = a.find("=")
            name = a if eq < 0 else a[:eq]
            valued = spec["long"].get(name, spec["long"].get(re.sub(r"^--no-", "--", name)))
            if valued is None or (valued is False and eq >= 0):
                ok = False
            else:
                value = "" if not valued else a[eq + 1:] if eq >= 0 else (args[i + 1] if i + 1 < len(args) else None)
                if valued and eq < 0:
                    i += 1
                if value is None:
                    ok = False
                opts.append((name, value or ""))
        elif a.startswith("-") and len(a) > 1:
            for j in range(1, len(a)):
                c = a[j]
                if c in spec["valued"]:
                    if j + 1 < len(a):
                        value = a[j + 1:]
                    else:
                        i += 1
                        value = args[i] if i < len(args) else None
                    if value is None:
                        ok = False
                    opts.append((f"-{c}", value or ""))
                    break
                if c not in spec["flags"]:
                    ok = False
                    break
                opts.append((f"-{c}", ""))
        elif spec.get("stop"):
            ops.extend(args[i:])
            break
        else:
            ops.append(a)
        i += 1
    return ok, opts, ops


_CURL = {"valued": "AbcCdDeEFHKmoPQrtTuUwxXyYz", "flags": "sSLfkviIOJGNq012346gjlnRZBaMVhp#", "long": _longs(
    "data data-ascii data-binary data-raw data-urlencode json form form-string upload-file url header output "
    "user request referer user-agent cookie cookie-jar proxy proxy-user max-time connect-timeout retry retry-delay "
    "retry-max-time write-out cert key cacert capath cert-type key-type pass resolve connect-to limit-rate "
    "max-filesize range output-dir interface dns-servers oauth2-bearer unix-socket abstract-unix-socket proto "
    "proto-redir ciphers tls-max max-redirs continue-at dump-header time-cond keepalive-time expect100-timeout "
    "local-port speed-limit speed-time url-query aws-sigv4 netrc-file config variable trace trace-ascii stderr "
    "preproxy noproxy socks5 socks5-hostname socks4 socks4a parallel-max hsts alt-svc etag-save etag-compare",
    "silent show-error location location-trusted fail fail-with-body fail-early insecure verbose include head "
    "remote-name remote-name-all remote-header-name get buffer compressed http0.9 http1.0 http1.1 http2 "
    "http2-prior-knowledge http3 http3-only ipv4 ipv6 globoff progress-bar progress-meter create-dirs raw "
    "tcp-nodelay anyauth basic digest ntlm negotiate netrc netrc-optional post301 post302 post303 list-only append "
    "ssl ssl-reqd tlsv1 tlsv1.0 tlsv1.1 tlsv1.2 tlsv1.3 path-as-is parallel parallel-immediate retry-all-errors "
    "retry-connrefused keepalive sessionid disable styled-output version help manual junk-session-cookies "
    "remove-on-error skip-existing")}
_WGET = {"valued": "OoaPUtTwQelABDXIiR", "flags": "qvcNrkpmSbxH46LKEFdhV", "multi": r"^-n[vpcdH]$", "long": _longs(
    "output-document output-file append-output directory-prefix user-agent header post-data post-file "
    "body-data body-file method tries timeout user password http-user http-password wait limit-rate quota execute "
    "input-file config base referer load-cookies save-cookies ca-certificate certificate private-key level accept "
    "reject domains exclude-directories include-directories restrict-file-names progress bind-address ftp-user "
    "ftp-password read-timeout dns-timeout connect-timeout waitretry",
    "quiet verbose verbose continue timestamping recursive parent clobber convert-links page-requisites mirror "
    "server-response spider check-certificate background show-progress inet4-only inet6-only span-hosts relative "
    "backup-converted adjust-extension content-disposition trust-server-names cookies keep-session-cookies "
    "ignore-length auth-no-challenge https-only directories host-directories force-directories debug help version "
    "force-html random-wait cache proxy")}
_SSH = {"valued": "BbcDEeFIiJLlmOoPpQRSWw", "flags": "46AaCfGgKkMNnqsTtVvXxYy", "long": {}, "stop": True}
_SCP = {"valued": "cDFiJlOoPSX", "flags": "346ABCOpqRrTv", "long": {}, "stop": True}
_RSYNC = {"valued": "eBfTM", "flags": "avzrPhnucCdlLkKHpogDtSWxRqiIAXEbFm8O", "long": _longs(
    "rsh exclude include exclude-from include-from files-from filter port bwlimit timeout contimeout info "
    "debug chmod chown usermap groupmap backup-dir suffix temp-dir partial-dir compare-dest copy-dest link-dest "
    "log-file log-file-format out-format max-size min-size max-delete modify-window block-size remote-option "
    "rsync-path password-file iconv compress-level checksum-choice protocol sockopts address outbuf stop-after "
    "stop-at write-batch read-batch only-write-batch",
    "archive verbose compress recursive partial progress human-readable dry-run update checksum delete delete-after "
    "delete-before delete-during delete-delay delete-excluded stats itemize-changes links perms times group owner "
    "devices specials hard-links acls xattrs sparse one-file-system whole-file relative copy-links safe-links "
    "copy-dirlinks keep-dirlinks backup remove-source-files inplace append append-verify mkpath ignore-existing "
    "existing size-only quiet ignore-times omit-dir-times omit-link-times numeric-ids prune-empty-dirs force "
    "ignore-errors list-only motd 8-bit-output super fake-super executability crtimes atimes open-noatime "
    "cvs-exclude from0 protect-args secluded-args trust-sender copy-unsafe-links munge-links implied-dirs "
    "delay-updates fuzzy blocking-io")}
_MAILX = {"valued": "scbaAqrSuf", "flags": "nNvEdiIH", "long": {}}
_SENDMAIL = {"valued": "fFBNRVXaC", "flags": "iv", "multi": r"^-o[A-Za-z]+$", "long": {}}
#: Programs that reach another machine; a step of one is read only when every option and source is known.
_TALKERS = {"nc", "ncat", "netcat", "socat", "telnet", "ftp", "tftp", "lftp", "smbclient", "sftp"}
_CLOUD = {"aws", "gcloud", "gsutil", "gh", "az", "rclone", "s3cmd"}
_INLINE_CODE = {"python": r"^-[a-zA-Z]*c$", "python2": r"^-[a-zA-Z]*c$", "python3": r"^-[a-zA-Z]*c$",
                "node": r"^(?:-e|-p|--eval|--print)$", "perl": r"^-[a-zA-Z]*[eE]$", "ruby": r"^-[a-zA-Z]*e$",
                "php": r"^-r$", "bun": r"^(?:-e|--eval)$", "deno": r"^eval$"}
_NETWORK = _FETCHERS | _TALKERS | _CLOUD | {"ssh", "mosh", "autossh", "scp", "rsync", "mail", "mailx", "sendmail",
                                            "msmtp", "mutt"}


def _form_file(value: str) -> str | None:
    """The file a `-F name=@file` / `name=<file` field sends, curl's own quoting read (`=@"a;b.txt"`); "" for a field
    with no file; None when its quoting does not close."""
    m = re.match(r"^[^=]*=[@<]", value)
    if not m:
        return ""
    rest = value[m.end():]
    if not rest.startswith('"'):
        return rest.split(";")[0]
    out, i = "", 1
    while i < len(rest):
        if rest[i] == "\\" and i + 1 < len(rest):
            i += 1
            out += rest[i]
        elif rest[i] == '"':
            return out
        else:
            out += rest[i]
        i += 1
    return None


def _curl(w: dict, rules: list[str]) -> dict:
    ok, opts, ops = _parse_opts(w["args"], _CURL)
    files, sends, sure, stdin = [], False, ok, False

    def file(f):
        nonlocal stdin
        if f == "-":
            stdin = True
        elif f:
            files.append(f)
    urls = [v for n, v in opts if n == "--url"] + ops
    for name, value in opts:
        if name in ("-K", "--config", "--variable"):
            sure = False
        elif name in ("-d", "--data", "--data-ascii", "--data-binary", "--json"):
            sends = True
            if value.startswith("@"):
                file(value[1:])
        elif name in ("--data-raw", "--form-string"):
            sends = True
        elif name == "--data-urlencode":
            sends = True
            m = re.match(r"^[^=@]*@(.*)$", value)
            file(m.group(1) if m else "")
        elif name in ("-F", "--form"):
            sends = True
            f = _form_file(value)
            if f is None:
                sure = False
            else:
                file(f)
        elif name in ("-T", "--upload-file"):
            sends = True
            if re.search(r"[\[{]", value):
                sure = False
            else:
                file(value)
        elif name in ("-b", "--cookie"):
            if "=" not in value:                                           # a cookie file is sent
                file(value)
        elif name in ("-H", "--header") and value.startswith("@"):
            file(value[1:])
    hosts = [_host_of_url(u) for u in urls]
    if not urls and sure:
        return _run(w["program"])                                          # nothing goes out
    if not sure or not urls or not all(hosts):
        return _unsure(w["program"], urls, files, stdin=stdin)
    return _reading("upload" if sends or "upload" in rules else "fetch", {"host": hosts[0]}, urls, [], sent=files,
                    stdin=stdin)


def _wget(w: dict) -> dict:
    ok, opts, urls = _parse_opts(w["args"], _WGET)
    files, sends, sure = [], False, ok
    for name, value in opts:
        if name in ("-e", "--execute", "-i", "--input-file", "--config"):
            sure = False
        elif name in ("--post-file", "--body-file"):
            sends = True
            files.append(value)
        elif name in ("--post-data", "--body-data"):
            sends = True
        elif name == "--load-cookies":
            files.append(value)
    hosts = [_host_of_url(u) for u in urls]
    if not urls and sure:
        return _run(w["program"])
    if not sure or not urls or not all(hosts):
        return _unsure(w["program"], urls, files)
    return _reading("upload" if sends else "fetch", {"host": hosts[0]}, urls, [], sent=files)


def _httpie(w: dict) -> dict:
    """HTTPie (http, https, xh): read only as `http [GET|HEAD] <url>`; items and anything else may send local data."""
    ops = [a for a in w["args"] if not a.startswith("-")]
    flags = [a for a in w["args"] if a.startswith("-")]
    url = ops[0] if len(ops) == 1 else ops[1] if len(ops) == 2 and re.match(r"^(?:GET|HEAD)$", ops[0]) else None
    host = _host_of_url(url) if url else None
    if not host or any(not re.match(r"^(?:-v|-h|-b|--verbose|--headers|--body|--follow|-F|--check-status|--pretty=\w+)$", f)
                       for f in flags):
        return _unsure(w["program"], [a for a in ops if _host_of_url(a) is not None and re.search(r"[./:]", a)],
                       [a for a in ops if _PATH_LIKE.match(a)])
    return _reading("fetch", {"host": host}, [url], stdin_unsure=True)


def _ssh(program: str, args: list[str], rules: list[str]) -> dict:
    spec = {**_SSH, "valued": _SSH["valued"] + "M"} if program == "autossh" else _SSH
    ok, opts, ops = _parse_opts(args, spec)
    risky = any(n in ("-F", "-W") or (n == "-o" and re.match(
        r"^(?:ProxyCommand|LocalCommand|PermitLocalCommand|KnownHostsCommand)\b", v, re.I)) for n, v in opts)
    if not ops:
        return _run(program) if ok and not risky else _unsure(program)
    target = ops[0]
    host = target[target.rfind("@") + 1:]
    if not ok or risky or (program == "mosh" and opts):
        return _unsure(program, [host])
    timeout = next((int(m.group(1)) for n, v in opts if n == "-o" and (m := re.match(r"^ConnectTimeout=([0-9]+)$", v, re.I))),
                   0)
    remote = ops[1:]
    if remote[:1] == ["--"]:
        remote = remote[1:]
    # #688 review 6d: words after the host are a command that runs there, read as its own line.
    there = _read(" ".join(remote), rules) if remote else None
    if there and there["real"]:
        return _reading("onHost", {"host": host}, [host, *there["hosts"]], [f"{host}:{p}" for p in there["local"]],
                        inner=there["purpose"], stdin_unsure=True, unsure=there["unsure"])
    if timeout:
        return _reading("sshTimeout", {"host": host, "seconds": timeout}, [host], stdin_unsure=True)
    return _reading("ssh", {"host": host}, [host], stdin_unsure=True)


def _copy(w: dict) -> dict:
    """scp and rsync: the last operand is where it copies to. Local files sent to another machine are named."""
    rsync = w["program"] == "rsync"
    ok, opts, ops = _parse_opts(w["args"], _RSYNC if rsync else _SCP)
    shell = next((v for n, v in opts if n in ("-e", "--rsh")), None)
    risky = any(n in ("-F", "-S", "--files-from", "--read-batch") for n, _ in opts) or (
        shell is not None and not re.match(r"^ssh(?:\s|$)", shell))
    extra = [v for n, v in opts if n == "--password-file"]

    def remote(a):
        if re.match(r"^[a-z]+://", a, re.I):
            return _host_of_url(a) or ""
        m = _REMOTE.match(a)
        return m.group(1) if m else None
    hosts = _unique(h for a in ops if (h := remote(a)) is not None)
    if not ok or risky or len(ops) < 2 or "" in hosts:
        return _unsure(w["program"], [h for h in hosts if h], [*(a for a in ops if remote(a) is None), *extra])
    dest, sources = ops[-1], ops[:-1]
    local = [a for a in sources if remote(a) is None]
    if remote(dest) is not None and local:
        return _reading("upload", {"host": remote(dest)}, hosts, [], sent=[*local, *extra])
    if hosts:
        return _reading("copyRemote", {"host": hosts[0]}, hosts, [dest, *extra])
    return _reading("copyLocal", {"count": max(len(sources), 1)}, [], ops)


def _mail(w: dict) -> dict:
    program, args = w["program"], w["args"]
    if program == "mutt":
        sent, to, sure, i = [], [], True, 0
        while i < len(args):
            a = args[i]
            if a == "--":
                to.extend(args[i + 1:])
                break
            if a == "-a":
                while i + 1 < len(args) and not args[i + 1].startswith("-"):
                    i += 1
                    sent.append(args[i])
            elif a == "-i":
                if i + 1 < len(args):
                    i += 1
                    sent.append(args[i])
            elif a in ("-s", "-c", "-b"):
                i += 1
            elif re.match(r"^-[nxyNRpZz]+$", a):
                pass
            elif a.startswith("-"):
                sure = False
            else:
                to.append(a)
            i += 1
        if not sure or not to:
            return _unsure(program, to, sent, stdin=True)
        return _reading("mailTo", {"to": to[0]}, to, [], sent=sent, stdin=True)
    ok, opts, to = _parse_opts(args, _SENDMAIL if program in ("sendmail", "msmtp") else _MAILX)
    sent = [v for n, v in opts if n in ("-a", "-A", "-q")]
    if not ok or not to:
        return _unsure(program, to, sent, stdin=True)
    return _reading("mailTo", {"to": to[0]}, to, [], sent=sent, stdin=True)


def _step(w: dict, rules: list[str]) -> dict:
    """One step's purpose and what it touches: `hosts` (other machines, web and mail addresses) and `local` (paths on
    the machine it runs on). `rules`: the server's terminal rules for the line (upload, git-push…)."""
    program, args = w["program"], w["args"]
    plain = _plain(args)
    if program in ("ssh", "mosh", "autossh"):
        return _ssh(program, args, rules)
    if program in ("scp", "rsync"):
        return _copy(w)
    if program == "curl":
        return _curl(w, rules)
    if program == "wget":
        return _wget(w)
    if program in ("http", "https", "xh"):
        return _httpie(w)
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
        return _mail(w)
    if program in _TALKERS:
        target = plain[0] if plain else None
        return _unsure(program, [target] if target and _host_of_url(target) else [], [a for a in plain if _PATH_LIKE.match(a)])
    if program in _CLOUD:
        # Their options are not read: every operand that looks like a file may be what it sends.
        return _unsure(program, [a for a in plain if re.match(r"^[a-z0-9]+://", a, re.I)],
                       [a for a in plain if _PATH_LIKE.match(a) or re.match(r"^[^/:]+\.[A-Za-z0-9]{1,8}$", a)])
    if program in _INLINE_CODE and any(re.match(_INLINE_CODE[program], a) for a in args):
        return _unsure(program)                                            # its inline code may send anything
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
    real, seen = [], {}                                                    # seen: the files each step names or reads

    def inside(node):
        return _unique(p for n in nodes if n["container"] is node for p in seen.get(id(n), []))

    def piped(node):                                                       # what steps piped into it read
        out, n = [], node["from"]
        while n is not None:
            out.extend(seen.get(id(n), []))
            n = n["from"]
        return _unique(out)
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
        inputs = [_rebase(folder, p) for p in w["inputs"]]
        quiet = program in QUIET or not program
        if node["merged"] or (quiet and not writes):
            seen[id(node)] = inputs
            continue
        r = _reading("write", {"target": writes[0]}) if quiet else _step(w, rules)
        if node["run"] and r["purpose"]["key"] in ("fetch", "upload"):
            r["purpose"] = {"key": "fetchRun", "params": {"host": r["purpose"]["params"]["host"]}}
        local = [_rebase(folder, p) for p in [*r["local"], *writes]]
        if r["purpose"]["key"] == "write":
            r["purpose"] = {"key": "write", "params": {"target": _rebase(folder, str(r["purpose"]["params"]["target"]))}}
        # #688 review, the second round and Astra 6: what a step sends, every source together: the files named on it,
        # its input when it sends it (`@-`, a mail's body) and the steps piped into it, and what a step run inside a
        # network step reads (`-d "$(cat f)"`, a URL with `$(…)` in it). The model picks the host; the file is the tell.
        fed_in = [*inputs, *piped(node)]
        sent = _unique([*(_rebase(folder, p) for p in r["sent"]), *(fed_in if r["stdin"] else []),
                        *(inside(node) if program in _NETWORK else [])])
        if r["stdin_unsure"] and fed_in:                                   # ssh given an input: not read
            r = _unsure(program, r["hosts"], r["local"])
            sent = _unique([*sent, *fed_in])
        key = r["purpose"]["key"]
        if sent and key in ("fetch", "upload", "mailTo"):
            file, more = ", ".join(sent[:3]), len(sent) - 3
            mailing = key == "mailTo"
            params = {"file": file, "to": r["purpose"]["params"]["to"]} if mailing else \
                {"file": file, "host": r["purpose"]["params"]["host"]}
            r["purpose"] = {"key": ("mailFile" if mailing else "uploadFile") + ("More" if more > 0 else ""),
                            "params": {**params, "count": more} if more > 0 else params}
        elif sent and program in _NETWORK and not r["unsure"] and key != "fetchRun":
            r = _unsure(program, r["hosts"], r["local"])                   # a transfer that sends more than it says
        r["local"] = _unique([*local, *sent])
        seen[id(node)] = [*r["local"], *inputs]
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
    s = summarize(shell, rules)
    if s["unsure"] and s["purpose"]["key"] != "unreadableSend":     # Astra: a transfer it could not fully read
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
