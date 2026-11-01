# IPB: what iPhone 1.0's part B reads from the Mac

| | |
|---|---|
| Grade | Must (user, 2026-11-01, relayed by ④参谋: option (b)). iPhone 1.0 goes to App Store review after v0.1.64, with parts A and B of round 2 complete, as the user decided on 10-26. |
| Lanes | ②Main: Bridge and server. ①iOS: reviews the frame list and each PR's frames, and builds nothing new on the phone (part B is built and waits for data). |
| Hard gate | **The user's explicit OK on the frame change list** (step 2 below). No code that touches a Bridge frame, `hello`, the shared vectors or `docs/specs/mobile-bridge-protocol.md` starts before it (the user's standing rule; `docs/sessions.md` §2). |
| Order | After the INB7 chain (#622 → #636), on ②Main's lane. Off the SBX → CLS critical path. |
| Effort | high for the build and ordinary reviews. effort=max only for the security-surface review of the Bridge PRs (what leaves the Mac, and over which channel). |

## Why

- The user decided on 10-26 that iPhone 1.0 is submitted only once round 2 is complete, parts A and B (`docs/plans/0162/README.md` §8, "iPhone 1.0 要的 Mac 端字段").
- Part B's fields were listed there and in ①iOS's 10-26 proposal, but v0.1.64 had no card for them. README §2 defers only renames, the four-line brief and sub-sessions to v0.1.65, so this was a gap, not a deferral (⓪Plan and ①iOS, 2026-11-01).
- Without the data, the App Store build hides the panels, which is guideline 2.1. So 1.0 could ship without IPB. The user chose to keep the rule instead.

## Reference

- **The phone side already exists** (①iOS, `claude/core-loop` at `afdde75`, in the iOS repo `arslan-ios-core-loop`):
  - `Availability.partB(hasData:)` (`ArslanApp/Design/Availability.swift:9`) returns show, comingSoon or hidden. `AvailabilityTests` pins the three states.
  - Part B's fields decode leniently (`8d2638c`), so a Mac that sends them lights the panels with no phone update.
  - Panels: the Overview's Mac rings (`OverviewView.swift:131-149`); the today/7-day picker and view (`OverviewActivity.swift:17-39`); the cost and self-handled numbers (`:118`); and in a conversation's details, the "on the Mac" section and the cost (`DetailsView.swift:133-173`).
- **The approved design:** the iOS repo at `0fddad1`, `docs/superpowers/specs/2026-10-18-iphone-mac-card-rail-files-design.md` §4.6 and §5.
- **①iOS's field proposal:** the iOS repo's `claude/core-loop`, `docs/protocol/2026-10-26-mac-0164-fields-proposal.md`. Every field is an optional addition; no existing field changes.
- **System sources:** Apple's `IOPSCopyPowerSourcesInfo` (battery), `host_statistics64` / `host_processor_info` (CPU and memory), the `kern.memorystatus_vm_pressure_level` sysctl (pressure), `URLResourceValues.volumeAvailableCapacityForImportantUsage` (disk) and `NWPathMonitor` (network type, with no SSID). ②Main confirms none of them needs a new entitlement or TCC permission; the SSID APIs do, which is one more reason to leave the name out.

## Raw material (on main at `d98a411c`)

- `desktop/bridge/Sources/BridgeCore/StatusReporter.swift:27-51`:
  - `status.snapshot` is posted to each peer when the headline/detail signature changes (`:54-59`);
  - its body is `/api/v1/phone/status` plus `jobs`, `device_name` and `last_seen`.
- `docs/specs/mobile-bridge-protocol.md`:
  - `:243` is `status.snapshot`'s field table;
  - `:301` is `status.snapshot.activity`, today's hours, which already exists;
  - `:245` and `:348` are `chat.history.result`.
- `desktop/bridge/Sources/BridgeCore/ConversationLinks.swift`:
  - `:363-370` builds `chat.history.result`, with a 560 KB trim;
  - `:558` is `hello.capabilities` (`new_conversation` and `quick` are already there).
- **Cadence:** Mac state (CPU, memory, battery) changes every few seconds, but today's signature resends only on job or presence changes. If state were part of the signature, every CPU tick would become an iCloud write.

## What the frame list must settle (step 2, ②Main and ①iOS)

For each field: its name, type, unit, whether it's optional, which frame carries it, how often it's sent, and what an older phone does with it. Names are ②Main's; ①iOS reviews.

1. **Mac state in `status.snapshot`:**
   - battery: charging, minutes left;
   - CPU: now, plus the last hour as 12 five-minute averages;
   - memory: used, total, and macOS memory pressure;
   - disk: free, total;
   - network: type and quality, **never the Wi-Fi name** (privacy, and newer macOS gates it behind location);
   - sleep: whether Arslan is holding the Mac awake;
   - OS version.

   **Cadence:** state rides its own slower clock (proposal: refresh at most every 5 minutes, or when the phone opens the Overview), not the headline signature.
2. **Per conversation in `chat.history.result`:**
   - environment: model, the folder's display path, the mode name;
   - context: used and window tokens, split into system, tools and chat;
   - the conversation's connectors: name, kind, on/off;
   - changed files: net lines added and removed over the whole conversation, plus the last run and step that changed one. The Mac computes this, because a run carries 40 steps and history 200 messages, so the phone would undercount;
   - this conversation's cost.

   It must stay inside the 560 KB trim.
3. **Week and result stats** (in `status.snapshot.activity`, or a sibling):
   - 7 days of replies, tasks and cards;
   - today's and this week's task results: each task's checks all passed or not, its cost, and how many times it needed the user.
4. **`hello` flags:** whether the phone needs any. It gates on data (`Availability.partB`), not flags, so ①iOS may say none. Say so explicitly either way.
5. **Not in IPB** (①iOS's "wanted, not urgent"): `conversation.rename`, already set aside on 10-28, and list paging, which Q1 did.

## Method

- **Red tests first:**
  - **Server:** each new field on `/api/v1/phone/status` and the history endpoint, with a fixture that discriminates (e.g. changed-file totals over more than 40 steps, a conversation with two connectors, one off).
  - **Bridge:** a snapshot without state when the backend omits it; the state clock doesn't post on a CPU change alone; `chat.history.result` stays under the trim with every new field filled.
  - **Shared vectors** in `spec/mobile-bridge` for each new shape, so `SharedProtocolV1Tests` on the phone decodes them.
- **Mutation on the computed numbers:** the changed-file totals, the cost per conversation, the 5-minute averages and the week window.
- **Probe:** `scripts/dev/probe.sh` with a scratch HOME. It reads `/api/v1/phone/status` and one history result, and shows the new fields filled and the Wi-Fi name absent.
- **Privacy check in a test:** no SSID, no BSSID, and no IP address anywhere in the snapshot body.

## External evidence

- CI ids for each PR, and the commit that turns each new test red.
- ①iOS's decode run of the new vectors (`SharedProtocolV1Tests`).
- **A real-Mac check with the user present:** build 31 or later paired to a Mac with IPB. The Mac rings, the 7-day view and a conversation's details all show real values. Then a release build with no `ArslanComingSoon` against a Mac without IPB hides them. That second half is already on ①iOS's pre-submission list.

## The privacy line

The aralem.dev privacy page (`aralem.dev/arslan/privacy`, site repo) gets this line, live with or before the Mac version that starts sending state: "Your Mac's battery, CPU, memory, disk and network state sync to your iPhone through your own iCloud". It can't wait for an iOS build, because an existing phone shows the data with no update. ①iOS expects no change to the App Privacy label: the data goes from the user's Mac to their own iPhone, end-to-end through their iCloud private database, and the developer never receives it. That's ①iOS's reading, not a ruling; the user confirms it at submission.

## Size and PRs

- **Expected:** about +500 product lines and +400 test lines, in two or three PRs:
  1. server fields, endpoint by endpoint;
  2. Bridge frames and their vectors;
  3. stats, if they don't fit in 1.
- Each Bridge PR gets ①iOS's review of its frames, plus the effort=max security review of what leaves the Mac.

## Rollback

Every field is optional. Reverting a PR stops the Mac sending that field, and the phone hides the panel again. No migration is planned. If the per-conversation cost needs one, it takes the next free number, which is 0086 at this writing.
