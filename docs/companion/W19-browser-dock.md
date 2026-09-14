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
