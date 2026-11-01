"""Which MCP Registry entries get a one-click card (v0.1.64 CAP4a-3c, the user's list D, 2026-10-31).

- **A package** (npm, PyPI, mcpb) is one-click when its Registry namespace is a verified domain, any of them, or
  one of the listed GitHub organizations. An organization is matched by its numeric id, checked against GitHub
  before the card, so a login that changed hands is not trusted.
- **A remote server** is one-click only from a listed vendor domain, and only when its URL's host is that domain, a
  subdomain of it, or a host the list names for it. A remote published by a GitHub account is manual-only (the
  user's Q2): it runs elsewhere, and nothing verified its host.
- **Everything else is added by hand** (Capabilities, Connections, add by hand). What is one-click still gets the
  lock, the scan and the sandbox.

Skills are not held to this list: they keep the pinned commit, the scan, the hashes and the card (CAP4a-1).
Installed servers' updates are not held to the list either (the user approved that source), but an update published
by a listed organization is checked by its id like a new card (#584 review 2): a login can change hands.

A vendor's subdomains count as the vendor (`com.microsoft.azure` is Microsoft): the Registry verified that the
publisher controls the subdomain. A subdomain someone else took over (a dangling CNAME) would pass too: a stated limit.

The list is the user's: stored in settings under `SETTING_KEY`, shown and edited through `/capability-allowlist`.
`DEFAULT` is its first version: list B's vendor domains and organizations, measured against the public Registry on
2026-10-31 (#563, comment 6527457019).
"""
from __future__ import annotations

import json
import logging
import re
import time
from urllib.parse import urlsplit

import httpx

from arslan.aio import within
from server.db import session as db_session

logger = logging.getLogger(__name__)

SETTING_KEY = "capability_allowlist"
GITHUB = "https://api.github.com"
ACCOUNT_CACHE_S = 24 * 3600
TIMEOUT_S = 10.0
#: One limit for an account check, and the most of GitHub's answer read (#625 review I-2): an account is ~1 KB.
ACCOUNT_DEADLINE_S = 20.0
ACCOUNT_MAX_BYTES = 64 * 1024

#: The first version of the list (the user's D). Domains are the vendors' own (their remotes, and their packages
#: when `packages_from_any_domain` is off); `hosts` names more hosts a vendor's remotes run on; `accounts` are
#: GitHub organizations by numeric id (read from api.github.com on 2026-10-31; every one is an Organization).
DEFAULT: dict = {
    "packages_from_any_domain": True,
    "domains": sorted([
        "modelcontextprotocol.io", "anthropic.com", "github.com", "microsoft.com", "google.com", "cloudflare.com",
        "stripe.com", "notion.so", "notion.com", "atlassian.com", "linear.app", "sentry.io", "vercel.com",
        "supabase.com", "figma.com", "hubspot.com", "asana.com", "zapier.com", "apify.com", "browserbase.com",
        "neon.tech", "mongodb.com", "elastic.co", "grafana.com", "datadoghq.com", "pagerduty.com", "twilio.com",
        "shopify.com", "box.com", "dropbox.com", "monday.com", "canva.com", "gitlab.com", "amazon.com",
        "huggingface.co", "paypal.com", "playwright.dev", "jetbrains.com", "docker.com", "postman.com", "slack.com",
        "salesforce.com"]),
    # Microsoft's own top-level domain: its Registry remotes run on agent365.svc.cloud.microsoft.
    "hosts": {"microsoft.com": ["cloud.microsoft"]},
    "accounts": {
        "modelcontextprotocol": 182288589, "anthropics": 76263028, "github": 9919, "microsoft": 6154722,
        "google": 1342004, "cloudflare": 314135, "stripe": 856813, "makenotion": 4792552, "atlassian": 168166,
        "getsentry": 1396951, "vercel": 14985020, "supabase-community": 87650496, "figma": 5155369,
        "hubspot": 326419, "apify": 24586296, "browserbase": 158221360, "neondatabase": 77690634,
        "mongodb-js": 11214950, "elastic": 6764390, "grafana": 7195757, "awslabs": 3299148, "huggingface": 25720743,
        "paypal": 476675, "jetbrains": 878437, "docker": 5429470, "postmanlabs": 10251060, "shopify": 8085},
}

#: Why a Registry entry has no one-click card (`Candidate.by_hand`).
REMOTE_NOT_HTTPS = "remote_not_https"
PUBLISHER_UNKNOWN = "publisher_unknown"
PUBLISHER_NOT_LISTED = "publisher_not_listed"
REMOTE_FROM_AN_ACCOUNT = "remote_from_an_account"
REMOTE_HOST_NOT_THE_PUBLISHERS = "remote_host_not_the_publishers"
ACCOUNT_CHANGED_HANDS = "account_changed_hands"
ACCOUNT_NOT_CHECKED = "account_not_checked"

_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_DOMAIN = re.compile(rf"(?:{_LABEL}\.)+{_LABEL}")
_LOGIN = re.compile(r"[a-z0-9](?:-?[a-z0-9]){0,38}")
MAX_ENTRIES = 500


class AllowlistError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def validate(data) -> dict:
    """The list as stored: lower-case domains, hosts per listed domain, logins with a positive numeric id. Anything
    else is refused whole (`AllowlistError`), never half saved."""
    if not isinstance(data, dict):
        raise AllowlistError("not_a_list")
    flag = data.get("packages_from_any_domain", True)
    if not isinstance(flag, bool):
        raise AllowlistError("packages_from_any_domain")
    domains = data.get("domains") or []
    if not isinstance(domains, list) or len(domains) > MAX_ENTRIES or not all(
            isinstance(d, str) and len(d) <= 253 and _DOMAIN.fullmatch(d) for d in domains):
        raise AllowlistError("domains")
    hosts = data.get("hosts") or {}
    if not isinstance(hosts, dict) or len(hosts) > MAX_ENTRIES or not all(
            d in domains and isinstance(hs, list) and len(hs) <= 20
            and all(isinstance(h, str) and len(h) <= 253 and _DOMAIN.fullmatch(h) for h in hs)
            for d, hs in hosts.items()):
        raise AllowlistError("hosts")
    accounts = data.get("accounts") or {}
    if not isinstance(accounts, dict) or len(accounts) > MAX_ENTRIES or not all(
            isinstance(login, str) and _LOGIN.fullmatch(login) and type(i) is int and i > 0
            for login, i in accounts.items()):
        raise AllowlistError("accounts")
    return {"packages_from_any_domain": flag, "domains": sorted(set(domains)),
            "hosts": {d: sorted(set(hs)) for d, hs in sorted(hosts.items())},
            "accounts": dict(sorted(accounts.items()))}


#: Nothing is one-click: the list Arslan uses when the user's saved list cannot be read (#584 review 1). DEFAULT
#: could be wider than what the user saved, so a failed read never falls back to it.
CLOSED: dict = {"packages_from_any_domain": False, "domains": [], "hosts": {}, "accounts": {}}


async def current() -> dict:
    """The user's list; DEFAULT when none is saved. A saved list that cannot be read (the read failed, or the row no
    longer validates) is CLOSED, never DEFAULT, which may be wider than it (logged)."""
    from sqlalchemy.exc import OperationalError
    from server.services import settings_service
    try:
        async with db_session.AsyncSessionLocal() as db:
            raw = await settings_service._get_raw(db, SETTING_KEY)
    except OperationalError as exc:
        if "no such table" in str(exc):          # a database with no settings table at all: nothing was saved
            return validate(DEFAULT)
        logger.warning("capability allowlist not read (%s): nothing is one-click until it reads", type(exc).__name__)
        return dict(CLOSED)
    except Exception as exc:  # noqa: BLE001 — any other failed read: closed, never wider
        logger.warning("capability allowlist not read (%s): nothing is one-click until it reads", type(exc).__name__)
        return dict(CLOSED)
    if raw is None:
        return validate(DEFAULT)
    try:
        return validate(json.loads(raw))
    except (ValueError, TypeError) as exc:
        logger.warning("capability allowlist unreadable (%s): nothing is one-click until it is saved again", exc)
        return dict(CLOSED)


async def save(data) -> dict:
    from server.services import settings_service
    clean = validate(data)
    async with db_session.AsyncSessionLocal() as db:
        await settings_service._set_raw(db, SETTING_KEY, json.dumps(clean))
        await db.commit()
    return clean


async def reset() -> dict:
    from server.db.models import Setting
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(Setting, SETTING_KEY)
        if row is not None:
            await db.delete(row)
            await db.commit()
    return validate(DEFAULT)


def _under(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def _vendor(domain: str, allow: dict) -> str | None:
    """The listed vendor domain a publisher's domain is (or is a subdomain of)."""
    return next((d for d in allow["domains"] if _under(domain, d)), None)


def verdict(c: dict, allow: dict) -> str | None:
    """None when this candidate gets a one-click card, else why it is added by hand. Only Registry MCP entries are
    held to the list; an organization's id is checked later, before the card (`confirm_account`)."""
    from server.services import capability_search
    if c.get("kind") != "mcp" or c.get("source") != "registry":
        return None
    who = capability_search.publisher_of(c)
    if who is None:
        return PUBLISHER_UNKNOWN
    if c.get("runtime") == "remote":
        if who["kind"] != "domain":
            return REMOTE_FROM_AN_ACCOUNT
        vendor = _vendor(who["value"], allow)
        if vendor is None:
            return PUBLISHER_NOT_LISTED
        try:
            parts = urlsplit(str((c.get("remote") or {}).get("url") or ""))
            host = (parts.hostname or "").lower().rstrip(".")
        except ValueError:                      # #584 review 7: a URL urlsplit refuses is no host of the vendor's
            return REMOTE_HOST_NOT_THE_PUBLISHERS
        if not host or not any(_under(host, d) for d in [vendor, *allow["hosts"].get(vendor, [])]):
            return REMOTE_HOST_NOT_THE_PUBLISHERS
        if parts.scheme.lower() != "https":     # #584 review 4: the key the card asks for travels in a header
            return REMOTE_NOT_HTTPS
        return None
    if who["kind"] == "domain":
        return None if allow["packages_from_any_domain"] or _vendor(who["value"], allow) else PUBLISHER_NOT_LISTED
    return None if who["value"].lower() in allow["accounts"] else PUBLISHER_NOT_LISTED


_IDS: dict[str, tuple[float, int | None]] = {}


async def _account_id(login: str, *, fresh: bool = False) -> int | None:
    """The numeric id GitHub gives `login` now, or None for no such account (a 404, cached a day). Anything else is
    no answer and raises, with nothing cached: a rate limit, an outage, a redirect, or a 200 that names no integer
    id (#625 review L-1, L-3). `fresh` skips the cache, as an update does (I-1)."""
    hit = None if fresh else _IDS.get(login)
    if hit and time.time() - hit[0] < ACCOUNT_CACHE_S:
        return hit[1]
    found = await within(_ask_github(login), ACCOUNT_DEADLINE_S)
    _IDS[login] = (time.time(), found)
    return found


async def _ask_github(login: str) -> int | None:
    async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False,
                                 headers={"Accept": "application/vnd.github+json"}) as client:
        async with client.stream("GET", f"{GITHUB}/users/{login}") as r:
            if r.status_code == 404:
                return None
            r.raise_for_status()                # a rate limit, an outage or a redirect is not an answer
            body = bytearray()
            async for chunk in r.aiter_bytes():
                body += chunk
                if len(body) > ACCOUNT_MAX_BYTES:
                    raise ValueError("GitHub's answer is too large")
    found = json.loads(bytes(body))
    if not isinstance(found, dict) or type(found.get("id")) is not int:     # #584 review 7, #625 review L-1
        raise ValueError("GitHub's answer names no account id")
    return found["id"]


async def confirm_account(c: dict, allow: dict) -> str | None:
    """Before the card: a package published by a listed GitHub organization is one-click only while that login is
    still the organization the list names (its numeric id). Another id, no such account, or GitHub not answering:
    added by hand."""
    from server.services import capability_search
    if c.get("kind") != "mcp" or c.get("source") != "registry":
        return None
    who = capability_search.publisher_of(c)
    if who is None or who["kind"] != "github":
        return None
    login = who["value"].lower()
    pinned = allow["accounts"].get(login)
    if pinned is None:
        return PUBLISHER_NOT_LISTED
    try:
        found = await _account_id(login)
    except (httpx.HTTPError, ValueError, AttributeError, TypeError, TimeoutError) as exc:   # #584 review 7
        logger.info("capability allowlist: GitHub did not answer for %s (%s)", login, type(exc).__name__)
        return ACCOUNT_NOT_CHECKED
    return None if found == pinned else ACCOUNT_CHANGED_HANDS


def account_pin(c: dict, allow: dict) -> dict | None:
    """#584 re-check: the listed GitHub organization a card was confirmed against, by login and numeric id, for the
    installed source to keep (`candidate["account_pin"]`), so a later update checks that same id even once the list
    no longer names the organization or reads closed."""
    from server.services import capability_search
    who = capability_search.publisher_of(c)
    if who is None or who["kind"] != "github":
        return None
    login = who["value"].lower()
    pinned = allow["accounts"].get(login)
    return {"login": login, "id": pinned} if type(pinned) is int else None


async def confirm_pin(c: dict, pin: dict) -> str | None:
    """An update of a source installed from a listed organization: the newer version's publisher is the pinned
    login, and that login still has the pinned id, asked fresh (#625 review I-1). Another publisher or id, or GitHub
    not answering (an error, a redirect, an answer that names no id, the deadline), refuses it."""
    from server.services import capability_search
    who = capability_search.publisher_of(c)
    if who is None or who["kind"] != "github" or who["value"].lower() != pin.get("login"):
        return ACCOUNT_CHANGED_HANDS
    try:
        found = await _account_id(pin["login"], fresh=True)
    except (httpx.HTTPError, ValueError, AttributeError, TypeError, TimeoutError) as exc:
        logger.info("capability allowlist: GitHub did not answer for %s (%s)", pin["login"], type(exc).__name__)
        return ACCOUNT_NOT_CHECKED
    return None if type(found) is int and found == pin.get("id") else ACCOUNT_CHANGED_HANDS


async def confirm_update(c: dict, pin: dict | None) -> tuple[str | None, dict | None]:
    """An update's check of a newer version's publisher: (why it is refused, or None; the pin the newer source
    keeps). #625 review L-2 (⓪Plan's call), for a source installed before pins:
    - its own pin, when it has one, whatever the list says now;
    - else, a listed organization: the list's id, checked the same way, and then kept as the pin;
    - else, a publisher on GitHub while the list can't be read or reads closed: not checked, so the user tries again;
    - else (a domain publisher, or an account the list doesn't name): the list stays out of updates, as before."""
    from server.services import capability_search
    if not isinstance(pin, dict):
        allow = await current()
        pin = account_pin(c, allow)
        who = capability_search.publisher_of(c)
        if pin is None:
            closed = allow == CLOSED and who is not None and who["kind"] == "github"
            return (ACCOUNT_NOT_CHECKED if closed else None), None
    refused = await confirm_pin(c, pin)
    return refused, (None if refused else pin)
