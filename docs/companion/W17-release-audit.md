# W17 — release audit in progress

This is an engineering checkpoint, not an 8-point score, a release candidate,
permission to publish, or permission to replace the installed application.

## Frozen engineering run

Subsequent deterministic-runtime localization is covered by scoped tests in W21,
not by the frozen backend result below. It changes product notices and locale
normalization, not account permissions or release status. Remaining service-error
copy is still being audited before another final-source regression.

Latest complete backend run: clean `4906f9c3`, including deletion-aware history,
task-only sources and replaced-summary dependencies: **4,767 passed, 14 skipped,
20 warnings in 451.36 seconds**. Source remained frozen throughout. Report:
`/tmp/arslan-revocation-corrected.OBwX4u/history-backend.xml`. The same scrubbed
environment and isolated HOME/data/synthetic secret controls below were used;
the aiosqlite guard recorded 67 closed-loop deliveries. The preceding targeted
history/in-flight selection passed 28 tests in 3.81 seconds.

The subsequent frontend-only settings-label wrap fix passed all 237 files /
**1,835 tests** in 20.68 seconds, TypeScript checking and production build in
6.65 seconds. A later added responsive-style regression plus language tests
passed all 15 tests in 0.913 seconds. This later test is not included in 1,835.
Real headless Chromium against the isolated production API/harness passed 24
language-change/Back/reload checks at 1100/600×800, in explicit light/dark modes.
Every post-fix screenshot was inspected. See W21 for the detected label overflow,
test boundaries and artifact paths. No account/model call, installation or
publication occurred; locked-Mac packaged desktop acceptance remains pending.

Previous complete backend run: clean `5250e62b` (in-flight memory dependencies and
snapshot writeback fences), **4,759 passed, 14 skipped, 19 warnings in 451.15
seconds**. Report: `/tmp/arslan-revocation-corrected.OBwX4u/backend.xml`. Source
remained frozen. The run used a scrubbed environment, isolated HOME and
`ARSLAN_DATA_DIR`, a synthetic `ARSLAN_SECRET_KEY`, disabled secret-file bootstrap
and `ARSLAN_LIVE_LLM=0`. The aiosqlite teardown guard recorded 74 closed-loop
deliveries. All 237 frontend files / **1,835 tests** passed in 18.94 seconds;
TypeScript checking and production build (2.98 seconds) passed. Existing warning
and skip categories remain. Both new pause states passed six-locale 900/480×720
headless layout checks; all 24 screenshots in
`/tmp/arslan-memory-layout.DCmfvI` were visually inspected. This is not desktop
acceptance; the Mac remains locked.

The first full attempt had incorrectly unprefixed test environment variables.
Encrypted-storage tests correctly refused the missing synthetic key. After
diagnosis, that invalid run was interrupted with 2,079 passes, 29 failures,
8 setup errors and 13 skips; its partial report is
`/tmp/arslan-revocation-regression.HOEuPq/backend.xml`. Temporary HOME and disabled
secret-file bootstrap still isolated it from production data. Correcting the
environment made the eight backup tests pass without product changes; the
complete corrected run above is the relevant engineering result.

A separate production-host/serialized-HTTP diagnostic confirmed an
acceptance defect on `5250e62b`: after deletion, a retained source message in
the same conversation enters a later request; compaction begun after deletion
can also derive the preference again. Existing suppression records are not yet
applied to working-history/compaction input on that source. The two diagnostic passes in
`/tmp/arslan-revocation-corrected.OBwX4u/test_deleted_source_diagnostic.py` prove
the bad behavior, not successful acceptance. The follow-up fix requires its own
complete regression before closing this engineering gate.

Previous complete backend run: clean `1d1be3c4` (including provider request evidence),
**4,739 passed, 14 skipped, 18 warnings in 444.62 seconds**. Report:
`/tmp/arslan-request-evidence-regression.bdRjdP/backend.xml`. Isolated HOME/data,
scrubbed environment, disabled live models and frozen source were retained; the
aiosqlite guard recorded 52 closed-loop deliveries. Frontend source is covered by
the complete 1,833-test/typecheck/build run in `context-request-evidence.md`.

Despite this green engineering run, an isolated real-host/serialized-HTTP
reproduction confirmed a deletion defect: deleting an injected memory after the
first model request does not remove it from the reused system prompt in the
second request. The diagnostic uses synthetic HTTP only and is not a successful
acceptance test. The follow-up implements mandatory task revalidation and
deletion-fenced snapshot writes, with real-host regression and explicit-resume
checks in `memory-inflight-revocation.md`. A full frozen run is pending for that
new source; the older green result must not be attributed to these changes.

Previous complete backend run: clean `4fd004ca` (including scoped current-revision
FTS), **4,718 passed, 14 skipped, 18 warnings in 447.84 seconds**. Report:
`/tmp/arslan-fts-regression.EtxGKm/backend.xml`. Scrubbed environment, isolated
HOME/data, disabled live models and frozen source were retained. The aiosqlite
guard recorded 78 closed-loop deliveries. Frontend source is unchanged from the
complete 1,829-test/typecheck/build result below. This is not desktop, real-model
or release-candidate acceptance.

Subsequent provider-bound request-evidence hooks and six-language display are
documented in `context-request-evidence.md`. Their focused checks and complete
1,833-test frontend run pass, but the frozen backend result above predates them.

Previous complete combined run: clean `4595994d` (including task-memory evidence
review), **4,704 passed, 14 skipped, 19 warnings in 451.57 seconds**. Report:
`/tmp/arslan-evidence-regression.LvwKlO/backend.xml`. The run used a scrubbed
environment, isolated HOME/data and disabled live models; the aiosqlite guard
recorded 59 closed-loop deliveries. Source remained frozen throughout. On the
same commit, all 237 frontend files / **1,829 tests** passed in 18.82 seconds,
TypeScript checking passed and the production build passed in 3.01 seconds.
Existing skip/warning categories remain; this is not real-model or desktop
acceptance. The Mac was checked again and remained locked.

Subsequent FTS integration now consults the existing local index after complete
permission filtering and validates current-revision content. Its combined
200-test regression passes; `memory-relevance.md` records the boundaries and
initial failures. The frozen 4,704-test result above predates this change and
must not be attributed to the later source without another complete run.

Previous complete backend run: clean `bec04286` (including local relevance
filtering and task-query binding), **4,701 passed, 14 skipped, 19 warnings in
440.60 seconds**. Report:
`/tmp/arslan-memory-relevance-regression.sfva4B/backend.xml`. This again used a
scrubbed environment, isolated HOME/data and disabled live models. Skip categories
remain unchanged; the aiosqlite guard recorded 85 closed-loop deliveries. Source
remained frozen through completion. The later task-memory evidence UI passed a
complete frontend run of 237 files / 1,829 tests in 18.32 seconds and a production
build in 3.06 seconds. Its backend API/repository/context regression passed 55
tests. The full backend run above predates those API additions; see
`memory-evidence-ui.md` for scoped evidence.

Previous complete backend run: clean `43649d7e` (including normalized knowledge
images and multi-turn runtime bindings), **4,610 passed, 14 skipped, 20 warnings
in 411.59 seconds**. Report:
`/tmp/arslan-companion-final-regression.dOUHnb/backend.xml`. The environment was
scrubbed, HOME/data isolated and live models disabled. Skip categories are
unchanged; the aiosqlite guard recorded 56 closed-loop deliveries. Warning
categories include deprecated TestClient transport, existing async markers,
SQLAlchemy connection cleanup/schema cycles and deliberate teardown diagnostics.
No source edits occurred during the run. Frontend source is unchanged since the
full 1,820-test/build result below.

A separate isolated in-memory reproduction on this source confirmed M08-02's
remaining relevance defect: the arithmetic query `What is 2 + 2?` still receives
the confirmed preference `For design work use orange minimalist layouts.` with
no `irrelevant` filter reason. Green engineering tests do not override this
observed acceptance failure. The Mac was checked again and remains locked, so
live UI verification is still unavailable.

Subsequent relevance work addresses that reproduction with a local lexical
filter, task-query binding and host-request regressions in six locales. Its scope
and remaining semantic/FTS limitations are recorded in `memory-relevance.md`.
The latest frozen run above now covers those changes. Lexical matching still has
semantic and arbitrary-paraphrase limitations; this is not the entire real-model
personalization gate.

Source `4bb3aa00` was clean when the complete Python suite started. The run used
a new temporary HOME/data directory, a scrubbed environment, a synthetic secret,
disabled secret-file bootstrap, and `ARSLAN_LIVE_LLM=0`. No production application
database or account configuration was loaded. Result: **4,514 passed, 3 failed,
14 skipped, 18 warnings in 389.69 seconds**. The report is
`/tmp/arslan-companion-regression.peETb1/companion-backend.xml`.

All three failures came from `test_accepted_file_types_agree.py`: its source
reader still required literal picker strings after W20 moved both pickers to the
shared registry. Updating the gate also exposed a real mismatch: the image branch
still recognized only six extensions, while the registry declared TIFF/HEIC
families too. The fix recognizes the complete shared image list and verifies
actual dispatch for every declared extension, rather than just comparing two
copies of the same list. Unknown extensions are still rejected. Parser/codec
fidelity remains separate from dispatch recognition.

The updated format/vision/OCR regression passed 93 tests. The complete frozen
rerun on clean source `59d5ba62` passed **4,577 tests, with 14 skips and 19
warnings in 411.38 seconds**. Its report is
`/tmp/arslan-companion-regression.u3Jhgc/companion-backend.xml`. The same skip
categories remain; the teardown guard recorded 64 closed-loop deliveries.
The complete frontend suite passed **236 files / 1,820 tests** in 19.20 seconds,
and the production build passed in 3.66 seconds. The first frontend attempt used
Node's experimental web storage and failed (53 files); rerunning with the already
established `NODE_OPTIONS=--no-experimental-webstorage` setting passed without
product changes. Existing jsdom canvas/navigation and bundle-size warnings remain.
These results apply to that frozen source, not automatically to subsequent edits.

Warnings were not hidden: the first full run included existing async-marker,
SQLAlchemy cleanup/cycle and deliberate teardown warnings. The aiosqlite guard
recorded 77 deliveries into closed loops without changing test outcomes. Twelve
live-model cases, one non-macOS case and one operator-copy allowlist case were
skipped. These are not successful real-model evaluations.

## Desktop source checks

The XcodeBuildMCP skill's session tools were unavailable. The repository's existing
Tauri/Rust CI path was used as the appropriate fallback, not raw Xcode commands.
With the installed stable toolchain, offline/locked dependencies and a temporary
HOME: Rust formatting passed, all 26 Rust tests passed, and Clippy passed for all
targets with warnings denied. Both Swift voice helper files passed typechecking.
The existing empty CI resource directories were reused. No application was
installed/launched, no microphone permission was requested, and no signing or
notarization was performed. These source checks do not verify a distributable app.

## Requirement evidence still needed

### Frozen backend preflight follow-up

Starting from `cbce62f6`, the existing build environment lacked PyInstaller. The
six lockfile-pinned build packages were installed from the local cache, offline,
into `/tmp/arslan-candidate-build.BboGj4/build-tools`; the project environment was
not changed. The first freeze failed because collecting the entire MCP SDK
imported its optional developer CLI, which exits when its `typer` extra is absent.
The spec now excludes only `mcp.cli` before subpackage traversal and from analysis;
the actual MCP client, auth and FastMCP server paths remain included.

The corrected PyInstaller freeze completed in 25.71 seconds with no signing
identity. Bundle verification passed (15 feature imports, SPA/data resources,
native PDFium/Vision/TLS checks, no forbidden rasterizer, database or secret-shaped
files). The 159 MiB development sidecar is
`/tmp/arslan-candidate-build.BboGj4/dist/arslan-server`; its entry executable SHA-256
is `7ffa3f26adb5f63eac2b4968ad6ccbb36def852acfee3c537539104ae0dac08f`.
Browser reader/policy resources and the shared input registry are present.
Warnings about optional `pysqlite2`, `MySQLdb` and Windows `user32` remain recorded
in the build output; they did not prevent the required native probes.

`scripts/frozen_sidecar_smoke.py` then booted that actual frozen executable twice
with disposable HOME/data. It verified unauthenticated settings requests receive
401, the generated token is mode 0600, the SPA loads, actual Word table and PDF
page-locator extraction works, all six languages save, and token/language survive
restart. Closing the parent pipe terminates the frozen process successfully.
Generated tokens and child logs are not printed; no real model/account was used.
The packaging/release regression passed 33 tests; targeted lint/whitespace passed.

This is not a signed application, DMG, notarized update, complete compute runtime,
old-library upgrade or native webview acceptance. No installed app was started or
replaced. XcodeBuildMCP session tools were unavailable, so the repository's Python
freeze path was used; no raw Xcode/notary commands or credentials were invoked.

Latest frozen backend checkpoint: clean `a8c00020`, after runtime-error locales and
Word table/source-locator extraction, completed **4,838 passed, 2 failed, 14 skipped,
19 warnings in 464.13 seconds**. Report:
`/tmp/arslan-companion-regression.lXHbJn/companion-backend.xml`.
The run used a new temporary HOME/data, scrubbed environment, synthetic secret,
disabled secret-file bootstrap and `ARSLAN_LIVE_LLM=0`; source remained unchanged.
The aiosqlite teardown guard recorded 72 closed-loop deliveries.

Both failures were stale copy assertions: provider-health persistence demanded
Chinese key-limit wording despite the default English UI, and expert vision
refusal demanded `vision support` instead of the new `image support` wording.
Their actionability/routing/raw-error protections remain; the health test now also
checks that the account may still have a balance. After updating those two tests,
the six-file health/expert/locale/provider/chat regression passed **95 tests** in
5.01 seconds. Targeted lint and whitespace checks passed. This focused repair is
not a new all-green frozen full run, nor real-model or packaged acceptance.

| Requirement | Current authoritative state | Remaining evidence |
| --- | --- | --- |
| Complete engineering regression | Clean `4906f9c3` full backend; subsequent frontend-only wrap fix has complete frontend/typecheck/build evidence above | Repeat on final release source after remaining implementation gates |
| Context evidence UI | Task-scoped receipt history, version review and provider-bound counters; in-flight withdrawal, snapshot fences and retained-source filtering implemented | Real desktop and packaged runtime verification, historical scope snapshots and complete scenario evaluation; see `context-request-evidence.md` and `memory-inflight-revocation.md` |
| 30 real task families × 3 attempts | All 30 catalog entries are `real_inputs_pending`; fixed denominator is 90 | Authorized real inputs, immutable initial-state/configuration hashes, actual attempts and independent checker evidence |
| 60 multi-turn memory scenarios | All 60 retain incomplete status; partial host-request/receipt bindings documented in `memory-runtime-bindings.md` | Complete remaining bindings, relevance filtering and separately authorized model-behavior checks |
| W11 credential boundary | Credential-backed activation remains disabled | Trusted broker identity/OS isolation, confirmation UI, independent security review |
| W12/W13 ASC | Offline read/diff/reconciliation contracts only | Authorized exact App/version integration and real draft-write/readback evidence; no submission/publication authorization inferred |
| W15 design/media | Project style references and gated media library; precise editing unsupported | Runnable design workflow evidence, reference/output review, approved available backend for D07; unsupported stays in denominator |
| W19 browser/dock | Isolated public-page navigation and earlier real-browser fixtures | Independent broker review, full locale/window checks and packaged runtime validation; authenticated actions remain disabled |
| W20 input coverage | Shared declaration, structured readers, sampled video frames and bounded payloads | Remaining codec/visual-quality/source-locator checks and real selected-model evidence; samples are not full-motion or audio analysis |
| W21 language consistency | UI/catalog/connector resources and component tests implemented | Remaining runtime messages/errors and all-six-language live layout/navigation checks |
| Installation and migration | Source-level synthetic migration/restore checks exist | Source/package identity, signature/notarization, isolated fresh install, old-library upgrade/restore and retained model configuration |
| Human trial and safety review | Not supplied by unit tests | Actual authorized trial, UX judgment and external review |

The Mac remains locked for live UI inspection. Unverified rows are not treated as
passed, unsupported tasks are not removed, and development checks are not used as
a substitute for the reserved real-input evaluation set.
