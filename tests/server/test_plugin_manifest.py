"""arslan.plugin.json — the third-party packaging contract (spec 2026-08-18, Part B).

The manifest is DATA: it declares launch config, secret SLOTS (never values),
skill paths and an expose suggestion. Landing still goes through the locked
add_server / create_skill choke points, so validation here is about honesty
and containment, not about execution: https-only urls, env names that look
like env names, repo-relative skill paths with no traversal, bounded lists.
Conservative like mcp_suggest: anything off-shape → (None, error), never a
partial pass-through.
"""
from server.services import plugin_manifest


def _valid() -> dict:
    return {
        "schema_version": 1,
        "name": "playwright-pack",
        "version": "0.1.0",
        "description": "Browser automation",
        "mcp_servers": [{
            "label": "Playwright",
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@playwright/mcp@latest"],
            "env": {"SOME_KEY": {"secret": True, "description": "an api key"}},
        }],
        "skills": ["skills/browsing.SKILL.md"],
        "suggest_spawn_expose": False,
    }


def test_valid_manifest_normalizes():
    import json
    manifest, err = plugin_manifest.validate(json.dumps(_valid()))
    assert err is None
    assert manifest["name"] == "playwright-pack"
    (srv,) = manifest["mcp_servers"]
    assert srv["transport"] == "stdio" and srv["command"] == "npx"
    assert srv["env"]["SOME_KEY"]["secret"] is True
    assert manifest["skills"] == ["skills/browsing.SKILL.md"]


def test_not_json_or_not_object_rejected():
    for raw in ("not json", "[1,2]", '"str"'):
        manifest, err = plugin_manifest.validate(raw)
        assert manifest is None and err


def test_wrong_schema_version_rejected():
    import json
    bad = _valid() | {"schema_version": 2}
    manifest, err = plugin_manifest.validate(json.dumps(bad))
    assert manifest is None and "schema_version" in err


def test_stdio_requires_command_http_requires_https_url():
    import json
    no_cmd = _valid()
    no_cmd["mcp_servers"][0] = {"label": "x", "transport": "stdio", "command": ""}
    assert plugin_manifest.validate(json.dumps(no_cmd))[0] is None

    plain_http = _valid()
    plain_http["mcp_servers"][0] = {"label": "x", "transport": "http",
                                    "url": "http://mcp.example/mcp"}
    manifest, err = plugin_manifest.validate(json.dumps(plain_http))
    assert manifest is None and "https" in err          # https-only, same doctrine as open_external

    https_ok = _valid()
    https_ok["mcp_servers"][0] = {"label": "x", "transport": "http",
                                  "url": "https://mcp.example/mcp"}
    assert plugin_manifest.validate(json.dumps(https_ok))[1] is None


def test_skill_path_traversal_rejected():
    import json
    for path in ("../secrets.md", "/etc/passwd.md", "a/../../b.md", "skills/x?raw=1.md"):
        bad = _valid() | {"skills": [path]}
        manifest, err = plugin_manifest.validate(json.dumps(bad))
        assert manifest is None, path
        assert "path" in err.lower(), path


def test_env_slots_must_declare_shape_never_values():
    import json
    bad = _valid()
    bad["mcp_servers"][0]["env"] = {"KEY": "sk-live-value"}   # a VALUE, not a slot
    manifest, err = plugin_manifest.validate(json.dumps(bad))
    assert manifest is None and "env" in err.lower()

    weird_name = _valid()
    weird_name["mcp_servers"][0]["env"] = {"not a name!": {"secret": True, "description": "d"}}
    assert plugin_manifest.validate(json.dumps(weird_name))[0] is None


def test_bounded_lists():
    import json
    too_many = _valid() | {"skills": [f"s{i}.md" for i in range(plugin_manifest.MAX_SKILLS + 1)]}
    assert plugin_manifest.validate(json.dumps(too_many))[0] is None


def test_unknown_top_level_keys_are_ignored_forward_compat():
    import json
    extra = _valid() | {"future_field": {"x": 1}}
    manifest, err = plugin_manifest.validate(json.dumps(extra))
    assert err is None and "future_field" not in manifest
