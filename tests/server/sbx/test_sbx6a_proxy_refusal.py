"""SBX-6a follow-up (v0.1.64, the #668 ruling): a proxy refusal names itself and reaches the model as a sandbox stop.

- The local proxy answers a destination the sandbox keeps closed (this Mac, the LAN, link-local) with a 403 whose
  reason says so, and the same line as a short body. Only that refusal is a 403: a request it can't take, a
  destination it can't reach and a full proxy each have their own status, so a client that prints only the code
  (curl, git) still tells them apart. No reply names a host, an address or a URL.
- `terminal_exec` reads that refusal in a sandboxed command's output as a sandbox stop: the note says what the proxy
  refused and the way out, and SBX-7's trace entry gets the code `proxy` (never the result).
"""
import asyncio
import json
import sys

import pytest

from server.orchestrator import run_trace
from server.registry.net_pin import _Unresolvable
from server.services import command_sandbox, sandbox_proxy, terminal_exec

macos = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                           reason="seatbelt is macOS-only")

DENIED_LINE = "403 Forbidden by Arslan's sandbox: local or non-public destination"


@pytest.fixture
async def proxy(monkeypatch):
    monkeypatch.setattr(sandbox_proxy.browser_proxy.net_pin, "getproxies", lambda: {})

    async def trusted():
        return []
    monkeypatch.setattr(sandbox_proxy, "_trusted", trusted)
    p = sandbox_proxy.LocalProxy()
    await p.start()
    yield p
    await p.close()


async def _ask(port: int, request: bytes) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(request)
    await writer.drain()
    data = await asyncio.wait_for(reader.read(65536), 5)
    writer.close()
    return data


def _status_and_body(reply: bytes) -> tuple[str, str]:
    head, _, body = reply.decode("latin-1").partition("\r\n\r\n")
    return head.split("\r\n", 1)[0].split(" ", 1)[1], body


def _names_nothing(reply: bytes, *spellings: str) -> None:
    text = reply.decode("latin-1")
    assert "http://" not in text and "https://" not in text, text
    for spelling in spellings:
        assert spelling not in text, (spelling, text)


# ── the proxy's answer, per refusal class ────────────────────────────────────

@pytest.mark.parametrize(("request_line", "spellings"), [
    (b"CONNECT 10.0.0.1:443 HTTP/1.1", ("10.0.0.1",)),                 # a LAN literal
    (b"CONNECT [::1]:8741 HTTP/1.1", ("::1", "8741")),                  # this Mac
    (b"CONNECT localhost:22 HTTP/1.1", ("localhost",)),                 # this Mac, by name
    (b"CONNECT nas.local:5000 HTTP/1.1", ("nas", "5000")),              # a local network name
    (b"GET http://169.254.169.254/latest/ HTTP/1.1", ("169.254", "latest")),   # link-local, plain http
    (b"GET http://192.168.1.2:8080/a?b=c HTTP/1.1", ("192.168", "8080", "b=c")),
])
async def test_a_closed_destination_gets_a_403_that_names_the_sandbox_and_no_address(proxy, request_line, spellings):
    """Unmocked: net_pin refuses these itself, before any lookup leaves this Mac."""
    reply = await _ask(proxy.port, request_line + b"\r\nHost: x\r\n\r\n")
    status, body = _status_and_body(reply)
    assert status == DENIED_LINE
    assert body == DENIED_LINE.split(" ", 1)[1] + "\n"                 # the same line, for a client that shows the body
    _names_nothing(reply, *spellings)


@pytest.mark.parametrize("request_line", [b"GET /relative HTTP/1.1", b"GET ftp://example.com/ HTTP/1.1",
                                          b"CONNECT example.com HTTP/1.1", b"CONNECT example.com:0 HTTP/1.1"])
async def test_a_request_it_cant_take_is_a_400_not_a_sandbox_refusal(proxy, request_line):
    reply = await _ask(proxy.port, request_line + b"\r\nHost: x\r\n\r\n")
    status, body = _status_and_body(reply)
    assert status.startswith("400 Bad Request") and body == status.split(" ", 1)[1] + "\n"
    assert "Forbidden" not in reply.decode("latin-1")
    _names_nothing(reply, "example.com", "relative")


async def test_a_name_that_doesnt_resolve_or_a_host_that_doesnt_answer_is_a_502(proxy, monkeypatch):
    def unresolvable(url, **kw):
        raise _Unresolvable("cannot resolve nowhere.example")
    monkeypatch.setattr(sandbox_proxy, "_resolve_pinned", unresolvable)
    dead = _status_and_body(await _ask(proxy.port, b"CONNECT nowhere.example:443 HTTP/1.1\r\nHost: x\r\n\r\n"))

    closed = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port = closed.sockets[0].getsockname()[1]
    closed.close()
    await closed.wait_closed()                                         # nothing listens there now
    monkeypatch.setattr(sandbox_proxy, "_resolve_pinned", lambda url, **kw: ("127.0.0.1", "example.com", port))
    reply = await _ask(proxy.port, b"CONNECT example.com:443 HTTP/1.1\r\nHost: x\r\n\r\n")
    for status, body in (dead, _status_and_body(reply)):
        assert status.startswith("502 Bad Gateway") and body == status.split(" ", 1)[1] + "\n"
    _names_nothing(reply, "example.com", str(port), "127.0.0.1")


@pytest.mark.parametrize("answer", [b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n", b"not http\r\n\r\n", b""])
async def test_a_system_proxy_that_refuses_is_a_502(monkeypatch, answer):
    async def upstream(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(answer)
        await writer.drain()
        writer.close()
    server = await asyncio.start_server(upstream, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setattr(sandbox_proxy.browser_proxy.net_pin, "getproxies", lambda: {"https": f"http://127.0.0.1:{port}"})
    monkeypatch.setattr(sandbox_proxy.browser_proxy.net_pin, "proxy_bypass", lambda host: False)
    monkeypatch.setattr(sandbox_proxy, "_resolve_pinned", lambda url, **kw: ("93.184.216.34", "example.com", 443))

    async def trusted():
        return []
    monkeypatch.setattr(sandbox_proxy, "_trusted", trusted)
    p = sandbox_proxy.LocalProxy()
    await p.start()
    try:
        reply = await _ask(p.port, b"CONNECT example.com:443 HTTP/1.1\r\nHost: x\r\n\r\n")
    finally:
        await p.close()
        server.close()
    assert _status_and_body(reply)[0].startswith("502 Bad Gateway"), reply
    _names_nothing(reply, "example.com", str(port))


async def test_a_system_proxy_setting_it_cant_use_is_a_502_not_the_sandboxs_403(proxy, monkeypatch):
    """`_upstream_proxy` refuses a malformed setting with ValueError; nothing goes, but the destination wasn't judged."""
    def unusable(name):
        raise ValueError
    monkeypatch.setattr(sandbox_proxy.browser_proxy, "_upstream_proxy", unusable)
    reply = await _ask(proxy.port, b"CONNECT example.com:443 HTTP/1.1\r\nHost: x\r\n\r\n")
    status, body = _status_and_body(reply)
    assert status.startswith("502 Bad Gateway") and body == status.split(" ", 1)[1] + "\n"
    _names_nothing(reply, "example.com")


async def test_a_full_proxy_is_a_503(proxy, monkeypatch):
    monkeypatch.setattr(sandbox_proxy, "_CONNECTIONS", 0)
    reply = await _ask(proxy.port, b"CONNECT example.com:443 HTTP/1.1\r\nHost: x\r\n\r\n")
    assert _status_and_body(reply)[0].startswith("503 Service Unavailable"), reply


def test_the_sandbox_reads_the_proxys_own_refusal_and_only_it():
    """The proxy's text and command_sandbox's pattern are written in two files: this keeps them the same."""
    status, reason = sandbox_proxy.DENIED
    assert f"{status} {reason}" == DENIED_LINE
    run = {"sandbox": "workspace", "ok": False, "exit_code": 1, "stdout": ""}
    assert command_sandbox.proxy_refused({**run, "stderr": f"Tunnel connection failed: {status} {reason}"})
    for status, reason in (sandbox_proxy.BAD_REQUEST, sandbox_proxy.UNREACHABLE, sandbox_proxy.BUSY):
        assert status != 403
        assert not command_sandbox.proxy_refused({**run, "stderr": f"Tunnel connection failed: {status} {reason}"})
        assert not command_sandbox.proxy_refused({**run, "stderr": f"curl: (56) CONNECT tunnel failed, response {status}"})


# ── terminal_exec: a stop, a note and the code ───────────────────────────────

_PYTHON = "Tunnel connection failed: " + DENIED_LINE
_URLLIB = "urllib.error.HTTPError: HTTP Error " + DENIED_LINE.replace("403 ", "403: ", 1)
_CURL = "curl: (56) CONNECT tunnel failed, response 403"
_OLD_CURL = "curl: (56) Received HTTP code 403 from proxy after CONNECT"
_GIT = "fatal: unable to access 'https://lan.example/x.git/': CONNECT tunnel failed, response 403"


async def _run(tmp_path, monkeypatch, command: str, **kw) -> tuple[dict, list[dict]]:
    monkeypatch.setattr(command_sandbox, "wrapper", lambda *a, **k: ["/usr/bin/env"])     # runs it as "workspace"
    with run_trace.collecting() as trace:
        result = await terminal_exec.run(command, cwd=tmp_path, sandbox=True, **kw)
        run_trace.record(tool="run_command", args={}, result=result, ok=bool(result["ok"]), error=result.get("error"),
                         ms=5)
    return result, trace


def _shows_the_proxy_note(result: dict) -> None:
    note = result["note"]
    assert "Arslan's proxy" in note and "local or non-public destination" in note
    assert "outside_sandbox: true" in note
    assert "may write only inside the working folder" not in note       # a network stop, not the file rules
    assert "device" not in note           # the model is never offered a device: the window's card is (SBX settings)


@pytest.mark.parametrize("printed", [_PYTHON, _URLLIB, _CURL, _OLD_CURL, _GIT])
async def test_a_proxy_refusal_is_a_sandbox_stop_with_a_note_and_the_proxy_code(tmp_path, monkeypatch, printed):
    result, trace = await _run(tmp_path, monkeypatch, f"printf '%s\\n' \"{printed}\" >&2; exit 1")
    assert result["sandbox_denied"] is True
    assert result["error"] == "the sandbox stopped this command (exit code 1)"
    _shows_the_proxy_note(result)
    assert trace[0].get("denial") == "proxy"
    assert "denial" not in json.dumps({k: v for k, v in result.items() if k != "note"})


async def test_a_client_that_exits_0_on_the_refusal_still_gets_the_note_and_the_code(tmp_path, monkeypatch):
    """curl without -f prints a plain-http refusal's body and exits 0; a script may print the status and go on."""
    body = DENIED_LINE.split(" ", 1)[1]
    result, trace = await _run(tmp_path, monkeypatch, f"printf '%s\\n' \"{body}\"")
    assert result["ok"] is True and "sandbox_denied" not in result and "error" not in result
    _shows_the_proxy_note(result)
    assert trace[0].get("denial") == "proxy"


@pytest.mark.parametrize("printed", ["HTTP Error 403: Forbidden", "curl: (22) The requested URL returned error: 403",
                                     "Tunnel connection failed: 502 Bad Gateway"])
async def test_a_servers_own_403_or_a_failed_connection_is_not_a_sandbox_stop(tmp_path, monkeypatch, printed):
    result, trace = await _run(tmp_path, monkeypatch, f"printf '%s\\n' \"{printed}\" >&2; exit 1")
    assert "sandbox_denied" not in result and "note" not in result and result["error"] == "exit code 1"
    assert trace[0].get("denial") is None


async def test_an_eperm_beside_a_proxy_refusal_keeps_its_eperm_code(tmp_path, monkeypatch):
    result, trace = await _run(tmp_path, monkeypatch,
                               f"printf '%s\\n' 'x: Operation not permitted' \"{_CURL}\" >&2; exit 1")
    assert result["sandbox_denied"] is True and trace[0].get("denial") == "eperm"


async def test_a_proxy_refusal_beside_a_failed_certificate_check_still_records_proxy(tmp_path, monkeypatch):
    """A certificate failure alone records no code; next to the proxy's refusal the refusal is still counted."""
    result, trace = await _run(tmp_path, monkeypatch,
                               f"printf '%s\\n' 'x509: OSStatus -26276' \"{_CURL}\" >&2; exit 1")
    assert result["sandbox_denied"] is True and trace[0].get("denial") == "proxy"
    _shows_the_proxy_note(result)
    assert "certificate check" in result["note"]


async def test_outside_the_sandbox_the_text_means_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(command_sandbox, "outside_wrapper", lambda **kw: ["/usr/bin/env"])
    with run_trace.collecting() as trace:
        result = await terminal_exec.run(f"printf '%s\\n' \"{_CURL}\" >&2; exit 1", cwd=tmp_path, sandbox=False)
        run_trace.record(tool="run_command", args={}, result=result, ok=False, error=result.get("error"), ms=5)
    assert result["sandbox"] == "outside" and "note" not in result and trace[0].get("denial") is None


async def test_a_real_client_through_the_real_proxy_gets_the_note(tmp_path, monkeypatch):
    """Python's own client, through the proxy terminal_exec started and pointed it at (no seatbelt here: the stand-in
    wrapper), to a LAN literal net_pin refuses without a lookup."""
    monkeypatch.setattr(sandbox_proxy.browser_proxy.net_pin, "getproxies", lambda: {})

    async def trusted():
        return []
    monkeypatch.setattr(sandbox_proxy, "_trusted", trusted)
    sandbox_proxy._reset_for_tests()
    client = (f"{sys.executable} -I -c \"import urllib.request as u; "
              "u.urlopen('https://10.0.0.1/', timeout=5)\"")
    try:
        result, trace = await _run(tmp_path, monkeypatch, client)
    finally:
        await sandbox_proxy.shutdown()
    assert result["sandbox_denied"] is True, result["stderr"][-400:]
    _shows_the_proxy_note(result)
    assert trace[0].get("denial") == "proxy"


# ── under real seatbelt (macOS) ──────────────────────────────────────────────

@pytest.mark.macos
@macos
@pytest.mark.parametrize("scheme", ["https", "http"])
async def test_curl_in_the_sandbox_to_a_loopback_destination_gets_the_refusal_and_the_note(tmp_path, scheme):
    """`--noproxy ''` sends even loopback to the proxy (NO_PROXY would send it to the kernel's rule). https: curl
    prints the refused CONNECT's code and exits 56. http: curl prints the refusal's body and exits 0."""
    sandbox_proxy._reset_for_tests()
    try:
        with run_trace.collecting() as trace:
            result = await terminal_exec.run(f"/usr/bin/curl -sS --max-time 10 --noproxy '' {scheme}://127.0.0.1:9/",
                                             cwd=tmp_path, sandbox=True)
            run_trace.record(tool="run_command", args={}, result=result, ok=bool(result["ok"]),
                             error=result.get("error"), ms=5)
    finally:
        await sandbox_proxy.shutdown()
    assert result["sandbox"] == "workspace", result.get("sandbox")
    if scheme == "https":
        assert result["sandbox_denied"] is True and "CONNECT tunnel failed, response 403" in result["stderr"]
    else:
        assert result["ok"] is True and DENIED_LINE.split(" ", 1)[1] in result["stdout"]
    _shows_the_proxy_note(result)
    assert trace[0].get("denial") == "proxy"
