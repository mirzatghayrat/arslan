"""C1 fixture: a tracking link that opens the app on Android but sends iPhones to the App Store (harness plan §4.1,
the capability set's first task, from a 2026-11-12 same-question comparison). Made-up names only: no real
attribution vendor, app or link.

File-based since the H0 follow-up. The first C1 served the link from a stub on 127.0.0.1, but Arslan's sandbox lets a
command reach loopback only while it runs online: after a turn reads outside content (a curl's output is outside
content), a command that reaches the network asks a network card first (command_gate), the bench's stand-in person
declines it, and any other command runs offline, where the profile denies all network, loopback included. So only
the first request of a run could reach the stub. The bench adapts to the sandbox: the vendor's server is now a
local script the worker runs, and nothing in C1 needs the network.

The fixture writes into the run folder:
- `link_sim.py`, a stand-in for the link vendor's server. `python3 link_sim.py --ua "<user agent>" "<link>"` prints
  the status, headers and body the server would send (no redirect followed) and appends the request to
  `link_requests.jsonl` beside it. Its rules are packed (`RULES` below), so the fix is found by trying links, as with
  the real server, not by reading the script.
  - `go.demoapp.test/.well-known/apple-app-site-association` and `.../assetlinks.json`: valid, `/abc1/*`.
  - `/abc1` (and `/abc1/...`) with an iPhone or iPad user agent: 301 to the App Store, empty body. This is the bug.
  - The same with `force_deeplink=true` (or 1) in the query: 200, a page that opens `demoapp://home` and falls back
    to the store. This is the fix. Nothing else changes the iPhone answer (a trailing slash, other parameters).
  - With an Android user agent: 200, a page that tries `intent://` and then `demoapp://home`.
  - Any other user agent: 302 to a web landing page.
- `app/make_link.py`, the app's code that builds the link (without force_deeplink): the code to fix.

No URL scheme anywhere the worker is pointed: Arslan reads `http(s)://` in a command as reaching the network
(untrusted.reaches_network), which would bring the network card back. check_c1 reads the request log and the fixed
code from disk, and the script's hash, so an edited simulator doesn't count.
"""
from __future__ import annotations

import base64
import hashlib
import json
import zlib
from pathlib import Path

HOST = "go.demoapp.test"
SIM = "link_sim.py"
LOG = "link_requests.jsonl"
CODE = "app/make_link.py"
STORE = "https://apps.apple.com/app/id0000000000"
LANDING = "https://www.example.com/demoapp"
IOS_PAGE = ('<html><body><script>window.location = "demoapp://home";'
            f'setTimeout(function () {{ window.location = "{STORE}"; }}, 1500);</script></body></html>')
ANDROID_PAGE = ('<html><body><script>window.location = '
                '"intent://home#Intent;scheme=demoapp;package=com.example.demoapp;end";'
                'setTimeout(function () { window.location = "demoapp://home"; }, 800);</script></body></html>')
AASA = {"applinks": {"details": [{"appIDs": ["ABCDE12345.com.example.demoapp"], "components": [{"/": "/abc1/*"}]}]}}
ASSETLINKS = [{"relation": ["delegate_permission/common.handle_all_urls"],
               "target": {"namespace": "android_app", "package_name": "com.example.demoapp",
                          "sha256_cert_fingerprints": ["00:" * 31 + "00"]}}]
#: The vendor's answers, packed into link_sim.py.
RULES = {"host": HOST, "link": "/abc1", "store": STORE, "landing": LANDING, "ios_page": IOS_PAGE,
         "android_page": ANDROID_PAGE, "aasa": AASA, "assetlinks": ASSETLINKS, "app_param": "force_deeplink",
         "app_on": ["true", "1"]}

SIM_SOURCE = r'''#!/usr/bin/env python3
"""A local stand-in for the link vendor's server (__HOST__). It answers one link the way the vendor's server does and
logs the request beside this script (link_requests.jsonl). Run it; don't change it.

    python3 link_sim.py --ua "<user agent>" "__HOST__/abc1?<query>"

It prints the status, the headers and the body the server would send. No redirect is followed. Without --ua it
sends no browser's user agent."""
import argparse
import base64
import json
import re
import sys
import time
import zlib
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

RULES = json.loads(zlib.decompress(base64.b64decode("__RULES__")))
LOG = Path(__file__).resolve().parent / "link_requests.jsonl"


def device(ua):
    if "iPhone" in ua or "iPad" in ua:
        return "ios"
    return "android" if "Android" in ua else "other"


def answer(path, query, ua):
    if path == "/.well-known/apple-app-site-association":
        return 200, {"Content-Type": "application/json"}, json.dumps(RULES["aasa"])
    if path == "/.well-known/assetlinks.json":
        return 200, {"Content-Type": "application/json"}, json.dumps(RULES["assetlinks"])
    if path != RULES["link"] and not path.startswith(RULES["link"] + "/"):
        return 404, {}, ""
    kind = device(ua)
    if kind == "ios":
        if query.get(RULES["app_param"], [""])[-1].lower() in RULES["app_on"]:
            return 200, {"Content-Type": "text/html"}, RULES["ios_page"]
        return 301, {"Location": RULES["store"]}, ""
    if kind == "android":
        return 200, {"Content-Type": "text/html"}, RULES["android_page"]
    return 302, {"Location": RULES["landing"]}, ""


def main(argv):
    ap = argparse.ArgumentParser(prog="link_sim.py", description="Answer one link as the vendor's server would.")
    ap.add_argument("--ua", "-A", "--user-agent", dest="ua", default="link_sim/1.0", help="the user agent")
    ap.add_argument("link", help=RULES["host"] + "/... (a scheme in front is ignored)")
    a = ap.parse_args(argv)
    link = re.sub(r"^[A-Za-z][A-Za-z0-9+.-]*://", "", a.link.strip())
    if not link.startswith(RULES["host"] + "/"):
        print("only " + RULES["host"] + " links are served here", file=sys.stderr)
        return 2
    u = urlsplit("//" + link)
    query = parse_qs(u.query, keep_blank_values=True)
    status, headers, body = answer(u.path, query, a.ua)
    with LOG.open("a") as f:
        f.write(json.dumps({"t": round(time.time(), 3), "path": u.path, "query": query, "ua": a.ua,
                            "device": device(a.ua),
                            "force": query.get(RULES["app_param"], [""])[-1].lower() in RULES["app_on"],
                            "status": status}) + "\n")
    print("status: %d" % status)
    for key, value in headers.items():
        print("%s: %s" % (key.lower(), value))
    print()
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
'''

APP_SOURCE = '''"""Builds the tracking link our ad campaigns use. The link vendor serves it at __HOST__."""
from urllib.parse import urlencode

LINK = "__HOST__/abc1"
PARAMS = {
    "pid": "demo_int",
    "c": "test",
    "is_retargeting": "true",
    "af_dp": "demoapp://",
    "deep_link_value": "demoapp://home",
    "clickid": "test123",
}


def build_link(extra=None):
    return LINK + "?" + urlencode({**PARAMS, **(extra or {})})


if __name__ == "__main__":
    print(build_link())
'''


def sim_source() -> str:
    packed = base64.b64encode(zlib.compress(json.dumps(RULES).encode())).decode()
    return SIM_SOURCE.replace("__RULES__", packed).replace("__HOST__", HOST)


def sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def read_log(run: str | Path) -> list[dict]:
    """The simulator's request log; a line it didn't write whole is skipped."""
    path, rows = Path(run) / LOG, []
    for line in (path.read_text().splitlines() if path.is_file() else ()):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def fixture(run: str) -> dict:
    """Writes the simulator and the app's link code into the run folder; check_c1 gets the simulator's hash."""
    folder = Path(run)
    (folder / "app").mkdir(parents=True, exist_ok=True)
    (folder / SIM).write_text(sim_source())
    (folder / CODE).write_text(APP_SOURCE.replace("__HOST__", HOST))
    return {"sim_sha256": sha256(folder / SIM)}
