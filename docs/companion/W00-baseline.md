# W00 — baseline and protection

Started: 2026-09-14. Baseline `d3e8081d0fc7a72072731edfaa0ea33acf095724`, clean before work, desktop 0.1.39. Isolated implementation branch created without changing the main checkout or installed app.

## Environment

- macOS; existing Python 3.11.15 environment and locked dependencies reused.
- Existing Node 25.5.0 environment; CI uses a different Node generation. Record this difference instead of treating an environment-specific failure as a product regression.
- Backend tests run with a temporary HOME/data directory, scrubbed environment, a synthetic test secret, secret-file bootstrap disabled, and live-model evaluation disabled. No existing user database or account configuration is loaded.
- No package installation, real credentials, paid model/API call, account write, release, or installed-app replacement is part of W00.

## Initial checks

| Check | Result |
| --- | --- |
| Python Ruff, baseline | Passed |
| Frontend TypeScript, baseline | Passed |
| Rust formatting, baseline | Passed |
| Frontend tests under unmodified Node 25 globals | Failed: 40 files; 43 tests failed / 1,449 passed; 2 unhandled errors. `localStorage.clear/setItem is not a function` dominates; Node emits an experimental Web Storage warning. This happened before product edits. |
| Frontend tests with Node's experimental Web Storage disabled | Passed: 1,687 tests. Set `NODE_OPTIONS=--no-experimental-webstorage` for the worker processes; setting only the initial process CLI flag was insufficient. No product/test implementation changed. |
| Full backend tests | Passed: 4,032; 14 skipped; 16 warnings; 365.93 seconds. Twelve live-model cases deliberately skipped, one non-macOS case skipped on macOS, one operator-only copy allowlist skip. |
| Frontend production build | Passed; existing large-chunk warnings retained |
| Rust tests | Passed: 26 tests. Initial build stopped because release-only resource directory `binaries/listen` was absent; the same empty resource-directory preparation used by CI resolved it. This is not a packaged-app test. |
| Rust Clippy | Passed offline, locked, all targets, warnings denied |

## Functional protection matrix

| Area | Existing behavior / evidence | Required protection or gap |
| --- | --- | --- |
| Conversations and experts | Main conversation, expert direct chat, history/archive, streaming, tool activity | Preserve identities/IDs/history; new workers must not pollute the recent-conversation list |
| Knowledge and memory | Notes/collections, scoped retrieval, temporal records, proposals, graph | No silent data loss, cross-project leakage, or fabricated confirmation during migration |
| Browser | `BrowserPanel`, managed static renderer, screenshots/text, proxy/SSRF and cancellation tests | Preserve static mode; interactive browsing and side-panel layout are explicitly not complete |
| Current file input | TXT, Markdown, PDF, DOCX, HTML; image payload/OCR; URL extraction | Keep working via both chat and library entry points; retain size/truncation and unsafe-URL handling |
| Input gaps | Picker/extractor does not cover common code extensions, CSV/XLSX/PPTX, or video ingestion | W20 must add bounded, declared support; a splash video or PPTX exporter is not a video reader/PPTX importer |
| Artifacts | Stored run artifacts, authenticated downloads, HTML/chart/SVG/PPTX output paths | Keep real downloadable files and ownership checks; side-panel previews must not execute hostile content with application privileges |
| Execution | Shared budgets, cancellation, checkpoints, recipes, provider-native tools | Preserve error visibility, provider opaque fields, no budget reset, no replay of uncertain writes |
| Credentials and access | Encrypted settings, caller scope, local/remote auth checks, managed tools | Do not read real secrets; UI simplification must not remove policy gates or warnings |
| Languages | en/zh/ja/es/de/fr, locale key-parity tests | Key parity alone does not prove translated runtime UI; W21 adds value/source/runtime checks |
| Packaging/platform | WebSockets loaded dynamically, Pillow indirectly used by PPTX, macOS OCR and Linux fallback, non-code package resources | Do not delete on direct-import count or one-platform coverage alone |

## Cleanup candidates (no deletion yet)

1. Retire only the old `tool_loop.run` text-JSON path after checking exports/dynamic consumers and migrating useful tests to `run_native`. Keep shared safety/evidence functions and the expert wrapper.
2. Correct stale comments claiming experts still use the old path; actual host and expert calls use `run_native`.
3. Simplify LLM routing only after preserving explicit expert selection, clarification, connection/setup, and old proposal continuation. `router.route` is currently live.
4. Do not delete the scoring/evolution modules as dead code: run recording and replay/evaluator paths still use them. Main-assistant runs already differ from expert scoring.
5. Remove redundant navigation only after replacement entries and deep links are operational. No database rows are deleted as part of navigation cleanup.

## Language findings to address

- English resources contain Chinese protocol headings in skill creation hints/examples. The parser's old heading contract must gain a compatible English form before replacing these hints; changing text alone would break imports.
- Some artifact controls are hardcoded English (for example the PPTX download control), which bypasses the six-language resource system.
- Backend errors and dynamic content need their own localization boundary; scanning only locale JSON and JSX is insufficient.

Backend warnings include existing async-marker warnings, SQLite cleanup warnings and intentional teardown probes; the teardown guard counted 82 deliveries into closed loops. They are recorded, not reclassified as new companion defects or hidden as clean execution.

The historical short-task classification is recorded in `W00-short-task-classification.md`. Packaged candidate verification belongs to W17 after implementation. This record does not certify new companion behavior or a live-agent quality score.
