# W03–W06 integration checkpoint

This is implementation evidence, not release approval. Production memory activation
is still deliberately unregistered until the remaining execution/recovery gates pass.

## Implemented surfaces

- Projects: versioned create/edit/archive, explicitly linked collection IDs, optional
  app metadata, and creation of a conversation with its project bound before opening.
- Memory: About me, Materials and the existing Graph. Existing users retain the graph
  default; the selected/default view is remembered. Legacy object IDs remain supported.
- Memory edits retain drafts on failure, enforce version checks, require sensitive/cloud
  acknowledgements, and show source, history, pause/resume and deletion impact.
- Pending suggestions are not active by default. Confirmation presents the project
  scope and defaults to local-only use. Stale confirmation cannot overwrite new content.
- Conversation controls: project, no-memory, no-learning, cloud-memory permission,
  sensitive-memory permission, and explicit temporary mode for empty conversations.
- Temporary conversations have no persisted client list/title, automatic title model,
  saved Run link, tools, automatic URL extraction, background workers or automatic TTS.
  Their dedicated runtime keeps only bounded in-memory dialogue. Provider retention is
  explicitly outside the app's no-saved-history claim.

## Actual UI verification, 2026-09-14

Used `scripts/companion_smoke_app.py`, an isolated temporary database, real production
migrations and HTTP/WebSocket endpoints, and a synthetic answer adapter. No real user
data or working model credentials were used. The harness now also stubs connection
checks and denies external HTTP requests: the initial harness revealed that the UI's
automatic health check bypassed the answer factory and sent its synthetic key to the
provider (401). Those pings were not real model-quality tests.

Checked English/dark and Chinese/light at a 900×700 viewport:

- Project card, editing and successful save; starting a project-bound conversation.
- Memory list, pending card, local-only confirmation and resulting active state.
- Temporary mode save, synthetic streamed answer, no replay link, and removing the
  temporary row on leaving. The test database contained zero messages, Runs, summaries
  and usage rows after that temporary exchange.
- Found and fixed duplicate sibling React keys which retained an old context toolbar
  during conversation switching. Rechecked that only one toolbar remains.
- Kept the Graph available as a peer view, not buried in advanced settings.

Frontend regression: 219 files / 1707 tests passed. A subsequent regression for
withheld legacy secret content (null, not a string) also passes; the UI does not crash
or offer to edit that withheld value. TypeScript and production build pass. The build
still reports its pre-existing large-chunk warning.

## Privacy recovery checks

Restoration modifies only the validated staged copy, never the backup or live data.
It creates new quarantined memory revisions, revokes prior task cloud permissions,
archives restored projects for review, pauses schedules, removes derived summaries
and cached prompt snapshots, and suppresses automatic extraction from restored source
IDs. A pre-v2 restore guard survives until migration. Original conversation text and
files remain readable; later deletions absent from an old backup are not invented.

Focused restore/migration/context suite: 41 passed. Local-model/factory/title/repository
suite: 72 passed. Full backend regression: 4218 passed, 14 skipped (338 seconds).
Subsequent durable Run privacy exclusion and API paging/revocation changes passed
96 focused lifecycle/migration tests, 58 existing replay/restore/API tests, and 17
focused privacy/restore/API tests. These counts overlap and are not added together.
The frontend now offers 100-entry pagination for memories and proposals, clearly
labels that search covers loaded entries, and retains loaded results after a failed
next-page request. Its focused companion suite has 12 passing tests.

Runs now retain a privacy ceiling before their execution starts. Opted-out turns,
local-only turns, unscoped companion background attempts and restored/legacy attempts
cannot enter automatic judges or replay corpora. Revoking conversation permissions
also excludes prior attempts and a later grant does not silently re-authorize them.
This cannot recall a provider request that was already sent before revocation.

## Remaining before activation / release

- Task/Run state, durable event cursors, recovery budgets and side-effect reconciliation.
- Bind all 60 memory scenarios to actual policy/runtime assertions; do not treat their
  specification catalog as a passing result or a live model evaluation.
- Relevance limits, knowledge resource receipts and receipt browsing.
- Remaining approved navigation, professional workflows, formats, browser and release gates.
