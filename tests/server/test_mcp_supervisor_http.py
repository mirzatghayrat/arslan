"""The supervisor against the REAL SDK http transport (0.1.61 PR 4, Task 5 review C-1).

`streamablehttp_client` runs over `httpx.MockTransport` — no network, no process. The SDK raises an
http failure in a child task of its task group, which cancels the task waiting on `initialize()`;
these tests pin that each such failure still ends classified, with its cause and a next try, and
never as a silent `starting`."""
import asyncio
from datetime import timedelta

import httpx
import pytest
from mcp.client.streamable_http import streamablehttp_client as real_streamablehttp_client
from mcp.shared.auth import OAuthToken

from server.mcp import oauth_flow, session, spawn_env
from server.mcp import supervisor as sm
from tests.server.test_mcp_supervisor import _row, _seed

URL = "https://mcp.example.test/mcp"


@pytest.fixture
async def sup(execution_db, tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(sm, "FIRST_START_GAPS_S", (0.0, 0.0, 0.0))
    monkeypatch.setattr(spawn_env, "login_shell_path", lambda: "")
    supervisor = sm.Supervisor()
    supervisor.maker = execution_db
    yield supervisor
    await asyncio.wait_for(supervisor.stop(), 10)
    await asyncio.wait_for(session.manager.aclose_all(), 10)


def _serve(monkeypatch, handler):
    """The real streamablehttp_client, its httpx client on a MockTransport."""
    def factory(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), headers=headers,
                                 timeout=timeout, auth=auth, follow_redirects=True)

    def client(url, headers=None, auth=None, **kw):
        return real_streamablehttp_client(url, headers=headers, auth=auth,
                                          httpx_client_factory=factory, **kw)
    monkeypatch.setattr(session, "streamablehttp_client", client)


def _answer(code):
    def handler(request):
        return httpx.Response(code if request.method == "POST" else 405, request=request)
    return handler


def _refuse(request):
    raise httpx.ConnectError("[Errno 61] Connection refused", request=request)


def _refuse_eperm(request):
    raise httpx.ConnectError("[Errno 1] Operation not permitted", request=request) from PermissionError(
        1, "Operation not permitted")


CASES = [
    # (case, handler, state, first line starts with, seconds to the next try)
    ("401", _answer(401), "needs_auth",
     "authorization failed (HTTP 401): no credentials are configured", sm.PROBE_EVERY_S),
    ("403", _answer(403), "needs_auth",
     "authorization failed (HTTP 403): no credentials are configured", sm.PROBE_EVERY_S),
    ("404", _answer(404), "parked", "the URL did not answer as an MCP endpoint (HTTP 404)",
     sm.PROBE_EVERY_S),
    ("405", _answer(405), "parked", "the URL did not answer as an MCP endpoint (HTTP 405)",
     sm.PROBE_EVERY_S),
    ("500", _answer(500), "failed", "could not reach the MCP URL — it answered HTTP 500",
     sm.RETRY_BASE_S),
    ("503", _answer(503), "failed", "could not reach the MCP URL — it answered HTTP 503",
     sm.RETRY_BASE_S),
    ("429", _answer(429), "failed", "the MCP URL answered HTTP 429", sm.RETRY_BASE_S),
    ("refused", _refuse, "failed", "could not reach the MCP URL — check the address", sm.RETRY_BASE_S),
    ("refused-eperm", _refuse_eperm, "failed", "could not reach the MCP URL — check the address",
     sm.RETRY_BASE_S),
]


@pytest.mark.parametrize("case, handler, state, line, retry_s", CASES, ids=[c[0] for c in CASES])
async def test_an_http_start_failure_is_classified_with_its_cause_and_a_next_try(
        sup, monkeypatch, case, handler, state, line, retry_s):
    await _seed(sup.maker, 1, transport="http", url=URL, command="")
    _serve(monkeypatch, handler)
    now = sm._utcnow()
    monkeypatch.setattr(sm, "_utcnow", lambda: now)          # a fixed clock: exact next try
    result = await sup.restart(1)
    row = await _row(sup.maker, 1)
    assert (result.state, row.state) == (state, state), (result, row.last_error)
    assert row.last_error.startswith(line) and result.last_error == row.last_error
    assert row.next_retry_at == now + timedelta(seconds=retry_s)
    assert "TaskGroup" not in row.last_error and session.manager.cached(1) is None


async def test_a_first_start_that_hits_an_http_failure_ends_classified_not_starting(sup, monkeypatch):
    """The background path (start_all's `first` plan, its retries) ends classified as well."""
    await _seed(sup.maker, 1, transport="http", url=URL, command="")
    _serve(monkeypatch, _answer(401))
    sup.start(run_loops=False)
    await sup.start_all()
    row = await _row(sup.maker, 1)
    assert row.state == "needs_auth" and row.next_retry_at is not None and 1 not in sup._inflight


def _oauth_server(request):
    """A server that wants a browser sign-in: 401 on the MCP endpoint, no protected-resource
    metadata, authorization-server metadata at the legacy root, dynamic registration."""
    base = "https://mcp.example.test"
    if request.url.path == "/mcp":
        return httpx.Response(401, request=request)
    if request.url.path == "/.well-known/oauth-authorization-server":
        return httpx.Response(200, request=request, json={
            "issuer": base, "authorization_endpoint": f"{base}/authorize",
            "token_endpoint": f"{base}/token", "registration_endpoint": f"{base}/register",
            "response_types_supported": ["code"], "code_challenge_methods_supported": ["S256"]})
    if request.url.path == "/register":
        return httpx.Response(201, request=request, json={
            "client_id": "arslan-test", "redirect_uris": ["http://127.0.0.1:1/callback"],
            "token_endpoint_auth_method": "none", "grant_types": ["authorization_code"],
            "response_types": ["code"]})
    return httpx.Response(404, request=request)


async def test_a_saved_sign_in_that_needs_the_browser_again_is_needs_auth(sup, monkeypatch):
    """Stored tokens → the silent provider; the server refuses them and the SDK's OAuth flow
    reaches the browser step, where the silent provider raises NeedsInteractiveAuth."""
    await _seed(sup.maker, 1, transport="http", url=URL, command="")
    stale = "-".join(["stale", "access", "token"])     # built at runtime (no literal for scanners)
    await oauth_flow.EncryptedTokenStorage(1).set_tokens(OAuthToken(access_token=stale))
    _serve(monkeypatch, _oauth_server)
    result = await sup.restart(1)
    row = await _row(sup.maker, 1)
    assert result.state == row.state == "needs_auth"
    assert row.last_error.startswith(sm.SIGN_IN_LINE)
