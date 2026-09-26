"""Bounded native-loop policy, independent of model prose and UI language.

These classifications do not grant tool access or certify a successful effect.
Write retry decisions belong to the durable action journal, never this policy.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum

import httpx


class FailureKind(StrEnum):
    RETRYABLE = "retryable"
    INPUT_REQUIRED = "input_required"
    DENIED = "denied"
    PERMANENT = "permanent"
    UNCERTAIN = "uncertain"


def exception_kind(exc: Exception) -> FailureKind:
    """Only known transport failures merit automatic model-request retries."""
    if isinstance(exc, (TimeoutError, httpx.TimeoutException, httpx.NetworkError)):
        return FailureKind.RETRYABLE
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in {408, 425, 429, 500, 502, 503, 504}:
            return FailureKind.RETRYABLE
        if status in {401, 403}:
            return FailureKind.DENIED
        if status in {400, 413, 415, 422}:
            return FailureKind.INPUT_REQUIRED
    if isinstance(exc, PermissionError):
        return FailureKind.DENIED
    if isinstance(exc, (ValueError, TypeError)):
        return FailureKind.INPUT_REQUIRED
    return FailureKind.PERMANENT


def tool_failure(result: dict) -> FailureKind | None:
    if result.get("ok"):
        return None
    declared = result.get("failure_kind")
    if isinstance(declared, str) and declared in set(FailureKind):
        return FailureKind(declared)
    code = str(result.get("code") or result.get("error_code") or "").casefold()
    if code in {"task_reconciliation_required", "task_action_uncertain"}:
        return FailureKind.UNCERTAIN
    if code in {"credentials_not_tool_data", "permission_denied", "grant_revoked", "tool_unavailable"}:
        return FailureKind.DENIED
    if code in {"invalid_arguments", "missing_input", "connection_required"}:
        return FailureKind.INPUT_REQUIRED
    if code in {"timeout", "rate_limit", "temporarily_unavailable"}:
        return FailureKind.RETRYABLE
    # Compatibility descriptions are classified for diagnosis only. A phrase
    # cannot authorize automatic tool retries or widen a permission.
    text = str(result.get("error") or "").casefold()
    if any(word in text for word in ("declined", "permission", "not available", "confirmation")):
        return FailureKind.DENIED
    if any(word in text for word in ("not configured", "missing", "invalid argument")):
        return FailureKind.INPUT_REQUIRED
    if any(word in text for word in ("timed out", "timeout", "rate limit", "temporarily")):
        return FailureKind.RETRYABLE
    return FailureKind.PERMANENT


@dataclass
class ProgressPolicy:
    """Detect repeated identical work and consecutive failures within one loop.

    Counters contain only hashes and structural classifications. A novel successful
    tool result resets a failure streak; repeating the same returned evidence with
    differently phrased queries does not. Global budgets remain the ultimate bounds.
    """
    max_stalled: int = 4
    stalled: int = 0
    observations: int = 0
    seen: set[str] = field(default_factory=set)
    last_failure: FailureKind | None = None

    def observe(self, tool: str, arguments: dict, result: dict) -> bool:
        self.observations += 1
        self.last_failure = tool_failure(result)
        if self.last_failure is not None:
            self.stalled += 1
            return False
        evidence = result
        if tool == "web_extract" and isinstance(result.get("source"), dict):
            # Refetching identical evidence is not progress merely because the
            # receipt has a newer clock value. Keep URL, text, scope and all
            # other fields; do not mutate the actual provenance shown to users.
            evidence = {**result, "source": {
                key: value for key, value in result["source"].items()
                if key != "retrieved_at"
            }}
        encoded = json.dumps([tool, evidence], ensure_ascii=False,
                             sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        novel = digest not in self.seen
        self.seen.add(digest)
        self.stalled = 0 if novel else self.stalled + 1
        return novel

    @property
    def stopped(self) -> bool:
        return self.stalled >= self.max_stalled


def bounded_history(history: list[dict], *, max_chars: int = 64_000,
                    preserve_tail: int = 0) -> tuple[list[dict], bool]:
    """Drop only old complete turns, preserving native provider-content pairs.

    This is reference retention, not a semantic summarizer. Durable task progress
    remains separately recoverable. The most recent group is retained even when
    it exceeds this soft bound; truncating an opaque provider block is unsafe.
    A caller may group a bounded batch of newly returned tool messages so each
    reaches the model once. This is not permanent pinning; the next call must
    explicitly request protection again. Native provider pairs remain intact.
    """
    if type(preserve_tail) is not int or not 0 <= preserve_tail <= len(history):
        raise ValueError("invalid history tail")
    groups: list[list[dict]] = []
    index = 0
    while index < len(history):
        item = history[index]
        content = item.get("content")
        is_provider = (item.get("role") == "assistant" and isinstance(content, list)
                       and any(isinstance(part, dict) and part.get("type") == "provider_content"
                               for part in content))
        if is_provider and index + 1 < len(history):
            groups.append(history[index:index + 2])
            index += 2
        else:
            groups.append([item])
            index += 1
    if preserve_tail:
        tail, count = [], 0
        while groups and count < preserve_tail:
            group = groups.pop()
            tail.append(group)
            count += len(group)
        groups.append([item for group in reversed(tail) for item in group])
    total, kept = 0, []
    for group in reversed(groups):
        size = len(json.dumps(group, ensure_ascii=False, default=str))
        if kept and total + size > max_chars:
            break
        kept.append(group)
        total += size
    result = [item for group in reversed(kept) for item in group]
    return result, len(result) != len(history)
