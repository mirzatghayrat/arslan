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
    if code in {"invalid_arguments", "invalid_arguments_json", "missing_input", "connection_required"}:
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
    """Detect a loop that makes no progress (K4a, v0.1.63): the same returned evidence 4 times (a new
    result resets that streak), or the same failing call — tool, arguments and error — 3 times.

    Different failures don't add up: five blocked sites in a row are five calls, not one stuck step
    (web_extract's errors don't carry the URL, so the error alone can't tell them apart). Before K4a any
    4 failures in a row stopped the loop. Counters contain only hashes and structural classifications;
    global budgets remain the ultimate bounds.
    """
    max_stalled: int = 4
    max_same_failure: int = 3
    stalled: int = 0
    observations: int = 0
    seen: set[str] = field(default_factory=set)
    failures: dict[str, int] = field(default_factory=dict)
    last_failure: FailureKind | None = None
    _failed_call: str | None = field(default=None, repr=False)

    def observe(self, tool: str, arguments: dict, result: dict) -> bool:
        self.observations += 1
        self.last_failure = tool_failure(result)
        if self.last_failure is not None:
            call = json.dumps([tool, arguments, str(result.get("error") or result.get("code") or "")],
                              ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
            self._failed_call = hashlib.sha256(call.encode()).hexdigest()
            self.failures[self._failed_call] = self.failures.get(self._failed_call, 0) + 1
            return False
        self._failed_call = None
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
    def count(self) -> int:
        """How far the last observation is toward its stop: the same failing call, or the same result."""
        return self.failures[self._failed_call] if self._failed_call else self.stalled

    @property
    def limit(self) -> int:
        return self.max_same_failure if self._failed_call else self.max_stalled

    @property
    def stopped(self) -> bool:
        return self.stalled >= self.max_stalled or any(n >= self.max_same_failure for n in self.failures.values())


def bounded_history(history: list[dict], *, max_chars: int = 64_000,
                    preserve_tail: int = 0, size_of=None, trim_to: int | None = None) -> tuple[list[dict], bool]:
    """Drop only old complete turns, preserving native provider-content pairs.

    This is reference retention, not a semantic summarizer. Durable task progress
    remains separately recoverable. The most recent group is retained even when
    it exceeds this soft bound; truncating an opaque provider block is unsafe.
    A caller may group a bounded batch of newly returned tool messages so each
    reaches the model once. This is not permanent pinning; the next call must
    explicitly request protection again. Native provider pairs remain intact.

    0.1.49: a neutral tool-call group (assistant tool_calls + its tool records,
    arslan/llm/trajectory.py) is one unit too; `size_of` measures a group as it
    will be sent (the caller's rendering), defaulting to its JSON length.

    K4a: with `trim_to`, a history over `max_chars` is trimmed down to `trim_to` in one go, not just under
    `max_chars`. A caller that keeps the trimmed history then grows it again for a while: on a provider
    that caches the prompt's prefix, the cache breaks once per chunk instead of on every step.
    """
    from arslan.llm import trajectory
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
        elif trajectory.is_call_group_start(item):
            group = trajectory.groups(history[index:])[0]
            groups.append(group)
            index += len(group)
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

    def measure(group):
        return size_of(group) if size_of else len(json.dumps(group, ensure_ascii=False, default=str))

    def keep(bound):
        total, kept, shrunk = 0, [], False
        for group in reversed(groups):
            if not kept and not preserve_tail:
                # The newest unit is always kept. An unprotected neutral call group
                # that alone exceeds the bound sheds its oldest results' bodies
                # (explicit notice, pairing intact). A protected tail is delivered whole.
                fitted = trajectory.shrink_group(group, max_chars, measure)
                shrunk = fitted is not group
                group = fitted
            size = measure(group)
            if kept and total + size > bound:
                break
            kept.append(group)
            total += size
        return kept, shrunk

    kept, shrunk = keep(max_chars)
    if trim_to is not None and trim_to < max_chars and len(kept) < len(groups):
        kept, shrunk = keep(trim_to)
    result = [item for group in reversed(kept) for item in group]
    return result, shrunk or len(result) != len(history)
