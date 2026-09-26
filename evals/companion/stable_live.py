"""Stable-pilot adapter: reserve before one non-streaming call; halt on ambiguity.

Not a provider selector. The isolated runner supplies the user-configured primary
after separately verifying pricing and credential handling. Never import or use
this from production routing. No model is called merely by importing this file.
"""
from decimal import Decimal
import fcntl
import hashlib
import json
import os

from evals.companion import stable_budget as budget


def persist(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def halt(reason):
    try:
        persist(budget.EVIDENCE / "HALT", {"reason": reason})
    except FileExistsError:
        pass


class StableAdapter:
    def __init__(self, adapter, case_id, pricing, preflight_sha256):
        provider = adapter._provider
        endpoint = provider.base_url.rstrip("/")
        if (adapter.provider_name != "openai" or adapter.report_provider != "deepseek"
                or endpoint not in {"https://api.deepseek.com", "https://api.deepseek.com/v1"}
                or adapter.model != pricing.get("model")):
            raise RuntimeError("stable_primary_identity_mismatch")
        self.adapter, self.case_id, self.pricing = adapter, case_id, dict(pricing)
        self.preflight_sha256 = preflight_sha256
        self.model = adapter.model

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        # One in-flight request across all adapter instances/processes. A missing
        # usage result/HALT must be seen before a second request can be sent.
        with (budget.EVIDENCE / "inflight.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError("stable_request_already_inflight") from error
            previous = budget.status()["requests"]
            if previous:
                try:
                    accounted = json.loads((budget.EVIDENCE / f"request-{previous:02d}.accounted.json").read_text())
                    estimate = Decimal(accounted["peak_rate_estimate_usd"])
                    valid = (accounted["request"] == previous and accounted["reserved_usd"] == "0.10"
                             and accounted["reservation_refunded"] is False
                             and estimate.is_finite() and Decimal(0) <= estimate <= Decimal("0.10"))
                except (OSError, ValueError, KeyError, TypeError, ArithmeticError):
                    valid = False
                if not valid:
                    halt("prior_request_unaccounted")
                    raise RuntimeError("stable_prior_request_unaccounted")
            provider = self.adapter._provider
            payload = provider._payload(provider.build_messages(system, user, history), tools, temperature)
            number = budget.reserve(self.case_id, payload, pricing=self.pricing,
                                    preflight_sha256=self.preflight_sha256)
            prefix = budget.EVIDENCE / f"request-{number:02d}"
            try:
                persist(prefix.with_suffix(".input.json"), {"case": self.case_id, "request": number,
                    "payload": payload, "preflight_sha256": self.preflight_sha256,
                    "payload_sha256": hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()})
                # The OpenAI-compatible non-streaming method contains one POST,
                # no retry. Never use its streaming fallback for this pilot.
                result = await self.adapter.chat(system, user, history=history, tools=tools, temperature=temperature)
                usage = result.usage or {}
                persist(prefix.with_suffix(".response.json"), {"case": self.case_id, "request": number,
                    "model_requested": self.model, "usage": usage,
                    "answer": result.content, "tool_calls": result.tool_calls, "quality_status": "not_run"})
                if not all(type(usage.get(key)) is int and usage[key] >= 0
                           for key in ("prompt_tokens", "completion_tokens")):
                    raise RuntimeError("stable_usage_unknown")
                if usage["prompt_tokens"] > 200_000 or usage["completion_tokens"] > payload["max_tokens"]:
                    raise RuntimeError("stable_usage_bound_violation")
                estimated = (usage["prompt_tokens"] * Decimal(str(self.pricing["input_usd_per_million"]))
                             + usage["completion_tokens"] * Decimal(str(self.pricing["output_usd_per_million"]))) / 1_000_000
                if estimated > Decimal("0.10"):
                    raise RuntimeError("stable_usage_price_violation")
                persist(prefix.with_suffix(".accounted.json"), {"request": number,
                    "peak_rate_estimate_usd": str(estimated), "invoice": False,
                    "reserved_usd": "0.10", "reservation_refunded": False})
                return result
            except BaseException as error:
                # Do not persist exception messages: provider errors may include
                # request details. The reservation is never refunded or retried.
                halt(type(error).__name__)
                raise

    async def chat_stream(self, system, user, history=None, tools=None, temperature=0.7):
        result = await self.chat(system, user, history, tools, temperature)
        yield result.content
