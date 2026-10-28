# SUB 总指挥 + 子会话的底子（一个子 agent 工具做成子会话）

> ⓪Plan 2026-10-29 夜间起草，用户 10-28 已定分级。v0.1.64 计划（#434）由用户点合并后才开工。

| 项 | 内容 |
|---|---|
| 道 | ②Main（⓪Plan 的建议） |
| 版本 | v0.1.64 |
| 分级 | 必须（用户 10-27 放进 v0.1.64，10-28 确认；只等 SBX） |
| 依赖 | S64-0（补洞的安全 PR，在 SUB 之外：`delegate_work` 的标记、`track_turn` 的起始值等）；SBX（沙箱默认拒绝，用户定的顺序：本卡排在它后面）；M64 的「拆开、分给子会话、汇总」题和反面题；Q1 的迁移（`kind` 列 + 父对话 id，两张卡共用，Q1 先申请）；手机上显示子会话要改 Bridge 帧，要用户点头 |
| 合并位置 | SUB2 在 Q1 的迁移合了以后。SUB3–SUB5 叠着做，M64 的题在叠起来的最上面跑过了才一起合，而且要在 S64-0 之后。SUB6 删代码，SUB7 删表，最后。改到 `tool_loop.py`、`arslan.py` 的，排在当时打开的 K 线 PR 后面 |
| 推动的门槛 | 领先路线 C 行「子 agent」落后 → 追平（`docs/plans/2026-10-17-0162-lead-roadmap.md:243`）；R64 的跑分（拆分派汇总题出数） |
| 分支 | `claude/0164-sub2-sub-data`、`claude/0164-sub3-runner`、`claude/0164-sub4-report`、`claude/0164-sub5-lifecycle`、`claude/0164-sub6-delete-delegate`、`claude/0164-sub7-drop-task-workers` |
| 迁移号 | SUB2 不另要（用 Q1 那一次）。SUB7 删 `task_workers` 表要一个迁移：⓪Plan 建议并进 C7c 那一次迁移，C7c 已经合了就向 ②Main 申请下一个空号 |

## 目标

- 用户 10-27 定的分两步（`docs/plans/0162/README.md` §8「项目里的『总指挥 + 子会话』」）。本卡只做第一步，v0.1.64 的**底子**：
  - 一个主会话（总指挥）开出几个子会话分工干活，子会话在后台跑，做完向总指挥汇报；
  - 每个子会话都是一段真对话，能点开、能直接跟它说话；
  - 最多三层：总指挥 → 子会话 → sub-agent。最下层拿不到这个工具，执行时也拒；
  - 领先路线里「子 agent 统一成一个工具」就是它，不另做一套。
- **先证明模型会用：** M64 的「拆开、分给子会话、汇总」题和反面题（一步就能做完的不开子会话）过了，工具才合。
- **先补洞：** `delegate_work` 今天不传「读过外部内容」的标记。这个修复放进单独的安全 PR S64-0（⓪Plan 的提议，在 SUB 之外），SUB 不再自己修，只引用它，并加一个「往下传标记」的测试（见 SUB1）。
- **本卡不做：** 项目页的总指挥 / 子会话树、子会话对上关卡检查点、关卡条跟着动，都是 v0.1.65（README §8 同一条）。旁聊用同一套底子（`kind`、父对话 id、只继承的设置），但旁聊本身另开卡，而且用户还没确认它进 v0.1.64。 (Update 2026-10-28: the user put side chat into v0.1.64 as card SIDE, `docs/plans/0164/SIDE-side-chat.md`, built on this card's base.)
- **同一版里替换（sessions §11 第 1 条）：** 新工具上线的同一版删掉 `delegate_work` 和 `TaskWorker`（SUB6 删代码，SUB7 删表）。

### main 现状（⓪Plan 读 main `8db45ef9` 核过）

- **`delegate_work`：**
  - 一次最多 4 个帮手（`server/services/task_workers.py:45`），同时最多跑 2 个（`task_service.py:622` 的 `Semaphore(2)`，`task_workers.py:111`）；
  - 只能用 `web_search`、`web_extract`（`:27`、`:34`）；
  - 只在有 Task 的回合里能用：`:213-215` 在没有 Task、已经在帮手里、或在专家里时报 `worker_host_only`；工具也只在这时提供（`server/orchestrator/arslan.py:1118-1123`）。C3b 已经把它降成按需发（`arslan.py:1034`）；
  - 预算：`WorkerBrief` 带一个 `shared_budget_id=budget.id`（`task_workers.py:242`），但这只是个没人读的标签（`arslan/companion/contracts.py:203`）。帮手共用预算，是因为它们跑在父回合里，经 ContextVar 看到同一个内存里的 `Budget`（`arslan/execution_budget.py:283`）。每次运行的默认上限是 $2（`execution_budget.py:66`）。
- **标记的洞（S64-0 要证实并修的）：**
  - `delegate` 返回 `"external": False`（`task_workers.py:268`），所以 `tool_loop.py:373-374` 把帮手从网页得来的文字原样交给父回合，**完全不加框**（连普通工具输出的框都没有）；
  - `counts_as_external` 没列它（`server/orchestrator/untrusted.py:72-73` 的名单、`:79-84` 的判断；README 写的是 `:72-79`，行号有一点漂移，内容一致）；
  - 每次 `run_native` 都调 `track_turn()`（`tool_loop.py:2812`），它总是放一个新的 `{"seen": False}`（`untrusted.py:92-93`）。帮手读网页只标它自己的；结果里的 `external_seen`（`tool_loop.py:2819`）`task_workers` 没读。父回合的标记一直是干净的，S2a-1 的断网卡（`tool_loop.py:1261`、`:1300`）和笔记的自动启用（`memory_tools_v2.py:137`）都不会触发；
  - 这些是读代码得出的，**没跑过**。
- **后台任务（子会话打算借用的运行器）：**
  - 全局最多同时跑 3 个（`background_jobs.py:27`）；每个任务在一个全新的 Context 里跑（`:162`），拿自己的预算（`:294-336` 的 `run_budget(tier, usd_cap)`）；
  - 任务的上下文去掉了「用户明确要求存」的授权（`background_jobs.py:305-306`：`explicit_save_digest`、`explicit_save_ref`、`allow_global_save`）；
  - 确认卡走 `JobConfirmations`，广播给这段对话的所有连接，授权也按这段对话算（`approvals.py:409-417`）；
  - 结果推回：任务的最后一段话直接存成这段对话里的一条 Arslan 消息（`background_jobs.py:362-372`），不加框、不带标记；
  - 任务以 `done` 结束时，`job_finished` 给交到这段对话的检查点打勾（`background_jobs.py:266` → `project_evidence.py:268-296`）。
- **浏览器只有一个：** 所有 `browser_*` 工具走同一个模块级的 worker、同一个 profile（`server/services/agent_browser.py:131` 的 `_worker = _Worker()`）。`browser_reader` 的会话只从 `POST /browser/sessions` 来（`server/api/browser.py:136-140`），最多 4 个（`browser_reader.py:204`），工具调用不会开它。
- **对话设置：** `ConversationContext` 有 `project_id`、`no_memory`、`no_learning`、`temporary`、`cloud_memory_allowed`、`allow_sensitive`（`server/db/companion_models.py:16-29`）；没有 `kind`，没有父对话 id。权限模式今天是一个全局设置（`permissions.py:575` 的 `_mode()` 读 `shell_confirm_policy`），不是按对话的。
- **手机上列出的对话：** `/phone/live` 除了 `list_conversations` 的最新几条，还把每个正在跑的后台任务的对话加进去（`server/api/phone.py:295-300`）；`describe` 把有任务的对话标成 `task`（`server/services/phone_reads.py:265`）。
- **学习和项目证据：**
  - 只有「Arslan 自己的回合」才学（`tool_loop.py:2857`）；帮手的 `actor="worker"` 不学（`task_workers.py:152`）。`lessons.after_turn` 遇到 `no_learning` 不学（`lessons.py:405`）；
  - 项目证据：后台任务的回合 `said=False`（`task_service.py:1036-1041`，按 `inside_job()` 判断），聊天回合 `said=True`（`project_evidence.py:300`）。
- **重启：** 开机时还在跑的帮手一律改成 `interrupted`（`task_repository.py:500-501`）；后台任务不跨重启（`background_jobs.py` 的 `report_interrupted`）。
- **花费的记录：**
  - 带 Task 的运行（后台任务都是）在每个工具前后各存一次预算快照，含花费（`task_service.py:666`、`:710`、`:760` → `task_repository.py:279-283`），树的上限可以读它；
  - `runs.execution_budget` 只在运行结束时写（`run_recorder.py:383-387`）。不带 Task 的运行，被重启打断时花的钱不在库里；有没有这种运行会进子会话的树，开工时 ②Main 核。

### README 和代码对不上的地方（⓪Plan 核，②Main 审 #434 时更正过两条）

1. **第 3 条「第二个动作回 409」：** `companion.py:256` 的 409 `conversation_running` 是**改对话设置**（`PUT /conversations/{id}/context`）时回的。聊天里第二条消息不回 409：它排队（`server/ws/arslan.py:225-241`），或者在下一个工具边界插进正在跑的回合（K9b，`:294-301`）。另外，后台任务的回合不拿这把锁，它和同一段对话里的聊天回合是并行的（0.1.42「边聊边干」）。所以「一段对话同时只跑一个回合」今天只对聊天成立。
2. **第 6 条「`parallel_reads.py:30-31` 已经让浏览器、桌面串行」：** 那两行是注释，意思是 `browser_*`、`desktop_*` 不进「可以并行的读」（`READS`，`:32-34`），只管**一个回合里**的一批调用。两个子会话是两个回合，这里管不到。但浏览器本身只有一个（`agent_browser.py:131`），两个子会话都用 `browser_open`、`browser_look` 时，会在同一个浏览器上排队、互相换页面。
3. **README 没提的方向：标记往下也会丢。** 原因是每次 `run_native` 都用 `track_turn()` 从 `{"seen": False}` 开始（`untrusted.py:92-93`），不在 Context 上：就算把总指挥的 Context 传下去，子会话的回合照样从「干净」开始。要给 `track_turn` 一个起始值（S64-0 加），SUB3、SUB4 用它。
4. **「像后台任务推回结果那样」不能照抄：** 后台任务的结果是不加框的 Arslan 消息（`background_jobs.py:362-372`）。子会话的汇报照这样推回，就和 `delegate_work` 是同一个洞。

## Projects: what the user agreed on 2026-10-28 (relayed by ④参谋)

Added after this card was drafted. The sub-session base in this card (v0.1.64) is what these build on; the project page, checklist and progress board are v0.1.65. ④参谋's basis: a read-only look at the user's database (counts only), main `502012f5`, and first-hand docs of Claude Projects (2026-09 redesign), Claude Code sub-agents and agent teams, ChatGPT Projects, Codex goals and sub-agents, vibe-kanban, cline/kanban, Nimbalyst and Manus Projects.

- **Why change:** the project feature is detailed but asks the user to manage it. On the user's machine there is one project; every gate was pushed through in ten seconds (trying the feature); all 35 checkpoints are still `todo`; 5 of 342 tasks belong to a project; `project_habits` has 0 rows. This is the opposite of "talk only to the coordinator".
- **The seven points:**
  1. **One project = one goal + one coordinator.** The user talks only to the coordinator. At the start, the coordinator and the user write "what done looks like" as a checklist; sub-sessions start in order (for a video: outline first, then cover and edit in parallel).
  2. **A checklist item is ticked only when** the coordinator has accepted the sub-session's report **and** its acceptance sheet and evidence are complete (Inbox item 8's three-column sheet). A sub-session saying "done" does not tick anything. Progress = ticked items / all items. No mainstream product ties checkpoints to a progress bar, so a tick always needs the coordinator or the user.
  3. **Shared inside a project:** project rules (that folder's rules, L11); project memory (by default it can use "about you"; things about the project are stored only in the project; one project can switch this off and be fully isolated); a library (the project folder, inputs and outputs); one spending cap (today's `shared_budget_id` is a shared budget id, not a cap: the cap has to be built); permissions only inherited, never widened.
  4. **Reporting default:** come to the user only when a decision is needed, plus one line per finished item. Changeable per project.
  5. **Delete:** the four-column board, per-type template gates, "learn how you advance gates" (shadow / auto, `project_habits`), rhythm stats, stall reminders. The retro becomes the coordinator's final report. Deleted under U2; each migration is its own PR.
  6. **The board becomes a read-only progress board.** One row per project: goal ("done = …"); a segmented bar, one segment per checklist item, four colours (done and accepted / in progress / waiting for you / not started), hover shows the item; one plain line "who is doing what now"; a status tag (needs you N / working / quiet N days), which is also the sort order (waiting first, finished at the bottom); a 7-day activity strip; spent / cap; last update. No columns, no dragging, no gamification. A row opens that project's coordinator conversation. Same data as the sidebar status dots and the progress page (the progress page is a timeline of all conversations; the board is one row per project).
  7. **Project page:** goal and checklist with the bar at the top; the tree of sub-sessions in the middle, one "doing what" line each, with a stop button; the progress timeline filtered to this project at the bottom.
- **Schedule (⓪Plan):**
  - **v0.1.64 (this card):** the sub-session base only. Nothing from the seven points is built here, but SUB2's data must not block them: the parent link and per-project settings (memory isolation, cap) need a place to live.
  - **v0.1.64, card PRJ0 (③Hands, U2, deletions only):** remove "learn how you advance gates" (shadow / auto, `server/services/project_habits.py` and its table), rhythm stats and stall reminders. Nothing replaces these and nobody uses them (`project_habits` has 0 rows), so §11 is satisfied by deleting. The table drop is its own PR.
  - **v0.1.65:** checklist and tick data, project page, progress-board data; in the same version delete the four-column board (`web/src/components/projects/ProjectsBoard.tsx`), the template gates (`server/services/project_templates.py`) and turn the retro (`project_retro.py`) into the coordinator's final report (§11 rule 1: replace means delete). `DELETE-BY: v0.1.65` on the board and gates.
  - **Look:** the interface version. **Before any UI code, a clickable demo for the user to approve** (user, 2026-10-28; also confirms README §2 item 7). ④参谋's sketch only sets the direction.

## 改哪些文件

按 PR 列。产品代码的行数是 ⓪Plan 的估计，不含测试和翻译。

### SUB1 `delegate_work` 的标记：在 S64-0 做，本卡只引用

> **S64-0 的实际做法（#438，③Hands 10-28）：** 「起始值」没有做成 `track_turn` 的参数，而是一个上下文 `untrusted.carried(seen)`（跑一次设一次），这样 `tool_loop.py`、`arslan.py` 都不用改。本卡凡写「`track_turn` 的起始值」，都指它：SUB3 往下传标记时写 `with untrusted.carried(True): …` 包住子会话的运行；汇总回合同理。

- **修复在 S64-0**（⓪Plan 提议的单独补洞 PR，安全，effort=max 写和审，Codex 审）。S64-0 一起管：`delegate_work`、后台任务从「干净」开始、教训的合并、恢复和 `task_progress`；它给 `track_turn` 加一个起始值。
- **S64-0 里关于 `delegate_work` 的要点**（②Main、③Hands 审 #434 时提的，记在这里方便对账）：
  - 两处都要改：不再返回 `"external": False`（`task_workers.py:268`），**并且** `delegate_work` 进 `_WEB_TOOLS`（`untrusted.py:52`）和 `_OUTSIDE_TOOLS`（`:72-73`）。只改一处，文字要么完全不加框，要么只按普通工具输出加框；
  - 副作用：之后几轮的历史里，`delegate_work` 会被记成「外部内容，只留来源」（`server/orchestrator/turn_tools.py:107`），这是对的；
  - 测试测后果，不只测标记：同一个回合里，`memory_note` 不自动生效；要联网的命令弹出断网卡。
- **本卡留下的：**
  - 一个「往下传」的测试（SUB3）：总指挥读过网页后开子会话，子会话的第一个回合同样测后果（`memory_note` 不自动生效、要联网的命令出卡）；
  - SUB6 删 `delegate_work` 时，S64-0 的测试不删，改成测子会话的汇报（见 SUB6）。
- 本卡不再有 SUB1 这个 PR。

### SUB2 子会话的数据：父对话、只继承的设置、列表里不出现

- **迁移：** 用 Q1 那一次（`conversation_contexts` 加 `kind` 和父对话 id）。`kind` 的取值 ⓪Plan 建议：`chat`（默认）、`quick`（Q1）、`sub`（本卡）、`side` (side chat: used from v0.1.64 by card SIDE, 2026-10-28)。Q1 的迁移如果没带父对话 id，SUB2 自己带一个迁移，向 ②Main 申请号。
- `server/services/sub_sessions.py`（新）：
  - `create_child(parent_id, title)`：建子对话的 `ConversationContext`。父对话是临时对话（`temporary`）时拒（`sub_session_from_temporary`）；
  - `effective_settings(conversation_id)`：**用的时候**沿父对话一路往上，每个设置取最严的值，不在创建时复制一次。总指挥后来收紧（例如开了 `no_memory`），子会话马上跟着。`no_learning` 对 `sub` 一律开（第 9 条）。读对话设置的地方（`task_context.load` 一带）对 `kind="sub"` 改用它；
  - 一张继承表：`ConversationContext` 的每一列写明怎么继承（取最严 / 跟父对话 / 子对话自己的，例如 `id`、`version`、时间戳）；
  - `depth(conversation_id)`：沿父对话往上数，最多数 3 步；
  - `children(parent_id)`、`tree(root_id)`：给后面几个 PR 用。
- `server/api/companion.py:250-300`（改对话设置）：子对话的设置不能比父对话链上最严的松，松了回 422 `sub_session_inherits`。
- **列表默认不列 `sub`：**
  - `server/api/conversations.py:33`（Mac 侧栏）、`server/api/projects.py:236`（项目的「对话」标签）、`server/api/phone.py:105`（Bridge 的 `conversations.result` 从这里取，见 `desktop/bridge/Sources/BridgeCore/ConversationLinks.swift:430`）；
  - `server/api/phone.py:288`（`/phone/live`）：除了 `list_conversations` 那一份，还要从「正在跑的后台任务」那一份里去掉子对话（`:295-300`），否则子会话一跑就出现在手机上；`phone_reads.py:265` 的 `describe` 也不能把它标成 `task` 列出来；
  - 和 Q1 用同一个过滤函数（Q1 卡定名字）。`phone.py`、`phone_reads.py` 是 Bridge 契约文件：这里只改列出哪些对话，不改帧格式，但合并前告诉 ①iOS。
- **守卫测试：** 列出 `ConversationContext` 的每一列，每一列都要在继承表里有一行；以后谁加了列没填表，测试变红。
- 量级：产品代码约 +250 行（迁移不算，若要自带约 +40）。

### SUB3 子会话工具和运行器（叠着做，跑分过了才合）

- `server/services/sub_sessions.py`：`start(parent_id, title, brief, tools)`：
  - 查层数和数量（第 10 条），建子对话（SUB2），把交代存成子对话的第一条消息；
  - 用后台任务的运行器在子对话里跑（`background_jobs.start`，加一个 `parent_id` 参数）；保留 `background_jobs.py:305-306` 去掉「明确要求存」授权的做法：交代里写「记住」不是用户说的话；
  - 确认卡发到**总指挥**那段对话的连接上（`JobConfirmations` 的 asker 换成父对话的），授权落在子对话上。所以卡上的按钮写「这个子会话里都允许」，不写「本对话都允许」；子会话不继承总指挥已有的「本对话都允许」（第 2 条）；
  - 往下传标记：总指挥这一回合 `external_seen()` 为 True 时，交代按外部内容加框，子会话的第一个回合用 S64-0 给 `track_turn` 加的起始值，一开始就带标记（上面「对不上」第 3 条）。
- `server/registry/task_tools.py`：新执行器，例如 `StartSubSessionExecutor`（工具名在本 PR 定，⓪Plan 建议 `start_sub_session`）。马上返回 `{ok, sub_session_id, status: "queued"}`，不等子会话做完。
- `server/orchestrator/arslan.py`（工具表，按需发那一组，`:1034` 一带）：总指挥和第一层子会话有这个工具；第二层没有。子会话是后台任务，所以要在后台任务的工具表（`_background_tools`，`arslan.py:721-728`）里也能拿到。
- `server/orchestrator/tool_loop.py`：工具的参数 schema（照 `:2042` 一带 `delegate_work` 的写法）。
- **工具收窄（第 6 条）：** 子会话只给文件、命令、`web_search`、`web_extract`、`update_plan` 这一组；不给任何 `browser_*`（浏览器只有一个，`agent_browser.py:131`），不给 Hands 和桌面。照后台任务的收窄写法（`arslan.py:721-728`）。
- **一棵树的花费上限：** 每次向模型发请求前查。已花的钱 = 树里每个带 Task 的运行最新的预算快照（`task_repository.py:279-283`，每个工具前后都存）加总，加上没有 Task 的已结束运行在 `runs.execution_budget` 里的花费。每次运行自己的 $2 上限照旧，两个都查，先到哪个停哪个。树的上限默认值用户定（见文末）。
- 量级：产品代码约 +450 行。

### SUB4 汇报和总指挥的汇总回合（叠着做）

- `server/services/sub_sessions.py`：
  - 子会话结束（`done` / `partial` / `blocked` / `stopped` / `out_of_budget`）时，记下它的结果、改过的文件，还有它所有回合里有没有读过外部内容（`run_native` 结果里的 `external_seen`，`tool_loop.py:2819`）；拿不到就当读过（照 `untrusted.py:106-108`「不知道就算是」）；
  - 总指挥的直接子会话**都**结束了（或者有一个停在「等你」），开**一个**总指挥的汇总回合。它是总指挥对话里的一个后台任务，所以 `said=False`（`task_service.py:1036-1041`）、卡照常出；
  - 汇报一律按外部内容加框；有任何一个子会话读过外部内容，汇总回合用 `track_turn` 的起始值一开始就带标记（第 1 条）。
- `server/services/background_jobs.py`：
  - `Job` 记 `parent_id` 和 `external_seen`；
  - 子会话的结果**不**用 `_report` 推回总指挥（它推的是不加框的 Arslan 消息，`:362-372`），只推到子会话自己的对话里。
- 汇总回合等总指挥空闲才开：`run_registry.active_for(总指挥)` 为空、ws 的回合锁也没被占着。用户正跟总指挥说话时，汇报先等着。
- 子会话的 `done` 不给检查点打勾：子对话从来不会有 `handoff` 事件，`job_finished`（`project_evidence.py:268-296`）对它本来就什么都不做。加一个测试钉住，因为 v0.1.65 要改成「总指挥收下汇报才打勾」。
- 量级：产品代码约 +300 行。

### SUB5 停止、删除、撤销、重启，直接对话，同一文件（叠着做）

- **重启矩阵**（第 4 条），写码前先写进 PR 描述，状态在发生时就记下：

  | 重启时的状态 | 开机后 |
  |---|---|
  | 子会话在跑 | 它的 Task 行照 `recover_interrupted` 改成 `process_interrupted`；子会话记 `interrupted` |
  | 子会话在等卡 | 卡作废；子会话记 `interrupted` |
  | 总指挥在等汇报 | 子会话都已结束（含 `interrupted`）时，在总指挥对话里写一行「N 个子会话因重启中断」；不自动开汇总回合，不自动重跑，等用户说继续 |
  | 汇总回合在跑 | 照普通后台任务：中断，不重跑 |

- **停止、删除、撤销**（第 5 条）：
  - 停总指挥（窗口的「停止」）：连同它正在跑的子会话一起停，照 H3 `carry_stop_to` 的做法（`hands_service.py:733`）；
  - 删总指挥：有子会话在跑时拒（409）；都停了，子会话跟着一起删（这一条用户定，见文末）；
  - 删一个总指挥还在等的子会话：它的汇报记成 `stopped`，其他子会话照常汇报；
  - 撤销开出子会话的那一轮（S3）：不删子会话的对话。它们写的文件按 S3 现有的跨运行撤销处理（README §8「撤销跨对话」那条，确认框会列出这些运行）。
- **直接对话**（第 3 条）：子会话在跑时用户在它的窗口里打字，消息排到这一轮后台回合结束再跑（和今天聊天里的排队一样，`ws/arslan.py:225-241`）。往后台回合里插话（K9b 那条路）不在本卡。
- **同一文件**（第 7 条）：每个子会话一个自己的文件夹（工作文件夹下的 `sub/<短名>/`）。它的命令和文件工具只能写这个文件夹，靠 SBX 给每次运行设可写的目录来管，不靠提示词；总指挥负责合并。SBX 不提供「每次运行一个可写目录」的话，退回到「同一时间只有一个子会话能写」，这时第一层同时最多跑一个能写的子会话。
- **Web 界面（最简）：**
  - 总指挥的对话里每个子会话一行：名字、状态、「打开」；
  - 子会话的对话顶上一行「这是〇〇的子会话，做完向它汇报」；
  - 卡上「这个子会话里都允许」的新文案；
  - 新文案 6 种语言同一个 PR 加（sessions §3）。外观等界面版统一。
- 量级：产品代码约 +350 行（服务端约 200、web 约 150）。

### SUB6 删掉 `delegate_work` 和帮手的代码（§11 第 1 条）

- 删：
  - 服务端：`server/services/task_workers.py` 整个文件；`server/registry/task_tools.py:21-33`（`DelegateWorkExecutor`）；`arslan.py:1118-1123`；`tool_loop.py` 里 `delegate_work` 的 schema（`:2042` 一带）和超时（`:1791`）；`server/registry/seed_catalog.py:26`；`server/services/task_service.py:42` 里的名字；`server/services/task_repository.py:328-329`、`:500-501`；`server/services/task_restore.py` 里的 `TaskWorker`；`server/api/tasks.py:11` 的导入、`:73` 的 `present_worker`、`:75-76` 的查询；`server/db/models.py:1067` 导出的 `TaskWorker`；`parallel_reads.py:31` 的注释；S64-0 在 `untrusted.py` 里加的两处名字；
  - web：`web/src/components/companion/TaskWorkers.tsx`，以及它在 `TaskPanel.tsx:9` 和 `ProfessionalMethods.test.tsx` 里的引用；`web/src/api/tasks.ts:29`（`workers?`）、`:34`（`TaskWorker` 类型）；`web/src/lib/toolWords.json:16`；`web/src/locales/process.ts` 里 6 种语言的 `t_delegate_work`。
- **`TaskWorker` 这个类先不能整个删：** 迁移 `_0052_task_workers.py:5` 导入它，新装的机器跑迁移会坏。二选一：类留在 `server/db/worker_models.py` 只给 0052 用（注释写 `DELETE-BY: v0.1.64`，条件是 SUB7 这一版把表内联进 0052；做不到就写明顺延到哪一版）；或者把表的定义内联进 0052。⓪Plan 建议后者，SUB7 就不用再回来改。
- 要先查的：`WorkerBrief` 和 `shared_budget_id`（`contracts.py:203`）还有没有别人用；`professional_methods`（`research`、`apple-growth`、`product-design`）除了帮手还有能力页在用（`web/src/components/Capabilities.tsx:13`），**不跟着删**，删不删另问用户；`personal_context.worker_context` 还被 `memory_tools_v2.py:21` 用，留着。
- **S64-0 的测试不删：** 改成测子会话的汇报（帮手 → 子会话，父回合 → 汇总回合），断言不变：汇报加框；汇总回合里 `memory_note` 不自动生效、要联网的命令出卡。
- 量级：产品代码约 −550 行（整份删除，照总计划 U2 的例外不受 800 行限制）。

### SUB7 删 `task_workers` 表（代码都删完以后，单独一个 PR）

- 一个迁移删 `task_workers` 表（号见表头）。
- SUB6 没把表内联进 0052 的话，这里同时处理 `worker_models.py` 里留给 0052 的 `TaskWorker`。
- 迁移的四处同步（sessions §4）：版本文件、`runner.py`、`tests/server/test_migration_runner.py`、`models.py`。
- 量级：产品代码约 +20 / −10 行。

## 不许碰

- Bridge 的帧格式。手机上显示子会话、手机上直接跟子会话说话，都要改帧，用户点头前不做（和 Q1 的帧一起问一次，见 v0.1.64 README §2 第 3 条）。v0.1.64 手机上能看到的只有：总指挥对话里的汇总，以及发到总指挥对话的确认卡（这两样今天的帧就有）。
- ③Hands 的文件。子会话不给 Hands 工具，就不用改它们。
- S64-0 的修复本身（`untrusted.py`、`track_turn`）：本卡只用它的起始值，不另改。
- 项目页、关卡地图、关卡条（v0.1.65）。
- Q1 的卡和它的迁移文件：只用它的列，不改它。要多一个列，跟 Q1 的作者和 ②Main 商量。
- 每次运行自己的预算规则（`execution_budget.py`）：树的上限是另加的一道检查，不改原来那道。
- 学习层、`lessons.py` 本身：子会话靠 `no_learning` 不学，不改学习的规则。

## 怎么做（要点）

1. **S64-0 先合**（#438，不在本卡）。SUB3 要用它加的起始值 `untrusted.carried(seen)`。
2. **SUB2** 等 Q1 的迁移合了再开。只加数据、继承和过滤，用户看不到变化。
3. **SUB3、SUB4、SUB5 叠在一起做，先不合。** 最上面那个 PR 的头上跑 M64 的拆分派汇总题和反面题（DeepSeek 当总指挥），加上全套旧题。过了，三个 PR 按顺序合，每个都要 CI 绿。没过，三个都不合，结论写进早报，回来改。理由：先合进 main 而工具没开放，就是一堆没人调的代码；跑分不过要么返工，要么撤。
4. **跑分过的标准（⓪Plan 建议，用户定）：**
   - 拆分派汇总题三次里至少两次过：开了 2–4 个子会话，每块都有产物，汇总覆盖了每一块，两个子会话没写同一个文件；
   - 反面题三次都不开子会话；
   - 旧题照 K 线的规矩：通过不降、「等你」不增、没有新的报错类型；
   - 记下来不设门槛的：这道题的花费（和不开子会话的同题比是几倍）、服务商回了几次 429。
5. **SUB6** 在 SUB5 合了以后马上做，同一版里删完；**SUB7** 在 SUB6 合了以后。删之前每个名字 `git grep -w` 一遍，再按字符串查一遍（注册表的键、翻译键），结果贴进 PR。
6. **每个 PR 都写完成证据四项**（sessions §8）。SUB3–SUB5 叠着时，跑分的命令、run 的位置和三次的结果写进最上面那个 PR。

### ②Main 的 12 条，在本卡怎么定

1. **汇报带着「读过外部内容」的标记（安全）：** 本卡定（⓪Plan）：汇报一律按外部内容加框；有一个子会话读过外部内容（或不知道），汇总回合一开始就带标记。往下也传（交代里有外部内容时子会话的回合带标记）。两个方向都靠 S64-0 给 `track_turn` 的起始值；测试测后果（`memory_note` 不自动生效、要联网的命令出卡）。
2. **设置和权限只继承、不放宽：** 本卡定（⓪Plan，③Hands 审 #434 时补）：
   - 用的时候沿父对话链取最严的值，不在创建时复制；总指挥收紧，子会话跟着收紧；
   - 继承表覆盖 `ConversationContext` 的每一列，守卫测试钉住；
   - 临时对话不能开子会话；
   - 权限模式今天是全局的，自然一样；以后改成按对话时，同样取链上最严的；
   - 子会话不继承总指挥的「本对话都允许」；卡发到总指挥窗口，授权落在子会话上，按钮写「这个子会话里都允许」；
   - 交代里写的「记住」不是用户说的话：保留 `background_jobs.py:305-306` 的做法。
3. **一段对话同时只跑一个回合：** 本卡定（⓪Plan）：在子会话窗口打字，排到它的后台回合结束再跑；汇报等总指挥空闲才开汇总回合（SUB4、SUB5）。见「对不上」第 1 条：今天的 409 不是这件事。
4. **重启：** 本卡定（⓪Plan）：见 SUB5 的重启矩阵。全部中断，不自动重跑，总指挥那里写一行说明。
5. **停止、删除、撤销：** 本卡定（⓪Plan）：见 SUB5。其中「删总指挥连子会话一起删」用户定。
6. **只有一个浏览器、一个桌面：** 本卡定（⓪Plan）：浏览器确实只有一个（`agent_browser.py:131`），所以 v0.1.64 子会话不给任何 `browser_*`，也不给 Hands 和桌面；这些只留在总指挥那里。以后要给，子会话在同一个浏览器上排队，那时再定排队的做法；桌面那边再问 ③Hands。**放开的时间用户定。**
7. **不同时改同一个文件：** 本卡定（⓪Plan）：每个子会话一个自己的文件夹，靠 SBX 的可写目录管；SBX 做不到就退回「同一时间只有一个子会话写」。
8. **列表：** 本卡定（⓪Plan）：和 Q1 共用 `kind` 列，加父对话 id；所有列表默认不列 `sub`，包括 `/phone/live` 里「正在跑的任务」那一份；Mac 上从总指挥的对话里点开。**手机上显示子会话要改 Bridge 帧，用户定**（⓪Plan 建议 v0.1.64 不做）。
9. **学习和项目证据：** 本卡定（⓪Plan）：子会话 `no_learning`（`lessons.py:405` 已经认）；子会话的后台回合和总指挥的汇总回合都是后台任务，`said=False`。用户在子会话窗口里自己打的字算用户说的话，`said=True`。
10. **层数和数量在代码里管：** 本卡定（⓪Plan）：层数沿父对话往上数；第二层不给工具，执行时也拒（错误码 `sub_session_depth`，照 `worker_host_only` 的写法）。数量：一个总指挥最多 4 个直接子会话，一个子会话最多 2 个 sub-agent，一棵树同时最多 6 个活着的；同时跑的个数由后台任务的全局上限 3 管（`background_jobs.py:27`）。数字在跑分上再调。
11. **`delegate_work` 怎么办：** 本卡定（⓪Plan）：v0.1.64 同一版删掉它和 `TaskWorker`（SUB6 删代码，SUB7 删表），不留作最下层；第三层就是同一个工具开出来的子对话。在那之前由 S64-0 先补洞，因为 SUB6 至少要排在 SBX 和 SUB5 之后，中间几周它还在。
12. **跑分题：** 本卡定（⓪Plan）：题在 M64 卡（拆分派汇总题 + 反面题），记花费和 429。过的标准见「怎么做」第 4 条，用户定。

README 里「开工前要先想好」的另外两条：

- **整个项目一个花费上限：** v0.1.64 先做「一棵树一个上限」（项目树是 v0.1.65）。子会话和汇总回合都是带 Task 的后台任务，每个工具前后都存预算快照（`task_service.py:666`、`:710`、`:760`），所以跨重启也算得到，最多漏掉最后一个工具之后的那一次模型请求。每次请求前查；和每次运行的 $2 上限两个都查。
- **总指挥要排先后（例如视频先定大纲）：** 本卡定（⓪Plan）：不做依赖关系的语法。总指挥分几波开：先开大纲那个，等它汇报，再开其余的。跑分题里放一道有先后的，看 DeepSeek 会不会这样做。

## 验收

- **S64-0（引用，#438）：** 合了，有起始值 `untrusted.carried(seen)`。
- **SUB2：**
  - 子对话不出现在 Mac 侧栏、项目的「对话」标签、`/phone/conversations`、`/phone/live`（子会话正在跑时也不出现）；
  - 子对话的设置改松回 422；总指挥后来开了 `no_memory`，子会话下一个回合就不用记忆；
  - 临时对话开子会话被拒；
  - 守卫测试：给 `ConversationContext` 加一列不填继承表，测试变红（用一个假列验证过一次）；
  - 层数数到第 3 层。
- **SUB3–SUB5（叠起来验）：**
  - M64 拆分派汇总题和反面题按「怎么做」第 4 条过；
  - 测试：第二层调工具被拒；超过数量被拒；子会话的工具表里没有 `browser_*`；
  - 标记，两个方向都测后果：汇报在框里，汇总回合里 `memory_note` 不自动生效、要联网的命令出卡（真跑一个读网页的假子会话）；交代里有外部内容时，子会话的第一个回合同样如此；
  - 子会话的卡出现在总指挥窗口，按钮是「这个子会话里都允许」，点了以后授权只在子对话上；子会话不继承总指挥原有的「本对话都允许」；
  - 交代里写「记住……」，子会话不能用「明确要求存」的授权；
  - 子会话不学（`lessons.after_turn` 没被调用）；`said` 的三种情况；子会话的 `done` 不打勾；
  - 重启矩阵的四行各一个测试（照 `task_repository` 的 interrupted 测试写法）；
  - 停总指挥时子会话也停；删在跑的总指挥回 409；
  - 两个子会话写同一个文件：第二个被沙箱拒（SBX 提供可写目录时），或者第二个排队（退回方案时）；
  - 树的花费上限：假价格下，树里第二个子会话的请求在树上限处停住，单次运行的 $2 还没到；重启后已花的钱从预算快照里读回来。
- **SUB6：** `git grep -nw delegate_work`、`git grep -n t_delegate_work`、`git grep -nw TaskWorkers` 都查不到（S64-0 改写后的测试不再出现这个名字）；新装的机器从空库跑完全部迁移。
- **SUB7：** 迁移测试通过；`git grep -nw TaskWorker` 查不到；旧库升级后没有 `task_workers` 表。
- **手工：** 在 Mac 上开一个项目对话，让它「做一个短视频的标题、大纲、素材清单」，看子会话一行行出现、能点开、能直接说话，最后总指挥出汇总。截图进 PR。

## 量级

| PR | 产品代码 | 测试 |
|---|---|---|
| SUB1 | 无（在 S64-0） | 往下传的测试算在 SUB3 |
| SUB2 | 约 +250（自带迁移再 +40） | 约 +200 |
| SUB3 | 约 +450 | 约 +250 |
| SUB4 | 约 +300 | 约 +200 |
| SUB5 | 约 +350（web 约 150） | 约 +250 |
| SUB6 | 约 −550 | 约 −300（S64-0 的测试改写，不删） |
| SUB7 | 约 +20 / −10 | 迁移测试 |

合计净增约 +800 行产品代码。每个 PR 都在约 800 行以内。

## 风险与回退

- **风险：DeepSeek 拆不好**（开太多、该开不开、汇总漏块）。跑分不过就不合 SUB3–SUB5；SUB2 已经合了也不受影响（只是数据、继承和过滤）。
- **风险：花费成倍、服务商 429。** N 个子会话就是 N 倍的请求。全局 3 个的并发上限和树的花费上限兜底；跑分记 429 次数，太多就把同时跑的上限调小。
- **风险：标记漏传**（往上、往下两个方向）。测试要真跑一个读网页的假回合，并且测后果（笔记不自动生效、断网卡出现），不能只断言标记或源码里有这个名字。
- **风险：继承漏列。** 以后给 `ConversationContext` 加的列没进继承表，子会话可能比总指挥松。守卫测试兜底。
- **风险：可写目录。** 「每个子会话一个文件夹」靠 SBX。SBX 的接口和本卡设想的不一样时，退回「同一时间只有一个子会话写」，并在 PR 描述里写明。
- **风险：违反 sessions §11 第 3 条。** 子会话是新子系统：v0.1.63 排了的删除没合完之前不开，同一时间只做一个新子系统。和 Q1、CAP、INB 谁先谁后，用户定。S64-0 是安全修复，不受这条限制。
- **旧路径：**
  - S64-0 之后、SUB6 之前的 `delegate_work`：代码注释写 `DELETE-BY: v0.1.64`（随 SUB6 删）；
  - SUB6 若把 `TaskWorker` 类留给迁移 0052：注释写 `DELETE-BY: v0.1.64`，前提是 SUB7 这一版把表内联进 0052 并删掉这个类；SUB7 赶不上就改写成它真正会删的版本。
- **回退：**
  - SUB2：revert 后子对话重新出现在列表里；迁移不回退（列留着，没人读）。
  - SUB3–SUB5：按倒序 revert，工具从工具表里消失；已经建出来的子对话变成普通对话（`kind` 还是 `sub`，但没人特殊处理），列表过滤要跟着 SUB2 一起撤。
  - SUB6：revert 会把 `delegate_work` 带回来，只在 SUB3–SUB5 也撤了的时候才做。
  - SUB7：删表的迁移进过正式版就不能撤（sessions §4）；合之前确认 SUB6 不会再撤。

## 开工前要用户定的

1. **S64-0 单独做**（⓪Plan 的提议：把 `delegate_work`、后台任务从干净开始、教训的合并、恢复和 `task_progress` 几个洞放进一个安全 PR，SUB 只引用）。
2. **跑分过的标准**（「怎么做」第 4 条）：拆分派汇总题三次过两次、反面题三次全不开、旧题不退步。
3. **一棵树的花费上限默认多少？** ⓪Plan 建议每次运行上限的 3 倍（默认 $6），在设置里和每次运行的上限放一起。
4. **删总指挥时子会话一起删吗？** ⓪Plan 建议一起删（有子会话在跑时先拒）。
5. **手机上显示子会话**（改 Bridge 帧）：⓪Plan 建议 v0.1.64 不做，手机上只看总指挥的汇总和发到总指挥的卡；要做就和 Q1 的帧一起问。
6. **子会话什么时候能用浏览器、Hands 和桌面？** ⓪Plan 建议 v0.1.64 不给。
7. **和 Q1、CAP、INB 的先后**（§11 第 3 条：同一时间只做一个新子系统）。
8. **`professional_methods`**（`research`、`apple-growth`、`product-design` 三个方法和能力页上的编辑）：SUB6 删掉帮手以后，除了能力页的编辑没有别的调用方，要不要另开一张卡删。SUB6 本身不删它们。
