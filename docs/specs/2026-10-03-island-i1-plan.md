# Arslan Island — phase I1 implementation plan (2026-10-03)

Research and phases: `docs/specs/2026-10-03-arslan-island-research.md`. Approved look: the clickable mock
(https://claude.ai/artifact/8eUMJdtSXS4p4JALshS9nY, v3). Mascot rule: the black-and-white head stays still and
breathes; states are shown only by the mouth constellation (signals · orbiting dots · ! · ? · ω · flat line ·
small and dim) plus a halo in the state colour; no sound.

I1 scope: the island window, notch geometry and the no-notch bar, modes and behaviour rules, click-through,
and **read-only** views — overview, empty, finished, stopped, and "needs you" (approvals are answered in the
chat window until I2). Screen recordings and shares never show the island.

## 1. Shell (`desktop/src-tauri/src/island.rs`)

- A second webview window, label `island`, loading `http://127.0.0.1:<port>/island` with the same token
  injection as the main window plus `window.__ARSLAN_ISLAND__ = true` (the SPA skips its boot veil, the page
  stays transparent). Built after the main window; one per app.
- 720 × 320 logical, transparent, no decorations or shadow, always on top, not in the Dock/⌘-Tab, never
  focused at creation, accepts the first click, on every Space.
- macOS: window level above the menu bar (`NSMainMenuWindowLevel + 3`), collection behaviour
  `canJoinAllSpaces | stationary | ignoresCycle | fullScreenAuxiliary`, `sharingType = none` (absent from
  screenshots, recordings and shares).
- Geometry: the screen whose `safeAreaInsets.top > 0` hosts the island at its top centre, notch width from
  `auxiliaryTopLeftArea`/`auxiliaryTopRightArea`; no such screen → the main screen and a small bar. Passed to
  the page at load and on display changes (`island-geometry` event).
- Click-through: a 30 Hz poll compares the cursor with the island rectangle the page reports
  (`island_shape`), with a 6 pt margin, and toggles ignore-cursor-events only when it changes.
- Presence: system idle time (`CGEventSourceSecondsSinceLastEventType`, keyboard and mouse) ≥ 180 s → the
  page gets `island-presence {away: true}`.
- Commands, granted to the `island` window only (`capabilities/island-ui.json`):
  `island_shape(x, y, w, h)` and `island_open_conversation(conversation_id?)` (shows the main window and
  emits the existing `open-conversation` event, as a notification click does).
- Debug builds only: `ARSLAN_DEV_BACKEND_PORT` skips the bundled backend and uses a running dev backend, so
  the shell can be run from a checkout. Compiled out of release builds.
- Known I1 limit: a click on the island activates Arslan (an `NSWindow`, not a non-activating `NSPanel`).
  I1's clicks all open Arslan anyway; I2 (approve from the island) converts it to a non-activating panel.

## 2. Backend

- `desktop_status`: `working(conversation_id, title=, kind=)` records an activity (kind, title, start, latest
  step, plan) reachable through a context variable; `note_step(tool, args)` (from `_dispatch_tool`) keeps a
  structured, minimal step — tool plus target, where the target is a host, a file name or the first 40
  characters of a query or command; `note_plan(text, done, total)` (from `update_plan`).
- Event titles and summaries are kept apart from the events the status endpoint serves, so notifications
  stay contentless (they can be read on a locked screen).
- `GET /api/v1/island/feed?after=N` (auth as every endpoint): `{active: [...], awaiting, events: [...], cursor}`.

## 3. Web (`web/src/island/`)

- `/island` renders `IslandApp` instead of the app; transparent page.
- `islandMachine.ts`: pure transitions — hidden → peek (hover) → expanded after 650 ms; compact while work
  runs; expanded after 200 ms hover in compact; collapse after 60 s without interaction (countdown in the
  last 10 s); away → hidden unless something needs the user; "needs you" opens by itself and stays; finished
  shows 5.2 s; events queue.
- `IslandMascot.tsx`: the mock's head and constellation engine (JS tween; WKWebView has no CSS `d`
  transitions), paused when hidden.
- Views: compact strip, overview (active items, step ticker, plan, other items), empty, finished, stopped,
  needs-you (read-only: "Open to approve").
- Strings in six languages. Settings: "Show Arslan in the notch" (on by default).

## 4. Tests

Rust: pure geometry and hit-test functions; the command/permission lockstep test. Backend: activity, step
targets (never full arguments), feed shape, status endpoint still contentless. Web: machine transitions,
feed → view mapping, mascot glyph tween, views. Each mutation-checked. Then a real run of the debug shell
against a dev backend.

## 5. As built (2026-10-03) — where the build differs from the plan above

- **Its own page, not an SPA route.** `web/island.html` is a second Vite entry (about 30 KB of script, no app
  bundle, no global CSS), loaded as `/island.html`. The server treats it as an entry page (never cached, like
  `index.html`), and `packaging/build_dmg.sh` refuses a build without it: the SPA fallback would otherwise load
  the whole app into the notch window.
- **Hover comes from the shell.** The island window is never key (`focusable(false)`), so it gets no reliable
  hover events of its own. The 30 Hz pointer poll that toggles click-through also emits `island-pointer
  {inside}`, and the page uses that for enter/leave; DOM hover is used only in a plain browser (dev).
- **Leaving closes a panel you opened by hovering** after 1.2 s, instead of waiting 60 s: an open panel blocks
  clicks on whatever is under it. The 60 s idle close (countdown in the last 10 s) applies to a "stopped" notice;
  "needs you" stays until it is answered or closed; "finished" shows 5.2 s, never closes under the pointer and
  stays at least 2 s after the pointer leaves.
- **A result waits only while other work is still running** under the pointer; when the last run finishes
  while you watch the overview, its result replaces the overview at once.
- **Chat turns you are looking at do not pop up.** The shell emits `island-main-focus`; finished events carry
  `work` (turn/job/scheduled) in the island feed only, so a background job still shows while the window is focused.
- **Plan is structured.** `note_plan(items)` keeps the checklist (60 characters an item) with done/total, and
  the overview shows it as chips; the overview's step lines are the last three distinct steps.
- **The panel clears the notch.** Cards start at `max(36, notch height + 6)` and the panel grows by the
  difference (found on a 14" MacBook Pro at 1800 × 1169, where the notch is 39 pt and hid the card's top edge).
  When hidden, the shape is exactly the notch, without the concave ears.
- **Debug only:** `ARSLAN_ISLAND_SHAREABLE=1` leaves the window capturable so it can be screenshotted while
  developing; compiled out of release builds with `ARSLAN_DEV_BACKEND_PORT`.
- **Not yet verified:** click-through on a real screen (the hit test is unit-tested; the toggle itself was not
  clicked through), and showing over another app's full-screen window. A regular `NSWindow` from a background
  app may not join another app's full-screen Space; if not, the non-activating `NSPanel` planned for I2 is the fix.
