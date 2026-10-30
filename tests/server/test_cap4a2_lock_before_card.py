"""CAP4a-2 (v0.1.64, docs/plans/0164/CAP-capabilities.md CAP4; the user's D1, option a): the lock before the card.

Arslan's own pinned runtime (capability_runtime: version and SHA-256 in the repository, checked before use) and the
lock are ready before the card. The card shows the locked packages and the lock's digest; a yes installs from that
very lock (`--require-hashes`, `npm ci`), never resolving again, and stops if the lock changed. A no, an expired
card or nobody to ask leaves nothing behind, and nobody to ask resolves nothing. No network here: uv and npm are
fakes that record each step and write what the real ones would.
"""
import hashlib
import json
import os
import time
from pathlib import Path

import pytest

from server.db import session as db_session
from server.db.models import CapabilitySource, MCPServer
from server.services import capability_flow, capability_install, capability_runtime, capability_search, permission_store

PYPI = {"id": "registry:io.github.acme/notes@1.2.0", "kind": "mcp", "name": "notes-mcp", "summary": "Notes",
        "source": "registry", "source_url": "https://github.com/acme/notes-mcp", "repo": "acme/notes-mcp",
        "version": "1.2.0", "runtime": "uv", "remote": None, "not_here": None, "stars": 3, "pushed_days": 1,
        "package": {"registry_type": "pypi", "identifier": "notes-mcp", "version": "1.2.0", "arguments": []},
        "needs": {"keys": [], "network": None}, "license": {"spdx": "MIT", "read_from": "LICENSE", "verdict": "usable"}}
NPM = {**PYPI, "id": "registry:io.github.acme/notes-js@2.0.1", "name": "notes-js", "runtime": "node",
       "package": {"registry_type": "npm", "identifier": "@acme/notes-js", "version": "2.0.1", "arguments": []}}
LOCK = ("notes-mcp==1.2.0 \\\n    --hash=sha256:" + "a" * 64 + "\nhttpx==0.27.0 \\\n    --hash=sha256:" + "b" * 64
        + "\n    # via notes-mcp\n")


@pytest.fixture(autouse=True)
def _world(execution_db, tmp_path, monkeypatch):
    """A data folder, a license, Arslan's runtime as a path, and uv/npm as recorders."""
    permission_store._reset_for_tests()
    from server import config
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path / "data")
    (tmp_path / "data").mkdir()

    async def mit(repo, version=None):
        return "MIT", f"LICENSE@v{version}" if version else "LICENSE@HEAD"
    monkeypatch.setattr(capability_install, "source_license", mit)

    async def ensure(name):
        return tmp_path / "rt" / name / "bin" / name
    monkeypatch.setattr(capability_runtime, "ensure", ensure)
    steps: list[tuple] = []

    async def run(argv, *, cwd, env):
        step = tuple(Path(argv[0]).name if i == 0 else a for i, a in enumerate(argv[:3]))
        steps.append(step)
        if step == ("uv", "pip", "compile"):
            (cwd / "requirements.lock").write_text(LOCK)
        elif step[:2] == ("uv", "venv"):
            (cwd / "venv" / "bin").mkdir(parents=True)
        elif step == ("uv", "pip", "install"):
            dist = cwd / "venv" / "lib" / "python3.12" / "site-packages" / "notes_mcp-1.2.0.dist-info"
            dist.mkdir(parents=True)
            (dist / "entry_points.txt").write_text("[console_scripts]\nnotes-mcp = notes_mcp:main\n")
        elif step == ("npm", "install", "@acme/notes-js@2.0.1"):
            (cwd / "package-lock.json").write_text(json.dumps({"packages": {
                "": {"name": "arslan-capability"}, "node_modules/@acme/notes-js": {"version": "2.0.1"},
                "node_modules/zod": {"version": "3.23.8"}}}))
        elif step[:2] == ("npm", "ci"):
            pkg = cwd / "node_modules" / "@acme" / "notes-js"
            pkg.mkdir(parents=True)
            (pkg / "package.json").write_text(json.dumps({"bin": {"notes-js": "cli.js"}}))
            (pkg / "cli.js").write_text("")
        return ""
    monkeypatch.setattr(capability_install, "_run", run)

    async def tested(source_id):
        return {"ok": True, "tools": ["read_note"], "at": "now"}
    monkeypatch.setattr(capability_flow, "test_mcp", tested)
    monkeypatch.setattr(capability_flow.capability_scan, "scan_install", lambda root: {"level": "clean", "findings": []})
    return steps


async def _propose(monkeypatch, steps, cand, *, approve=True, during=None):
    cards, asked_after = [], []

    async def ask(card):
        cards.append(card)
        asked_after.append(list(steps))
        if during:
            during()
        from server.services import approvals
        approvals.LAST_OUTCOME.set("approved" if approve else "declined")
        return {"approved": approve, "call_id": "cap-1", "keys": {}, "folders": []}
    monkeypatch.setattr(capability_search, "seen", lambda conversation_id, candidate_id: dict(cand))
    out = await capability_flow.propose({"candidate_id": cand["id"], "why": "notes"}, conversation_id="c1", ask=ask,
                                        emit=lambda frame: None)
    return out, cards, asked_after[0] if asked_after else None


def _prepared(data: Path) -> list:
    folder = data / "capabilities" / ".prepared"
    return sorted(folder.iterdir()) if folder.is_dir() else []


async def test_a_pypi_card_shows_the_lock_and_a_yes_installs_from_it(monkeypatch, _world, tmp_path):
    """The red case before CAP4a-2: the lock was resolved after the yes, and the card had none."""
    out, [card], before_card = await _propose(monkeypatch, _world, PYPI)
    assert out["ok"], out
    assert before_card == [("uv", "pip", "compile")]                       # resolved before the card, nothing else
    assert card["lock"] == {"sha256": hashlib.sha256(LOCK.encode()).hexdigest(), "count": 2,
                            "packages": [{"name": "notes-mcp", "version": "1.2.0"}, {"name": "httpx", "version": "0.27.0"}]}
    assert card["runtime_download"] is None                                # Arslan's own runtime is ready first
    assert card["license"] == {"spdx": "MIT", "read_from": "LICENSE@v1.2.0"}  # CAP4a-3: what the gate read
    assert _world == [("uv", "pip", "compile"), ("uv", "venv", "venv"), ("uv", "pip", "install")]   # one resolve
    async with db_session.AsyncSessionLocal() as db:
        row = (await db.execute(__import__("sqlalchemy").select(CapabilitySource))).scalars().one()
    root = tmp_path / "data" / "capabilities" / row.id
    assert row.lock_sha256 == card["lock"]["sha256"] and (root / "requirements.lock").read_text() == LOCK
    assert _prepared(tmp_path / "data") == []                              # the staged lock moved in whole


async def test_an_npm_card_shows_the_lock_and_a_yes_runs_npm_ci_only(monkeypatch, _world, tmp_path):
    out, [card], before_card = await _propose(monkeypatch, _world, NPM)
    assert out["ok"], out
    assert before_card == [("npm", "install", "@acme/notes-js@2.0.1")]
    assert card["lock"]["packages"] == [{"name": "@acme/notes-js", "version": "2.0.1"}, {"name": "zod", "version": "3.23.8"}]
    assert _world == [("npm", "install", "@acme/notes-js@2.0.1"), ("npm", "ci", "--ignore-scripts")]


async def test_a_lock_changed_after_the_card_stops_the_install(monkeypatch, _world, tmp_path):
    def swap():
        [staging] = _prepared(tmp_path / "data")
        (staging / "requirements.lock").write_text(LOCK.replace("0.27.0", "6.6.6"))
    out, [card], _ = await _propose(monkeypatch, _world, PYPI, during=swap)
    assert not out["ok"] and "lock_changed" in json.dumps(out)
    assert ("uv", "pip", "install") not in _world
    async with db_session.AsyncSessionLocal() as db:
        assert (await db.execute(__import__("sqlalchemy").select(MCPServer))).scalars().all() == []
    assert [p.name for p in (tmp_path / "data" / "capabilities").iterdir()] == [".prepared"]
    assert _prepared(tmp_path / "data") == []


async def test_a_declined_card_installs_nothing_and_keeps_no_lock(monkeypatch, _world, tmp_path):
    out, [card], _ = await _propose(monkeypatch, _world, PYPI, approve=False)
    assert out.get("declined") and _world == [("uv", "pip", "compile")]
    assert _prepared(tmp_path / "data") == []
    async with db_session.AsyncSessionLocal() as db:
        assert (await db.execute(__import__("sqlalchemy").select(CapabilitySource))).scalars().all() == []


async def test_a_license_that_is_not_usable_resolves_nothing_and_shows_no_card(monkeypatch, _world):
    async def gpl(repo, version=None):
        return None, "LICENSE"
    monkeypatch.setattr(capability_install, "source_license", gpl)
    out, cards, _ = await _propose(monkeypatch, _world, PYPI)
    assert cards == [] and not out["ok"] and "license" in out["error"] and _world == []


async def test_nobody_to_ask_resolves_nothing(monkeypatch, _world):
    monkeypatch.setattr(capability_search, "seen", lambda conversation_id, candidate_id: dict(PYPI))
    out = await capability_flow.propose({"candidate_id": PYPI["id"], "why": "notes"}, conversation_id="c1", ask=None,
                                        emit=lambda frame: None)
    assert out.get("not_added") and _world == []


async def test_a_reinstall_with_no_card_prepares_first(_world, tmp_path):
    """The dossier's reinstall shows no card: install() resolves the lock itself, then installs from it."""
    row = await capability_install.install(PYPI, folders=[])
    assert row.state == "installed" and _world == [("uv", "pip", "compile"), ("uv", "venv", "venv"), ("uv", "pip", "install")]


def test_the_lock_summary_lists_at_most_forty_packages():
    lock = {"sha256": "c" * 64, "packages": [{"name": f"p{n}", "version": "1"} for n in range(55)]}
    summary = capability_install.lock_summary({"lock": lock})
    assert (summary["count"], len(summary["packages"])) == (55, 40) and capability_install.lock_summary({"lock": None}) is None


async def test_a_staging_folder_from_a_card_long_gone_is_swept(_world, tmp_path):
    old = tmp_path / "data" / "capabilities" / ".prepared" / "old"
    old.mkdir(parents=True)
    stale = time.time() - capability_install.PREPARED_MAX_AGE_S - 60
    os.utime(old, (stale, stale))
    fresh = old.parent / "fresh"
    fresh.mkdir()
    await capability_install.prepare(PYPI)
    left = {p.name for p in old.parent.iterdir()}
    assert "old" not in left and "fresh" in left and len(left) == 2


def test_the_runtime_pins_carry_a_checksum_in_the_repository():
    """D1: Arslan's runtime is part of the app because its version and SHA-256 are pinned here and checked."""
    for pin in capability_runtime.PINS.values():
        assert len(pin.sha256) == 64 and pin.url.startswith("https://") and pin.version in pin.url


async def test_a_bundle_shows_its_published_checksum_and_one_without_gets_no_card(monkeypatch, _world):
    bundle = {**PYPI, "id": "registry:io.github.acme/notes-bundle@1.0.0", "runtime": "mcpb",
              "package": {"registry_type": "mcpb", "identifier": "https://github.com/acme/notes/releases/notes.mcpb",
                          "version": "1.0.0", "file_sha256": "D" * 64, "arguments": []}}
    out, [card], before_card = await _propose(monkeypatch, _world, bundle, approve=False)
    assert card["lock"] == {"sha256": "d" * 64, "count": 1, "packages": [{"name": "notes.mcpb", "version": "1.0.0"}]}
    assert before_card == []                                               # nothing to resolve, nothing downloaded
    bundle["package"] = {**bundle["package"], "file_sha256": None}
    out, cards, _ = await _propose(monkeypatch, _world, bundle)
    assert cards == [] and out["error"] == "cannot be added: no_checksum"
