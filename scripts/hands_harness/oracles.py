"""The harness's judges (spec docs/specs/2026-10-08-0157-hands-v2.md §8.3). Pure functions over
what the observer sampled and what the fixtures logged, so they are tested anywhere.

O1 front app unchanged · O2 the user's key window unchanged (a micro-borrow may take it for
at most `borrow_ms`) · O3 hardware pointer unchanged · O4 on-screen window order unchanged ·
O5 the typist's text exact (nothing lost, nothing misdirected) · O6 each requested action
happened exactly once · O7 the reported outcome agrees with the ground truth.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Sample:
    t: float
    front_pid: int | None
    pointer: tuple[float, float]
    order: tuple[int, ...]          # on-screen window ids, front to back, without the engine's own


@dataclass
class Verdict:
    violations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations


def disturbance(before: Sample, during: list[Sample], after: Sample, *, pointer_slack: float = 0.5) -> Verdict:
    """O1, O3, O4 over the samples of one action, against the moment before it."""
    verdict = Verdict()
    for s in [*during, after]:
        if s.front_pid != before.front_pid:
            verdict.violations.append(f"O1 front app changed at {s.t:.3f}s ({before.front_pid} -> {s.front_pid})")
            break
    for s in [*during, after]:
        if abs(s.pointer[0] - before.pointer[0]) > pointer_slack or abs(s.pointer[1] - before.pointer[1]) > pointer_slack:
            verdict.violations.append(f"O3 pointer moved at {s.t:.3f}s")
            break
    if after.order != before.order:
        verdict.violations.append("O4 window order changed")
    return verdict


def key_window(key_events: list[tuple[float, bool]], start: float, end: float, *, borrow_ms: float = 0.0) -> Verdict:
    """O2 from the typist's own log of becoming / resigning key, within [start, end].
    A resign followed by a become within `borrow_ms` is a micro-borrow; anything longer, or a
    resign never undone, is a violation."""
    verdict = Verdict()
    lost_at: float | None = None
    for t, is_key in sorted(key_events):
        if t < start or t > end:
            continue
        if not is_key and lost_at is None:
            lost_at = t
        elif is_key and lost_at is not None:
            if (t - lost_at) * 1000 > borrow_ms:
                verdict.violations.append(f"O2 key window lost for {(t - lost_at) * 1000:.0f} ms")
            lost_at = None
    if lost_at is not None:
        verdict.violations.append("O2 key window lost and not given back")
    return verdict


def typed_exactly(expected: str, typist_text: str, target_texts: list[str]) -> Verdict:
    """O5: everything the user typed is in the typist, in order, and none of it reached the target."""
    verdict = Verdict()
    if typist_text != expected:
        lost = len(expected) - len(typist_text)
        verdict.violations.append(f"O5 typist text differs ({lost:+d} chars): {typist_text[-40:]!r}")
    for text in target_texts:
        if expected and any(chunk in text for chunk in _chunks(expected)):
            verdict.violations.append(f"O5 the user's typing reached the target: {text[-40:]!r}")
            break
    return verdict


def _chunks(text: str, size: int = 4) -> list[str]:
    return [text[i:i + size] for i in range(0, max(len(text) - size + 1, 1), size)] if len(text) >= size else [text]


def once(count_before: int, count_after: int, expected: int = 1) -> Verdict:
    """O6: the fixture counted exactly `expected` effects."""
    happened = count_after - count_before
    return Verdict([] if happened == expected else [f"O6 happened {happened} times, expected {expected}"])


def honest(reported: str | None, happened: bool) -> Verdict:
    """O7: `done` must mean it happened; `refused` must mean it did not. The other outcomes
    make no claim either way and are never lies."""
    if reported == "done" and not happened:
        return Verdict(["O7 reported done but nothing happened"])
    if reported == "refused" and happened:
        return Verdict(["O7 reported refused but it happened"])
    return Verdict()
