# W19 — isolated navigation and work dock

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
