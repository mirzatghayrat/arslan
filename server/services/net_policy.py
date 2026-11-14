"""NET-a (v0.1.64): which sites a sandboxed command may reach, judged for each connection at Arslan's local proxy.

Every sandboxed run gets a token in its proxy address (`start_run`, `sandbox_proxy.proxy_url`), registered while it
runs and bound to the process it was started for (`bind`): the proxy serves it only to that process's run (`owns`), and
ends the run's connections with it (`end_run`). The proxy reads each connection's token and asks `admits` about the host
it names, before its own checks (public addresses, the user's trusted devices), which still run as they did. A host is
- `allow`: a package registry (`PACKAGE_HOSTS`), a site in Settings (`sandbox_allowed_sites`), or one the user named
  in what they typed in this conversation (`_named`: not a sub-session's brief, one stored before briefs were tagged
  too, nor a picture's file name);
- `outside_only`: seen in outside content this conversation read (recorded where that content is marked:
  `untrusted.mark_external`, `untrusted.carried`), and none of the above;
- `unknown`: anything else.
Only `outside_only` is refused (403), unless the user allowed that host for this conversation (a `network:<host>` grant,
never "Always"): a site that appears nowhere was steered by nothing (⓪Plan Q1, as mainstream agents judge it). An
address is judged apart (`judge`). The command is told why (`refusal_note`), and the user is asked once whether
commands in this conversation may reach the site (`offer`; NET-b words that card and adds Settings' list). That card
comes after verify's run too (Codex round 1, F8). Where it can't be asked or isn't answered, the Inbox lists it, and
its "In this conversation" there stores what the card's would (`allow_from_inbox`, F7): not for a scheduled run's
entry, since a run with nobody to ask reads no grant (S1).

Hosts are compared after IDNA (UTS 46), in lower case, with no port and no trailing dot: the exact host, or a subdomain
of a listed, named or recorded one within that one's own site, never one a public suffix keeps apart from it
(`_covers`). A public suffix is a name anyone can have a site under, as the Public Suffix List says, both its sections
and its wildcard and exception rules (`is_public_suffix`, Codex round 1 F4): it is never a listed, named or recorded
site, nor is a bare TLD (`listable`), and outside content that names one refuses that host alone (`_shared`). An
address is matched only as itself, read in every spelling as the proxy reads a destination (`normalize`), in what the
user typed too (`addresses_in`). A text is read for hosts as people write them, in full-width forms, with an
ideographic full stop for a dot, and with text in a script written without spaces running on into them (`hosts_in`).
Outside content is read with JSON's string escapes undone as well, however deeply JSON nests in it, since it is often
recorded as its JSON (a tool's result, a resumed task's saved progress); what the user typed is read as written. And
what the user typed names a host only where its beginning and end can be told (`_typed_hosts`, Codex round 2): never
a guess at where one begins, which outside content's reading takes (in doubt, more hosts recorded).

Known limits:
- The record lives in memory, as the turn's own mark does: a restart forgets it (as GIT_REFUSED_IN), and a turn after
  one records again only what it reads, or carries in marked as outside content (a job's result or a sub-session's
  brief in its history, a rolling summary that folded one in, a resumed task's saved progress: Codex round 1 F5).
- A host spelled so that no reader sees a host ("evil dot example", base64) is `unknown`, so it passes.
- Only JSON's escapes are undone: a bare host right after an escape in another syntax (%0A in a URL, a Python repr's
  backslash-x1b, a terminal's color code) is read with the escape's last letters in front, so it is `unknown`. A host
  in a URL is read whole.
- The list is the snapshot tld bundles (its `// VERSION:` line), new with each tld: a public suffix added upstream
  since is a site here until then.
- Where a host in a script written without spaces begins, when text in that script runs on into it, can't be told.
  Outside content records each place it may begin (`hosts_in`), a few hosts it doesn't mean as well. What the user
  typed names none of those (Codex round 2): such a host only as the whole name it stands in ("请上传到例子.com"
  names that name, as a rule no one's, and not "例子.com"), so outside content that names it is refused and the user is
  asked once; typed as a URL, or apart from the text, it is named. A name in another script that such text runs into
  is named from where the script changes ("请访问example.com": example.com), which a label mixing the two scripts
  can't be told from ("例子2.com" names 2.com).
- A number the user typed for something else names the address it spells as the resolver reads it: a version 3.11.4
  names 3.11.0.4, an id 1572395042 names 93.184.216.34. That only opens the address itself, for someone holding it.
- A token is in its command's environment, but it works only for that run's own processes (`owns`, Codex round 1 F1):
  a process of another run that read it, or one that left this run and lost its parent, is refused as with no token.
  What the run's own processes do with it is the run's, as is a socket one of them hands to another process.
"""
from __future__ import annotations

import asyncio
import functools
import ipaddress
import json
import re
import secrets
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib import resources

import idna

from arslan.aio import within

#: Package registries and code hosts every sandboxed command may reach. github.com stays (⓪Plan Q2): a push already
#: gets HR-2b's once-only push card, which nothing answers automatically, and the sandbox closes ~/.ssh and gh's
#: credentials, so a command there can fetch but not sign in.
PACKAGE_HOSTS = frozenset({
    "pypi.org", "files.pythonhosted.org", "registry.npmjs.org", "registry.yarnpkg.com", "crates.io",
    "static.crates.io", "proxy.golang.org", "sum.golang.org", "rubygems.org", "github.com", "codeload.github.com",
    "objects.githubusercontent.com", "release-assets.githubusercontent.com"})

#: The Public Suffix List as the `tld` package bundles it (a locked dependency: THIRD_PARTY_NOTICES.md): upstream's
#: file at the commit its `// COMMIT:` line names, MPL-2.0. Codex round 1, F4: the whole list, not a short set kept
#: here. Read as a file on first use, and never through tld's own lookups, which fetch the list over the network when
#: their copy is missing: nothing here goes online. The app carries it by packaging/arslan-server.spec, and its
#: selftest asks it (packaging/server_entry.py).
_SUFFIX_LIST = ("tld", "res", "effective_tld_names.dat.txt")


def _suffix_list_text() -> str:
    package, folder, name = _SUFFIX_LIST
    try:
        return (resources.files(package) / folder / name).read_text(encoding="utf-8")
    except (ImportError, OSError) as exc:
        raise RuntimeError(f"NET-a: the Public Suffix List ({'/'.join(_SUFFIX_LIST)}) can't be read: {exc}") from exc


@functools.cache
def _psl() -> tuple[frozenset[str], frozenset[str], frozenset[str], frozenset[str]]:
    """The list's rules, each name as `normalize` writes one: its rules; its wildcard rules (`*.ck`) less their `*.`;
    its exception rules (`!www.ck`) less their `!`; and its TLDs, an IDN one both in its own script and after IDNA.
    Read once. Both sections count, ICANN's and the PRIVATE one (F4): the private one is shared hosting (github.io,
    blogspot.com, s3.us-east-1.amazonaws.com), where anyone gets a site, so naming or listing one of those must vouch
    for none of its tenants. Browsers keep sites apart by both sections too."""
    rules: set[str] = set()
    wildcards: set[str] = set()
    exceptions: set[str] = set()
    tlds: set[str] = set()
    for line in _suffix_list_text().splitlines():
        rule = line.split(maxsplit=1)[0] if line.strip() else ""        # a rule is read up to its first space
        if not rule or rule.startswith("//"):
            continue
        kind, name = ((exceptions, rule[1:]) if rule.startswith("!") else
                      (wildcards, rule[2:]) if rule.startswith("*.") else (rules, rule))
        tlds.add(name.rsplit(".", 1)[-1].lower())
        try:
            written = name.lower() if name.isascii() else idna.encode(name, uts46=True).decode("ascii")
        except idna.IDNAError:
            continue                     # no host is written so (`normalize` reads none), so no host is under it
        kind.add(written)
        tlds.add(written.rsplit(".", 1)[-1])
    return frozenset(rules), frozenset(wildcards), frozenset(exceptions), frozenset(tlds)


def _suffix_labels(name: str) -> int:
    """How many of `name`'s last labels are its public suffix, by the list's own algorithm (publicsuffix.org/list): an
    exception rule that matches prevails, and its suffix is the rule less its first label (`!www.ck`: ck); else the
    longest rule that matches, a wildcard's `*` matching any one label in its place (`*.ck`: foo.ck); else the last
    label alone (the implicit `*`)."""
    rules, wildcards, exceptions, _ = _psl()
    labels = name.split(".")
    tails = [".".join(labels[i:]) for i in range(len(labels))]
    for i, tail in enumerate(tails):
        if tail in exceptions:
            return len(labels) - i - 1
    for i, tail in enumerate(tails):
        if tail in rules or (i + 1 < len(tails) and tails[i + 1] in wildcards):
            return len(labels) - i
    return 1


def is_public_suffix(name: str) -> bool:
    """`name`, as `normalize` writes one, is a public suffix: a TLD, or a name anyone can have a site under."""
    return _suffix_labels(name) >= name.count(".") + 1


#: A name's labels, after IDNA: letters, digits, "-" and "_" (some real hosts carry one).
_NAME = re.compile(r"[a-z0-9_-]{1,63}(?:\.[a-z0-9_-]{1,63})*")
#: One part of an IPv4 address as inet_aton reads it: hex (0x), octal (a leading 0) or decimal.
_PART = re.compile(r"0x[0-9a-f]*|0[0-7]*|[1-9][0-9]*")
#: A last label that is a number: no TLD is, so such a name is an address in some spelling, or no host.
_ENDS_IN_NUMBER = re.compile(r"(?:^|\.)(?:0x[0-9a-f]*|[0-9]+)$")
#: Hosts a text names: a URL's host (after any user part), a bare name with a dot ending in letters (or punycode), and
#: a dotted IPv4 address.
_URL_HOST = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://(?:[^\s/?#@\[\]]*@)?(\[[^\]\s/]*\]|[^\s/?#:@\[\]<>'\"`]+)")
_BARE_NAME = re.compile(r"(?<![\w.-])((?:[^\W_](?:[\w-]{0,61}[^\W_])?\.)+(?:[^\W\d_]{2,63}|xn--[a-z0-9-]{1,59}))"
                        r"(?![\w-])", re.I)
_BARE_IPV4 = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?![\w-]|\.\w)")
#: A URL's host as `_URL_HOST` reads one, after any "://": in what the user typed (`_typed_hosts`) where a URL says it
#: begins, text in any script running into its scheme too.
_AFTER_SCHEME = re.compile(r"://(?:[^\s/?#@\[\]]*@)?(\[[^\]\s/]*\]|[^\s/?#:@\[\]<>'\"`]+)")
#: A token that may spell an address (inet_aton's IPv4 forms; IPv6, bracketed or not; with a port), never one inside a
#: longer name or word: `normalize`, the proxy's own reading of a destination, says which one is.
_ADDRESS = re.compile(r"(?<![\w.-])[0-9a-fx:.]+(?![\w-]|\.\w)", re.I | re.A)
#: Scripts written without spaces between words, as code point ranges: Thai and Lao, Myanmar, Hangul's jamo, Khmer,
#: the CJK radicals, symbols and punctuation, kana, Bopomofo, Han, Hangul, and Han's compatibility and supplementary
#: planes. Text in them runs straight on into a host beside it: a host in another script begins or ends where they do.
_SPACELESS_RANGES = ((0x0E00, 0x0EFF), (0x1000, 0x109F), (0x1100, 0x11FF), (0x1780, 0x17FF), (0x2E80, 0x2FDF),
                     (0x3000, 0x31FF), (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xA960, 0xA97F), (0xAC00, 0xD7FF),
                     (0xF900, 0xFAFF), (0x20000, 0x3FFFF))
_SPACELESS = re.compile("[" + "".join(f"{chr(low)}-{chr(high)}" for low, high in _SPACELESS_RANGES) + "]")
#: The ideographic full stop, which IDNA (UTS 46), and so curl and browsers, read as a host's dot (NFKC makes the
#: half-width one it, and the full-width one a dot). In a text it is that where a host has one: between two labels in
#: ASCII ("evil。example"), or before a TLD the list has that ends there. Anywhere else it ends a sentence, and stays:
#: as dots, sentences in CJK would run together into names.
_STOP = chr(0x3002)
_STOP_IN_ASCII = re.compile(f"(?<=[a-z0-9-]){_STOP}(?=[a-z0-9-])", re.I | re.A)
_STOP_BEFORE_LABEL = re.compile(_STOP + r"(?=([^\W_][\w-]{0,62})(?![\w-]))")
#: A host's last label as written in ASCII: letters, or punycode. In another script a TLD is one the list has.
_ASCII_TLD = re.compile(r"[a-z]{2,63}|xn--[a-z0-9-]{1,59}", re.I)
#: A label in ASCII, as one between a host's first label and its TLD.
_ASCII_LABEL = re.compile(r"[a-z0-9_-]{1,63}", re.I | re.A)
#: Up to four labels after a dot, in any script: the first may run on into other text (`_tld_cuts`).
_LABELS_AFTER = re.compile(r"(?:\.[^\W_][\w-]{0,62}){1,4}")
#: How far before a dot a host in a spaceless script may begin: a label of more such characters is past IDNA's 63
#: bytes (20 of Han or Hangul, 31 of kana).
_LEAD_KEPT = 32
#: How many hosts a text may name by where one in a spaceless script may begin (`hosts_in`): a page of them can't
#: stall the turn reading it.
_GUESSES_KEPT = 1024
#: A JSON string escape (RFC 8259): a letter's (\n, \t, \r, \b, \f), \" and \/, or a character by its code (\uXXXX, as
#: json.dumps writes all but ASCII by default), after one backslash or more, since JSON inside JSON (a command's output
#: that was JSON, in its result's JSON) escapes each backslash again. Left as written, an escape's letter or code runs
#: on into the host after it. An escaped backslash stays: a backslash stands apart from a host anyway. A run of
#: backslashes is read once, from its first (a long run is no slower to read than any other text).
_JSON_ESCAPE = re.compile(r'(?<!\\)\\++(?:u([0-9a-fA-F]{4})|([bfnrt"/]))')
_JSON_ESCAPED = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", '"': '"', "/": "/"}


def _ipv4(host: str) -> ipaddress.IPv4Address | None:
    """`host` read as inet_aton reads it, the resolver's reading of an address in any spelling: one to four parts, the
    last filling the bytes left, so 1572395042, 0x5db8d822, 0135.0270.0330.042 and 93.12113954 are 93.184.216.34."""
    parts = host.split(".")
    if not 1 <= len(parts) <= 4 or not all(_PART.fullmatch(part) for part in parts):
        return None
    *head, last = [int(p[2:] or "0", 16) if p.startswith("0x") else int(p, 8) if p.startswith("0") else int(p)
                   for p in parts]
    if any(value > 255 for value in head) or last >= 1 << (8 * (4 - len(head))):
        return None
    return ipaddress.IPv4Address(sum(value << (8 * (3 - i)) for i, value in enumerate(head)) + last)


def _ip(name: str | None):
    try:
        return ipaddress.ip_address(name or "")
    except ValueError:
        return None


def normalize(text) -> str | None:
    """A host as everything here holds it: lower case, IDNA (UTS 46) for a name that isn't ASCII, no port, no trailing
    dot, and an address in any spelling as `ipaddress` writes it (an IPv4-mapped one as IPv4). None: no host."""
    host = str(text or "").strip().lower()
    bracketed = host.startswith("[")                     # only an IPv6 address is written in brackets
    if bracketed:
        host = host[1:].partition("]")[0]
    elif host.count(":") == 1:
        host, _, port = host.partition(":")
        if not port.isdigit():
            return None
    host = host.rstrip(".")
    if bracketed or ":" in host:
        try:
            address = ipaddress.IPv6Address(host)
        except ValueError:
            return None
        return str(address.ipv4_mapped or address)
    if (address := _ipv4(host)) is not None:
        return str(address)
    if not host.isascii():
        try:
            host = idna.encode(host, uts46=True).decode("ascii")
        except idna.IDNAError:
            return None
    return host if len(host) <= 253 and _NAME.fullmatch(host) else None


def _address_like(name: str | None) -> bool:
    """An address in any spelling, or what no reader reads as a host: judged as an address (`judge`)."""
    return name is None or _ip(name) is not None or bool(_ENDS_IN_NUMBER.search(name))


def listable(name: str) -> bool:
    """Whether a list, the user's words or outside content can name `name` as a site, it and its subdomains in it: a
    name with a dot that is no public suffix (`is_public_suffix`). An address is matched only as itself."""
    return "." in name and not _address_like(name) and not is_public_suffix(name)


def _unescaped(text: str) -> str:
    """`text` with each JSON string escape in it undone (`_JSON_ESCAPE`): a surrogate pair is the one character its two
    codes spell, and a lone surrogate U+FFFD."""
    text = _JSON_ESCAPE.sub(lambda escape: chr(int(escape.group(1), 16)) if escape.group(1)
                            else _JSON_ESCAPED[escape.group(2)], text)
    return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")


def _host_text(text, *, escapes: bool = False) -> str:
    """A text as its hosts are read, as IDNA (UTS 46) reads a host, and so curl and browsers do: NFKC, so a full-width
    form is the ASCII one ("ｅｖｉｌ．ｅｘａｍｐｌｅ"), and an ideographic full stop a dot where a host has one (`_STOP`).
    `escapes`: and with each JSON string escape in it undone (`_unescaped`), then NFKC again for what they spelled."""
    text = unicodedata.normalize("NFKC", str(text or ""))
    if escapes and "\\" in text:
        text = unicodedata.normalize("NFKC", _unescaped(text))
    if _STOP in text:
        tlds = _psl()[3]
        text = _STOP_IN_ASCII.sub(".", text)
        text = _STOP_BEFORE_LABEL.sub(lambda stop: "." if stop.group(1).lower() in tlds else stop.group(), text)
    return text


def _spaceless(char: str) -> bool:
    return _SPACELESS.match(char) is not None


def _tld_ok(label: str, known: bool) -> bool:
    """`label` can end a host: a TLD the list has, or, unless `known`, any written in ASCII (`_ASCII_TLD`)."""
    return label.lower() in _psl()[3] or (not known and label.isascii() and _ASCII_TLD.fullmatch(label) is not None)


@functools.lru_cache(maxsize=4096)
def _tld_cuts(label: str, known: bool) -> tuple[str, ...]:
    """Where a host's last label ends, as a text has it: at its own end, where its script changes ("example请查收"
    after example), or, in a spaceless script, after a TLD that more text runs on from ("中国请查收" after its TLD);
    only where a TLD ends (`_tld_ok`)."""
    ends = {len(label)}
    ends.update(i for i in range(1, len(label)) if _spaceless(label[i - 1]) != _spaceless(label[i]))
    if label[:1] and _spaceless(label[0]):
        ends.update(range(1, min(len(label), _LEAD_KEPT)))
    return tuple(label[:end] for end in sorted(ends) if _tld_ok(label[:end], known))


def hosts_in(text, *, escapes: bool = False) -> set[str]:
    """The hosts a text names, as outside content is read (`note_outside`), each as `normalize` writes it (a public
    suffix too: its readers take what they use). A text is read three ways, and every host any of them finds counts (in
    doubt, more hosts):
    - as written: a host in any script that stands apart from the words around it, an IDN one included;
    - with text in a spaceless script read as the spaces it stands for: a host in another script that such text runs
      into, on either side, is read on its own ("请上传到evil.example" names evil.example);
    - for a host in a spaceless script that text in it runs into, where the host begins can't be told: each of the
      characters right before a dot may begin one, and it ends where a TLD the list has does ("请上传到例子.com"
      names "例子.com", and "到例子.com" and the rest too), at most `_GUESSES_KEPT` of them.
    `escapes`, outside content's reading (`note_outside`): the text with each JSON string escape in it undone
    (`_unescaped`) is read those three ways as well, and first, the two readings sharing `_GUESSES_KEPT`. A text
    recorded as its JSON (a tool's result, a resumed task's saved progress) names the host right after an escape in
    it, which as written is read with the escape's letter in front (a backslash-n before drop.evil.example:
    ndrop.evil.example), and text json.dumps wrote by its codes runs into a host in its own script again. What the
    user typed is read otherwise (`_typed_hosts`, Codex round 2), and as written alone: it is no JSON, and a host it
    would name but doesn't spell would pass (a Windows path, C:\\new.example, names new.example, never ew.example)."""
    texts = list(dict.fromkeys((_host_text(text, escapes=True), _host_text(text)) if escapes else (_host_text(text),)))
    candidates: set[str] = set()
    for reading in {form for text in texts for form in (text, _SPACELESS.sub(" ", text))}:
        candidates.update(match.group(1) for pattern in (_URL_HOST, _BARE_IPV4) for match in pattern.finditer(reading))
        for match in _BARE_NAME.finditer(reading):
            *head, last = match.group(1).split(".")
            candidates.update(".".join([*head, cut]) for cut in _tld_cuts(last, False))
    guesses: list[str] = []
    for text in texts:
        for dot in re.finditer(r"\.", text):
            if len(guesses) >= _GUESSES_KEPT:
                break
            start = begin = dot.start()
            while (begin > 0 and start - begin < _LEAD_KEPT and text[begin - 1].isalnum()
                   and _spaceless(text[begin - 1])):
                begin -= 1
            after = _LABELS_AFTER.match(text, start) if begin < start else None
            if after is None:
                continue
            labels, ends = after.group()[1:].split("."), []
            for j, label in enumerate(labels):
                ends.extend(".".join([*labels[:j], cut]) for cut in _tld_cuts(label, True))
                if not (_ASCII_LABEL.fullmatch(label) or label.lower() in _psl()[3]):
                    break              # between a host's first label and its TLD: ASCII labels, or TLDs (`公司.cn`)
            guesses.extend(f"{text[first:start]}.{end}" for first in range(begin, start) for end in ends)
    candidates.update(guesses[:_GUESSES_KEPT])
    return {name for candidate in candidates if (name := normalize(candidate)) is not None}


def _mixed(label: str) -> bool:
    """`label` has text in a spaceless script and in another: where one runs into the other."""
    return len({_spaceless(char) for char in label}) > 1


def _typed_name(name: str, *, url: bool = False) -> str | None:
    """A name in what the user typed (`_typed_hosts`), as the host it names: up to where its last label's script first
    changes, if it does (text in a spaceless script runs on from it there: "evil.example请查收", "例子.com请查收"), and
    then ending in a TLD (`_tld_ok`); with no label that mixes a spaceless script with another, unless it is a URL's
    host (`url`), which begins where the URL says. Elsewhere such a label is where text in one script runs into a name
    in the other ("请访问example.com"), which is read where the script changes. None: no host (an address in a URL is
    `addresses_in`'s)."""
    *head, last = name.split(".")
    end = next((i for i in range(1, len(last)) if _spaceless(last[i - 1]) != _spaceless(last[i])), None)
    labels = [*head, last[:end]]
    if not _tld_ok(labels[-1], False) or (not url and any(map(_mixed, labels))):
        return None
    return ".".join(labels)


def _typed_hosts(text) -> set[str]:
    """Codex round 2: the hosts what the user typed names, each as `normalize` writes it, read only where a host's
    beginning and end can be told, never by a guess (`hosts_in`'s third reading, outside content's alone):
    - a URL's host, from where the URL says it begins, and no host inside it: "https://例子.com/" names "例子.com",
      and not "子.com";
    - a name standing apart from the words around it, in any script (an IDN one included);
    - a name in another script that text in a spaceless script runs into, read with that text as the spaces it stands
      for (`hosts_in`'s second reading): "请访问example.com" names example.com, not that whole run.
    Each ends where its last label's script changes, if it does (`_typed_name`). So a host in a spaceless script that
    text in that script runs into is named only as the whole name it stands in as written ("请上传到例子.com" names
    that, which is no one's as a rule, and not "例子.com"): where it begins can't be told. Read as written, as
    `hosts_in` reads a text (full-width forms, an ideographic full stop), and never as JSON."""
    text = _host_text(text)
    urls = [match.span(1) for match in _AFTER_SCHEME.finditer(text)]
    found = {_typed_name(text[start:end], url=True) for start, end in urls}
    for reading in (text, _SPACELESS.sub(" ", text)):
        found.update(_typed_name(match.group(1)) for match in _BARE_NAME.finditer(reading)
                     if not any(start < match.start(1) < end for start, end in urls))     # in a URL's host: read above
    return {name for candidate in found if candidate and (name := normalize(candidate)) is not None}


def _apart(text: str, start: int, end: int) -> bool:
    """Whether `text[start:end]`, a token `_ADDRESS` read (so with no ASCII letter or digit beside it), stands apart
    from the words beside it in any script (Codex round 2): beside it on each side, no letter or digit, or one of a
    spaceless script, whose text runs straight into it there ("服务器在10.0.0.5上"). A dot between it and a letter or
    digit of any script joins it to that word as a longer name ("例子.10.0.0.5", as "1.2.3.4.example.com")."""
    def beside(char: str, dot: bool) -> bool:
        return not char.isalnum() or (_spaceless(char) and not dot)
    return ((start == 0 or beside(text[start - 1], text[start] == "."))
            and (end == len(text) or beside(text[end], text[end - 1] == ".")))


def addresses_in(text) -> set[str]:
    """Codex round 1, F6: the addresses a text spells out, each as the proxy reads a destination (`normalize`), so in
    any spelling: 10.0.0.5, 167772165, 0xa000005, 012.0.0.05, 10.5, [::ffff:a00:5] and ::ffff:10.0.0.5 are each
    10.0.0.5 there, with a port or without. Not one inside a longer name or word, in any script (1.2.3.4.example.com,
    v1.2.3.4, café10.0.0.5, "例子.10.0.0.5": `_apart`). The text is read as `hosts_in` reads it (full-width forms, an
    ideographic full stop)."""
    found = set()
    text = _host_text(text)
    for match in _ADDRESS.finditer(text):
        if not _apart(text, *match.span()):
            continue
        token = match.group()
        name = normalize(token)
        if _ip(name) is None:
            name = normalize(token.strip(".").rstrip(":"))  # one that ends a sentence ("at 10.0.0.5:") or follows "..."
        if _ip(name) is not None:
            found.add(name)
    return found


def _sites_named(texts) -> set[str]:
    """What the user's words name: sites (`listable`) where a host's beginning and end can be told (`_typed_hosts`,
    Codex round 2), and addresses in any spelling the proxy reads (`addresses_in`), each address matched as itself."""
    named: set[str] = set()
    for text in texts:
        named.update(name for name in _typed_hosts(text) if listable(name) or _ip(name) is not None)
        named.update(addresses_in(text))
    return named


def _covers(hosts, name: str) -> bool:
    """`name` is one of `hosts`, or a subdomain of one within that one's site: never across a public suffix (F4), so a
    listed amazonaws.com.cn covers none of the buckets under s3.cn-north-1.amazonaws.com.cn, each its owner's site,
    and a public suffix covers only itself. An address only as itself."""
    if name in hosts:
        return True
    if not hosts or _address_like(name):
        return False
    labels = name.split(".")
    site = _suffix_labels(name) + 1                      # its site's labels: its public suffix, and one more
    return any(".".join(labels[i:]) in hosts for i in range(1, len(labels) - site + 1))


# ── what outside content named, per conversation (in memory) ─────────────────

_outside: dict[str, set[str]] = {}
#: The public suffixes outside content named, per conversation. None is a site (`listable`): it covers no one's site
#: under it. But each is a host as reachable as any, and refused as itself alone: a bucket endpoint that takes
#: path-style uploads (s3.us-east-1.amazonaws.com), an EC2 instance's name (a wildcard's: *.compute-1.amazonaws.com).
#: Unrecorded, such a host would be `unknown` and pass, where before F4 it was recorded and refused.
_shared: dict[str, set[str]] = {}


def note_outside(conversation_id: str | None, text: str | None = None) -> None:
    """This conversation read outside content (`untrusted.mark_external`, a turn that carried some in); `text`, what was
    read where the caller has it, adds the sites it names, and the public suffixes it names to `_shared`: read as
    written and as its JSON (`hosts_in`'s `escapes`), as it may be recorded."""
    if not conversation_id:
        return
    hosts = _outside.setdefault(conversation_id, set())
    for name in hosts_in(text, escapes=True) if text else ():
        if listable(name):
            hosts.add(name)
        elif "." in name and not _address_like(name):
            _shared.setdefault(conversation_id, set()).add(name)


def outside_seen(conversation_id: str | None) -> bool:
    return bool(conversation_id) and conversation_id in _outside


def outside_hosts(conversation_id: str | None) -> frozenset[str]:
    return frozenset(_outside.get(conversation_id or "", ()))


# ── the settings: the switch and the sites list ──────────────────────────────

async def judging() -> bool:
    """The user's `sandbox_net_judgement` (default on): the proxy judges each site, instead of S2a-1's whole-network
    rule after outside content. DELETE-BY: v0.1.65, with that old path (command_gate)."""
    from server.db import session as db_session
    from server.services import settings_service
    try:
        async with db_session.AsyncSessionLocal() as db:
            return await settings_service.sandbox_net_judgement(db)
    except Exception:  # noqa: BLE001 — unreadable means the default (on): every connection is still judged at the proxy
        return True


def parse_sites(raw, *, strict: bool = False) -> list[str]:
    """`sandbox_allowed_sites`, a JSON list of hosts, each once as `normalize` writes it. An entry no list can hold (a
    public suffix, a bare TLD, not a host) is left out and anything malformed lists nothing; `strict` (a save) raises
    ValueError instead."""
    try:
        entries = json.loads(raw) if raw else []
    except ValueError:
        entries = None
    if not isinstance(entries, list):
        if strict:
            raise ValueError("the sites list is a JSON list of host names")
        return []
    sites: list[str] = []
    for entry in entries:
        name = normalize(entry) if isinstance(entry, str) else None
        if name is None or not (listable(name) or _ip(name) is not None):
            if strict:
                raise ValueError(f"not a site Arslan can list: {str(entry)[:100]}")
            continue
        if name not in sites:
            sites.append(name)
    return sites


async def _sites() -> list[str]:
    from server.db import session as db_session
    from server.services import settings_service
    try:
        async with db_session.AsyncSessionLocal() as db:
            return parse_sites(await settings_service.sandbox_allowed_sites(db))
    except Exception:  # noqa: BLE001 — fails closed: an unreadable list allows no site beyond the package hosts
        return []


#: The hosts each conversation's user messages name, kept until a message comes or goes (their count and last id).
_named_cache: dict[str, tuple[tuple[int, int], frozenset[str]]] = {}


def _brief_id(conversation_id: str, ids) -> int | None:
    """Codex round 2, F3: which of a conversation's user messages (`ids`) is a sub-session's brief, tagged or not: a
    sub-session's first. Read from where a brief is, since one stored before `sub_sessions.BRIEF_SOURCE` (every
    sub-session started before NET-a) has no `source`, and a clean one no frame, so it read as typed. Only
    `sub_sessions.create_child` gives an id `CHILD_PREFIX`, as it has since sub-sessions began (SUB3), and the id stays
    when the sub-session is kept as an ordinary conversation or its row is gone. `start` stores the brief as its first
    message, before its job starts and before anyone has its id; ids are never handed out again (migration 0069); and
    an undo takes back a typed turn and the ones after it, never a brief, whose turn is a job's. So every message typed
    there has a larger id. None: this is no sub-session."""
    from server.services import sub_sessions
    return min(ids, default=None) if conversation_id.startswith(sub_sessions.CHILD_PREFIX) else None


async def _named(conversation_id: str | None) -> frozenset[str]:
    """The hosts the user named in this conversation: what they typed in their own messages (role user). Codex round
    1, F3: never a sub-session's brief, the commander's words, framed or not (`sub_sessions.BRIEF_SOURCE`; a framed one
    also by SUB5b's header, `untrusted.BRIEF_FROM_OUTSIDE`; one stored before either, by where it is: `_brief_id`, Codex
    round 2), nor the file names of the pictures sent with a message (`arslan.typed_text`). Every other user-role row is
    typed: in the window, on the phone (a chat message, a task's goal), or while a turn ran (K9b). A choice card's pick
    is sent as the user's message: its label, shown in full, is what they chose to send, as with a paste."""
    if not conversation_id:
        return frozenset()
    from sqlalchemy import func, select
    from server.db import session as db_session
    from server.db.models import ArslanMessage
    from server.orchestrator import arslan, untrusted
    from server.services import sub_sessions
    mine = (ArslanMessage.conversation_id == conversation_id, ArslanMessage.role == "user")
    try:
        async with db_session.AsyncSessionLocal() as db:
            count, last = (await db.execute(select(func.count(), func.max(ArslanMessage.id)).where(*mine))).one()
            cached = _named_cache.get(conversation_id)
            if cached is not None and cached[0] == (count, last or 0):
                return cached[1]
            rows = (await db.execute(select(ArslanMessage.id, ArslanMessage.content, ArslanMessage.source)
                                     .where(*mine))).all()
    except Exception:  # noqa: BLE001 — fails closed: messages that can't be read name no host
        return frozenset()
    brief = _brief_id(conversation_id, (row_id for row_id, _, _ in rows))
    named = frozenset(_sites_named(arslan.typed_text(content) for row_id, content, source in rows
                                   if row_id != brief and source != sub_sessions.BRIEF_SOURCE
                                   and not content.startswith(untrusted.BRIEF_FROM_OUTSIDE)))
    _named_cache[conversation_id] = ((count, last or 0), named)
    return named


async def _trusted_device(name: str) -> bool:
    """⓪Plan's carve-out (b): a device the user trusted in the SBX settings counts as listed. An address by
    `trusted_address`'s rule; a name by the name it was trusted under (the proxy's own check still pins its address)."""
    from server.services import sandbox_proxy
    trusted = await sandbox_proxy._trusted()
    if _ip(name) is not None:
        return sandbox_proxy.trusted_address(name, trusted) is not None
    return any(entry.get("host") == name for entry in trusted)


# ── the judgement ────────────────────────────────────────────────────────────

async def judge(host: str, conversation_id: str | None, *, turn_seen: bool = False) -> str:
    """`allow`, `outside_only` or `unknown` for `host` in this conversation (the module says which is which).
    `turn_seen`: the run's turn carried outside content in, which counts for an address as this conversation's
    record does."""
    name = normalize(host)
    ip = _ip(name)
    if ip is not None and ip.is_loopback:
        return "allow"                          # ⓪Plan's carve-out (a): the proxy's own check refuses it, as today
    if name is not None and (_covers(PACKAGE_HOSTS, name) or _covers(await _sites(), name)
                             or _covers(await _named(conversation_id), name)):
        return "allow"
    if not _address_like(name):
        if not (_covers(_outside.get(conversation_id or "", ()), name)
                or name in _shared.get(conversation_id or "", ())):
            return "unknown"
        return "allow" if await _trusted_device(name) else "outside_only"
    # ⓪Plan (2026-11-14), the address rule: after outside content an address in any spelling (dotted, decimal, hex,
    # octal, short, IPv6, IPv4-mapped; and a name ending in a number, which some resolvers read as one) counts as
    # `outside_only` unless the user named that address or listed it. The named risk: the host record can't hold an
    # address no text spells out, so an injected `curl http://1572395042/` would be `unknown` and pass. The only
    # carve-outs (Codex round 1, F6): loopback (a, above), and the devices the user trusted (b), which count as listed.
    # A LAN address is none: one the user didn't name, list or trust is refused here first, and the proxy's own check
    # (which refuses an untrusted one and offers its device card) runs only once it is allowed here.
    # Before outside content an address is judged as today.
    if ip is not None and await _trusted_device(name):
        return "allow"
    return "outside_only" if turn_seen or outside_seen(conversation_id) else "unknown"


# ── the runs the proxy serves ────────────────────────────────────────────────

@dataclass(eq=False)
class Run:
    """One sandboxed command (or MCP server) while its token is registered."""
    token: str
    conversation_id: str | None
    job_id: str | None
    command: str
    seen: Callable[[], bool]                # its turn's outside-content mark as it stands (`untrusted.turn_so_far`)
    asks: bool                              # someone can be asked here: only then does a grant count (S1)
    judged: bool                            # off: an MCP server (design item 7), or every run with the switch off
    refused: list[str] = field(default_factory=list)       # what the proxy refused it, for its note and card
    granted: set[str] = field(default_factory=set)         # what a grant let through (one ledger row each)
    root: int | None = None                 # its process, once started (`bind`): the token works for its run only
    started: asyncio.Event = field(default_factory=asyncio.Event)       # set with `root`
    connections: set = field(default_factory=set)          # the proxy's connections of it (their tasks): `end_run`


_runs: dict[str, Run] = {}
_REFUSED_KEPT = 8
#: How long a connection waits for its run's process to be named (`bind`), which happens as that process starts.
_START_WAIT_S = 5


async def start_run(command: str = "", *, judged: bool | None = None) -> Run:
    """A run's token, registered until `end_run`, with what the proxy judges it by: this turn's conversation and job,
    its outside-content mark, and whether someone can be asked. `judged` None: the switch says."""
    from server.orchestrator import untrusted
    from server.services import background_jobs, permissions, tool_outputs
    run = Run(secrets.token_hex(16), tool_outputs.conversation.get(), background_jobs._inside_job.get(),
              command[:300], untrusted.turn_so_far(), permissions.current_asker() is not None,
              await judging() if judged is None else judged)
    _runs[run.token] = run
    return run


def bind(run: Run | None, pid: int | None) -> None:
    """Codex round 1, F1: `pid` is the process `run` was started for (a command, or an MCP server), which leads a session
    of its own. From now on its token works only for that process's run (`owns`)."""
    if run is not None and pid:
        run.root = pid
        run.started.set()


def end_run(run: Run | None) -> None:
    """Its token ends with it, and so does every connection the proxy holds for it, open or still being set up (Codex
    round 1, F2): nothing it started outlives it, a child left running included, and from now on it is refused."""
    if run is not None:
        _runs.pop(run.token, None)
        for connection in list(run.connections):
            connection.cancel()


def run_for(token: str | None) -> Run | None:
    return _runs.get(token) if token else None


async def owns(run: Run, client, server) -> bool:
    """Codex round 1, F1: whether the connection from `client` to the proxy at `server` ((host, port) each) comes from
    `run`'s own processes (`peer_process`). A connection that comes before its run's process is named waits for it."""
    from server.services import peer_process
    if run.root is None:
        try:
            await within(run.started.wait(), _START_WAIT_S)
        except TimeoutError:
            return False
    return await asyncio.to_thread(peer_process.held, run.root, client, server)


async def admits(run: Run, host: str) -> bool:
    """The proxy's question for one connection of `run` to `host`: refused only when `host` is `outside_only` in its
    conversation and no grant of that conversation lets it through; then it is kept on the run (`refused`)."""
    if not run.judged or await judge(host, run.conversation_id, turn_seen=run.seen()) != "outside_only":
        return True
    name = normalize(host) or host.lower()
    if run.asks and await _granted(run, name):
        return True
    if name not in run.refused and len(run.refused) < _REFUSED_KEPT:
        run.refused.append(name)
    return False


async def _granted(run: Run, name: str) -> bool:
    """This conversation's grant for `name` (its card's "In this conversation"). Its first use in a run writes the
    ledger row a standing answer writes."""
    from server.db import session as db_session
    from server.services import permission_store, permissions
    try:
        async with db_session.AsyncSessionLocal() as db:
            grant = await permission_store.find_grant(db, run.conversation_id, None, "network", f"network:{name}")
    except Exception:  # noqa: BLE001 — fails closed: a grant that can't be read lets nothing through
        return False
    if grant is None:
        return False
    if name not in run.granted:
        run.granted.add(name)
        await permissions.note_standing(request(name, run.command), permissions.Context(
            run.conversation_id, job_id=run.job_id), permissions.Standing(
            permissions.Decision(True, "grant", "conversation"), grant_id=grant.id))
    return True


# ── what the command and the user are told ───────────────────────────────────

def refusal_note(hosts) -> str:
    """What a refused run's result says, one sentence a host (NET-b may word it again)."""
    return " ".join(
        f"{host} was refused: " + ("after this conversation read outside content, only an address the user named or "
                                   "listed is allowed." if _address_like(normalize(host)) else
                                   "it appeared only in outside content this conversation read, and the user didn't "
                                   "name it.") + " The user can allow it for this conversation." for host in hosts)


def request(host: str, command: str):
    """The card for one refused site (`offer`), and what a grant's use records: only what is known, the site and the
    command that connected (none, for the Inbox's answer: `allow_from_inbox`), never what it would send (the proxy
    doesn't see it)."""
    from server.services import permissions
    why = (f"the address {host}, which you didn't name, after this conversation read outside content"
           if _address_like(normalize(host)) else
           f"{host}, a site that appeared only in outside content this conversation read (a page, a file or a tool's "
           "output), not one you named")
    ran = f"`{command[:300]}`" if command else "A command"
    return permissions.Request(
        kind="network", target=f"network:{host}", conversation_only=True,
        title=f"Let commands in this conversation connect to {host}?",
        detail=f"{ran} tried to connect to {why}. Arslan can't see what it would send.")


async def offer(hosts, command: str, conversation_id: str | None) -> str:
    """NET-a's card after a run the proxy refused sites in: one card for up to three, "In this conversation" (one
    `network:<host>` grant each, never "Always") or no. What the model is told of the answer. With nobody to ask (a
    scheduled run) the card goes where every card goes there (Codex round 1, F7): refused by policy, with nothing
    granted, and listed in the Inbox, which offers it no grant (S1: such a run reads none)."""
    from server.services import background_jobs, permissions
    shown = list(dict.fromkeys(hosts))[:3]
    if not shown:
        return ""
    names = ", ".join(shown)
    decisions = await _card(shown, command, permissions.Context(conversation_id,
                                                                job_id=background_jobs._inside_job.get()))
    refused = next((decision for decision in decisions if not decision.allowed), None)
    if refused is None:
        return f"The user allowed {names} for this conversation: run the command again."
    return refused.model_text or f"The user did not allow {names}."


async def _card(sites: list[str], command: str, context) -> list:
    """The card itself, asked after the run (`offer`) or answered from the Inbox (`allow_from_inbox`)."""
    from server.services import permissions
    return await permissions.decide_many([request(site, command) for site in sites], context,
                                         title=f"Let commands in this conversation connect to {', '.join(sites)}?")


def listed_sites(kind: str, target: str) -> list[str]:
    """Codex round 1, F7: the sites a ledger row of NET-a's card names, in its order: `request`'s target
    (`network:<host>`), or for a card that asked about several, theirs as `decide_many` joins them. What "In this
    conversation" on that card allows. [] for any other row: S2a-1's, verify's and a Shortcut's `network:*` among them,
    and a target no card of NET-a writes (a host in a spelling other than `normalize`'s)."""
    parts = target.split("\x1e") if kind == "network" else []
    sites = [part.removeprefix("network:") for part in parts if part.startswith("network:")]
    return sites if parts and len(sites) == len(parts) and all(normalize(site) == site for site in sites) else []


async def allow_from_inbox(row) -> list:
    """Codex round 1, F7: "In this conversation", given in the Inbox to a ledger row of NET-a's card the Inbox lists
    (never opened, or unanswered: `permission_store.LISTED`, never a scheduled run's), for that row's own
    conversation. Answered through the card's own path (`_card`) by that click, so it stores what a click on the card
    stores: one `network:<host>` grant a site (`listed_sites`), and its ledger row. The grants, for Undo. The caller
    (`POST /permissions/grants`) checked the row."""
    from server.db import session as db_session
    from server.services import permission_store, permissions
    sites = listed_sites(row.kind, row.target)

    async def click(frame: dict) -> dict:
        return {"approved": True, "scope": "conversation", "by": "inbox", "call_id": f"refused:{row.id}"}
    with permissions.asking_with(click):
        await _card(sites, "", permissions.Context(row.conversation_id, job_id=row.job_id))
    async with db_session.AsyncSessionLocal() as db:
        return [await permission_store.find_grant(db, row.conversation_id, None, "network", f"network:{site}")
                for site in sites]


def _reset_for_tests() -> None:
    _runs.clear()
    _outside.clear()
    _shared.clear()
    _named_cache.clear()
