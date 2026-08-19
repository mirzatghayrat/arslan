"""Manifest detection rides the existing evaluate funnel (zero new choke points).

fetch_file stays inside the fixed-host api.github.com surface (owner/repo are
path segments, path is sanitized twice — here as defense, in the validator as
contract). evaluate_ref attaches `manifest` when present+valid,
`manifest_error` when present+broken, neither when absent — and a broken
manifest must NOT block the evaluation itself (the LLM-guess path stays the
fallback). Manifest skills[] install through the
EXISTING scan/import path (skill_import.import_skill — verbatim, frontmatter-
validated, ecosystem-compatible), so no new skill route exists.
"""
import httpx
import pytest

import server.services.github_eval as ge


def _stub_client(monkeypatch, *, status, text=""):
    class _Resp:
        def __init__(self):
            self.status_code = status
            self.text = text

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)


async def _noop_token():
    return ""


async def test_fetch_file_returns_body(monkeypatch):
    monkeypatch.setattr(ge, "_token", lambda: _noop_token())
    _stub_client(monkeypatch, status=200, text='{"schema_version": 1}')
    assert await ge.fetch_file("o", "r", "arslan.plugin.json") == '{"schema_version": 1}'


async def test_fetch_file_absent_is_empty(monkeypatch):
    monkeypatch.setattr(ge, "_token", lambda: _noop_token())
    _stub_client(monkeypatch, status=404)
    assert await ge.fetch_file("o", "r", "arslan.plugin.json") == ""


async def test_fetch_file_refuses_traversal_before_any_request(monkeypatch):
    def explode(*a, **k):
        raise AssertionError("no HTTP client may be constructed for a bad path")
    monkeypatch.setattr(httpx, "AsyncClient", explode)
    with pytest.raises(ValueError):
        await ge.fetch_file("o", "r", "../../../etc/passwd")
    with pytest.raises(ValueError):
        await ge.fetch_file("o", "r", "a?b.md")


async def test_evaluate_ref_attaches_manifest(monkeypatch):
    from server.services import discovery_service, github_eval, mcp_suggest

    async def fake_repo(o, r):
        return {"full_name": "o/r", "html_url": "u", "stars": 1, "forks": 0,
                "license": None, "pushed_days": 1, "description": "", "topics": []}

    async def fake_readme(o, r):
        return ""

    async def fake_suggest(meta, readme):
        return {"is_mcp": False}

    async def fake_file(o, r, path):
        return ('{"schema_version": 1, "name": "p", "version": "1", "mcp_servers": '
                '[{"label": "S", "transport": "stdio", "command": "npx", "args": []}]}')

    monkeypatch.setattr(github_eval, "fetch_repo", fake_repo)
    monkeypatch.setattr(github_eval, "fetch_readme", fake_readme)
    monkeypatch.setattr(github_eval, "fetch_file", fake_file)
    monkeypatch.setattr(mcp_suggest, "classify_and_suggest", fake_suggest)

    out = await discovery_service.evaluate_ref("o", "r")
    assert out["manifest"]["name"] == "p"
    assert "manifest_error" not in out


async def test_evaluate_ref_broken_manifest_does_not_block(monkeypatch):
    from server.services import discovery_service, github_eval, mcp_suggest

    async def fake_repo(o, r):
        return {"full_name": "o/r", "html_url": "u", "stars": 1, "forks": 0,
                "license": None, "pushed_days": 1, "description": "", "topics": []}

    async def fake_readme(o, r):
        return ""

    async def fake_suggest(meta, readme):
        return {"is_mcp": True, "transport": "stdio", "command": "npx", "args": []}

    async def fake_file(o, r, path):
        return '{"schema_version": 99}'

    monkeypatch.setattr(github_eval, "fetch_repo", fake_repo)
    monkeypatch.setattr(github_eval, "fetch_readme", fake_readme)
    monkeypatch.setattr(github_eval, "fetch_file", fake_file)
    monkeypatch.setattr(mcp_suggest, "classify_and_suggest", fake_suggest)

    out = await discovery_service.evaluate_ref("o", "r")
    assert "manifest" not in out
    assert "schema_version" in out["manifest_error"]
    assert out["suggestion"]["is_mcp"] is True          # the guess path still delivered


async def test_evaluate_ref_no_manifest_no_fields(monkeypatch):
    from server.services import discovery_service, github_eval, mcp_suggest

    async def fake_repo(o, r):
        return {"full_name": "o/r", "html_url": "u", "stars": 1, "forks": 0,
                "license": None, "pushed_days": 1, "description": "", "topics": []}

    async def fake_readme(o, r):
        return ""

    async def fake_suggest(meta, readme):
        return {"is_mcp": False}

    async def fake_file(o, r, path):
        return ""

    monkeypatch.setattr(github_eval, "fetch_repo", fake_repo)
    monkeypatch.setattr(github_eval, "fetch_readme", fake_readme)
    monkeypatch.setattr(github_eval, "fetch_file", fake_file)
    monkeypatch.setattr(mcp_suggest, "classify_and_suggest", fake_suggest)

    out = await discovery_service.evaluate_ref("o", "r")
    assert "manifest" not in out and "manifest_error" not in out
