"""0.1.57 P4: what Arslan installed — dossiers, folders, updates, removal (CAP1a removed the page's
search, install and "found for later" rail)."""
from datetime import datetime

import httpx

from server.services import capability_dossier as cd
from server.services import capability_flow, capability_install

CAND = {"id": "registry:io.github.haris-musa/excel-mcp-server@1.1.2", "kind": "mcp", "name": "excel-mcp-server",
        "summary": "Reads and writes .xlsx", "source": "registry", "source_url": "https://github.com/haris-musa/excel-mcp-server",
        "repo": "haris-musa/excel-mcp-server", "version": "1.1.2", "runtime": "uv",
        "package": {"registry_type": "pypi", "identifier": "excel-mcp-server", "version": "1.1.2",
                    "arguments": [{"type": "positional", "value": "stdio"},
                                  {"type": "named", "name": "--allow-dir", "format": "filepath"}]},
        "remote": None, "not_here": None, "path": None, "stars": 4216, "pushed_days": 10,
        "needs": {"keys": [], "network": None},
        "license": {"spdx": "MIT", "read_from": "github:LICENSE", "verdict": "usable"}}


# ── an installed capability ──────────────────────────────────────────────────

async def _installed(execution_db, tmp_path, monkeypatch):
    from server import config
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path / "data")
    (tmp_path / "data").mkdir()

    async def mit(repo, version=None):
        return "MIT", "LICENSE"

    async def lock(root, identifier, version):                 # CAP4a-2: the lock before the card
        (root / "requirements.lock").write_text("x")
        return {"file": "requirements.lock", "sha256": __import__("hashlib").sha256(b"x").hexdigest(), "packages": []}

    async def pypi(root, identifier, prepared_lock):
        return {"command": str(root / "venv/bin/excel-mcp-server"), "args": [], "lock_sha256": "a" * 64}
    monkeypatch.setattr(capability_install, "source_license", mit)
    monkeypatch.setattr(capability_install, "lock_pypi", lock)
    monkeypatch.setattr(capability_install, "install_pypi", pypi)
    old = tmp_path / "Old"
    old.mkdir()
    return await capability_install.install(CAND, folders=[str(old)])


async def test_changing_folders_updates_the_sandbox_and_the_folder_argument(execution_db, monkeypatch, tmp_path):
    from server.db.models import MCPServer
    from server.mcp.supervisor import supervisor
    scheduled = []
    monkeypatch.setattr(supervisor, "schedule", lambda sid, **kw: scheduled.append((sid, kw)))
    row = await _installed(execution_db, tmp_path, monkeypatch)
    new = tmp_path / "New"
    new.mkdir()
    out = await cd.set_folders(row.id, [str(new)])
    assert scheduled == [(row.mcp_server_id, {"fresh": True, "cold": True})]     # cold: final review fix C
    assert out["grants"]["folders"] == [str(new.resolve())]
    async with execution_db() as db:
        server = await db.get(MCPServer, row.mcp_server_id)
    assert server.args == ["stdio", "--allow-dir", str(new.resolve())]
    assert server.sandbox["folders"] == [str(new.resolve())]
    await cd.set_folders(row.id, [])
    async with execution_db() as db:
        assert (await db.get(MCPServer, row.mcp_server_id)).args == ["stdio"]


async def test_update_installs_beside_and_removes_the_old_only_when_the_new_one_passes(execution_db, monkeypatch, tmp_path):
    row = await _installed(execution_db, tmp_path, monkeypatch)

    async def latest(sid):
        return {"current": "1.1.2", "latest": "1.2.0", "newer": True,
                "candidate": {**CAND, "id": "registry:io.github.haris-musa/excel-mcp-server@1.2.0", "version": "1.2.0"}}
    monkeypatch.setattr(cd, "check_update", latest)
    removed, folders_seen = [], []

    async def remove(sid):
        removed.append(sid)
    monkeypatch.setattr(capability_install, "remove", remove)

    async def failing(c, *, folders, keys):
        folders_seen.append(folders)
        return {"state": "failed", "stage": "test", "detail": "x"}
    monkeypatch.setattr(capability_flow, "install_mcp", failing)
    out = await cd.update(row.id)
    assert out["state"] == "failed" and removed == []                          # the old one stays on
    assert folders_seen == [row.grants["folders"]]                             # same folders as before

    async def passing(c, *, folders, keys):
        return {"state": "on", "source_id": "new", "tools": ["a"]}
    monkeypatch.setattr(capability_flow, "install_mcp", passing)
    out = await cd.update(row.id)
    assert out["state"] == "on" and removed == [row.id]


async def test_check_update_compares_with_the_registry(execution_db, monkeypatch, tmp_path):
    row = await _installed(execution_db, tmp_path, monkeypatch)
    real = httpx.AsyncClient

    def handler(request):
        assert "io.github.haris-musa" in str(request.url) and str(request.url).endswith("/versions/latest")
        return httpx.Response(200, json={"server": {"name": "io.github.haris-musa/excel-mcp-server", "version": "1.10.0",
                                                    "repository": {"url": "https://github.com/haris-musa/excel-mcp-server"},
                                                    "packages": [{"registryType": "pypi", "identifier": "excel-mcp-server",
                                                                  "version": "1.10.0", "transport": {"type": "stdio"}}]}})

    class Client(real):
        def __init__(self, *a, **kw):
            kw.setdefault("transport", httpx.MockTransport(handler))
            super().__init__(*a, **kw)
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    out = await cd.check_update(row.id)
    assert out["newer"] is True and out["latest"] == "1.10.0" and out["current"] == "1.1.2"
    assert out["compare_url"] == "https://github.com/haris-musa/excel-mcp-server/compare/v1.1.2...v1.10.0"
    # The registry lists an older version than the one installed: nothing to update.
    from server.db.models import CapabilitySource
    async with execution_db() as db:
        (await db.get(CapabilitySource, row.id)).version = "1.11.0"
        await db.commit()
    out = await cd.check_update(row.id)
    assert out["newer"] is False and out["candidate"] is None


async def test_removing_a_skill_moves_its_files_to_the_trash(execution_db, monkeypatch, tmp_path):
    from pathlib import Path

    from server import config
    from server.db.models import CapabilitySource, SkillPack
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    (tmp_path / "skill_scripts" / "csv-tidy").mkdir(parents=True)
    async with execution_db() as db:
        db.add(SkillPack(key="csv-tidy", name="c", category="imported", description="d", tier="safe",
                         status="registered", body="x", source_id="sk1"))    # as capability_flow installs it
        db.add(CapabilitySource(id="sk1", kind="skill", name="c", candidate_id="c", needs={}, grants={},
                                state="installed", skill_key="csv-tidy", created_at=datetime.utcnow()))
        await db.commit()
    await cd.remove("sk1")
    async with execution_db() as db:
        assert await db.get(SkillPack, "csv-tidy") is None
        assert (await db.get(CapabilitySource, "sk1")).state == "removed"
    assert not (tmp_path / "skill_scripts" / "csv-tidy").exists()
    assert (tmp_path / "home" / ".Trash" / "Arslan capability csv-tidy").is_dir()

