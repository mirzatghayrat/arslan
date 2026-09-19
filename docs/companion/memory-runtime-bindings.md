# Multi-turn memory runtime bindings — partial engineering evidence

`tests/server/test_memory_multiturn_runtime.py` now has 46 synthetic runtime cases
covering aspects of 30 catalog scenarios. This is not 60 passing scenarios, a
real-model score, or release approval. The catalog retains its uncompleted status.

The harness runs the real `scoped_turn` / TaskService boundary, user-message
persistence and source binding, host Run lifecycle, native tool loop, actual
RememberExecutor, activated v2 repository, working-history assembly, personal
context selection and persisted ContextReceipt. Later tasks have separate
conversation IDs and reload their trusted settings from the database. Assertions
inspect the outbound adapter system prompt, not merely recall-tool output.

Only the model adapter, tool-list discovery, unrelated knowledge retrieval and
team roster are substituted. The synthetic adapter emits predetermined tool
arguments and a deliberately ungraded answer. The harness enters the host answer
path directly: it does not prove router selection, natural-language consent
interpretation, model compliance, the transport UI, or actual provider delivery.
Trusted UI settings/actions are represented by database setup or repository calls;
their separate API/UI tests are not replaced by these cases.

| Scenario aspects | Runtime assertions | Still outside this binding |
| --- | --- | --- |
| M01-01/02/04/05 | Exact explicit content is saved; source resolves to actual first-turn user message; next task sends content and records its version | Natural-language extraction, correct language/sections/negative-rule compliance in generated output |
| M01-06 | Exact repeated content leaves one active entry and one injected reference | Semantic deduplication of paraphrases |
| M02-03/05 | Non-explicit inference stays proposed; trusted no-learning blocks persistence; neither enters next task | Recognizing all natural-language one-off and no-learning phrases |
| M02-06 | Trusted no-memory excludes content from actual host request without deleting it; later normal task can use it | UI interaction and natural-language setting changes |
| M02-01/02 | One-off report/design request reaches the current adapter; a scripted save attempt becomes only a proposal, the original active version remains unchanged, and a new task's prompt/receipt excludes the proposed rule | Real model obedience to the one-off instruction and semantic equivalence of arbitrary paraphrases |
| M03-01/03/05 | Opposite rules in distinct same-named projects stay isolated; unassigned task inherits neither; receipts exclude the other project's IDs | Output design fidelity, every source type, worker context and old write-grant invalidation |
| M04-01/02 | User-confirmed revision replaces prompt content with history retained; an inferred candidate cannot replace confirmed content | Model recognition of replacement intent and review-card interaction |
| M04-03/06 | A stale direct edit or stale second candidate confirmation is refused; a new task sends only the chosen current rule and records its exact revision; the original history remains intact | Concurrent UI interaction, natural-language intent and conflicts across distinct target entries |
| M04-08 | Dismissing an unconfirmed guess excludes it from later host prompts/receipts and retains the user's correction message; dismissing an older proposal cannot pause a newer confirmed revision | Automatic understanding of natural-language correction, actual review-card UI and real model behavior |
| M05-01/04 | Advancing the context-selection clock changes effective/expired eligibility in subsequent host requests | Version-specific source revalidation and historical factual interpretation |
| M06-01/02 | Paused/deleted content is absent from later host requests; pause preserves history and can be restored | Vector/index rebuild, old summaries and backup restoration (separate tests exist; not covered here) |
| M07-07 | Local-only memory stays stored but is absent from a synthetic cloud-destination request, even with task-level cloud permission | Sensitive-item acknowledgement UI and a real network capture |
| M07-07 additional matrix | Sensitive, cloud-eligible project memory enters actual host requests/used receipts only when both task cloud-memory and sensitive-item permissions are true; all four combinations retain the stored item | Natural-language consent interpretation, permission UI and actual provider transport |
| M06-05 | Restore quarantine removes an existing memory from the next host request and used receipt without erasing it; fresh user review restores later eligibility | Archive I/O/new-machine migration (separate frozen harness), missing-ledger UI explanation and model output |
| M06-07 | An actual host-generated receipt resolves its original revision through authenticated HTTP after a newer revision exists; deletion changes that same review to a content-free deletion marker; later host prompts/receipts and revision history contain no deleted memory text | Native review interaction, previously displayed UI text and unrelated historical user-message content |
| M06-03 | Deletion invalidates an old summary; actual compaction excludes pre-deletion source messages while retaining displayed chat, rebuilds from new eligible messages, and a later task excludes deleted content | Real summarizer behavior, arbitrary paraphrases and untracked external-source reingestion |
| M06-04 | An actual pre-deletion backup is restored using either a later imported manifest or automatic record selection from an explicitly supplied current installation; a new task bound to the restored DB sends no deleted text/reference, and a repeated save is refused | Trusted native UI import, packaged host-request capture and natural-language/model behavior |
| M07-01 | Explicit synthetic credential-save requests are rejected at task admission before host/remember execution; no task/message/run or ordinary memory remains, and a different conversation's prompt/receipt contains no such memory | Detection of every credential shape, UI presentation of the refusal and redaction of unrelated historical sources |
| M03-06 / M08-02 | Saved report preferences stay out of a code-patch request; saved design preferences stay out of arithmetic requests in six locales; related subsequent tasks can still retrieve them | General semantic relevance, arbitrary paraphrases and generated-answer quality |

## Known remaining coverage and implementation gaps

### Summary regeneration after deletion (2026-09-19, after `1668a547`)

The new M06-03 binding saves a rule via the real host path, adds a derived reply
and an old rolling summary, then deletes the memory. Display messages remain,
but the old summary is invalidated. New post-deletion turns are compacted using
the real `maybe_compact` and deletion-aware eligible-message query. A scripted
summarizer captures every input; none contains the deleted preference or old
summary, while the new task material is present. A subsequent host turn in the
same conversation uses the regenerated summary without deleted content and has
no used-memory reference. Receipt assertions select new identities explicitly,
not incidental database order.

The added case passed in **2.10s**, 45 deselected, one warning. JUnit:
`/tmp/arslan-memory-summary-deletion.xml`, SHA-256
`9de91477f0cbdea74bf31dce5f05ca9894b7178d8e090d9eaa24bee239f0afdf`.
Separately, history-deletion/repository regressions passed **24 tests in 2.48s**.
Lint/diff checks pass. These are incremental checks, not one complete 46-case
runtime invocation. No production code or catalog completion status changed.
M06-06's full external-source deletion/reingestion chain remains unbound here;
this test must not be counted as that scenario or as real summarizer quality.

### Historical receipt deletion (2026-09-19, after `a0c3dd4e`)

One new M06-07 binding uses a receipt persisted by an actual synthetic-adapter
host task, not a fabricated receipt. Authenticated in-process HTTP first resolves
the recorded old revision while a newer revision exists. Deleting the memory
then yields `status=deleted` and null content from the same review paths;
receipt listing contains neither revision's text. A new conversation's host
request and used receipt exclude both revisions, and stored revision contents
are erased. This is deletion of memory/revisions, not a promise to erase all
original conversation messages or previously displayed UI text.

The added case passed in **2.94s**, 44 deselected, one warning. JUnit:
`/tmp/arslan-memory-historical-receipt.xml`, SHA-256
`7ec0a7adf45dd8bfeb726fca8994de61ff7fd73bab3c46ed4d3a94d432567fdc`.
The existing `MemoryEvidence.test.tsx` selection also passed all 13 component
cases (1.25s), including safe deletion labels and ignoring cached deleted titles.
Its mocked API responses are separate component evidence, not a native browser
or end-to-end transport claim.
Lint/diff checks pass. The complete expanded 45-case file has not been rerun
in one invocation; preceding complete and incremental results remain distinct.
No production behavior or catalog completion status changed.

### Rejected guesses (2026-09-19, after `f97efae7`)

Two added M04-08 cases exercise an actual host-scripted remember attempt
without explicit save consent, a later user correction message, trusted
proposal dismissal, and an independent subsequent host task. The unconfirmed
guess is never injected; dismissal pauses it without inventing confirmation.
The user's exact correction remains in user-message storage and the proposal
has a dismissal timestamp. In the second case, a trusted newer revision is
confirmed before dismissing the old proposal: it stays active and the next
host request/receipt uses that exact current revision. This is not automatic
interpretation of correction language or a claim that dismissal creates a
new corrective long-term preference.

Both added cases pass in **9.07s**, 42 deselected, one warning. JUnit:
`/tmp/arslan-memory-rejected-guess.xml`, SHA-256
`24cd0987332b5fd1e798fab2ad6138739364358e732e1f69eba4723f34b5bb68`.
Lint/diff checks pass. The preceding 42-case full-file pass and these two
new cases are disjoint runs, not one 44-case invocation. No production code,
catalog status, account, model or user data was changed.

All other catalog scenarios still need explicit multi-turn bindings at their
appropriate runtime boundary. Do not count existing single-operation tests as
complete scenario coverage. Model behavior needs separate authorized evaluation;
scripted answers above are not evidence of quality or uncertainty calibration.

## Stale edits and conflicting candidates (2026-09-19)

Two new bindings cover M04-03 and M04-06 at the actual subsequent host-request
boundary. Both begin with a remembered rule and retain its history. One submits
a revision-1 edit after a trusted revision-2 edit. The other creates two host
proposals against the same target/version, verifies neither enters the next
task before review, accepts the chosen proposal and rejects the other as stale.
Later independent tasks contain only the selected current rule; every used
receipt includes the exact selected revision. Stale attempts add no revision;
the unaccepted proposal remains pending rather than falsely marked accepted.

The first two-case run failed only at the receipt assertion because the test
used `version` instead of the existing ResourceRef `revision` field. Product
behavior and policy were not changed. After correcting the field, the complete
expanded binding file passed **42 tests in 77.94s**, one warning. JUnit:
`/tmp/arslan-memory-stale-runtime.xml`, SHA-256
`5383d114334b37c8ea1a681b72ccb5eec6434759390117590c371f884130582d`.
Lint and diff checks pass. This adds two scenario aspects (27 of 60), not two
fully certified natural-language/UI/model scenarios. Catalog completion status
is unchanged. The separately running full backend regression was collected
before these two tests were added; do not include them in its case count.

The earlier zero-overlap injection bug now has a local relevance filter and
actual host-request regressions. See `memory-relevance.md` for the implementation,
explicit inventory behavior and lexical/cross-language limitations. The sampled
M03-06/M08-02 cases are now bound; this is not evidence that every paraphrase or
universal/domain-specific preference has been classified correctly.

These tests use an isolated temporary database, a synthetic configured model and
no real credentials. No model/network calls, account changes, publication or
installation are performed.

The complete binding file plus personal-context, memory-tool, model-locality,
shared-runtime and evaluation-contract regressions passed **112 tests** in
41.33 seconds. Ruff and whitespace checks passed. This focused run is not the
complete repository regression or the remaining scenario acceptance gate.

## 2026-09-19 follow-up

The unchanged production source at `a853cf8f` passed the full backend population
(4,904 passed, 14 skipped), including the earlier 29 bindings. Four new cases
were then added for M02-01/02 and two synthetic M07-01 credential shapes. The
first binding-file run had 31 passes and two failures: its credential expectation
incorrectly assumed execution would reach the remember tool, while the actual
task boundary already rejected the sensitive goal. The correction asserts that
stronger refusal and zero persisted task/message/run state; no product policy
was weakened. All four new cases then passed in 7.30s. Ruff and whitespace checks
passed. This is a disjoint follow-up, not a claim that the new 33-case file or an
expanded full suite was rerun in one invocation. No production implementation,
model, account, real input, or scenario-completion status changed.

## Restore quarantine and sensitive permissions (2026-09-19)

Five additional cases exercise four combinations of trusted cloud/sensitive
permissions and the real restore-quarantine service followed by a new task.
Assertions inspect every captured request and persisted used receipts, with
the stored item checked separately. The restore case also performs a fresh,
versioned user review and proves a subsequent host request can use the memory.
The focused five-case run passed in 6.65s; no production code changed. The
synthetic adapter does not contact a provider or grade a generated answer.

The complete expanded file then passed all 38 cases in 75.81s. Targeted lint
and whitespace checks passed. This is partial evidence for 24 scenario aspects,
not 38 or 60 completed catalog scenarios; catalog status remains unchanged.
