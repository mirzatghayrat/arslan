# Acceptance evidence: engineering versus model quality

Passing deterministic tests proves the exercised contracts, not an 8/10 agent.
No paid model evaluation or independent human calibration was performed in the
2026-09-14 reliability work. Do not substitute test counts for task success rates.

## Reproducible zero-cost contract suite

`uv run python -m scripts.acceptance_contracts --output /path/to/new-results`
runs 30 fixed behavior contracts with deterministic provider substitutes. It
executes real storage, cancellation, artifact export, recipe scheduling, backup,
permission, context and retrieval code. The browser transport and Gemini API
are mocked; the Python artifact case uses the actual local sandbox on macOS.
These are **not 30 natural-language end-to-end tasks with a real model**.

The output folder must not already exist. It contains pytest logs, JUnit and a
JSON report with commit/dirty status, catalog and test source hashes, platform,
configuration, per-contract timing/status/reasons and zero external model cost.
Missing/skipped tests are not passes; one failed parameter fails its whole
contract. Temporary application storage is removed after the run. Fixtures use
synthetic keys; parent provider credentials are not passed into the test process.

## Judge reliability

The pairwise judge runs both output orders, with each arm's trace evidence moving
with its output. A dimension gets a winner only if both orders agree. Malformed
dimension shapes or winner slots degrade to an all-tie verdict. Margins are finite
and bounded to 0–10, reasons remain strings, and any dimension/overall disagreement
marks position sensitivity. These are parser and aggregation guarantees, not
evidence that a model judge agrees with users.

The old `scripts/r1_compare_judge_probe.py` is retired and refuses to call a
provider. Its obsolete better>=1 gate, tiny sample, and a supposedly better answer
containing unsupported sales figures made its “usable” conclusion invalid.

## Required live comparison before a quality claim

1. Freeze at least 30 task inputs, expected deliverables, authorized tools/data,
   and factual ground truth before running. Include research, file production,
   code execution, multi-step collaboration, memory recall, refusal and recovery.
   Keep training/proposal tasks separate from held-out acceptance tasks.
2. Compare three arms using the same provider/model version and request limits:
   baseline without adaptation, static memory, and proposed evolution. Freeze
   arm configuration hashes, memory snapshots and skill revisions. Randomize
   arm display names and order; do not expose treatment labels to judges.
3. Save commit, model identifier, sampling settings, task/arm IDs, wall time,
   actual provider usage/cost (or explicitly unavailable), tool trace, stop reason,
   durable Run ID and artifact hashes. An output claiming a file exists must
   have a downloadable file that opens and meets the task's required contents.
4. Score completion, factual support, identity and permission compliance against
   task-specific criteria. A permission violation or fabricated delivery is a
   hard failure, regardless of eloquence. Missing evidence is not a success.
5. Have independent humans label a calibration subset including ties, shorter
   correct answers, longer unsupported answers, partial artifacts and blocked
   tools. Report judge-human agreement and disagreement examples. Inspect both
   orderings and retain degraded-judge counts separately from genuine ties.
6. Report per-arm success rates, paired differences, sample sizes and uncertainty;
   do not silently discard failures. Respect the production replay gate's current
   thresholds from `server/services/replay_gate.py`, not a copied stale formula.
   Passing the gate only permits a proposal; promotion remains explicit.

Before live execution, the maintainer must approve the provider, exact model,
maximum spend, permitted external writes and the task corpus. Provider-side spend
caps remain necessary: application token budgets are not exact currency ceilings.

## Native desktop checks still requiring a person/device

| Scenario | Acceptance criterion | Current evidence |
| --- | --- | --- |
| First launch with microphone denied | Clear denial/recovery guidance; no stuck recording | Physical check pending |
| Built-in microphone, voice response | Capture/transcript/playback completes with stop control | Physical check pending |
| Bluetooth connect/disconnect mid-recording | No crash, stale capture or unexpected playback | Physical check pending |
| Sleep/wake during recording or response | Clear recoverable state; no duplicate send | Physical check pending |
| App quit/relaunch after partial task | Stored interruption and durable outputs available | Backend tests; signed-app manual check pending |
| Signed fresh install, Python CSV/chart | Bundled interpreter imports and creates a real image | Local relocated runtime passed; release gate pending |

Do not turn on a user's microphone, change audio routing, sleep their computer,
or overwrite their app/data merely to mark these rows passed.
