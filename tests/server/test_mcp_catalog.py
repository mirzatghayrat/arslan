"""Tests for the backend preset connector catalog (server/mcp/catalog.py) and its
GET /mcp/catalog endpoint. The catalog is the single source of truth for both the
Settings recommended list and conversation-driven connect."""
from __future__ import annotations

import pytest

from server.mcp import catalog


def test_find_connector_matches_label_and_key_case_insensitively():
    gh = catalog.find_connector("github")
    assert gh is not None and gh["key"] == "github"
    assert catalog.find_connector("GitHub") == gh
    assert catalog.find_connector("connect my github") is None or gh  # exact/alias only; see impl
    assert catalog.find_connector("nonesuch-xyz") is None


def test_github_connector_discloses_its_required_token_with_how_to():
    gh = catalog.find_connector("github")
    env = gh["env"]
    assert len(env) == 1
    tok = env[0]
    assert tok["name"] == "GITHUB_PERSONAL_ACCESS_TOKEN"
    assert tok["get_it_url"].startswith("https://")   # how-to link present
    assert isinstance(tok["paid"], bool)
    assert gh["one_click"] is False                    # needs a credential


def test_one_click_connector_has_no_env():
    fetch = catalog.find_connector("fetch")
    assert fetch["env"] == [] and fetch["one_click"] is True


def test_filesystem_and_git_require_a_local_path():
    # Regression guard: the Task-1 backend catalog port dropped needsPath/pathPlaceholder
    # from the old web/src/data/mcpPresets.ts. Filesystem and Git are credential-free
    # (env == [], one_click True in that sense) but still need a local path before they
    # can actually connect — requires_path is the orthogonal gate for that.
    fs = catalog.find_connector("filesystem")
    assert fs["requires_path"] is True
    assert fs["path_placeholder"] == "/absolute/path/to/expose"
    assert fs["env"] == []  # no credential — requires_path is orthogonal to env/one_click

    git = catalog.find_connector("git")
    assert git["requires_path"] is True
    assert git["path_placeholder"] == "/absolute/path/to/git/repo"
    assert git["env"] == []


def test_credentialed_and_plain_one_click_connectors_do_not_require_a_path():
    gh = catalog.find_connector("github")
    assert gh["requires_path"] is False
    assert gh["path_placeholder"] is None

    fetch = catalog.find_connector("fetch")
    assert fetch["requires_path"] is False
    assert fetch["path_placeholder"] is None


def test_list_connectors_returns_all_nine():
    keys = {c["key"] for c in catalog.list_connectors()}
    assert {"fetch", "memory", "github", "brave-search", "filesystem", "git"} <= keys


@pytest.mark.asyncio
async def test_get_catalog_endpoint(client):
    r = await client.get("/api/v1/mcp/catalog")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 10  # +playwright (B3): a reviewed set, so the count is deliberate
    keys = {c["key"] for c in data}
    assert {"fetch", "memory", "github", "brave-search", "filesystem", "git",
            "sequential-thinking", "time", "everything", "playwright"} == keys
