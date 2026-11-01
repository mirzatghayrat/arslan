"""A secret typed into a connection's address or command arguments (v0.1.64 SEC1, docs/plans/0164/CAPX-followups.md).

`env` is encrypted at rest and masked on read, but a token in a URL's query, a password in its userinfo or a key
after a command-line flag was stored and shown as typed. Moving one into `env` would not work: for an HTTP
connection `env` is its header map, so the secret would also go out as a header, and a server that reads a query
token or a flag would not find it. So a moved secret leaves a `${NAME}` placeholder where it was, its value goes
into its own encrypted column (`mcp_servers.secrets`, migration 0081), and `fill` puts it back when the connection
starts (`discovery.runtime_dict`), the way Claude Code expands `${VAR}` in its MCP config. Nothing moves without
being asked; the click that asks is the card's (SEC1b, behind its mock).

- `find`: the secret-looking parts of an address and its arguments, by where they are, never their values. A part
  is `{"where": "url"|"arg", "index": the argument, "at": "password"|"user"|"path"|"query"|"header", "key", "n"}`.
- `move`: one part out, a placeholder in. `fill`: the placeholders back to values. `shown`: an address and
  arguments with every secret-looking part masked, for every place that shows them. `missing`: the placeholders
  with no stored value.
All three work on the raw text by position (`_spans`), so a moved value is stored as written and `fill` gives the
original back byte for byte (#536 review).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from urllib.parse import unquote, unquote_plus

PLACEHOLDER = re.compile(r"\$\{([A-Z][A-Z0-9_]{0,63})\}")
#: The last word of a query key, flag, `NAME=` or header name that names a secret. Matched as a word, never as a
#: substring (#536 review 5: `--max-tokens 1000` and `--keyboard` are not secrets; `--token-limit` neither).
_SECRET_LAST = frozenset({"token", "secret", "password", "passwd", "pwd", "key", "apikey", "auth", "authorization",
                          "credential", "credentials", "signature", "sig", "bearer", "pat", "authtoken", "accesstoken",
                          "apitoken", "secretkey", "privatekey", "accesskey", "sessiontoken", "clientsecret"})
#: Values that name a kind of credential, or none, rather than being one.
_NOT_A_SECRET = frozenset({"true", "false", "yes", "no", "none", "null", "oauth", "basic", "bearer", "token", "env"})
_FLAG = re.compile(r"--?([A-Za-z][A-Za-z0-9_-]*)(?:=(.*))?$", re.S)
#: Any other `--name=value`, such as npm's own `--//registry.npmjs.org/:_authToken=…` (#623 re-check R-7).
_OPTION = re.compile(r"--([^=\s]+)=(.*)$", re.S)
_HEADER_FLAGS = frozenset({"header", "headers", "h"})
#: `Name: value`, a scheme word (`Bearer`, `Basic`, `token`) before the value left in place.
_HEADER = re.compile(r"\s*([A-Za-z0-9_-]+)\s*:\s*(?:(?:bearer|basic|token)\s+)?(.*?)\s*", re.I | re.S)
_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")
_MASK = "●●●●"


class NothingToMove(ValueError):
    """The part asked for is not there, holds no secret, or holds a placeholder already."""


def _random_looking(value: str) -> bool:
    """A long value that reads like a key, not a word: 24 or more characters of a token alphabet, with letters
    and digits both, and more than 3.5 bits of entropy per character."""
    if len(value) < 24 or not re.fullmatch(r"[A-Za-z0-9_\-.~+/=]+", value):
        return False
    if not (re.search(r"[A-Za-z]", value) and re.search(r"[0-9]", value)):
        return False
    counts = Counter(value)
    return -sum(n / len(value) * math.log2(n / len(value)) for n in counts.values()) > 3.5


def _names_secret(key) -> bool:
    words = [w.lower() for w in re.split(r"[^A-Za-z0-9]+", re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(key or ""))) if w]
    return bool(words) and words[-1] in _SECRET_LAST


def _secret_value(key, value: str) -> bool:
    if not value or PLACEHOLDER.search(value) or value.lower() in _NOT_A_SECRET:
        return False
    return _names_secret(key) or _random_looking(value)


def _url_spans(text: str) -> list[tuple[dict, int, int]]:
    """The secret-looking spans of one URL, over its raw text (never decoded and encoded again, so `move` and
    `fill` give back the URL byte for byte: percent-encoding, `%40` in a user name, IPv6 brackets, a bad port;
    #536 review 2 and 3): the password; a user name that reads like a key; a path segment that does; a query
    value whose key names a secret or that reads like a key."""
    m = _URL.match(text)
    if not m:
        return []
    out: list[tuple[dict, int, int]] = []
    start = m.end()
    end = min([i for i in (text.find(c, start) for c in "/?#") if i != -1] or [len(text)])
    at = text.rfind("@", start, end)
    if at != -1:
        user, colon, password = text[start:at].partition(":")
        if colon and password and not PLACEHOLDER.search(password):
            out.append(({"at": "password"}, start + len(user) + 1, at))
        elif not colon and _random_looking(unquote(user)):
            out.append(({"at": "user"}, start, start + len(user)))
    hash_at = text.find("#", end)
    query_at = text.find("?", end, hash_at if hash_at != -1 else len(text))
    path_end = min([i for i in (query_at, hash_at) if i != -1] or [len(text)])
    pos = end
    for n, segment in enumerate(text[end:path_end].split("/")):
        if segment and not PLACEHOLDER.search(segment) and _random_looking(unquote(segment)):
            out.append(({"at": "path", "n": n}, pos, pos + len(segment)))
        pos += len(segment) + 1
    if query_at != -1:
        out += _pairs(text, query_at + 1, hash_at if hash_at != -1 else len(text), "query")
    if hash_at != -1 and "=" in text[hash_at + 1:]:            # #628 review L-1: `#access_token=…`, `#token=…`
        out += _pairs(text, hash_at + 1, len(text), "fragment")
    return out


def _pairs(text: str, start: int, stop: int, at: str) -> list[tuple[dict, int, int]]:
    """The `key=value&…` pairs of a query or a fragment: a value whose key names a secret, or that reads like a key."""
    out: list[tuple[dict, int, int]] = []
    pos, seen = start, Counter()
    for piece in text[start:stop].split("&"):
        key_raw, eq, value_raw = piece.partition("=")
        key = unquote_plus(key_raw)
        n, seen[key] = seen[key], seen[key] + 1
        if eq and _secret_value(key, unquote_plus(value_raw)):
            value_at = pos + len(key_raw) + 1
            out.append(({"at": at, "key": key, "n": n}, value_at, value_at + len(value_raw)))
        pos += len(piece) + 1
    return out


def _header_span(text: str, offset: int) -> list[tuple[dict, int, int]]:
    """`Authorization: Bearer <token>` (mcp-remote's `--header`): the value after the scheme word."""
    m = _HEADER.fullmatch(text)
    if m and m.group(2) and not PLACEHOLDER.search(m.group(2)) and (
            _names_secret(m.group(1)) or _random_looking(m.group(2))) and m.group(2).lower() not in _NOT_A_SECRET:
        return [({"at": "header", "key": m.group(1).lower()}, offset + m.start(2), offset + m.end(2))]
    return []


def _option_spans(name: str, value: str, value_at: int) -> list[tuple[dict, int, int]]:
    """`--name=value` or `NAME=value`: the whole value when the name names a secret or the value reads like a key;
    else, when the value holds an address (`--index-url=https://user:token@host/simple`, uv's `corp=https://…`), its
    secret-looking parts, as in an argument that is one (#623 re-check R-7)."""
    if _secret_value(name, value):
        return [({"key": name.lower()}, value_at, value_at + len(value))]
    return _address_spans(value, value_at)


def _address_spans(text: str, offset: int) -> list[tuple[dict, int, int]]:
    """The secret-looking parts of an address that starts anywhere in `text`, read from its scheme (#628 review
    L-2: `corp=https://…`, `name@https://…`), at their place in the argument."""
    m = _URL.search(text)
    if not m:
        return []
    at = offset + m.start()
    return [(part, at + start, at + end) for part, start, end in _url_spans(text[m.start():])]


def _spans(url: str | None, args) -> list[tuple[dict, int | None, int, int]]:
    """Every secret-looking part, as (part, where it is: None for the address or an argument's index, start,
    end). One list that `find`, `move` and `shown` all read, so they always agree."""
    out = [({"where": "url", **part}, None, s, e) for part, s, e in _url_spans(url or "")]
    args = [str(arg) for arg in (args or ())]
    for i, arg in enumerate(args):
        flag = _FLAG.match(arg)
        prev = _FLAG.match(args[i - 1]) if i else None
        found: list[tuple[dict, int, int]] = []
        if _URL.match(arg):                                                 # mcp-remote https://…?token=…
            found = _url_spans(arg)
        elif flag and flag.group(2) is not None:              # --token=VALUE, --header=…, --index-url=https://…
            value_at = arg.index("=") + 1
            if flag.group(1).lower() in _HEADER_FLAGS:
                found = _header_span(flag.group(2), value_at)
            else:
                found = _option_spans(flag.group(1), flag.group(2), value_at)
        elif flag:
            continue
        elif prev and prev.group(2) is None and prev.group(1).lower() in _HEADER_FLAGS:   # --header "Name: v"
            found = _header_span(arg, 0)
        elif prev and prev.group(2) is None and _secret_value(prev.group(1), arg):         # --api-key VALUE
            found = [({"key": prev.group(1).lower()}, 0, len(arg))]        # #628 review I-1: before an option
        elif option := _OPTION.match(arg):                   # --//registry.npmjs.org/:_authToken=…
            found = _option_spans(option.group(1), option.group(2), arg.index("=") + 1)
        elif "=" in arg and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", arg.partition("=")[0]):  # NAME=VALUE
            name, _, value = arg.partition("=")
            found = _option_spans(name, value, len(name) + 1)
        elif _URL.search(arg):                               # name@https://…, an address after a name
            found = _address_spans(arg, 0)
        elif _random_looking(arg) and not PLACEHOLDER.search(arg):
            found = [({}, 0, len(arg))]
        out += [({"where": "arg", "index": i, **part}, i, s, e) for part, s, e in found]
    return out


def find(url: str | None, args) -> list[dict]:
    """The secret-looking parts of an address and its arguments, by where they are, never their values. Pure
    string work: it never raises, so finding never blocks an add or a list (the user's D3)."""
    return [part for part, *_ in _spans(url, args)]


def missing(url: str | None, args, values: dict) -> list[str]:
    """The placeholders with no stored value, by name (#536 review: the start sent `${NAME}` as text, and
    nothing named it)."""
    text = " ".join([url or "", *[str(arg) for arg in (args or ())]])
    return sorted({m.group(1) for m in PLACEHOLDER.finditer(text)} - set(values or {}))


def suggest_name(label: str | None, part: dict) -> str:
    """`NOTES_TOKEN`: the connection's name and the part's key, upper case, letters, digits and `_` only."""
    words = [w for w in re.split(r"[^A-Za-z0-9]+", f"{label or ''} {part.get('key') or ''}") if w]
    if part.get("at") in ("password", "user"):
        words.append(part["at"])
    elif not part.get("key"):
        words.append("secret")
    name = "_".join(words).upper() or "CONNECTION_SECRET"
    name = name if name[0].isalpha() else "CONNECTION_" + name
    return (name if label and re.search(r"[A-Za-z0-9]", label) else "CONNECTION_" + name)[:64]


def _position(part: dict) -> tuple:
    return tuple(part.get(field) for field in ("where", "index", "at", "key")) + (part.get("n") or 0,)


def _check_name(name: str) -> None:
    if not PLACEHOLDER.fullmatch("${" + str(name) + "}"):
        raise NothingToMove("a name is upper-case letters, digits and _, starting with a letter")


def _replace(url: str | None, args: list[str], target: int | None, start: int, end: int, text: str):
    if target is None:
        return url[:start] + text + url[end:], args
    args = list(args)
    args[target] = args[target][:start] + text + args[target][end:]
    return url, args


def move(url: str | None, args, part: dict, name: str, values: dict) -> tuple[str | None, list[str], dict]:
    """`part` out of the address or arguments, `${name}` in its place; its text, exactly as written, goes into a
    copy of `values` under `name`."""
    _check_name(name)
    args, values = [str(arg) for arg in (args or ())], dict(values)
    spans = {_position(found): (target, s, e) for found, target, s, e in _spans(url, args)}
    if _position(part) not in spans:
        raise NothingToMove("nothing to move there")
    if name in values:
        raise NothingToMove(f"the name {name} is taken")
    target, start, end = spans[_position(part)]
    values[name] = (url if target is None else args[target])[start:end]
    url, args = _replace(url, args, target, start, end, "${" + name + "}")
    return url, args, values


def fill(url: str | None, args, values: dict) -> tuple[str | None, list[str]]:
    """The placeholders back to their values; one with no value is left as written (`missing` names it). A value
    is never read again for placeholders (no recursion)."""
    def sub(text: str) -> str:
        return PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), text)
    return (sub(url) if url else url), [sub(str(arg)) for arg in (args or ())]


def shown(url: str | None, args) -> tuple[str | None, list[str]]:
    """An address and arguments as every place may show them: each secret-looking part masked, nothing else
    changed (never re-encoded, never raising)."""
    args = [str(arg) for arg in (args or ())]
    for _, target, start, end in sorted(_spans(url, args), key=lambda span: span[2], reverse=True):
        url, args = _replace(url, args, target, start, end, _MASK)
    return url, args
