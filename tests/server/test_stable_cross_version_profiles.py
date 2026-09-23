"""Opt-in, source-version profile rehearsal; not signed-app/UI acceptance.

Uses only local Git objects and synthetic data in pytest temporary directories.
Run with ARSLAN_STABLE_COMPAT=1. No fetch, model calls, real HOME or app launch.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest

from server.services import backup
from server.services.recovery_preflight import check


ROOT = Path(__file__).resolve().parents[2]
SECRET = "stable-cross-version-synthetic-only"
SOURCES = [
    ("v0.1.38", "1724d2afa95fd4dfff28d1151135e00ec15926d4", "0046"),
    ("v0.1.40-beta.3", "fe0624943534e63b38a9a440c6631000c0798eec", "0053"),
    ("v0.1.40-beta.6", "0beb89bd638d5846745b7546adeb128452a5a0c2", "0053"),
]
pytestmark = pytest.mark.skipif(os.environ.get("ARSLAN_STABLE_COMPAT") != "1",
                              reason="explicit historical-source acceptance only")

# The released storage preparation functions are imported from the chosen
# archive, never from the parent test's module cache. No seeders/workers run.
CHILD = r'''
import asyncio
import json
import os
from pathlib import Path
import sys

def audit(event, args):
    if event in {"socket.connect", "socket.bind", "socket.getaddrinfo"}:
        raise RuntimeError("network_forbidden_in_profile_rehearsal")
sys.addaudithook(audit)

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from server import config, crypto
from server.db.models import Base, ArslanMessage, UserFact, ProviderConfig, Setting
from server.db.migrations import runner
from server.services import crypto_boot

assert Path(config.settings.data_dir).resolve() == Path(os.environ["ARSLAN_DATA_DIR"]).resolve()
assert Path(config.settings.db_path).resolve() == Path(os.environ["ARSLAN_DB_PATH"]).resolve()
profile = Path(config.settings.data_dir)
profile.mkdir(parents=True, exist_ok=True)

if sys.argv[1] == "create":
    engine = sa.create_engine("sqlite:///" + config.settings.db_path)
    with engine.begin() as db:
        Base.metadata.create_all(db)
        runner.apply_pending(db)
        crypto_boot.resolve_and_adopt_salt(db)
        crypto_boot.migrate_legacy_ciphertext(db)
        db.execute(Setting.__table__.insert().values(key="language", value="en"))
        db.execute(ArslanMessage.__table__.insert().values(
            conversation_id="stable-synthetic", role="user", content="Synthetic Cedar owner Mira"))
        db.execute(UserFact.__table__.insert().values(
            content="Synthetic Cedar uses orange diagrams", source="manual", sensitive=False))
        db.execute(ProviderConfig.__table__.insert().values(
            label="synthetic-offline", provider="openai", model="never-call",
            api_key=crypto.encrypt("synthetic-provider-credential"), is_primary=True))
    engine.dispose()
    (profile / "artifacts").mkdir()
    (profile / "artifacts" / "result.csv").write_text("currency,total\nUSD,12.00\n")

async def boot():
    engine = create_async_engine("sqlite+aiosqlite:///" + config.settings.db_path)
    try:
        if Path("server/services/storage_boot.py").is_file():
            from server.services.storage_boot import initialize
            await initialize(engine)
        else:
            # v0.1.38 server.main lifespan's storage-only prefix, same order.
            async with engine.begin() as db:
                for fn in (Base.metadata.create_all, runner.apply_pending,
                           crypto_boot.resolve_and_adopt_salt, crypto_boot.migrate_legacy_ciphertext):
                    await db.run_sync(fn)
        async with engine.connect() as db:
            assert await db.scalar(sa.text("SELECT content FROM arslan_messages WHERE conversation_id='stable-synthetic'")) == "Synthetic Cedar owner Mira"
            assert await db.scalar(sa.text("SELECT content FROM user_facts WHERE id=1")) == "Synthetic Cedar uses orange diagrams"
            ciphertext = await db.scalar(sa.text("SELECT api_key FROM provider_configs WHERE label='synthetic-offline'"))
            assert crypto.decrypt(ciphertext) == "synthetic-provider-credential"
            assert await db.scalar(sa.text("PRAGMA integrity_check")) == "ok"
            versions = list((await db.execute(sa.text("SELECT version FROM schema_version ORDER BY version"))).scalars())
            assert versions == [version for version, _ in runner.MIGRATIONS]
            assert (profile / "artifacts/result.csv").read_text() == "currency,total\nUSD,12.00\n"
    finally:
        await engine.dispose()
    return {"head": runner.head(), "versions": versions, "checks": ["chat", "legacy_fact", "credential", "artifact", "integrity"]}
print(json.dumps(asyncio.run(boot())))
'''


def run_child(source, profile, home, operation):
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home),
        "ARSLAN_DATA_DIR": str(profile), "ARSLAN_DB_PATH": str(profile / "arslan.db"),
        "ARSLAN_SECRET_KEY": SECRET, "ARSLAN_SECRET_KEY_FILE": "",
        "ARSLAN_ENV": "prod", "ARSLAN_LIVE_LLM": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    result = subprocess.run([sys.executable, "-c", CHILD, operation], cwd=source,
                            env=environment, text=True, capture_output=True, timeout=45)
    assert result.returncode == 0, result.stderr
    assert SECRET not in result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("tag,commit,head", SOURCES)
def test_released_profile_upgrade_restart_and_preupgrade_backup_recovery(tmp_path, tag, commit, head):
    resolved = subprocess.check_output(["git", "rev-parse", f"{tag}^{{commit}}"], cwd=ROOT, text=True).strip()
    assert resolved == commit, "release label must match the pinned source commit"
    archive = subprocess.run(["git", "archive", "--format=zip", commit, "server", "arslan"],
                             cwd=ROOT, capture_output=True, check=True, timeout=20).stdout
    source = tmp_path / "released-source"
    source.mkdir()
    with zipfile.ZipFile(io.BytesIO(archive)) as packed:
        packed.extractall(source)
    profile, upgraded, restored = (tmp_path / name for name in ("original", "upgraded", "restored"))
    home = tmp_path / "isolated-home"
    home.mkdir()
    created = run_child(source, profile, home, "create")
    assert created["head"] == head
    original_digest = digest(profile / "arslan.db")
    archive_path = tmp_path / "pre-upgrade.zip"
    backup.create(profile, archive_path)
    backup_digest = digest(archive_path)

    shutil.copytree(profile, upgraded)
    boots = [run_child(ROOT, upgraded, home, "boot") for _ in range(2)]
    assert boots[0] == boots[1] and boots[0]["head"] == "0053"
    assert check(upgraded / "arslan.db", SECRET)["status"] == "compatible"
    upgraded_digest = digest(upgraded / "arslan.db")
    assert check(upgraded / "arslan.db", "wrong-synthetic-key")["status"] == "unreadable_credentials"
    assert check(upgraded / "arslan.db", None)["status"] == "secret_required"
    assert digest(upgraded / "arslan.db") == upgraded_digest

    # Supported recovery is pre-upgrade archive + matching key + old source.
    # Never claim the old binary can open the upgraded database safely.
    backup.restore(archive_path, restored)
    recovered = run_child(source, restored, home, "boot")
    assert recovered == created
    assert digest(profile / "arslan.db") == original_digest
    assert digest(archive_path) == backup_digest
    assert not (home / ".arslan").exists()
    report = {
        "source_tag_label": tag, "source_commit": commit, "source_head": head,
        "candidate_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "candidate_worktree_diff": subprocess.check_output(["git", "diff", "--stat"], cwd=ROOT, text=True),
        "harness_sha256": digest(Path(__file__)), "python": sys.version,
        "historical_source_archive_sha256": hashlib.sha256(archive).hexdigest(),
        "original_database_sha256": original_digest, "preupgrade_backup_sha256": backup_digest,
        "upgraded_database_sha256": upgraded_digest, "boot_results": boots, "recovery": recovered,
        "wrong_key": "refused_read_only", "missing_key": "refused_read_only",
        "limitations": ["source-level, not packaged/UI", "synthetic data", "current dependency environment",
                        "no interrupted process or updater exercised", "not safe in-place downgrade"],
    }
    evidence = os.environ.get("ARSLAN_STABLE_COMPAT_EVIDENCE")
    if evidence:
        target = Path(evidence)
        target.mkdir(parents=True, exist_ok=True)
        with (target / f"{tag}.json").open("x") as stream:
            json.dump(report, stream, indent=2)
