"""A secret typed into a connection's address or command arguments (v0.1.64 SEC1, docs/plans/0164/CAPX-followups.md).

`env` is encrypted at rest and masked on read, but a token in a URL's query, a password in its userinfo or a key
after a command-line flag was stored and shown as typed. Moving one into `env` would not work: for an HTTP
connection `env` is its header map, so the secret would also go out as a header, and a server that reads a query
token or a flag would not find it. So a moved secret leaves a `${NAME}` placeholder where it was, its value goes
into its own encrypted column (`mcp_servers.secrets`, migration 0081), and `fill` puts it back when the connection
starts (`discovery.runtime_dict`), the way Claude Code expands `${VAR}` in its MCP config. Nothing moves without
being asked; the click that asks is the card's (SEC1b, behind its mock).

- `find`: the secret-looking parts of an address and its arguments, by where they are, never their values.
- `move`: one part out, a placeholder in. `fill`: the placeholders back to values. `shown`: an address and
  arguments with every secret-looking part masked, for every place that shows them.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

PLACEHOLDER = re.compile(r"\$\{([A-Z][A-Z0-9_]{0,63})\}")
#: A query key or flag that names a secret.
_SECRET_WORDS = re.compile(r"token|secret|password|passwd|pwd|api[_-]?key|apikey|access[_-]?key|auth|credential"
                           r"|signature|sig|private[_-]?key|session|key", re.I)
#: The value of a flag that takes none of these is never taken for a secret by its name alone.
_FLAG = re.compile(r"--?([A-Za-z][A-Za-z0-9_-]*)(?:=(.*))?$")
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


def _secret_value(key: str, value: str) -> bool:
    return bool(value) and not PLACEHOLDER.fullmatch(value) and (bool(_SECRET_WORDS.search(key))
                                                              or _random_looking(value))


def find(url: str | None, args) -> list[dict]:
    """The secret-looking parts: a URL's password, a query value whose key names a secret (or that reads like a
    key), a flag's value whose flag names one (`--api-key VALUE`, `--token=VALUE`), a `NAME=VALUE` argument
    whose name does, and any argument that reads like a key. Positions only; a placeholder is not a secret."""
    parts: list[dict] = []
    if url:
        try:
            split = urlsplit(url)
            password = split.password
        except ValueError:
            split, password = None, None
        if password and not PLACEHOLDER.fullmatch(password):
            parts.append({"where": "password"})
        if split is not None:
            for key, value in parse_qsl(split.query, keep_blank_values=True):
                if _secret_value(key, value):
                    parts.append({"where": "query", "key": key})
    args = [str(arg) for arg in (args or ())]
    for i, arg in enumerate(args):
        flag = _FLAG.match(arg)
        prev = _FLAG.match(args[i - 1]) if i else None
        if flag and flag.group(2) is not None:                          # --token=VALUE
            if _secret_value(flag.group(1), flag.group(2)):
                parts.append({"where": "arg", "index": i, "key": flag.group(1).lower()})
        elif flag:
            continue
        elif prev and prev.group(2) is None and _secret_value(prev.group(1), arg):   # --api-key VALUE
            parts.append({"where": "arg", "index": i, "key": prev.group(1).lower()})
        elif "=" in arg and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", arg.partition("=")[0]):  # NAME=VALUE
            name, _, value = arg.partition("=")
            if _secret_value(name, value):
                parts.append({"where": "arg", "index": i, "key": name.lower()})
        elif _random_looking(arg):
            parts.append({"where": "arg", "index": i})
    return parts


def suggest_name(label: str | None, part: dict) -> str:
    """`NOTES_TOKEN`: the connection's name and the part's key, upper case, letters, digits and `_` only."""
    words = [w for w in re.split(r"[^A-Za-z0-9]+", f"{label or ''} {part.get('key') or ''}") if w]
    if part["where"] == "password":
        words.append("password")
    if not part.get("key") and part["where"] != "password":
        words.append("secret")
    name = "_".join(words).upper() or "CONNECTION_SECRET"
    name = name if name[0].isalpha() else "CONNECTION_" + name
    return (name if label and re.search(r"[A-Za-z0-9]", label) else "CONNECTION_" + name)[:64]


def _position(part: dict) -> tuple:
    """Where a part is: the URL's password, a query key, or an argument's index."""
    return (part.get("where"), part.get("index") if part.get("where") == "arg" else part.get("key"))


def _check_name(name: str) -> None:
    if not PLACEHOLDER.fullmatch("${" + str(name) + "}"):
        raise NothingToMove("a name is upper-case letters, digits and _, starting with a letter")


def move(url: str | None, args, part: dict, name: str, values: dict) -> tuple[str | None, list[str], dict]:
    """`part` out of the address or arguments, `${name}` in its place; the value goes into a copy of `values`."""
    _check_name(name)
    args, values = [str(arg) for arg in (args or ())], dict(values)
    if _position(part) not in {_position(found) for found in find(url, args)}:
        raise NothingToMove("nothing to move there")
    if name in values:
        raise NothingToMove(f"the name {name} is taken")
    where = part["where"]
    if where == "password":
        split = urlsplit(url)
        values[name] = split.password
        host = split.hostname or ""
        netloc = f"{quote(split.username or '', safe='')}:${{{name}}}@{host}{f':{split.port}' if split.port else ''}"
        return urlunsplit(split._replace(netloc=netloc)), args, values
    if where == "query":
        split = urlsplit(url)
        pairs, done = [], False
        for key, value in parse_qsl(split.query, keep_blank_values=True):
            if key == part["key"] and not done and _secret_value(key, value):
                values[name], value, done = value, f"${{{name}}}", True
            pairs.append((key, value))
        query = urlencode(pairs, safe="${}")
        return urlunsplit(split._replace(query=query)), args, values
    i = int(part["index"])
    arg = args[i]
    flag = _FLAG.match(arg)
    if flag and flag.group(2) is not None:
        values[name], args[i] = flag.group(2), arg[: arg.index("=") + 1] + f"${{{name}}}"
    elif "=" in arg and not flag and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", arg.partition("=")[0]):
        values[name], args[i] = arg.partition("=")[2], arg.partition("=")[0] + f"=${{{name}}}"
    else:
        values[name], args[i] = arg, f"${{{name}}}"
    return url, args, values


def fill(url: str | None, args, values: dict) -> tuple[str | None, list[str]]:
    """The placeholders back to their values; one with no value is left as written. A value is never read again
    for placeholders (no recursion)."""
    def sub(text: str) -> str:
        return PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), text)
    return (sub(url) if url else url), [sub(str(arg)) for arg in (args or ())]


def shown(url: str | None, args) -> tuple[str | None, list[str]]:
    """An address and arguments as every place may show them: each secret-looking part masked."""
    args = [str(arg) for arg in (args or ())]
    for part in find(url, args):
        if part["where"] == "password":
            split = urlsplit(url)
            host = split.hostname or ""
            url = urlunsplit(split._replace(netloc=f"{split.username or ''}:{_MASK}@{host}"
                                                   f"{f':{split.port}' if split.port else ''}"))
        elif part["where"] == "query":
            split = urlsplit(url)
            pairs = [(k, _MASK if k == part["key"] and _secret_value(k, v) else v)
                     for k, v in parse_qsl(split.query, keep_blank_values=True)]
            url = urlunsplit(split._replace(query=urlencode(pairs, safe="●")))
        else:
            arg = args[part["index"]]
            head, eq, _ = arg.partition("=")
            args[part["index"]] = f"{head}={_MASK}" if eq and (head.startswith("-") or head.isidentifier()) else _MASK
    return url, args
