"""CAP5c: a hand-added `npx` or `uvx` package is pinned to one exact version, or refused (the CAP card, "a
hand-added MCP package's version"). The registry lookup is a stub; one test reads the real `_lookup` against a
mock transport."""
import asyncio
import re
from types import SimpleNamespace

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

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
    ("npx", ["-y", "--node-options=--inspect", "notes-mcp"], "--node-options=--inspect"),
    ("npx", ["--prefix", "/opt/x", "notes-mcp@1.2.3"], "--prefix"),
    ("npx", ["--", "notes-mcp"], "--"),
    ("uvx", ["--with", "extra", "mcp-server-fetch==1.0"], "--with"),
    ("uvx", ["-y", "mcp-server-fetch"], "-y"),
    ("uvx", ["--offline", "mcp-server-fetch"], "--offline"),
])
async def test_an_option_arslan_does_not_read_before_the_package_is_refused(execution_db, registry, command, args,
                                                                             flag):
    """#623 review M-1: the message names what Arslan reads before the package, and never says to move an option
    past it (uv and npx would hand that option to the server)."""
    with pytest.raises(mcp_pin.PinRefused, match=f"{command}: {flag} comes before the package. Before it, Arslan "
                                                 f"reads only ") as refused:
        await mcp_service.add_server("x", command, args, {})
    assert not re.search(r"(?i)put the package first|after the package|move", str(refused.value))
    assert await _stored() == [] and registry.calls == []


@pytest.mark.parametrize("command, args", [
    ("npx", ["--registry", "https://npm.internal", "notes-mcp@1.2.3"]),
    ("npx", ["--registry=https://npm.internal/", "-y", "notes-mcp@1.2.3", "--stdio"]),
    ("npx", ["--cache", "/tmp/npm-cache", "-y", "@acme/notes@2.0.0"]),
    ("uvx", ["--python", "3.12", "mcp-server-fetch==1.0.0"]),
    ("uvx", ["-p", "3.12", "--index-url", "https://pypi.internal/simple", "mcp-server-fetch@1.0"]),
    ("uvx", ["--isolated", "--python=3.12", "--extra-index-url", "https://x.internal/simple", "--from",
             "mcp-server-time==2.0.1", "mcp-server-time"]),
    ("uvx", ["--default-index", "https://x.internal/simple", "--index", "corp=https://y.internal/simple",
             "mcp-server-fetch==1.0"]),
])
async def test_an_exact_version_is_kept_whatever_known_options_come_before_it(execution_db, registry, command, args):
    """#623 review M-1: `uvx --python 3.12 foo==1.0.0` and `npx --registry … foo@1.2.3` were refused, and the
    advice moved the option to the server."""
    added = await mcp_service.add_server("x", command, args, {})
    assert added["args"] == args and registry.calls == []


@pytest.mark.parametrize("command, args, env, where", [
    ("npx", ["--registry", "https://npm.internal", "notes-mcp"], {}, "--registry"),
    ("npx", ["--registry=https://npm.internal", "-y", "notes-mcp@latest"], {}, "--registry"),
    ("npx", ["-y", "notes-mcp"], {"npm_config_registry": "https://npm.internal"}, "npm_config_registry"),
    ("npx", ["-y", "notes-mcp"], {"NPM_CONFIG_REGISTRY": "https://npm.internal/"}, "NPM_CONFIG_REGISTRY"),
    ("npx", ["-y", "notes-mcp"], {"npm_config_userconfig": "/Users/me/.npmrc-work"}, "npm_config_userconfig"),
    ("npx", ["-y", "-p", "notes-mcp", "--registry", "https://npm.internal", "notes"], {}, "--registry"),
    ("uvx", ["--index-url", "https://pypi.internal/simple", "mcp-server-fetch"], {}, "--index-url"),
    ("uvx", ["--default-index=https://pypi.internal/simple", "mcp-server-fetch"], {}, "--default-index"),
    ("uvx", ["--index", "corp=https://pypi.internal/simple", "mcp-server-fetch"], {}, "--index"),
    ("uvx", ["--extra-index-url", "https://pypi.internal/simple", "mcp-server-fetch@latest"], {}, "--extra-index-url"),
    ("uvx", ["mcp-server-fetch"], {"UV_INDEX_URL": "https://pypi.internal/simple"}, "UV_INDEX_URL"),
    ("uvx", ["mcp-server-fetch"], {"UV_DEFAULT_INDEX": "https://pypi.internal/simple"}, "UV_DEFAULT_INDEX"),
    ("uvx", ["mcp-server-fetch"], {"UV_INDEX": "corp=https://pypi.internal/simple"}, "UV_INDEX"),
    ("uvx", ["mcp-server-fetch"], {"UV_EXTRA_INDEX_URL": "https://pypi.internal/simple"}, "UV_EXTRA_INDEX_URL"),
    ("uvx", ["mcp-server-fetch"], {"UV_CONFIG_FILE": "/Users/me/uv-work.toml"}, "UV_CONFIG_FILE"),
])
async def test_another_registry_needs_an_exact_version(execution_db, registry, command, args, env, where):
    """#623 review L-2: the public registry's latest says nothing about the registry the line names."""
    with pytest.raises(mcp_pin.PinRefused, match=rf"names its own registry \({where}\).+Write an exact version"):
        await mcp_service.add_server("x", command, args, env)
    assert await _stored() == [] and registry.calls == []


@pytest.mark.parametrize("command, args, env", [
    ("npx", ["--registry", "https://registry.npmjs.org/", "-y", "notes-mcp"], {}),
    ("npx", ["-y", "notes-mcp"], {"npm_config_registry": "https://registry.npmjs.org"}),
    ("npx", ["--cache", "/tmp/c", "notes-mcp"], {"NODE_ENV": "production"}),
    ("uvx", ["--index-url", "https://pypi.org/simple/", "notes-mcp"], {}),
    ("uvx", ["--python", "3.12", "notes-mcp"], {"UV_INDEX_URL": "https://pypi.org/simple"}),
])
async def test_the_public_registry_named_or_known_options_alone_still_pin(execution_db, registry, command, args, env):
    registry.answers[("npm", "notes-mcp", "latest")] = "4.0.0"
    registry.answers[("pypi", "notes-mcp", "latest")] = "4.0.0"
    added = await mcp_service.add_server("x", command, args, env)
    assert [a for a in added["args"] if a.startswith("notes-mcp")] == ["notes-mcp@4.0.0"]


@pytest.mark.parametrize("command, args", [("npx", ["--registry"]), ("npx", ["-y", "--cache"]),
                                           ("uvx", ["--python"]), ("uvx", ["--from"])])
async def test_an_option_with_no_value_is_refused(execution_db, registry, command, args):
    with pytest.raises(mcp_pin.PinRefused, match=f"{command}: {args[-1]} has no value after it"):
        await mcp_service.add_server("x", command, args, {})


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
    (["-p", "notes-mcp@v1.2.3", "notes"], ["-p", "notes-mcp@1.2.3", "notes"]),
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
    ("python3", ["-m", "notes_mcp"]), ("bun", ["x", "notes-mcp"]), ("npm", ["x", "notes-mcp"]),
    ("yarn", ["dlx", "notes-mcp"]), ("pipx", ["run", "notes-mcp"]), ("uv", ["run", "--with", "x", "notes"]),
    ("env", ["npx", "-y", "notes-mcp"]), ("sh", ["-c", "npx -y notes-mcp"]), ("bash", ["-lc", "npx -y notes-mcp"]),
])
async def test_other_launchers_are_left_as_written(execution_db, registry, command, args):
    """The stated limit: only npx and uvx are pinned."""
    added = await mcp_service.add_server("x", command, args, {})
    assert added["args"] == args and registry.calls == []


@pytest.mark.parametrize("command", ["/opt/homebrew/bin/npx", "Npx", "NPX", " npx ", "/usr/local/bin/Npx"])
async def test_npx_is_found_by_its_path_and_case_blind(execution_db, registry, command):
    """#623 review L-1: the Mac's file system finds `Npx`, and it ran unpinned."""
    registry.answers[("npm", "notes-mcp", "latest")] = "4.0.0"
    added = await mcp_service.add_server("x", command, ["-y", "notes-mcp"], {})
    assert added["args"] == ["-y", "notes-mcp@4.0.0"]


@pytest.mark.parametrize("command, runtime", [("Npx", "node"), ("UVX", "uv"), ("Node", "node"), ("npx", "node"),
                                              ("/opt/homebrew/bin/npx", None), ("bunx", None)])
def test_arslans_own_runtime_is_found_case_blind(command, runtime):
    """#623 review L-1: spawn_env's lookup reads the command the same way, so a pinned `Npx` runs Arslan's npx."""
    from server.mcp import spawn_env
    assert spawn_env.runtime_for(command) == runtime


@pytest.mark.parametrize("args, pinned", [
    (["tool", "run", "mcp-server-fetch"], ["tool", "run", "mcp-server-fetch@2025.4.7"]),
    (["tool", "run", "--python", "3.12", "--from", "mcp-server-fetch", "fetch"],
     ["tool", "run", "--python", "3.12", "--from", "mcp-server-fetch==2025.4.7", "fetch"]),
])
async def test_uv_tool_run_is_read_as_uvx(execution_db, registry, args, pinned):
    """#623 review L-3."""
    registry.answers[("pypi", "mcp-server-fetch", "latest")] = "2025.4.7"
    assert (await mcp_service.add_server("x", "uv", args, {}))["args"] == pinned


async def test_uv_tool_run_names_itself_in_a_refusal(execution_db, registry):
    with pytest.raises(mcp_pin.PinRefused, match=r"^uv tool run: --with comes before the package"):
        await mcp_service.add_server("x", "uv", ["tool", "run", "--with", "x", "mcp-server-fetch"], {})


async def test_a_remote_server_is_not_looked_up(execution_db, registry):
    await mcp_service.add_server("r", "", [], {}, transport="http", url="https://mcp.example/api")
    assert registry.calls == []


async def test_the_form_gets_the_reason_as_a_400(execution_db, registry, monkeypatch):
    monkeypatch.setenv("ARSLAN_API_TOKEN", "")
    from server.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/mcp/servers", json={"label": "n", "command": "npx", "args": ["-y", "notes@^1"]})
        blank = await c.post("/api/v1/mcp/servers", json={"label": "  ", "command": "npx", "args": ["x@1.0.0"]})
    assert r.status_code == 400
    assert r.json()["detail"] == "npx: notes@^1 names a range. Write an exact version, as notes@1.2.3."
    assert (blank.status_code, blank.json()["detail"]) == (400, "a label is required")
    assert await _stored() == []


async def test_only_the_forms_own_refusals_are_a_400(execution_db, registry, monkeypatch):
    """#623 review L-6: the catch covered the commit and `_to_dict` too; any other ValueError is not the form's."""
    monkeypatch.setenv("ARSLAN_API_TOKEN", "")

    def broken(srv, **kw):
        raise ValueError("the row would not render")
    monkeypatch.setattr(mcp_service, "_to_dict", broken)
    from server.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        with pytest.raises(ValueError, match="would not render"):
            await c.post("/api/v1/mcp/servers", json={"label": "n", "command": "x", "args": []})


@pytest.mark.parametrize("command, args", [
    ("npx", ["https://me:hunter2pass@npm.example/notes.tgz"]),
    ("npx", ["--userconfig=https://npm.example/?token=tok_example_42abcdef", "notes-mcp"]),
    ("uvx", ["git+https://me:hunter2pass@git.example/notes"]),
    ("npx", ["notes-mcp@https://me:hunter2pass@npm.example/x"]),
])
async def test_a_refusal_never_echoes_a_secret_in_the_argument(execution_db, registry, command, args):
    """#623 review L-6: what the form echoes goes through SEC1's masking."""
    with pytest.raises(mcp_pin.PinRefused) as refused:
        await mcp_service.add_server("x", command, args, {})
    text = str(refused.value)
    assert "hunter2pass" not in text and "tok_example_42abcdef" not in text and "\u25cf" in text


# ── #623 review L-5: the reviewer's witness tests, each red under a mutant that survived ──────────────────────


@pytest.mark.parametrize("answer", ["", "1.0 ; x", "not a version", "1..0"])
async def test_a_bad_pypi_answer_is_refused(execution_db, registry, answer):
    registry.answers[("pypi", "mcp-server-fetch", "latest")] = answer
    with pytest.raises(mcp_pin.PinRefused, match=r"^PyPI: no version found"):
        await mcp_service.add_server("x", "uvx", ["mcp-server-fetch"], {})


@pytest.mark.parametrize("spec", ["notes-mcp@1.2.3||>=2", "notes-mcp@1.2.3 - 9.0.0", "notes-mcp@1.2.3 || 2"])
async def test_an_exact_looking_range_is_refused(execution_db, registry, spec):
    with pytest.raises(mcp_pin.PinRefused, match=r"names a range"):
        await mcp_service.add_server("x", "npx", ["-y", spec], {})


async def test_the_same_unpinned_line_twice_is_one_server(execution_db, registry):
    registry.answers[("npm", "notes-mcp", "latest")] = "4.0.0"
    first = await mcp_service.add_server("n", "npx", ["-y", "notes-mcp"], {})
    again = await mcp_service.add_server("n", "npx", ["-y", "notes-mcp"], {})
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(select(func.count()).select_from(MCPServer))).scalar_one()
    assert first["id"] == again["id"] and rows == 1


# ── #623 review I-1 / I-2 ─────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("spec", ["notes-mcp@1..0", "notes-mcp@1.2.3-.", "notes-mcp@01.2.3", "notes-mcp@1.2.3+",
                                  "notes-mcp@1.2.3.4"])
async def test_an_npm_version_is_exact_only_by_semver(execution_db, registry, spec):
    with pytest.raises(mcp_pin.PinRefused, match="names a range"):
        await mcp_service.add_server("x", "npx", [spec], {})


@pytest.mark.parametrize("spec", ["mcp-server-fetch==1..0", "mcp-server-fetch@1.0-", "mcp-server-fetch==1.0 ; x"])
async def test_a_pypi_version_is_exact_only_by_pep_440(execution_db, registry, spec):
    with pytest.raises(mcp_pin.PinRefused, match="names a range"):
        await mcp_service.add_server("x", "uvx", [spec], {})


@pytest.mark.parametrize("spec, pinned", [("notes-mcp@v1.2.3", "notes-mcp@1.2.3"), ("notes-mcp@=1.2.3", "notes-mcp@1.2.3"),
                                          ("@acme/notes@=v2.0.0-rc.1", "@acme/notes@2.0.0-rc.1")])
async def test_npms_own_exact_forms_are_written_plain(execution_db, registry, spec, pinned):
    assert (await mcp_service.add_server("x", "npx", [spec], {}))["args"] == [pinned] and registry.calls == []


@pytest.mark.parametrize("command, spec", [("npx", "notes-mcp.tgz"), ("npx", "notes-1.0.0.tar.gz"),
                                           ("uvx", "notes-1.0-py3-none-any.whl"), ("uvx", "notes-1.0.zip")])
async def test_an_archive_name_is_not_looked_up(execution_db, registry, command, spec):
    with pytest.raises(mcp_pin.PinRefused, match="so it can't be pinned"):
        await mcp_service.add_server("x", command, [spec], {})
    assert registry.calls == []


async def test_one_deadline_covers_every_lookup(execution_db, monkeypatch):
    monkeypatch.setattr(sm.supervisor, "schedule", lambda sid, **kw: None)
    monkeypatch.setattr(mcp_pin, "DEADLINE_S", 0.2)
    asked = []

    async def slow(kind, name, tag):
        asked.append(name)
        await asyncio.sleep(0.15)
        return "1.0.0"
    monkeypatch.setattr(mcp_pin, "_lookup", slow)
    with pytest.raises(mcp_pin.PinRefused, match=r"^npx: the registry did not answer within 0 seconds"):
        await mcp_service.add_server("x", "npx", ["-p", "a", "-p", "b", "-p", "c", "run"], {})
    assert len(asked) < 3 and await _stored() == []


def _mock_client(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(mcp_pin.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


async def test_the_real_lookup_asks_the_registries_for_exactly_that_package(monkeypatch):
    """`_lookup` itself, on a mock transport: npm's dist-tags document for the escaped scoped name, PyPI's
    info.version, and no redirect followed but PyPI's own, once, to a canonical name (#623 review L-4)."""
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.host == "registry.npmjs.org":
            return httpx.Response(200, json={"latest": "2.0.0", "next": "3.0.0-rc.1"})
        path = request.url.path
        if path == "/pypi/Mcp_Server_Fetch/json":
            return httpx.Response(301, headers={"location": "/pypi/mcp-server-fetch/json"})
        if path == "/pypi/moved/json":
            return httpx.Response(301, headers={"location": "https://elsewhere.example/pypi/moved/json"})
        if path == "/pypi/twice/json":
            return httpx.Response(301, headers={"location": "https://pypi.org/pypi/twice-again/json"})
        if path == "/pypi/twice-again/json":
            return httpx.Response(301, headers={"location": "https://pypi.org/pypi/twice-final/json"})
        return httpx.Response(200, json={"info": {"version": "2025.4.7"}})

    _mock_client(monkeypatch, handler)
    assert await mcp_pin._lookup("npm", "@acme/notes", "next") == "3.0.0-rc.1"
    assert await mcp_pin._lookup("npm", "@acme/notes", "beta") == ""
    assert seen[0] == "https://registry.npmjs.org/-/package/@acme%2Fnotes/dist-tags"
    assert await mcp_pin._lookup("pypi", "mcp-server-fetch", "latest") == "2025.4.7"
    assert seen[2] == "https://pypi.org/pypi/mcp-server-fetch/json"
    assert await mcp_pin._lookup("pypi", "Mcp_Server_Fetch", "latest") == "2025.4.7"       # one canonical hop
    assert seen[3:5] == ["https://pypi.org/pypi/Mcp_Server_Fetch/json", "https://pypi.org/pypi/mcp-server-fetch/json"]
    for name in ("moved", "twice"):
        with pytest.raises(httpx.HTTPStatusError):
            await mcp_pin._lookup("pypi", name, "latest")
    assert "https://elsewhere.example/pypi/moved/json" not in seen
    assert "https://pypi.org/pypi/twice-final/json" not in seen


async def test_an_answer_past_the_size_cap_is_no_answer(monkeypatch):
    monkeypatch.setitem(mcp_pin.MAX_BYTES, "npm", 64)
    _mock_client(monkeypatch, lambda request: httpx.Response(200, json={"latest": "1.0.0", "pad": "x" * 200}))
    with pytest.raises(mcp_pin.ResponseTooLarge):
        await mcp_pin._lookup("npm", "notes-mcp", "latest")
    with pytest.raises(mcp_pin.PinRefused, match=r"no answer for notes-mcp@latest \(ResponseTooLarge\)"):
        await mcp_pin._exact("npm", "notes-mcp", "latest")
