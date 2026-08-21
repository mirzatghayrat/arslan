"""LAN discovery — the read-only half of reach (spec P3a).

🔴 ITS OWN CODE PATH, ON PURPOSE. `net_pin._is_non_public` is an ALLOW-list
that deliberately refuses private addresses, and this feature must reach
192.168.x.x. Widening that list would open the same door for `web_extract`,
trading an SSRF defence for a config flag — so this module never imports it,
and a test asserts both halves of that separation.

Everything here observes. Nothing connects to a service, authenticates, or
executes. Reaching a machine is P3b, behind its own gate.

🔴 THE INTERFACE RULES CAME FROM MEASUREMENT. The usual trick for "what is my
LAN" — connect a UDP socket outward, read back the local address — returned
198.18.0.1 on the dev machine, a VPN tunnel, while the real LAN was
192.168.1.0/24. And `ipaddress.ip_address("198.18.0.1").is_private` is True,
so filtering on private-ness would not have caught it either. We read the
interface table instead and take only physical ones.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import subprocess

logger = logging.getLogger(__name__)

#: Fixed, not user input: an open port list a caller can widen is a port
#: scanner with extra steps. These five answer "is there a machine here, and
#: what kind" without touching anything.
SCAN_PORTS = (22, 80, 443, 3389, 5900)

#: A /24 is 254 hosts and scans in a couple of seconds. A /16 is 65534 — not
#: quick, and not neighbourly on someone else's network.
MIN_PREFIX = 22
PROBE_TIMEOUT_S = 0.4
MAX_CONCURRENCY = 64
_CMD_TIMEOUT_S = 5

#: Physical interfaces only. Tunnels (utun/ppp/ipsec), loopback, Apple's
#: peer-to-peer radios (awdl/llw) and bridges are not the user's LAN.
_PHYSICAL_IFACE = re.compile(r"^(en|eth|wlan)\d+$")

_IFACE_LINE = re.compile(r"^(\S+):\s")
_INET_LINE = re.compile(r"^\s+inet (\d+\.\d+\.\d+\.\d+)\s+netmask (0x[0-9a-fA-F]+)")
_ARP_LINE = re.compile(r"\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+([0-9a-fA-F:]{11,17})")

#: A small, honest table. An unrecognised prefix reports None rather than a
#: guess — "unknown vendor" is information; a wrong vendor is worse than none.
_OUI = {
    "80:a9:97": "Apple", "f8:20:a9": "Apple", "a4:83:e7": "Apple",
    "3c:22:fb": "Apple", "bc:d0:74": "Apple", "dc:a9:04": "Apple",
    "d0:b1:ca": "Apple", "88:66:5a": "Apple", "f0:18:98": "Apple",
    "b8:27:eb": "Raspberry Pi", "dc:a6:32": "Raspberry Pi", "e4:5f:01": "Raspberry Pi",
    "00:1a:11": "Google", "f4:f5:d8": "Google", "6c:ad:f8": "Google",
    "fc:65:de": "Amazon", "44:65:0d": "Amazon", "68:37:e9": "Amazon",
    "00:50:56": "VMware", "08:00:27": "VirtualBox", "52:54:00": "QEMU/KVM",
}


def parse_scannable_networks(ifconfig_text: str) -> list:
    """Networks worth scanning, from `ifconfig` output.

    Physical interfaces, private addresses, and small enough to finish. A
    point-to-point tunnel is excluded by its interface name rather than by its
    address, because a tunnel address can look perfectly private.
    """
    nets: list = []
    iface = ""
    for line in (ifconfig_text or "").splitlines():
        head = _IFACE_LINE.match(line)
        if head:
            iface = head.group(1)
            continue
        m = _INET_LINE.match(line)
        if not m or not _PHYSICAL_IFACE.match(iface):
            continue
        addr, mask_hex = m.group(1), m.group(2)
        try:
            prefix = bin(int(mask_hex, 16)).count("1")
            net = ipaddress.ip_network(f"{addr}/{prefix}", strict=False)
        except ValueError:
            continue
        if not net.network_address.is_private or net.prefixlen < MIN_PREFIX:
            continue
        if net not in nets:
            nets.append(net)
    return nets


def _read_ifconfig() -> str:
    try:
        return subprocess.run(["/sbin/ifconfig"], capture_output=True, text=True,
                              timeout=_CMD_TIMEOUT_S, check=False).stdout
    except Exception as exc:  # noqa: BLE001 — discovery is best-effort
        logger.warning("ifconfig failed: %s", exc)
        return ""


def _read_arp() -> str:
    """The ARP table, read AFTER probing: probing is what populates it."""
    try:
        return subprocess.run(["/usr/sbin/arp", "-a"], capture_output=True, text=True,
                              timeout=_CMD_TIMEOUT_S, check=False).stdout
    except Exception as exc:  # noqa: BLE001
        logger.warning("arp failed: %s", exc)
        return ""


def _macs(arp_text: str) -> dict[str, str]:
    out = {}
    for ip, mac in _ARP_LINE.findall(arp_text or ""):
        parts = [p.zfill(2) for p in mac.lower().split(":")]
        if len(parts) == 6:
            out[ip] = ":".join(parts)
    return out


def vendor_for(mac: str | None) -> str | None:
    if not mac:
        return None
    return _OUI.get(mac.lower()[:8])


async def _probe(host, port: int, timeout: float) -> bool:
    """Open a TCP connection and close it. Nothing is sent."""
    try:
        fut = asyncio.open_connection(str(host), port)
        reader, writer = await asyncio.wait_for(fut, timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001 — closing is best-effort
            pass
        return True
    except Exception:  # noqa: BLE001 — closed/filtered/unreachable all mean "no"
        return False


async def scan() -> dict:
    """Devices on this machine's own LAN. Read-only."""
    nets = parse_scannable_networks(_read_ifconfig())
    if not nets:
        return {"ok": False,
                "error": "no scannable local network was found (a VPN-only or "
                         "loopback-only setup has no LAN to look at)"}

    hosts = [h for net in nets for h in net.hosts()]
    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    async def probe_host(host):
        async with sem:
            results = await asyncio.gather(
                *(_probe(host, p, PROBE_TIMEOUT_S) for p in SCAN_PORTS))
        open_ports = [p for p, ok in zip(SCAN_PORTS, results) if ok]
        return (str(host), open_ports) if open_ports else None

    found = [r for r in await asyncio.gather(*(probe_host(h) for h in hosts)) if r]
    macs = _macs(_read_arp())      # after probing: that is what fills the table
    devices = [{"ip": ip, "open_ports": ports, "mac": macs.get(ip),
                "vendor": vendor_for(macs.get(ip))}
               for ip, ports in found]
    return {"ok": True, "networks": [str(n) for n in nets], "devices": devices}
