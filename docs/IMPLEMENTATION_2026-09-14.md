# Reliability implementation — 2026-09-14

Baseline: `19f307720c9ffb00df04a591781a2be8a1f94dc1` / v0.1.37.
Branch: `codex/reliability-2026-09-14`.

The maintainer authorized implementation, push, and version updates. Paid model
evaluation has not been authorized. Use synthetic data and isolated test storage.
An 8/10 target is an acceptance goal, not a claim of achieved quality.

## Order and acceptance tracking

| ID | Work | State |
| --- | --- | --- |
| P0-01 | No automatic unsandboxed retry | Implemented; 19 targeted tests passed, full regression pending |
| P0-02 | Filesystem isolation | Pending |
| P1-01 | Startup/authentication boundary | Pending |
| P1-02 | Accurate safety documentation and release | Pending |
| P1-03 | Unified host/spawn Run, cancellation, events | Pending |
| P1-04 | Persistent downloadable artifacts | Pending |
| P1-05 | Shared execution budget | Pending |
| P1-06 | Provider contract verification | Pending; paid calls need budget |
| P1-07 | Recovery and backup acceptance | Pending |
| P1-08 | End-to-end task benchmark | Pending; paid calls need budget |
| P2-01 | Memory quality, context budgets, scale | Pending |
| P2-02 | Evolution evidence and judge calibration | Pending; live evidence required |
| P2-03 | Capability/version/provenance documentation | Pending |
| P2-04 | Dependency and test infrastructure | Pending |
| P2-05 | Behavior-oriented module boundaries | Pending |
| P2-06 | Loading, empty states, steps and artifacts UI | Pending |
| P2-07 | Voice and native desktop acceptance | Pending; physical checks explicit |
| P3-01 | Versioned recipes and bounded collaboration | Pending; after Run/artifact/budget |
| P3-02 | Controlled browser workflow (selected first) | Pending; cross-platform later |

## Verification log

- Baseline audit: 3912 backend tests and 1669 frontend tests passed on the same
  commit, recorded separately on 2026-09-13. This is not post-change evidence.
- P0-01 adds behavior tests for attacker-controlled stderr and for a backend
  claiming availability but returning no execution wrapper.
- P0-01 targeted suite: 19 passed, 1 non-macOS-path skip on macOS; Ruff and
  whitespace checks passed. This does not resolve the separate filesystem issue.

Do not mark an item complete solely because code exists or a mocked test passes.
Release only the verified scope and clearly identify unverified features.
