# Eight-case additive retest — actual outcomes

Frozen executable source: `470c713735f1661c54941da55975eb0bf881c605`.
This report is later than the tested source; subsequent offline fixes are not
represented as tested live. The original failed baseline and old ledgers remain.

## Authority and cost

User explicitly approved an independent additional **36 requests / US$5** for
these eight cases. Authorization ID:
`arslan-stable-0140-repair-primary-20260924`.
Evidence directory (local, not uploaded):
`../stable-0140-retest-evidence-20260924`.
The frozen contract links the previous contract and 31-request ledger by hash.
The older 32-call pilot also remains separate.

Actual new consumption: **30/36 requests**, **US$3.00 reserved**. Sum of recorded
peak-rate token estimates: **US$0.1131012**, not an invoice or a refund of reserved
funds. Pricing was verified on the same UTC day from the provider's official
pricing page; requested `deepseek-v4-flash`, served `DeepSeek-V4.1-Flash`.
No automatic failed-case retry occurred. Six globally unused slots do not reset
the registered per-case limits or authorize an unregistered retry sweep.

## Reviewed outcomes

| Case | Calls | Actual result | Acceptance disposition |
| --- | ---: | --- | --- |
| D1 | 1 | Real attachment API preserved physical page inventory. Answer correctly located source facts and distinguished page 2's absent native text from a missing/blank page; no claimed OCR or visual inspection. | Core passed. |
| D3 | 3 | Actual `totals.csv` written and reopened: USD 12.00, CNY 23.50. Missing amount stayed unknown and refund was retained. Final prose incorrectly said six complete rows (five) and called a data row a header. | Not fully accepted; artifact arithmetic passed, ancillary factual claims failed. |
| M2 | 2 | Proposed preference excluded, confirmed green included. Final response included an unexecuted XML `ask_user_choice` call and a placeholder instead of the requested useful brief. | Failed final-answer quality; confirmation boundary passed. |
| R1 | 6 | Three pinned sources fetched; `comparison.md` written and reopened. Repeated source reads and protocol correction consumed the case cap; final answer absent (`stable_budget_exhausted`). | Failed delivery; report existence is not overall success. Semantic review not completed. |
| R2 | 4 | Both real, conflicting abstract claims retained, dates and source scope separated, no invented winner; report saved/reopened. H0 values, quoted uncertainty convention and author-attributed tension checked against actual extracted abstracts. | Core passed with wording caveats: the broad model-dependence sentence should stay tied to its specific parameter context; awkward Chinese classifier for SN hosts. Not a review of full papers. |
| R3 | 3 | Pinned README comparison saved/reopened, version-specific architecture/install differences supported, commit dates distinct from unknown release dates. README omission explicitly not proof of removed APIs; compatibility remains unverified. | Core passed. Speculative branch interpretation in final prose is labelled, not independently verified. |
| R4 | 5 | Both full bilingual README texts fetched; report saved/reopened. Further repeated reads exhausted cap before final answer. | Failed delivery; semantic review not completed. |
| M4 | 6 | Real process exit 73 after saved/reopened three-line source-only brief; recovery idempotent and waiting for explicit resume; resumed response correct. Hash/inode/mtime unchanged, exactly one successful write, same cumulative task budget. | Core process-recovery passed. Not native UI recovery or an interrupted/uncertain write experiment. |

R2/R3 source-specific conclusions apply only to the frozen inspected materials,
not a new claim about current upstream software or scientific consensus.
All raw result files retain their original `quality_status`; this dated review
adds conclusions without rewriting outputs or hiding failed attempts.

## Subsequent offline repair, not live-certified

1. Reject XML-shaped tool-call text just like textual JSON protocol. It is never
   parsed for execution; existing bounded native correction/plain-answer handling
   remains under runtime budgets. Tests cover repeated malformed XML, no tool
   dispatch, no streaming leak, and ordinary markup preservation.
2. Remove contradictory legacy host guidance saying files cannot be generated
   directly and budgets reset every turn. Available authorized tools and actual
   successful results determine file claims; resumed cumulative budgets remain
   authoritative. Prompt wiring is not semantic proof.
3. Exclude only `source.retrieved_at` from web-extract progress fingerprints.
   Identical fetched evidence no longer looks novel because its clock changed;
   actual receipts remain untouched, and changed text/URL/scope remain novel.
   This does not by itself solve history eviction or prove R1/R4 complete.

Scoped offline verification after these repairs: 41 tool-loop tests, 17
grounded-answer/cache tests, and 20 runtime-policy/fresh-batch tests passed
(78 total); Ruff passed on changed Python files. No paid retest of these later
repairs occurred and no full CI/signing result is claimed.

## Remaining finite work

- R gate: resolve D3 explanation accuracy, M2 useful final answer, and R1/R4
  completion without refetch churn; review report claims, not just tool asserts.
- Native/package gates remain open as documented in the exit plan. Do not tag,
  claim release-ready, replace a real installation, or Publish on this evidence.
- Paid calls stopped after the registered sweep. Source changes invalidate its
  frozen identity for future reservations by design. Any follow-up experiment
  needs a separately frozen, explicitly authorized scope; no best-of-N reruns.
- `arslan-2` is paused. No periodic wakeup loop or new beta was started.
