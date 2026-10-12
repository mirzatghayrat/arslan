"""Every outbound HTTP fetch this server makes, resolved once and pinned.

MOVED HERE, NOT REWRITTEN. This was private to ``server/registry/executors.py``, which
meant the SEARCH path could not use it — ``search_providers.py`` cannot import
``executors`` (executors already imports it, so it would cycle), and so search ran on a
bare ``httpx.AsyncClient`` with none of this applied. That was tolerable only while the
search endpoint was a hard-coded constant. It stops being tolerable the moment a
self-hosted SearXNG address typed by the user becomes the destination.

So it lives in a third module both sides import. NOT copied: every rule below was
derived from a specific attack (see the individual docstrings — DNS rebinding, CGNAT
shared address space, IDN homographs), and two copies of a security control are two
copies that drift apart while both continue to look reasonable.

``tests/server/test_pinning_is_the_same_on_both_paths.py`` runs one table of adversarial
URLs through BOTH callers and fails if their verdicts ever differ.

FAKE-IP DNS (0.1.61). A Mac behind Clash/Surge/sing-box in fake-IP mode resolves EVERY
name into 198.18.0.0/15, RFC 2544's benchmarking block, where no real host lives; the
proxy (or its TUN) maps the address back to the name. `not is_global` refused all of it,
so the web was dead on such a Mac. The exception is narrow on purpose: a NAME (never a
literal address in any spelling, never a local name) asked for over https:// on port 443,
whose IPv4 answers all lie in that block, passes, except 198.18.0.1, which Clash and mihomo
keep for the TUN's own gateway and never hand out as a fake address. It passes only when a
proxy carries the request or the system DNS is fake-IP for a public canary too. Plain http,
or any other port, to such a name is refused (`_FakeIpOnlyHttps`). A name is judged in its
canonical form (IDNA/NFKC, ASCII, lower case, no trailing dot): the one the resolver and the
HTTP stack really use, not the raw spelling in the URL.

🔴 WHAT THE EXCEPTION COSTS, AND WHAT BOUNDS IT. For such a name the guard can no longer see
the real address. The fake one stands for it, and the TUN or the proxy decides where the
request really goes, so SSRF protection for that name is DELEGATED there, as it already is
for https behind a configured proxy (see ``_pinning_disabled_by_proxy``). The TUN path says
so in the log, once per host per 10 minutes. What still holds is TLS, checked against the
real name: wherever the TUN or the proxy connects, nothing is sent until the other end
proves it is that name, which a service on the LAN or on this Mac cannot. That is why the
exception is https on 443 only. Plain http proves nothing, and the proxy or the TUN resolves
the name again and may route a LAN or loopback answer DIRECT.

Every other name is still judged by its addresses, and more strictly than before 0.1.61:
it is judged in its canonical form, and local names (dotless ones included) and hosts with
a control character in them are refused whatever DNS says.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
import time
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import getproxies, proxy_bypass

import httpx
import trafilatura

logger = logging.getLogger(__name__)

_EXTRACT_CHAR_LIMIT = 12_000
# Explicit larger reads remain bounded; ordinary reads/ingest keep the default.
_MAX_EXTRACT_CHAR_LIMIT = 40_000
# Fail fast on a slow page: the mini agent-loop has a small tool budget, so a page that hangs
# should surrender quickly (leaving budget + wall-clock for synthesis) rather than consuming the
# full loop timeout. 12s is generous for a real page while well under the loop's per-tool cap.
_FETCH_TIMEOUT = 12.0


def _is_private_host(url: str) -> bool:
    """Does this URL resolve to a loopback/private/link-local/reserved address?

    🔴 THIS IS A PREDICATE, NOT THE GATE. It answers a question about DNS at the moment
    it is asked; it does not bind that answer to the connection that follows. Use
    `_resolve_pinned` for anything that is about to open a socket. Kept because
    ingest.py's docstring and existing tests speak in its terms.
    """
    try:
        _resolve_pinned(url)
    except _BlockedHost:
        return True
    return False


def _is_non_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Anything that is not a routable public address.

    🔴 Written as `not is_global` — an ALLOW-list — rather than the enumeration
    `is_private or is_loopback or is_link_local or is_reserved` this replaces. That
    enumeration looked complete and was not: RFC 6598 shared address space
    (100.64.0.0/10) belongs to NONE of those four sets in Python's `ipaddress`, so it
    sailed straight through. That range is CGNAT — and it is also the whole of a
    Tailscale tailnet, which this project's own remote-control design uses. An attacker
    needed no DNS trickery at all for that one: a static A record at 100.64.x.x reached
    the operator's private overlay, which is cheaper than the rebinding attack the rest
    of this module exists to stop.

    An enumeration of bad ranges is a list someone has to keep complete forever;
    `is_global` fails closed on every block nobody has thought of yet. `is_multicast`
    needs its own term because multicast addresses report is_global=True (a TCP connect
    to one fails at the OS level anyway, but the guard should not depend on that).
    """
    return (not ip.is_global) or ip.is_multicast


#: RFC 2544's benchmarking block. No real host lives here; fake-IP DNS (Clash, Surge,
#: Stash, sing-box, Shadowrocket) hands these out so the proxy can map them back to names.
_FAKE_IP_NET = ipaddress.ip_network("198.18.0.0/15")
#: The TUN's own address. Clash and mihomo keep it for the gateway and never hand it out as a
#: name's fake address, and local services (AirPlay, rapportd) listen on it.
_FAKE_IP_GATEWAY = ipaddress.ip_address("198.18.0.1")
#: The (scheme, port) the exception is for, and the only one. TLS checked against the real name
#: is what bounds it (module docstring). Plain http proves nothing: the proxy or the TUN
#: resolves the name again and may route a LAN or loopback answer DIRECT, a card-free read of
#: port-80 services on the LAN or on this Mac. Any other port on a fake address could be a
#: service on this very Mac, reached through the TUN. Port 80 serves nothing under https only:
#: the browser's CONNECT is always 443.
_FAKE_IP_WEB = ("https", 443)
#: A public name whose answer says whether the system DNS is fake-IP. IANA's, stable.
_FAKE_IP_CANARY = "example.com"
#: Zones that are never on the public internet, whatever a resolver answers for them. A name
#: is local when it IS one of these or sits below one (see `_is_local_name`). Neither
#: `localdomain` nor `home` is delegated on the public internet.
_LOCAL_ZONES = ("localhost", "local", "lan", "internal", "intranet", "home.arpa", "corp",
                "localdomain", "home")
#: The TUN path warns that protection is delegated, at most once per host per this many seconds.
_FAKE_IP_WARN_EVERY = 600.0
#: ... and remembers at most this many hosts, so a long-lived server cannot grow without bound.
_FAKE_IP_WARN_HOSTS = 256
#: host -> time.monotonic() of its last warning. Module state, so tests that look at the warning
#: reset it.
_fake_ip_warned: dict[str, float] = {}


def _canonical_host(host: str) -> str:
    """The name the resolver and the HTTP stack will really use: IDNA/NFKC-normalised, so that
    fullwidth digits and letters and the dots U+3002, U+FF0E and U+FF61 become plain ASCII;
    lower case; no trailing dot.

    🔴 Judge THIS, never the raw `urlparse` host. `getaddrinfo`, httpx and `_ascii_host` all
    normalise afterwards, so a literal address or a local name written in fullwidth, or with
    ideographic full stops, looks like a public name to a check on the raw spelling, and is
    the address or the local name once it is used.
    """
    return _ascii_host(host).lower().rstrip(".")


def _is_local_name(name: str) -> bool:
    """A name that is never on the public internet, whatever a resolver answers for it: a
    name with no dot at all (the machine's search domains resolve it, so it names something
    on the local network), or one of the private zones itself, or a name below one.

    Takes the CANONICAL host (see `_canonical_host`) and is for names: an address literal has
    no zone, and `_resolve_pinned` judges those by their address. An empty host is not a local
    name here, and it is still refused: `getaddrinfo("")` answers loopback, and
    `_is_non_public` refuses that.
    """
    if not name:
        return False
    return "." not in name or any(name == zone or name.endswith("." + zone)
                                  for zone in _LOCAL_ZONES)


def _is_ip_literal(host: str) -> bool:
    """An address, however it is spelled: whatever `ipaddress` parses (IPv6 included), or what
    the OS resolver reads as one and `ipaddress` does not (`0xc6120021`, `198.18.33`, a bare
    decimal). Such a spelling is an address, never a name, so it is never "fake". Takes the
    CANONICAL host (see `_canonical_host`)."""
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    try:
        socket.inet_aton(host)
    except (OSError, ValueError):
        return False
    return True


def _all_fake_v4(ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address]) -> bool:
    """Every IPv4 answer lies in the fake-IP block, and none is the TUN's own gateway. IPv6
    answers are ignored: in fake mode nothing connects to them (we pin the IPv4, or the proxy
    resolves the name itself)."""
    v4 = [ip for ip in ips if ip.version == 4]
    return bool(v4) and all(ip in _FAKE_IP_NET and ip != _FAKE_IP_GATEWAY for ip in v4)


def _fake_ip_dns() -> bool:
    """Is this Mac's DNS fake-IP (a TUN-mode proxy)? Asked only after an answer was already
    fake, so an ordinary lookup never pays for a second one."""
    try:
        infos = socket.getaddrinfo(_FAKE_IP_CANARY, 443, type=socket.SOCK_STREAM)
    except OSError:
        return False
    return _all_fake_v4([ipaddress.ip_address(info[4][0]) for info in infos])


def _warn_fake_ip(host: str, ip: str) -> None:
    """Say that a faked name's real destination is decided by the TUN or the proxy and not by
    this guard: at most once per host per 10 minutes, in the style of the proxy branch's
    warning in `pinned_request`, which this path would otherwise lack."""
    now = time.monotonic()
    last = _fake_ip_warned.get(host)
    if last is not None and now - last < _FAKE_IP_WARN_EVERY:
        return
    if len(_fake_ip_warned) >= _FAKE_IP_WARN_HOSTS:
        for stale, then in list(_fake_ip_warned.items()):
            if now - then >= _FAKE_IP_WARN_EVERY:
                _fake_ip_warned.pop(stale, None)
        if len(_fake_ip_warned) >= _FAKE_IP_WARN_HOSTS:
            _fake_ip_warned.clear()
    _fake_ip_warned[host] = now
    logger.warning("fake-IP DNS: %s → %s; the TUN/proxy maps it back and decides the real "
                   "destination — SSRF protection is delegated there", host, ip)


class _BlockedHost(Exception):
    """The host may not be fetched: it is a local name, or it resolves to a non-public
    address. The subclasses are the other refusals; callers catch them all as this."""


class _Unresolvable(_BlockedHost):
    """The host did not resolve. Still a refusal (failure is closed), but no address was
    judged and found private, so `categorize` names it apart: a dead resolver is not a
    blocked network, and must not wear a blocked network's advice."""


class _NotConfiguredHost(_BlockedHost):
    """`allow_host` is set and this is not it: every hop of a configured search host must be
    that host. Named apart from a refused address by `categorize`."""


class _FakeIpOnlyHttps(_BlockedHost):
    """A name behind fake-IP DNS asked for over plain http, or on a port other than 443."""


class _InvalidHost(_BlockedHost):
    """The host holds a C0 control character or DEL, so it is no host name at all."""


def _resolve_pinned(url: str, *, allow_host: str | None = None,
                    via_proxy: bool = False) -> tuple[str, str, int]:
    """Resolve ONCE, validate EVERY answer, and return the address we will connect to.

    FU-1 (DNS rebinding). The old code checked `getaddrinfo(host)` and then handed the
    HOSTNAME to httpx, which resolved it again before connecting. Nothing tied the
    checked answer to the used one, so an attacker serving TTL=0 DNS answers the check
    with a public IP and the connect with 127.0.0.1 — walking straight past a guard that
    looks correct. Per-hop revalidation (added earlier for redirects) did not help: every
    hop had the same split.

    So the resolution result is PINNED and the caller connects to the returned IP.

    Every answer must pass. Picking "the first public one" out of a mixed answer set
    would let an attacker pad the response with a public address to get through, and the
    only reason to return several is to have the client try several.

    We pin the FIRST validated address rather than failing over between them: failover
    would put "which address did we actually reach" back in the attacker's hands, which
    is the property this function exists to take away. The cost is that an unreachable
    first address fails the fetch instead of retrying — acceptable for a fetch tool.

    Returns (pinned_ip, host, port). Raises _BlockedHost on refusal — unresolvable
    included (`_Unresolvable`), so failure is closed.

    🔴 AN EXCEPTION to "the address we validated is the address we connect to" is a NAME
    under fake-IP DNS (module docstring); the other is https through a proxy, where we never
    connect at all (`_pinning_disabled_by_proxy`). A fake answer is a stand-in that the TUN
    or the proxy maps back to the name, so the guard cannot see the real address and that
    protection is delegated there (and logged). It holds for https:// on port 443 only, where
    TLS against the real name bounds it; plain http or another port to such a name is
    refused (`_FakeIpOnlyHttps`). Everything else about it is still judged here: literal
    address, local name, the TUN gateway, and the host is judged in its canonical form.

    A host with a control character in it is refused before anything else (`_InvalidHost`),
    a configured `allow_host` included.

    `via_proxy`: a proxy will resolve and connect, so a fake-IP answer needs no further
    proof.
    """
    parts = urlparse(url)
    host = parts.hostname or ""
    # 0.1.61 (final review): a C0 control character or DEL makes the host no name at all, and
    # every layer below reads it differently. `198.18.0.33\x00.example.com` was taken for a
    # NAME (`inet_aton` refuses the NUL, so it is no literal) while the C resolver stops at
    # the NUL and answers the address 198.18.0.33, and in fake-IP mode that name passed. So it
    # is refused here, before the port is read, before `allow_host` and before any lookup.
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in host):
        raise _InvalidHost(f"{host!r} is not a host name: it holds a control character")
    port = parts.port or (443 if parts.scheme == "https" else 80)

    # `allow_host` WIDENS and NARROWS in the same breath, and the two halves are why
    # it is safe. A self-hosted search instance most plausibly lives on 192.168.x or
    # 100.64.x, so refusing every non-public address would refuse the feature — but
    # the address is only trusted because a HUMAN typed it into Settings. The model
    # supplies the query and never the destination. So the moment we relax the
    # address class, we pin the destination to that single host, and every hop
    # (redirects included, since this runs per hop) must still be it.
    #
    # 🔴 EQUALITY, not a prefix or a substring: `startswith` would let 192.168.1.10
    # admit 192.168.1.100. And it is a PARAMETER — never module state, no flag and no
    # contextvar — because web_extract and the DuckDuckGo fallback are paths where the
    # model does influence the destination, and they must not be able to inherit this.
    exempt = False
    if allow_host is not None:
        if _ascii_host(host) != _ascii_host(allow_host):
            raise _NotConfiguredHost(
                f"{host} is not the configured host ({allow_host})")
        exempt = True

    # 🔴 Judge the CANONICAL name, never the raw spelling `urlparse` handed us: the resolver,
    # httpx and the Host header all normalise it afterwards (see `_canonical_host`), so a
    # fullwidth `１２７.０.０.１` or `nas.ｌａｎ` is the literal address or the local name it
    # turns into. The lookup below still gets the raw `host`, which CPython IDNA-encodes
    # with the same codec.
    canon = _canonical_host(host)
    literal = _is_ip_literal(canon)
    if not exempt and not literal and _is_local_name(canon):
        raise _BlockedHost(f"{host} is a local network name")

    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise _Unresolvable(f"cannot resolve {host}") from exc
    if not infos:
        raise _Unresolvable(f"cannot resolve {host}")
    ips = [ipaddress.ip_address(info[4][0]) for info in infos]

    # 0.1.61: fake-IP DNS. A NAME (a literal address is never "fake") whose IPv4 answers all
    # lie in 198.18.0.0/15, the TUN's own 198.18.0.1 excepted, stands for itself: the proxy
    # resolves it, or the TUN maps the address back to it. The canary is only consulted here,
    # after the answers were already fake, so ordinary lookups still resolve exactly once. It
    # is consulted for every scheme and port: when it says this DNS is NOT fake-IP, such an
    # answer is a real non-public address and is refused as one, below. The guard cannot see
    # where such a name really goes: through a proxy that is already logged by
    # `pinned_request`, on the TUN path we say so here.
    if not exempt and not literal and _all_fake_v4(ips) and (via_proxy or _fake_ip_dns()):
        if (parts.scheme, port) != _FAKE_IP_WEB:
            # Only TLS against the real name bounds where the proxy or the TUN sends it.
            raise _FakeIpOnlyHttps(
                f"{host}: behind fake-IP DNS only https:// on port 443 is fetched")
        pinned = str(next(ip for ip in ips if ip.version == 4))
        if not via_proxy:
            _warn_fake_ip(canon, pinned)
        return pinned, host, port

    pinned = None
    for ip in ips:
        if not exempt and _is_non_public(ip):
            raise _BlockedHost(f"{host} resolves to a private or internal address")
        if pinned is None:
            pinned = str(ip)
    assert pinned is not None
    return pinned, host, port


def _ascii_host(host: str) -> str:
    """IDNA/punycode form, because the Host header and SNI are ASCII-only.

    httpx normally does this itself from the URL. Once we set `Host` EXPLICITLY that
    stops happening, and a raw Unicode value raises UnicodeEncodeError while the request
    is being built — so every internationalised domain would fail, reported as a generic
    "unexpected error". Non-encodable input is handed back unchanged; it is either
    already ASCII or malformed, and the resolve step above has the final say either way.
    """
    try:
        return host.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        return host


def _pinning_disabled_by_proxy(url: str) -> bool:
    """True only for the ONE combination where pinning cannot work: https via a proxy.

    On httpcore's CONNECT-tunnel path the `sni_hostname` extension is IGNORED — the
    tunnel passes `self._remote_origin.host` as `server_hostname`, which after our
    rewrite is the IP literal, so certificate validation would be attempted against the
    IP and every https fetch would fail. Verified against the installed httpcore.

    PLAIN HTTP through a proxy still pins: the proxy connects to whatever address the
    absolute-form request line names, and no SNI is involved. Only the https+proxy cell
    degrades, and it degrades to "the proxy decides", which is the honest description of
    that configuration anyway — with a proxy WE never resolve or connect, so no rewrite
    of ours could have carried the guarantee. TLS against the real name still holds there,
    and under fake-IP DNS it is all that holds, so https on port 443 is the only request a
    faked name gets at all: a plain-http pin to a fake address is a stand-in the proxy maps
    back to the name and resolves itself, and nothing then proves who answers, so
    `_resolve_pinned` refuses it (`_FakeIpOnlyHttps`).

    🔴 This is not hypothetical: a developer machine in this project has
    HTTPS_PROXY=http://127.0.0.1:7899 set, which means https fetches there run in the
    delegated mode. That is why the degradation is LOGGED rather than silent — an
    install whose protection is delegated should be able to find that out.

    Reads the same environment `trust_env` consults, including NO_PROXY.
    """
    parts = urlparse(url)
    if parts.scheme != "https":
        return False
    proxies = getproxies()
    if not proxies:
        return False
    if proxy_bypass(parts.hostname or ""):
        return False
    return "https" in proxies or "all" in proxies


def _pinned_request_args(url: str, *, allow_host: str | None = None) -> tuple[str, dict, dict]:
    """Rewrite `url` to point at its pinned address, preserving everything else about
    the request.

    `Host` preserves virtual hosting, and `sni_hostname` drives the TLS handshake so the
    certificate is still verified against the REAL hostname. Without the latter, pinning
    would silently downgrade TLS to "any certificate this IP presents", trading an SSRF
    hole for a MITM one. httpcore reads that extension as `server_hostname`; the floor in
    pyproject.toml exists to keep it doing so.

    USERINFO is carried across. httpx derives `Authorization: Basic` from the URL, so
    dropping it would fetch a credentialed URL anonymously and return whatever the server
    shows an anonymous visitor — as `ok: True`, with no sign anything was lost.
    """
    ip, host, port = _resolve_pinned(url, allow_host=allow_host)
    parts = urlparse(url)
    ascii_host = _ascii_host(host)
    literal = f"[{ip}]" if ":" in ip else ip
    netloc = f"{literal}:{port}" if parts.port else literal
    if parts.username:
        cred = parts.username + (f":{parts.password}" if parts.password else "")
        netloc = f"{cred}@{netloc}"
    pinned_url = urlunparse(parts._replace(netloc=netloc))
    # bracket an IPv6 literal in the Host header too, or "::1:8443" is ambiguous
    header_host = f"[{ascii_host}]" if ":" in ascii_host else ascii_host
    host_header = f"{header_host}:{parts.port}" if parts.port else header_host
    return pinned_url, {"Host": host_header}, {"sni_hostname": ascii_host}


#: HTTP statuses whose REMEDIES differ. Named rather than numbered because the number
#: is a fact and the name is the fact plus what to do about it: wait, top up, or
#: replace the key. Codes we have no advice for keep their number — inventing a
#: category for them would read as understanding we do not have.
_STATUS_MEANING = {
    401: "key-rejected",
    403: "key-rejected",
    402: "quota-exhausted",
    429: "rate-limited",
}

#: The one category worth trying again. A rejected key retried is a rejected key,
#: more slowly.
RETRYABLE = frozenset({"rate-limited"})


def categorize(exc: Exception) -> str:
    """Name the failure in terms a caller can act on.

    🔴 BRANCH ORDER IS LOAD-BEARING. ``HTTPStatusError`` and ``TimeoutException`` are
    BOTH subclasses of ``httpx.HTTPError``, so moving the HTTPError arm above them
    collapses every rate limit into "network error" — and the user gets told to check
    their connection when the real answer is "wait a minute". Two tests pin this.

    The same goes for the guard's own refusals: `_Unresolvable`, `_NotConfiguredHost`,
    `_FakeIpOnlyHttps` and `_InvalidHost` are `_BlockedHost`s, so they are tested first or
    they would all be reported as a blocked network. That matters beyond wording:
    `executors._auto` must not mistake a host that will not resolve for an anti-bot block,
    and plain http behind fake-IP DNS is refused for its scheme, not for its address.
    """
    if isinstance(exc, _Unresolvable):
        return "cannot resolve"
    if isinstance(exc, _NotConfiguredHost):
        return "not the configured search host"
    if isinstance(exc, _FakeIpOnlyHttps):
        return "behind fake-IP DNS only https:// on port 443 is fetched"
    if isinstance(exc, _InvalidHost):
        return "invalid host name"
    if isinstance(exc, _BlockedHost):
        # The guard's own refusal of an address or a local name: say so, instead of
        # "unexpected error" (0.1.61 §E3).
        return "blocked address (local network)"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return _STATUS_MEANING.get(code, f"http {code}")
    if isinstance(exc, httpx.HTTPError):
        return "network error"
    return "unexpected error"


def _categorize_exc(exc: Exception) -> str:
    """Back-compat alias. web_extract's callers and their tests speak in these terms."""
    return categorize(exc)


_MAX_REDIRECTS = 5


def _build_client() -> httpx.AsyncClient:
    # follow_redirects=False on purpose: we follow manually so every hop is resolved,
    # validated and PINNED individually (see _resolve_pinned).
    #
    # 🔴 PROXY SCOPE, stated honestly. `trust_env` is left at its default (True), so a
    # configured HTTP_PROXY/HTTPS_PROXY/ALL_PROXY still applies — deliberately, because
    # turning it off would break every install that can only reach the internet through
    # one. But when a proxy IS configured the connection is made BY THE PROXY, so what
    # the proxy does with the address is outside this guard: the SSRF protection is
    # DELEGATED to it, not enforced here. Do not describe the proxy case as carrying the
    # same guarantee. Without a proxy — the default — the pinning below is the guarantee,
    # with one exception: under fake-IP DNS (a TUN) a name's answer is a stand-in that the
    # TUN maps back to the name, so the guard cannot see its real address and that
    # protection is delegated too, for https on port 443 only, where TLS against the real
    # name bounds it (see `_resolve_pinned`; the TUN path logs it).
    # max_keepalive_connections=0: after pinning, httpcore keys its pool on
    # (scheme, host, port) where host is now the IP — so two DIFFERENT hostnames that
    # resolve to the same address would share a connection, and the second hop would
    # ride the first hop's TLS session and SNI. For a one-shot fetch tool, not reusing
    # connections costs nothing and removes that confusion entirely.
    return httpx.AsyncClient(timeout=_FETCH_TIMEOUT, follow_redirects=False,
                             limits=httpx.Limits(max_keepalive_connections=0))


#: Redirect statuses that turn the follow-up request into a bodyless GET. 307 and 308
#: are deliberately absent: they exist to say "the same request, at a new address".
#: httpx applies these rules inside `follow_redirects`, which this module cannot use
#: (every hop has to be re-pinned), so they are restated here rather than inherited.
_METHOD_CHANGING_REDIRECTS = frozenset({301, 302, 303})


async def pinned_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    json: object | None = None,
    data: dict[str, str] | None = None,
    allow_host: str | None = None,
    max_redirects: int = _MAX_REDIRECTS,
) -> httpx.Response:
    """A request whose every hop is resolved once, validated, and PINNED.

    This is the path `web_extract` has always used, given a name and a method so the
    search providers can share it instead of growing a second copy. Two copies of SSRF
    logic do not stay identical, and the copy nobody is looking at is the one that gets
    weaker — which is why this is an extraction rather than a new module.

    🔴 The body is dropped when a redirect changes the method (see
    _METHOD_CHANGING_REDIRECTS). Carrying a POST body onto a GET would replay a
    submission at a destination that only asked us to look elsewhere.

    Returns the final response WITHOUT `raise_for_status()`. The caller decides: a
    connection test needs to read the status itself, and a helper that raised would
    force it to catch its own subject.
    """
    async with _build_client() as client:
        current = url
        cur_method = method.upper()
        cur_json, cur_data = json, data
        for _ in range(max_redirects):
            # Resolve-and-pin EVERY hop, including the first. Sending the hostname and
            # letting httpx resolve it is precisely the rebinding hole (see
            # _resolve_pinned); a redirect target is no more trustworthy than the
            # original URL, so it goes through the identical path.
            if _pinning_disabled_by_proxy(current):
                # Still validate — it blocks the obvious cases — but say plainly that the
                # guarantee is the proxy's here, so a delegated install is discoverable
                # instead of quietly believing it is protected.
                _resolve_pinned(current, allow_host=allow_host, via_proxy=True)
                logger.warning(
                    "pinned_request: https via a configured proxy — address pinning is "
                    "disabled for %s and SSRF protection is delegated to the proxy",
                    urlparse(current).hostname)
                resp = await client.request(cur_method, current, headers=headers,
                                            params=params, json=cur_json, data=cur_data)
            else:
                pinned_url, pin_headers, extensions = _pinned_request_args(
                    current, allow_host=allow_host)
                # Pinning's own headers go last: a caller must not be able to overwrite
                # `Host`, which is what preserves virtual hosting and keeps the request
                # pointed at the address that was validated.
                merged = {**(headers or {}), **pin_headers}
                resp = await client.request(cur_method, pinned_url, headers=merged,
                                            params=params, json=cur_json, data=cur_data,
                                            extensions=extensions)
            if resp.is_redirect:
                location = resp.headers.get("location", "")
                if not location:
                    raise httpx.HTTPError("redirect without a Location header")
                if resp.status_code in _METHOD_CHANGING_REDIRECTS and cur_method != "GET":
                    cur_method, cur_json, cur_data = "GET", None, None
                # resolve against the ORIGINAL url, not the pinned one — a relative
                # Location must not inherit the IP literal as its base.
                current = urljoin(current, location)
                continue
            return resp
        raise httpx.HTTPError("too many redirects")


async def pinned_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    allow_host: str | None = None,
    max_redirects: int = _MAX_REDIRECTS,
) -> httpx.Response:
    """The readable spelling of `pinned_request("GET", ...)`.

    A wrapper, never a second implementation — the whole point of this module is that
    there is exactly one place where an outbound address is decided.

    Returns the final response WITHOUT `raise_for_status()`, exactly as
    `pinned_request` does.
    """
    return await pinned_request("GET", url, headers=headers, params=params,
                                allow_host=allow_host, max_redirects=max_redirects)


async def _fetch_text(url: str) -> str:
    resp = await pinned_get(url)
    resp.raise_for_status()
    media_type = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type in {"text/plain", "text/markdown"}:
        # Treat literal code/README placeholders as data, not HTML tags. The
        # executor's character cap and untrusted-result framing still apply.
        return resp.text
    extracted = trafilatura.extract(resp.text)
    return extracted or ""
