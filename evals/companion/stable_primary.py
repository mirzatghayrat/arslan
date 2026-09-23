"""Read only the configured primary and crypto material for an authorized run.

No application startup, migrations, chat reads or provider selection. Never log
the database row, key, ciphertext or provider exception text.
"""
import base64
from datetime import datetime, timezone
import json
import os
import sqlite3

from evals.companion import stable_budget as budget


def pricing_snapshot(path):
    pricing = json.loads(path.read_bytes())
    if (pricing.get("verified_on_utc") != datetime.now(timezone.utc).date().isoformat()
            or pricing.get("model") != "deepseek-v4-flash"
            or pricing.get("input_usd_per_million") != "0.30"
            or pricing.get("output_usd_per_million") != "1.20"
            or pricing.get("source") != "https://api-docs.deepseek.com/quick_start/pricing/"
            or pricing.get("provider") != "deepseek"
            or pricing.get("endpoint") != "https://api.deepseek.com"):
        raise RuntimeError("stable_pricing_requires_review")
    return pricing


def primary_adapter(profile, secret_file, pricing):
    if os.environ.get("ARSLAN_STABLE_LIVE") != "authorized-36-requests-usd5":
        raise RuntimeError("stable_authorization_missing")
    if (budget.EVIDENCE / "HALT").exists() or budget.status()["requests"] >= 36:
        raise RuntimeError("stable_budget_unavailable")
    # Only these two narrow queries touch the real profile, always read-only.
    with sqlite3.connect(f"file:{profile / 'arslan.db'}?mode=ro", uri=True) as db:
        rows = db.execute("SELECT provider, model, base_url, api_key FROM provider_configs WHERE is_primary=1").fetchall()
        salt = db.execute("SELECT value FROM settings WHERE key='crypto_salt_b64'").fetchone()
    if len(rows) != 1 or not salt:
        raise RuntimeError("stable_primary_or_salt_missing")
    provider, model, base_url, encrypted = rows[0]
    if (provider != "deepseek" or model != pricing["model"] or model != "deepseek-v4-flash"
            or (base_url or "").rstrip("/") not in {"", "https://api.deepseek.com", "https://api.deepseek.com/v1"}):
        raise RuntimeError("stable_primary_changed_reverify_pricing")
    from arslan.llm.adapter import LLMAdapter
    from server.crypto_material import keyring
    key = keyring(secret_file.read_text().strip(), base64.b64decode(salt[0], validate=True)).decrypt(encrypted.encode()).decode()
    return LLMAdapter("openai", model, api_key=key, base_url=(base_url or "https://api.deepseek.com").rstrip("/"),
                      report_provider="deepseek")
