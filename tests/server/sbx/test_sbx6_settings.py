"""Decided SBX-6 settings: optional trustd and address-pinned local devices.

Must go red: T1 default trustd grant; T2 switch ignored; T3 switch in all modes;
T4 ocspd grant; L1 permissive LAN; L2 trust a name after its address changes.
The proxy implementation belongs to 6a; this file only drives its test seams.
"""
import asyncio
import importlib.util
import json
from pathlib import Path
import socket
import sys

import pytest

from server.services.sandbox_profile import NetworkMode
from tests.server.sbx import harness
from tests.server.sbx import test_sbx2_kernel as gates
from tests.server.sbx import test_sbx6_network as network

net_sbx = network.net_sbx
pending = network.pending

macos = pytest.mark.skipif(sys.platform != "darwin", reason="macOS seatbelt")
SERVICE_CASES = (("commands-proxy", NetworkMode.PROXY), ("mcp-proxy", NetworkMode.PROXY),
                 ("network-sbx6", NetworkMode.NONE), ("network-sbx6", NetworkMode.PORT_22))


def feature_pending(feature):
    message = f"SBX-6a {feature} protection is not built"
    return pytest.mark.xfail(feature not in harness.BUILT_FEATURES, strict=True,
                            raises=pytest.RaisesExc(AssertionError, match="^" + message), reason=message)


def service_result(h, name, profile):
    result = h.python(gates.PROBE.read_text(), "mach-lookup", name, profile=profile, probe="settings-" + name)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def trust_services(h, text, *, trust_allowed):
    for name, allowed in (("com.apple.trustd.agent", trust_allowed), ("com.apple.ocspd", False)):
        # Live lookup control: an absent/unreachable service cannot prove denial.
        control = service_result(h, name, "(version 1)(allow default)")
        assert control == {"policy": 0, "lookup": 0}, control
        actual = service_result(h, name, text)
        if allowed:
            assert actual == {"policy": 0, "lookup": 0}, actual
        else:
            assert actual["policy"] == 1 and actual["lookup"] != 0, (name, actual)


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@pytest.mark.parametrize("net_sbx,mode", [pytest.param(b, mode, marks=pending(b))
                                        for b, mode in SERVICE_CASES], indirect=["net_sbx"])
def test_trust_services_are_off_by_default(net_sbx, mode):
    net_sbx.network = mode
    # Omit the setting: passing False would miss a permissive default.
    trust_services(net_sbx, net_sbx.profile(), trust_allowed=False)


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@pytest.mark.parametrize("net_sbx,mode,feature", [
    pytest.param(b, mode, "trustd-toggle", marks=[feature_pending("trustd-toggle"), pending(b)])
    for b, mode in SERVICE_CASES], indirect=["net_sbx"])
def test_trust_switch_grants_only_trustd_in_proxy(net_sbx, mode, feature):
    net_sbx.network = mode
    trust_services(net_sbx, net_sbx.profile(trust_service=True), trust_allowed=mode == NetworkMode.PROXY)
    trust_services(net_sbx, net_sbx.profile(trust_service=False), trust_allowed=False)


@pytest.fixture
def proxy_module(request, net_sbx):
    # net_sbx runs the feature guard before any optional product import.
    # The explicit reference plugin may load an immutable read-only 6a snapshot;
    # normal collection always uses the product module when the feature is built.
    path = request.config.getoption("sbx6_proxy_source", default=None)
    if path:
        spec = importlib.util.spec_from_file_location("sbx6_proxy_reference", Path(path))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    from server.services import sandbox_proxy
    return sandbox_proxy


@pytest.mark.macos
@pytest.mark.sbx_mac
@macos
@pytest.mark.parametrize("net_sbx,feature", [
    pytest.param(b, "trusted-lan", marks=[feature_pending("trusted-lan"), pending(b)])
    for b in ("commands-proxy", "mcp-proxy")], indirect=["net_sbx"])
@pytest.mark.parametrize("scenario", ["listed-ip", "unlisted-ip", "unlisted-name", "rebound-name"])
async def test_trusted_local_devices_are_pinned(net_sbx, feature, scenario, proxy_module, monkeypatch):
    proxy = proxy_module
    address, other = "192.168.77.5", "192.168.77.6"
    settings, dialled, received = [], [], []
    answers = {"nas.invalid": address, "unlisted.invalid": other}
    token = b"sbx-trusted-device"

    async def origin(reader, writer):
        try:
            data = await asyncio.wait_for(reader.readexactly(len(token)), 3)
            received.append(data)
            writer.write(b"received:" + data)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    listener = await asyncio.start_server(origin, "127.0.0.1", 0)
    port = listener.sockets[0].getsockname()[1]

    async def trusted():
        return list(settings)

    def resolve(name, requested_port, *args, **kwargs):
        # Synthetic DNS only; no real LAN or name service is contacted.
        resolved = answers.get(name, name)
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (resolved, requested_port or 0))]

    async def dial(ip, requested_port):
        # Preserve and check the exact address chosen by the proxy; only the
        # transport is mapped onto a test-owned loopback listener.
        dialled.append((ip, requested_port))
        assert ip in {address, other} and requested_port == port
        return await asyncio.open_connection("127.0.0.1", port)

    monkeypatch.setattr(proxy, "_trusted", trusted)
    monkeypatch.setattr(proxy, "_dial", dial)
    # Keep the real public-address refusal logic, replacing only DNS and the
    # transport. Even a regression admitting a private address cannot touch LAN.
    from types import SimpleNamespace
    from server.registry import net_pin
    sockets = SimpleNamespace(**{**vars(socket), "getaddrinfo": resolve})
    monkeypatch.setattr(proxy, "socket", sockets)
    monkeypatch.setattr(net_pin, "socket", sockets)
    monkeypatch.setattr(proxy, "asyncio", SimpleNamespace(**{**vars(asyncio), "open_connection": dial}))
    monkeypatch.setattr(proxy.browser_proxy, "_upstream_proxy", lambda host: None)
    server = proxy.LocalProxy()
    source = """
import socket, sys
with socket.create_connection(('127.0.0.1', int(sys.argv[1])), timeout=4) as client:
    client.sendall(('CONNECT ' + sys.argv[2] + ':' + sys.argv[3] + ' HTTP/1.1\\r\\nHost: test\\r\\n\\r\\n').encode())
    response = b''
    while b'\\r\\n\\r\\n' not in response:
        part = client.recv(1)
        assert part, 'proxy closed without a response'
        response += part
    status = int(response.split()[1])
    print(status)
    if status == 200:
        client.sendall(b'sbx-trusted-device')
        expected = b'received:sbx-trusted-device'
        answer = b''
        while len(answer) < len(expected):
            part = client.recv(len(expected) - len(answer))
            assert part, 'device closed without replying'
            answer += part
        assert answer == expected
"""

    async def ask(host, allowed):
        start = len(dialled), len(received)
        result = await asyncio.to_thread(net_sbx.python, source, server.port, host, port,
                                         profile=text, probe="trusted-lan-" + scenario)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == ("200" if allowed else "403"), result.stdout
        if allowed:
            assert dialled[start[0]:] == [(address, port)]
            assert received[start[1]:] == [token]
        else:
            assert (len(dialled), len(received)) == start, "refused request reached a device"

    try:
        await server.start()
        text = net_sbx.profile(proxy_port=server.port, bound_ports=[], system_proxies=[])
        # Positive byte-level control in every row makes refusal distinguishable
        # from an unavailable proxy or endpoint. No token reaches a real device.
        settings[:] = [{"address": address}]
        await ask(address, True)
        if scenario == "listed-ip":
            # An opt-in for one IP must never open its private subnet.
            await ask(other, False)
        elif scenario in {"unlisted-ip", "unlisted-name"}:
            target = other if scenario == "unlisted-ip" else "unlisted.invalid"
            settings.clear()  # default settings: no trusted local devices
            await ask(target, False)
            settings[:] = [{"address": address}]
            await ask(target, False)
        else:
            settings[:] = [{"host": "nas.invalid", "address": address}]
            await ask("nas.invalid", True)
            answers["nas.invalid"] = other
            await ask("nas.invalid", False)
    finally:
        await server.close()
        listener.close()
        await listener.wait_closed()


def test_feature_guards_do_not_absorb_real_failures(monkeypatch):
    for feature in ("trustd-toggle", "trusted-lan"):
        for built in (frozenset(), frozenset({"unrelated"}), frozenset({feature})):
            monkeypatch.setattr(harness, "BUILT_FEATURES", built)
            mark = feature_pending(feature)
            assert mark.args == (feature not in built,)
            assert mark.kwargs["strict"] is True
            matcher = mark.kwargs["raises"]
            assert matcher.matches(AssertionError(f"SBX-6a {feature} protection is not built"))
            assert not matcher.matches(AssertionError("real policy failure"))
            other = "trusted-lan" if feature == "trustd-toggle" else "trustd-toggle"
            assert not matcher.matches(AssertionError(f"SBX-6a {other} protection is not built"))
