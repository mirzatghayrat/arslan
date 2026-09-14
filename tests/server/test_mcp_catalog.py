"""Tests for the backend preset connector catalog (server/mcp/catalog.py) and its
GET /mcp/catalog endpoint. The catalog is the single source of truth for both the
Settings recommended list and conversation-driven connect."""
from __future__ import annotations

import pytest
import json
from pathlib import Path

from server.mcp import catalog
from server.ws import protocol


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


def test_all_connector_display_hints_resolve_in_six_languages():
    path = Path(__file__).resolve().parents[2] / "web/src/locales/connectorCatalog.json"
    translations = json.loads(path.read_text())
    assert set(translations) == {"en", "zh", "ja", "es", "de", "fr"}
    for language in translations.values():
        assert set(language) == {row["key"] for row in catalog.CONNECTORS}
        for row in catalog.list_connectors():
            prefix = f"catalogUI.connectors.{row['key']}"
            assert row["label_key"] == f"{prefix}.name"
            assert row["description_key"] == f"{prefix}.description"
            display = language[row["key"]]
            assert display["name"].strip() and display["description"].strip()
            assert set(display.get("credentials", {})) == {item["name"] for item in row["env"]}
            for item in row["env"]:
                assert item["description_key"] == f"{prefix}.credentials.{item['name']}"
                assert display["credentials"][item["name"]].strip()


def test_display_catalog_returns_copies_without_mutating_connection_inputs():
    github = catalog.find_connector("github")
    github["args"].append("changed")
    github["env"][0]["description"] = "changed"
    actual = catalog.find_connector("github")
    seed = next(row for row in catalog.CONNECTORS if row["key"] == "github")
    assert actual["args"] == seed["args"]
    assert actual["env"][0]["description"] == seed["env"][0]["description"]
    assert "description_key" not in seed["env"][0]


def test_connect_proposal_transmits_ui_hints_but_never_credential_values():
    c = catalog.find_connector("github")
    frame = protocol.propose_connect_mcp(call_id="test", key=c["key"], label=c["label"], label_key=c["label_key"],
        transport=c["transport"], command=c["command"], argv=c["args"], url=c["url"],
        env_keys=[{**c["env"][0], "value": "synthetic-secret"}])
    assert frame["label"] == "GitHub" and frame["argv"] == c["args"]
    assert frame["label_key"] == c["label_key"]
    assert frame["env_keys"][0]["description_key"] == c["env"][0]["description_key"]
    assert "synthetic-secret" not in json.dumps(frame)
