"""PC-5: per-skill health check — storage integrity + script runnability + references.

`skill_health(key, body)` is deterministic and HONEST: it never reports a script
"runnable" when the sandbox backend is unavailable on this host, and never reports
storage "ok" when a body-declared bundled file is missing on disk. It PROBES sandbox
availability (cheap, read-only) — it never executes skill code.

Mirrors the PB-4 MCP health endpoint shape: POST /registry/skills/{key}/health,
require_auth, bounded timeout, structured report.
"""
from __future__ import annotations

import importlib

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, SkillPack
from server.registry import service
from server.services import code_sandbox

# ── Part A: skill_health service helper (direct unit tests) ───────────────────────────

_SCRIPTS_SECTION = "\n\n## Bundled scripts\n- `{key}/{f}`\n"
_REFS_SECTION = "\n\n## Bundled references\n- `references/{f}`\n"


def test_text_only_skill_storage_ok_no_scripts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    h = service.skill_health("plain", "## Method\njust prose, body-only")
    assert h["key"] == "plain"
    assert h["status"] == "ok"
    assert h["ok"] is True
    assert h["storage"]["ok"] is True
    assert h["storage"]["body_present"] is True
    assert h["scripts"] == []
    assert h["references"] == []
    assert h["compatibility"] == "text"


def test_empty_body_flags_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    h = service.skill_health("blank", "   ")
    assert h["storage"]["body_present"] is False
    assert h["ok"] is False
    assert h["status"] == "degraded"


def test_present_py_script_runnable_when_backend_available(tmp_path, monkeypatch):
    """On a host WITH a real sandbox backend, a clean .py entry reports runnable.

    We assert against what the probe truly returns on THIS host — no faking. When the
    backend is unavailable the same script must honestly report blocked (asserted below)."""
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    d = tmp_path / "skill_scripts" / "runner"
    d.mkdir(parents=True)
    (d / "entry.py").write_text("print('hi')", encoding="utf-8")
    body = "## Method\nrun it" + _SCRIPTS_SECTION.format(key="runner", f="entry.py")
    h = service.skill_health("runner", body)

    assert h["storage"]["ok"] is True
    assert h["storage"]["missing"] == []
    sc = {s["name"]: s for s in h["scripts"]}
    assert set(sc) == {"entry.py"}
    if code_sandbox.backend_available():
        assert sc["entry.py"]["runnable"] is True
        assert h["sandbox_available"] is True
        assert h["status"] == "ok"
        assert h["compatibility"] == "full"
    else:
        # Honesty: no backend on this host → blocked, never a false "runnable".
        assert sc["entry.py"]["runnable"] is False
        assert "sandbox" in sc["entry.py"]["reason"].lower()
        assert h["status"] == "degraded"


def test_sandbox_unavailable_blocks_runnable_honestly(tmp_path, monkeypatch):
    """When the backend probe reports unavailable, a perfectly clean .py must NOT be
    called runnable — the honest verdict is 'sandbox unavailable'."""
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(code_sandbox, "backend_available", lambda: False)
    monkeypatch.setattr(code_sandbox, "backend_name", lambda: "null")
    d = tmp_path / "skill_scripts" / "runner"
    d.mkdir(parents=True)
    (d / "entry.py").write_text("print('hi')", encoding="utf-8")
    body = "## Method\nrun it" + _SCRIPTS_SECTION.format(key="runner", f="entry.py")
    h = service.skill_health("runner", body)

    sc = {s["name"]: s for s in h["scripts"]}
    assert sc["entry.py"]["runnable"] is False
    assert "sandbox" in sc["entry.py"]["reason"].lower()
    assert h["sandbox_available"] is False
    assert h["status"] == "degraded"
    assert h["ok"] is False


def test_declared_script_missing_on_disk_flags_orphan(tmp_path, monkeypatch):
    """Body claims a bundled script that is NOT on disk → storage flags it missing,
    storage.ok is False, and the overall roll-up is degraded."""
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    (tmp_path / "skill_scripts" / "claims").mkdir(parents=True)   # dir exists, file absent
    body = "## Method\nx" + _SCRIPTS_SECTION.format(key="claims", f="ghost.py")
    h = service.skill_health("claims", body)

    assert "ghost.py" in h["storage"]["missing"]
    assert h["storage"]["ok"] is False
    assert h["ok"] is False
    assert h["status"] == "degraded"


def test_disk_script_not_in_body_is_orphaned_info(tmp_path, monkeypatch):
    """A .py on disk the body never declares is reported as orphaned (informational),
    but present-and-runnable scripts don't make storage 'not ok' on their own."""
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    d = tmp_path / "skill_scripts" / "extra"
    d.mkdir(parents=True)
    (d / "entry.py").write_text("print('x')", encoding="utf-8")
    # body declares nothing
    h = service.skill_health("extra", "## Method\nprose only")
    assert "entry.py" in h["storage"]["orphaned"]
    # missing is empty → storage.ok stays True (orphans are info, not integrity failure)
    assert h["storage"]["missing"] == []
    assert h["storage"]["ok"] is True


def test_requires_network_script_blocked_with_reason(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    d = tmp_path / "skill_scripts" / "netskill"
    d.mkdir(parents=True)
    (d / "entry.py").write_text("# requires: network\nprint('x')", encoding="utf-8")
    body = "## Method\nx" + _SCRIPTS_SECTION.format(key="netskill", f="entry.py")
    h = service.skill_health("netskill", body)

    sc = {s["name"]: s for s in h["scripts"]}
    assert sc["entry.py"]["runnable"] is False
    assert "网络" in sc["entry.py"]["reason"] or "requires" in sc["entry.py"]["reason"].lower()
    assert h["status"] == "degraded"
    assert h["compatibility"] == "partial"


def test_non_utf8_script_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    d = tmp_path / "skill_scripts" / "binary"
    d.mkdir(parents=True)
    (d / "entry.py").write_bytes(b"\xff\xfe\x00bad")
    body = "## Method\nx" + _SCRIPTS_SECTION.format(key="binary", f="entry.py")
    h = service.skill_health("binary", body)
    sc = {s["name"]: s for s in h["scripts"]}
    assert sc["entry.py"]["runnable"] is False
    assert "utf" in sc["entry.py"]["reason"].lower() or "解码" in sc["entry.py"]["reason"]


def test_non_py_script_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    d = tmp_path / "skill_scripts" / "mixed"
    d.mkdir(parents=True)
    (d / "run.sh").write_text("echo hi", encoding="utf-8")
    h = service.skill_health("mixed", "## Method\nx")
    sc = {s["name"]: s for s in h["scripts"]}
    assert sc["run.sh"]["runnable"] is False
    assert ".py" in sc["run.sh"]["reason"]


def test_references_present_and_readable(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    refs = tmp_path / "skill_scripts" / "docskill" / "references"
    refs.mkdir(parents=True)
    (refs / "guide.md").write_text("# guide", encoding="utf-8")
    body = "## Method\nread it" + _REFS_SECTION.format(f="guide.md")
    h = service.skill_health("docskill", body)

    rf = {r["name"]: r for r in h["references"]}
    assert rf["guide.md"]["readable"] is True
    assert h["storage"]["missing"] == []
    # references-only (no scripts) → compatibility partial, but references readable ⇒ not degraded
    assert h["compatibility"] == "partial"
    assert h["status"] == "ok"


def test_declared_reference_missing_flags_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    (tmp_path / "skill_scripts" / "docskill" / "references").mkdir(parents=True)
    body = "## Method\nx" + _REFS_SECTION.format(f="absent.md")
    h = service.skill_health("docskill", body)
    assert "references/absent.md" in h["storage"]["missing"]
    assert h["storage"]["ok"] is False
    assert h["status"] == "degraded"


# ── Part B: POST /registry/skills/{key}/health endpoint ───────────────────────────────


@pytest_asyncio.fixture
async def health_client(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_API_TOKEN", "test-token")
    monkeypatch.setenv("ARSLAN_DB_PATH", str(tmp_path / "sh.db"))
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))

    import server.config as config
    importlib.reload(config)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'sh.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    # Seed one runnable-script skill on disk.
    d = tmp_path / "skill_scripts" / "runner"
    d.mkdir(parents=True)
    (d / "entry.py").write_text("print('hi')", encoding="utf-8")
    async with maker() as s:
        s.add(SkillPack(key="runner", name="Runner", category="x", description="d",
                        tier="safe", status="registered",
                        body="## Method\nrun\n\n## Bundled scripts\n- `runner/entry.py`\n"))
        await s.commit()

    from server.main import create_app
    from server.db.session import get_session

    async def _override_get_session():
        async with maker() as s:
            yield s

    app = create_app()
    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await engine.dispose()
    # Restore a clean global config so the reloaded test-token never leaks into a later
    # suite that doesn't reload config (monkeypatch reverts env AFTER this teardown, so we
    # clear + reload here explicitly). Mirrors the isolation other config-reloading fixtures rely on.
    monkeypatch.setenv("ARSLAN_API_TOKEN", "")
    importlib.reload(config)


AUTH = {"Authorization": "Bearer test-token"}


async def test_health_endpoint_requires_auth(health_client):
    r = await health_client.post("/api/v1/registry/skills/runner/health")
    assert r.status_code in (401, 403)


async def test_health_endpoint_unknown_key_404(health_client):
    r = await health_client.post("/api/v1/registry/skills/nope/health", headers=AUTH)
    assert r.status_code == 404


async def test_health_endpoint_ok(health_client):
    r = await health_client.post("/api/v1/registry/skills/runner/health", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["key"] == "runner"
    assert body["storage"]["ok"] is True
    assert {s["name"] for s in body["scripts"]} == {"entry.py"}
    # On this darwin host the seatbelt backend is available → runnable. If a CI host lacks
    # it, the honest verdict flips to blocked — assert the two coherently.
    sc = {s["name"]: s for s in body["scripts"]}
    if body["sandbox_available"]:
        assert sc["entry.py"]["runnable"] is True
        assert body["status"] == "ok"
    else:
        assert sc["entry.py"]["runnable"] is False
        assert body["status"] == "degraded"
