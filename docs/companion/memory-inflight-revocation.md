# In-flight memory withdrawal

The real-host synthetic-HTTP reproduction on `1d1be3c4` showed that deleting a
selected memory between model calls did not change the tool loop's cached system
prompt. A second serialized request contained the deleted body. Request-evidence
counters observed this faithfully but did not enforce withdrawal.

## Enforcement

Each live task now retains metadata-only dependencies: selected memory IDs and
versions, and the owner/project/domain/expert/locality/sensitivity read scope.
Host and worker selections share the task's dependency registry. Personal hits
returned by `recall` register dependencies too; material-only results do not.
The registry ends with the attempt and does not persist another memory body.

Before each model checkpoint and before preparing a tool action, the task checks
all selected versions against the same eligibility query used by retrieval:
ownership, current revision identity/version, confirmation, status, supersession,
scope, active project, sensitivity, use policy and validity/review/expiry times.
This does not rerank or grant permission. Unrelated memory changes do not pause a
task. Database failures fail closed with a sanitized error; cancellation remains
cancellation.

A changed dependency pauses the task with `task_memory_changed`; a failed check
uses `task_memory_check_failed`. Both are explicit-review states, not ordinary
model failures. Six-language UI explains the pause and offers user-initiated
resume. Resume rebuilds context using current permissions and memory while
retaining saved progress, budget and the existing completed-action journal.

Already-admitted model requests or tool actions are not retroactively recalled.
The check is an admission fence, not a claim of atomicity with a remote server.
The optional request-evidence hook runs after this mandatory checkpoint and is
not used as an authorization gate.

## Snapshot writeback

A second regression proved that Run finalization could write a deleted prompt
back after repository deletion cleared it. Run start now captures store identity
and deletion epoch. The final SQL UPDATE only stores system/injected-context
snapshots if that token still matches. Rolling compaction captures the same token,
checks before summarization calls, and uses a conditional SQL INSERT. Thus an
in-flight summary or recorder cannot restore snapshots invalidated by a deletion
or replaced store. These fences do not erase independent user conversation text
or claim that already-generated output has been recalled.

## Evidence and limits

`test_memory_inflight_revocation.py` uses production host/task/provider serializers
with synthetic HTTP, real isolated SQLite repositories and no external accounts.
It verifies deletion before a tool and after a completed tool; only the first
request is sent, no unstarted action is journaled, pause state is persisted, and
explicit resume sends no deleted block or duplicate completed tool call. It also
checks shared worker/recall dependencies, eligibility changes, storage failure,
cancellation, unrelated deletion, project archive/cloud policy and summary races.
The host test asserts that finalization leaves invalidated snapshots empty.

The initial adjacent backend run passed 104 tests; subsequent summary-call tests
and complete frozen regression results belong in W17. TaskPanel's nine component
tests pass with the repository's established Node web-storage setting. These
checks do not prove all 60 memory scenarios, historical scope snapshots,
real-model behavior, packaged desktop behavior or release readiness.

The frozen follow-up on `5250e62b` passed 4,759 backend tests, 14 skips and 19
warnings in 451.15 seconds. All 1,835 frontend tests, typechecking and build pass;
both pause states passed 24 six-locale/wide-and-narrow isolated browser checks,
with every screenshot visually inspected. W17 records the reports and an earlier
invalid environment attempt separately.

An additional diagnostic still proves a distinct deletion gap: working context
does not yet consult source-suppression records, so retained old messages can
enter later requests and compaction begun after deletion. The in-flight epoch
fence does not solve that stable post-deletion input path. This requirement is
not accepted until those inputs respect the deletion ledger.
