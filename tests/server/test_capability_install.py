"""0.1.57 P2: installing a capability — pinned runtimes, pinned packages, switched off, sandboxed."""
import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from server.services import capability_install as ci
from server.services import capability_runtime as rt

PKG = {"registry_type": "pypi", "identifier": "excel-mcp-server", "version": "1.1.2", "file_sha256": None,
       "transport": "stdio", "arguments": [{"type": "positional", "value": "stdio"},
                                           {"type": "named", "name": "--allow-dir", "format": "filepath"}]}
CAND = {"id": "registry:io.github.haris-musa/excel-mcp-server@1.1.2", "kind": "mcp", "name": "excel-mcp-server",
        "summary": "Excel", "source": "registry", "source_url": "https://github.com/haris-musa/excel-mcp-server",
        "repo": "haris-musa/excel-mcp-server", "version": "1.1.2", "runtime": "uv", "package": PKG, "remote": None,
        "not_here": None, "needs": {"keys": [], "network": None}, "stars": 4216, "pushed_days": 10,
        "license": {"spdx": "MIT", "read_from": "github:LICENSE", "verdict": "usable"}}


@pytest.fixture
def data(monkeypatch, tmp_path):
    from server import config
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path / "data")
    (tmp_path / "data").mkdir()
    return tmp_path / "data"


# ── runtimes ─────────────────────────────────────────────────────────────────

def _archive(members: dict[str, bytes], *, link=None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(content))
        if link:
            info = tarfile.TarInfo(link[0])
            info.type, info.linkname = tarfile.SYMTYPE, link[1]
            tar.addfile(info)
    return buf.getvalue()


def _pin(monkeypatch, archive: bytes, *, sha=None):
    pin = rt.Pin("uv", "9.9.9", "https://example.invalid/uv.tar.gz", sha or hashlib.sha256(archive).hexdigest(), 1,
                 "uv-aarch64-apple-darwin", ("uv",))
    monkeypatch.setitem(rt.PINS, "uv", pin)
    monkeypatch.setattr(rt, "available", lambda: True)
    calls = []

    async def download(url, out):
        calls.append(url)
        out.write_bytes(archive)
        return hashlib.sha256(archive).hexdigest()
    monkeypatch.setattr(rt, "_download", download)
    return calls


async def test_a_runtime_is_downloaded_once_and_verified_against_its_pin(data, monkeypatch):
    calls = _pin(monkeypatch, _archive({"uv-aarch64-apple-darwin/uv": b"#!/bin/sh\n"}))
    path = await rt.ensure("uv")
    assert path == data / "runtimes" / "uv-9.9.9" / "uv-aarch64-apple-darwin" / "uv" and path.is_file()
    assert await rt.ensure("uv") == path and len(calls) == 1          # ready: no second download
    assert not list((data / "runtimes").glob(".*part"))


async def test_a_checksum_mismatch_installs_nothing(data, monkeypatch):
    _pin(monkeypatch, _archive({"uv-aarch64-apple-darwin/uv": b"x"}), sha="0" * 64)
    with pytest.raises(rt.RuntimeFailure, match="checksum_mismatch"):
        await rt.ensure("uv")
    assert not rt.ready("uv") and not (data / "runtimes" / "uv-9.9.9").exists()


async def test_an_archive_that_escapes_its_folder_is_refused(data, monkeypatch):
    _pin(monkeypatch, _archive({"uv-aarch64-apple-darwin/uv": b"x"}, link=("uv-aarch64-apple-darwin/evil", "/etc/passwd")))
    with pytest.raises(rt.RuntimeFailure, match="archive_escapes"):
        await rt.ensure("uv")


async def test_an_archive_member_named_out_of_its_folder_is_refused(data, monkeypatch):
    _pin(monkeypatch, _archive({"uv-aarch64-apple-darwin/uv": b"x", "../escaped": b"y"}))
    with pytest.raises(rt.RuntimeFailure, match="archive_escapes"):
        await rt.ensure("uv")
    assert not (data / "escaped").exists()


async def test_not_on_apple_silicon_says_so(monkeypatch):
    monkeypatch.setattr(rt, "available", lambda: False)
    with pytest.raises(rt.RuntimeFailure, match="unsupported_platform"):
        await rt.ensure("uv")


def test_the_pins_are_complete():
    for pin in rt.PINS.values():
        assert pin.url.startswith("https://") and len(pin.sha256) == 64 and pin.version in pin.url


# ── what an install takes from the candidate ─────────────────────────────────

def test_start_arguments_fill_the_folder_and_keep_fixed_values(tmp_path):
    assert ci.start_arguments(PKG, ["/g"]) == ["stdio", "--allow-dir", "/g"]
    assert ci.start_arguments(PKG, []) == ["stdio"]                  # optional folder left out
    with pytest.raises(ci.InstallFailure, match="needs_argument"):
        ci.start_arguments({"arguments": [{"type": "named", "name": "--token", "isRequired": True}]}, [])


@pytest.mark.parametrize("cand, code", [
    ({**CAND, "kind": "skill"}, "not_an_mcp_server"),
    ({**CAND, "not_here": "needs_dotnet"}, "not_here"),
    ({**CAND, "runtime": None}, "no_runtime"),
    ({**CAND, "package": {**PKG, "identifier": "x; rm -rf /"}}, "bad_package"),
    ({**CAND, "package": {**PKG, "version": "1.0 && curl"}}, "bad_package"),
    ({**CAND, "runtime": "mcpb", "package": {"identifier": "http://plain/x.mcpb"}}, "bad_package"),
])
def test_a_candidate_that_cannot_be_installed_is_refused(cand, code):
    with pytest.raises(ci.InstallFailure, match=code):
        ci._check_candidate(cand)


def test_grants_are_real_existing_folders_and_network_follows_secret_keys(tmp_path):
    (tmp_path / "a").mkdir()
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "a")
    g = ci.grants_for([str(tmp_path / "a"), str(link), str(tmp_path / "missing"), "/"], {"keys": [], "network": None})
    assert g == {"folders": [str((tmp_path / "a").resolve())], "network": False}
    assert ci.grants_for([], {"keys": [{"name": "API_KEY", "secret": True}], "network": None})["network"] is True


def test_the_console_script_is_found_in_a_real_dist_info_layout(tmp_path):
    """Measured on excel-mcp-server 1.1.2: `excel_mcp_server-1.1.2.dist-info` — the "-" in
    "dist-info" is the last one, which once made the package name unmatchable."""
    site = tmp_path / "venv" / "lib" / "python3.12" / "site-packages"
    for dist, scripts in (("excel_mcp_server-1.1.2", "excel-mcp-server = excel_mcp.cli:main\n"),
                          ("uvicorn-0.54.0", "uvicorn = uvicorn.main:main\n")):
        (site / f"{dist}.dist-info").mkdir(parents=True)
        (site / f"{dist}.dist-info" / "entry_points.txt").write_text(f"[console_scripts]\n{scripts}")
    assert ci._console_script(tmp_path / "venv", "excel-mcp-server") == "excel-mcp-server"
    with pytest.raises(ci.InstallFailure, match="no_command"):
        ci._console_script(tmp_path / "venv", "not-installed")
    # Several scripts and none named like the package: which one is the server is unknown.
    (site / "two-1.0.dist-info").mkdir()
    (site / "two-1.0.dist-info" / "entry_points.txt").write_text("[console_scripts]\na = x:a\nb = x:b\n")
    with pytest.raises(ci.InstallFailure, match="no_command"):
        ci._console_script(tmp_path / "venv", "two")


# ── the install ──────────────────────────────────────────────────────────────

async def _fake_pypi(root: Path, identifier: str, version: str) -> dict:
    (root / "requirements.lock").write_text(f"{identifier}=={version} --hash=sha256:abc\n")
    return {"command": str(root / "venv" / "bin" / identifier), "args": [], "lock_sha256": "f" * 64}


async def test_an_install_is_pinned_switched_off_and_sandboxed(execution_db, data, monkeypatch, tmp_path):
    from server.db.models import CapabilitySource, MCPServer
    grant = tmp_path / "Downloads"
    grant.mkdir()

    async def mit(repo):
        return "MIT", "LICENSE"
    monkeypatch.setattr(ci, "source_license", mit)
    monkeypatch.setattr(ci, "install_pypi", _fake_pypi)
    row = await ci.install(CAND, folders=[str(grant)])
    assert row.state == "installed" and row.version == "1.1.2" and row.lock_sha256 == "f" * 64
    assert row.license_spdx == "MIT" and row.license_path == "LICENSE"
    async with execution_db() as db:
        server = await db.get(MCPServer, row.mcp_server_id)
        saved = await db.get(CapabilitySource, row.id)
    assert server.host_allowed is False                      # the first test decides (P3)
    assert server.args == ["stdio", "--allow-dir", str(grant.resolve())]
    assert server.sandbox == {"root": str(data / "capabilities" / row.id), "folders": [str(grant.resolve())],
                              "network": False, "read": [str(data / "runtimes")]}
    assert saved.grants == {"folders": [str(grant.resolve())], "network": False}
    from server.mcp.discovery import runtime_dict
    assert runtime_dict(server)["sandbox"] == server.sandbox          # what the launch reads


async def test_a_license_that_is_not_usable_stops_before_any_download(execution_db, data, monkeypatch):
    downloads = []

    async def gpl(repo):
        return None, "LICENSE"                                 # a file that is not a permissive license
    monkeypatch.setattr(ci, "source_license", gpl)

    async def never(*a, **k):
        downloads.append(a)
    monkeypatch.setattr(ci, "install_pypi", never)
    with pytest.raises(ci.InstallFailure, match="license"):
        await ci.install(CAND, folders=[])
    assert downloads == [] and not (data / "capabilities").exists()


async def test_a_failed_step_is_recorded_and_leaves_nothing_behind(execution_db, data, monkeypatch):
    from sqlalchemy import select

    from server.db.models import CapabilitySource, MCPServer

    async def mit(repo):
        return "MIT", "LICENSE"

    async def broken(root, identifier, version):
        raise ci.InstallFailure("step_failed", "uv pip compile: no wheel for excel-mcp-server")
    monkeypatch.setattr(ci, "source_license", mit)
    monkeypatch.setattr(ci, "install_pypi", broken)
    with pytest.raises(ci.InstallFailure):
        await ci.install(CAND, folders=[])
    async with execution_db() as db:
        rows = (await db.execute(select(CapabilitySource))).scalars().all()
        servers = (await db.execute(select(MCPServer))).scalars().all()
    assert [(r.state, r.error.split(":")[0]) for r in rows] == [("failed", "step_failed")]
    assert servers == [] and list((data / "capabilities").iterdir()) == []


async def test_a_remote_server_is_registered_without_a_sandbox_and_keeps_its_key(execution_db, data, monkeypatch):
    from server.db.models import MCPServer
    from server.mcp.discovery import runtime_dict

    async def none(repo):
        return None, None
    monkeypatch.setattr(ci, "source_license", none)
    remote = {**CAND, "runtime": "remote", "package": None, "repo": None,
              "remote": {"type": "streamable-http", "url": "https://mcp.example.com/x"},
              "needs": {"keys": [{"name": "Authorization", "secret": True, "required": True}], "network": True}}
    row = await ci.install(remote, folders=[], keys={"Authorization": "Bearer t"})
    async with execution_db() as db:
        server = runtime_dict(await db.get(MCPServer, row.mcp_server_id))
    assert server["transport"] == "http" and server["url"] == "https://mcp.example.com/x"
    assert server["sandbox"] is None and server["env"] == {"Authorization": "Bearer t"}


async def test_remove_moves_the_folder_to_the_trash(execution_db, data, monkeypatch, tmp_path):
    from server.db.models import CapabilitySource, MCPServer
    trash = tmp_path / "home" / ".Trash"
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    async def mit(repo):
        return "MIT", "LICENSE"
    monkeypatch.setattr(ci, "source_license", mit)
    monkeypatch.setattr(ci, "install_pypi", _fake_pypi)
    row = await ci.install(CAND, folders=[])
    await ci.remove(row.id)
    async with execution_db() as db:
        assert (await db.get(CapabilitySource, row.id)).state == "removed"
        assert await db.get(MCPServer, row.mcp_server_id) is None
    assert not (data / "capabilities" / row.id).exists()
    assert [p.name for p in trash.iterdir()] == [f"Arslan capability {row.id}"]


async def test_the_launch_wraps_only_installed_servers(monkeypatch):
    """session.py: a server with a sandbox starts under sandbox-exec; a hand-added one as before."""
    from server.mcp import session
    seen = []

    class Stop(Exception):
        pass

    def fake_stdio(params):
        seen.append(params)
        raise Stop
    monkeypatch.setattr("mcp.client.stdio.stdio_client", fake_stdio)
    manager = session.MCPSessionManager() if hasattr(session, "MCPSessionManager") else type(session.manager)()
    base = {"id": 1, "transport": "stdio", "command": "/bin/echo", "args": ["hi"], "url": None, "env": {}}
    for server in (base, {**base, "id": 2, "sandbox": {"root": "/tmp/arslan-cap-test", "folders": [], "network": False}}):
        with pytest.raises(Exception):
            await manager._open_session(server)
    assert seen[0].command.endswith("echo") and seen[0].cwd is None
    assert seen[1].command == "/usr/bin/sandbox-exec" and seen[1].args[2:] == ["/bin/echo", "hi"]
    assert seen[1].cwd == "/tmp/arslan-cap-test/home"


def test_no_installer_reads_search_results_and_the_catalog_stays_static():
    """The red line (test_capability_supply_chain): the installer takes one candidate the user
    answered for; it never searches."""
    import inspect
    source = Path(inspect.getfile(ci)).read_text()
    assert "capability_search" not in source and "/search/" not in source
    assert json.loads(json.dumps(CAND)) == CAND
