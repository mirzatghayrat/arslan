# W07 — durable task boundary and explicit recovery

Starting checkpoint: `a4e865c0`. Implemented on 2026-09-14. This is an
engineering checkpoint, not the release-candidate gate or a live-model quality claim.

## Delivered

- Migration 0051 separates the user goal, immutable goal revisions, execution
  attempts, monotonic events, reference-only checkpoints and action journal.
  Existing Run IDs remain the inspectable execution records.
- A task-wide budget survives explicit resume. Provider admission persists the
  charged request before HTTP; tool intent is committed before execution.
  Recovery never resets charged usage or silently expands the budget.
- Process interruption parks unfinished tasks for user action. Concurrent starts,
  stale attempts, project-version changes and goal revisions are fenced. Double
  cancellation cannot interrupt the first cancellation's cleanup.
- Non-read actions use intent hashes without storing arguments. Uncertain effects
  block replay until explicit human reconciliation. Completed effects cannot be
  repeated just by restarting the same goal. Credential screening includes nested
  structured argument fields; it is not a claim of complete secret detection or
  OS-level credential isolation.
- Host and nested Run records link back to their attempt. The host-only
  `task_progress` tool can recover bounded outputs owned by that task, without
  granting access to another task's output. Detached background work loses the
  task checkpoint and personal-context authority.
- Acceptance is independent of response text and legacy Run.status. Without an
  executable acceptance check, the task waits for explicit human review instead
  of declaring itself done. Backup restore clears acceptance and requires review.
- Authenticated inspection, events, cancellation, goal revision, reconciliation
  and acceptance endpoints are available. UI offers paged task selection,
  budget/attempt inspection, execution replay, explicit recovery and human review.
  Six locales have matching task/error resources.
- UI state ignores stale event sequences, including interleaved tasks. Newer REST
  acceptance state wins over an older websocket frame; delayed list responses do
  not undo newer cached state.
- Private Run records expose their no-learning status; replay stops waiting for
  automatic scoring and manual rescore rejects them. History derived from
  local-only memory cannot silently switch to a cloud model in the same session.

## Evidence

All checks use isolated temporary data and synthetic adapters. No paid models,
external writes, real credentials, installed-app replacement or publishing.

- First full backend run: 4,258 passed, 14 skipped; one failure was the generated
  capability inventory becoming stale after adding `task_progress`. The inventory
  was regenerated and its two tests passed.
- Focused checkpoint/privacy/memory/reaper tests after hardening: 49 passed.
- Initial full frontend run: 1,713 passed. Focused TaskPanel/RunReplay tests after
  UI QA fixes: 31 passed. Production build passed (existing large-chunk warnings).
- Full frontend rerun: 1,715 passed. TypeScript and Ruff checks passed.
- Second full backend run: 4,259 passed, 14 skipped, one source-introspection test
  failed because this working tree was edited while the already-imported module
  was being tested. Its old code line number pointed `inspect.getsource` at
  `_reveal_streamed` instead of `run_native`; this is not counted as a green full
  run. The affected fetch-budget and task-service tests passed on stable files:
  21 passed, including the new pre-preview/trace credential-redaction regression.
  Subsequent full runs must hold source files unchanged until completion.
- Final immutable-checkpoint run (`8fc967af`, detached temporary checkout):
  **4,261 passed, 14 skipped**, 19 warnings, 357.79 seconds. The imported app/module
  paths were checked to point to that frozen checkout. Log and JUnit evidence are
  `w07-frozen.log` / `w07-frozen.xml` in the isolated test output directory.
- Real browser QA over the built frontend and real local API verified: answer →
  pending human review; checkbox required for acceptance; actual Run replay;
  persisted task selection after reload; uncertain effect blocks resume; neither
  reconciliation choice preselected; explicit evidence note unlocks reconciliation;
  resume creates attempt 2; acceptance updates both header and detail. Light layout
  was inspected at default and 900px viewport. Dark-mode task QA is still pending.
- QA uncovered the stale websocket header bug; a regression now reproduces it.
  The offline harness blocks non-loopback HTTP and uses only a dedicated temporary
  database. Its simulated effects did not call any external executor.

## Remaining integration gates

W08 must bring direct expert/recipe/scheduled entry points under the same durable
task boundary and replace fixed inner-loop limits/text-marker continuation.
W09 adds independently scoped temporary workers. W10 supplies composable
deterministic/model/manual validators and artifact-specific proof. W11 must prove
the credential and queued-permission boundary before account-write workflows are
enabled. Those items are not completed merely by these schema and runtime tests.
