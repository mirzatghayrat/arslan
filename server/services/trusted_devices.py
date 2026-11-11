"""SBX settings (v0.1.64, the mock the user OK'd with A): trusted local devices, and the chat cards a sandbox stop leads to.

A device becomes trusted only two ways (the rule the user approved, 2026-11-11):
- the user's own Settings action: `add`, which only the authenticated `POST /settings/sandbox/trusted-devices` calls
  (server/api/settings.py). The server resolves a name now and pins it to what it answers (`pin`);
- the user's click on "Trust this device" on a card this server showed: `answer`, which only the authenticated
  `POST /sandbox/cards/{card_id}` calls. An answer names its card by id and repeats the device the card showed, as an
  approval card's answer names its `call_id` (approvals.answer). A card that isn't pending (never shown, answered
  already, or past its 30 minutes) is refused, and so is a device it didn't show.

Nothing a model can call reaches either. A command the proxy refused makes a card (`offer`, from the tool loop), never
a trusted device; `PUT /settings` doesn't take this setting (it isn't on SettingsIn), and no tool writes settings. The
certificate switch (`sandbox_system_certificates`) is an ordinary setting that only `PUT /settings` writes.
tests/server/sbx/test_sbx_trust_cards.py pins both.
"""
from __future__ import annotations

import asyncio
import json
import re
import secrets
import socket
import time
from dataclasses import dataclass

from arslan.aio import within
from server.services import sandbox_proxy, settings_service
from server.ws import protocol

CARD_S = 1800                # a card can be answered for 30 minutes, as every card (approvals.TIMEOUT_S)
_MAX_CARDS = 64              # pending cards kept at once; the oldest goes first
_LOOKUP_S = 5.0
_NAME = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*")
_NUMBERS = re.compile(r"[0-9.]+")      # "10.1" is no IP, and no name either: getaddrinfo would read it as 10.0.0.1


class Refused(Exception):
    """Why a device can't be trusted, as the message the user sees names it: `not_found` (a name that doesn't resolve,
    or isn't a name), `not_lan` (an address no entry could hold: public, loopback, link-local), `own_address` (this
    Mac), `listed` (it is in the list already). `value` is the name or the address the message shows."""

    def __init__(self, code: str, value: str = ""):
        super().__init__(code)
        self.code, self.value = code, value


class NotPending(Exception):
    """No card by this id is waiting: never shown, answered already, or past its time."""


class NotShown(Exception):
    """The answer names a device its card didn't show."""


def _check(address: str) -> str:
    """`address` when `parse_trusted` would keep it (a private LAN address that isn't this Mac's), else Refused."""
    if address in sandbox_proxy.own_addresses():
        raise Refused("own_address", address)
    if not sandbox_proxy._private(address):
        raise Refused("not_lan", address)
    return address


def pin(text: str, resolve=None) -> list[dict]:
    """The entries trusting `text` (a name or a LAN IP, as typed or as the proxy was asked) would add, by
    `parse_trusted`'s rules, else Refused. An IP is itself. A name is resolved now and pinned to each private answer,
    one entry each, so `trusted_address` finds every answer it gets later among them; answers no entry could hold
    (public, link-local) are left out. A name that answers one of this Mac's addresses is refused."""
    value = text.strip().strip("[]").lower()
    try:
        literal = str(sandbox_proxy._ip(value))
    except ValueError:
        literal = None
    if literal is not None:
        return [{"address": _check(literal)}]
    name = value.rstrip(".")
    if len(name) > 253 or not _NAME.fullmatch(name) or _NUMBERS.fullmatch(name):
        raise Refused("not_found", text.strip())
    try:
        answers = sorted({str(sandbox_proxy._ip(info[4][0])) for info in (resolve or socket.getaddrinfo)(name, None)})
    except (OSError, UnicodeError, ValueError):
        answers = []
    if not answers:
        raise Refused("not_found", name)
    own = sandbox_proxy.own_addresses()
    for address in answers:
        if address in own:
            raise Refused("own_address", address)
    lan = [address for address in answers if sandbox_proxy._private(address)]
    if not lan:
        raise Refused("not_lan", answers[0])
    return [{"host": name, "address": address} for address in lan]


def _stored(raw: str) -> list[dict]:
    """The setting's entries as stored, normalized. Unlike `parse_trusted` it keeps one that is this Mac's address
    now (a Mac on another network can hold a device's address, and the entry trusts nothing meanwhile), so a save
    never drops what the user listed."""
    try:
        entries = json.loads(raw) if raw else []
    except ValueError:
        return []
    kept = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get("address"), str):
            continue
        try:
            address = str(sandbox_proxy._ip(entry["address"]))
        except ValueError:
            continue
        host = entry.get("host")
        kept.append({"address": address, **({"host": host.strip().lower()} if isinstance(host, str) and host.strip() else {})})
    return kept


async def listed(db) -> list[dict]:
    """The devices trusted now (`parse_trusted`, what the proxy reads), as Settings shows them."""
    return sandbox_proxy.parse_trusted(await settings_service.sandbox_trusted_devices(db))


async def _save(db, entries: list[dict]) -> list[dict]:
    await settings_service._set_raw(db, "sandbox_trusted_devices", json.dumps(entries, ensure_ascii=False))
    await db.commit()
    return await listed(db)


async def _pin(text: str) -> list[dict]:
    """`pin`, off the event loop; a name that takes longer than `_LOOKUP_S` to answer is not found."""
    try:
        return await within(asyncio.to_thread(pin, text), _LOOKUP_S)
    except TimeoutError:
        raise Refused("not_found", text.strip()) from None


def _covered(entry: dict, trusted: list[dict]) -> bool:
    """Whether `entry` is trusted already: an IP under any name, a name at that address."""
    return any(t["address"] == entry["address"] and ("host" not in entry or t.get("host") == entry["host"])
               for t in trusted)


async def add(db, text: str) -> list[dict]:
    """The user's Settings action (only `POST /settings/sandbox/trusted-devices` calls it): trust `text` by `pin`'s
    rules. Refused also when everything it would pin is trusted already."""
    new = await _pin(text)
    trusted = await listed(db)
    if all(_covered(entry, trusted) for entry in new):
        raise Refused("listed", new[0].get("host") or new[0]["address"])
    stored = _stored(await settings_service.sandbox_trusted_devices(db))
    return await _save(db, stored + [n for n in new if n not in stored])


async def remove(db, *, address: str | None = None, host: str | None = None) -> list[dict]:
    """The user's Settings action: stop trusting every entry with this address, or with this name."""
    stored = _stored(await settings_service.sandbox_trusted_devices(db))
    name = (host or "").strip().lower()
    try:
        address = str(sandbox_proxy._ip(address.strip().strip("[]"))) if address else ""
    except ValueError:
        address = ""
    kept = [e for e in stored if not ((address and e["address"] == address) or (name and e.get("host") == name))]
    return await _save(db, kept) if kept != stored else await listed(db)


# ── the cards (protocol.sandbox_card) ─────────────────────────────────────────

@dataclass(frozen=True)
class _Card:
    conversation_id: str
    entries: tuple[tuple[str, str], ...]     # (host or "", address), sorted: what the card shows, what an answer pins
    deadline: float                          # monotonic


_cards: dict[str, _Card] = {}


def _shown(entries: list[dict]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((e.get("host", ""), e["address"]) for e in entries))


def _frame(card_id: str, card: _Card) -> dict:
    return protocol.sandbox_card(card_id, "lan_device", host=card.entries[0][0] or None,
                                 addresses=[address for _, address in card.entries])


async def offer(conversation_id: str | None, tool_key: str, result, refused: list[str]) -> list[dict]:
    """The cards for one run_command call (the tool loop, once it ran): the certificate card when the sandbox stopped
    it on a certificate check with the switch off, and a device card when its output shows the proxy's refusal and the
    proxy refused one LAN device while it ran (`refused`, the call's watch; one only: of two, one may be another
    command's, run at the same time). Read from the result and the proxy's own record, never written onto the result.
    A card trusts nothing: these are frames for the Mac windows, and `answer` is the only way a card trusts its
    device."""
    from server.services import command_sandbox, terminal_exec
    if tool_key != "run_command" or not isinstance(result, dict):
        return []
    frames = []
    if (result.get("sandbox_denied") and command_sandbox.trust_check_failed(result)
            and not await terminal_exec.trust_service_allowed()):
        frames.append(protocol.sandbox_card(secrets.token_hex(16), "certificates"))
    hosts = refused[:3] if command_sandbox.proxy_refused(result) else []
    if conversation_id and hosts:
        try:
            pinned = await within(asyncio.gather(*(asyncio.to_thread(pin, host) for host in hosts),
                                                 return_exceptions=True), _LOOKUP_S)
        except TimeoutError:
            pinned = []
        devices = {_shown(entries) for entries in pinned if isinstance(entries, list)}
        if len(devices) == 1:
            frames.append(_register(conversation_id, devices.pop()))
    return frames


def _register(conversation_id: str, entries: tuple[tuple[str, str], ...]) -> dict:
    now = time.monotonic()
    for card_id in [key for key, card in _cards.items() if card.deadline <= now]:
        del _cards[card_id]
    for card_id, card in _cards.items():
        if card.conversation_id == conversation_id and card.entries == entries:
            return _frame(card_id, card)       # the same device again: the card still waiting, shown again
    while len(_cards) >= _MAX_CARDS:
        del _cards[next(iter(_cards))]
    card_id = secrets.token_hex(16)
    _cards[card_id] = _Card(conversation_id, entries, now + CARD_S)
    return _frame(card_id, _cards[card_id])


async def answer(db, card_id: str, *, trust: bool, host: str | None = None, addresses: list[str] = ()) -> list[dict]:
    """The user's click on a device card (only `POST /sandbox/cards/{card_id}` calls it). "Trust this device" must
    repeat the device the card showed, and pins exactly that, checked by `parse_trusted`'s rules again; "Not now"
    lets the card go. A card is answered once; a device it didn't show leaves it waiting."""
    card = _cards.get(card_id)
    if card is None or card.deadline <= time.monotonic():
        _cards.pop(card_id, None)
        raise NotPending(card_id)
    if trust:
        try:
            asked = tuple(sorted(((host or "").strip().lower(), str(sandbox_proxy._ip(a))) for a in addresses))
        except ValueError:
            asked = ()
        if asked != card.entries:
            raise NotShown(card_id)
    del _cards[card_id]
    if not trust:
        return await listed(db)
    for _, address in card.entries:
        _check(address)                        # this Mac's own addresses may have changed since the card was shown
    stored = _stored(await settings_service.sandbox_trusted_devices(db))
    new = [{"address": address, **({"host": name} if name else {})} for name, address in card.entries]
    return await _save(db, stored + [n for n in new if n not in stored])


def _reset_for_tests() -> None:
    _cards.clear()
