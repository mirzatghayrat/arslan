# W19 — isolated navigation and work dock

## Failed-stop ownership and navigation exclusion — after `83cd3758`

Two new component regressions failed on the unchanged reader: a rejected close
request disabled Stop permanently by discarding the session ID, and a pending
close allowed another navigation/session to start. Stop now keeps the owned ID
until closure succeeds, clears obsolete frame/error state, and keeps navigation
and duplicate stop controls disabled while the close request is pending. A
failed request leaves explicit retry and unmount cleanup able to address the
same session. Generation checks prevent late action frames and close errors
from updating a superseded/unmounted view.

Four new tests cover failed-close retry, navigation exclusion while closing,
unmount retry after a failed stop, and suppression of a late frame after a
failed stop. Full frontend regression: **2,004 passed, zero failures/errors**,
62.79s; report `/tmp/arslan-reader-stop-full.xml`, SHA-256
`fdb7fe9636aad749bb6c17bae0f0abaa4a85010cc56d09322193f09eac4311dc`.
TypeScript and production build pass (6.80s, existing chunk-size warning).
This is component/API-mock evidence, not actual failed-network process cleanup.
Temporary native package refresh and UI verification remain pending. Full
authenticated interaction and broker review remain separate open requirements.

## Packaged privacy transition and restart — after `bbb335c0`

Refreshed the unsigned temporary app's web resources (no native/backend source
change); bundled assets compare byte-for-byte with current web/dist. Entry
`index-B7nurUzD.js` SHA-256:
`e53a84647df7b2e10ffa3370722e4e99b2a91dfc4207e4f61f9e25e383c6b774`.
Used synthetic HOME `/private/tmp/arslan-native-restore-ui-m1tgzvbv`, minimal PATH,
German/dark, no configured model and the pre-existing isolated browser runtime.

The dock initially restored one unrelated ordinary tab without navigating.
Created a new browser tab bound to the current empty conversation
`thread-1789825323509`, then visibly opened example.com. Actual session
`e1ebf888-e57d-466d-bc9b-ac76653c879e` returned a frame. Confirmed owned Node and
Chromium process IDs **66846, 66848, 66849, 66850, 66851** and profile root
`/tmp/arslan-reader-9mo74qj8` before the transition.

Through the actual conversation-settings dialog, enabled temporary mode and
saved. The context PUT returned 200, the reader DELETE returned 204, and native
AX/screenshot showed the Example Domain tab removed while the unrelated tab
remained. All five observed browser processes were absent and the profile root
was deleted. Quit also terminated app/backend 66774/66782. Restarted with the
same synthetic HOME: only the unrelated blank ordinary browser tab returned;
the removed tab did not, and no browser-session request was made on restart.
Quit again; no owned app/backend/browser processes remain.

Logs (no traceback): `dock-privacy.stderr`, SHA-256
`c27d79137b274373dd76e9a1780916595946ff672d6a2f113a9f1c2c4dbed864`, and
`dock-privacy-restart.stderr`, SHA-256
`6a0bb23b4fcbf789b881eb3ca7c614185a46a469018a8658a63fdafaef9bdf8c`,
under the synthetic HOME above. This closes the native package/process/restart
verification gap for this defect. It does not certify authenticated interaction,
independent broker security, all locales/window sizes or overall release readiness.
No real account, model request, installed-app replacement or publication occurred.

## Same-conversation privacy transition — after `7d20d4f0`

Reproduced a dock ownership defect with the production component: creating a
normal browser tab, then converting that same conversation to temporary left
the old reader mounted and its normal restore metadata intact. The existing
cleanup only handled conversation-ID changes and tabs born temporary, not the
privacy-mode change of an existing conversation. The added regression failed
on the unchanged source because the old reader was still mounted.

WorkDock now closes ordinary browser tabs belonging to a conversation when it
becomes temporary and rewrites safe restoration metadata without those tabs.
Other ordinary conversations' tabs remain. Closing unmounts the real reader,
which closes its live session or, if creation is still pending, closes the
late-created session without navigating. Explicitly opened new temporary tabs
remain usable/session-only and are removed on leaving the conversation. Hidden
initial mounts in temporary mode also purge old restore metadata.

Focused tests: **18 passed** across dock, reader and new ownership integration
tests; TypeScript and production build pass (3.18s, existing chunk warning).
Integration uses the actual BrowserReader with mocked browser API responses,
not a mocked reader component. It proves close requests and stale-result
ownership, not actual renderer process exit for this newly fixed path.
The temporary native bundle has not yet been refreshed for this change;
native privacy-transition/browser-process revalidation remains next.

Full frontend regression: **1,976 passed, zero failures/errors**, exit 0.
JUnit `/tmp/arslan-dock-privacy-full.xml`, SHA-256
`05ed466bef24270fa11c10db01b23de57f1c3702bb423066736e39f9bf3e3c64`.
Existing jsdom canvas/navigation warnings remain.

Checkpoint: 2026-09-15, starting from `d3450890`. This implements bounded public-page interaction, not authenticated automation or a completed independent security review.

## Delivered

- Persistent, resizable typed browser/artifact tabs, eight-tab limit, keyboard navigation, explicit new/close controls, task/conversation association. Only safe tab metadata is restored; URLs, page contents, screenshots and live sessions are not persisted. Temporary-conversation tabs are never restored.
- Separate Node/Chromium renderer with a temporary profile and scrubbed environment. Navigation, revision-bound link following, history, refresh, fixed scrolling, screenshot and extracted text. No page access to the application bridge. The existing static preview remains unchanged.
- Public-IP-pinned CONNECT proxy; HTTPS-only routes; GET/HEAD only; WebSocket and service-worker blocking; no credentials, forms, uploads, downloads or page-controlled evaluate API. GET navigation still contacts websites and can have server-side semantics; this is not a claim that every possible website side effect is eliminated.
- Session ownership checks, four-session cap, 100-operation/15-minute limits, task cancellation hook, close/deadline cleanup. Chromium renderer sandbox is enabled; a separately reviewed OS-level broker sandbox is not yet claimed.
- Saved artifact previews verify size and SHA-256 before displaying content. HTML/SVG/code are text, never executable frames. Media uses temporary blob URLs; closing revokes them and switching tabs pauses playback. Other documents use the existing extraction endpoint.
- All new panel/reader strings are present in six locales. Broader W21 terminology and runtime-language acceptance remain separate work.

## Evidence

- 14 reader backend tests pass; earlier combined reader/proxy/static/task-service checkpoint: 38 passed.
- 11 artifact/dock/reader UI tests pass; TypeScript and production build pass. Existing large-bundle warning remains.
- Real temporary Chromium runtime: example.com navigation, refresh, stale-link rejection, close, temporary-profile deletion and zero remaining browser children pass.
- Shared production-policy component fixture: POST/PATCH/PUT/DELETE and WebSocket blocked, no Tauri/Node globals in page, real 560px scrolling verified.
- Actual local app UI at 1280×720: dock opens beside conversation; example.com renders; link follow reaches IANA Example Domains. No real account, paid model, production data or installed application was used.

## Remaining gates

Authenticated browser actions are disabled. Native-broker independent review, all-language/narrow-window UI acceptance, full regression and packaged runtime acceptance are not implied by these checks. W20 adds richer declared input capability metadata. No release was published and the installed app was not replaced.

## Six-language narrow-window reader follow-up

The production WorkDock/BrowserReader and compiled CSS were exercised in isolated
Chromium with synthetic reader API responses and all external requests blocked.
The first run reproduced a narrow-layout defect: at a 600px viewport the dock was
only 330px wide, leaving the conversation and reader competing for limited space.
Below 768px the dock now opens as a full-width dismissible dialog; wider windows
retain the adjustable side panel. Narrow mode moves focus inside, wraps Tab focus,
supports Escape, restores prior focus on exit and hides the resize handle.
The conversation label/reader layout now uses flex sizing rather than assuming a
fixed 24px translated label, keeping scrollable source text above the footer.

The reusable `scripts/work_dock_layout_smoke.cjs` passed 36 combinations: six
languages × 1100/600/360px widths × light/dark. It checks synthetic navigation,
scroll action wiring, tab keyboard selection, narrow focus wrapping/dismissal,
horizontal bounds and accessibility of the end of long source text. Screenshots
are in `/tmp/arslan-dock-layout.JWcrB0`; six representative images spanning every
language, width and theme were visually inspected. This is real-browser component
layout/interaction evidence, not a new native broker, real website or packaged app
test. Static preview/setup and all artifact types are not covered by this matrix.

Complete frontend regression: 237 files / 1,837 tests passed in 17.83 seconds.
TypeScript and production build (3.04 seconds) passed. Existing bundle-size and
jsdom warnings remain. The initial focused test attempt hit the already-known Node
experimental web-storage incompatibility; the established
`NODE_OPTIONS=--no-experimental-webstorage` setting fixed the test environment
without product changes. Native broker review, authenticated actions and packaged
runtime acceptance remain unresolved.

## Whole-app integration follow-up

The current production build was then served by `companion_smoke_app`, using real
migrations/settings/browser APIs, a fresh temporary HOME/data directory, synthetic
model configuration and loopback-only HTTP. No browser runtime was configured in
the app and no setup/download action was taken. The existing temporary Chromium
test driver used a new isolated context for every case.

`scripts/work_dock_app_smoke.cjs` passed another 36 combinations (six languages,
1100/600/360px, light/dark) inside the full application shell. Each case changes
the real settings/theme, returns to the conversation, opens a browser tab, and
verifies the real `409 browser.setup_required` response. The visible refusal,
panel title and new-tab accessible label exactly match the selected language.
Bounds and page exceptions are checked, and narrow Escape dismissal restores
focus to the actual app opener. A first driver attempt accidentally selected a
hidden static-preview close button; direct-child scoping corrected that test
locator. No production fix was necessary in this follow-up.

Screenshots: `/tmp/arslan-companion-ui-dock.9Tvo9P/screens`. Six representative
images across all languages, widths and themes were inspected. This complements
the synthetic successful-reader component matrix; it does not prove live public
navigation, authenticated actions, artifact rendering or native packaging.
The temporary app server and Chromium contexts were closed after verification.

## Published-frame integrity and failed history navigation — 2026-09-19

Source baseline `3a15df9f` had a reproduced frame-binding defect. After a new
navigation changed the page, link extraction overwrote the link map before
screenshot/title capture completed. A failed capture left the previous revision
valid, so an old displayed `link-0` could follow the newly extracted page's
`link-0` URL. The baseline stdin/stdout program was run against a deterministic
renderer double: the displayed target was `https://example.com/original/target`,
but the subsequent refresh revealed navigation to
`https://example.com/capture-fails/target`. No public request or account was used
for this defect reproduction. The first diagnostic expected an immediate success
response, but the double also failed capture on that new target; observing the
subsequent refresh established the actual wrong destination.

The runtime now invalidates the published frame before navigation/scroll can
change the page, stages the new links and history cursor, and commits them only
after the entire frame is available. Failed back/forward no longer consume a
history step. Refresh after partial navigation records the actual recovered URL.
Old frame IDs are refused rather than rebound. The UI removes old screenshots
and link controls on action failure; a still-live session can still be stopped.
No arbitrary click/type or authenticated action has been enabled by this fix.

Seven new tests run the actual shipped Node program through its stdin/stdout
protocol with a synthetic renderer: capture/title/oversize/navigation failures,
failed history retries, failed scroll and refresh after partial navigation.
Five new component cases check stale frame removal and recovery, including
terminal session errors. Reader/dock selection: **21 passed**; Python reader,
proxy and managed-browser selection: **29 passed**, one existing dependency
warning, 0.74s.

Real temporary Chromium checks also passed: public example.com navigation,
scroll request, stale-link rejection, refresh and complete child/profile cleanup
using `scripts.browser_reader_smoke`. The production-policy synthetic-page smoke
confirmed actual 560px scrolling, blocked POST/PATCH/PUT/DELETE and WebSocket,
and absent Tauri/Node globals. Runtime:
`/private/tmp/arslan-reader-runtime.vfxygc`; no real profile/account was used.
Capture-failure injection remains renderer-double evidence, not a claim of
all failure modes reproduced in actual Chromium.

Complete frontend suite: **248 files / 1,918 tests passed** in 23.50s, without
the former Node storage workaround. JUnit report
`/tmp/arslan-reader-frame-regression.xml`, SHA-256
`4a0eb3f3e89a96a6fac819b2643f4e695248b529394189ccf900b049ff3413da`.
TypeScript, whitespace and production build passed (3.15s); existing React/jsdom
and large-chunk warnings remain. The native bundle has not yet been refreshed
with this reader/web change, so the preceding packaged hash does not cover it.
Authenticated browser scope, broker review and the broader W19/W21 acceptance
matrix remain open; this checkpoint is not a release certification.

## Current packaged reader and native UI — 2026-09-19

Production source `3a0d6177` was frozen in 24.59s to
`/tmp/arslan-candidate-build.BboGj4/dist-reader-frame/arslan-server`, staged with
the existing temporary compute runtime (9,240 files), and bundled unsigned into
`/tmp/arslan-native-candidate.xIygc5/target/release/bundle/macos/Arslan.app`.
All packaged web assets compare byte-for-byte with the current `web/dist`; the
packaged reader and policy scripts match source. Reader script SHA-256:
`94ed2feceefae5bf805bcf4da8186bb958366eb945cc08109ca4f30b0f3ec089`;
web entry SHA-256:
`9e3bed0154e0b056b201853a2c5da05d319aeba0f1dcaec0ceb3be792463436c`.
Native executable remains
`fa0d2c37c102e8d0d93125423b2e2b28ecd7e494d11b558d4da1303de2052d30`
and frozen executable remains
`6e3dc602bdc44b397366a307492644d6bbd3ae099ee207110a9a7bec2abb1401`:
the reader/web changes are external packaged resources, so executable hashes
alone would not identify this update. Bundle verification passes 15 module
imports, assets and prohibited-content checks, 431 MiB.

New `scripts.frozen_browser_reader_smoke` starts the actual frozen server with a
disposable HOME and tests authenticated browser APIs against real Chromium. It
reuses the existing temporary pinned runtime through fixture-only symlinks and a
fixture ready record; no setup endpoint, package installation or download is
tested. The first run correctly refused a record containing the `/tmp` alias
while the application resolved `/private/tmp`; canonicalizing the fixture HOME
fixed the harness without relaxing product checks. The final driver avoids
server-configuration imports, so importing it cannot bootstrap the invoking
user's key/profile. Five driver isolation/target-refusal tests pass (0.29s), as do
Ruff and whitespace checks.

The smoke passes against both the fresh frozen output and the final app-bundled
server: resource identity, navigation/history/refresh, stale-frame refusal,
typing/file-URL rejection, session deletion, child termination and temporary
profile removal. The standard frozen-sidecar smoke also passes fresh boot and
restart, authentication, six saved languages, onboarding/token retention,
document/cell/slide/PDF locators, inert source code, malformed inputs and the
unprovisioned browser gate. It does not invoke a real model.

Actual native UI used the retained synthetic profile
`/private/tmp/arslan-native-restore-ui-m1tgzvbv`, with only its fixture runtime
record added. The Chinese/dark side panel visibly opened example.com and followed
its displayed link to IANA Example Domains. Navigation to the reserved
`https://arslan-reader-smoke.invalid` failed as expected: old screenshot/link
controls disappeared, the localized error appeared, and Stop remained available.
Navigating to example.com again produced a new frame. Stop removed the frame and
terminated the owned Node/Chromium processes (25554/25556/25557/25558/25820).
Native Quit then terminated app/backend 25469/25480. Unrelated browser processes
were not touched. No owned test app or browser remains running.

This closes the package-refresh gap for the frame-integrity change and adds one
actual native success/failure/recovery path. It is not all-language/narrow-window
native acceptance, runtime-installation acceptance, arbitrary interactive forms,
authenticated browser support, independent broker review or release readiness.
No real account, model cost, production installation or publication was used.
