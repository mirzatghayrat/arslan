# Two-case retest — no release clearance

User approved an independent 12 requests / US$1.20 with “确认 继续”.
Frozen tested source: `60e779ba6d1caed9aa10bba5ce59f92a9b446ae1`.
Evidence: `../stable-0140-two-retest-evidence-20260924` (local, not uploaded).
Same source inputs and original semantic requirements; one registered attempt
per case, no automatic repeat. Parent 15-call ledger preserved and hash-linked.

## Execution and accounting

R1: 4 requests. R4: 4 requests. **8/12 total**, US$0.80 reserved.
Recorded conservative peak-rate estimate **US$0.0636471**, not an invoice.
Pricing re-opened on 2026-09-24 at the official provider page. Configured legacy
Flash alias is served/billed as V4.1-Flash; cache-miss peak input/output rates
0.30/1.20 per million tokens used conservatively. No retries or budget reset.
Four unused slots are not authorization for another failed-case attempt.

Both execution tests completed in 81.56 seconds. Each fetched the required full
sources, saved `comparison.md`, reopened it and delivered a final response.
This is delivery evidence, not semantic acceptance.

## Review of actual report and final response

| Case | Improvement | Still blocks acceptance |
| --- | --- | --- |
| R1 | No longer excludes all three projects from document/research capabilities or calls the 15k README shorter than the 10k README; actual file and final answer delivered. | Report and final answer say benchmark sample size is absent, while the same report and frozen English source lines 716/723 state an average across 25 tasks. Number of tasks is known; repetition/uncertainty details are a separate gap. The undifferentiated absence claim is not supported. |
| R4 | Now includes and compares both English V2 and Chinese privacy exclusion lists instead of falsely declaring an English list absent. | Saved report section 1.2 says switching to OpenAI/Ollama means leaving the machine. The quoted passage only offers alternate embedding providers and does not establish endpoint location. Final summary is more cautious, but the actual saved artifact still contains this unsupported privacy-boundary conclusion. |

No claim that all other report sentences have been exhaustively certified.
The installation/Node statement is **not** counted as a new failure: the frozen
English installation table expressly requires Node to build the source Web UI.
Preserve source-specific distinctions, including contradictory/ambiguous text,
rather than inventing a failure from a remembered older reading.

## Evidence hashes

- Contract: `742d1a2fa4e4ef4154cb0fb127194789ebcf3ae1fd0538c28f4ccb78c5e7509d`
- Ledger: `c11d339d0457fac252fe4351fa802f45cc8acd0f2549296c0016e7df824f0b0a`
- R1 result: `6d6956dc6585067730c964ea6a3a362ed64246fcc61e64852af208f727ff518e`
- R4 result: `48fef43d00575a1e4027ddc2751965b8d8adf106ef0879734190d03d74746ded`

## Decision and next repair boundary

R remains open for R1/R4. Do not tag, promote a beta, claim stable readiness,
or treat execution assertions as factual accuracy. No installation/main/Latest
change. Automation remains paused. Native/package gates remain independently open.

The latest shared prompt-only repair did not reliably enforce the requested
evidence boundary. Do not request another identical paid rerun or silently add
case-specific expected answers to product prompts. Next repair must address
claim-to-passage review of the **saved artifact**, not only its final summary:
preserve known measurement scope separately from unreported details, and avoid
deriving deployment/privacy properties from provider names. A deterministic
quote-match alone also cannot prove that an inference follows from the quote.
Any additional reviewer/model calls must be explicitly budgeted and frozen;
do not introduce hidden per-task paid verification or silently change the model.
Unpaid native work can proceed, but cannot clear this research-quality blocker.
