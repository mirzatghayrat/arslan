# Stable 0.1.40 acceptance contract — revision 1

This is the independent budget authorized on 2026-09-23, not a reset of the
stage-2 pilot (32 requests). No live calls are enabled by adding this contract.

`stable-0140-acceptance.json` freezes all twelve original IDs, original input
definitions/generators, previous runner bindings, semantic review criteria and
per-case ceilings totaling 36 requests. The reference runner is historical:
**do not run its paid tests under a new output directory to spend this grant**.
It does not yet use the stable ledger. Preserve original failed outputs.

Canonical evidence directory is `stable-0140-live-evidence-20260924` beside this
worktree. `python -m evals.companion.stable_budget --initialize` creates its
`budget.jsonl` exclusively once. Subsequent status reads omit `--initialize`.
A missing ledger during reservation fails; never recreate/delete/relocate it
to obtain extra requests. Failed/interrupted calls keep their reservations.
The ledger header pins this contract's hash. Contract amendments after creation
require an explicit reviewed accounting migration preserving every reservation,
not overwriting the header or making a fresh budget.

## Before the first real call

1. Complete a stable runner that reserves in this canonical ledger before
   **every** outbound request (tool iterations, summaries and retries included).
   Keep no automatic retries and retain exclusive per-attempt output files.
2. For each case create an immutable `<ID>-preflight.json` with `case`,
   `contract_sha256`, `status: ready`, and `inputs` entries `{path, sha256}`.
   Paths stay beneath the evidence directory; hashes cover exact bytes.
   Archive actual document inputs and pinned public bodies, plus prompt/checker
   identity, source SHA, dates, URLs and source-receipt expectations. Do not feed
   review notes/oracles to the model or substitute supplied excerpts for reads.
3. R2 additionally needs `public_same_scope_conflict_review` describing both
   incompatible claims, dates and identical scope, linked to the frozen public
   inputs. A nonempty field is only bookkeeping: a reviewer must establish that
   the conflict is genuine. **R2 remains blocked today**; the unit-test marker
   is synthetic and must never be promoted to public evidence.
4. Read current official pricing and the configured primary identity without
   exposing credentials. Verify endpoint/model, no additional paid path, and a
   conservative request bound. The helper currently accepts only an explicitly
   reviewed DeepSeek official-endpoint pricing snapshot from the same UTC day;
   this does not itself verify an online price. If primary/provider or pricing
   changed, stop and review the guard rather than assuming the old quote.
5. Payload limit: 100,000 serialized UTF-8 bytes, 8,192 output tokens; budget
   conservatively uses 200,000 input tokens. Reserve US$0.10 without refunds;
   the calculated peak-price ceiling must fit. 36 requests reserve US$3.60,
   below the US$5 authorization; unused money does not authorize more calls.
6. Runner must persist actual usage and source/output evidence, halt on unknown
   or out-of-bound usage, and perform no paid continuation after a HALT. These
   are required runner checks, not guaranteed by the offline bookkeeping module.

## Review and progress

Input freeze, successful execution, answer usefulness, native interaction and
signed-package evidence are different columns. Source receipts alone do not
prove factual entailment. Test counts are not the twelve-task result.
Before marking a task passed, review each criterion against the saved actual
output and open the artifacts. Record a supported partial read honestly, but do
not call an excerpt-only comparison the complete-source acceptance run.

No public sources were fetched and no pricing/profile/credentials were read in
this bookkeeping batch. R1/R3/R4 complete-source acquisition and R2 selection
remain next. D/M fixtures reuse their frozen historical definitions; native
attachment, memory and process-recovery interactions remain gate N/U work.

Follow-up on 2026-09-24: complete public bodies are archived and R2's genuine
public tension inputs are selected in the additive canonical preflight. See
`docs/companion/stable-public-input-review.md`; the original contract/ledger is
unchanged. `stable_live.StableAdapter` supplies the guarded one-shot request path,
but host-runner integration and current pricing/primary preflight remain required.
R1/R4 full-source reading still exceeds the production reader's initial cap.
