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
