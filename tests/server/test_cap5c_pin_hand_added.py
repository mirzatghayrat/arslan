"""CAP5c: a hand-added `npx` or `uvx` package is pinned to one exact version, or refused (the CAP card, "a
hand-added MCP package's version"). The registry lookup is a stub; one test reads the real `_lookup` against a
mock transport."""
from types import SimpleNamespace

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from server.db import session as db_session
from server.db.models import MCPServer
from server.mcp import supervisor as sm
from server.services import mcp_pin, mcp_service


@pytest.fixture
def registry(monkeypatch):
    """The registries' answers, by (kind, name, tag): a version, or an exception to raise. Every call is kept."""
    answers, calls = {}, []

    async def lookup(kind, name, tag):
        calls.append((kind, name, tag))
        answer = answers.get((kind, name, tag), "")
        if isinstance(answer, Exception):
            raise answer
        return answer
    monkeypatch.setattr(mcp_pin, "_lookup", lookup)
    monkeypatch.setattr(sm.supervisor, "schedule", lambda sid, **kw: None)
    return SimpleNamespace(answers=answers, calls=calls)


async def _stored():
    async with db_session.AsyncSessionLocal() as db:
        return [(row.command, row.args) for row in (await db.execute(select(MCPServer))).scalars()]


async def test_an_npx_package_with_no_version_is_pinned_to_the_latest(execution_db, registry):
    registry.answers[("npm", "@modelcontextprotocol/server-filesystem", "latest")] = "2026.1.14"
    added = await mcp_service.add_server("fs", "npx", ["-y", "@modelcontextprotocol/server-filesystem", "/data"], {})
    assert added["args"] == ["-y", "@modelcontextprotocol/server-filesystem@2026.1.14", "/data"]
    assert await _stored() == [("npx", added["args"])]
    assert registry.calls == [("npm", "@modelcontextprotocol/server-filesystem", "latest")]


async def test_an_npx_dist_tag_is_written_as_the_version_it_names(execution_db, registry):
    registry.answers[("npm", "notes-mcp", "next")] = "3.0.0-beta.1"
    added = await mcp_service.add_server("n", "npx", ["--yes", "notes-mcp@next"], {})
    assert added["args"] == ["--yes", "notes-mcp@3.0.0-beta.1"]


@pytest.mark.parametrize("command, args", [
    ("npx", ["-y", "notes-mcp@1.2.3"]),
    ("npx", ["-y", "@acme/notes@1.2.3-rc.1+build.5", "--port", "8080"]),
    ("uvx", ["mcp-server-fetch@2025.4.7"]),
    ("uvx", ["mcp-server-fetch==2025.4.7"]),
    ("uvx", ["--from", "mcp-server-time[cli]==2.0.1", "mcp-server-time"]),
])
async def test_an_exact_version_is_kept_as_written_and_nothing_is_asked(execution_db, registry, command, args):
    added = await mcp_service.add_server("x", command, args, {})
    assert added["args"] == args and registry.calls == []


@pytest.mark.parametrize("spec", ["notes-mcp@^1.2", "notes-mcp@~1", "notes-mcp@1.x", "notes-mcp@>=1",
                                  "notes-mcp@1", "notes-mcp@1.2", "notes-mcp@*", "notes-mcp@v1", "notes-mcp@x",
                                  "@acme/notes@^2"])
async def test_an_npx_range_is_refused_with_what_to_write(execution_db, registry, spec):
    with pytest.raises(mcp_pin.PinRefused, match=r"names a range\. Write an exact version, as .+@1\.2\.3"):
        await mcp_service.add_server("x", "npx", ["-y", spec], {})
    assert await _stored() == [] and registry.calls == []


@pytest.mark.parametrize("spec", ["mcp-server-fetch>=1", "mcp-server-fetch~=1.2", "mcp-server-fetch==1.*",
                                  "mcp-server-fetch@>1,<2"])
async def test_a_uvx_range_is_refused(execution_db, registry, spec):
    with pytest.raises(mcp_pin.PinRefused, match=r"names a range\. Write an exact version, as mcp-server-fetch"):
        await mcp_service.add_server("x", "uvx", [spec], {})
    assert await _stored() == [] and registry.calls == []


@pytest.mark.parametrize("command, args, flag", [
    ("npx", ["--registry", "https://npm.example", "notes-mcp"], "--registry"),
    ("npx", ["-y", "--node-options=--inspect", "notes-mcp"], "--node-options=--inspect"),
    ("npx", ["--", "notes-mcp"], "--"),
    ("uvx", ["--with", "extra", "mcp-server-fetch"], "--with"),
    ("uvx", ["--python", "3.12", "mcp-server-fetch"], "--python"),
    ("uvx", ["-y", "mcp-server-fetch"], "-y"),
])
async def test_a_flag_arslan_does_not_read_before_the_package_is_refused(execution_db, registry, command, args, flag):
    with pytest.raises(mcp_pin.PinRefused, match=f"{command}: {flag} comes before the package"):
        await mcp_service.add_server("x", command, args, {})
    assert await _stored() == [] and registry.calls == []


@pytest.mark.parametrize("failure, words", [
    (httpx.ConnectError("offline"), r"npm registry: no answer for notes-mcp@latest \(ConnectError\)"),
    (httpx.ReadTimeout("slow"), r"no answer for notes-mcp@latest \(ReadTimeout\)"),
    (httpx.HTTPStatusError("gone", request=httpx.Request("GET", "https://registry.npmjs.org/notes-mcp"),
                           response=httpx.Response(404)), r"no version found for notes-mcp@latest \(HTTP 404\)"),
    (ValueError("not json"), r"no answer for notes-mcp@latest \(ValueError\)"),
    ("", r"npm registry: no version found for notes-mcp@latest\. Write an exact version"),
    ("latest-ish", r"no version found for notes-mcp@latest"),
])
async def test_a_failed_lookup_refuses_the_server_and_says_what_was_tried(execution_db, registry, failure, words):
    registry.answers[("npm", "notes-mcp", "latest")] = failure
    with pytest.raises(mcp_pin.PinRefused, match=words):
        await mcp_service.add_server("x", "npx", ["-y", "notes-mcp"], {})
    assert await _stored() == []


async def test_a_failed_pypi_lookup_names_pypi(execution_db, registry):
    registry.answers[("pypi", "mcp-server-fetch", "latest")] = httpx.ConnectError("offline")
    with pytest.raises(mcp_pin.PinRefused, match=r"^PyPI: no answer for mcp-server-fetch@latest"):
        await mcp_service.add_server("x", "uvx", ["mcp-server-fetch"], {})


@pytest.mark.parametrize("args, pinned", [
    (["mcp-server-fetch"], ["mcp-server-fetch@2025.4.7"]),
    (["-q", "mcp-server-fetch@latest", "--ignore-robots-txt"], ["-q", "mcp-server-fetch@2025.4.7", "--ignore-robots-txt"]),
    (["mcp-server-fetch[socks]"], ["mcp-server-fetch[socks]@2025.4.7"]),
    (["--from", "mcp-server-fetch", "mcp-server-fetch"], ["--from", "mcp-server-fetch==2025.4.7", "mcp-server-fetch"]),
    (["--from=mcp-server-fetch[socks]", "fetch"], ["--from=mcp-server-fetch[socks]==2025.4.7", "fetch"]),
])
async def test_a_uvx_package_is_pinned_from_pypi(execution_db, registry, args, pinned):
    registry.answers[("pypi", "mcp-server-fetch", "latest")] = "2025.4.7"
    added = await mcp_service.add_server("x", "uvx", args, {})
    assert added["args"] == pinned and registry.calls == [("pypi", "mcp-server-fetch", "latest")]


@pytest.mark.parametrize("args, pinned", [
    (["-p", "notes-mcp", "notes"], ["-p", "notes-mcp@4.0.0", "notes"]),
    (["--package=notes-mcp", "notes", "--stdio"], ["--package=notes-mcp@4.0.0", "notes", "--stdio"]),
    (["-y", "--package", "notes-mcp", "-p", "notes-mcp@1.0.0", "notes"],
     ["-y", "--package", "notes-mcp@4.0.0", "-p", "notes-mcp@1.0.0", "notes"]),
])
async def test_npx_packages_named_by_flag_are_pinned_and_the_command_is_left(execution_db, registry, args, pinned):
    registry.answers[("npm", "notes-mcp", "latest")] = "4.0.0"
    assert (await mcp_service.add_server("x", "npx", args, {}))["args"] == pinned


@pytest.mark.parametrize("command, args", [
    ("npx", ["github:acme/notes-mcp"]), ("npx", ["acme/notes-mcp"]), ("npx", ["./notes-mcp"]),
    ("npx", ["https://example.com/notes-mcp.tgz"]), ("npx", ["notes@github:acme/notes"]),
    ("npx", ["notes@npm:other@1.0.0"]), ("npx", ["notes@file:../notes"]),
    ("uvx", ["git+https://github.com/acme/notes"]), ("uvx", ["notes @ https://example.com/notes.whl"]),
    ("uvx", ["./notes"]), ("uvx", ["--from", "git+https://github.com/acme/notes", "notes"]),
])
async def test_a_spec_that_is_not_a_registry_package_is_refused(execution_db, registry, command, args):
    with pytest.raises(mcp_pin.PinRefused, match="so it can't be pinned"):
        await mcp_service.add_server("x", command, args, {})
    assert registry.calls == []


@pytest.mark.parametrize("command, args", [("npx", []), ("npx", ["-y"]), ("npx", ["-q"]), ("uvx", []),
                                           ("uvx", ["-q"])])
async def test_no_package_at_all_is_refused(execution_db, registry, command, args):
    with pytest.raises(mcp_pin.PinRefused, match=f"{command}: no package to run"):
        await mcp_service.add_server("x", command, args, {})


@pytest.mark.parametrize("command, args", [
    ("bunx", ["notes-mcp"]), ("pnpm", ["dlx", "notes-mcp"]), ("npm", ["exec", "notes-mcp"]),
    ("docker", ["run", "-i", "acme/notes"]), ("/usr/local/bin/notes-mcp", ["--stdio"]), ("node", ["server.js"]),
    ("python3", ["-m", "notes_mcp"]),
])
async def test_other_launchers_are_left_as_written(execution_db, registry, command, args):
    """The stated limit: only npx and uvx are pinned."""
    added = await mcp_service.add_server("x", command, args, {})
    assert added["args"] == args and registry.calls == []


async def test_npx_named_by_its_path_is_pinned_too(execution_db, registry):
    registry.answers[("npm", "notes-mcp", "latest")] = "4.0.0"
    added = await mcp_service.add_server("x", "/opt/homebrew/bin/npx", ["-y", "notes-mcp"], {})
    assert added["args"] == ["-y", "notes-mcp@4.0.0"]


async def test_a_remote_server_is_not_looked_up(execution_db, registry):
    await mcp_service.add_server("r", "", [], {}, transport="http", url="https://mcp.example/api")
    assert registry.calls == []


async def test_the_form_gets_the_reason_as_a_400(execution_db, registry, monkeypatch):
    monkeypatch.setenv("ARSLAN_API_TOKEN", "")
    from server.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/mcp/servers", json={"label": "n", "command": "npx", "args": ["-y", "notes@^1"]})
    assert r.status_code == 400
    assert r.json()["detail"] == "npx: notes@^1 names a range. Write an exact version, as notes@1.2.3."
    assert await _stored() == []


async def test_the_real_lookup_asks_the_registries_for_exactly_that_package(monkeypatch):
    """`_lookup` itself, on a mock transport: the scoped name is escaped, npm's abbreviated document is asked for,
    the dist-tag is read, PyPI's latest is info.version, and a redirect is not followed."""
    seen = []

    def handler(request):
        seen.append((str(request.url), request.headers.get("accept")))
        if request.url.host == "registry.npmjs.org":
            return httpx.Response(200, json={"dist-tags": {"latest": "2.0.0", "next": "3.0.0-rc.1"}})
        if request.url.path == "/pypi/moved/json":
            return httpx.Response(301, headers={"location": "https://elsewhere.example/pypi/moved/json"})
        return httpx.Response(200, json={"info": {"version": "2025.4.7"}})

    real = httpx.AsyncClient
    monkeypatch.setattr(mcp_pin.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    assert await mcp_pin._lookup("npm", "@acme/notes", "next") == "3.0.0-rc.1"
    assert await mcp_pin._lookup("npm", "@acme/notes", "beta") == ""
    assert await mcp_pin._lookup("pypi", "mcp-server-fetch", "latest") == "2025.4.7"
    with pytest.raises(httpx.HTTPStatusError):
        await mcp_pin._lookup("pypi", "moved", "latest")
    assert seen[0] == ("https://registry.npmjs.org/@acme%2Fnotes", "application/vnd.npm.install-v1+json")
    assert seen[2][0] == "https://pypi.org/pypi/mcp-server-fetch/json"
    assert len(seen) == 4                                        # the redirect was not followed
