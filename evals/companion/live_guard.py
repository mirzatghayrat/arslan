"""Explicit opt-in, read-only primary configuration and durable live-test cap.

Only for the 2026-09-23 user-approved DeepSeek pilot; not a production router.
Official peak rates verified 2026-09-23: $0.30/M input, $1.20/M output.
Each request reserves $0.10 without refunds, including errors/interruption.
36 reservations therefore stay below the authorized $5 even across retries.
"""
import base64
import fcntl
import json
import os
from pathlib import Path
import sqlite3

from arslan.llm.adapter import LLMAdapter
from server.crypto_material import keyring


def reserve(path: Path, payload: dict) -> int:
    if (path.parent / "HALT").exists():
        raise RuntimeError("live_run_halted")
    raw = json.dumps(payload, ensure_ascii=False).encode()
    # UTF-8 bytes plus a generous framing allowance bound input token counts.
    if len(raw) > 100_000 or payload.get("max_tokens") != 8192:
        raise RuntimeError("live_input_or_output_cap")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.seek(0)
        lines = stream.readlines()
        records = [json.loads(line) for line in lines]  # corrupt ledger fails closed
        if any(row.get("reserved_usd") != "0.10" for row in records) or len(records) >= 36:
            raise RuntimeError("live_budget_exhausted_or_invalid")
        number = len(records) + 1
        stream.write(json.dumps({"request": number, "reserved_usd": "0.10", "payload_bytes": len(raw)}) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
        return number


def primary_adapter(profile: Path, secret_file: Path) -> LLMAdapter:
    if os.environ.get("ARSLAN_STAGE2_LIVE") != "authorized-36-requests-usd5":
        raise RuntimeError("live_authorization_missing")
    # Do not import application startup or write/migrate the user's database.
    with sqlite3.connect(f"file:{profile / 'arslan.db'}?mode=ro", uri=True) as db:
        rows = db.execute("SELECT provider, model, base_url, api_key FROM provider_configs WHERE is_primary=1").fetchall()
        salt = db.execute("SELECT value FROM settings WHERE key='crypto_salt_b64'").fetchone()
    if len(rows) != 1 or not salt:
        raise RuntimeError("primary_or_salt_missing")
    provider, model, base_url, encrypted = rows[0]
    if provider != "deepseek" or model != "deepseek-v4-flash" or (base_url or "").rstrip("/") not in {
        "", "https://api.deepseek.com", "https://api.deepseek.com/v1",
    }:
        raise RuntimeError("primary_changed_reverify_pricing")
    key = keyring(secret_file.read_text().strip(), base64.b64decode(salt[0], validate=True)).decrypt(encrypted.encode()).decode()
    return LLMAdapter("openai", model, api_key=key, base_url=(base_url or "https://api.deepseek.com").rstrip("/"),
                      report_provider="deepseek")


class GuardedAdapter:
    def __init__(self, adapter, output: Path):
        self.adapter, self.output = adapter, output
        self.model = adapter.model

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        provider = self.adapter._provider
        payload = provider._payload(provider.build_messages(system, user, history), tools, temperature)
        number = reserve(self.output / "reservations.jsonl", payload)
        # Fixed output cap and no automatic retry in the non-streaming provider.
        result = await self.adapter.chat(system, user, history=history, tools=tools, temperature=temperature)
        usage = result.usage or {}
        record = {"request": number, "model_requested": self.model, "usage": usage,
                  "answer": result.content, "tool_calls": result.tool_calls,
                  "input_system": system, "input_user": user, "input_history": history}
        with (self.output / f"response-{number:02d}.json").open("x", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
        # Usage omission/oversize is not silently converted into a zero bill.
        if not all(type(usage.get(key)) is int and usage[key] >= 0 for key in ("prompt_tokens", "completion_tokens")):
            (self.output / "HALT").write_text("usage_unknown")
            raise RuntimeError("live_usage_unknown_stop")
        if usage["prompt_tokens"] > 200_000 or usage["completion_tokens"] > 8192:
            (self.output / "HALT").write_text("usage_bound_violation")
            raise RuntimeError("live_usage_bound_violation_stop")
        return result

    async def chat_stream(self, system, user, history=None, tools=None, temperature=0.7):
        result = await self.chat(system, user, history, tools, temperature)
        yield result.content
