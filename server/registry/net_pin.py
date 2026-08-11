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
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import getproxies, proxy_bypass

import httpx
import trafilatura

logger = logging.getLogger(__name__)

_EXTRACT_CHAR_LIMIT = 12_000
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


class _BlockedHost(Exception):
    """The host may not be fetched — unresolvable, or resolves to a non-public address."""


def _resolve_pinned(url: str, *, allow_host: str | None = None) -> tuple[str, str, int]:
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
    included, so failure is closed.
    """
    parts = urlparse(url)
    host = parts.hostname or ""
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
            raise _BlockedHost(
                f"{host} is not the configured host ({allow_host})")
        exempt = True

    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise _BlockedHost(f"cannot resolve {host}") from exc
    if not infos:
        raise _BlockedHost(f"cannot resolve {host}")

    pinned = None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
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
    of ours could have carried the guarantee.

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
    """
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
    # same guarantee. Without a proxy — the default — the pinning below is the guarantee.
    # max_keepalive_connections=0: after pinning, httpcore keys its pool on
    # (scheme, host, port) where host is now the IP — so two DIFFERENT hostnames that
    # resolve to the same address would share a connection, and the second hop would
    # ride the first hop's TLS session and SNI. For a one-shot fetch tool, not reusing
    # connections costs nothing and removes that confusion entirely.
    return httpx.AsyncClient(timeout=_FETCH_TIMEOUT, follow_redirects=False,
                             limits=httpx.Limits(max_keepalive_connections=0))


async def pinned_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    allow_host: str | None = None,
    max_redirects: int = _MAX_REDIRECTS,
) -> httpx.Response:
    """A GET whose every hop is resolved once, validated, and PINNED.

    This is the path `web_extract` has always used, given a name so the search
    providers can share it instead of growing a second copy. Two copies of SSRF logic
    do not stay identical, and the copy nobody is looking at is the one that gets
    weaker — which is the whole reason this is an extraction rather than a new module.

    Returns the final response WITHOUT `raise_for_status()`. The caller decides: a
    connection test needs to read the status itself, and a helper that raised would
    force it to catch its own subject.
    """
    async with _build_client() as client:
        current = url
        for _ in range(max_redirects):
            # Resolve-and-pin EVERY hop, including the first. Sending the hostname and
            # letting httpx resolve it is precisely the rebinding hole (see
            # _resolve_pinned); a redirect target is no more trustworthy than the
            # original URL, so it goes through the identical path.
            if _pinning_disabled_by_proxy(current):
                # Still validate — it blocks the obvious cases — but say plainly that the
                # guarantee is the proxy's here, so a delegated install is discoverable
                # instead of quietly believing it is protected.
                _resolve_pinned(current, allow_host=allow_host)
                logger.warning(
                    "pinned_get: https via a configured proxy — address pinning is "
                    "disabled for %s and SSRF protection is delegated to the proxy",
                    urlparse(current).hostname)
                resp = await client.get(current, headers=headers, params=params)
            else:
                pinned_url, pin_headers, extensions = _pinned_request_args(
                    current, allow_host=allow_host)
                # Pinning's own headers go first: a caller must not be able to
                # overwrite `Host`, which is what preserves virtual hosting and keeps
                # the request pointed where it was validated.
                merged = {**(headers or {}), **pin_headers}
                resp = await client.get(pinned_url, headers=merged, params=params,
                                        extensions=extensions)
            if resp.is_redirect:
                location = resp.headers.get("location", "")
                if not location:
                    raise httpx.HTTPError("redirect without a Location header")
                # resolve against the ORIGINAL url, not the pinned one — a relative
                # Location must not inherit the IP literal as its base.
                current = urljoin(current, location)
                continue
            return resp
        raise httpx.HTTPError("too many redirects")


async def _fetch_text(url: str) -> str:
    resp = await pinned_get(url)
    resp.raise_for_status()
    extracted = trafilatura.extract(resp.text)
    return extracted or ""

