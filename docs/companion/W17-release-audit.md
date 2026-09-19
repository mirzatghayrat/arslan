# W17 — release audit in progress

This is an engineering checkpoint, not an 8-point score, a release candidate,
permission to publish, or permission to replace the installed application.

## Frozen engineering run

### Latest temporary desktop bundle: bound recovery consent, 2026-09-19

Source checkpoint `f66e569f` is now in the temporary full desktop application:
`/tmp/arslan-native-candidate.xIygc5/target/release/bundle/macos/Arslan.app`.
It includes the read-only existing-secret helper, bounded native control
transport, six-language interrupted-recovery dialog and operation-bound consent.
Forward restore picker and native trial orchestration remain incomplete.

The sidecar was staged with the existing verified compute runtime (9,240 files).
Native source, Cargo files, locale JSON, locale resources and splash were checked
against the source tree. An initial resource-copy command used the wrong JSON
location and failed; the root-level locale JSON files were then copied correctly
and a second release build completed in 1m05s, before bundling. The first build
is not the final bundle's provenance. XcodeBuildMCP defaults had no configured
project/scheme/device; compilation used isolated offline Rust. Tauri packaging
used `--no-sign`; there was no developer signing/notarization or publication.

- Native SHA-256: `89258bca3c79be2a290127c582899a3278b968107c6379e6f970ed2c6a8c676b`.
- Backend SHA-256: `e8c5651dfdaa94e35756ef3257bac187d15643f44678f6669af0d2f4b4a119c4`.
- Bundled web resources exactly match the current `web/dist` directory.

Checks against the actual application's resource directory passed: 15-import
selftest, web assets, absence of AGPL rasterizers/databases/secrets (431 MiB),
and sandboxed/network-isolated compute with two durable verified artifacts.
Both native-test-transport-to-bundled-backend smoke branches passed: offline
restore, inspection, mismatched-operation refusal, restricted trial health,
ownership refusal, graceful shutdown, original data retention, rollback or
finalization, and normal restart. These use disposable synthetic data and source
backup creation; they do not exercise native UI or real model/account actions.

Computer-use freshly reported the Mac locked. No desktop launch or confirmation
click was attempted, so translated dialog layout, menus and native interaction
acceptance remain open. The installed app and real profiles were not changed.
This checkpoint supersedes older bundle hashes below, not their historical
evidence or the remaining W11/W17/W19/W20/W21 acceptance gates.

### Later source checkpoint: attachment ownership, 2026-09-19

Composer async completion is now fenced against deletion, clear, unmount and
URL-policy withdrawal. Concurrent extraction merges the latest list and preserves
busy/slot accounting. Pasted URLs now honor the existing temporary-conversation
restriction. W20 details the reproduced failures and limits; this is frontend
source only and has not been folded into the native menu candidate below.
Full frontend: **243 files / 1,889 tests passed** (22.00s), typecheck and web
production build passed (3.17s). Existing warning categories remain. Backend
production code and the previous complete backend evidence are unchanged.

### Complete backend source regression: a853cf8f, 2026-09-19

The full Python suite ran on clean, unchanged `a853cf8f` in a scrubbed environment
with disposable HOME/data, a synthetic secret, disabled secret-file bootstrap
and `ARSLAN_LIVE_LLM=0`: **4,904 passed, 14 skipped, 19 warnings in 482.43s**.
Report: `/tmp/arslan-release-regression.Vc3q8a/backend.xml`. The teardown guard
recorded 96 closed-loop deliveries. Warnings include existing Starlette
deprecation, sync tests marked async, SQLAlchemy connection cleanup/cyclic
metadata/null identity, and deliberately exercised portal teardown diagnostics.

Skips are 12 real-model evaluations, one non-macOS-only refusal check and one
explicit operator-copy allowlist case. None is a successful real-model result.
The existing 30 deterministic acceptance contracts were also summarized from
this actual XML: all 30 passed. They are not the 30 real task families.

After that frozen run, four cross-turn memory tests were added without changing
production code. Two initial credential cases expected a later boundary than
the actual early task refusal; corrected assertions verify that stronger
boundary rather than bypassing it. The four-case follow-up passed (7.30s);
see `memory-runtime-bindings.md`. Frontend/native/package results remain those
of the menu checkpoint below; this turn did not rebuild or modify the app.

An explicit all-unrun evaluation report at
`/tmp/arslan-release-regression.Vc3q8a/unrun-report.json` has denominator 90,
observed 0 and no eligible live score. No attempt evidence was supplied to this
report. Real-input evaluation, remaining memory bindings, W11/account boundaries,
design/media workflows, native visual acceptance and human review remain open.

### Current packaged checkpoint: native menus, 2026-09-19 (UI pending)

Six-language native menu labels are implemented with predefined system roles
and existing handles; W21 details scope and remaining acceptance. Full frontend
242 files / 1,879 tests passed (26.85s), native 30 tests passed, typecheck passed,
production web build passed (3.13s). Existing canvas/navigation and large-chunk
warnings remain. No fresh full backend suite was run for these menu-only changes.

Native release rebuilt offline in 1m39s in the isolated staging project; sidecar
frozen in 44.14s at `/tmp/arslan-candidate-build.BboGj4/dist-menu/arslan-server`,
then staged with the unchanged verified compute runtime. Tauri bundled with
`--no-sign` at the same temporary app path. Actual bundled smoke, 15-import and
resource verification (431 MiB), no-prohibited-rasterizer/database/secrets checks,
and sandboxed compute selftest (two durable artifacts) passed. Bundled SPA
exactly matches `web/dist`.

- Native shell SHA-256: `768bc50f20e1dc7ee094483be8f3c4aa5bc8af077fda66ca6d6daa02d61d45e3`
- Backend SHA-256: `1e98bb372e9b03ee003a84416ed5711f62dbcaa5243862caabd61fdaa7fadafd`
- Main SPA `index-KPUVlq6L.js`: `c15e5d4d95050ba82c2c156e27ce6bf2193cf462ef7201f1073e866018506645`

Launch used the existing disposable HOME and unique port 61580. Computer-use
reported the Mac locked, so no menu display or copy/paste acceptance is claimed.
The owned temporary app was terminated, and owned smoke processes completed.
No signing, install replacement, publication or real account/model action.

### Earlier packaged checkpoint: onboarding, 2026-09-19

Research adoption order is recorded in `W22-open-source-adoption.md`; no new
runtime dependency was installed. Onboarding now writes `first_run_seen` into
the existing backend settings table and restores it before deciding whether to
show the wizard. The old origin-local flag is migrated when available. Failed
writes fall back locally; cross-origin durability requires a successful save.

An initial temporary-HOME launch reused the default loopback origin and showed
cached conversation titles while API calls failed. The disposable database had
zero messages and zero providers; no cached conversations were opened. This
exposed a separate bootstrap defect: the webview's old cached token took
precedence over the newly injected native token. Native injection now wins when
non-empty; absent/blank injection preserves browser credentials. A new regression
test failed before the change and passed afterward. HOME isolation alone does
not isolate WKWebView origin storage; subsequent UI acceptance used unique ports.

Validation: final full frontend **241 files / 1,876 tests passed** (24.28s),
TypeScript and diff whitespace checks passed; focused backend settings suites
**17 passed**, including a new database-session persistence check. Existing
canvas/navigation, large-chunk, Starlette deprecation and SQLAlchemy
connection-cleanup warnings remain. This is not a fresh full backend run.

The final sidecar was frozen at
`/tmp/arslan-candidate-build.BboGj4/dist-bootstrap/arslan-server` (39.97s), with
the unchanged locked compute runtime copied from the earlier verified bundle.
The unchanged Tauri shell was rebundled with `--no-sign` into the same temporary
application path documented below. Actual bundled sidecar smoke passed fresh
boot/restart, retained onboarding state, six languages, source locators, auth and
parent-pipe shutdown. Bundle verification passed (15 imports, 431 MiB); compute
selftest passed with two durable artifacts and network isolation. Bundled web
assets exactly match `web/dist`. Backend SHA-256:
`1e98bb372e9b03ee003a84416ed5711f62dbcaa5243862caabd61fdaa7fadafd`.
Main SPA `index-BI7IV7Et.js` SHA-256:
`63fbe98e510763a910975564e76c81d23d45df8232e370f3a47293751c734665`.

Real native UI in `/tmp/arslan-native-ui-onboarding.237zFG` passed Chinese
onboarding → skip → Japanese settings → two workspace returns. Quit on port
60118 and relaunch on 60554 retained Japanese UI / ja-JP voice hint and did NOT
show onboarding. Screenshots confirmed a visible greeting before and after
restart. This bounded run did not reproduce the previously observed disappearing
greeting and does not establish its cause or close that finding. Native menus
still remain English. All owned native and smoke processes exited; no release,
installation replacement, real model or real account action was performed.

### Earlier packaged checkpoint: 409f42ea

After the user unlocked the Mac, real native-window inspection proceeded in
disposable HOME directories, using LaunchServices to open only the temporary
application. No model, real account, microphone capture, signing identity,
installed application, or installed application data was used.

The `ad6bc662` package passed real public-browser interaction: the missing-runtime
gate appeared first; an already pinned browser runtime was then copied into the
disposable profile without downloading. Example Domain → IANA link navigation,
back/forward, direct navigation to IANA Protocol Registries, visible scroll
down/up, and dock resizing worked. Stop cleared the live screenshot, disabled
navigation, and the owned reader process exited. This is bounded public read-only
browsing evidence, not authenticated account or arbitrary browser automation.

Native UI inspection found and reproduced two state defects: onboarding language
was not propagated to App, and Settings saves did not refresh the shared settings
read by the speech-input control. Fixes `a2eff2f1` and `409f42ea` cover them. Ten
new regression cases include pending-save dismissal, failure, superseded response,
field-scoped merging and masked-secret handling. The final complete frontend run
passed **239 files / 1,866 tests in 20.24s**; typecheck passed and web build took
5.91s, with existing warning categories retained.

The final sidecar was frozen in 26.32s at
`/tmp/arslan-candidate-build.BboGj4/dist-voice/arslan-server`; unchanged locked
compute files were copied from the earlier verified same-turn bundle. Tauri
rebundled the unchanged native shell with explicit `--no-sign` at the temporary
application path below. Its actual bundled sidecar passed the frozen smoke,
15-import/resource verification and sandboxed compute selftest (two durable
artifacts, outside-file/network access denied). The bundled SPA exactly matches
`web/dist`. Shell and backend executable hashes are unchanged from `ad6bc662`;
the new main SPA asset is `index-CccCi4j5.js`, SHA-256
`f010cd2354d8c039bf40ccb8fcb965336821f45ab130809928bbbbe0c87358f5`.

On the final package, Chinese onboarding → skip → Settings stayed Chinese.
Settings selection → workspace → Settings passed for Japanese, Spanish, German,
French and English; switching back to Chinese also updated the workspace.
Speech-input help showed `ja-JP`, `es-ES`, `de-DE`, `fr-FR`, `en-US` and `zh-CN`
respectively, without activating recording. Six language-setting layouts were
visually inspected at 1170×768 in dark mode. Chinese UI/language hint persisted
after a native quit/relaunch. All temporary application instances and smoke
processes were closed at the end.

**Still failing / not accepted:** restarting the same disposable profile at its
new native loopback port showed onboarding again (the seen flag is currently
origin-local localStorage). After repeated settings round trips, the workspace
greeting remained in the accessibility tree but disappeared visually, including
after an additional delayed observation. Root cause of that rendering issue is
not yet established. Standard native menu titles still appear in English.
These findings and the broader security/real-task/signing gates keep W17 and W21
open; this is not a release candidate.

### Earlier packaged checkpoint: ad6bc662

The current temporary application includes the `3d8ca803` native boot/status
localization, `ac7047b9` execution-intent binding, `93af5001` gated field-draft
service and `ad6bc662` structured-attachment fidelity fix. None enables real
credentials or constitutes a release candidate.

The web production build passed in 3.17s with the existing large-chunk warning;
TypeScript passed. The input inspection reproduced five cleanup-model calls for
structured sources before the fix. Afterward, the eight-file input/extraction/
ingestion regression passed 58 tests in 2.80s and the disjoint Word-source suite
passed 9 tests in 0.22s. These 67 tests are not a fresh full engineering population.

The final PyInstaller freeze completed in 23.29s at
`/tmp/arslan-candidate-build.BboGj4/dist-input/arslan-server`. The unchanged locked
compute runtime was copied from the same-turn offline-verified standalone build.
The native shell was rebuilt offline in 1m02s, then Tauri rebundled that unchanged
shell with the final sidecar using explicit `--no-sign`. No signing identity,
notarization, updater artifact, installation or publication was used.

Application:
`/tmp/arslan-native-candidate.xIygc5/target/release/bundle/macos/Arslan.app`

- Shell SHA-256: `a16c27893d1816bc8ad3b0c6e26d2d26036e6245e814a53885180c1a63b22da6`
- Bundled sidecar SHA-256: `e33ea4779d3c5a34e083ac185a2d7a5f67a76a3d77aa840fe66e4fb1c2f64304`

The actual sidecar inside the final `.app` passed fresh boot/restart,
authentication, token/language retention, native locale-hint repair, Word/PDF
source locators, XLSX cell/formula/cache labels, PPTX slide locators and inert TSX
text with `compress=true`. Fresh browser sessions correctly refused to run without
their optional runtime. Video transcription/visual-understanding limits stayed
explicit; this is not successful video decoding or real-model visual acceptance.
Parent-pipe closure terminated the tested sidecars.

The actual bundled compute selftest passed with two durable artifacts and denied
outside-file/network access. Bundle verification passed 15 imports, native lazy
resources and the no-prohibited-rasterizer/database/secret-shaped-file checks
(431 MiB sidecar). The bundled SPA exactly matched `web/dist`; Info.plist and all
six localized permission resources passed plist validation. Optional PyInstaller
warnings for `pysqlite2`, `MySQLdb` and Windows `user32` remain.

The Mac was locked and automatic unlock failed both before and after this work.
The user was asked to unlock it; no temporary application window was launched in
this checkpoint. Consequently native boot copy, status labels, six-locale layouts
and dock interaction remain live-UI acceptance gaps. Installed app/data remain
untouched; this unsigned temporary bundle is not presented as ready to publish.

### Earlier source and packaged checkpoint: 040a7f56

The Python population ran in two disjoint selections on unchanged product
source: `tests/server` passed **4,208 tests, 14 skipped, 20 warnings in 461.84
seconds**; `tests --ignore=tests/server` passed **659 tests in 2.56 seconds**.
Total: **4,867 passed**, not one combined-process run. Both used scrubbed
environments, disposable HOME/data, synthetic secrets, disabled secret-file
bootstrap and `ARSLAN_LIVE_LLM=0`. The server aiosqlite guard recorded 58
closed-loop deliveries. Warnings/skips remain explicit.

The frozen sidecar rebuilt in 25.31s under
`/tmp/arslan-candidate-build.BboGj4/dist-locale`; executable SHA-256:
`0f0c4c0062a7f67525a1487bf006de20c46e979664ca3c1293ae9d48dcc8f1a4`.
The locked compute runtime was staged from offline cache and passed relocation
and library checks. The native app rebuilt offline with explicit `--no-sign`
in 1m05s at
`/tmp/arslan-native-candidate.xIygc5/target/release/bundle/macos/Arslan.app`;
shell SHA-256:
`8d59ef9c78d667834b1f416f042961f0cdeb2081ce5cc7f44b78d0b045a6789c`.
The sidecar inside that app passed fresh boot/restart/authentication, Word/PDF
source locators, six saved languages, mode-0600 native hints, and hint deletion
followed by startup repair from the retained database. Its compute selftest
produced two durable artifacts with outside-file/network access denied.
Bundle verification passed 15 imports, native/web resources and prohibited
component/database/secret-file checks. All six permission resources and
Info.plist passed native plist validation.

### Bounded real macOS window inspection

The Mac was unlocked. Directly executing the inner Mach-O with a scrubbed
environment showed `cannot locate the bundled sidecar: unknown path`; that
process was stopped. Launching the same temporary app through macOS Launch
Services, with explicit disposable HOME `/tmp/arslan-native-ui.ojYVFl` and
synthetic/no-live-model settings, successfully opened the native webview. This
launch-path distinction is not counted as all-launch-method success.

Native UI inspection observed English and switched through Chinese, Japanese,
Spanish, German and French in the first-run language screen. Chinese first-run
and French workspace/dock layouts were visually inspected. With no account
configured, the French dock opened a browser tab; the public example URL returned
the expected HTTP 409 localized setup-required state because the fresh profile
has no browser runtime. No browser download, login or model request occurred.
The native menu showed `Rechercher des mises à jour…`. A public release-feed
check was requested without installation; the localized checking indicator
appeared then disappeared, but the result dialog was not reliably observed and
is **not** certified.

Remaining observed defects include English `Online` in Japanese/Spanish/French,
legacy “spawns” composer terminology, and English splash/boot notices. This was
not complete six-locale layout/navigation, upgrade, signing/notarization or
real-task acceptance. Quit was invoked on the temporary candidate; its process
and sidecar were confirmed gone. The installed app/data were not replaced.

### Earlier checkpoints

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

### Unsigned native application assembly

A tracked desktop-source snapshot of `89852d02` was copied into
`/tmp/arslan-native-candidate.xIygc5`. Tauri CLI 2.11.4 was installed from the local
npm cache with offline/ignore-scripts mode. The previously verified sidecar/runtime
was dereferenced into that temporary tree, and both Swift voice helpers compiled
there. The original repository resource directories and installed app stayed
unchanged. Tauri completed an optimized release build in 1m31s using locked,
offline Cargo dependencies and explicit `--no-sign --ci --bundles app`.

Output: `/tmp/arslan-native-candidate.xIygc5/target/release/bundle/macos/Arslan.app`
(440 MiB). The shell and both helpers are ARM64 Mach-O executables. Info.plist is
valid and retains the existing `com.arslan.desktop` / `0.1.39` metadata; no new
release version is implied. Shell executable SHA-256:
`1bfa792d73ab039ee956591ddf72b6a68d6a0e21592fc517035010609966dfdf`.

The actual sidecar inside the assembled `.app` passed fresh boot/restart/auth,
Word/PDF source extraction, six saved languages and parent-pipe shutdown checks.
Its actual compute selftest passed with two verified artifacts and denied outside
file/network access. Bundle verification passed again after Tauri copied the
resources (431 MiB sidecar), and a whole-app scan found no database or listed
secret-shaped files. The smoke driver's allowed paths now include only temporary
candidate-build/native-candidate trees; installed app paths remain excluded.

No app window was launched, installation attempted, microphone permission
requested, update contacted, signing identity used, DMG created or notarization
submitted. This does not prove native webview behavior, old-library migration,
Gatekeeper acceptance or safe publication. That assembled snapshot predates the
native update/install dialog localization described below.

Native-dialog source follow-up: nine product-owned update/install strings now
cover all six UI languages. A disposable mode-0600 `ui_language` cache is written
atomically after a committed language change and repaired from the database on
startup. It contains only a normalized locale; no provider settings or secrets
are read. Cache I/O failures do not fail the committed settings write or startup.
The native shell reads a bounded, regular-file hint before each dialog, with
English fallback for missing/invalid hints. Install/relaunch authorization,
updater behavior and the nine-command webpage allowlist remain unchanged.

The update menu label refreshes on window focus, menu actions and the existing
status poll (up to 60 seconds while continuously focused); instant same-window
menu refresh is not claimed. Native OS permission dialogs still use macOS language
selection, independently of this app-selected display hint. Initial launch before
any hint exists uses English. The original bilingual dialog defect is repaired
in source, not yet proven in the rebuilt packaged UI.

The related backend/settings/packaging selection passed 53 tests, and the complete
native Rust library suite passed 28 tests in an isolated temporary desktop tree
with locked offline dependencies. Tests cover all six hint values, bounded native
reads and symlink refusal, catalog parity, atomic replacement, commit failure,
non-fatal cache failure and startup-style repair. The current-source package
above now includes these changes. The French native menu label was observed;
complete six-language dialog/menu layout and immediate switching remain unverified.

Permission-localization follow-up: the microphone and speech-recognition purpose
strings now have native `en`, `zh-Hans`, `ja`, `es`, `de`, and `fr` `.lproj`
resources, explicitly mapped to the app resource root. macOS chooses these using
its application language settings; they are not claimed to follow the SPA's
language selector. The English fallback matches the localized English. All six
descriptions now disclose possible Apple speech processing when on-device
recognition is unavailable, matching both helpers' conditional
`supportsOnDeviceRecognition` behavior rather than promising unconditional local
processing. No recognition or permission behavior was changed.

Eight dedicated completeness/mapping/fallback tests, targeted lint, and native
`plutil` validation passed. The temporary app was rebuilt offline and unsigned
in 1m02s; all six packaged `InfoPlist.strings` files compare byte-for-byte with
source and pass `plutil`. No installed app or real permission prompt was opened.
This verifies shipped resources, not live OS language selection or permission
dialog layout; those remain in the desktop acceptance gate.

### Frozen backend preflight follow-up

Compute-runtime follow-up on `af40ed34`: the standalone Python runtime was staged
beside the temporary frozen executable using the existing staging script,
`UV_OFFLINE=1`, the local cache and all 18 hash-locked sandbox packages. The
project environment and installed app were not changed. Relocation/import checks
and real NumPy/Pandas/Matplotlib chart generation passed; no first-run dependency
download is needed for this candidate runtime.

The actual frozen `--compute-selftest` then passed: it ran through the production
code sandbox, exported verified CSV and PNG artifacts, denied reading/writing an
outside canary and denied loopback network access with permission errors. The
canary remained unchanged and artifact hashes matched stored bytes. The runtime
is 262 MiB; the assembled development sidecar is 421 MiB. Bundle verification was
repeated after adding the runtime and again passed imports/native resources and
the no-database/no-secret-shaped-file/no-forbidden-rasterizer checks. These results
do not certify every analysis library or generated program, and the assembled
sidecar is still not a signed/notarized native application or updater artifact.

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
| Complete engineering regression | Clean `6f62e8d1`: 4,929 Python tests passed, 14 skipped, including production activation; frontend 1,889 passed and rebuilt-package evidence below | Repeat after further production changes; engineering checks do not close real-task/UI gates |
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

The Mac was unlocked for the bounded native inspection above. Unverified rows
are not treated as passed, unsupported tasks are not removed, and development
checks do not substitute for the reserved real-input evaluation set.

### Subsequent input-boundary checkpoint (2026-09-19)

The shared Office reader now translates malformed DEFLATE errors into the
existing localizable invalid-file response. A failing real archive fixture
established the defect before the change. Six reader cases and three real
multipart API cases cover DOCX/XLSX/PPTX, including the already-safe unsupported
compression path. The five-file extraction/source-locator selection passed
55 tests in 6.35s; targeted lint passed. See W20 for scope. This production
change has not received a new complete backend run or native package rebuild;
the earlier clean full-run/package evidence must not be attributed to it.

The subsequent extraction request-shape fix rejects non-object JSON, non-string
URLs and multipart text masquerading as an uploaded file before extraction.
Eight failing HTTP cases reproduced the original attribute errors; ten added
cases cover those shapes and malformed JSON syntax/encoding. The five-file
input regression now passes 65 tests in 3.20s, with targeted lint and whitespace
checks passing. This remains source-only evidence; a fresh full regression and
native candidate are still outstanding.

### Input-hardening candidate rebuild (2026-09-19)

This checkpoint supersedes the earlier candidate's backend and SPA identity.
Production source was clean at `1048f20fe42adb428bab8f359533829b4f612a3e`;
only the smoke driver and this audit were subsequently edited. Frontend full
regression passed 243 files / 1,889 tests in 24.42s, TypeScript passed, and the
production build passed in 3.31s. Existing test-environment warnings and the
large-chunk warning remain. PyInstaller completed in 26.65s using the existing
isolated tooling; no dependency was installed. Native Rust source and the menu
message catalog matched the existing temporary native build exactly, so its
unchanged native executable was reused. Tauri bundled with `--no-sign`.

Candidate: `/tmp/arslan-native-candidate.xIygc5/target/release/bundle/macos/Arslan.app`.
The temporary bundle at this path was replaced, not the installed application.
Its complete packaged SPA directory matches the fresh `web/dist` byte-for-byte.
SHA-256 identities:

- Native executable: `768bc50f20e1dc7ee094483be8f3c4aa5bc8af077fda66ca6d6daa02d61d45e3`.
- Frozen backend: `aa9244f3f344fdf610ed380098d53109baf95dbaa86b9c696d5772c0caa28fb2`.
- SPA `index-CUnuiQel.js`: `ea11bc6c64081c022fc080bc9d5e617768f758650fb99b7857f26043806af230`.

Actual bundled-backend smoke passed with a disposable HOME, generated inputs,
loopback-only API calls and no real model. Coverage includes startup/restart,
authentication, six saved languages, onboarding persistence, source locators,
inert code, browser activation refusal, capability limits and parent-pipe exit.
New checks exercise malformed request shapes and corrupt DEFLATE in all three
Office formats against the frozen executable, asserting the localized 400
envelope. Bundle verification passed 15 module imports, packaged assets and
the no-AGPL/no-database/no-secret-shaped-file checks (431 MiB). The actual
bundled executable's compute selftest passed with sandbox/network isolation
and two durable artifacts under a separate temporary HOME.

This is not a signed/notarized release or a live native UI acceptance. The full
backend suite has not been repeated on this revision. All outstanding real
task, human review, migration and desktop visual gates above remain outstanding.

### Complete backend regression on the rebuilt-candidate source (2026-09-19)

Clean commit `3617083eb5eddc8a249c0baedd851f05d7de3c14` was held unchanged for
the entire run and rechecked afterward. This has the same production source as
the `1048f20f` input-hardening candidate; the intervening commit only changes
the smoke driver and audit documentation. The full backend suite passed:
**4,927 passed, 14 skipped, 18 warnings in 492.62s**, process exit 0.

Run environment: scrubbed environment, disposable HOME and ARSLAN_DATA_DIR
under `/tmp/arslan-release-regression.fkxf1Z`, synthetic secret, and
`ARSLAN_LIVE_LLM=0`. JUnit evidence:
`/tmp/arslan-release-regression.fkxf1Z/backend.xml`, SHA-256
`d3ae42b43cece4e0a3a0f167427624f7c9b5f7678fb3e65634911aecd9b68b87`.
The XML records 4,941 cases, zero failures/errors and 14 skips. Its exact skip
reasons account for 12 live-LLM evaluations, one non-macOS-only fail-closed
case, and one explicitly allowlisted operator-facing copy check.

All 30 fixed deterministic contracts in `scripts.acceptance_contracts.py`
were extracted from this same XML and passed, including backup roundtrip/live
WAL, cancellation, checkpoint preservation, recipe dependencies, network/auth
refusal, context bounds and memory scope. This is NOT 30 real agent tasks or
the 90-attempt live evaluation. The latest memory and input regressions are
now included in one full run rather than only separate focused selections.

Existing dependency deprecation, test-marking and SQLAlchemy lifecycle warnings
remain; the aiosqlite teardown guard reported 66 closed-loop deliveries. No
warning is being treated as repaired by this result. No production code changed
after the run. This closes the fresh backend-regression gap for this candidate,
not desktop visual acceptance, real-model outcomes, signed installation/
migration, credential activation or independent human/security review.

### Frozen restored-profile boot (2026-09-19)

The Mac remains locked according to a fresh native-control inventory, so native
menu and live desktop visual acceptance were not attempted against the installed
app. Instead, `scripts/frozen_restore_smoke.py` now provides a repeatable,
synthetic restored-profile boot check against the current temporary candidate.
It passed, as did targeted lint and whitespace checks. No production source was
changed, so the preceding complete regression and binary identities still apply.

The harness boots the actual candidate backend in a new disposable HOME, saves
German/onboarding state through the real API, and creates a synthetic provider
configuration pointing only to loopback port 9. It never calls model-list,
health-test or chat endpoints. After stopping the backend, it adds one generated
artifact, creates a backup with the source backup service, and restores into a
different absent profile directory. This checks the source backup implementation
plus frozen startup/migrations, NOT a bundled backup CLI or native restore UI.

The restored profile preserved the provider row, ciphertext and database salt
exactly, and preserved the artifact SHA-256. Booting it with the same synthetic
external secret returned the same masked provider configuration with key status
`set`, retained German/onboarding state, minted a new access token and rejected
the old token with HTTP 401. The archive excludes token/secret files. The restore
service reports review required; this fixture contains no memory entries or
schedules and does not establish their end-to-end quarantine acceptance. Both
owned backend processes exited through parent-pipe closure; temporary profiles
and archives were removed automatically.

This closes one concrete restored-profile check, not the old-release upgrade,
signature/notarization, user-library migration, native UI, or real task gates.

### Restored memory/schedule safety follow-up (2026-09-19)

The frozen restore harness now includes an active, user-created global memory
with cloud-use permission and a synthetic overdue schedule. The memory is
created through the candidate's real authenticated API. The enabled schedule
is inserted only after stopping the source process; the harness asserts that
restoration has paused it BEFORE starting the restored backend. No enabled
schedule is ever launched by this test.

Actual packaged API checks passed: the restored memory retains its content,
has version 2/status `quarantined`, has no confirmation timestamp and only
`local_only` policy. An edit with its old version 1 receives the exact HTTP 409
`memory_version_conflict` envelope. The overdue schedule has
`backup_restore_review_required`, remains disabled, and has zero dispatch
records before and after the bounded boot. A second restored-profile startup
preserves the same complete memory response and access token, with no additional
memory revision or schedule dispatch. Earlier provider/ciphertext/salt/artifact
and stale-token checks also passed in this expanded run. Lint and whitespace
checks passed; no production source or candidate binary changed.

This supersedes the prior empty-memory/empty-schedule fixture limitation for
these particular checks. It does not prove all restore scenarios, downstream
model-context exclusion, long-running scheduler behavior, fresh human approval
UX, or old-release migration. The source-service/frozen-boot split is unchanged.

### Actual 0.1.38 upgrade: storage passes, activation gap found (2026-09-19)

**Release blocker / next integration priority:** the actual candidate leaves
`memory_store_state.phase='prepared'` after upgrading an old profile. Migration
0047 explicitly creates only the snapshot. The only `activate_sync` caller
outside tests is `scripts/companion_smoke_app.py`, not real startup. Earlier
synthetic-app checks therefore do not prove production v2 activation. Audit
routing and legacy-write compatibility before integrating activation, then
repeat actual frozen upgrade. W04/W05 rollout is not complete.

The new `scripts/frozen_upgrade_smoke.py` uses a temporary copy of the installed
0.1.38 backend, identified by its installed Info.plist. Installed and copied
backend hashes match, before/after testing:
`578caa1f06717684f6235c0fb6039e0b41df423fa999449ed988d03580be5598`.
The candidate is the previously recorded `aa9244...28fb2` backend. No installed
app or real user profile was launched, modified or replaced.

The first run failed its expected-active assertion. The revised harness does
not activate memory in the fixture; it explicitly reports
`memory_v2_activation=missing_in_production_boot` and checks storage only.
The old backend creates French settings and a synthetic loopback-only provider
under a disposable HOME. After stopping it, the harness adds one generated
legacy manual preference/artifact and makes a pre-upgrade backup. Two candidate
boots preserve provider ciphertext/salt, decryptable masked key, language,
access token, artifact hash and backup hash; database integrity checks pass.
The old profile lacks `memory_entries`; migration creates one stable ID/version/
content snapshot of the preference across both boots and retains its legacy row.

The revised storage-only run and lint/whitespace checks passed. Temporary
profiles were removed and owned processes stopped. No model request or real
credential was used. Native installation/signing and complete upgrade acceptance
remain open, with production memory activation now an explicit integration gap.

### Production activation wired; new package acceptance pending (2026-09-19)

`server.main.lifespan` now calls `activate_sync` inside the existing boot
transaction, after schema/crypto preparation and before seeders, classifiers,
schedulers or served requests. Compatibility views and immutable recovery rows
are installed together; activation failure propagates instead of serving a
partially switched application. Existing primary legacy entry points already
branch on `is_active`, and legacy classification declines background cloud work
when active. This inspection is not proof of every possible legacy path.

A new test invokes the actual lifespan database sequence, stopping at the first
seeder to isolate background work. It failed on inactive state before the fix,
then passed on two startups with retained legacy content and compatibility views.
An additional rollback test interrupts the activation transaction and verifies
prepared state/original table/content survive, followed by successful retry.
The activation/migration/restore/runner selection passed 69 tests in 15.64s;
after adding rollback coverage, all five activation tests passed in 0.86s.
Nine compatibility/repository/tool/classifier/facts/learning/distill/brain suites
passed 72 tests in 11.07s (existing dependency warning and nine guarded aiosqlite
closed-loop deliveries remain). Targeted lint and whitespace checks passed.

The real frozen-upgrade driver now REQUIRES active state, compatibility views
and the preserved recovery row; it no longer accepts prepared state. This
stronger expectation has not yet been run against a rebuilt candidate. The
existing `aa9244...28fb2` package predates the production fix and is not accepted
as fixed. Rebuild, frozen fresh/upgrade/restore checks and a new full regression
remain required before closing the activation blocker.

### Activation candidate: actual upgrade/restore now pass (2026-09-19)

Production source was clean at `5ee448ac5774377c6075696cfd5435f5602dc745` for
the rebuild and all checks. PyInstaller completed in 26.81s using the same
isolated existing tooling. Native sources/catalog match the temporary native
build exactly, so the unchanged shell was reused. Tauri rebundled `--no-sign`
at `/tmp/arslan-native-candidate.xIygc5/target/release/bundle/macos/Arslan.app`.
This replaces only the temporary candidate. Packaged SPA matches `web/dist`
byte-for-byte; frontend source/build and native hash are unchanged.

New backend SHA-256:
`3d2df48f591019fb876444863b9540760636002e15ab64a1ce1aa6cfb9a3a4a3`.
Native SHA-256 remains
`768bc50f20e1dc7ee094483be8f3c4aa5bc8af077fda66ca6d6daa02d61d45e3`.

All three harnesses passed against the actual bundled backend, each with
independent disposable data: `frozen_sidecar_smoke`, `frozen_restore_smoke`,
and `frozen_upgrade_smoke`. The latter starts the real copied 0.1.38 backend,
then boots the candidate twice. It now proves phase `active`, compatibility
views, preserved immutable legacy preference, stable migrated identity/version,
and retained provider ciphertext/salt/decryptability, language, token, artifact
and backup. Restore still quarantines memory, rejects stale confirmation and
old tokens, pauses the due schedule without dispatch, and remains stable on a
second boot. Fresh/startup/input/language/restart checks also passed.

Bundle verification passed all 15 imports and the no-AGPL/no-database/no-secret
checks (431 MiB). No production install, user data, real model or credential was
used. This verifies the previously missing activation in an actual upgraded
candidate; it does not close all memory routing, full regression, live desktop,
installer/signature, real task or independent review gates. The previous full
backend run predates `5ee448ac` and must be repeated for this startup change.

The bundled compute selftest also passed under a separate temporary HOME:
sandboxed execution, network isolation and two durable artifacts. All launched
test processes completed; no background test or native candidate UI was left
running by this checkpoint.

### Full regression after production activation (2026-09-19)

Clean `6f62e8d14248af7bfa6bccf0e5105e9f200f0f19` was verified before and after
the entire run, with no edits during execution. It has the same production
source as the preceding `5ee448ac` packaged candidate. Results:
**4,929 passed, 14 skipped, 20 warnings in 487.42s**, process exit 0.
The run used a scrubbed environment, synthetic secret, `ARSLAN_LIVE_LLM=0`,
and disposable HOME/data under `/tmp/arslan-release-regression.KvQV9F`.

JUnit `/tmp/arslan-release-regression.KvQV9F/backend.xml` records 4,943 cases,
zero failures/errors and 14 skips. SHA-256:
`b494fab2bbcbba0ce4960c43b51308a40a6485e76d2f14082a64db5b44e66fa5`.
Skip reasons are exactly 12 live-LLM evaluations, one non-macOS-only sandbox
refusal and one documented operator-copy allowlist. All 30 fixed deterministic
contracts extracted from this same XML passed; they are not 30 real agent tasks.

Warnings include existing dependency deprecation, synchronous-test asyncio
markers, SQLAlchemy connection cleanup/cyclic metadata/null identity, and the
deliberately adversarial portal teardown cases. The aiosqlite guard reported
61 closed-loop deliveries. These are recorded, not claimed fixed.

Together with actual frozen fresh/upgrade/restore checks, this closes the
post-activation full-regression gap for the current candidate. Native visual
acceptance, complete memory/task scenarios, credential/security review and
signature/install acceptance are still not established. No release or installed
application change occurred.

### Upgraded-profile legacy API writes and deletion (2026-09-19)

The actual frozen-upgrade harness now continues beyond read-only migration.
Using the unchanged accepted candidate (`3d2df48...a3a4a3`), it obtains the
migrated preference through `/facts`, verifies its stable v2 ID/version, then
checks an unversioned edit returns 428. A versioned edit succeeds and is visible
through `/memory/entries` at version 2 while the recovery row retains its original
content. A stale version-1 delete returns 409; the current version-2 delete
returns 204. Direct inspection of the disposable database confirms a version-3
deleted stub, a single null-content revision, no FTS payload and no legacy
recovery row. The fourth candidate startup still excludes the fact and exposes
only the empty deleted stub. All these checks passed, together with the earlier
upgrade/provider/artifact assertions, and targeted lint/whitespace checks passed.

The pre-upgrade backup hash remains unchanged. This deliberately distinguishes
deletion in the active profile from erasure of independent external backups;
the test does not claim to rewrite archived backups. All material is synthetic,
no model call or real account is involved, and temporary profiles/processes are
cleaned up. Only the test harness/documentation changed, not production code or
candidate bytes. This supplies actual packaged legacy edit/delete compatibility
evidence, not full UI, all-memory-scenario or real-task acceptance.

### Additional outbound memory-boundary evidence (2026-09-19)

Five test-only bindings extend the actual host-request/receipt checks: four
sensitive-project/cloud-permission combinations (M07-07), plus restore
quarantine → excluded next task → fresh review → eligible later task (M06-05).
The focused new cases passed 6.65s, and the entire expanded binding file passed
38 cases in 75.81s. Lint/whitespace checks passed. No production source, candidate
or catalog completion status changed; model responses remain scripted. The
binding document now records partial aspects of 24 scenarios, not 60 completed
scenarios. The preceding complete backend run does not include these five newer
tests, though its production-source identity is unchanged.

### Deletion-manifest gap and bounded foundation (2026-09-19)

The approved recovery contract requires coordination with later deletion
metadata, not just blanket quarantine. Current `backup.restore` has no manifest
input, so M06-04 remains incomplete. The new isolated manifest service provides
strict bounded parsing and read-only metadata export; it is not wired into
runtime/restore/UI yet. Fifteen tests passed in 3.81s with lint/whitespace clean.
See `memory-deletion-manifest.md` for the schema, privacy limits and remaining
integration. Existing frozen candidate bytes are unchanged and do not include
this new module. No existing data or restore behavior changed; do not count the
format foundation as completed deletion reconciliation or release acceptance.

### Staged deletion reconciliation implemented (2026-09-19)

`backup.restore(..., deletion_manifest=...)` now applies validated metadata in
the quarantined staging transaction, before the final directory install.
Foreign store IDs/stale epochs/unquarantined databases are refused. Matching
IDs or same-scope revision fingerprints become content-free deleted stubs,
with sources/revision payloads/proposals/legacy recovery content erased and
tombstones retained. The absent-manifest path preserves previous quarantine
and reports that reconciliation was not applied. No runtime/API authorization
or automatic manifest discovery is added.

The manifest/backup/restore selection passed 31 tests, covering actual old
archive/later deletion reconciliation, fingerprint matching, activated legacy
payload erasure, repeat application, malformed/foreign refusal before install,
and unchanged original archive. See the manifest document for remaining work.
The current frozen candidate and full regression predate this production change;
no package or end-to-end M06-04 completion is claimed. UI/import authority,
independent latest-ledger retention and host-request verification remain open.

### Reconciled restore reaches the host-request boundary (2026-09-19)

A new M06-04 synthetic binding now covers real archive creation, later repository
deletion/manifest export, staged restore and an actual new host task bound to
the restored DB. Deleted content is absent from all captured adapter requests
and used receipts; history contains only the empty stub and repeated saving
fails with `memory_previously_deleted`. Separate tests refuse live/unquarantined
stores and stale manifests without changing deletion metadata.

The focused four-file selection passed 44 tests, 27 deselected, in 20.59s;
the new runtime case passed separately in 2.32s. Lint/whitespace checks passed.
Only tests/docs changed; no real provider was called. The binding catalog now
has 39 cases covering partial aspects of 25 scenarios, not 60 completed cases.
Trusted import/export UI, independently retained current manifests and actual
packaged manifest restore remain open; source request evidence alone does not
close the full recovery contract.

### User-facing deletion-record export (2026-09-19)

Added an authenticated no-store attachment endpoint and explicit Settings →
Memory & Data download control. Six-language copy describes the privacy,
separate-storage/re-export requirement and absent restore import. No automatic
file discovery, import authorization or ledger persistence is inferred. Export
failure stays generic, duplicate clicks are fenced and departed results cannot
start a download. Backend API/manifest selection: 36 passed (1.53s). Frontend
two-suite selection: 8 passed (1.61s), including URL release. TypeScript and
targeted lint/whitespace checks passed. See the manifest document for scope.
Native download and live layout remain unverified; current frozen package and
previous full suites predate these source/UI changes.

### Restore interruption and current frontend regression (2026-09-19)

Two new failure-injection cases interrupt staged reconciliation immediately
after revision erasure and after successful reconciliation but before commit.
Both prove that no destination or temporary restore directory remains, the
input archive and live deletion manifest stay unchanged, and retrying the same
archive/manifest succeeds with a content-free deleted stub and a healthy DB.
These are caught-exception tests, not power-loss or filesystem-crash tests.

The complete manifest/backup/restore/runtime four-file selection passed 73 tests
in 78.80s, with one dependency deprecation warning, using an isolated temporary
home/data directory and synthetic encryption secret. This includes all 39
scripted runtime bindings. An initial invocation without the synthetic secret
had 26 passes and 8 backup fixture failures: the existing insecure-secret guard
correctly refused encryption; no security policy was weakened to rerun them.

Current frontend regression passed all 244 files / 1,893 tests in 22.01s;
existing React act/i18next warnings remain. TypeScript, targeted lint and
whitespace checks passed. Only tests/docs changed in this checkpoint. Full
backend regression and frozen-package verification still predate the manifest
implementation; native download, trusted import and independent ledger storage
remain open. No real provider calls, publication or installed-app replacement.

### Candidate rebuilt with deletion metadata export (2026-09-19)

Rebuilt web assets (3.96s; existing large-chunk warning) and the frozen backend
(29.25s) from clean `99b826be5431cef90fbced29dbd0b66cbe14c9bd` production
source. Tauri's existing isolated bundling path produced an unsigned temporary
app at `/tmp/arslan-native-candidate.xIygc5/target/release/bundle/macos/Arslan.app`.
XcodeBuildMCP context was checked; no macOS workflow tools were available, and
this Tauri app used its existing project build rather than raw Xcode commands.
Native source/localization resources still match the isolated native build;
only the sidecar and web resources were refreshed. No installed app was changed.

Identity:

- Backend: `c83fe225bff2349332770559a523a52d89baa249b2fc42f0698b75d0a2a7a5e0`.
- Native: `768bc50f20e1dc7ee094483be8f3c4aa5bc8af077fda66ca6d6daa02d61d45e3`.
- SPA `index-Cg1uNwNW.js`: `a55a36155cbc890e14a6b0a43552bbdf2f8f809b06d21681976d68f72e1eeac2`.

The packaged web tree exactly matches the current production build. Both frozen
and staged-app bundle verifiers passed (15 module imports, assets, no forbidden
rasterizer/database/secret-shaped files); the staged app sidecar is 431 MiB.
Actual packaged compute self-test passed with network isolation and two durable
artifacts. Fresh boot/restart/input/six-language tests, quarantined restore with
paused overdue schedules, and actual copied 0.1.38-to-candidate four-boot upgrade
including legacy edit/delete all passed using disposable profiles.

The new `frozen_deletion_restore_smoke` also passed: actual frozen API deletion
and private export, source-coordinated restore of an older archive, then two
actual restored boots prove the deleted content stays absent and cannot be
re-saved; the other memory stays quarantined and the archive is unchanged.
It explicitly does not test native import/download or capture frozen host
requests. The new harness is not a production-code change.

Mac UI inspection returned locked; no native candidate window was launched.
Native download/layout, trusted restore-import UI, independent ledger retention,
signing/notarization and the other existing release gates remain open. This
candidate is not declared release-ready and has not been published.

### Full regression including deletion-manifest production code (2026-09-19)

Full backend run started from clean `99b826be5431cef90fbced29dbd0b66cbe14c9bd`
and passed **4,959 tests**, with **14 skips / 21 warnings**, in **505.42s**
(exit 0). Production code and collected tests were unchanged during the run;
only the separately executed frozen deletion smoke harness and audit documents
were added while it ran. The process used scrubbed environment, temporary
HOME/data storage and a synthetic encryption secret, with live LLMs disabled.

JUnit evidence: `/tmp/arslan-full-regression.2Xv6dz/backend.xml`;
SHA-256 `145092a826a7a90f846618e8af7ff20adfeb34e25ad92617abc58f4fd92098e4`.
Parsed XML confirms 4,973 cases, zero errors/failures and 14 skips. All 30 fixed
engineering contracts extracted from the same XML passed; these are not the
separate real-task quality gate. Skips remain 12 live-model cases, one real
non-macOS sandbox-refusal case and one allowlisted operator-facing copy case.

Warnings cover dependency deprecation, existing sync/async test markings,
SQLAlchemy connection cleanup/cyclic metadata/NULL identities, and intentional
portal teardown fixtures. The test guard reports 84 attempted aiosqlite
deliveries into closed loops; no test outcome was affected, but the run is not
described as warning-free. All test/smoke processes completed and no candidate
UI was launched or left running. Targeted harness lint and whitespace checks
passed. This closes the latest full-backend and package-refresh gap, not the
remaining native UI, live task-quality, import/ledger or release gates.

### Independent local deletion record and visible status (2026-09-19)

Added a private per-instance file mirror independent of SQLite/backup snapshots,
updated after committed repository and legacy expert-preference deletions and
repaired at startup before background work. Rolled-back changes never persist;
storage failures cannot undo an already committed deletion. Monotonic epochs,
history-subset checks, bounded cross-process locking, atomic replacement,
private permissions and no-follow access protect the record. It contains only
the existing bounded deletion metadata, not deleted text or digest keys.

An authenticated no-store status endpoint and explicit six-language Settings
check expose current/missing/stale/ahead/unavailable states without private
paths or error diagnostics. Copy describes a last-checked local record, not an
external backup or a completed restore. See `memory-deletion-manifest.md` for
failure semantics, POSIX support and the non-atomic DB-to-file crash window.

Eight backend files passed 77 cases in 4.98s; two frontend suites passed 17 cases
in 2.05s. TypeScript, targeted lint, whitespace checks and production web build
(3.31s) passed. Concurrency initially exposed a first-lock-creation race; the
exclusive-create/open-existing fix passed ten parallel first-write rounds.
The complete backend suite and frozen candidate above predate this production
change and must be rerun/rebuilt. Restore's automatic ledger selection, trusted
import UI, native visual/download checks and other release gates remain open.
No real profile was migrated, model/account called, app installed or release
published. New filesystem tests use disposable data only.

### Recovery selects current installation records before staged install (2026-09-19)

The restore service accepts an explicitly trusted current DB path, opens a
read-only SQLite snapshot, discovers its independent ledger by store UUID and
compares an optional imported manifest. It selects the highest consistent epoch,
requires older histories to be contained, rejects same-epoch divergence and
refuses corrupt/foreign/unsafe local records. Missing or behind mirror files can
be supplemented by the committed DB; a newer ledger cannot be replaced by an
older DB. All source files and the old backup remain untouched. Reconciliation
still occurs within quarantined staging, before installation into a new path.

Offline restore now exposes the current-DB and bounded manifest-import options,
including a new-machine import without a local installation. The command's help
states that Arslan must already be stopped; no running process is stopped or
automatically certified absent. This is not yet a native restore/import UI.

Six-file backend selection passed 109 cases in 83.27s, including all 40 scripted
runtime bindings; the new current-installation M06-04 variant checks actual
adapter requests, receipts, deleted stubs and repeat-save refusal. After
tightening exact error assertions and CLI help, the 19-case selection/CLI suite
passed in 1.71s. Targeted lint/whitespace checks passed. Scenario completion
remains partial aspects of 25/60, not a 60-scenario or real-model quality pass.
Latest full regression and frozen candidate predate both the independent mirror
and this selection path. Native trusted restore/import, runtime stop/activation
coordination, native UI/download checks and the other release gates remain open.

### Packaged profile/recovery mutual exclusion prerequisite (2026-09-19)

Inspection found that stopping one shell-owned sidecar alone would not rule out
another packaged copy using the same DB. A new POSIX profile lock now spans the
packaged server run, and current-installation restore takes the same lock before
staging. Busy profiles are refused without waiting or signalling their owner.
The persistent empty lock file is private, validates owner/type/link count,
refuses symlinks and uses OS locking rather than PID/stale-file heuristics.

Packaged startup emits only a fixed busy/unavailable code before a port line;
the native handshake converts known codes into six-language product copy. Its
failure/timeout paths reap only the newly spawned child. No automatic app stop,
database switch, overwrite, native restore button or release action was added.

Six Python test files passed 77 cases in 3.03s, including actual synthetic
process death/reacquisition, same-profile refusal, independent profiles, unsafe
lock slots, packaged-entry ordering, restore refusal before staging and retry.
Targeted lint/whitespace checks passed. XcodeBuildMCP skill/context was checked;
no macOS workflow tool was available for this Tauri project. The established
isolated Cargo fallback compiled the updated native source in 8.47s and passed
all 31 native tests (0.06s). Native source/catalog were copied only into the
temporary build workspace; the release executable and app bundle have NOT yet
been rebuilt with these changes. No real app was launched or replaced.

This is cooperative POSIX protection for the packaged entry, not proof against
older/uncooperative binaries, plain uvicorn launches, every child-process writer
or manual filesystem replacement. The explicit stop-all-writers requirement
therefore remains. Full regression, current frozen lock tests, native visual
checks and the complete trusted recovery/activation workflow remain open.

### Frozen repetition exposed acknowledgement-before-commit (2026-09-19)

The profile-lock candidate was rebuilt from `540ae8b6` (web 3.37s, native
release build 69s, PyInstaller 26.83s) and exercised with a stronger frozen
deletion harness. Initial checks passed, but a second run against the staged
app found fewer restored memories than the two acknowledged creates. That
candidate backend (`5fe375bd...359f58d`) is NOT accepted on the strength of its
earlier successful run. Its native executable is
`1db50bd7eb44c77c1348d7ef1f4c8a172f3b50217b71e7f881e7b4deba55c650`.

An ASGI send-boundary test then reproduced the underlying defect deterministically:
normal creation sent HTTP 201 before commit; an injected SQLite commit conflict
also sent 201 even though persistence failed. Both new assertions failed before
the fix. All companion repository dependencies now use function scope so commit,
rollback and mapped errors occur before response transmission. The six-file
selection passed 86 tests in 5.69s after the fix. Full frontend regression on
the unchanged UI passed 244 files / 1,902 tests in 22.61s (existing React/i18next
warnings). Targeted lint/whitespace checks passed.

The strengthened frozen harness also checks independent-record persistence and
startup repair, duplicate-process refusal without harming the owner, active
profile restore refusal, stopped-current-installation selection, and two
restored boots. It must be rerun against a newly rebuilt fixed backend; prior
passing profile checks alone do not close the acknowledgement defect. This is
not a UI or real-model test, and the restore coordinator remains source code.

### Fixed candidate and complete offline regression (2026-09-19)

Production source `07e5886f` was clean when the full backend run began. It passed
5,009 tests, with 14 skips and 18 warnings in 505.72s; process exit was 0.
The JUnit report at `/tmp/arslan-commit-regression.1jmwX1/backend.xml` contains
5,023 cases, zero failures/errors, and all 30 engineering acceptance contracts
passed. Its SHA-256 is
`27364b126d20dc7ce3245b077548a89bc436211681747a3adbe1690ceef09425`.
Skips are 12 opt-in live-model evaluations, one non-macOS-only sandbox refusal
and one operator-copy allowlist. Warnings include existing deprecations, async
marks, SQLAlchemy connection/schema warnings and deliberate teardown fixtures;
the aiosqlite guard reported 63 closed-loop deliveries. This is not a clean
warning run or a real-model quality score. Frontend remains 244 files / 1,902
passing tests; unchanged native source has 31 passing unit tests.

The fixed backend was rebuilt in 26.08s and staged into the unsigned temporary
app at `/tmp/arslan-native-candidate.xIygc5/target/release/bundle/macos/Arslan.app`.
Exact packaged executable hashes:

- Backend: `11902688744d525ea461769acf874e4bd043e967602320c26d11a065951493c6`.
- Native: `1db50bd7eb44c77c1348d7ef1f4c8a172f3b50217b71e7f881e7b4deba55c650`.
- SPA: `5343cbf8b9e0030636cc5d1f52d138ccbc1419c70a1b3b42897c8f530c74cef7`.

The enhanced deletion/restore harness has three observed successful runs on the
fixed backend: one against the build output and two against the app resource.
It includes immediate shutdown after two acknowledged creates, mirror repair,
same-profile process refusal without stopping its owner, active-profile restore
refusal, current-installation record selection and two restored boots. Additional
app-resource checks passed fresh startup/restart, six saved languages and input
formats, actual old-release upgrade (four candidate boots), quarantined restore,
and sandboxed/network-isolated compute with two durable artifacts. Bundle
validation passed. Lost tool-output observations are not counted as evidence;
the affected terminal smoke runs were repeated and their exit-0 results observed.

All data/accounts were synthetic and disposable; no real model, installed app,
signing, publication or user profile was used. Restore coordination is still
source-side, not the native import/activation UI. Native visual checks, trusted
recovery activation, live-model evaluation, external review and release gates
remain open. The rejected backend described above is superseded, not accepted.

### Atomic no-overwrite recovery installation (2026-09-19)

A deterministic race test found that the final `exists()` check followed by
ordinary `os.rename()` could replace an empty directory created after the check.
The pre-fix test failed with DID NOT RAISE; thus the previously stated
no-overwrite guarantee was too strong at this final boundary.

Restore now uses Darwin `renamex_np(RENAME_EXCL)` or Linux
`renameat2(RENAME_NOREPLACE)` for kernel-enforced exclusive installation. Darwin
declarations/flag were checked against the installed SDK's `sys/stdio.h` and
`sys/attr.h`; Linux semantics were checked against the
[Linux manual](https://man7.org/linux/man-pages/man2/rename.2.html).
Unsupported platforms, missing symbols and filesystem refusal fail closed;
there is no check-then-rename fallback. This protects the final entry, not
hostile ancestor replacement or physical power-loss durability, and requires
trusted same-filesystem parents.

Five relevant test files passed 67 cases in 2.98s, with one existing Starlette
deprecation warning. Coverage includes preserving the exact concurrently created
directory inode, unchanged archive and staging cleanup, explicit retry, existing
files/directories/live and dangling links, eight concurrent installers with one
winner, unsupported environments, and both platform call signatures. Actual
filesystem execution was on macOS; Linux binding checks are simulated, not a
Linux runtime validation. Targeted lint and whitespace checks passed.

The deletion/restore smoke also passed using the new source coordinator with
the previous `11902688...` packaged backend, including two restored boots.
This does NOT claim the updated helper has been rebuilt into that candidate.
The 5,009-test full regression predates this change; the evidence above is the
current targeted regression. Native restore UI/activation and broader release
gates remain open. No installed app or real profile was touched.

### Actual packaged offline recovery coordinator (2026-09-19)

`5fba717d` adds `arslan-server --restore-offline` dispatch before normal profile
bootstrap. Its argument parser requires an explicit stopped current DB or
`--new-machine`, accepts a bounded separately exported deletion record, and only
installs into a new directory. It neither starts HTTP nor activates the result.
The shared manifest reader also serves the existing source CLI. Operational
failures produce bounded JSON (`restore_refused`, or `data_profile_in_use`), not
tracebacks containing archive data or paths. Invalid arguments exit through the
parser. This local maintenance command is not an authenticated web endpoint or
a substitute for the future trusted native picker/confirmation workflow.

Seven focused files passed 104 tests in 3.67s (one existing Starlette warning).
Lint and whitespace checks passed. PyInstaller rebuilt unchanged production
sources from this commit in 26.61s; the commit was recorded during the build,
and only smoke-harness changes followed. The new standalone sidecar is at
`/tmp/arslan-candidate-build.BboGj4/dist-offline-restore/arslan-server/arslan-server`,
SHA-256 `07f1f5dac91622bfb2445989e7296d7ad382658401f203c8be593d639bfa171e`.
It contains the exclusive-install helper from the preceding checkpoint.

Two observed packaged deletion/restore runs passed. Recovery now executes in
the binary itself, rather than the source coordinator. Checks cover active
profile refusal, current DB/independent ledger selection, new-machine manifest
import, existing-target inode preservation, unchanged archive/export, and two
restored server boots with deletion suppression and remaining-memory quarantine.
The second run used a separate empty maintenance HOME and verified it remained
empty: no implicit default profile, access token or secret bootstrap.
Backup creation is still source-side. All fixtures are synthetic; no real model,
installed app, native import UI or normal-user profile was used.

This standalone sidecar has not yet replaced the prior temporary app's resource
or undergone a new full-suite run. Native selection, confirmation, stop/restart,
activation rollback, complete UI checks and the broader release gates remain
open. A command returning success does not mean the restored profile is active.

### Desktop candidate includes guarded packaged recovery (2026-09-19)

Production commit `b83914c3` rejects unknown/ambiguous process arguments before
environment sanitization, profile locking or any server/selftest mode. Selftests
now require an exact single flag; restore options are parsed only after the
leading offline-restore flag. This closes accidental normal startup after a
misspelled or reordered maintenance invocation. Seven related test files passed
110 cases in 3.80s, with one existing Starlette deprecation warning; targeted
lint/whitespace checks passed.

PyInstaller rebuilt the backend in 26.56s. The existing isolated compute runtime
was copied into this new build, 9,240 files were staged, and Tauri rebundled the
temporary app unsigned. XcodeBuildMCP skill/defaults were checked (all defaults
unset, no macOS workflow available); the Tauri fallback did not use raw Xcode
commands or change project settings. The native executable was unchanged.

Current app: `/tmp/arslan-native-candidate.xIygc5/target/release/bundle/macos/Arslan.app`.
Backend SHA-256:
`f0251905b4ec3c7ab37431bcf493c931058636d59f3368f68a2481da0db10ba9`.
Native SHA-256 remains
`1db50bd7eb44c77c1348d7ef1f4c8a172f3b50217b71e7f881e7b4deba55c650`.
Bundled SPA tree exactly matches current `web/dist`.

Observed exit-0 checks against the app resource: fresh startup/restart and
six-language/input-format smoke, actual old-release upgrade with four candidate
boots, packaged deletion-aware restore with two restored boots, module/resource
and forbidden-file bundle validation (431 MiB), and network-isolated sandboxed
compute with two durable artifacts. The strengthened recovery harness also
invokes four invalid mode combinations and verifies exit 2 with only the fixed
error code. Maintenance subprocesses now receive NO secret variables and use an
empty disposable HOME; it remains empty after current-installation restore,
new-machine manifest import and overwrite refusal. No key bootstrap is hidden
by supplying a synthetic key to those maintenance subprocesses.

The Mac was rechecked and remains locked, so no native visual/UI pass is claimed.
The latest full 5,009-test regression still predates these recovery changes;
110 targeted cases and the explicit current-package checks are the new evidence.
Native picker/confirmation, owned-process stop/restart, reversible profile
activation and broader live-quality/signing/release gates remain unfinished.
No formal installation, real profile, model call, signing or release occurred.

### Stable ownership across a future profile switch (2026-09-19)

Before implementing activation, a new test reproduced another ownership gap:
moving the active directory also moves its inner lock inode, so a second caller
could create a replacement directory at the original path and acquire a new
inner lock. The pre-fix test failed when the second caller became an owner.

The shared packaged/maintenance lock now acquires a stable outer lock in the
profile directory's parent before it creates the profile directory or acquires
the original inner DB lock. The outer filename is a SHA-256 namespace of profile
directory name and DB name; it contains no contents, token or PID. Both files
use the existing private-file checks and OS locking and are never unlinked.
The inner lock remains for compatibility with the preceding packaged version;
failure there releases outer ownership. No directory activation was wired in.

Six focused test files passed 111 cases in 3.32s, with one existing Starlette
warning; targeted lint/whitespace checks passed. Coverage includes directory
move with and without a replacement, refusal before recreating a missing active
directory, a real competing subprocess, unsafe outer symlink/hardlink/FIFO/mode,
legacy inner ownership, exception cleanup and process-death release.

This changes the cooperative ownership prerequisite, not a complete rollback
journal or native recovery flow. Trusted parent paths and stopping all older or
uncooperative writers remain required; old binaries do not acquire the outer
lock and are not protected throughout directory switching. The current app
bundle and latest full regression predate this change. No real profile, installed
app, provider or published build was touched.

### Read-only credential compatibility prerequisite (2026-09-19)

Added `recovery_preflight.check(database, secret)` for a trusted stopped-profile
activation caller. It reads a checkpointed standalone DB with SQLite read-only
immutable access, refuses WAL/SHM/rollback sidecars instead of ignoring pending
data, and returns only bounded status/counts. It never discovers/generates a key,
adopts a process salt, repairs ciphertext, invokes a provider or activates a
directory. The original secret must be supplied in memory, not a command line.
Writer exclusion remains the caller's responsibility; this is not a live-DB
probe or proof of all restoration/authorization requirements.

Pure key derivation was factored out of normal crypto initialization, preserving
PBKDF2/current and legacy read compatibility. Existing runtime caching remains
at the original wrapper. Inventory review found SSH private identity and MCP
OAuth token/client rows absent from the boot crypto sweep. A shared inventory
now includes them, along with the three secret settings, provider keys and MCP
environment values. Boot diagnosis and verified legacy migration use this same
inventory; public SSH identity and ordinary settings remain excluded.

Eleven crypto/preflight test files passed 118 cases in 30.60s before the final
journal guard, with existing Starlette and SQLAlchemy cleanup warnings. The
expanded final preflight suite passed 25 cases in 3.36s (Starlette warning only).
Coverage includes all eight synthetic credential sites, one-site corruption,
wrong/missing keys, missing/corrupt salts, valid legacy reads, verified/idempotent
legacy migration, empty OAuth exclusions, oversized/blob/non-UTF8 credentials,
count limits, symlinks, missing DBs and pending journals. A fresh subprocess
verified no config/normal-crypto import or HOME bootstrap. DB bytes and process
salt stay unchanged; a checkpointed WAL snapshot creates no sidecars even while
the read connection is open. Targeted lint/whitespace checks passed.

This prerequisite is NOT yet exposed through native recovery or the packaged
maintenance command, and does not complete the activation journal/rollback.
The latest frozen bundle and full-suite result predate this change. No actual
credential, user database, installed app, model account or release was used.

### Internal journaled switch and retryable rollback substrate (2026-09-19)

Added an internal same-parent/same-device profile switch substrate. It acquires
both profile locks, runs the credential preflight, and reconciles the latest
current deletion records again before switching (records may have advanced after
the restore was prepared). It writes an exclusive private journal, fsyncs it and
its parent, then uses exclusive renames to retain the original directory under
a unique sibling name and put the candidate at the active path. No profile is
deleted. A journal contains only operation/name/directory-identity metadata.

Recovery infers state from recorded device/inode identities rather than trusting
a phase that might not have been updated before a crash. Rollback accepts only
three exact layouts, preserves the candidate, restores the original, and clears
the record only after verifying the final layout. It can be retried after its
own interrupted rename. Invalid/private-file violations, unknown directories,
links, traversal and changed identities refuse action; no guessed overwrite or
cleanup is performed. Parent paths and all older/uncooperative writers still
must be trusted/stopped.

Normal packaged/maintenance ownership now refuses any pending activation record
BEFORE recreating a temporarily absent profile. The packaged entry test confirms
no server/port announcement and the existing generic unavailable error. There is
no public switch/rollback command, native button, trial-boot exception or finalize
operation yet. This intentionally leaves the switched state blocked until the
internal rollback is used; it is a substrate, not an enabled user recovery flow.

Six related test files passed 122 cases in 10.78s, with one existing Starlette
warning. Tests interrupt after durable record creation, after each forward move,
and during rollback; original DB bytes, both directory identities/markers and
archive bytes are retained. A synthetic subprocess exits abruptly with `os._exit`
after the first move; another process then rolls it back successfully. Late
deletion records are re-reconciled, while wrong credentials, foreign/unrestored
candidates and busy profiles refuse before moving the original. Targeted lint
and whitespace checks passed. These are real local filesystem/process tests,
not physical power-loss durability or a packaged/native activation pass.

Trusted trial boot, health verification, finalize/rollback coordination, native
confirmation, six-language recovery guidance and a new full/frozen regression
remain open. No user profile, installed app, model, secret file or release was
used. The active goal is not release-complete.

### Trial-process ownership without a generic journal bypass (2026-09-19)

Added internal `trial_ownership(active, operation_id, secret)`. It owns the stable
lifecycle lock, validates the private journal and exact completed-switch layout,
then owns the candidate's inner lock and repeats credential compatibility with
the secret actually supplied to the trial. A prior successful switch preflight
cannot make a launcher using a different key acceptable. No `ignore_journal`
boolean, HTTP route or generic normal-boot exception was added.

The operation ID binds a trusted coordinator to its journal; it is metadata, NOT
a user approval or security credential. Normal boot, another trial and rollback
remain excluded for the lease's lifetime. Leaving the context releases ownership
but does not finalize the switch or remove the journal; normal boot is still
blocked until the unfinished coordinator deliberately finalizes or rolls back.

Six focused files passed 128 cases in 13.32s, with one existing Starlette warning;
targeted lint/whitespace checks passed. Tests cover incomplete switch phases,
wrong operation/key/missing key, changed layout, ownership conflict and retained
journal/profile contents. A real synthetic subprocess acquired the trial lease,
received its synthetic secret over a pipe rather than arguments, excluded parent
rollback, and released ownership when the parent closed the pipe. Rollback then
succeeded. This is a process-ownership test, NOT a running backend health test.

Inspection of `server.main.lifespan` confirms that ordinary startup schedules
classification/reaper/background loops and optional MCP checks. Consequently the
trial lease is not yet wired to ordinary `_serve()`: a restricted boot/health
path must prevent those actions before any native recovery activation is enabled.
Native confirmation, restricted health checks, finalization, packaged validation
and broader release gates remain open. No real app/profile/provider was used.

### Restricted local trial health application (2026-09-19)

Factored normal startup's transactional storage sequence into `storage_boot`:
table setup, migrations, salt adoption, verified legacy-ciphertext migration and
memory activation, in the same order/transaction. Normal `main.lifespan` calls
this shared implementation; it still performs its existing work afterwards.
The new internal `activation_trial` app calls only the shared storage stage and
startup settings validation while holding exact-journal trial ownership.

The factory requires an already prepared configuration (it will not import config
to bootstrap a key), a distinct 64-hex-character trial token, and configuration
whose DB/data paths match the switched active profile. Actual startup key checks
occur when acquiring the lease, not at factory construction. It uses its own DB
engine and disposes it before releasing ownership. It does not run the normal
lifespan, seeders, classification, reapers, timers, MCP checks or business routes.

Only `GET /api/v1/activation-trial/health` exists, with bearer authentication,
operation-bound readiness and no-store responses. Docs/OpenAPI, settings/memory
routes, MCP and WebSockets are absent. Readiness is set only after successful
local initialization and cleared on shutdown/failure. Readiness is not approval,
full normal-app readiness, model quality or finalization; the journal remains.

Six related files passed 113 cases in 16.73s, including the existing real normal
lifespan migration-order tests. Targeted lint/whitespace checks passed (one
existing Starlette warning). The restricted app was tested both with ASGI client
and with a real dedicated Python/uvicorn process on OS-assigned loopback HTTP.
Valid health, unauthorized refusal and business-route absence were observed;
parent-pipe closure stopped that synthetic process, released locks, left HOME
empty and allowed rollback. Tests also inject boot failure, change the configured
key after construction, refuse another profile's data path, verify no implicit
config import in a fresh process and forbid normal background startup functions.

This is source-process validation, not the frozen entry/native launcher. There
is still no public trial flag, native recovery UI, automatic finalize or release
activation. Native token/secret preparation, authenticated trial orchestration,
health-checked finalization, packaging and full regression remain open. No real
profile, installed app, provider call, signing or publication occurred.

### Packaged trial pipe entry and WAL-safe restore verification (2026-09-19)

`--activation-trial` now dispatches only to the restricted app. A fresh process
requires one bounded stdin-pipe JSON message within 10 seconds (16 KiB total,
8 KiB secret bound, exact keys, canonical operation UUID and 64-hex trial token).
Secrets/tokens are not command arguments. The normal packaged path sanitizer
removes data/DB overrides; the message cannot choose a profile path. Its explicit
original secret is installed in process memory/environment and secret-file
bootstrap is disabled before config is imported. A preloaded runtime is refused.
The trial binds an OS-assigned loopback port with a distinct trial handshake.
Parent-pipe EOF requests graceful exit with a five-second self-exit fallback;
there is no generic normal-server route or journal-bypass mode.

The first full frozen-chain attempt was correctly refused by credential preflight
as `preflight_unavailable`, not a successful activation. Investigation reproduced
lingering restore-side SQLite connections, then confirmed that even a closed
read-only WAL integrity connection can leave WAL/SHM files. Backup/snapshot
connections now close explicitly. Integrity checks of our closed standalone
snapshots/staging use immutable read access only after refusing existing WAL/SHM/
rollback journals (including symlinks). The strict activation preflight was NOT
weakened. A regression retains connection references and disables GC, verifies
explicit closure and no sidecars, then successfully invokes preflight.

Six focused files passed 132 cases in 17.22s, with one existing Starlette warning;
lint and whitespace checks passed. The source entry test supplies a wrong inherited
secret and wrong data/DB/key-file overrides, then confirms only the pipe inputs
and fixed disposable-home profile are used. Parser coverage includes duplicates,
unknown fields, malformed/missing credentials, size limits, incomplete EOF,
partial-message timeout and trailing data.

Production sources recorded in `1c7fceac` were rebuilt into the standalone sidecar
in 28.18s (commit recorded after build, no intervening production edits):
`/tmp/arslan-candidate-build.BboGj4/dist-trial-fixed/arslan-server/arslan-server`.
SHA-256 `1af4dbff69eecda918b2ef4579bed307015d3e9fdb125026ded943e99800fd89`.
Its actual frozen trial passed normal authenticated startup, source backup/restore
and journaled switch, pipe-controlled restricted HTTP, unauthorized/business-route
refusal, parent closure, source rollback and normal restart with the synthetic
stored key still readable. Original DB bytes remain intact; neither inherited
override path nor key file is created, and captured trial output contains neither
pipe secret nor token. The current frozen deletion/restore harness also passed
packaged maintenance, record selection/import, profile exclusion and two restored
boots. Source coordination versus frozen execution is explicit in both reports.

The temporary desktop app resource has not yet been replaced by this sidecar.
Finalization, native confirmation/orchestration, full regression, native visual
checks and broader release gates remain incomplete. No real profile, account,
installed app or publication was involved; health success did not finalize data.

### Internal health-bound finalization (2026-09-19)

Restricted trials now invalidate any older success receipt on entry. Only an
authenticated health request followed by graceful lifespan completion and engine
disposal creates a private receipt bound to the operation, candidate directory
identity and SHA-256 of the closed database. The coordinator must independently
observe HTTP success and child exit; the receipt is not user authorization.

The internal `finalize` helper rechecks ownership/layout, receipt, database bytes,
credential compatibility and the original profile's latest deletion records under
locks. An exclusive journal rename commits completion and removes the ordinary
startup block. The original directory and completed metadata remain retained.
Retry after a lost acknowledgement recognizes the completed layout. No public
finalize entry, native confirmation or automatic activation was added.

Three focused suites passed 76 tests in 23.60s (one existing Starlette warning),
covering successful finalization, missing/corrupt/unsafe/stale receipts, wrong
operation/key, unobserved health, newer-trial invalidation, advanced original
deletion records and acknowledgement loss after commit.
An additional pre-commit rename-failure test passed in 1.35s, proving ordinary
startup remains blocked and rollback remains available; targeted lint and
whitespace checks passed.
This is source validation; the previously documented frozen sidecar does not
contain these changes. Native
orchestration, rebuilt packaging and full regression remain open. No real profile,
account, installed application or publication was touched.

### Frozen health receipt and both activation outcomes (2026-09-19)

Production code at `12365255` was rebuilt in 26.83s as the standalone sidecar:
`/tmp/arslan-candidate-build.BboGj4/dist-finalization/arslan-server/arslan-server`.
SHA-256 `dff8a9e2bc73d0fa9535c38e0dd7ba8874f6e24e6cc118baddcca1bbd1e48797`.
The synthetic smoke harness now has an explicit `--finalize` option; its default
still exercises rollback. Both modes passed against that same frozen binary in
separate disposable homes. Each starts the normal frozen server, stores a fake
encrypted provider key, stops it, restores/switches via source coordination, runs
the frozen restricted trial with pipe credentials, observes authenticated health,
refuses unauthorized/business routes and waits for graceful parent-pipe shutdown.

Rollback preserves the original database bytes and permits normal frozen restart.
Finalization consumes the frozen process's health receipt through the source
helper, retains original database bytes, permits normal frozen restart with the
stored key readable, and remains idempotent after normal startup has written to
the active database. Inherited wrong-key/path canaries remain unused; captured
trial output contains no supplied secret/token. Lint and whitespace checks pass.

This verifies frozen receipt production and normal restart, not a frozen/native
finalization coordinator, user confirmation UI, independent security review or
full application regression. The complete temporary desktop bundle has not been
updated. No installed app, real profile, provider request or publication changed.

### Six-language pending-recovery startup guidance (2026-09-19)

The packaged entry now preserves the exact trusted `data_profile_recovery_required`
ValueError as a bounded handshake code instead of misclassifying it as a storage
permission problem. Unknown exceptions and OSErrors remain generic and never echo
paths or diagnostics. Rust recognizes the exact code and uses product-owned copy
in all six languages. The copy explains the startup pause and warns against
deleting/moving data folders or recovery records; it does not invent a recovery
button or claim no directory switch has occurred.

The native skill's session check found no configured Xcode project, scheme or
device; this Tauri project was validated using its Rust library tests with an
isolated temporary HOME/target and offline dependencies. All 31 native tests passed,
including exact error-code mapping and six-language catalog coverage. This is not
a rendered desktop dialog or user recovery workflow acceptance. The entry tests
cover refusal before recreating an absent profile, record preservation and generic
handling of private diagnostics. No normal server starts on these failures.
All 39 entry tests passed in 0.52s with one existing Starlette warning; targeted
lint and whitespace checks passed.

The full recovery picker, explicit user confirmation, native secret preparation
and orchestration remain unimplemented. Previously built sidecars and the complete
temporary desktop app predate this new handshake/copy. No real data, account,
installed app or publication was changed.

### Refuse normal startup before secret bootstrap (2026-09-19)

Review of original-secret preparation found normal packaged startup imported
configuration before acquiring profile ownership. A pending-recovery or busy
profile could therefore trigger first-boot key generation before being refused.
Path resolution now lives in a pure stdlib module shared by configuration and
the entry point; the entry acquires ownership before configuration is imported
by normal serving. Platform defaults and packaged override sanitization are
unchanged. This does not implement the native original-secret reader yet.

Fresh-process tests omit explicit keys and disabling flags, exercise actual
default paths under disposable HOME, and prove both pending-recovery and busy
refusals leave `server.config` unloaded and no `.arslan` secret directory or DB.
The pending case preserves the journal and does not recreate the active folder.
Initial tests exposed fixture assumptions about preloaded settings and stripped
path overrides; those fixtures were corrected to exercise the new pure resolver
and real sanitized default path. No real user profile was used.

The three targeted suites cover entry behavior, platform paths and existing
secret-bootstrap compatibility: 71 passed in 0.72s, with one existing Starlette
warning; targeted lint and whitespace checks passed. Frozen rebuild and complete regression remain
required; no installed application or release artifact was replaced.

### Frozen pre-configuration refusal and full-regression launch (2026-09-19)

Production source `dea967d8` was rebuilt in 31.26s into
`/tmp/arslan-candidate-build.BboGj4/dist-preconfig-lock/arslan-server/arslan-server`.
SHA-256 `027253cf67100f5a565c27ee6aec7f775a72673b8c398e64298bafc61fcbb691`.
The strengthened frozen harness passed both source-coordinated finalize and
rollback branches. Before each restricted trial, a fresh normal frozen process
with no explicit secret or secret-file override returned exactly the pending
recovery code and exit 1 without creating `.arslan`. Authenticated trial, graceful
shutdown, original DB retention and normal restart then passed as before.
Targeted lint and whitespace checks passed. This is not native recovery UI or
complete-app packaging acceptance.

A full `tests/server` regression began against clean production `dea967d8` with
live-model calls disabled and isolated HOME. Report target:
`/tmp/arslan-recovery-regression.HvYYsE/backend.xml`.
At this checkpoint it is still running (process 95582, tool session 29524);
completion, counts and report integrity are not yet established. Resume that
same live process rather than starting a duplicate. Only the frozen harness and
this audit documentation changed while it ran; production and collected tests
were unchanged. No real profile, account or installed app was used.

### Updated temporary desktop bundle (2026-09-19)

The native skill session check again found no Xcode project/scheme/device context;
the Tauri/Rust candidate was built offline with temporary HOME/target instead.
The current native source and six-language catalog were staged alongside the
pre-configuration-lock sidecar and existing compute runtime (9,240 staged files).
The native release build completed in 1m11s; Tauri bundled with `--no-sign` into
`/tmp/arslan-native-candidate.xIygc5/target/release/bundle/macos/Arslan.app`.
Native executable SHA-256:
`9719f3f28a194de413a23fa6c36ce5c888d0414408e434f9e22ee84248a2f596`.
The bundled backend retains SHA-256
`027253cf67100f5a565c27ee6aec7f775a72673b8c398e64298bafc61fcbb691`.

Both staging and actual app resources passed bundle verification: 15 importable
feature modules, SPA assets, no forbidden rasterizer, DB or secret-shaped files
(431 MiB sidecar). The actual app-resource backend passed the synthetic pending
normal-boot refusal, restricted trial, source finalization and normal-restart
chain, preserving original data. The native window itself was not launched or
visually accepted. This is an unsigned test bundle, not a release candidate.

The full server-directory regression remains running with at least one failure
observed. Historical 5,009-test coverage also included non-server Python tests;
those were separately checked now: all 659 passed in 3.29s. Report:
`/tmp/arslan-recovery-regression.HvYYsE/other-python.xml`, SHA-256
`ef60ab926189e441df0a55e383774792167f4a48ecb5e5408f329e41da9d1e6a`.
Separate runs do not prove cross-directory ordering compatibility. Failure
diagnosis and a complete combined rerun remain required before a green claim.

### Full server result and verification repairs (2026-09-19)

The server run ended with exit 1: 4,470 passed, 2 failed, 14 skipped and 19 warnings
in 531.19s; 65 closed-loop aiosqlite deliveries were suppressed by the existing
teardown guard. Report SHA-256:
`f671f4956ef08f72513ef386aecf8b2fa37c4060fcf62241c457b1000cef53c7`.
It is a failed run, not a release pass.

The platform coverage tripwire identified the real macOS restricted-trial test
missing its selection marker. Added the marker alongside its existing platform
skip, and updated both the measured file population and CI's expected executed
count from 42 to 43. The startup backfill test still searched `server.main` text
for migration calls moved to shared storage boot. Replaced that text check with
normal-lifespan delegation into the real shared initializer, observing ordered
schema/migration/salt/credential/memory callbacks and stopping before background
startup. The existing actual legacy-provider backfill/decryption test remains.

All 6 focused checks passed in 2.98s. Actual macOS selection passed all 43 tests,
zero skips, in 11.43s (5,102 deselected); report is
`/tmp/arslan-recovery-regression.HvYYsE/macos.xml`. Targeted lint and whitespace
checks passed. These repairs change test/CI coverage, not production behavior;
the temporary app hashes above remain applicable. A single combined run of all
5,145 collected Python cases is still required. No real account/data was used.

### Native existing-secret preparation primitive (2026-09-19)

The macOS shell now has an internal existing-secret reader for the future trusted
recovery coordinator. It accepts an explicitly selected absolute file path, or
an explicit nonblank secret taking precedence without reading that path. There
is no implicit HOME/environment discovery, secret generation, permission repair,
IPC command, model tool, logging or automatic activation. The secret wrapper has
no Debug/Display/Serialize implementation; its value is available only through
an explicit crate-private accessor for the later pipe protocol.

Read-only open uses no-follow/nonblocking/close-on-exec flags. The open descriptor
must be a regular file owned by the effective user, single-linked, with no group
or other permissions; content is bounded to 8 KiB and must be nonblank UTF-8 with
no NUL. Metadata is checked again after reading. Missing/invalid material returns
bounded error variants without filenames or content. Parent folders remain a
trusted-coordinator precondition: this is not hostile-ancestor protection,
debugger isolation, locked/zeroized memory or credential-broker completion.

The native skill context check had no configured Xcode project/scheme/device;
isolated offline Rust tests were used. All 38 native tests passed (0.06s execution,
6.12s final build), including seven new synthetic tests covering preservation,
no creation, explicit precedence, size boundaries, invalid bytes, relative paths,
symlinks/hardlinks, unchanged lax permissions, directories and a real FIFO that
must not block. `libc` is now a direct dependency using the already locked/cached
version; no new version or package was downloaded. Whitespace checks passed.

This primitive is intentionally not yet wired to a native picker or user
confirmation; the existing temporary desktop bundle predates it. The combined
Python run started at `679626db` remains live as process 98436 / tool session
16626, targeting `/tmp/arslan-recovery-regression.HvYYsE/combined.xml`. Only native
source/manifest/lock and documentation changed during this checkpoint; the Python
production/tests under that run remain unchanged. Do not restart that live run.

### Combined Python regression completed (2026-09-19)

The same combined run from clean `679626db` completed with exit 0: 5,131 passed,
14 skipped and 20 warnings in 529.95s. JUnit independently contains 5,145 cases,
zero failures and zero errors. Report:
`/tmp/arslan-recovery-regression.HvYYsE/combined.xml`, SHA-256
`9f953531531bd69514ff68edda6e8ac295abf57a6066b40f56d3bb515790856f`.
The process/session above is now terminal; no regression run remains active.
The current `server`, `packaging` and Python `tests` trees were compared with
that starting commit and are unchanged. Subsequent native secret-reader work
has separate 38-test evidence and is not covered by this Python result.

The skips are 12 opt-in real-model evaluations, one actual non-macOS sandbox
refusal, and one operator-warning localization allowlist. Existing warnings
include Starlette, async markers, SQLAlchemy schema/connection handling and
deliberate teardown fixtures; the guard reported 54 closed-loop deliveries.
The task-evaluation suite checks positive/negative synthetic checker evidence
for 30 task families, not completion of 30 real tasks or 60 real memory scenarios.
No real model/credential/account request or payment was made.

Native UI access was checked again via the desktop automation surface: the Mac
is still locked, so native interaction/visual acceptance remains unavailable.
No unlock bypass or installed-app launch was attempted. This local limitation
does not prevent remaining implementation work. Native recovery picker,
confirmation and process coordination, isolated credential broker/security
review, live quality and the other previously recorded release gates are still
open. The goal is not complete and publication is not authorized by these tests.

### Bounded activation-control process entry (2026-09-19)

The exact `--activation-control` mode now accepts a single bounded stdin-pipe
message and dispatches only switch, rollback or finalize. It shares the existing
10-second/16-KiB pipe framing with restricted trials. Per-action fields are exact;
duplicates, path traversal, active-path overrides, extra arguments, invalid UUIDs
and invalid/oversized secrets are refused. Switch accepts only a sibling basename.
The existing environment sanitizer and pure path resolver choose the packaged
active profile, never a request-supplied active path. No config import, HTTP
server, token bootstrap or secret generation is involved. Secret values travel
in the pipe, not command arguments; output is bounded result metadata or a generic
refusal code. This is a local trusted-coordinator entry, not proof of user consent:
native UI must still collect confirmation and observe trial health/exit.

Four focused suites passed 127 cases in 23.57s (one existing Starlette warning),
and targeted lint/whitespace checks passed. New actual source-process tests switch
a synthetic fixed-home profile, exercise rollback, reject finalization before
health, then accept it after restricted authenticated health/graceful shutdown
and accept an idempotent retry. Original bytes are preserved. Wrong inherited
key/path canaries are ignored, secrets are absent from captured output, and each
child asserts configuration remained unloaded. The initial parser-test collection
used pytest's reserved `request` parameter name; it was corrected to `payload`
before the successful run, without changing product acceptance rules.

The complete combined regression above predates this entry. Frozen rebuild,
packaged-control smoke and native coordinator/UI wiring remain required. No
real profile, secret, installed application, account or publication was touched.

### Packaged activation control end-to-end (2026-09-19)

Production `59e856fc` was rebuilt in 26.97s into the standalone sidecar
`/tmp/arslan-candidate-build.BboGj4/dist-control-entry/arslan-server/arslan-server`.
SHA-256 `5c695cb8b5ca2a116f4e4cf6aa87181db5d93d396545b94f015f2411a358ced8`.
The frozen smoke now uses packaged offline restore and packaged stdin-pipe
activation control for every switch/finalize/rollback; only backup creation and
read-only evidence inspection remain source-side. Both finalize and rollback
branches passed using independent disposable profiles and the same binary.

Each branch rejects wrong-key switching without changing original DB bytes,
rejects finalization before trial health, blocks normal startup before secret
bootstrap, observes restricted authenticated health, and refuses both finalize
and rollback while the trial still owns the profile. After graceful pipe closure,
the selected packaged transition succeeds and normal frozen startup reads the
stored synthetic credential. Finalize remains idempotent after normal restart.
Original bytes remain retained in both outcomes, override/key-file canaries stay
absent, and supplied secrets/tokens are not present in captured control/trial
output. Targeted lint and whitespace checks passed.
The standalone bundle verifier also passed all 15 feature imports, SPA presence
and prohibited-component/data/secret-file checks (159 MiB, before adding the
separate compute runtime); this is not a compute-runtime validation.

This advances the actual packaged protocol, not the native user-confirmation or
picker workflow. The complete temporary desktop app has not yet been refreshed
with this sidecar/native secret reader. The combined 5,131-pass regression still
predates activation-control production changes. No real profile, credential,
model, account, installed application or publication was used.

### Native bounded activation-control transport (2026-09-19)

The macOS shell now contains a crate-private caller for the packaged activation
control protocol. It takes a trusted absolute executable path and typed requests;
secrets come from the existing-secret wrapper and appear only in a bounded stdin
message, never command arguments. Inherited secret/key-file/API-token overrides
are removed. The caller does not discover a binary, obtain approval, expose web
IPC, launch a trial or automatically retry/rollback an uncertain operation.

Nonblocking stdin/stdout avoid pipe stalls without unbounded reader threads.
Requests are capped at 16 KiB, replies at 4 KiB, and the operation deadline is
30 seconds. Captured stderr is discarded rather than forwarded to UI/logs. Success
requires a matching strict per-action JSON schema and a successful process exit;
duplicate/extra fields (including extra null fields), invalid operation identities,
missing original-retained confirmation and unexpected exit statuses are refused.
Transport failure/timeouts are explicitly `OutcomeUnknown`. Even a backend refusal
may follow a partial move, so neither implies unchanged data; journal reconciliation
remains mandatory. Cleanup kills/reaps only the child owned by this call.

The native skill session had no configured Xcode project/scheme/device; isolated
offline Rust testing passed all 43 tests in 0.28s after a 1.59s incremental build.
Five added tests cover request/response validation, actual synthetic process I/O,
failed exit, busy-loop timeout, unbounded-output refusal, secret-environment
scrubbing and exact-child reaping (ECHILD after timeout). Formatting/whitespace
checks passed. This is native transport tested with synthetic children, not yet
a native-to-frozen full-chain run or a confirmed user-facing recovery workflow.
The existing temporary app bundle predates this module. No real secret/profile,
installed app, account or publication was used.

### Native-to-frozen control integration (2026-09-19)

The frozen activation harness now optionally drives the actual Rust `run` caller
through a test-only native executable, rather than constructing control pipes
itself. The opt-in fixture is ignored in default unit runs and refuses anything
outside canonical temporary test-home/binary prefixes. It uses only fixed
synthetic correct/wrong secrets and the fixed `restored` sibling; it is absent
from release builds and is not a general user-profile control command.

The native skill context remained unconfigured for Xcode; offline Rust testing
passed 43 regular tests with the one opt-in integration fixture explicitly
ignored (0.27s execution, 1.96s build). The Python harness then explicitly ran
that fixture for every control operation in two separate full chains. Both
native-to-frozen finalize and rollback branches passed against backend SHA-256
`5c695cb8b5ca2a116f4e4cf6aa87181db5d93d396545b94f015f2411a358ced8`.
This includes wrong-key refusal, pre-health/active-trial refusal, normal pending
startup refusal, graceful trial exit, original retention, normal restart and
idempotent finalize. Packaged offline restore and frozen HTTP trial remain real;
source backup creation and harness health orchestration remain explicit.

Native test executable:
`/tmp/arslan-native-candidate.xIygc5/target/debug/deps/arslan_desktop_lib-9c709306606e194d`.
SHA-256 `bd1cd74644611e31322b365c3f901cf1862d0c5bfd32b2ec96850c44fcd2be6a`.
Targeted lint/whitespace checks passed. This establishes protocol interoperability,
not the desktop confirmation/picker workflow, full native trial orchestration or
visual acceptance. No installed app, real user data/secret, provider or publication
was used; the temporary desktop bundle still predates these native modules.

### User-confirmed interrupted-recovery rollback entry (2026-09-19)

The macOS boot path now preserves a typed pending-recovery flag from the exact
backend handshake. After the failed normal child has been killed/reaped, only
that flag opens a native warning dialog on the existing boot worker thread. The
user can return to original data or keep startup paused. Product-owned title,
explanation, action/cancel labels and unconfirmed-result guidance exist in all
six languages. The explanation states that original and candidate folders are
retained, not deleted. No webpage/model IPC can approve this action.

Cancel returns the existing startup failure without invoking maintenance or
restarting. Confirmation invokes the bundled control executable with Rollback;
only `RolledBack(true)` permits one fresh normal-start attempt. No-op, refusal,
timeout, malformed/uncertain output or unexpected action results keep this boot
paused. Another pending failure after the retry does not repeat the dialog or
rollback. Unrelated startup errors never offer recovery. This is an interrupted
operation's rollback UI, not a backup picker or forward restore/activation UI.

The native skill context had no configured Xcode project/scheme/device; isolated
offline Rust tests passed 47 cases with one separately exercised opt-in fixture
ignored (0.27s execution, 1.00s incremental build). Four new state-flow tests cover
non-recovery paths, cancellation, confirmed single retry, unknown outcomes and
repeated pending status. Exact handshake matching and six-language nonempty/
distinct action labels are also checked. Shell/packaged-entry Python checks
passed 46 cases in 0.63s; native-locale tests were separately exercised. Whitespace
checks passed. These are code/flow assertions, not a click or visual acceptance.

The desktop remains locked from the latest UI check, so actual dialog behavior
and translated layout remain unverified. The temporary full app must be rebuilt
before that acceptance. No actual user confirmation was fabricated and no real
profile, key, installed app, account or publication was touched by these tests.

### Bind interrupted-recovery consent to one operation (2026-09-19)

The native boot path now inspects a validated pending journal before prompting.
It captures that operation ID and sends a bound rollback after confirmation.
The backend rechecks the ID while holding the lifecycle lock, before any profile
move. A different operation is refused without changing its journal, directory
identity or database. Failed inspection never prompts; missing/uncertain results
keep startup paused. The operation ID is a binding, not an authorization token.
Legacy internal unbound rollback remains compatible but is not used by the
desktop confirmation path. Inspection validates supported interrupted layouts
without moving profiles or bootstrapping configuration/secrets.

Offline native tests passed 50 cases, with the separately invoked packaged
fixture ignored in the default run (0.27s). Targeted Python control, activation
and packaging tests passed 120 cases in 23.83s, with one existing Starlette
deprecation warning. Tests include state changing during the confirmation and
stale consent for an earlier operation. Targeted Ruff and whitespace checks
passed. XcodeBuildMCP session defaults had no project/scheme/device; this Tauri
validation used the isolated offline Rust environment, not Xcode/UI testing.

A fresh frozen backend built in 27.14s at
`/tmp/arslan-candidate-build.BboGj4/dist-consent-bound/arslan-server/arslan-server`.
SHA-256: `e8c5651dfdaa94e35756ef3257bac187d15643f44678f6669af0d2f4b4a119c4`.
Bundle verification passed 15 import checks, web assets, and absence of AGPL
rasterizers, databases and secrets (159 MiB). Both native-to-frozen rollback and
finalize smoke chains passed, including inspection, wrong-operation refusal,
trial ownership refusal, restricted health, graceful shutdown and normal restart.
Source code creates only the synthetic backup; packaged restore/control/trial
operations and native transport are exercised against the actual frozen binary.

These checks do not exercise the native dialog or forward-restore picker. The
temporary full desktop app still needs rebuilding and visual/click acceptance.
No real profile, account, model, installed app or publication was used. Full
Python regression evidence above predates this change and is not relabeled as a
new full run.

### Native restricted-trial launcher (2026-09-19)

An internal macOS launcher now owns `--activation-trial` from start to exit.
It accepts only an absolute trusted executable, canonical operation ID and the
existing-secret wrapper. A fresh 32-byte OS-random token and the secret travel
only in a bounded stdin request; inherited secret/key-file/API-token variables
are removed. Stdin remains open until verified health, then EOF requests normal
shutdown. The launcher shares the existing exact-child kill/reap guard; no
broad process termination or background reader thread is introduced.

The handshake must be the exact trial-specific port line. The health client
connects directly to numeric IPv4 loopback with no proxy/DNS/redirect handling,
uses the fixed restricted health path and random bearer token, bounds the whole
startup/probe to 90 seconds and the response to 4 KiB, and rejects ambiguous
HTTP framing, duplicate headers/JSON fields, non-200 status, extra JSON fields,
wrong operation/mode/status or missing no-store/JSON headers. Graceful exit has
an additional 10-second bound. Success requires both verified health and exit
code zero with stdout EOF. Neither success nor a receipt is user approval;
finalization still separately validates the durable receipt and live profile.
Errors never auto-finalize, retry or roll back.

Offline Rust tests passed 56 cases with one opt-in packaged fixture ignored in
the default run (0.34s execution, 1.02s build). New tests cover fresh token shape,
port parsing, strict health framing/content, real loopback request behavior,
environment scrubbing, healthy response plus failed child exit, hung/oversized
health, hung child reaping, wrong handshake, excessive stdout and invalid inputs.
Targeted Ruff and whitespace checks passed. XcodeBuildMCP defaults had no
project/scheme/device; this is isolated Rust testing, not native UI acceptance.

The opt-in synthetic fixture can invoke the actual native launcher. The frozen
harness adds a second trial through native code after its existing HTTP security
probes; that second trial invalidates the earlier receipt. Subsequent successful
finalization therefore requires the native-launched trial's own health/shutdown
receipt. Both rollback and finalize chains passed against the temporary app's
actual backend resources (SHA-256
`e8c5651dfdaa94e35756ef3257bac187d15643f44678f6669af0d2f4b4a119c4`),
without a real account/model/profile. Native test executable SHA-256:
`b63c93e72f8d2bc331820ebc6ff31ced7412abe6eb58878225dfa1fef90ddcc0`.

This module is not yet exposed through a forward-restore picker/confirmation
workflow, and the release desktop binary predates it. The trusted coordinator
must still stop its normal child, prepare the selected candidate and secret,
obtain user confirmation, invoke trial/finalize and restart. There is no web IPC
or model-callable recovery command. Latest temporary bundle details above remain
unchanged; a new source module does not constitute completed desktop recovery.

### Native selected-archive preparation transport (2026-09-19)

The local maintenance protocol now accepts a `prepare` request with an explicit
absolute archive path and a candidate basename, not an active-profile override.
The packaged entry sanitizes environment and resolves the fixed active profile
without configuration/secret bootstrap. Preparation requires an existing owned
active directory and a new same-parent candidate distinct from it. The selected
archive is opened read-only/no-follow/nonblocking, checked as a nonempty regular
file of at most 2 GiB, and passed by its pinned descriptor into the existing
restore validator. Current-profile ownership locking, archive checksums, atomic
new-directory installation, restored-memory review and deletion-record
reconciliation remain in the existing restore path. No key is read or generated.

Before/after archive size, modification and change times must match before a
prepared result is returned. A changed file or uncertain transport can leave a
candidate in place; it is retained, not approved, activated, deleted or blindly
overwritten on retry. Parent-directory trust remains an explicit assumption.
The Rust response parser requires the exact requested candidate, a bounded
positive file count, prepared=true and secret_included=false. No web IPC or
model-callable endpoint is added. The prior CLI remains available unchanged.

Focused Python control/activation/CLI/deletion-restore suites passed 121 tests in
28.41s (one existing Starlette deprecation warning). Source subprocess tests now
prepare then switch, and assert configuration stays unloaded and inherited
secret/path canaries remain absent. Tests cover original/archive preservation,
existing-destination refusal, links, FIFOs, directories, empty files, active
ownership, non-sibling/active destinations and changed-archive uncertainty.
Offline native tests passed 57 cases, one opt-in fixture ignored (0.33s, 7.27s
build), including strict preparation request/result binding. Ruff and whitespace
checks passed. XcodeBuildMCP defaults were unconfigured; no Xcode/UI acceptance
is inferred from these Rust tests.

The frozen backend built in 30.89s at
`/tmp/arslan-candidate-build.BboGj4/dist-native-prepare/arslan-server/arslan-server`.
SHA-256: `3f77ae1e9c02da0938b164b413196c0dbd4381a07fbd4105fc2b58f611e4c189`.
Bundle verification passed 15 imports, web assets and prohibited-rasterizer/
database/secret checks (159 MiB, before compute-runtime staging). Both rollback
and finalize smoke chains passed with actual native preparation, control and
trial launch against this frozen backend. Only synthetic backup creation remains
source-side. Native test executable SHA-256:
`eacda53f18c7372f95b5525513fd897171147622d0b82957dc8d893e1145a865`.

The menu, file selection, original-key selection, exclusive UI coordination and
normal-child shutdown/restart still require integration. The full temporary
desktop bundle predates this change; no installed app, real data/secret/account,
paid model, signing identity or publication was used.

### Explicit normal-backend shutdown before recovery (2026-09-19)

UI integration review found that closing the normal backend's parent pipe uses
immediate `os._exit`, bypassing lifespan cleanup. A new exact parent-pipe
`ARSLAN_SHUTDOWN` request instead asks the Uvicorn Server instance to stop and
arms a 10-second failure watchdog. Ordinary EOF/broken-pipe parent-death cleanup
remains unchanged. Requests arriving before server startup are unconfirmed.
The normal lifespan records completion only after watcher, scheduler, curation,
browser and MCP cleanup and database-engine disposal. Previously nonfatal stop
exceptions remain nonfatal for ordinary shutdown but invalidate recovery-stop
confirmation. Successful requested shutdown emits `ARSLAN_STOPPED=1`; incomplete
cleanup returns failure without that receipt. This is tracked-service cleanup,
not a claim that unrelated/older application processes have been stopped.

The desktop now retains a per-child receipt observer beside its process handle.
The native stop helper keeps stdin open, sends the request, requires exactly one
post-request acknowledgement, successful process exit and clean stdout closure.
Premature/duplicate/malformed acknowledgements, reader errors, already-exited
children, failed exits and a 15-second deadline all refuse confirmation. On
failure only the owned child is killed/reaped; this is NOT permission to move
profiles or infer a safe graceful stop. Ordinary app exit behavior is unchanged.
The menu coordinator does not invoke this helper yet.

Native tests passed 60 cases with one opt-in fixture ignored (0.32s, 2.56s build).
Focused packaged-entry, startup-backfill and shutdown-cleanup tests passed 58
cases in 0.97s (one existing Starlette warning), including each cleanup failure,
early requests and absent completion state. Ruff and whitespace checks passed.
XcodeBuildMCP defaults remained unconfigured; tests used isolated offline Rust.

The frozen backend built in 28.40s at
`/tmp/arslan-candidate-build.BboGj4/dist-graceful-stop/arslan-server/arslan-server`.
SHA-256: `f6d80eca684e74b035c3b901ad373ae954b46da008bf2e92282f86f8dcadebaf`.
Bundle verification passed 15 imports, SPA resources and absence of prohibited
rasterizers, databases and secrets (159 MiB before compute-runtime staging).
Both actual native-stop → native-prepare → trial → rollback/finalize smoke chains
passed on disposable synthetic profiles. A subsequent reader-error hardening
change was unit-tested and the finalize chain rerun with the final native test
binary (SHA-256 `9fe3e74741def8b5ebad808809e957011bf93935ce2766a3f8cbb4dedd79bc38`).
The frozen binary predates a later docstring-only change, not a runtime change.

Menu/file selection, operation-wide exclusivity, original-key selection and
durable restart key-source handling remain unfinished. Review explicitly kept
the existing external-key/data separation contract: no key was placed inside a
profile or backup to shortcut restart handling. No real data, keys, accounts,
installed app, signing or publication were involved. Full Python regression is
required after this lifespan change; earlier full-run counts do not certify it.

### Full regression after explicit shutdown (2026-09-19)

The complete run on production baseline `81949a01` finished with 5,197 passed,
one failed, 14 skipped and 19 warnings in 553.31s (exit 1). Report:
`/tmp/arslan-shutdown-regression.2R4LPk/combined.xml`. The sole failure was the
legacy memory startup test passing `None` as the application to the lifespan,
which now records shutdown completion on application state. This failed run is
retained, not classified as a pass.

The test now supplies a real FastAPI application and seeds completion to true
before each of two deliberately interrupted startups. Both must reset it to
false, while retaining the migration, deletion-ledger and legacy identity
checks. Production shutdown checks were not relaxed. Focused memory activation,
shutdown services and packaged-entry tests passed 61 cases in 1.26s with one
existing warning. A fresh full run is still required for the corrected suite.
