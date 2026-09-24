# Stable 0.1.40 — close the measured gaps

Current: [cumulative release retest](stable-0.1.40-release-retest-20260924.md).
57/60 requests reserved, US$5.70 retained (not invoice). R1 core passes with
caveat; R4 remains blocked after the separately frozen 16k critique experiment
returned no content. Production cap increase reverted. No further paid retry
registered; earlier budgets and pending-approval text below are historical.

Newest: [two-case review](stable-0.1.40-two-retest-20260924.md), source 60e779ba,
8/12 calls, US$0.80 reserved, US$0.0636471 peak estimate (not invoice). Both
execution paths pass but R1/R4 remain semantically unaccepted. Do not repeat
the same paid prompt-only experiment or silently change models. Earlier grant
requests below are historical, not pending approvals for these completed calls.

Latest: [four-case actual review](stable-0.1.40-four-retest-20260924.md).
User approved 22/$3; 15 calls executed on 83f29f4e. D3/M2 core passed with
recorded caveat; R1/R4 execution recovered but saved-report factual comparisons
remain unaccepted. A later shared guidance repair is offline only. Two-case
12/$1.20 follow-up permission requested; no paid retry authorized by this text.
Earlier proposal/status paragraphs below are historical checkpoints.

## Four remaining cases — repair candidate after user continuation

No additional paid calls in this batch. D3/M2/R1/R4 remain open until reviewed
real outputs on the changed source, not merely these deterministic checks.

- D3: CSV extraction now supplies logical-record numbers, physical-line ranges,
  total logical records (including any header), and empty-field record count.
  Every cell is retained as JSON text; no inferred header, arithmetic oracle or
  currency-specific expected result enters production code. Multiline/quoted
  cells and negatives are covered. Malformed CSV falls back to unchanged raw
  text; bounded extraction still reports truncation. The frozen synthetic
  input bytes and acceptance totals are unchanged. Checker revision 2 records
  the former hash and reconstructs every cell before the same assertions;
  original paid preflights/results/ledgers are untouched.
- M2: clarification guidance is conditional on actual tool availability and
  distinguishes a style brief from writing a whole report. No irrelevant topic
  question or invented placeholder is required for a format-only request.
  The earlier XML non-execution guard remains active.
- R1/R4: successful web-evidence turns retain a bounded 96k rolling history
  instead of dropping a <=96k fresh batch back to 64k immediately after a save.
  Other turns remain 64k; this is not permanent source pinning. Native call JSON
  is no longer replayed as assistant prose or duplicate large write bodies;
  real arguments remain in traces/journals. Opaque provider-content pairs remain
  unchanged. Compaction guidance no longer advertises unavailable task_progress.
  A four-request offline fixture proves three 23k sources survive save/readback
  with a 30k write payload, without re-fetch or textual-call imitation. This
  may increase per-request context; actual cost/completion impact is unmeasured.

Verification: 68 input/retention/grounding/cache/runtime-policy checks passed;
39 host/native/Gemini/protocol checks passed; the 41 tool-loop checks also passed
on the changed loop in the initial targeted batch. Ruff and diff checks passed.
Initial CSV representation assertions and then the checker-hash fence failed
as expected after representation changes; both failures are retained in task
output. The updated checker verifies equivalent source cells, not weaker totals.
No full CI or release gate closure is claimed.

Proposed follow-up: one registered attempt each, R1 <=8, R4 <=7, D3 <=4,
M2 <=3 = 22 requests, independently capped at US$3. User approval requested;
not yet granted at this checkpoint. Previous new grant remains 30/36 requests,
US$3 reserved, peak estimate US$0.1131012 (not invoice). Its unused six slots
do not become a reset failed-case allocation. Freeze candidate, inputs and
checkers before execution; no paid failure auto-retry or best-of-N selection.

Latest additive sweep: [2026-09-24 actual outcomes](stable-0.1.40-retest-20260924.md).
The new grant was approved and used 30/36 calls; D1/R2/R3/M4 core criteria now
have retest evidence (R2 retains wording caveats). D3/M2/R1/R4 remain open.
Historical budget/decision paragraphs below describe the pre-sweep checkpoint,
not a still-unused grant or permission to retry.

Checkpoint: 2026-09-24, after all twelve stable baselines. This is a finite
repair/retest plan, not a new feature milestone or permission to rerun paid cases.
The original contract, inputs, outputs and ledger remain immutable. The release
gates and product scope in `stable-0.1.40-exit-plan.md` remain authoritative.

## Eight unaccepted cases are not eight identical product defects

| Case | Measured blocker / qualification | Repair or retest prerequisite | Unchanged acceptance |
| --- | --- | --- | --- |
| D1 | PDF text omitted the empty page; model called it physically missing. | Page inventory repaired offline. New input must use the real attachment entry point and explicitly record its difference from the old low-level helper. | Correct facts/page locators; no invented page content or visual inspection. |
| D3 | File-call arguments omitted; no CSV. Numeric missing value also acquired an unsupported sign/bound. Old harness shortened tool descriptions. | Typed read/write schemas and numeric/row guidance repaired offline. Use production descriptions and real write/read artifact checks. | USD 12.00 and CNY 23.50; missing amount remains unknown, refund retained, no conversion. |
| M2 | Confirmation boundary worked, but the requested one-line style brief gained invented decorative project details. | Tighten brevity and source-only behavior without inserting the case's expected answer. | Unknown before confirmation; confirmed preference afterward; useful brief without fictional project facts. |
| R1 | Full sources reached model after fresh-batch repair, but textual malformed write-call leaked instead of producing a file. Also unsupported permission exception and overbroad offline-fit inference. | Output guard now permits bounded native correction with original permission gates; source-scope repair/review still required. | Same comparison fields, supported claims, labelled inference, actual saved/readable result. |
| R2 | Preserved real conflict but invented an uncertainty convention and inferred methodology from reporting detail. | Source-grounding rule must distinguish explicit support from plausible domain knowledge. | Retain both claims/dates/scope, no invented winner or statistical attribution. |
| R3 | Reader treated raw Markdown as HTML and lost installation text; answer overclaimed incompatibility. | Plaintext reader repaired offline. Compatibility must remain unverified unless inspected evidence demonstrates it. | Version-specific changes, distinct commit/release dates, no claimed tested compatibility or incompatibility. |
| R4 | False absence claims despite both source texts being available. Later history eviction plus overly strict no-refetch harness and short cap prevented final delivery. | Refetch harness corrected for future attempts; review bilingual full-scope evidence before asserting absence. Do not resolve source disagreement by assumption. | Accurate attributable bilingual comparison, correct locality scope, saved result and final answer. |
| M4 | Real process recovery retained file/source/budget and did not repeat writes. One remaining call checked results; the next final-answer call hit the five-call harness ceiling. | Register a separately budgeted recovery retest, not an automatic continuation of the failed phase or a product replay fix unsupported by evidence. | Explicit resume, same cumulative budget, no repeated write, retained useful source/result and reviewed final answer. |

D2/D4 core passes retain their caveats; M1/M3 core passes remain recorded.
Recheck affected paths if later changes invalidate their evidence. Do not rerun
unaffected expensive cases merely to increase a test count.

Offline guidance checkpoint: source `2ed10c995fb2c443dbf6329e618a9718ffc884f4`
implements the generic brevity/evidence-scope rules needed by M2 and R1–R4 in
both host and synthesis prompts, removes conflicting forced-decisiveness language,
and frames synthesis notes as untrusted material. Wiring and execution regressions
pass; this does **not** resolve the semantic acceptance findings by itself. The
table's source-quality requirements still require actual output review on the
registered additive retests. No original outcome or input has been rewritten.

## Order and stop conditions

1. Close the reproducible execution gaps with scoped offline regressions. For
   protocol correction, both malformed and valid textual calls must remain
   non-executable; only a subsequent native call can enter the existing gate.
   A declined write stays declined, and correction cannot extend the request cap.
2. Review the generic answer contract for unsupported absence, compatibility,
   statistical and locality claims, and unsolicited example facts. Keep facts,
   source claims, inference and unknowns separate. Do not put project-specific
   answers or evaluation oracles in product prompts. Prompt-string tests alone
   cannot establish output quality.
3. Freeze one additive candidate-bound retest per failed ID. Record source SHA,
   exact runner/input/checker hashes, what changed and why, request allocation,
   and cumulative accounting **before** calls. Preserve failures separately; no
   best-of-N selection or post-result weakening of criteria. Stop on exhausted
   authority, uncertain price/usage or unresolved safety/data-loss findings.
4. Complete isolated native core flows and packaged upgrade/recovery evidence.
   Finish candidate review and same-SHA CI/signing/packaging only when all five
   release gates actually close. No intermediate beta is required.

## Paid-call decision still required before additional retests

Current independent authorization: **31/36 calls**, **$3.10 reserved**, estimated
peak usage **$0.0805866** (not an invoice). Old 32-call pilot is separate. Money
and request ceilings are different: low estimated cost does not authorize more
calls. Five unused global slots do not reset any exhausted case allocation.

The eight-case repair sweep cannot fit the five remaining calls: D3 alone needs
model-guided write/read/final, research cases require source reads plus delivery,
and M4 needs both initial and resumed phases. Do not quietly raise existing caps.
After source/runner readiness, request a bounded additional authorization or ask
the user to choose a smaller retest scope. Any new ledger must reference the old
one and keep prior consumption/outcomes, never disguise itself as an unused
replacement budget. No additional paid authorization is implied by this document.

Proposed planning envelope (not enabled): R1 6, R2 4, R3 4, R4 5, D1 1, D3 4,
M2 3, M4 7 = **34 calls**, at most one registered attempt per ID. Any spare
authorization would be held, not automatically used for retries. These ceilings
must be reviewed against the frozen runners before requesting/executing them.

This stage still targets stable 0.1.40, not completion of all v1.2 development.

## Read-only repair inventory — 2026-09-24

Source `b2b37ee0ea4a1a4de479337ade9d5ed8b3f0b4c8` adds an offline preparation
command, not a paid runner or new budget. It validates the original contract,
eight preflight identities and thirteen retained input entries against their
recorded hashes, copies unchanged acceptance criteria, and snapshots existing
runner hashes and the canonical ledger without writing to the old evidence tree.
Five isolated checks cover immutable accounting, no authorization/reservation,
exclusive output, original-tree refusal, and altered/escaping input identities;
Ruff passes. These are harness integrity checks, not product-quality results.

Private receipt:
`../stable-0140-repair-preparation-20260924/inventory-v1.json`, SHA-256
`5da133748651aa5de5353b020051322909afb7146226b6507004b6626d07ef9c`.
Canonical ledger SHA-256 remains
`20c988dcbcaf9977d268e6b1d880bbc8ba57d94aa1b41fa9593ef47b3049751a`:
31 requests, $3.10 reserved. No credential reads or model/network calls occurred.
All eight entries explicitly have `runner_ready: false`; authorization is null
and execution is disabled. The proposed 34 calls remain unapproved planning.

Two concrete dependencies must not be skipped: D1's historical document runner
still obtains text through legacy `ingest._extract_file`, so an additive runner
must consume the actual attachment extraction API response/page inventory;
the research/recovery runners still bind the old contract, case caps and ledger.
Changing an output directory would not establish independent authorization or
correct accounting. Preserve those historical runners/results and implement a
separately linked, reviewed retest path before freezing executable inputs and
checkers. This receipt freezes only a preparation snapshot, **not** a release
candidate or ready-to-run evaluation contract. The pending budget question is
unchanged; do not repeat it or infer consent from another heartbeat.

## D1 additive attachment adapter — 2026-09-24

Source `feb8922dfd98fd4b846d3af0417b078e6018ace5` adds
`stable_pdf_repair.prepare/save`. It reads the retained original PDF only after
preflight/contract/path/content checks, requires an in-process isolated REST
client and explicitly disabled native OCR, then posts the original 1,173 bytes
to the actual `/api/v1/extract` endpoint. The historical document runner and
failed model output remain unchanged. The request wording is unchanged; only
the context now contains the actual API response, without a hand-inserted
expected answer or page-specific oracle.

The unmodified endpoint returned 698 characters, untruncated, with three physical
pages, page 2 without native text, no visual-verification claim, and a body
identical to the old extracted source text. Nine isolated adapter checks passed
(including refusal of changed bytes, network clients, OCR-enabled scope and
invalid/partial API responses); the canonical retained-input receipt check also
passed. Ruff passed. The emitted private receipt is
`../stable-0140-repair-preparation-20260924/d1-attachment-v1.json`, SHA-256
`f20b571931eab0aa540c10259bd2e80d3a6cbd3ed1803e59c0f6b0058162a2a0`.
It binds the implementation/checker hashes and original PDF/preflight/ledger.
The old ledger hash is unchanged from the preceding inventory.

This closes the **offline D1 input adapter** dependency, not D1 semantic
acceptance: no model call, native interaction, paid runner, new grant or final
candidate freeze. `runner_ready` remains false. Independently linked accounting,
the executable host runner and reviewed real answer still remain. Other seven
retest adapters/criteria are not claimed ready by this batch. Do not regenerate
these receipts or repeat extraction checks as new progress. While the additional
grant remains unanswered, prioritize another distinct native core interaction
batch, such as synthetic memory deletion/restart, on a controlled-HOME clone.
