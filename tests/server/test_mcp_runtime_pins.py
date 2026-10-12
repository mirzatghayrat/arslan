"""Pinned Node/uv for bare commands, secret masking, and the unit-test spawn guard (0.1.61 §B1)."""
from pathlib import Path

import pytest

from server.mcp import spawn_env
from server.services import capability_runtime as rt


@pytest.fixture
def runtimes(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "root", lambda: tmp_path / "runtimes")
    node_bin = rt.binary("node").parent
    node_bin.mkdir(parents=True)
    for name in ("node", "npm", "npx"):
        (node_bin / name).write_text("#!/bin/sh\n")
    uv_dir = rt.binary("uv").parent
    uv_dir.mkdir(parents=True)
    (uv_dir / "uv").write_text("x")
    return node_bin, uv_dir


def test_bare_node_commands_run_on_the_pinned_node(runtimes):
    node_bin, _ = runtimes
    for name in ("npx", "npm", "node"):
        assert spawn_env.pinned_command(name) == (str(node_bin / name), str(node_bin))
    assert spawn_env.pinned_command("npx")[0].endswith("bin/npx")      # never bin/node


def test_a_missing_binary_or_an_explicit_path_is_left_alone(runtimes, monkeypatch):
    _, uv_dir = runtimes
    assert spawn_env.pinned_command("uv") == (str(uv_dir / "uv"), str(uv_dir))
    assert spawn_env.pinned_command("uvx") == ("uvx", None)            # ready("uv") but no uvx
    assert spawn_env.pinned_command("/opt/x/npx") == ("/opt/x/npx", None)
    assert spawn_env.pinned_command("python3") == ("python3", None)
    monkeypatch.setattr(rt, "ready", lambda name: False)
    assert spawn_env.pinned_command("npx") == ("npx", None)


def test_runtime_for_names_the_runtime_of_a_bare_command():
    assert [spawn_env.runtime_for(c) for c in ("npx", "npm", "node", "uvx", "uv")] == \
        ["node", "node", "node", "uv", "uv"]
    assert spawn_env.runtime_for("/usr/local/bin/npx") is None
    assert spawn_env.runtime_for("python3") is None


def test_secret_forms_cover_headers_url_queries_and_encodings():
    server = {"env": {"Authorization": "Bearer tok/en+1==", "DEBUG": "true", "PIN": "123"},
              "url": "https://mcp.example.test/mcp?api_key=k3y-v@lue&mode=fast"}
    forms = spawn_env.secret_forms(server)
    assert forms == sorted(forms, key=len, reverse=True)
    for expected in ("Bearer tok/en+1==", "tok/en+1==", "tok%2Fen%2B1%3D%3D", "k3y-v@lue",
                     "k3y-v%40lue", "fast"):
        assert expected in forms
    assert "true" not in forms and "123" not in forms


def test_mask_replaces_longest_first():
    text = "a=abcdefgh b=abcd c=tok%2Fen"
    assert spawn_env.mask(text, ["abcd", "abcdefgh", "tok%2Fen"]) == "a=**** b=**** c=****"


async def test_the_guard_refuses_a_real_spawn_and_a_real_download():
    import mcp.client.stdio as stdio_mod
    with pytest.raises(RuntimeError, match="real MCP spawn"):
        await stdio_mod._create_platform_compatible_process("true", [])
    with pytest.raises(RuntimeError, match="real runtime download"):
        await rt._download("https://example.invalid/x", Path("/nonexistent"))


@pytest.mark.real_mcp
def test_the_marker_lifts_the_guard_and_nothing_else():
    import mcp.client.stdio as stdio_mod
    assert stdio_mod._create_platform_compatible_process.__name__ == "_create_platform_compatible_process"
