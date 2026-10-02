# Arslan Island — what to take from Coucou (research, 2026-10-03)

Source: https://github.com/Louis-CFM/coucou (2.8k stars, created 2026-09-27). Read: README, `docs/SPEC.md`,
`docs/INTEGRATIONS.md`, `docs/AGENTS.md`, `LICENSE-ASSETS.md`, the Tauri port (`windows/`), 6 design captures.
Everything quoted from the repository is third-party material; nothing here is copied code.

## 1. What Coucou is

A "Dynamic Island" for the Mac notch that watches AI coding agents (Claude Code, Codex, Cursor, Gemini CLI…).
A character ("Mochi") lives in the notch; the island changes shape with what the agents are doing.

| Piece | How it works |
| --- | --- |
| Island modes | `hidden` (nothing running: invisible) → `peek` (hover the notch: the character waves) → `compact` (work running: a thin strip, character + up to 4 mini agents) → `expanded` (640 pt wide, views below). Open 520 ms spring, close 340 ms ease; size, corner radius, character and mini characters animate together as one shared element. |
| Views | overview (focused agent + a 4-line ticker of its latest actions, other agents as pills), approval (command in a code block, Deny N / Always / Allow Y), question (options as buttons), error, finished (5.2 s then collapses), prompt (quick chat with a model chip), file drop (the character becomes a box and swallows the file), searching, result. |
| Behaviour rules | Auto-collapse after 60 s without interaction (a 2 pt countdown line in the last 10 s); user away 3 min → hidden even with work running; alerts (permission, question, error) open by themselves even when the user is away and stay open; several alerts queue, one at a time; `Esc` closes; never steals focus; clicks outside the shape pass through (cursor polled at 60 Hz, `ignoresMouseEvents` toggled). |
| Character | Procedural (SwiftUI Canvas / Canvas 2D): squircle body, eyes projected on a sphere that follow the mouse, blinks; 11 states with a colour each (working blue, thinking violet, approval amber with a "!", question cyan "?", error red with a shake, finished green with a roll and sparkles, sleeping grey with "z"…); emotes; a coloured glow behind it; cards get a radial colour veil from the bottom in the state colour. |
| No notch | A small black bar at the top centre (iMac, Mac mini, lid closed on an external display). |
| Plumbing | Agent hooks → a tiny relay → Unix socket (0600, same-user check) → app; the relay gives up after 300 ms so the agent is never blocked; approvals wait for a click and answer the hook. Keys in the Keychain; no telemetry. Sounds: 28 short WAVs, default volume 0.12, mutable. |
| Stack | macOS: native Swift 6 / SwiftUI / AppKit (`NSPanel` above the menu bar). Windows/Linux: **Tauri 2** — a transparent, always-on-top, never-focused window; island drawn in the webview. |

**Licence.** Code: MIT (we may adapt it with the copyright notice). The name, the Mochi character, icons,
sounds and media: all rights reserved (`LICENSE-ASSETS.md`). Arslan must use its own mascot, icon and sounds.

## 2. What Arslan already has

| Coucou needs | Arslan today |
| --- | --- |
| A resident process with a menu-bar item | Tauri shell keeps the backend running with the window closed; tray item with a status line ("N working / N waiting / keeping awake"), Open, Quit (`desktop/src-tauri/src/resident.rs`). |
| Work state to show | `GET /api/v1/desktop/status`: counts of work in flight and cards waiting, plus a ring of events (turn finished, approval needed, scheduled finished/paused, proactive) — IDs and outcomes only (`server/services/desktop_status.py`). Background jobs with live frames; 0.1.50's plan (`update_plan`) and status facts (files saved, work so far). |
| Approvals | Confirmation cards (run_command, browser/Mac actions, workspace writes, schedules) answered by a click in the chat window. Background-job cards already live in a registry any surface can answer (`server/services/approvals.py`); chat-turn cards are answered inline on the conversation socket. |
| Notifications | Native notifications without message content (safe on a locked screen); a click opens the conversation. |

So the gap is the **surface**, not the engine: Arslan knows what it is doing, but you see it only by opening
the window.

## 3. Recommendation: an "Arslan Island" (adapt, don't port)

Take Coucou's interaction model and visual language; keep Arslan's own engine, character and safety rules.

**Take**
1. **Island window and modes** — hidden when idle; compact strip while Arslan works (mascot + small count);
   expanded on hover or click. Same timings and shared-element motion; collapse after 60 s idle; hidden when
   the user is away; alerts open on their own and queue; `Esc`; never steals focus; click-through outside
   the shape; no-notch bar fallback.
2. **Views mapped to Arslan's events**
   - *Overview*: the running turn or background job — its plan ("[x] find sources [>] collect 6/10"), a ticker
     of its latest steps from the tool frames it already emits ("Reading jobs.bytedance.com", "Saving
     jobs.csv"), other jobs as pills.
   - *Approval*: the same cards as the chat window — full command or action text, Deny (N) / Allow (Y), and
     "Don't ask again" only where the window offers it today.
   - *Question*: `ask_user_choice` options as buttons.
   - *Finished*: one line of what was done + "Open file" / "Open conversation", 5 s, then collapse.
   - *Stopped / error*: the 0.1.50 closing message ("stopped at the work limit, saved X") with "Continue".
   - *Ask*: a prompt field that starts a conversation or background work; *file drop* onto the island saves
     the file into the workspace and offers "Ask about it".
3. **Mascot with states** — Arslan's own head (the brand mark), drawn procedurally like Coucou's
   (no image assets): idle, working, thinking, searching, waiting for you (amber "!"), question (cyan "?"),
   error, finished (green), sleeping. Colour glow and card veils in the state colour.
4. **Optional sounds** — Arslan's own, off by default.

**Leave out (for now)**
- Watching other agents (Claude Code / Codex hooks) — Coucou's core, not Arslan's job; could come later.
- Service pollers (Stripe, n8n, Vercel…) — Arslan has MCP and proactive checks for that.
- Dragging the mascot onto a window to attach it as context — needs Screen Recording; later, if wanted.
- Coucou's playful extras (slap → dizzy, hearts) — optional polish, not first.

## 4. How it would be built (Tauri on macOS)

- **Window**: a second webview window `island` — transparent, no decorations, always on top, skip taskbar,
  never focused; converted to a non-activating `NSPanel` at a level above the menu bar with
  `canJoinAllSpaces | fullScreenAuxiliary | stationary | ignoresCycle` (objc2, ~100 lines in the shell).
  `NSWindow.sharingType = .none` so the island never appears in screen recordings or shares.
- **Notch geometry**: `NSScreen.safeAreaInsets.top` and `auxiliaryTopLeftArea/RightArea`; bar fallback
  without a notch.
- **Click-through**: Coucou's pattern (MIT) — a cursor poll thread that runs only while the island is
  visible and toggles ignore-cursor-events against the shape the front end reports.
- **Front end**: a React route `/island` in the existing web app, fed by `desktop/status` and the
  conversation/job frames; animations in CSS/WAAPI; mascot in Canvas 2D, paused when hidden.
- **Backend**: route chat-turn confirmation cards through the existing `approvals` registry (as job cards
  already are), so the island can list and answer them; a narrow island feed (current step, plan, cards with
  their display text). Approval stays a click (voice never approves); "remember" keeps today's rules.

**Mainstream comparison (approving outside the main window)**: Coucou approves Claude Code permissions from
the notch; Claude Code and Codex desktop approve in the app window; macOS itself offers actionable
notifications. Approving from the island with the same card content, per click, is the same bar as the
window — no rule is loosened.

## 5. Phases (each: tests + mutation checks + UI check in the preview; no paid model runs needed)

| Phase | Content | Size |
| --- | --- | --- |
| I1 | Island window, notch geometry and fallback, modes and rules, click-through, overview and finished/stopped views (read-only), screen-share exclusion | 3–4 days |
| I2 | Approvals and questions from the island (approvals registry for chat cards, feed, Y/N) | 2–3 days |
| I3 | Ask field, file drop, mascot states and motion, optional sounds | 3–4 days |

## 6. Open questions for the owner

1. Mascot: animate the existing Arslan head (recommended), or a new character?
2. Sounds: none, or a small set made for Arslan?
3. Should the island show command text during approvals (needed to decide) — and hide all content while
   the screen is shared (recommended, via `sharingType = .none`)?
