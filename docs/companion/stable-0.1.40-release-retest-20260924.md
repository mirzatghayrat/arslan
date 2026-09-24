# Shared 60-request / US$6 release acceptance grant

Round 4 (`8d066969`) failed both cases without writing. Low-effort thinking
still consumed all 8192 output tokens as reasoning, leaving no critique content.
Six calls with usage receipts; cumulative 26 reserved slots / US$2.60. Do not
repeat low/high thinking review. Round 5 restores the only observed working
JSON mode (non-thinking), now with the round-4 factual-vs-stylistic distinction
rules and pre-reservation task admission. Same inputs, caps and factual criteria.

Native v11 on backend/web `8d066969`: persisted synthetic host conversation
opens Run #1 through its new result button; work-panel preview displays exact
CANARY-V10-ONLY Markdown with matching d43060cd…f60b6a9b hash. A source-link click
had no observed destination tab/window: Markdown used target=_blank rather than
the existing native external-link command. New repair routes external clicks
through the existing HTTPS/maintenance gate and supplies six-locale failure
notices; 14 link/result-entry tests, TypeScript and web build pass. Internal
paths stay internal. No new browsing permission or gate bypass is introduced.
Rebuilt native link verification is pending. Both native test processes exited
normally; no real installation/profile was changed.

Latest: round 3 (`1fb1c55f`) failed R1 at the unchanged 128k product token
ceiling, before delivery; R4 was blocked by HALT without a call. Eight local
reservations (seven usage receipts plus one full-charge budget-stop disposition),
20 cumulative reservations / US$2.00. Critiques included false-positive stylistic
objections (faithful translation, selective examples); not every anchored model
objection is factually valid. No R pass is claimed.

Round-4 repair switches ONLY bounded official-DeepSeek critique to documented
low thinking effort (same model/cap), with explicit no-stylistic-objection rules.
Normal task mode and the 128k product budget are not increased. New-round
admission checks task exhaustion before reserving an API slot. Previous slots
are never refunded. R1/R4 inputs and actual factual acceptance stay unchanged.

Native synthetic conversation exposed a missing result entry for main-assistant
history messages: run ownership is persisted but only specialist messages had a
RunReplay button. Added the same existing result viewer entry for a positive,
persisted host run in all three styles; streaming/temporary messages are excluded.
13 focused frontend tests and TypeScript pass. Native revalidation is pending.
The fixture is not a generated model result; old native process exited normally.

Offline legacy acceptance tests were still bound to a historical input/checker
freeze and failed after already-recorded stage-2 repairs. Disposable unit-test
contracts now bind current unit inputs; original paid manifests/ledgers remain
unchanged. Source/input mutation rejection stays tested. This does not certify
the historical baseline against today's source or alter live acceptance results.

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

Round 2 actual result on `e747315b`: both cases stopped without writes, 3 calls
each, all six response usages accounted. Cumulative 12 reservations / US$1.20.
Non-thinking critiques returned usable JSON, but one inexact quotation caused
the whole mixed list to be rejected, discarding separately anchored objections.
Do not count this as task success. Raw drafts and critique responses are retained.
Registered round-3 repair admits only individually exact claim/source pairs;
mixed valid/invalid lists remain blocking objections, and a wholly rejected
nonempty list remains unavailable, never a false empty-list pass. Criteria and
public input bytes stay unchanged. Guidance distinguishes factual contradictions
from harmless summary omissions/rounding; critique remains fallible.

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
After staging the locked standalone runtime and invoking the same probe with a
clean PATH, all 65 checks passed, including sandbox denial/CSV/PNG and packaged
OCR. This remains the `81b38b53` ad-hoc development bundle, not source e747315b
or the final signed candidate. The earlier two failures remain above.
