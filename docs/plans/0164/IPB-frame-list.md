# IPB: the frame change list (for the user's OK)

> Step 2 of card IPB (`IPB-iphone-part-b.md`, PR #639). Written by ②Main from ①iOS's 10-26 proposal and its 11-01
> English restatement, and checked against the Mac's code on main at `d98a411c`. **No frame, `hello`, vector or
> protocol-spec code starts until the user OKs this list.** Four choices are marked **Decide**; each has a
> recommendation.
>
> **OK'd by the user on 2026-11-01, about 13:45 UTC, relayed by ④参谋:** 「帧 OK，1/2/4 按推荐，3 选 b」. The frames stand as listed
> below. Decides 1, 2 and 4 go as recommended (4 is option (a)). Decide 3 takes the alternative: `details.context`
> is left out of 1.0, so nothing new is recorded and there is no migration 0086 for it. The phone hides that row.

## The short version

- **Names:** the phone's. the phone already decodes every block below under these names, since `8d2638c` (TestFlight build 30
  and later; BridgeKit `PartBModels.swift`, iOS repo `claude/core-loop` at `afdde75`). Taking them as they are means no decode change on
  the phone (①iOS checked every name, type and req mark). The one phone change is wording: Decide 1's network words,
  phone only and no frame change, in build 31, which is needed before submission anyway. Where the Mac sends more than the phone reads, the extra keys are marked
  *phone ignores*; Swift's decoder skips unknown keys.
- **Frames:** two existing frames gain optional blocks:
  - `status.snapshot` gains `mac`, `week` and `outcomes`;
  - `chat.history.result` gains `details`.
- **No new frame types and no `hello` flag** (§4).
- **What older software does:**
  - **Older phones:** a phone from before part B (before `8d2638c`) ignores all four blocks.
  - **Part-B phones:** a part-B phone decodes each block on its own (`try?` per block), so a malformed block drops
    alone.
  - **Older Macs:** an older Mac sends none of the blocks, and the phone hides their panels.
- **Cadence:**
  - Nothing new posts a snapshot. The send signature stays as it is (`StatusReporter.swift:54-59`), so a CPU
    change never causes an iCloud write.
  - The new blocks ride the posts that already happen: a headline change, a phone's hello, and the 60 s
    heartbeat (`StatusReporter.swift:8`).
  - On those posts, the readings are at most about a minute old (disk: five).
- **Required vs optional:** inside each block, the fields marked **req** are required by the phone's decoder. If
  one is missing, the whole block is dropped. The Mac always sends required fields, and leaves out an optional
  field it doesn't know rather than sending `null`.

## 1. `status.snapshot.mac`: the Mac's own state

**Who builds it:**
- The Bridge reads the system values and merges them into the backend's snapshot body
  (`StatusReporter.snapshot`, `:47-53`). System reads stay in the Swift process that already runs every 2 s.
- Only `sleep` comes from the backend.

**Permissions:** none of the system calls below needs an entitlement or a TCC permission for Arslan (not
sandboxed, hardened runtime). The Wi-Fi name is the one that would, through Location, so it is never read.

| Field | Type | Unit, values | Req | Source | Read every |
|---|---|---|---|---|---|
| `mac.taken_at` | string, ISO 8601 UTC | when this set was read | **req** | Bridge clock | with the set |
| `mac.battery` | object | absent on a Mac without a battery | opt | `IOPSCopyPowerSourcesInfo` | 60 s |
| `mac.battery.level` | int | percent, 0–100 | **req** | `kIOPSCurrentCapacityKey` / max | |
| `mac.battery.charging` | bool | | **req** | `kIOPSIsChargingKey` | |
| `mac.battery.minutes_left` | int | minutes; only on battery, and only once macOS has an estimate (not −1) | opt | `kIOPSTimeToEmptyKey` | |
| `mac.cpu` | object | | opt | `host_processor_info` tick deltas | sampled every 10 s |
| `mac.cpu.now` | int | percent of all cores, 0–100, over the last 10 s sample | **req** | | |
| `mac.cpu.last_hour` | [int] | percent, 5-minute averages, oldest first, at most 12; only full buckets, so fewer than 12 (even `[]`) right after the Bridge starts (①iOS: fine; the phone draws only `now` today) | **req** | in-memory ring | |
| `mac.memory` | object | | opt | `host_statistics64` + sysctl | 60 s |
| `mac.memory.used_gb` | double | GiB (2^30), one decimal, as Activity Monitor's "Memory Used" (app + wired + compressed) | **req** | `vm_statistics64` | |
| `mac.memory.total_gb` | double | GiB, one decimal | **req** | `hw.memsize` | |
| `mac.memory.pressure` | string | `normal` / `warn` / `critical` | **req** | `kern.memorystatus_vm_pressure_level` (1 / 2 / 4) | |
| `mac.disk` | object | the startup volume | opt | `volumeAvailableCapacityForImportantUsage` | 5 min |
| `mac.disk.free_gb` | double | GB (10^9), one decimal, as Finder shows | **req** | | |
| `mac.disk.total_gb` | double | GB (10^9), one decimal | **req** | `volumeTotalCapacity` | |
| `mac.network` | object | absent until the first path update | opt | `NWPathMonitor` | on change |
| `mac.network.kind` | string | `wifi` / `ethernet` / `other` | **req** | `usesInterfaceType` | |
| `mac.network.quality` | string | `good` / `fair` / `poor`; see **Decide 1** | **req** | `NWPath` status flags | |
| `mac.sleep` | object | | opt | backend | with the snapshot |
| `mac.sleep.kept_awake` | bool | Arslan is holding off sleep right now | **req** | backend: the keep-awake setting and work running | |
| `mac.os_version` | string | `macOS 26.1` (major.minor[.patch]) | opt | `ProcessInfo.operatingSystemVersion` | once |

Not sent in IPB:
- `sleep_in_min`: macOS has no cheap, honest answer, and the field is optional on the phone.
- Any Wi-Fi name, BSSID or IP address. A test asserts that none of them is anywhere in the snapshot body.

**Decide 1: network quality.** macOS reports link state, not speed. **Decided: as recommended.**
- **Recommended:**
  - `good` when the path is satisfied and neither constrained (Low Data Mode) nor expensive (a phone hotspot);
  - `fair` when it is satisfied but constrained or expensive;
  - `poor` when it is not satisfied.
- The status sheet should read this as the kind of link, not a measured speed. ①iOS agrees and changes the phone's
  words in build 31 (phone only, no frame change): 「已连接」 / 「受限 · 低数据模式或热点」 / 「没有网络」, and on
  `poor` the advice 「检查 Mac 的网络」 instead of a weak-signal claim.
- The alternative is a timed round trip on each read. It is more honest about speed, but it adds network traffic
  for one ring, so I don't recommend it.

**`kept_awake` is a second copy of a rule.** The desktop shell holds sleep when the keep-awake setting is on and
work is running (`desktop/src-tauri/src/resident.rs:129`). The backend can see both, so it computes the same rule.
- A test pins the two against each other: the setting, the working count, the result.
- Reading the live power assertion from the Bridge would be exact, but it means parsing `pmset` output, so I don't
  recommend it.

## 2. `status.snapshot.week` and `status.snapshot.outcomes`

**Who builds them:**
- The backend's `/api/v1/phone/status` builds both, from persisted rows only.
- Today's `activity` partly counts from memory (running jobs, the island's events), so it resets on restart. The
  week must not.
- The Bridge calls that endpoint on every 2 s tick, so the backend caches both blocks for 60 s, and drops the cache
  when a run or job ends.

### `week`: the last 7 days

| Field | Type | Unit, values | Req |
|---|---|---|---|
| `week` | [object], 7 items | oldest first, the last item is today | opt (block) |
| `week[].day` | string | `yyyy-MM-dd`, the Mac's time zone | **req** |
| `week[].counts` | [int], 3 items | [replies, tasks, approvals asked], the order of `activity.hours` | **req** |

How each count is made:
- **Replies:** that day's runs (not replays) that weren't a task's.
- **Tasks:** that day's runs that were a task's, by the rule that sorts runs into origins (`server/api/runs.py:111`).
- **Approvals asked:** that day's `approval_events` that a person had in front of them (`decided_by` `user` or
  `expired`).

One known difference: today's item counts persisted rows, while `activity` counts running jobs and island events
from memory. So right after a restart, today's two numbers can differ. `activity` is left as it is.

### `outcomes`: today's and this week's task results

| Field | Type | Unit, values | Req |
|---|---|---|---|
| `outcomes.today`, `outcomes.week` | object | today = since local midnight; week = the same 7 days as `week` | **req** (both) |
| `….tasks` | [object] | **finished** tasks only, newest first; capped at 50 per set, see **Decide 2** | **req** |
| `….tasks[].conversation_id` | string | | **req** |
| `….tasks[].title` | string | the task's goal, one line, at most 80 characters | **req** |
| `….tasks[].state` | string | `done` / `unfinished` / `failed` | **req** |
| `….tasks[].checks_passed` | int | checks passed, `not_applicable` counted as passed | **req** |
| `….tasks[].checks_total` | int | the task's own checks, without the built-in "answer delivered" | **req** |
| `….tasks[].spent_usd` | double | US dollars at list price; left out when nothing in it could be priced | opt |
| `….tasks[].needed_you` | bool | the task put at least one card in front of you (`approval_events`, same rule as the week) | **req** |
| `….spent_usd` | double | everything spent in the range that could be priced | **req** |
| `….other_spent_usd` | double | `spent_usd` minus the listed tasks' `spent_usd`, never below 0 | **req** |
| `….spent_partial` | bool | *phone ignores*: some use in the range had no price, so `spent_usd` is low | opt |

How it is made:
- **States:** `state` maps the job's outcome as the conversation list already does
  (`server/services/phone_reads.py`, in `describe`):
  - `done` stays `done`;
  - `partial`, `blocked`, `out_of_budget` and `interrupted` become `unfinished`;
  - `stopped` becomes `failed`.
- **Done:** "done" is the verifier's, including its last "was the goal reached" check
  (`background_jobs.py:250`). The phone never recounts checks.
- **Running tasks** are left out. This answers ①iOS's question (b).
- **Cost:**
  - Uses the same items and prices as the Progress page (`fetch_usage_items`, `item_usd`).
  - A task's cost is the sum over its run, which needs a run filter added to `fetch_usage_items`.
  - Nothing new is stored, so no migration.

**Decide 2: the task cap.** **Decided: as recommended (50).**
- The whole snapshot is written to iCloud on every 60 s heartbeat.
- Uncapped, a busy week of tasks would be resent every minute. 50 tasks of about 200 bytes each is about 10 KB per
  set at worst; a usual week is a few hundred bytes.
- **Recommended:** 50 per set, newest first. Past that, the phone's 7-day counts undercount. The cap is a named
  constant pinned by a vector, so a later counts field can replace it cleanly (①iOS).
- The alternative is to add `done`, `unfinished`, `failed` and `on_its_own` counts beside the list. That's
  correct at any size, but ①iOS would have to read them, which means a phone change, so I don't recommend it for
  1.0.

## 3. `chat.history.result.details`: one conversation as the Mac runs it

**Who builds it:**
- The backend's history endpoint (`/api/v1/phone/conversations/{id}/history`) builds it.
- The history trim (`phone_reads.fit_history`, 560 KB) counts `details` first and fits messages into what is left.
- The Bridge's last-resort trim (`ConversationLinks.swift:363-370`) drops messages only, never `details`.
- `details` is about 1–3 KB.

**When it's sent:** on each history result, which the phone asks for when a conversation opens and after each
turn. A result without `details` makes the phone keep its last value.

| Field | Type | Unit, values | Req |
|---|---|---|---|
| `details` | object | | opt (block) |
| `details.folder` | string | display only: the conversation's folder (its project's, else the workspace), the home part shown as `~` | opt |
| `details.model` | string | the model's display name the conversation runs on | opt |
| `details.mode` | string | *phone ignores*: the approval mode's name in effect | opt |
| `details.connectors` | [object] | **req, `[]` when none** (the phone's decoder requires it) | **req** |
| `details.connectors[].name` | string | the connector's display name | **req** |
| `details.connectors[].kind` | string | `mcp` / `skill` / `hands` | **req** |
| `details.connectors[].on` | bool | on for this conversation's turns: enabled and connected (MCP), equipped (skill), Hands on | **req** |
| `details.context` | object | see **Decide 3**: **not sent in 1.0** | opt |
| `details.context.used_tokens` | int | tokens in the last model call's prompt | **req** |
| `details.context.window_tokens` | int | that model's context window | **req** |
| `details.context.system_tokens`, `tools_tokens`, `chat_tokens` | int | *phone ignores*: the split of `used_tokens` | opt |
| `details.changes` | object | see **Decide 4** | opt |
| `details.changes.files` | int | distinct paths changed over the whole conversation | **req** |
| `details.changes.added`, `removed` | int | lines | **req** |
| `details.changes.last_run_id` | int | *phone ignores*: the newest run that changed a file | opt |
| `details.spent_usd` | double | US dollars, the conversation's total (`/conversations/{id}/usage` `usd_total`); left out when nothing could be priced | opt |

Connectors are capped at 30 entries: Hands first, then the ones that are on.

**Decide 3: context (the only item that needs new recording).** **Decided: the alternative, `context` is left out of 1.0.**
- The Mac doesn't keep the size of a turn's last prompt today. `runs.tokens_in` is the run's total over all its
  model calls, and is often empty for streamed turns.
- **Recommended:**
  - Record it at turn end: the last call's prompt tokens (the provider's count when it gives one, else our
    estimate), and the window (`context_window.window_for`, which history already uses).
  - Add the split into system, tools and chat as estimated shares.
  - That's one new nullable JSON column on `runs`, migration 0086, plus a few lines where the turn ends
    (`server/orchestrator`, a hot file).
- **The alternative** is to leave `context` out of IPB: the phone hides that one row, and nothing new is stored.
  ①iOS has no preference, and calls this a clean fallback for 1.0 if the hot-file change or 0086 puts v0.1.64 at risk.

**Decide 4: changed lines.** There are two honest sources, and neither is perfect. **Decided: (a), as recommended.**
- **(a) Recommended: the edit and write steps' recorded review**, summed over every run of the conversation.
  - Cheap, and kept as long as the runs are.
  - Doesn't count changes made by a shell command.
  - Undercounts a very large edit, since the review keeps a capped snippet (`tool_review.py:46`).
- **(b) The undo checkpoints:** the saved copy against the file now, per path.
  - Exact for the turns whose checkpoint is still kept, but only those.
  - Costs a diff per path on each history fetch, so it needs a cache.
- With (a), the protocol spec says that changes made by a shell command aren't counted (①iOS accepts the
  undercount on that condition).
- Either way, `files` counts distinct paths, and the Mac does the sum. The phone's own count would be capped by
  `run.result`'s 40 steps and history's 200 messages.

## 4. `hello`

- **No new capability flag.** The phone gates every part-B panel on whether the data is there
  (`Availability.partB(hasData:)`), and ignores flags for these.
- A flag would be one more thing for the Mac to keep in step and the phone to ignore. The shared vectors pin the
  shapes instead.
- `hello.capabilities` stays as it is (`ConversationLinks.swift:557-558`).

## 5. Answers to ①iOS's two open points

- **(a) A first message with a file in a conversation the Mac hasn't made yet:** accepted as it is today.
  - The Bridge saves a phone's file by its file id, and doesn't read the offer's `conversation_id`
    (`ConversationLinks.receive`, `:248-273`).
  - The `chat.send` that carries `new_conversation_id` creates the conversation, and its held message waits for
    the files like any other.
  - No change.
- **(b) Running tasks in `outcomes`:** left out. Only finished ones are listed (§2).

## 6. Shared vectors (`spec/mobile-bridge/vectors`)

Each vector decodes with `SharedProtocolV1Tests` on the phone:
- a full snapshot with all three blocks;
- a snapshot with each block absent in turn;
- a snapshot where `mac` is missing `taken_at`, to show it drops alone and the rest decodes;
- a desktop Mac with no `battery`;
- `cpu.last_hour` with fewer than 12 items, and with `[]`;
- an unknown `memory.pressure` value: the phone shows the raw word and keeps the block;
- a `network` of each quality;
- `outcomes` with a task that has no `spent_usd`, and a set at the task cap;
- a history result with full `details`, one without it, and one with `connectors: []`.

## 7. Privacy

- **Never leaves the Mac:** the Wi-Fi name, the BSSID or any IP address. A test checks the snapshot body for all
  three.
- **Does go to the phone:**
  - the Mac's state;
  - the conversation's folder, shown with `~`;
  - its connectors' names.
  All of it travels the way every frame does: end-to-end sealed, through the user's own iCloud private database.
- **The folder never carries the absolute home path** (⓪Plan's review of #640). A test checks that `details.folder`
  has no absolute home prefix. It compares resolved paths (`realpath` of both the folder and the home), so a home
  reached through a symlink, or written with different case on a case-insensitive volume, still comes out as `~`.
- **A connector's `name` is its display name only:** never its URL, command or arguments, which can hold a credential
  (SEC1, #628). A test registers an MCP server whose URL carries `?token=…` and one whose command has a
  `--token=…` argument, and checks that neither value appears anywhere in `details`.
- **The privacy page:** `aralem.dev/arslan/privacy` gets one line about the Mac's state reaching the iPhone. It
  goes live with, or before, the first Mac version that sends `mac`, because existing phones show the data with no
  update.

## 8. Build order after the OK

1. **Server:**
   - `week` and `outcomes` on `/phone/status`;
   - `details` on history.
   - With Decide 3's recommendation: migration 0086 and the turn-end recording.
2. **Bridge:**
   - the `mac` sampler and the snapshot merge;
   - the history trim keeping `details`;
   - the vectors and the protocol spec's tables (`docs/specs/mobile-bridge-protocol.md`: `status.snapshot` and
     `chat.history.result`).
3. **Stats,** split out of 1 if it grows past about 800 lines.

**Reviews:**
- ①iOS reviews each Bridge PR's frames against the vectors.
- What leaves the Mac gets the effort=max security review.
