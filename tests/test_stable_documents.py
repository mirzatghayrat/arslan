"""Offline preflight and narrow credential-loader regressions. No paid calls."""
from datetime import datetime, timezone
import json
import sqlite3

import pytest

from evals.companion import stable_budget as budget, stable_documents as documents
from evals.companion.stable_primary import primary_adapter, pricing_snapshot


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(budget, "EVIDENCE", tmp_path)
    monkeypatch.setattr(documents.ingest.ocr_vision, "is_available", lambda: False)
    budget.initialize()
    return tmp_path


@pytest.mark.parametrize("case_id", documents.DOCUMENT_CASES)
def test_freeze_replays_exact_bytes_and_disallows_replacement(isolated, case_id):
    record = documents.freeze(case_id)
    verified, digest = documents.verified_preflight(case_id)
    assert verified == record and len(digest) == 64
    assert verified["quality_status"] == verified["native_status"] == "not_run"
    with pytest.raises(FileExistsError):
        documents.freeze(case_id)
    path = isolated / record["inputs"][0]["path"]
    path.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="input_changed"):
        documents.verified_preflight(case_id)


def test_prompt_change_is_rejected(isolated):
    documents.freeze("S2-D1")
    path = isolated / "S2-D1-preflight.json"
    data = json.loads(path.read_bytes())
    data["prompt"] += "invent a result"
    path.write_text(json.dumps(data))
    with pytest.raises(RuntimeError, match="preflight_changed"):
        documents.verified_preflight("S2-D1")


def test_reader_rejects_ocr_and_preserves_blank_page(isolated, monkeypatch):
    bodies = documents.inputs("S2-D1")
    extracted = documents.read_inputs("S2-D1", bodies)
    assert "[page 1]" in extracted and "[page 3]" in extracted and "[page 2]" not in extracted
    monkeypatch.setattr(documents.ingest.ocr_vision, "is_available", lambda: True)
    with pytest.raises(RuntimeError, match="ocr_must_be_disabled"):
        documents.read_inputs("S2-D1", bodies)


def test_loader_requires_authorization_before_reading_profile(isolated, monkeypatch):
    monkeypatch.delenv("ARSLAN_STABLE_LIVE", raising=False)
    with pytest.raises(RuntimeError, match="authorization_missing"):
        primary_adapter(isolated / "absent-profile", isolated / "absent-key", {})


def test_changed_primary_refuses_before_decryption(isolated, monkeypatch):
    monkeypatch.setenv("ARSLAN_STABLE_LIVE", "authorized-36-requests-usd5")
    with sqlite3.connect(isolated / "arslan.db") as db:
        db.execute("CREATE TABLE provider_configs (provider,model,base_url,api_key,is_primary)")
        db.execute("INSERT INTO provider_configs VALUES ('other','other','','not-a-key',1)")
        db.execute("CREATE TABLE settings (key,value)")
        db.execute("INSERT INTO settings VALUES ('crypto_salt_b64','not-a-salt')")
    with pytest.raises(RuntimeError, match="primary_changed"):
        primary_adapter(isolated, isolated / "absent-key", {"model": "deepseek-v4-flash"})


def test_pricing_requires_exact_reviewed_identity_and_date(isolated):
    path = isolated / "pricing.json"
    value = {"verified_on_utc": datetime.now(timezone.utc).date().isoformat(),
        "model": "deepseek-v4-flash", "input_usd_per_million": "0.30", "output_usd_per_million": "1.20",
        "source": "https://api-docs.deepseek.com/quick_start/pricing/", "provider": "deepseek",
        "endpoint": "https://api.deepseek.com"}
    path.write_text(json.dumps(value))
    assert pricing_snapshot(path) == value
    for key, replacement in (("verified_on_utc", "2000-01-01"), ("model", "other"),
                             ("input_usd_per_million", "0"), ("endpoint", "https://other.example")):
        path.write_text(json.dumps({**value, key: replacement}))
        with pytest.raises(RuntimeError, match="pricing_requires_review"):
            pricing_snapshot(path)
