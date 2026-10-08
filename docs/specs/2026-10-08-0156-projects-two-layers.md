# 0.1.56 — Projects in two layers

Status: draft for review (2026-10-08). Boards: Projects-Board-v3, Project-Templates, Project-New,
Project-LevelMap, Project-Habits, Project-Replan (canvas round 3, approved by the user 2026-10-08:
"都可以，按你建议的版本排，开工吧", shadow threshold 10).

## 0. What is there today (measured)

- `projects` (`server/db/companion_models.py:43-60`): name, kind (general/software/research/design,
  API-only check `server/api/companion.py:54`), summary, workspace_ref, collection_ids, app_binding,
  status `CHECK IN ('active','archived')`, version. No migration ever changed it.
- Routes: list / create / edit (`companion.py:109-140`). No get-by-id, no delete, no service layer.
- **Every edit bumps `version`, and running or queued tasks pinned to the old version fail with
  `task_project_changed`** (`server/services/task_repository.py:169-189`); App Store grants fail with
  `grant_project_stale` (`server/services/action_permissions.py:86-88`). A board that moved cards by
  editing the project would break work in progress.
- **The project never reaches the model**: name, summary and kind are in no prompt. What a project
  does today: scopes memory (`personal_context.py:298-301`), limits material retrieval to its
  collections (`knowledge.py:226-241`), carries the ASC binding.
- `workspace_ref` is stored and edited but nothing reads it.
- The page (`web/src/components/companion/ProjectsSection.tsx`) is a grid of cards with Edit / Archive /
  Start; no progress, no conversations, no last activity, no testids. The editor's limits differ from
  the API (name 160 vs 200, summary 4000 vs 10000); the editor never sets `app_binding.connection_id`,
  so the ASC grant check (`action_permissions.py:91`) can never match.
- No stage / level / milestone concept anywhere. `update_plan` (`server/orchestrator/turn_plan.py`) is
  a per-run checklist in memory only. Judgments (`server/services/judgment.py`) record a verdict and
  the user's outcome but no agreement rate is computed in the app (only `scripts/judgment_replay.py`).
- Lessons have no project link and a CHECK on `source` (a new source = table rebuild).

## 1. The two layers

**Board (layer 1).** Four columns for every project, like Jira / Linear status categories:
**Idea** (not started) · **Shaping** (finding out what and how) · **Doing** (clearing levels) · **Done**.
Plus **Dropped** (folded away) and a **Paused** flag (shown as a count, "暂停 1 · 归档 2"). Archive stays
as it is (orthogonal). A card shows the name, its type, "做完 = <finish line>", a segmented bar of its
levels, "第 N 关 · <level>", "还差 N 关", and time in the level ("这一关第 4 天 · 你一般 9 天").
A list view shows the same rows in a table.

**The column is derived, never dragged.** Idea = no level started. Otherwise the column is the band of
the current level (each level belongs to Shaping, Doing or Done). Done and Dropped are set only by the
user. There is no drag and drop: the agent's job is to say "this can move", the user's to agree.

**Project page (layer 2).** Tabs **Levels · Conversations N · Files · Materials · Settings**.
- Levels: the level map (done ✓ / current / to do / finish flag, bands drawn as Shaping / Doing / Done),
  the current level's checkpoints with their evidence and its clear condition, "现在最该做" (the first
  open checkpoint) with "交给 Arslan 起头", "Arslan 最近做的" with Undo on each, "还差 N 关 · 约 N 周"
  (weeks only when there is pace history, §6), and a line on how often the plan changed.
- Conversations: every conversation with this `project_id`, newest first, and "在项目里新对话".
- Files: the project folder's top level (the folder is `workspace_ref`, now read; see §8).
- Materials: its collections (as the editor sets them today).
- Settings: today's editor fields, plus type, finish line and folder.

## 2. Levels per type (templates)

Data, not code paths: `server/services/project_templates.py`, ten types, each level with a band. The
`*` level is a habit level (added from the user's habits, §6), not part of the template.

| Type | Shaping | Doing | Done |
|---|---|---|---|
| Game | Idea · Prototype (find the fun) | Vertical slice · Production · Beta · Store prep | Launch |
| App / software | Problem and users · Prototype | Core features · Polish and test · Store prep | Launch |
| Website | Goal and readers · Structure and wireframe | Visual design · Build · Content · Pre-launch check | Launch |
| Research / paper | Question · Literature · Method | Data · Analysis · Writing · Revision | Submit / publish |
| Writing | Topic and readers · Outline | First draft · Revision · Check sources | Final |
| Video / content | Topic · Script | Shoot / material · Edit · Subtitles and voice | Publish |
| Learn a skill | Goal and method · Baseline | Foundations · Practice · Real use | Test |
| Trip | Destination and dates · Budget | Book · Itinerary · Prepare | Leave |
| Job search | Direction · CV and portfolio | Apply · Interview | Offer |
| Other (fallback) | Think it through · Try a version | Make it · Polish | Hand it over |

Each level has a one-line description and a **clear condition** in words, and 0–7 **checkpoints**.
The existing `kind` column is kept for compatibility (software ⇢ App/software, research ⇢ Research,
design ⇢ Website, general ⇢ Other).

## 3. New project

Board "新项目" → (1) type, (2) "做完是什么" in one sentence, (3) folder (optional, default
`~/Arslan/<name>`), (4) the drafted levels, editable (rename, reorder, delete, add; band per level),
then **开始**. Drafting:

1. Deterministic first: the template for the type, the finish line put into the last level's clear
   condition. This works without any model and is what a user with no model gets.
2. Then one model call (role "draft", the `update_drafter` pattern, stubbable adapter, nothing applied
   until the user presses 开始) adapts the levels' clear conditions and checkpoints to the finish line,
   and adds habit levels (§6). Cost: one call per new project, on the user's own model; shown as
   "Arslan 起草中…". If the call fails or there is no model, the deterministic draft stays.

**Existing projects** (created before 0.1.56) show in Idea with "给它排关卡", which opens the same
step 4 for them. Nothing is drafted for them automatically.

## 4. How a level moves: evidence, ticks, proposals

Evidence is only what can be seen, and every tick or proposal names it. Four kinds:

| Kind | Example | 0.1.56 |
|---|---|---|
| You said | "效果稿可以", "这关算过了" | yes: a judgment point after a turn in a project conversation (§4.3) |
| Project files | `levels/level-01.json`, store screenshots | yes: a checkpoint may carry an expected path pattern, checked in the folder |
| A run's result | a background job finished done, tests pass | yes: jobs started from a checkpoint ("交给 Arslan 起头") report back to it |
| Outside state | App Store review passed, paper submitted | **not in 0.1.56** (needs connectors; 0.1.57+) |

### 4.1 Rules (from the board)
- **Small ticks are automatic**: a checkpoint is ticked when its evidence appears, logged with the
  evidence, undoable from "Arslan 最近做的" and from the checkpoint.
- **Clearing a level asks first.** When every checkpoint of the current level is ticked, or the
  user's words meet the clear condition, Arslan proposes "第 N 关的通关条件满足了：<evidence>。进第
  N+1 关…" with **挪过去 / 还不**, on the card on the board and on the project page. If the next
  level is in another band, the same proposal says the card moves column.
- **Done and Dropped are only the user's.** Arslan may say "最后一关的条件满足了" but never sets Done.
- Proposals are never notifications and never Inbox items: they wait on the card.

### 4.2 Files
A checkpoint may have `expects: {kind: "file", pattern, min}` (glob relative to the folder). The
folder is scanned (bounded: depth 4, 5 000 entries, no symlinks out of the folder, secrets-named files
ignored as `workspace_paths.is_secret_name` already does) after every turn in a project conversation
and on the existing proactive scan loop (600 s). A match ticks the checkpoint with the file as evidence.

### 4.3 You said
A new judgment point `project.progress` (active, threshold 0.8, after-turn timing like `memory.*`):
state = the current level's name and clear condition, its open checkpoints, the user's last message.
Question: which open checkpoints did the user say are done, and is the level's condition met? A yes on
a checkpoint ticks it (evidence: a quote ≤ 120 characters and a link to the message); a yes on the
condition makes a proposal. Runs only in conversations with a project, under the judgment daily token
cap that already exists. With no router/model configured it is simply absent.

### 4.4 Runs
"交给 Arslan 起头" starts a conversation in the project with the checkpoint as the request; when that
conversation starts a background job, the job carries `project_checkpoint_id`. A job that ends `done`
ticks the checkpoint with the job as evidence; `partial` / `blocked` do not tick.

## 5. Shadow mode: when may Arslan move things itself

Every level-clear proposal is recorded with its outcome (accepted / declined / undone later). The board
footer and the habits sheet show: "提议挪过 7 次，你接受了 6 次，眼下连续猜对 4 次". A decline asks
for nothing but offers one optional line ("还想再试一版") that becomes a habit candidate (§6).

**At 10 accepted in a row** (an undo after acceptance counts as a miss and resets the streak), Arslan
asks once, on the board: "以后让我自己挪吗？挪了都写依据，随时能撤回" — 好 / 先不. Only on 好 does
the setting `projects_auto_advance` turn on (default off; also in Settings › Background). With it on,
level clears that would have been proposed are applied, logged with evidence, and undoable; Done and
Dropped still never are. The streak keeps being measured with it on (an undo is a miss). Arslan does
not turn the setting off by itself; after 2 undos in a row it says so on the board and offers to.

## 6. What Arslan learns about how the user advances (habits)

Sheet "看它学到了什么" (from the board footer):
- **The meter**: the shadow numbers above, and the last miss with what was learned from it.
- **Plan rules** ("起草计划时会用上"), each with a switch and its source: e.g. "游戏和 App：先认可效果稿，
  再动手做 (Sluice、百面、MathVoid)". Written by Arslan when (a) the user adds the same kind of level to two
  projects of one type, (b) a re-plan removes features mid-way twice, (c) a decline's optional line.
  Active at once (Arslan's own notes rule, `decide_write`), visible, switchable; off = not used.
  Used only when drafting levels (§3) and re-plans (§7).
- **Pace** ("你的节奏"): median days per level by type and band, computed from cleared levels, never
  stored as text; editable as an override. Weeks are shown only with ≥ 3 cleared levels of history.

Stored locally in a new table (lessons cannot take a new source without a rebuild, §0). Never sent to a
cloud model except as part of a drafting request the user started.

## 7. When the direction changes (re-plan)

A tool `propose_plan_change` (offered only in a project conversation): Arslan proposes a diff of the
levels and checkpoints that are not cleared yet — ＋ added, － removed, ＝ cleared levels untouched,
and the new estimate. Shown as an AskCard ("计划要不要跟着改？", 保留原计划 esc / 用新计划 ⌘⏎).
Applied only on confirm, logged as a plan change, counted on the project page. Cleared levels can never
be changed by a proposal.

## 8. The project reaches the model

In a conversation with a project, the system context gets a short project card: name, type, finish
line, current level and its clear condition, open checkpoints, folder. ≤ 600 characters, reference data
not instructions, same position as the memory block. This is what makes "交给 Arslan 起头" and §4.3 make
sense, and what was missing (§0).

The folder (`workspace_ref`) becomes real: the project's Files tab, the checkpoint file checks, and the
default working folder for file tools in that project's conversations (inside the existing read/write
rules; a folder outside the green ring is read-only unless it is the workspace).

## 9. Stalled projects

Marked quietly on the card, never notified: "第 5 关停了 23 天（你一般 9 天），还差 3 关。不催你，只是让
你知道。" with 接着做 / 暂停 / 改计划. Shown when there has been no activity (turn in a project
conversation, tick, file change in the folder) for more than 21 days, or more than twice the user's
usual for that level when pace is known. 接着做 opens a conversation in the project at "现在最该做".

## 10. Done: a short retro

When the user marks Done, Arslan writes a retro (one model call): what took longer than usual, what
changed in the plan, and up to three plan rules; each rule can be kept as a habit (§6). Skippable.

## 11. Data (migration 0063; `projects.version` untouched by any of this)

- `projects` + nullable columns: `template`, `finish_line`, `stage` (`idea|active|done|dropped`,
  default `idea`), `paused` (bool), `done_at`. No CHECK change, no rebuild.
- `project_levels` (id, project_id, position, name, description, band `shaping|doing|done`, clear_condition,
  state `todo|current|cleared`, habit (bool), started_at, cleared_at, version).
- `project_checkpoints` (id, level_id, position, text, expects JSON, state `todo|done`, progress text,
  evidence JSON, done_at, done_by `user|arslan`).
- `project_events` (id, project_id, kind `tick|untick|proposal|advance|plan_change|stage|auto_ask`, payload
  JSON incl. evidence, actor `user|arslan`, outcome `accepted|declined|undone|null`, undo_of, created_at).
- `project_habits` (id, template, text, kind `plan_rule|pace_override`, sources JSON, enabled, created_at).
- `background_jobs`/task: `project_checkpoint_id` carried in the job (in memory) and on its task row.

API (all authed): `GET /projects/board`, `GET /projects/{id}`, `GET/PUT /projects/{id}/plan`
(levels + checkpoints, its own version), `POST /projects/{id}/checkpoints/{cid}/tick|untick`,
`POST /projects/{id}/proposals/{eid}/accept|decline`, `POST /projects/{id}/events/{eid}/undo`,
`PUT /projects/{id}/stage` (done/dropped/idea, paused), `GET /projects/{id}/conversations`,
`GET /projects/{id}/files`, `GET/PUT /project-habits`, `POST /projects/draft` (type + finish line → levels).

## 12. Small fixes on the way

- Editor limits match the API (name 200, summary 10000).
- `JudgmentsCard` labels for `memory.conflict`, `job.accomplished` (and the new `project.progress`).
- ProjectsSection gets testids.
- (Not fixed, stated) the ASC `connection_id` gap stays as it is: it belongs to the App Store flow.

## 13. Not in this release

Outside-state evidence (store review, submissions); "capabilities later levels will need" (0.1.57,
with the discover loop); drag and drop; notifications or Inbox items for stalls or proposals;
sharing projects.

## 14. Phases (one PR, these commits)

- P1 data + templates + API (no model): migration, plan CRUD with its own version, board derivation,
  events + undo, folder listing, conversations by project. Tests: derivation table, undo, version
  isolation (a plan write leaves `projects.version` and a running task untouched).
- P2 UI: board (columns, list view, counts), new project (deterministic draft), project page (tabs, level
  map, checkpoints, recent with Undo), existing projects → "给它排关卡".
- P3 Model drafting (§3.2) and re-plan tool + card (§7); project card in context (§8).
- P4 Evidence: files (§4.2), runs (§4.4), you-said judgment (§4.3); proposals on card and page.
- P5 Shadow numbers, the ask at 10, `projects_auto_advance`; habits sheet; stalled marking.
- P6 Retro at Done.

## 15. Acceptance

- A plan, tick, proposal or stage change never changes `projects.version` (test with a running task).
- The column shown is a pure function of stage + current level band (table test over every case).
- Every automatic tick and every proposal carries evidence; every automatic change is undoable.
- No proposal, tick or stall produces a notification or an Inbox item.
- Auto-advance never happens before the user said 好 to the ask; never sets Done or Dropped.
- With no model configured: create, draft (template), tick by hand, clear by hand, board — all work.
- Real Mac: create a game project with a folder, see a file tick a checkpoint, accept a proposal, undo
  it, see the card move columns.

## 16. Model cost (user's own model)

One call per new project draft, one per re-plan, one per retro; the `project.progress` judgment per turn
in a project conversation, on the router model under the existing judgment daily cap.

## 17. As built: where the implementation differs (flagged for review, not waiting)

1. **§3.2 model draft is on a button** ("让 Arslan 细化"), not automatic after the template draft:
   a paid call only when asked. Failure keeps the draft (`refine_failed`).
2. **§7 a changed plan is a non-blocking card** answered through the projects API
   (`/plan-proposals/{id}/accept|decline`), not an entry in the approvals registry: the turn goes on;
   a newer proposal makes the older one stale.
3. **§4.3 two decision points, not one**: the judge answers yes/no only, so `project.progress` is a
   gate asked once per user turn ("does this message say any of it is done?"), and only on its yes
   `project.progress.item` is asked per open checkpoint (≤ 5) and for the condition. Cost: 1 call on
   most turns, up to 7 on a "done" message, all under the existing judgment daily cap. Background-job
   turns are not asked (a job's goal is not the user speaking).
4. **§4.4 the link is conversation ↔ checkpoint** (`POST /projects/{id}/handoff`, event `handoff`),
   not a `project_checkpoint_id` on the job: any background job in that conversation that ends `done`
   ticks it.
5. **§4.2 files tick only the current level's checkpoints**; a later level's files are not evidence
   until that level is current. File changes also count as activity (§9) and start a planned Idea.
6. **§6 (a)** counts a level as "added" only in a plan built on the type's template (≥ 2 template
   levels kept) and never a level a rule put there; the rule is named as first written.
   **§6 (b)** "twice" = in two different projects of the type.
7. **§6 rules are not given to re-plans (§7)** — only to drafting (§3). The project card goes to the
   model on every turn in the conversation, and §6 says rules leave the Mac only inside a drafting
   request the user started. Re-plans therefore do not use rules yet.
8. **§9 "twice the usual" has a floor of 3 days**, so a fast usual never marks a short gap.
9. **§5 the ask's answer is a setting** (`projects_auto_asked`), not an `auto_ask` event (events
   belong to one project; the ask is global). Undoing twice in a row offers to turn it off; 留着
   holds until a new miss. The decline's optional line can also be added right after declining
   (board footer, `/proposal-notes/{id}`).
10. **§10 the retro is offered at Done and written on request** (one call), not automatically;
    skippable; without a model it is the counted facts alone. Asking again replaces it.
