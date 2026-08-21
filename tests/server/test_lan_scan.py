"""LAN discovery (spec P3a) — the read-only proposal surface.

Its own code path on purpose. `net_pin._is_non_public` is an ALLOW-list that
deliberately refuses private addresses, and widening it so this feature can
reach 192.168.x.x would open the same door for web_extract — trading an SSRF
defence for a config flag. So this module never imports it, and the separation
is asserted below both structurally and behaviourally.

The interface rules come from measurement, not from a guess about what a
machine looks like. On the dev machine, "connect a UDP socket outward and read
the local address" — the usual trick — returned 198.18.0.1, a VPN tunnel,
while the real LAN was 192.168.1.0/24. That method would have failed silently
for anyone with a VPN up.
"""

from server.services import lan_scan

# Verbatim from `ifconfig` on macOS with a VPN connected. The tunnel is the
# whole point of this fixture.
IFCONFIG = """lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
\tinet 127.0.0.1 netmask 0xff000000
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tinet 192.168.1.5 netmask 0xffffff00 broadcast 192.168.1.255
utun4: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1400
\tinet 198.18.0.1 --> 198.18.0.1 netmask 0xffffffff
awdl0: flags=8843<UP,BROADCAST,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tinet 169.254.180.2 netmask 0xffff0000
"""


# ── which networks we are willing to scan ─────────────────────────────────
def test_finds_the_real_lan_from_a_physical_interface():
    nets = lan_scan.parse_scannable_networks(IFCONFIG)
    assert [str(n) for n in nets] == ["192.168.1.0/24"]


def test_a_tunnel_with_ordinary_formatting_is_still_not_a_lan():
    """The interface-name rule standing on its own.

    utun's line reads "inet X --> X netmask", which the inet regex already
    rejects for its shape — so the fixture above cannot tell whether the name
    rule works or the regex is carrying it (measured: deleting the name rule
    kept that test green). A tunnel that formats like a normal interface,
    which some VPNs do, leaves the name rule as the only defence.
    """
    text = (
        "utun0: flags=8051<UP,POINTOPOINT,RUNNING> mtu 1400\n"
        "\tinet 10.8.0.2 netmask 0xffffff00\n"
        "ppp0: flags=8051<UP,POINTOPOINT,RUNNING> mtu 1400\n"
        "\tinet 10.9.0.2 netmask 0xffffff00\n"
    )
    assert lan_scan.parse_scannable_networks(text) == []


def test_a_vpn_tunnel_is_not_a_lan():
    """The measured failure: 198.18.0.1 is_private() is True, so a naive
    private-address filter would have accepted the tunnel and scanned a
    network with nothing on it while missing the real one."""
    import ipaddress
    assert ipaddress.ip_address("198.18.0.1").is_private is True   # the trap
    nets = [str(n) for n in lan_scan.parse_scannable_networks(IFCONFIG)]
    assert not any(n.startswith("198.18.") for n in nets)


def test_loopback_and_link_local_are_excluded():
    nets = [str(n) for n in lan_scan.parse_scannable_networks(IFCONFIG)]
    assert not any(n.startswith(("127.", "169.254.")) for n in nets)


def test_a_network_too_large_to_scan_is_refused():
    """A /16 is 65534 hosts. Scanning it is neither quick nor neighbourly, and
    an interface can legitimately carry one."""
    big = ("en0: flags=8863<UP> mtu 1500\n"
           "\tinet 10.0.0.5 netmask 0xffff0000 broadcast 10.0.255.255\n")
    assert lan_scan.parse_scannable_networks(big) == []


def test_a_slash_24_is_accepted_and_a_slash_25_too():
    for mask, expect in (("0xffffff00", "192.168.1.0/24"),
                         ("0xffffff80", "192.168.1.0/25")):
        text = f"en0: flags=8863<UP> mtu 1500\n\tinet 192.168.1.5 netmask {mask}\n"
        assert [str(n) for n in lan_scan.parse_scannable_networks(text)] == [expect]


def test_malformed_output_yields_nothing_rather_than_raising():
    for text in ("", "garbage", "en0:\n\tinet not-an-ip netmask 0xffffff00\n"):
        assert lan_scan.parse_scannable_networks(text) == []


# ── the scan itself ───────────────────────────────────────────────────────
def test_ports_are_a_fixed_whitelist_not_user_input():
    assert set(lan_scan.SCAN_PORTS) == {22, 80, 443, 3389, 5900}


async def test_scan_probes_only_whitelisted_ports(monkeypatch):
    tried = []

    async def fake_probe(host, port, timeout):
        tried.append(port)
        return port == 22

    monkeypatch.setattr(lan_scan, "_probe", fake_probe)
    monkeypatch.setattr(lan_scan, "parse_scannable_networks",
                        lambda _text: [__import__("ipaddress").ip_network("192.168.1.0/30")])
    monkeypatch.setattr(lan_scan, "_read_ifconfig", lambda: IFCONFIG)
    monkeypatch.setattr(lan_scan, "_read_arp", lambda: "")

    out = await lan_scan.scan()
    assert out["ok"] is True
    assert set(tried) <= set(lan_scan.SCAN_PORTS)


async def test_scan_reports_hosts_with_open_ports_only(monkeypatch):
    async def fake_probe(host, port, timeout):
        return str(host).endswith(".2") and port == 22

    monkeypatch.setattr(lan_scan, "_probe", fake_probe)
    monkeypatch.setattr(lan_scan, "parse_scannable_networks",
                        lambda _t: [__import__("ipaddress").ip_network("192.168.1.0/29")])
    monkeypatch.setattr(lan_scan, "_read_ifconfig", lambda: IFCONFIG)
    monkeypatch.setattr(lan_scan, "_read_arp", lambda: "")

    out = await lan_scan.scan()
    assert [d["ip"] for d in out["devices"]] == ["192.168.1.2"]
    assert out["devices"][0]["open_ports"] == [22]


async def test_a_vendor_is_named_when_the_mac_is_known(monkeypatch):
    """The OpenClaw moment: 80:a9:97 → Apple is how it recognised the new Mac."""
    async def fake_probe(host, port, timeout):
        return str(host).endswith(".2") and port == 22

    monkeypatch.setattr(lan_scan, "_probe", fake_probe)
    monkeypatch.setattr(lan_scan, "parse_scannable_networks",
                        lambda _t: [__import__("ipaddress").ip_network("192.168.1.0/29")])
    monkeypatch.setattr(lan_scan, "_read_ifconfig", lambda: IFCONFIG)
    monkeypatch.setattr(lan_scan, "_read_arp",
                        lambda: "? (192.168.1.2) at 80:a9:97:11:22:33 on en0 ifscope [ethernet]\n")

    out = await lan_scan.scan()
    dev = out["devices"][0]
    assert dev["mac"] == "80:a9:97:11:22:33"
    assert dev["vendor"] == "Apple"


async def test_an_unknown_mac_says_unknown_rather_than_guessing(monkeypatch):
    async def fake_probe(host, port, timeout):
        return str(host).endswith(".2") and port == 22

    monkeypatch.setattr(lan_scan, "_probe", fake_probe)
    monkeypatch.setattr(lan_scan, "parse_scannable_networks",
                        lambda _t: [__import__("ipaddress").ip_network("192.168.1.0/29")])
    monkeypatch.setattr(lan_scan, "_read_ifconfig", lambda: IFCONFIG)
    monkeypatch.setattr(lan_scan, "_read_arp",
                        lambda: "? (192.168.1.2) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]\n")

    out = await lan_scan.scan()
    assert out["devices"][0]["vendor"] is None


async def test_no_scannable_network_is_a_readable_refusal(monkeypatch):
    monkeypatch.setattr(lan_scan, "_read_ifconfig", lambda: "lo0:\n\tinet 127.0.0.1 netmask 0xff000000\n")
    out = await lan_scan.scan()
    assert out["ok"] is False and "network" in out["error"].lower()


# ── the separation from net_pin, asserted two ways ────────────────────────
def test_this_module_does_not_import_net_pin():
    """Structural half of the separation.

    Asserts on IMPORTS, not on the source text: the module docstring names
    net_pin deliberately, to explain why it is absent. A test that could not
    tell an import from a comment would have punished the explanation."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(lan_scan))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(f"{node.module}.{a.name}" for a in node.names)
    assert not any("net_pin" in name for name in imported), imported


def test_net_pin_still_refuses_private_addresses():
    """Behavioural half: the SSRF defence is untouched by this feature
    existing. If someone 'fixes' the conflict by widening net_pin, this fails."""
    from server.registry import net_pin
    assert net_pin._is_private_host("http://192.168.1.8/") is True
