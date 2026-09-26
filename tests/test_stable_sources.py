import hashlib

import pytest

from evals.companion import stable_sources as collector


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(collector.budget, "EVIDENCE", tmp_path)
    return tmp_path


def item(body=b"synthetic input"):
    return {"id": "fixture", "url": "https://example.invalid/frozen", "kind": "synthetic",
            "sha256": hashlib.sha256(body).hexdigest()}


def test_allowlist_contains_pinned_references_only():
    entries = collector.sources()
    assert len(entries) == 7
    assert all("/abs/" in row["url"] or row.get("commit") in row["url"] for row in entries)
    with pytest.raises(RuntimeError, match="allowlist"):
        collector.fetch("https://example.invalid/unapproved")


def test_archive_reuses_verified_bytes_without_refetch_or_fake_receipt(isolated, monkeypatch):
    calls = []
    def fetch(url):
        calls.append(url)
        return b"synthetic input", "text/plain"
    monkeypatch.setattr(collector, "fetch", fetch)
    first = collector.collect_one(item())
    assert collector.collect_one(item()) == first
    assert len(calls) == 1
    assert first["runtime_receipt"] is None and first["quality_status"] == "not_run"


def test_bad_pinned_hash_is_not_archived(isolated, monkeypatch):
    monkeypatch.setattr(collector, "fetch", lambda url: (b"different", "text/plain"))
    with pytest.raises(RuntimeError, match="hash_mismatch"):
        collector.collect_one(item())
    assert not list((isolated / "public-inputs").iterdir())


def test_changed_archive_refuses_and_retains_bytes(isolated, monkeypatch):
    monkeypatch.setattr(collector, "fetch", lambda url: (b"synthetic input", "text/plain"))
    collector.collect_one(item())
    path = isolated / "public-inputs/fixture.body"
    path.write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="changed"):
        collector.collect_one(item())
    assert path.read_bytes() == b"changed"
