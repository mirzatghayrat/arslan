"""NET-a (v0.1.64): which sites a sandboxed command may reach, judged for each connection at Arslan's local proxy.

Every sandboxed run gets a token in its proxy address (`start_run`, `sandbox_proxy.proxy_url`), registered while it
runs. The proxy reads each connection's token and asks `admits` about the host it names, before its own checks (public
addresses, the user's trusted devices), which still run as they did. A host is
- `allow`: a package registry (`PACKAGE_HOSTS`), a site in Settings (`sandbox_allowed_sites`), or one the user named
  in their own messages in this conversation;
- `outside_only`: seen in outside content this conversation read (recorded where that content is marked:
  `untrusted.mark_external`, `untrusted.carried`), and none of the above;
- `unknown`: anything else.
Only `outside_only` is refused (403), unless the user allowed that host for this conversation (a `network:<host>` grant,
never "Always"): a site that appears nowhere was steered by nothing (⓪Plan Q1, as mainstream agents judge it). An
address is judged apart (`judge`). The command is told why (`refusal_note`), and the user is asked once whether
commands in this conversation may reach the site (`offer`; NET-b words that card and adds Settings' list).

Hosts are compared after IDNA (UTS 46), in lower case, with no port and no trailing dot: the exact host, or a subdomain
of a listed, named or recorded one. A bare TLD or a public suffix is never one of those (`listable`).

Known limits:
- The record lives in memory, as the turn's own mark does: a restart forgets it (as GIT_REFUSED_IN), and a turn after
  one records again only what it reads, or carries in framed (a job's result or a sub-session's brief in its history).
  A rolling summary that folds outside content in marks the turn but records no host.
- A host spelled so that no reader sees a host ("evil dot example", base64) is `unknown`, so it passes.
- A token is in its command's environment: a process that can read another running command's environment could use
  that token while that command runs, and be judged as that command's conversation.
"""
from __future__ import annotations

import ipaddress
import json
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field

import idna

#: Package registries and code hosts every sandboxed command may reach. github.com stays (⓪Plan Q2): a push already
#: gets HR-2b's once-only push card, which nothing answers automatically, and the sandbox closes ~/.ssh and gh's
#: credentials, so a command there can fetch but not sign in.
PACKAGE_HOSTS = frozenset({
    "pypi.org", "files.pythonhosted.org", "registry.npmjs.org", "registry.yarnpkg.com", "crates.io",
    "static.crates.io", "proxy.golang.org", "sum.golang.org", "rubygems.org", "github.com", "codeload.github.com",
    "objects.githubusercontent.com", "release-assets.githubusercontent.com"})

#: Names under which anyone can get a host of their own, so none is ever a listed, named or recorded host: common
#: public suffixes of two labels and more, and shared hosting. Built in, conservative and short, not the Public Suffix
#: List: one missing here can be listed or named (it and its subdomains), or recorded from outside content (refusing
#: its subdomains), like any site. A single label, a TLD, never can (`listable`).
_SUFFIXES = frozenset({
    "co.uk", "org.uk", "me.uk", "ltd.uk", "plc.uk", "net.uk", "ac.uk", "gov.uk", "sch.uk",
    "com.au", "net.au", "org.au", "edu.au", "gov.au", "id.au", "asn.au", "co.nz", "net.nz", "org.nz", "ac.nz",
    "co.jp", "ne.jp", "or.jp", "ac.jp", "go.jp", "ad.jp", "ed.jp", "gr.jp", "lg.jp",
    "co.kr", "or.kr", "ne.kr", "ac.kr", "go.kr", "re.kr", "com.cn", "net.cn", "org.cn", "gov.cn", "edu.cn", "ac.cn",
    "com.hk", "net.hk", "org.hk", "edu.hk", "gov.hk", "com.tw", "net.tw", "org.tw", "edu.tw", "gov.tw",
    "com.sg", "net.sg", "org.sg", "edu.sg", "gov.sg", "com.my", "net.my", "org.my",
    "co.in", "net.in", "org.in", "firm.in", "gen.in", "ind.in", "ac.in", "gov.in", "co.id", "or.id", "ac.id",
    "go.id", "web.id", "com.br", "net.br", "org.br", "gov.br", "com.mx", "org.mx", "gob.mx", "com.ar", "org.ar",
    "com.tr", "net.tr", "org.tr", "gen.tr", "co.za", "org.za", "net.za", "gov.za", "co.il", "org.il", "ac.il",
    "co.th", "in.th", "ac.th", "com.ua", "com.pl", "com.es", "com.vn", "com.ph", "com.pk", "com.eg", "com.sa",
    "com.ng", "com.co", "com.pe", "com.ve", "com.bd", "com.np", "co.ke", "co.at", "or.at",
    "github.io", "githubusercontent.com", "gitlab.io", "bitbucket.io", "pages.dev", "workers.dev", "r2.dev",
    "netlify.app", "vercel.app", "now.sh", "herokuapp.com", "appspot.com", "web.app", "firebaseapp.com",
    "blogspot.com", "wordpress.com", "tumblr.com", "wixsite.com", "myshopify.com", "readthedocs.io", "surge.sh",
    "azurewebsites.net", "cloudapp.net", "cloudfront.net", "amazonaws.com", "s3.amazonaws.com",
    "googleusercontent.com", "onrender.com", "fly.dev", "deno.dev", "glitch.me", "repl.co", "replit.dev",
    "ngrok.io", "ngrok.app", "ngrok-free.app", "trycloudflare.com", "loca.lt", "duckdns.org", "ddns.net"})

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
    """Whether a list, the user's words or outside content can name `name` as a site, it and its subdomains: a name
    with a dot that is no public suffix (`_SUFFIXES`). An address is matched only as itself."""
    return "." in name and name not in _SUFFIXES and not _address_like(name)


def hosts_in(text) -> set[str]:
    """The hosts a text names, each as `normalize` writes it (a public suffix too: its readers take `listable` ones)."""
    text = str(text or "")
    return {name for pattern in (_URL_HOST, _BARE_NAME, _BARE_IPV4) for match in pattern.finditer(text)
            if (name := normalize(match.group(1))) is not None}


def _sites_named(texts) -> set[str]:
    """What a list or the user's words can name: sites (`listable`) and addresses, each matched as itself."""
    return {name for text in texts for name in hosts_in(text) if listable(name) or _ip(name) is not None}


def _covers(hosts, name: str) -> bool:
    """`name` is one of `hosts` or a subdomain of one (an address only as itself)."""
    if name in hosts:
        return True
    labels = name.split(".")
    return not _address_like(name) and any(".".join(labels[i:]) in hosts for i in range(1, len(labels) - 1))


# ── what outside content named, per conversation (in memory) ─────────────────

_outside: dict[str, set[str]] = {}


def note_outside(conversation_id: str | None, text: str | None = None) -> None:
    """This conversation read outside content (`untrusted.mark_external`, a turn that carried some in); `text`, what was
    read where the caller has it, adds the sites it names."""
    if not conversation_id:
        return
    hosts = _outside.setdefault(conversation_id, set())
    if text:
        hosts.update(name for name in hosts_in(text) if listable(name))


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


async def _named(conversation_id: str | None) -> frozenset[str]:
    """The hosts the user named in this conversation: their own messages (role user), never a sub-session's brief that
    a turn wrote after reading outside content (SUB5b stores it framed, `untrusted.BRIEF_FROM_OUTSIDE`)."""
    if not conversation_id:
        return frozenset()
    from sqlalchemy import func, select
    from server.db import session as db_session
    from server.db.models import ArslanMessage
    from server.orchestrator import untrusted
    mine = (ArslanMessage.conversation_id == conversation_id, ArslanMessage.role == "user")
    try:
        async with db_session.AsyncSessionLocal() as db:
            count, last = (await db.execute(select(func.count(), func.max(ArslanMessage.id)).where(*mine))).one()
            cached = _named_cache.get(conversation_id)
            if cached is not None and cached[0] == (count, last or 0):
                return cached[1]
            texts = (await db.scalars(select(ArslanMessage.content).where(*mine))).all()
    except Exception:  # noqa: BLE001 — fails closed: messages that can't be read name no host
        return frozenset()
    named = frozenset(_sites_named(t for t in texts if not t.startswith(untrusted.BRIEF_FROM_OUTSIDE)))
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
        if not _covers(_outside.get(conversation_id or "", ()), name):
            return "unknown"
        return "allow" if await _trusted_device(name) else "outside_only"
    # ⓪Plan (2026-11-14), the address rule: after outside content an address in any spelling (dotted, decimal, hex,
    # octal, short, IPv6, IPv4-mapped; and a name ending in a number, which some resolvers read as one) counts as
    # `outside_only` unless the user named that address or listed it. The named risk: the host record can't hold an
    # address no text spells out, so an injected `curl http://1572395042/` would be `unknown` and pass. Carve-outs:
    # loopback (a, above), and the devices the user trusted (b), which count as listed. A LAN address is left to the
    # proxy's own check, which refuses it unless trusted and offers its device card (a grant here couldn't open it).
    # Before outside content an address is judged as today.
    if ip is not None and await _trusted_device(name):
        return "allow"
    if not (turn_seen or outside_seen(conversation_id)) or (ip is not None and not ip.is_global):
        return "unknown"
    return "outside_only"


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


_runs: dict[str, Run] = {}
_REFUSED_KEPT = 8


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


def end_run(run: Run | None) -> None:
    """Its token ends with it: anything that outlived it (a child left running) is refused from now on."""
    if run is not None:
        _runs.pop(run.token, None)


def run_for(token: str | None) -> Run | None:
    return _runs.get(token) if token else None


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
    command that connected, never what it would send (the proxy doesn't see it)."""
    from server.services import permissions
    why = (f"the address {host}, which you didn't name, after this conversation read outside content"
           if _address_like(normalize(host)) else
           f"{host}, a site that appeared only in outside content this conversation read (a page, a file or a tool's "
           "output), not one you named")
    return permissions.Request(
        kind="network", target=f"network:{host}", conversation_only=True,
        title=f"Let commands in this conversation connect to {host}?",
        detail=f"`{command[:300]}` tried to connect to {why}. Arslan can't see what it would send.")


async def offer(hosts, command: str, conversation_id: str | None) -> str:
    """NET-a's card after a run the proxy refused sites in: one card for up to three, "In this conversation" (one
    `network:<host>` grant each, never "Always") or no. What the model is told of the answer; "" with nobody to ask,
    where the refusal note stands alone."""
    from server.services import background_jobs, permissions
    shown = list(dict.fromkeys(hosts))[:3]
    if not shown or permissions.current_asker() is None:
        return ""
    names = ", ".join(shown)
    decisions = await permissions.decide_many(
        [request(host, command) for host in shown],
        permissions.Context(conversation_id, job_id=background_jobs._inside_job.get()),
        title=f"Let commands in this conversation connect to {names}?")
    refused = next((decision for decision in decisions if not decision.allowed), None)
    if refused is None:
        return f"The user allowed {names} for this conversation: run the command again."
    return refused.model_text or f"The user did not allow {names}."


def _reset_for_tests() -> None:
    _runs.clear()
    _outside.clear()
    _named_cache.clear()
