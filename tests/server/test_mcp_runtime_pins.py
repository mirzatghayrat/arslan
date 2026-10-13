"""Pinned Node/uv for bare commands, secret masking, and the unit-test spawn guard (0.1.61 §B1)."""
from pathlib import Path

import httpx
import mcp.client.stdio as stdio_mod
import pytest

from server.mcp import spawn_env
from server.services import capability_runtime as rt

# The real functions, captured at collection: before any test's guard fixture has run.
_REAL_SPAWN = stdio_mod._create_platform_compatible_process
_REAL_DOWNLOAD = rt._download
# Never executable and never resolvable: a run with no guard fails on the wrong exception type
# (FileNotFoundError / ConnectError) without having run or fetched anything.
_NO_SUCH_COMMAND = "/nonexistent/arslan-guard-probe"
_LOOPBACK_URL = "http://127.0.0.1:9/arslan-guard-probe"


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


def _printed_by_httpx(url: str) -> str:
    """The text httpx.HTTPStatusError carries for a failed request: the URL as written."""
    request = httpx.Request("GET", url)
    try:
        httpx.Response(401, request=request).raise_for_status()
    except httpx.HTTPStatusError as error:
        return str(error)
    raise AssertionError("raise_for_status did not raise")


@pytest.mark.parametrize("url, secret, masked_url", [
    ("https://mcp.example.test/mcp?key=ab+cd/ef==&x=1", "ab+cd/ef==",              # raw + / =
     "https://mcp.example.test/mcp?key=****&x=1"),
    ("https://mcp.example.test/mcp?token=abc%2fdef%2Bghij&x=1", "abc%2fdef%2Bghij",  # lower-case hex
     "https://mcp.example.test/mcp?token=****&x=1"),
    ("https://mcp.example.test/mcp?token=tok/en%2B1xyz&x=1", "tok/en%2B1xyz",      # partly encoded
     "https://mcp.example.test/mcp?token=****&x=1"),
    ("https://ghp_SECRETtoken0123@mcp.example.test/mcp", "ghp_SECRETtoken0123",      # username only
     "https://****@mcp.example.test/mcp"),
    ("https://svc:p%40ssw0rd@mcp.example.test/mcp", "p%40ssw0rd",                   # password, as written
     "https://svc:****@mcp.example.test/mcp"),
], ids=["raw-symbols", "lowercase-hex", "partly-encoded", "username-only", "password-encoded"])
def test_a_url_secret_does_not_survive_in_the_error_httpx_prints(url, secret, masked_url):
    text = _printed_by_httpx(url)
    assert secret in text                                     # the probe prints the URL as written
    masked = spawn_env.mask(text, spawn_env.secret_forms({"url": url}))
    # The whole value is replaced, not its tail: a partial hit would leave `ab+****` behind, and
    # asserting only that the full secret is gone would let that pass.
    assert f"for url '{masked_url}'" in masked


def test_a_password_is_masked_encoded_and_decoded():
    forms = spawn_env.secret_forms({"url": "https://svc:p%40ssw0rd@mcp.example.test/mcp"})
    assert "p%40ssw0rd" in forms and "p@ssw0rd" in forms      # a library may print either
    assert spawn_env.mask("auth failed for p@ssw0rd", forms) == "auth failed for ****"


def test_a_password_alone_is_a_secret():
    forms = spawn_env.secret_forms({"url": "https://svc:pw-s3cret@mcp.example.test/mcp"})
    assert "pw-s3cret" in forms
    assert "svc" not in forms                                  # under 4 characters, not a secret


def test_quote_plus_form_of_a_value_with_spaces():
    forms = spawn_env.secret_forms({"env": {"API_KEY": "my secret value"}})
    assert "my+secret+value" in forms and "my%20secret%20value" in forms
    assert spawn_env.mask("GET /x?k=my+secret+value", forms) == "GET /x?k=****"


def test_default_quote_form_keeps_slashes_unescaped():
    forms = spawn_env.secret_forms({"env": {"TOKEN": "tok/en+1xyz"}})
    assert "tok/en%2B1xyz" in forms and "tok%2Fen%2B1xyz" in forms
    assert spawn_env.mask("GET /x?t=tok/en%2B1xyz", forms) == "GET /x?t=****"


def test_mask_replaces_longest_first():
    text = "a=abcdefgh b=abcd c=tok%2Fen"
    assert spawn_env.mask(text, ["abcd", "abcdefgh", "tok%2Fen"]) == "a=**** b=**** c=****"


async def test_the_guard_refuses_a_real_spawn_and_a_real_download():
    with pytest.raises(RuntimeError, match="real MCP spawn"):
        await stdio_mod._create_platform_compatible_process(_NO_SUCH_COMMAND, [])
    with pytest.raises(RuntimeError, match="real runtime download"):
        await rt._download(_LOOPBACK_URL, Path("/nonexistent"))
    assert stdio_mod._create_platform_compatible_process is not _REAL_SPAWN
    assert rt._download is not _REAL_DOWNLOAD


@pytest.mark.filterwarnings("ignore::ResourceWarning")   # the guard's error skips stdio_client's cleanup
async def test_the_guard_is_reached_through_stdio_client_itself():
    """An SDK rename of the private spawn function must not turn the guard into a silent no-op
    while the test above stays green: go in through the public door every MCP path uses."""
    from mcp import StdioServerParameters

    with pytest.raises(RuntimeError, match="real MCP spawn"):
        async with stdio_mod.stdio_client(StdioServerParameters(command=_NO_SUCH_COMMAND)):
            pytest.fail("stdio_client got past the guard")


async def test_a_tests_own_monkeypatch_undo_does_not_lift_the_guard(monkeypatch):
    monkeypatch.setattr(rt, "root", lambda: Path("/nonexistent"))
    monkeypatch.undo()
    with pytest.raises(RuntimeError, match="real MCP spawn"):
        await stdio_mod._create_platform_compatible_process(_NO_SUCH_COMMAND, [])
    with pytest.raises(RuntimeError, match="real runtime download"):
        await rt._download(_LOOPBACK_URL, Path("/nonexistent"))


@pytest.mark.real_mcp
async def test_the_marker_lifts_the_guard_and_nothing_else():
    # Both halves are the real functions again: reaching the real spawn gets FileNotFoundError
    # from a path that does not exist (nothing runs); the real download is the very function
    # captured at collection.
    assert stdio_mod._create_platform_compatible_process is _REAL_SPAWN
    assert rt._download is _REAL_DOWNLOAD
    with pytest.raises(FileNotFoundError):
        await stdio_mod._create_platform_compatible_process(_NO_SUCH_COMMAND, [])
