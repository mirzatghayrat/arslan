# Task memory evidence — read-only review

TaskPanel now includes a collapsed Lucide memory-context section. Opening it
loads only the selected task's receipts; reading a memory requires a separate
explicit click. Copy in all six application languages distinguishes selection
for a request from delivery or model adoption. Cloud permission is not reported
as proof of transmission. Missing records and an empty selection are distinct.

Request-boundary evidence is now added separately from selection. The UI shows
attempt and successful service-response counts only when valid metadata exists;
details, newer verification results and limitations are in
`context-request-evidence.md`. These counters are not proof of model adoption.

The authenticated receipt endpoint supports owner/conversation/task-scoped
keyset pagination. A cursor outside that scope is rejected. Memory references
are returned without historical cached titles or locators. The separate review
endpoint requires an actual reference in the owned receipt and resolves its
recorded revision, never the latest text as a fallback. Deleted entries return a
marker without text; missing revisions and cross-owner entries are unavailable.
No new mutation or permission grant is introduced.

Refreshing, collapsing or switching tasks clears reviewed text and invalidates
pending responses. Pagination deduplicates stable receipt IDs. Incomplete legacy
metadata cannot create an invalid memory-review button or an invented token
estimate. Errors use generic localized copy, not raw backend diagnostics.

## Evidence

- Final frozen source `4595994d`: complete backend **4,704 passed, 14 skipped,
  19 warnings in 451.57 seconds**; complete frontend **237 files / 1,829 passed
  in 18.82 seconds**, TypeScript checking and production build (3.01 seconds)
  passed. Isolated backend report: `/tmp/arslan-evidence-regression.LvwKlO/backend.xml`.
  This supersedes the scoped-only limitation below; it does not certify live
  models or desktop integration. No source edits occurred during the run.
- Backend API, repository and context regression: 55 passed, one existing
  TestClient deprecation warning, 2.97 seconds. Includes task/cursor/auth isolation,
  actual revision lookup, deletion, missing revision and cross-owner cases.
- Complete frontend regression: 237 files / 1,829 tests passed in 18.32 seconds.
  Nine MemoryEvidence tests use the real component and localization provider;
  API responses are controlled fixtures. Existing jsdom canvas/navigation
  warnings remain. An initial targeted invocation omitted the established
  `NODE_OPTIONS=--no-experimental-webstorage` setting and failed before test
  collection; the complete correctly configured run passed.
- Production frontend build passed in 3.06 seconds; existing large-chunk
  warnings remain. A subsequent legacy-metadata typing correction passed
  TypeScript checking, all nine focused component tests and a fresh build in
  2.97 seconds; the complete-suite count above precedes that correction.
- `scripts/memory_evidence_layout_smoke.cjs` renders the production component and
  built CSS in existing isolated Chromium with synthetic receipts and no external
  network. Six locales at 900×720 and 480×720 pass horizontal-overflow, runtime
  error, translation-key and scroll-to-text-end checks. All 12 screenshots were
  visually inspected. Screenshots are local temporary evidence in
  `/tmp/arslan-memory-layout.s6nMtr`, not packaged product assets.

These are source/component checks, not a real desktop task evaluation. The Mac
was locked during this work. Packaged runtime, actual task-to-panel integration,
real-model behavior and the broader W17 release gates remain unverified. The
complete backend result above covers the new API routes. No installation was replaced,
no real account/model was used, and nothing was published.
