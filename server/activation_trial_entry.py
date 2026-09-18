"""Bounded parent-pipe protocol for the packaged restricted recovery trial.

The parent supplies the existing secret and fresh trial token through stdin,
never arguments. No key-file discovery, generation or normal profile override.
"""
import json
import os
import re
import select
import stat
import sys
import time
from uuid import UUID

MAX_REQUEST = 16 * 1024


def decode_request(data: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("activation_trial_request_invalid")
            result[key] = value
        return result
    if len(data) > MAX_REQUEST:
        raise ValueError("activation_trial_request_invalid")
    value = json.loads(data, object_pairs_hook=unique)
    if not isinstance(value, dict) or set(value) != {"operation_id", "access_token", "secret"}:
        raise ValueError("activation_trial_request_invalid")
    if (not isinstance(value["operation_id"], str)
            or str(UUID(value["operation_id"])) != value["operation_id"]
            or not isinstance(value["access_token"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["access_token"])
            or not isinstance(value["secret"], str) or not value["secret"].strip()
            or len(value["secret"].encode()) > 8192):
        raise ValueError("activation_trial_request_invalid")
    return value


def read_request(fd: int, timeout: float = 10) -> dict:
    if not stat.S_ISFIFO(os.fstat(fd).st_mode):
        raise ValueError("activation_trial_pipe_required")
    deadline = time.monotonic() + timeout
    data = bytearray()
    while len(data) <= MAX_REQUEST:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
            raise ValueError("activation_trial_request_timeout")
        chunk = os.read(fd, min(4096, MAX_REQUEST + 1 - len(data)))
        if not chunk:
            raise ValueError("activation_trial_request_incomplete")
        data.extend(chunk)
        if b"\n" in data:
            line, remainder = data.split(b"\n", 1)
            if remainder:
                raise ValueError("activation_trial_request_invalid")
            return decode_request(bytes(line))
    raise ValueError("activation_trial_request_invalid")


def run(sanitize_env) -> int:
    try:
        # Configuration must not have bootstrapped before the pipe request.
        if "server.config" in sys.modules:
            raise ValueError("activation_trial_runtime_already_loaded")
        request = read_request(sys.stdin.fileno())
        sanitize_env()
        os.environ["ARSLAN_SECRET_KEY"] = request["secret"]
        os.environ["ARSLAN_SECRET_KEY_FILE"] = ""
        os.environ["ARSLAN_API_TOKEN"] = ""
        from server.config import settings
        from server.activation_trial import create_app
        app = create_app(settings.data_dir, request["operation_id"], request["access_token"])
        del request
        return serve(app)
    except Exception:  # noqa: BLE001 — bounded process boundary, never echo secret/input
        print("ARSLAN_ERROR=activation_trial_refused", flush=True)
        return 1


def serve(app) -> int:
    import socket
    import threading
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))

    def parent_closed():
        try:
            sys.stdin.read()
        finally:
            server.should_exit = True
            # A stuck startup/shutdown must not leave an orphan owning the profile.
            timer = threading.Timer(5, lambda: os._exit(1))
            timer.daemon = True
            timer.start()

    threading.Thread(target=parent_closed, daemon=True, name="trial-parent-watchdog").start()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        print(f"ARSLAN_TRIAL_PORT={sock.getsockname()[1]}", flush=True)
        server.run(sockets=[sock])
    return 0 if server.started else 1
