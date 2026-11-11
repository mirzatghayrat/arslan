"""SBX settings (v0.1.64, the mock the user OK'd with A): the certificate switch, the trusted local devices, and the two
chat cards a sandbox stop leads to.

The rule (user-approved): a device becomes trusted only from the user's click on "Trust this device" on that card, or
from the user's own Settings action, never from a model. Pinned here:
- the server, not only the window, refuses a public address, this Mac's own and a name that doesn't resolve, and pins
  a name to the address it resolves to now;
- a card trusts nothing until it is answered; an answer is bound to that card's id and the device it showed, and one
  with no such card waiting is refused;
- no tool, socket frame or API path but those two routes writes the device list, and the certificate switch stays off
  until Settings turns it on.
"""
from __future__ import annotations

import ast
import asyncio
import dataclasses
import functools
import ipaddress
import json
import pathlib
import socket
import sys

import pytest

from server.schemas import SettingsIn
from server.services import capability_list, command_sandbox, sandbox_proxy, settings_service, terminal_exec
from server.services import trusted_devices
from tests.server.conftest import build_ws_client

ROOT = pathlib.Path(__file__).resolve().parents[3]
OWN = frozenset({"192.168.1.8", "127.0.0.1", "::1", "fe80::1"})
ANSWERS = {
    # An mDNS NAS: its LAN address, its IPv6 link-local one and a global IPv6 one.
    "nas.local": ["192.168.1.20", "fe80::20", "2606:2800:220:1::1"],
    "printer.local": ["192.168.1.30"],
    "me.local": ["192.168.1.8"],                          # this Mac, by name
    "public.example": ["93.184.216.34"],
}
DEVICES = "/api/v1/settings/sandbox/trusted-devices"
# run_command results as terminal_exec makes them: a sandboxed command whose output shows the proxy's refusal, and one
# stopped on a certificate check the closed trust service failed.
REFUSED = {"ok": False, "exit_code": 56, "stdout": "", "stderr": "curl: (56) CONNECT tunnel failed, response 403",
           "sandbox": "workspace", "sandbox_denied": True, "error": "the sandbox stopped this command (exit code 56)"}
CERTIFICATE = {"ok": False, "exit_code": 1, "stdout": "", "stderr": "x509: OSStatus -26276", "sandbox": "workspace",
               "sandbox_denied": True, "error": "the sandbox stopped this command (exit code 1)"}


@pytest.fixture(autouse=True)
def lan(monkeypatch):
    """This Mac's addresses, and names answered from a table: a name not in it doesn't resolve, and nothing reaches DNS
    (a literal still resolves, numerically). The test may change an answer."""
    monkeypatch.setattr(sandbox_proxy, "own_addresses", lambda: OWN)
    answers = {name: list(values) for name, values in ANSWERS.items()}
    real = socket.getaddrinfo

    def lookup(host, port, family=0, type=0, proto=0, flags=0):
        if host in answers:
            return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port or 0))
                    for a in answers[host]]
        try:
            ipaddress.ip_address(str(host).split("%")[0])
        except ValueError:
            raise socket.gaierror(socket.EAI_NONAME, "nodename nor servname provided, or not known") from None
        return real(host, port, family, type, proto, flags | socket.AI_NUMERICHOST)
    monkeypatch.setattr(socket, "getaddrinfo", lookup)
    trusted_devices._reset_for_tests()
    yield answers
    trusted_devices._reset_for_tests()


async def _devices(client) -> list[dict]:
    r = await client.get(DEVICES)
    assert r.status_code == 200, r.text
    return r.json()["devices"]


async def _raw(client) -> str:
    async with client.db_maker() as db:
        return await settings_service.sandbox_trusted_devices(db)


async def _card(conversation: str = "c1", hosts: tuple[str, ...] = ()) -> dict:
    """The device card for a command whose output shows the proxy's refusal, `hosts` being what the proxy refused."""
    [frame] = [f for f in await trusted_devices.offer(conversation, "run_command", REFUSED, list(hosts))
               if f["kind"] == "lan_device"]
    return frame


def _answer(client, frame: dict, **body):
    return client.post(f"/api/v1/sandbox/cards/{frame['card_id']}", json=body)


# ── Settings: the server decides ──────────────────────────────────────────────

@pytest.mark.parametrize(("typed", "code", "value"), [
    ("8.8.8.8", "not_lan", "8.8.8.8"),                       # a public address
    ("public.example", "not_lan", "93.184.216.34"),          # a name that answers one
    ("169.254.169.254", "not_lan", "169.254.169.254"),       # link-local: never trusted
    ("192.168.1.8", "own_address", "192.168.1.8"),           # this Mac
    ("me.local", "own_address", "192.168.1.8"),              # this Mac, by name
    ("127.0.0.1", "own_address", "127.0.0.1"),
    ("gone.local", "not_found", "gone.local"),               # a name that doesn't resolve
    ("10.1", "not_found", "10.1"),                           # no IP and no name: getaddrinfo would read 10.0.0.1
    ("not a name", "not_found", "not a name"),
])
async def test_the_server_refuses_a_public_address_this_macs_own_and_a_name_that_doesnt_resolve(client, typed, code,
                                                                                               value):
    r = await client.post(DEVICES, json={"device": typed})
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == {"code": code, "value": value}
    assert await _devices(client) == [] and await _raw(client) == ""


async def test_a_name_is_pinned_to_the_address_it_resolves_to_now(client, lan):
    r = await client.post(DEVICES, json={"device": " NAS.local "})
    assert r.status_code == 200, r.text
    pinned = [{"address": "192.168.1.20", "host": "nas.local"}]       # not its link-local or public answers
    assert r.json()["devices"] == pinned
    trusted = sandbox_proxy.parse_trusted(await _raw(client))
    assert sandbox_proxy.trusted_address("nas.local", trusted) == "192.168.1.20"   # its other answers don't refuse it
    lan["nas.local"].append("192.168.1.99")
    assert sandbox_proxy.trusted_address("nas.local", trusted) is None             # another LAN answer still does
    lan["nas.local"] = ["192.168.1.99"]
    assert sandbox_proxy.trusted_address("nas.local", trusted) is None             # moved: pinned to the old address
    assert await _devices(client) == pinned


async def test_an_ip_is_added_once_and_removed_from_the_list(client):
    r = await client.post(DEVICES, json={"device": "192.168.1.42"})
    assert r.status_code == 200 and r.json()["devices"] == [{"address": "192.168.1.42"}]
    again = await client.post(DEVICES, json={"device": "192.168.1.42"})
    assert again.status_code == 422 and again.json()["detail"]["code"] == "listed"
    assert (await client.post(DEVICES, json={"device": "nas.local"})).status_code == 200
    r = await client.delete(DEVICES, params={"address": "192.168.1.42"})
    assert r.json()["devices"] == [{"address": "192.168.1.20", "host": "nas.local"}]
    r = await client.delete(DEVICES, params={"host": "NAS.local"})
    assert r.json()["devices"] == [] and json.loads(await _raw(client)) == []


async def test_put_settings_cannot_trust_a_device(client):
    r = await client.put("/api/v1/settings", json={"sandbox_trusted_devices": json.dumps([{"address": "192.168.1.50"}])})
    assert r.status_code == 200, r.text
    assert await _devices(client) == [] and await _raw(client) == ""


async def test_the_certificate_switch_is_off_until_settings_turns_it_on(client):
    async with client.db_maker() as db:
        assert await settings_service.sandbox_system_certificates(db) is False
    assert (await client.get("/api/v1/settings")).json()["sandbox_system_certificates"] == ""
    [card] = await trusted_devices.offer("c1", "run_command", CERTIFICATE, [])   # its card turns nothing on
    assert card == {"type": "sandbox_card", "card_id": card["card_id"], "kind": "certificates"}
    async with client.db_maker() as db:
        assert await settings_service.sandbox_system_certificates(db) is False
    for value, on in (("true", True), ("false", False)):
        assert (await client.put("/api/v1/settings", json={"sandbox_system_certificates": value})).status_code == 200
        async with client.db_maker() as db:
            assert await settings_service.sandbox_system_certificates(db) is on


async def test_both_routes_need_the_access_token(client, monkeypatch):
    import server.config as config
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, api_token="secret-tok"))
    frame = await _card(hosts=["192.168.1.20"])
    assert (await client.post(DEVICES, json={"device": "192.168.1.20"})).status_code == 401
    assert (await _answer(client, frame, trust=True, addresses=["192.168.1.20"])).status_code == 401
    bearer = {"Authorization": "Bearer secret-tok"}
    assert (await client.get(DEVICES, headers=bearer)).json()["devices"] == []
    r = await client.post(f"/api/v1/sandbox/cards/{frame['card_id']}", headers=bearer,
                          json={"trust": True, "addresses": ["192.168.1.20"]})
    assert r.status_code == 200 and r.json()["devices"] == [{"address": "192.168.1.20"}]


# ── the device card: bound to its id and the device it showed ─────────────────

async def test_a_card_trusts_nothing_until_the_user_answers_it(client):
    frame = await _card(hosts=["192.168.1.20"])
    assert frame == {"type": "sandbox_card", "card_id": frame["card_id"], "kind": "lan_device",
                     "addresses": ["192.168.1.20"]}
    assert await _devices(client) == [] and await _raw(client) == ""          # a model's command made it: nothing
    r = await _answer(client, frame, trust=True, addresses=["192.168.1.20"])
    assert r.status_code == 200 and r.json()["devices"] == [{"address": "192.168.1.20"}]


async def test_an_answer_for_one_device_cant_trust_another(client):
    nas = await _card(hosts=["nas.local"])
    printer = await _card(hosts=["printer.local"])
    assert (nas["host"], nas["addresses"]) == ("nas.local", ["192.168.1.20"])
    for body in ({"trust": True, "host": "nas.local", "addresses": ["192.168.1.21"]},     # another address
                 {"trust": True, "addresses": ["192.168.1.20"]},                          # its address, not its name
                 {"trust": True, "host": "printer.local", "addresses": ["192.168.1.30"]},  # another card's device
                 {"trust": True, "host": "nas.local", "addresses": ["192.168.1.20", "192.168.1.30"]},   # more
                 {"trust": True, "host": "nas.local", "addresses": ["not an address"]},
                 {"trust": True}):
        r = await _answer(client, nas, **body)
        assert r.status_code == 409, (body, r.text)
    assert await _devices(client) == []
    r = await _answer(client, nas, trust=True, host="nas.local", addresses=["192.168.1.20"])     # still waiting
    assert r.status_code == 200 and r.json()["devices"] == [{"address": "192.168.1.20", "host": "nas.local"}]
    r = await _answer(client, printer, trust=True, host="printer.local", addresses=["192.168.1.30"])
    assert r.status_code == 200 and len(r.json()["devices"]) == 2


async def test_a_card_pins_what_it_showed_even_when_the_name_has_moved_since(client, lan):
    frame = await _card(hosts=["nas.local"])
    lan["nas.local"] = ["192.168.1.66"]
    r = await _answer(client, frame, trust=True, host="nas.local", addresses=["192.168.1.20"])
    assert r.json()["devices"] == [{"address": "192.168.1.20", "host": "nas.local"}]


async def test_an_answer_without_that_card_waiting_is_refused(client):
    body = {"trust": True, "addresses": ["192.168.1.20"]}
    assert (await _answer(client, {"card_id": "0" * 32}, **body)).status_code == 404        # never shown
    frame = await _card(hosts=["192.168.1.20"])
    assert (await _answer(client, frame, trust=False)).status_code == 200                    # "Not now"
    assert (await _answer(client, frame, **body)).status_code == 404                         # answered already
    frame = await _card(hosts=["192.168.1.20"])
    card = trusted_devices._cards[frame["card_id"]]
    trusted_devices._cards[frame["card_id"]] = dataclasses.replace(card, deadline=0.0)
    assert (await _answer(client, frame, **body)).status_code == 404                         # past its 30 minutes
    frame = await _card(hosts=["192.168.1.20"])
    trusted_devices._reset_for_tests()                                                       # Arslan restarted
    assert (await _answer(client, frame, **body)).status_code == 404
    assert await _devices(client) == []


async def test_an_answer_is_checked_against_this_macs_addresses_again(client, monkeypatch):
    frame = await _card(hosts=["192.168.1.20"])
    monkeypatch.setattr(sandbox_proxy, "own_addresses", lambda: OWN | {"192.168.1.20"})     # the Mac moved networks
    r = await _answer(client, frame, trust=True, addresses=["192.168.1.20"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "own_address"
    assert await _raw(client) == ""


@pytest.mark.parametrize("hosts", [["127.0.0.1"], ["169.254.169.254"], ["192.168.1.8"], ["me.local"], ["gone.local"],
                                   ["192.168.1.20", "192.168.1.30"]])
async def test_no_device_card_for_what_no_entry_could_hold_or_for_two_devices(hosts):
    """Two devices refused while one command ran: one may be another command's, run at the same time."""
    assert await trusted_devices.offer("c1", "run_command", REFUSED, hosts) == []


async def test_a_card_needs_the_refusal_in_the_commands_own_output_and_a_command():
    """The proxy's record alone makes no card: the command's own output must show the refusal, and only run_command's
    results are read."""
    failed = {**REFUSED, "stderr": "curl: (7) Failed to connect to 192.168.1.20 port 80: Connection refused"}
    assert await trusted_devices.offer("c1", "run_command", failed, ["192.168.1.20"]) == []
    assert await trusted_devices.offer("c1", "fetch_url", REFUSED, ["192.168.1.20"]) == []
    assert await trusted_devices.offer("c1", "run_command", {**REFUSED, "sandbox": "outside"}, ["192.168.1.20"]) == []
    assert await trusted_devices.offer(None, "run_command", REFUSED, ["192.168.1.20"]) == []    # no conversation
    assert len(await trusted_devices.offer("c1", "run_command", REFUSED, ["192.168.1.20"])) == 1


async def test_the_same_device_again_shows_the_card_still_waiting():
    first, again = await _card(hosts=["192.168.1.20"]), await _card(hosts=["192.168.1.20"])
    assert first == again and len(trusted_devices._cards) == 1
    assert (await _card("c2", hosts=["192.168.1.20"]))["card_id"] != first["card_id"]


# ── where the cards come from: the proxy's refusal, through terminal_exec and the tool loop ──

async def _ask(port: int, request: bytes) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(request)
    await writer.drain()
    data = await asyncio.wait_for(reader.read(65536), 5)
    writer.close()
    return data


async def test_the_proxy_notes_each_destination_it_refuses_to_the_watches_open_then(monkeypatch):
    from server.registry.net_pin import _FakeIpOnlyHttps
    monkeypatch.setattr(sandbox_proxy.browser_proxy.net_pin, "getproxies", lambda: {})

    async def nothing_trusted():
        return []
    monkeypatch.setattr(sandbox_proxy, "_trusted", nothing_trusted)
    real = sandbox_proxy._resolve_pinned

    def resolve(url, **kw):
        if "plain.example" in url:
            raise _FakeIpOnlyHttps("plain.example: behind fake-IP DNS only https:// on port 443 is fetched")
        return real(url, **kw)
    monkeypatch.setattr(sandbox_proxy, "_resolve_pinned", resolve)
    proxy = sandbox_proxy.LocalProxy()
    await proxy.start()
    watch = sandbox_proxy.watch()
    try:
        for line in (b"CONNECT 10.0.0.1:443", b"CONNECT NAS.local:5000", b"CONNECT [::1]:22", b"CONNECT 10.0.0.1:22",
                     b"GET /relative", b"GET http://plain.example/"):
            assert b" 403 " in (reply := await _ask(proxy.port, line + b" HTTP/1.1\r\nHost: x\r\n\r\n")) \
                or line == b"GET /relative", reply
        assert sandbox_proxy.unwatch(watch) == ["10.0.0.1", "nas.local", "::1"]   # not a bad request, not fake-IP
        await _ask(proxy.port, b"CONNECT 10.0.0.2:443 HTTP/1.1\r\nHost: x\r\n\r\n")
        assert watch.hosts == ["10.0.0.1", "nas.local", "::1"]                      # closed: nothing more reaches it
    finally:
        await proxy.close()


async def test_a_lan_refusal_through_the_real_proxy_offers_its_card_and_trusts_nothing(client, tmp_path, monkeypatch):
    """Python's own client, through the proxy terminal_exec started and pointed it at (the stand-in wrapper, no seatbelt
    here), to a LAN literal net_pin refuses, watched as the tool loop watches a run_command call."""
    monkeypatch.setattr(sandbox_proxy.browser_proxy.net_pin, "getproxies", lambda: {})

    async def nothing_trusted():
        return []
    monkeypatch.setattr(sandbox_proxy, "_trusted", nothing_trusted)
    monkeypatch.setattr(command_sandbox, "wrapper", lambda *a, **k: ["/usr/bin/env"])
    sandbox_proxy._reset_for_tests()
    command = f"{sys.executable} -I -c \"import urllib.request as u; u.urlopen('https://10.0.0.1/', timeout=5)\""
    watch = sandbox_proxy.watch()
    try:
        result = await terminal_exec.run(command, cwd=tmp_path, sandbox=True)
    finally:
        await sandbox_proxy.shutdown()
    refused = sandbox_proxy.unwatch(watch)
    assert result["sandbox_denied"] is True, result["stderr"][-400:]
    assert refused == ["10.0.0.1"] and watch not in sandbox_proxy._watches
    [frame] = await trusted_devices.offer("c1", "run_command", result, refused)
    assert (frame["kind"], frame["addresses"]) == ("lan_device", ["10.0.0.1"]) and "host" not in frame
    assert frame["card_id"] not in json.dumps(result) and await _devices(client) == []


@pytest.mark.parametrize(("switch_on", "cards"), [(False, ["certificates"]), (True, [])])
async def test_a_failed_certificate_check_offers_its_card_only_while_the_switch_is_off(tmp_path, monkeypatch, switch_on,
                                                                                       cards):
    async def port():
        return 41000

    async def allowed():
        return switch_on
    monkeypatch.setattr(sandbox_proxy, "port", port)
    monkeypatch.setattr(terminal_exec, "trust_service_allowed", allowed)
    monkeypatch.setattr(command_sandbox, "wrapper", lambda *a, **k: ["/usr/bin/env"])
    result = await terminal_exec.run("printf '%s\\n' 'x509: OSStatus -26276' >&2; exit 1", cwd=tmp_path, sandbox=True)
    assert result["sandbox_denied"] is True
    assert [f["kind"] for f in await trusted_devices.offer("c1", "run_command", result, [])] == cards


async def test_the_tool_loop_shows_the_card_and_the_model_never_sees_it(execution_db, monkeypatch):
    from server.orchestrator import tool_loop
    from server.orchestrator.turn_state import ToolTurn

    async def run(command, **kw):
        sandbox_proxy._note_refused("192.168.1.20")                # as the proxy does when it refuses the command
        return dict(REFUSED)
    monkeypatch.setattr(terminal_exec, "run", run)

    async def card(command, argv, **kw):
        return True

    async def resolve():
        return [{"key": "run_command", "description": "run"}]
    frames, convo = [], []
    watches = len(sandbox_proxy._watches)
    turn = ToolTurn(resolve_tools=resolve, emit=frames.append, tool_timeout_s=5, tool_trace=[], convo=convo,
                    confirm_command=card, conversation_id="c1")
    result = await tool_loop._run_tool("run_command", {"command": "ls"}, "{}", turn)
    [shown] = [f for f in frames if f.get("type") == "sandbox_card"]
    assert shown["kind"] == "lan_device" and shown["addresses"] == ["192.168.1.20"]
    told = json.dumps([result, convo, [f for f in frames if f is not shown]], default=str)
    assert shown["card_id"] not in told and "192.168.1.20" not in told       # the model's result, its record, the rest
    assert len(sandbox_proxy._watches) == watches                             # the call's watch is closed
    async with execution_db() as db:
        assert await trusted_devices.listed(db) == []


def test_a_replayed_card_frame_or_an_answer_over_the_socket_trusts_nothing(portal, tmp_path, monkeypatch):
    client = build_ws_client(portal, tmp_path, monkeypatch, db_name="trust_cards.db")
    frame = portal.call(functools.partial(_card, "main", hosts=["192.168.1.20"]))
    with client.websocket_connect("/ws/arslan/main") as ws:
        assert ws.receive_json()["type"] == "history"
        for sent in (frame, {**frame, "type": "confirm_sandbox_card", "trust": True},
                     {"type": "confirm_action", "call_id": frame["card_id"]}):
            ws.send_json(sent)
            assert ws.receive_json()["type"] == "error"
    assert frame["card_id"] in trusted_devices._cards

    async def stored():
        async with client.db_maker() as db:
            return await settings_service.sandbox_trusted_devices(db)
    assert portal.call(stored) == ""


# ── no other path: the writers' callers, and the keys' writers ─────────────────

def _sources():
    for base in ("server", "arslan"):
        for path in sorted((ROOT / base).rglob("*.py")):
            yield path.relative_to(ROOT).as_posix(), ast.parse(path.read_text(encoding="utf-8"))


def test_only_the_two_settings_routes_call_what_trusts_a_device():
    """Every use of trusted_devices' writers in server/ and arslan/: the settings router, and nothing a tool, an MCP
    tool, memory or the socket runs."""
    used = set()
    for rel, tree in _sources():
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and node.attr in {"add", "answer", "remove", "_save"}
                    and isinstance(node.value, ast.Name) and node.value.id == "trusted_devices"):
                used.add((rel, node.attr))
            if isinstance(node, ast.ImportFrom) and node.module == "server.services.trusted_devices":
                used.update((rel, alias.name) for alias in node.names)
    assert used == {("server/api/settings.py", name) for name in ("add", "answer", "remove")}


def test_the_two_keys_are_written_nowhere_else():
    """The keys' string literals in server/ and arslan/: the settings registry and accessors, and the device list's one
    writer. PUT /settings takes the switch only, and no capability switch names either key."""
    places: dict[str, set[str]] = {}
    for rel, tree in _sources():
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value in ("sandbox_trusted_devices", "sandbox_system_certificates"):
                places.setdefault(node.value, set()).add(rel)
    assert places == {"sandbox_trusted_devices": {"server/services/settings_service.py",
                                                  "server/services/trusted_devices.py"},
                      "sandbox_system_certificates": {"server/services/settings_service.py"}}
    assert "sandbox_trusted_devices" not in SettingsIn.model_fields
    assert "sandbox_system_certificates" in SettingsIn.model_fields
    assert not {"sandbox_trusted_devices", "sandbox_system_certificates"} & set(capability_list.SETTING_SWITCHES.values())
