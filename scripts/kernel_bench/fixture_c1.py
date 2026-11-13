"""C1 stub: a tracking link that opens the app on Android but sends iPhones to the App Store (harness plan §4.1,
the capability set's first task, from a 2026-11-12 same-question comparison). On 127.0.0.1 only, with made-up
names: no real attribution vendor, app or link.

- `/.well-known/apple-app-site-association` and `/.well-known/assetlinks.json`: valid, `/abc1/*`.
- `/abc1` (and `/abc1/...`) with an iPhone or iPad user agent: 301 to the App Store, empty body. This is the bug.
- The same with `force_deeplink=true` in the query: 200, a page that opens `demoapp://home` and falls back to the
  store. This is the fix. Nothing else changes the iPhone answer (a trailing slash, other parameters, no macros).
- With an Android user agent: 200, a page that tries `intent://` and then `demoapp://home`.
- Any other user agent (a desktop browser, plain curl): 302 to a web landing page.

Every request is logged with its user agent, path, query and the status it got; check_c1 reads that log (server
state), not the agent's word.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

STORE = "https://apps.apple.com/app/id0000000000"
LANDING = "https://www.example.com/demoapp"
QUERY = ("pid=demo_int&c=test&is_retargeting=true&af_dp=demoapp%3A%2F%2F&deep_link_value=demoapp%3A%2F%2Fhome"
         "&clickid=test123")
AASA = {"applinks": {"details": [{"appIDs": ["ABCDE12345.com.example.demoapp"], "components": [{"/": "/abc1/*"}]}]}}
ASSETLINKS = [{"relation": ["delegate_permission/common.handle_all_urls"],
               "target": {"namespace": "android_app", "package_name": "com.example.demoapp",
                          "sha256_cert_fingerprints": ["00:" * 31 + "00"]}}]
IOS_PAGE = ('<html><body><script>window.location = "demoapp://home";'
            f'setTimeout(function () {{ window.location = "{STORE}"; }}, 1500);</script></body></html>')
ANDROID_PAGE = ('<html><body><script>window.location = '
                '"intent://home#Intent;scheme=demoapp;package=com.example.demoapp;end";'
                'setTimeout(function () { window.location = "demoapp://home"; }, 800);</script></body></html>')


def device(ua: str) -> str:
    if "iPhone" in ua or "iPad" in ua:
        return "ios"
    return "android" if "Android" in ua else "other"


class Stub:
    def __init__(self, port: int = 0):
        self.requests: list[dict] = []
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self.port = self._server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}/abc1?{QUERY}"

    def start(self) -> Stub:
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def log(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.requests]

    def answer(self, path: str, query: dict, ua: str) -> tuple[int, dict, bytes]:
        if path == "/.well-known/apple-app-site-association":
            return 200, {"Content-Type": "application/json"}, json.dumps(AASA).encode()
        if path == "/.well-known/assetlinks.json":
            return 200, {"Content-Type": "application/json"}, json.dumps(ASSETLINKS).encode()
        if path != "/abc1" and not path.startswith("/abc1/"):
            return 404, {}, b""
        kind = device(ua)
        if kind == "ios":
            if query.get("force_deeplink", [""])[-1].lower() in ("true", "1"):
                return 200, {"Content-Type": "text/html"}, IOS_PAGE.encode()
            return 301, {"Location": STORE}, b""
        if kind == "android":
            return 200, {"Content-Type": "text/html"}, ANDROID_PAGE.encode()
        return 302, {"Location": LANDING}, b""

    def _handler(self):
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def _serve(self, body_too: bool) -> None:
                u = urlsplit(self.path)
                query = parse_qs(u.query, keep_blank_values=True)
                ua = self.headers.get("User-Agent", "")
                status, headers, body = stub.answer(u.path, query, ua)
                with stub._lock:
                    stub.requests.append({"t": round(time.time(), 3), "method": self.command, "path": u.path,
                                          "query": query, "ua": ua, "device": device(ua),
                                          "force": query.get("force_deeplink", [""])[-1].lower() in ("true", "1"),
                                          "status": status})
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body_too:
                    self.wfile.write(body)

            def do_GET(self):
                self._serve(True)

            def do_HEAD(self):
                self._serve(False)

            def log_message(self, *args):
                pass

        return Handler


def fixture(run: str) -> Stub:
    """Started for the run (runner.SITES); the runner stops it after the check. Nothing goes into the run folder."""
    return Stub().start()
