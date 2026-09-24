# Shared 60-request / US$6 release acceptance grant

User explicitly approved: “批准：最多 60 次／US$6”. Old pilot and repair
ledgers remain separate and immutable. This grant permits separately registered
repair rounds, not automatic retry of failed paid requests. Canonical cumulative
ledger: `../stable-0140-release-evidence-20260924/budget.jsonl`.

## Round 1 — failed, retained

Source `81b38b53`, frozen original R1/R4 inputs and criteria, local allocation
12 calls each. R1 was interrupted by pytest's inherited 120-second whole-test
timeout. R4 was blocked by the resulting HALT **before** a provider call.
Six reservations remain charged, US$0.60, not six successful responses.

Responses 1–5 have provider usage receipts. Reviews 3 and 5 returned empty
content with 8192 completion tokens, all reported as reasoning tokens. No usable
critique was produced; no reviewed report or R-gate pass is claimed. Request 6
was cancelled without a response/usage receipt. Its distinct abandonment record
retains the full US$0.10 and unknown actual usage; it is NOT an accounted usage
estimate or invoice. Original admitted payload limits (<=200k input bound,
8192 output) and frozen peak rates imply <=US$0.0698304, within that retained
reservation. HALT and original round files are not removed or resumed.

## Registered repair for round 2

- Raise this opt-in multi-call test's outer timeout to 600 seconds; individual
  provider and task budget limits remain intact.
- On unavailable/invalid critique, stop before writing and before another model
  call. Six localized notices explain the incomplete result and no auto retry.
- Only the tool-free bounded critique at the official DeepSeek endpoint uses
  documented `thinking: disabled`, same configured model and output cap. Normal
  task requests and other providers are unchanged. This is an explicit mode
  change, not a hidden model swap. Exact source quotes still must validate;
  model objections or absence of objections are not factual certificates.
- Cross-round accounting accepts an audited cancelled-request disposition only
  after verifying its original payload hash, limits, rates and cancellation
  marker. The entire slot remains consumed, with no claimed refund or usage.

Provider specification checked 2026-09-24:
https://api-docs.deepseek.com/guides/thinking_mode/
https://api-docs.deepseek.com/quick_start/pricing/

Offline: 14 focused review, mode-scope and master-ledger checks passed. They
prove execution/accounting behavior, not R1/R4 factual quality. Round 2 must be
frozen separately before calls; no final source CI/tag/release yet.
Expanded mixed-path invocation had 36 passes and 28 fixture-discovery errors
(`execution_db` not found in runtime-message tests). Running that module alone
passed all 31 cases. Preserve the collection issue for final integration; do not
claim the combined command passed. Ruff and diff checks passed.

## Development bundle check (not final P gate)

Built backend from `81b38b53`; reused the earlier isolated native shell whose
Rust/web source is unchanged. New copy only, no `/Applications` replacement.
Bundle self-test and packaged-file audit pass (15 import modules, web assets,
no bundled database/secrets). Fresh-install probe: 60 pass, 2 fail. The known
development copy omits the standalone compute runtime; this host also has
Tesseract on PATH, so the probe cannot establish packaged-only OCR. Preserve
these failures; this is neither signed/notarized release evidence nor a P pass.
