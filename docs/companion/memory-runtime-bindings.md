# Multi-turn memory runtime bindings — partial engineering evidence

`tests/server/test_memory_multiturn_runtime.py` now has 33 synthetic runtime cases
covering aspects of 23 catalog scenarios. This is not 60 passing scenarios, a
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
| M05-01/04 | Advancing the context-selection clock changes effective/expired eligibility in subsequent host requests | Version-specific source revalidation and historical factual interpretation |
| M06-01/02 | Paused/deleted content is absent from later host requests; pause preserves history and can be restored | Vector/index rebuild, old summaries and backup restoration (separate tests exist; not covered here) |
| M07-07 | Local-only memory stays stored but is absent from a synthetic cloud-destination request, even with task-level cloud permission | Sensitive-item acknowledgement UI and a real network capture |
| M07-01 | Explicit synthetic credential-save requests are rejected at task admission before host/remember execution; no task/message/run or ordinary memory remains, and a different conversation's prompt/receipt contains no such memory | Detection of every credential shape, UI presentation of the refusal and redaction of unrelated historical sources |
| M03-06 / M08-02 | Saved report preferences stay out of a code-patch request; saved design preferences stay out of arithmetic requests in six locales; related subsequent tasks can still retrieve them | General semantic relevance, arbitrary paraphrases and generated-answer quality |

## Known remaining coverage and implementation gaps

All other catalog scenarios still need explicit multi-turn bindings at their
appropriate runtime boundary. Do not count existing single-operation tests as
complete scenario coverage. Model behavior needs separate authorized evaluation;
scripted answers above are not evidence of quality or uncertainty calibration.

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
