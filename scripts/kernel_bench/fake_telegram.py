"""A local stand-in for the Telegram Bot API (127.0.0.1 only) for T6.

The entrant's Telegram integration is pointed at http://127.0.0.1:<port>/bot
(python-telegram-bot style base_url). The fake delivers one message from a
test chat through getUpdates and records everything the bot sends back,
including document bytes. No real token, no network, no phone needed.
"""
from __future__ import annotations

import json
import threading
import time
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CHAT_ID = 424242


class FakeTelegram:
    def __init__(self, text: str, port: int = 0):
        self.updates = [{"update_id": 1, "message": {
            "message_id": 1, "date": int(time.time()), "text": text,
            "chat": {"id": CHAT_ID, "type": "private", "first_name": "Bench"},
            "from": {"id": CHAT_ID, "is_bot": False, "first_name": "Bench", "username": "bench_user"}}}]
        self.sent: list[dict] = []
        self.calls: list[str] = []
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self.port = self._server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}/bot"

    def start(self) -> FakeTelegram:
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def _reply(self, result):
                data = json.dumps({"ok": True, "result": result}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _params(self, body: bytes) -> tuple[dict, list[dict]]:
                ctype = self.headers.get("Content-Type", "")
                if ctype.startswith("multipart/form-data"):
                    msg = BytesParser(policy=email_policy).parsebytes(
                        f"Content-Type: {ctype}\r\n\r\n".encode() + body)
                    fields, files = {}, []
                    for part in msg.iter_parts():
                        name = part.get_param("name", header="content-disposition")
                        filename = part.get_filename()
                        payload = part.get_payload(decode=True) or b""
                        if filename:
                            files.append({"field": name, "filename": filename, "bytes": payload})
                        else:
                            fields[name] = payload.decode(errors="replace")
                    return fields, files
                if ctype.startswith("application/json") and body:
                    return json.loads(body), []
                from urllib.parse import parse_qs
                return {k: v[0] for k, v in parse_qs(body.decode(errors="replace")).items()}, []

            def do_GET(self):
                self.do_POST()

            def do_POST(self):
                method = self.path.rstrip("/").rsplit("/", 1)[-1]
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                fields, files = self._params(body)
                with fake._lock:
                    fake.calls.append(method)
                if method == "getMe":
                    return self._reply({"id": 777, "is_bot": True, "first_name": "BenchBot", "username": "bench_bot",
                                        "can_join_groups": False, "can_read_all_group_messages": False,
                                        "supports_inline_queries": False})
                if method == "getUpdates":
                    offset = int(fields.get("offset") or 0)
                    with fake._lock:
                        pending = [u for u in fake.updates if u["update_id"] >= offset]
                    if not pending:
                        time.sleep(0.5)       # stand-in for long polling, never a spin
                    return self._reply(pending)
                if method in ("sendMessage", "sendDocument", "sendPhoto"):
                    record = {"method": method, "chat_id": fields.get("chat_id"),
                              "text": fields.get("text") or fields.get("caption") or "",
                              "files": [{"filename": f["filename"], "bytes": f["bytes"]} for f in files]}
                    with fake._lock:
                        fake.sent.append(record)
                    return self._reply({"message_id": len(fake.sent) + 1, "date": int(time.time()),
                                        "chat": {"id": CHAT_ID, "type": "private"}})
                return self._reply(True)   # setMyCommands, deleteWebhook, sendChatAction, ...

        return Handler
