# 0.1.53 — Hands: Arslan uses Mac apps through agent-desktop (2026-10-03)

Task book: `~/Documents/arslan-strategy-2026-09-14/Arslan-越用越好+手脚+判断层-任务书-2026-10-03.md`, task B
(B0–B5). User decisions 2026-10-03: D1–D5 as recommended; **D3: the user clicks "Allow" on the macOS
Accessibility prompt for "Arslan Hands" the first time it is used.** Ships as 0.1.53, in parallel with 0.1.52
(P4a memory + judgment layer). This work does not touch memory, personal_context, learning or the judgment
ledger.

Today Arslan's hands are the browser (0.1.45, Playwright) plus Shortcuts and AppleScript. Native apps (Notes,
Finder, Mail drafts, Pages…) can only be reached by AppleScript, which the user must read and allow every time.
agent-desktop gives a structured accessibility (AX) tree with stable refs, background (no focus, no mouse)
actions, and refusals (`STALE_REF`, `AMBIGUOUS_TARGET`) instead of guessed clicks.

## 0. Measured before designing (2026-10-03, this Mac, macOS 26.6)

**B2.1 — does a command inherit an Accessibility grant?** Yes, and the P3 sandbox does not stop it.

| # | What ran | Result |
| --- | --- | --- |
| M1 | A freshly compiled Swift binary (`print(AXIsProcessTrusted())`), never granted anything, run as a child of a process whose responsible app holds Accessibility | `true` |
| M2 | The same binary under `sandbox-exec` with the exact P3 profile (`command_sandbox.profile(...)`) | `true` |
| M3 | The same binary spawned with responsibility disclaimed (`responsibility_spawnattrs_setdisclaim`) | `false` |
| M4 | agent-desktop 0.9.4 (built from source, never granted) `permissions` from the same shell | `accessibility: granted` |

macOS checks Accessibility against the *responsible process*, which children inherit; seatbelt does not change it
(M2), and only cutting the responsibility link removes it (M3). So if the process that Arslan's commands descend
from ever held Accessibility, every `run_command` — including the sandboxed ones that need no click — could
drive any app's UI.

Two more measurements fix the shape of the helper:

| # | What ran | Result |
| --- | --- | --- |
| M5 | A probe app launched with `open` (LaunchServices), spawning a Resources binary that spawns a leaf (C and Rust `std::process::Command` parents) | app: parent 1, responsible = itself; sidecar and leaf: responsible = the app |
| M6 | Installed Arslan 0.1.50: `responsibility_get_pid_responsible_for_pid` on the running shell and backend | shell → itself; backend `arslan-server` → **itself** (not the shell) |
| M7 | The same `arslan-server` binary started from a shell | inherits the shell's responsible process |

M5 says an app started through LaunchServices is its own responsible process, and its grant is not shared with
Arslan's backend or the backend's children. M6/M7: in the installed app the backend is attributed to itself
(cause not yet found — M7 rules out the binary disclaiming at start; the shell spawns it with a plain
`Command`); either way the backend's children inherit *the backend's* identity. The conclusion does not depend on
which of the two is responsible: **whatever holds Accessibility must not be an ancestor of `run_command`.**
⇒ A separate helper app, "Arslan Hands", launched through LaunchServices, holds the grant; neither Arslan.app nor
the backend ever does.

**The P3 protected paths do not stop a socket connection.** A `0600` Unix socket inside a directory listed in
`default_protected()` (`deny file-read* file-write*`, last rule): a sandboxed `python3` still connected and read
from it. Only `(deny network-outbound (subpath …))` / `(literal …)` refused it (`EPERM`). So "add the socket to the
protected paths" needs a profile change, not only a list entry (§2.3).

**agent-desktop 0.9.4 facts used below** (read in the source at `a4a695fd`, built locally: `cargo build --release
--locked -p agent-desktop` = 45 s, 3.2 MB binary):
- Every command prints one JSON envelope `{"version":"2.4","ok":…,"command":…,"data"|"error":…}`; exit 0 / 1
  (structured error) / 2 (argument error). Error codes: `PERM_DENIED, ELEMENT_NOT_FOUND, APP_NOT_FOUND,
  ACTION_FAILED, ACTION_NOT_SUPPORTED, STALE_REF, AMBIGUOUS_TARGET, WINDOW_NOT_FOUND, PLATFORM_NOT_SUPPORTED,
  TIMEOUT, INVALID_ARGS, NOTIFICATION_NOT_FOUND, SNAPSHOT_NOT_FOUND, POLICY_DENIED, APP_UNRESPONSIVE, INTERNAL`;
  errors carry `suggestion`, `recovery` and `disposition.retry`.
- Default delivery is headless (AX actions, PID-targeted keys; `press --app` tries the menu shortcut, then an AX
  action, then a PID-targeted key — it focuses the app only with `--headed`). Arslan never passes `--headed`.
- **It types into secure text fields** (`AXSecureTextField` is accepted by `type`); it only hides their value
  and marks them with the `secure` state. Refusing passwords is our job (§2.4).
- It also has clipboard, Notification Center, `launch --cdp`, screenshot and mouse-coordinate commands. Arslan
  never calls them (§2.4).
- State lives under `AGENT_DESKTOP_HOME` (default `~/.agent-desktop`): snapshots/refmaps, sessions, cursor-overlay
  sockets. The cursor overlay is a child process of the CLI with a caller-written `--label`.

## 1. Maintenance: fork, pin, source build, contract layer

- **Fork** `lahfir/agent-desktop` → `mirzatghayrat/agent-desktop` (public; **asked of the user before
  creating it**). Branch `arslan/0.9.4`: upstream `v0.9.4` (`a4a695fdd1f673426579696c7e17074910e799fc`) plus one
  commit that adds `vendor/` (`cargo vendor --locked`) and `.cargo/config.toml` pointing crates-io at it. That
  commit's SHA is the pin.
- **Pin** in this repo: `packaging/hands/agent-desktop.pin` — repository URL, commit SHA, upstream tag. The build
  script refuses any checkout whose `HEAD` is not the pinned SHA.
- **Build** (`packaging/hands/build_hands.sh`, called by `build_dmg.sh` as step 4c): fetch the fork at the pin
  (or use `HANDS_AGENT_DESKTOP_SRC=<local checkout>` for development — same SHA check) →
  `cargo build --release --locked --offline -p agent-desktop` (vendored; no crates downloaded) → record its
  sha256 in the build log and in `Arslan Hands.app/Contents/Resources/agent-desktop.sha256` → build our helper →
  assemble `Arslan Hands.app` → sign inside-out with the Developer ID (hardened runtime, timestamp, no
  entitlements). Notarization is the DMG's existing notarization (nested code is checked with it).
- **Supply chain**: `cargo deny check` (licenses, bans, sources, advisories) on the pinned fork, in CI (Linux)
  and before the release build. The fork's own `deny.toml` allows Apache-2.0/MIT/MPL-2.0/Unicode-3.0/Unlicense
  and only crates.io. `THIRD_PARTY_NOTICES.md` gets the Apache-2.0 attribution for agent-desktop (and its
  NOTICE file if upstream adds one).
- **Contract layer** — Arslan uses 11 commands: `snapshot, find, get, click, type, set-value, press, scroll,
  list-apps, list-windows, wait`. `tests/fixtures/hands_contract/` holds one case per command plus one per error
  code we handle: the request Arslan makes, the exact argv it must produce, a real envelope, and what Arslan must
  make of it. Both layers read the same files: the helper's Rust tests (argv building, envelope checks) and the
  backend's pytest (parsing, error mapping, retry hints). Both run on Linux CI. Any binary — upstream's, our
  fork's, or a future trimmed reimplementation — must pass `scripts/hands_contract_check.py --binary …`, which runs
  the same cases against a real binary and a fixture app on a Mac with Accessibility (the release smoke).
- **Monthly sync**: read upstream releases and the diff of `crates/core`, `crates/macos`; take security fixes into
  the fork; re-vendor; move the pin; run the contract check and the smoke. **Exit plan**: upstream silent > 3
  months or diverging → maintain the fork ourselves; long term, trim to the 11 commands in our own crate behind
  the same contract tests.

## 2. Security design

### 2.1 Isolation: the "Arslan Hands" helper app

`Arslan.app/Contents/Resources/hands/Arslan Hands.app`, bundle id `com.arslan.desktop.hands`, `LSUIElement`
(no Dock icon), its own icon and name in System Settings → Privacy & Security → Accessibility.
- `Contents/MacOS/arslan-hands` — our small Rust program (new crate `desktop/hands/`, deps: serde, serde_json,
  libc). `Contents/MacOS/agent-desktop` — the pinned build. arslan-hands spawns agent-desktop per command; being
  their parent, it is their responsible process, so only Hands' grant applies.
- Started by the backend on first use with `/usr/bin/open -g -j <path>` (LaunchServices: own responsible process
  (M5), no focus taken). It takes **no arguments and reads no environment for its own configuration**: anything a
  command can pass on a command line, a command could abuse.
- Its folder is fixed: `~/Library/Application Support/Arslan Hands/` (0700), derived by Hands itself — not Arslan's
  data folder, because Hands must find it without being told (dev and packaged data folders differ), and because
  a location passed in could be one a command controls. Inside: `lock` (single instance, `flock`), `s.sock`,
  `ready.json`, `ad/` (agent-desktop's `AGENT_DESKTOP_HOME`).
- Quits after 15 minutes without a request, and on the backend's `quit`.

### 2.2 The channel: 0600 socket, per-launch token, verified peer

- Hands binds `s.sock` with mode 0600 (umask 077, then `chmod`, then `listen`), generates a 32-byte token from
  `getentropy` at every launch, and writes `ready.json` `{pid, version, token, socket}` 0600 atomically (temp +
  rename) only after it listens.
- Every request is one JSON line `{token, id, op, args}`; the token is compared in constant time.
- **Peer check (signed builds).** Hands reads the connecting process's audit token (`LOCAL_PEERTOKEN`) and
  requires its code signature to satisfy `anchor apple generic and certificate leaf[subject.OU] = "<Hands' own
  Team ID>" and identifier "arslan-server"`. Without it, any process of the user that can read `ready.json` (an
  approved outside-sandbox command, anything else running as the user) could borrow Hands' Accessibility grant.
  Hands reads its own Team ID from its own signature; an unsigned/ad-hoc Hands (development) has none, skips the
  check and says so in `status`. Release builds are checked end to end by the fresh-install acceptance (§5).
- Socket path length: macOS allows 104 bytes; Hands refuses to start with a clear error rather than truncating.

### 2.3 What a command can reach (P3 sandbox)

`command_sandbox.default_protected()` adds `~/Library/Application Support/Arslan Hands` (socket, token, state).
`profile()` gains `(deny network-outbound …)` for every protected path, after the file rule (measured in §0: the
file rule alone lets `connect()` through). This also closes the same latent gap for any socket ever created under
Arslan's data folder. `run_python` already denies all network.

What remains: a command the user explicitly let out of the sandbox runs as the user. It can read `ready.json`, but
the peer check refuses it in signed builds.

### 2.4 Never

Enforced inside Hands (so a backend bug cannot open them) and repeated in the backend for a clear message:
- **Only the 11 commands**, built from structured requests; never `--headed`, `--screenshot`, `--debug`,
  `--force`, `launch`, `clipboard-*`, `*-notification*`, `screenshot`, mouse-coordinate commands, `batch`.
- **No typing into password fields**: before `type`/`set-value` Hands reads the target's states and refuses
  `secure` (`AXSecureTextField`).
- **No clipboard reads** (no clipboard command is reachable). **No CDP port** (`launch` is unreachable).
  **No Notification Center** (its surfaces and commands are unreachable; it is on the deny list).
- **Deny list** (no looking, no acting), visible in Settings → Desktop, built in and not removable; the user can
  add apps: Keychain Access, Passwords, 1Password, Bitwarden, Dashlane, LastPass, KeePassXC, Enpass, Proton Pass;
  System Settings (the whole app — the Privacy & Security pane is one search away inside the same window, and
  pane titles are localized); the macOS security dialogs (SecurityAgent, coreautha, UserNotificationCenter);
  Notification Center; **Arslan itself and Arslan Hands** (otherwise Arslan could click "Allow" on its own
  confirmation cards).
- **Tiers by app kind** (Claude's computer use does the same: browsers read-only, terminals and IDEs click-only):
  - terminals and code editors (Terminal, iTerm, Warp, Ghostty, kitty, Alacritty, WezTerm, Script Editor,
    VS Code, Cursor, Xcode, JetBrains IDEs): look and click only — typing there would run commands outside the
    command sandbox and its cards;
  - web browsers (Safari, Chrome, Edge, Firefox, Arc, Brave, Opera, Vivaldi): look only — acting on web pages goes
    through Arslan's own browser (0.1.45), where the rules for sites already apply.
- **Screenshots**: none. Hands is AX-tree only and never asks for Screen Recording.

### 2.5 When the user is asked (same shape as the 0.1.45 browser)

| Tool | Kind | Asks |
| --- | --- | --- |
| `desktop_apps` | read (running app names) | never |
| `desktop_look` (snapshot, find, wait for text; windows) | read | first time per app per conversation |
| `desktop_click/type/select/press/scroll` | act | only inside a background job; first time per app per job |
| an action whose *real* target label (read live from the element, not the model's words) or key matches delete / send / pay / buy / transfer / submit (删除、发送、付款、购买、转账、提交, and the other UI languages) | high-risk act | every time, card shows the real label |

Also high-risk, every time: `press` of delete/send shortcuts (`cmd+delete`, `cmd+backspace`,
`cmd+shift+delete`, `cmd+shift+d`, `cmd+return`, `cmd+enter`), and `press return/enter` or typed text ending in a
newline in messaging and mail apps (Messages, Mail, Slack, Discord, Telegram, WhatsApp, WeChat, QQ, Lark/Feishu,
DingTalk, Teams, Outlook, Spark) — there Return sends. Grants live in memory only; a job's grants die with the
job (as `hands_tools.forget_job`). A ref must belong to the app it is used for: Hands resolves the ref's process
from agent-desktop's refmap and refuses a mismatch (`ref_wrong_app`), so a grant for Notes cannot be spent in
Mail.

### 2.6 Seen and stoppable

- **Cursor overlay** on by default: Hands starts one agent-desktop session per job with the cursor and labels it
  "Arslan …" with the current action (localized by the backend).
- **Island**: the step line shows the app and the element ("Notes · New Note"); while Hands is acting, the island
  shows a Stop button.
- **Trace**: the backend appends every Hands call to `<data>/hands/trace/YYYY-MM-DD.jsonl` (file 0600, folder
  0700): time, conversation, job, app, op, target label, outcome code, duration. Typed text is recorded as its
  length only. Files older than 7 days are deleted on write and at start. Activity gets a "Hands" list.
- **Stop**: one action stops every Hands action — the island's Stop and a "Stop Arslan's hands" item in the
  menu-bar menu, both `POST /api/v1/hands/stop`. Hands kills the agent-desktop process in flight (SIGKILL), ends
  the cursor sessions, and every job that was running refuses further Hands calls with `stopped_by_user` (jobs
  started later are unaffected). Target: under 1 second, measured by the smoke.

## 3. Wiring into Arslan

- `server/registry/hands_tools.py`: seven tools — `desktop_apps`, `desktop_look {app, ref?, text?, role?,
  wait_for_text?}`, `desktop_click {app, element, ref}`, `desktop_type {app, element, ref, text, replace?,
  submit?}` (`replace` = `set-value`), `desktop_select {app, element, ref, value}`, `desktop_press {app, keys}`,
  `desktop_scroll {app, element, ref, direction, amount?}`. Results are external text (framed as untrusted like
  web pages). Long trees are trimmed to the interactive skeleton first; drilling uses `ref`.
- New: `server/services/hands_client.py` (start Hands, read `ready.json`, one JSON line per request, timeouts),
  `server/services/hands_service.py` (settings file `<data>/hands/settings.json`, deny list, grants, stop latch,
  trace), `server/api/hands.py` (`GET /api/v1/hands` status + lists, `PUT` switch/extra apps, `POST stop`,
  `GET trace`). Hands' settings live in their own file rather than `settings_service` so 0.1.52 and 0.1.53 do not
  collide; the Settings page reads both.
- Small touches: tool descriptions (`orchestrator/arslan.py`) and schemas (`orchestrator/tool_loop.py`), the
  registry, `task_service.effect_of` (look = read, act = external_write), `desktop_status.step_target`, the
  card copy (`web/src/locales/hands.ts`, `ActionApprovalCard`), Settings → Desktop, Activity, the island, the
  tray menu (`resident.rs` + `native_messages.json`).
- **Recovery hints** on failure: `STALE_REF` → "the window changed: look again, then retry once";
  `AMBIGUOUS_TARGET` → "look again and use a ref from inside the right group"; `PERM_DENIED` → the user has not
  allowed Arslan Hands yet (Hands has just asked macOS to show its prompt; the tool says where the switch is);
  `APP_NOT_FOUND`/`WINDOW_NOT_FOUND` → open the app first (with the user's words), never `launch`.
- **Division of labour** (in the tool descriptions): web pages → Arslan's browser; native apps → Hands; Chromium
  apps (Slack, Notion, Discord) → Hands on their AX tree only.
- Offered when Hands is available: macOS, Hands' switch on (default on), and the helper present (packaged:
  next to the sidecar; development: `ARSLAN_HANDS_APP`).

## 4. Out of scope for 0.1.53

Screenshots and Screen Recording; mouse-coordinate input; `--headed`; CDP; the clipboard; launching apps;
drag-and-drop; Windows/Linux. A real-model multi-step evaluation is a paid round and needs the user's approval
(D4 style), separately.

## 5. Acceptance (task book B4)

1. **Real Mac**: in a background job Arslan creates a titled note in Notes, then renames a file inside the working
   folder in Finder, while the user types in another window undisturbed (no focus taken). First driven by a
   script through the real tool executors (no model cost), then — with the user's approval — once by a model.
2. Refusals: a password field; a deny-listed app; acting without a card or outside a job; Stop takes effect in
   < 1 s.
3. A sandboxed command cannot connect to Hands' socket nor read its token (pytest, macOS-marked, real seatbelt);
   Arslan.app and the backend never hold Accessibility (only `com.arslan.desktop.hands` appears in the list).
4. Contract tests on Linux CI (Rust + pytest); `scripts/hands_contract_check.py` + the smoke on a Mac for every
   release; mutation checks on the policy, the peer check, the never-list, the sandbox profile.
5. Release: `cargo deny` green; fresh-install acceptance checks Hands' bundle id, signature and Team ID, and a
   handshake through `GET /api/v1/hands` (ready, peer verified; Accessibility not granted on CI is expected).

## 6. Order

S1 sandbox: the protected path + `network-outbound` rule (+ macOS test). S2 the helper crate (protocol, never-list,
argv builder, peer check) + contract fixtures. S3 backend client/service/tools/policy + API. S4 web: cards,
Settings, Activity, island; shell tray item. S5 packaging: pin, build script, cargo-deny, notices, fresh-install
checks, CI. S6 smoke + contract check on this Mac (the user clicks Allow once — D3). Version 0.1.53 last, after
0.1.52's state is known.

## 7. Amendments — measured while building (2026-10-03)

These change the design above; each was measured on the user's Mac (macOS 26.6).

1. **agent-desktop is not inside the bundle** (changes §2.1). With it in `Arslan Hands.app/Contents/MacOS`, running it
   on its own with responsibility disclaimed reported Accessibility **granted**: macOS lent it the bundle's grant, so
   any process (a sandboxed command included) could have driven apps past the token, the peer check and every card.
   It now sits beside the bundle (`hands/agent-desktop`): run on its own → **denied** (measured); run by Hands → it
   inherits Hands' grant as Hands' child. Being a plain file it could be swapped, and a swapped binary run by Hands
   would inherit the grant, so Hands checks its sha256 against `Contents/Resources/agent-desktop.sha256` (inside the
   sealed bundle) before every run; a signed Hands without that record refuses to start.
2. **Hands is a real Cocoa app.** Without an `NSApplication` run loop LaunchServices never saw it check in: Finder
   called it "not responding" and it never appeared in the Accessibility list. It now runs `NSApplication`
   (accessory policy, no Dock icon) on the main thread and serves the socket on another; check-in 0.6 s.
3. **D3 needs a properly signed Hands.** An ad-hoc build could be listed and switched on and still not be trusted.
   Signed (Developer ID in releases; a personal Apple Development certificate for development), macOS showed its
   prompt by itself and the grant applied at once. Development switches, refused for a DMG:
   `HANDS_SIGN_TIMESTAMP=none` and `HANDS_DEV_UNVERIFIED_PEER=1` (a cargo feature that turns the peer check off so a
   personally signed Hands can serve an unsigned dev backend). `build_dmg.sh` refuses the latter and the
   fresh-install acceptance requires `peer_check == "verified"`.
4. **Twelve commands, not eleven**: `select` (pop-ups, lists) joins the contract.
5. **`desktop_type` sets the value.** Headless `type` needs a focused field (POLICY_DENIED otherwise, measured) and
   Hands never takes focus, so the tool uses `set-value` (append = read, then set) and falls back to `type`.
6. **Focus guard.** Notes brings itself forward on New Note (measured). Around every action Hands notes the front
   app; if the app acted on took the front, Hands gives it back.
7. **Window titles come from accessibility.** Without Screen Recording the window list carries no real titles
   (agent-desktop fills in the app's name: every Finder window was "Finder"), so `desktop_look {window}` reads each
   window's title with a one-level look. A look at an app with several windows and none named uses the focused one.
8. **Only the current Space.** agent-desktop sees on-screen windows of the current desktop only: apps on another
   Space or behind a full-screen app are "not open". Said in the tool's advice; a known limit.
9. **A busy Mac times out** (a simulator, many windows): Notes' tree and the global window inventory timed out
   intermittently and succeeded on the next try, so reads are repeated once on TIMEOUT; actions never are.
10. **Team-ID-prefixed bundle ids** (`2BUA8C4S2C.com.1password.browser-helper`, seen live) are matched without the
    prefix, so the prefix cannot hide an app from the lists.
11. **Peer check, measured** with a Developer ID-signed Hands: `arslan-server` signed by the team + token → accepted;
    wrong token → `bad_token`; same team, other identifier → `peer_not_allowed`; unsigned `python3` holding the
    right token → `peer_not_allowed`.
12. **Test hygiene.** Running AX-calling test binaries with responsibility disclaimed adds them to the
    Accessibility list (and one was switched on by mistake). Tests now build such binaries only in temporary paths
    that are deleted afterwards, and the user is told which entries to remove.
13. **Real-Mac acceptance (B4.1), measured on the user's Mac with the user typing in another window.** Notes passes
    in full: New Note by cmd+n, the empty body found as the focused text field, title and text set, the note read
    back — and across 10 actions Hands never had to give the front back (no focus taken). **Finder renaming in the
    background is not possible with agent-desktop 0.9.4 headless**, measured three ways: a click on a file row is
    `AXOpen` (it fails, and where it works it would open the file, not select it); keys posted to a background
    Finder (cmd+a, Return) do nothing; `set-value` on the row's name field changes its accessibility value but
    Finder never commits it (the file keeps its name). Headed mode would work but takes focus, which §3 rules out.
    So the Finder half of the acceptance is changed: the file is **seen** in its window (column view: the rows sit
    under a `list` below the skeleton, opened with `desktop_look {ref}`), and the model is told to rename, move or
    copy files with `run_command` (mv/cp), which is the better tool for files anyway.
14. **The first release build from a clean fetch failed (run 37223227745), and only there.** The fork's
    `.gitignore` has a `.vim/` rule, so the vendoring commit `ccd72ee0` lacked memchr's and aho-corasick's
    `.vim/coc-settings.json`, which their `.cargo-checksum.json` list: `cargo build --offline` from a clean
    checkout stops at "failed to calculate checksum". Every local build used a checkout that still had the
    ignored files on disk, and CI only ran cargo-deny on the pin (it builds nothing), so nothing before the
    release run saw it. Reproduced locally from a clean clone (same error, exit 101). Fixed in the fork as
    `2c2f505e` (fast-forward on `arslan/0.9.4`): both files added, `.gitignore` ends with `!vendor/**`,
    ARSLAN-FORK.md says to check `git status --ignored -- vendor` before committing a re-vendor; a clean clone
    of it builds offline with an empty CARGO_HOME (37 s). The pin moved to it. Guards so this cannot hide
    again: CI checks every vendored file of the pinned commit against its checksums
    (`scripts/verify_vendored_checksums.py`: on `ccd72ee0` it names exactly those two files, on `2c2f505e`
    nothing), and `build_hands.sh` refuses a local checkout whose `vendor/` holds files git ignores.
15. **First run of the signed Hands on the user's Mac: refused although the switch showed on.** tccd logged
    "Failed to match existing code requirement for subject com.arslan.desktop.hands and service
    kTCCServiceAccessibility" for Hands and for its agent-desktop child (the child is judged as Hands, as
    designed). macOS keys the grant by bundle id and keeps the code requirement of the build that asked; the
    entry had been created by the development build (Apple Development certificate, same bundle id), so the
    Developer ID build matched nothing, no prompt appeared, and System Settings still showed the switch on. The
    model then fell back to AppleScript and osascript, one approval card per script ("it kept asking"). Changes:
    development builds now get their own bundle id `com.arslan.desktop.hands.dev` ("Arslan Hands (dev)"), still
    under the never-list's `com.arslan.desktop.*`; the PERM_DENIED advice tells the model to stop rather than
    switch to AppleScript, and tells the user to remove the entry and ask again; the settings line for "not
    allowed" says the same in six languages. A user who never ran a development build cannot hit this; a Developer
    ID re-sign keeps the team, so the requirement still matches across releases.
