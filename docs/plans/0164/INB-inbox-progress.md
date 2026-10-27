# INB 收件箱拆掉，东西回到各自的地方；加「进展」页的四行简报

> 草稿（⓪Plan 2026-10-29 夜间起草），用户批准 v0.1.64 计划之前不开工。

| 项 | 内容 |
|---|---|
| 道 | ②Main（⓪Plan 的建议；②Main 卡太多时可以另开一个会话分走 INB3–INB9） |
| 版本 | v0.1.64 |
| 分级 | 必须（⓪Plan 建议，用户定） |
| 依赖 | INB1、INB2 不依赖别的卡，最先做。其余：文案跟 ACM（卡片界面与文案大合并，领先路线里叫 D1）对齐，但不并进 ACM、不等 ACM 合并；SUB（子会话的父链接、子会话的验收单，`delegate_work` 的外部内容标记）；Q1（iPhone 快问输入框，四行简报挂在它下面）；Bridge 帧的一次性决定（v0.1.64 README §2 第 3 条） |
| 合并位置 | INB1 → INB2（安全面，先合）→ INB3 → INB4 → INB5 → INB6 → INB7 → INB8 → INB9。手机那半（INB5、INB7、INB8 里标了「手机」的部分）等 Bridge 帧点头，可以顺延，不挡 Mac 端 |
| 推动的门槛 | R64「用户验收：收件箱改完后用户一天的使用感受」；R64 安全（碰安全面的 PR 都有 effort=max 审查 + Codex 审查）；§11「换掉就删掉」（收件箱的代码本版删完） |
| 分支 | `claude/0164-inb1-lessons-direct`、`claude/0164-inb2-memory-direct`、`claude/0164-inb3-scheduled-entry`、`claude/0164-inb4-inbox-out`、`claude/0164-inb5-sidebar-dots`、`claude/0164-inb6-run-records`、`claude/0164-inb7-progress-brief`、`claude/0164-inb8-push`、`claude/0164-inb9-acceptance-sheet` |
| 迁移号 | INB5 要一个（「做完未看」的已读标记），开工时向 ②Main 申请；其余 PR 不要迁移（见各节） |

## 目标

- **用户的原话：** 「看 Inbox 70 多条就头疼，agent 反而给我加了这么多活」。用户 10-28 逐条同意了八条（`docs/plans/0162/README.md` §8「收件箱怎么改，加『进展』页」）。本卡做 v0.1.64 那部分：第 1、2、5、6、7、8 条，第 3 条的基本入口，第 4 条的四行简报，加上先核每次运行记了什么。第 4 条的时间线和地图、第 3 条的外观，是界面版的事，不在本卡。
- **角标为什么满：** 角标是 `summary()` 的三项相加（`server/services/proactive_service.py:294-307` → `web/src/App.tsx:80`、`:633-634`）：没看过的主动提醒、等批的卡、记忆等你确认。最后一项 `_memory_waiting`（`proactive_service.py:310-321`）数的是 `memory_proposals` 里所有 pending 的行，加上 `lessons` 里 `status="proposed"` 的行。所以先做第 6、7 条（INB1、INB2），角标就降下来了；其余按「东西挪到哪」拆。
- **收件箱今天有五块**（`web/src/components/proactive/ProactiveInbox.tsx`），每块都要有去处，不能丢：

| 今天在收件箱里的 | 来源 | 挪到哪 | PR |
|---|---|---|---|
| 现在就要你批准的卡 | `GET /approvals/pending`（`server/api/approvals.py:30-32`；`InboxApprovals.tsx:54`） | 对话里本来就有；灵动岛（`web/src/island/feed.ts:117`）和 iPhone 照旧能答。收件箱这一份删掉 | INB4 |
| 「你不在时没做的」 | `GET /approvals/refused`（`approvals.py:59-88`，`permission_store.refused_groups` `:165-182`） | 每行都带 `conversation_id`。定时任务的（`decided_by=policy`，`unattended`）→ 定时任务入口里那个任务；后台任务和对话里的 → 那个对话。「总是允许」和撤销会建长期规则，照原样搬，不改 | INB3、INB4 |
| 记忆等你确认 | `InboxMemory.tsx` ← `web/src/lib/pendingMemory.ts:27-62`（三个来源） | Memory 页的「待整理」；学到的做法回「学到的做法」列表 | INB1、INB2 |
| 主动提醒 `proactive_items` | `proactive_service.py`；五种 `kind`（`server/db/models.py:1087`） | `job_followup` 带 `conversation_id` 和「接着做」（`proactive_service.py:344` `accept`）→ 那个对话；`scheduled_problem`、`web_change`、`folder_change` → 定时任务入口（第 3 条），沿用 `proactive_diagnosis` 的「猜测 + 下一步」；`brief` → 被进展页的四行简报取代 | INB3、INB4、INB7 |
| 侧栏的「在盯着」和静音 | `WatchesPanel.tsx`（静音列表也在这里管） | 定时任务入口 | INB3 |

  另外三样没有界面块、但要有去处：`POST /proactive/scan`（「现在检查一下」）→ 定时任务入口；`POST /proactive/items/seen` → 在新位置看到时标已读；`/proactive/config` 已经在设置里（`web/src/components/settings/ProactiveSection.tsx:57-58`）。
- **名字陷阱：** `POST /phone/inbox`（`server/api/phone.py:261`）和工作区里的 `Inbox/iPhone/` 文件夹（`phone.py:235-237`）是 iPhone 发来的文件，跟收件箱无关，不删、不改名。

## 先核过的现状（⓪Plan 读 main `8db45ef9`）

- **侧边栏已经有状态图标。** 每个对话一个：在干活（进度环）、等你（琥珀色 !）、做完（绿勾）、没做成、停了、定时、Remote（`web/src/components/ConversationGlyph.tsx:9-45`），状态来自 `GET /conversations` 的 `state`（`server/services/phone_reads.py:235-293`：`waiting` 取自灵动岛的等卡对话 `:271-272`，`working` 取自运行中的任务 `:273-274`，其余按最后结果 `:276-280`）。缺的是：「做完未看」、项目一级的点、角标按「几个对话在等」数。
- **定时任务现在在「Activity」页里**（`web/src/components/ActivityView.tsx:97` 的 `ScheduledTasksCard`），能看每次运行（`GET /scheduled-tasks/{id}/runs`，`server/api/scheduled_tasks.py:267`）。
- **学到的做法（第 6 条）今天在哪几处变成「等你确认」**（`server/services/lessons.py`）：
  1. 设置「学到的做法直接生效」关着（`:265-266`；默认开，`settings_service.py:247-252`）；
  2. 这一轮读过外部内容，而且不是用户亲口纠正（`:277`，就是 README 说的那道闸）；
  3. 判断模型没给答案，而来源是用户纠正（`:275` 放行、`:277` 的 `bool(worth)` 让它不生效）；
  4. L1：纠正不是在回应 Arslan 之前做的事，或者跟这一轮刚走通的路线相反（`:278-284`）；
  5. 跟已有的一条冲突，又不是用户纠正盖掉旧的（`:309-314`）。
  另外：`stale` 状态在表约束里有（`models.py:874` 的 `ck_lesson_status`），但**没有任何代码把一条做法设成 `stale`**；`failed` 只是累计数（`lessons.py:382-396`），不是「连续失败」。第 6 条的「连续失败就自动停用」是新做的。
- **关于你的记忆（第 7 条），README 的说法要改正：**
  - 今天「关于你」的记忆只有两条路直接生效：用户这句话明确说了「记住」（宿主的显式保存，摘要要对上，`arslan/companion/memory.py:124-128`），或者事实提取器（`server/services/turn_facts.py:93-108`）——它**只读用户自己的消息**，按构造就碰不到网页和文件，不靠 `external_seen`。
  - 用 `external_seen` 的只有 Arslan 自己的笔记（`server/services/memory_tools_v2.py:137` → `memory.py:137-139` 的 `own_note`）。
  - 所以第 7 条其实是**放宽**：模型通过 `remember`、`memory_note` 写的「关于你」，今天没有「记住」二字就是提案（`memory.py:140-153` 落到 `proposed`，`memory_repository.py:231-232`、`:238-248` 建一条 `memory_v2` 提案）。放宽后同样要过 `external_seen` 这道闸。
  - 敏感的今天不是「当场问一句」，是要用户在表单里确认（`memory.py:129-130`，`sensitive_acknowledged` 只有 `origin=="user"` 才算）。关键词表（`memory.py:118-121`）有健康、钱、证件、住址，**没有家人**。
  - README 说「跟现有的敏感记忆规则（#239）对上」。#239 是**读**这一侧：专家 / 子任务的回忆永远拿不到敏感记忆（`server/services/personal_context.py:323-325` 一带）。**写**这一侧的规则在 `decide_write`（`memory.py:113-130`）。两边都要留。
  - 精简方案早就定了「记忆提案不再推给用户审，需要确认的敏感记忆照旧问」（`docs/plans/2026-10-17-0162-reduce-proposal.md:109`），代码没跟上：`_memory_waiting` 照数，`InboxMemory` 照列。
- **外部内容这道闸的两个漏洞（第 6、7 条都靠它）：**
  - `delegate_work` 的帮手会读网页（`web_search`、`web_extract`），但工具结果写的是 `"external": False`（`server/services/task_workers.py:268`），`delegate_work` 也不在 `_OUTSIDE_TOOLS` 里（`server/orchestrator/untrusted.py:72-73`），所以 `tool_loop.py:375-377` 不会把这一轮标成「读过外部内容」。SUB 卡说要补这个洞。
  - 用户点「接着做」恢复的回合（`server/services/task_service.py:1088-1110`）把上一次的进度当外部数据放进提示（`wrap_external`），但新回合的标记从「没读过」开始（`untrusted.py:92-94`，`tool_loop.py:2812`），上一次读过的外部内容不算进来。
- **停下来的任务：** 后台任务的 `job_followup` 提醒带 `conversation_id`（`models.py:1098`），重启打断的任务已经会在原对话里说一句（`server/services/background_jobs.py:398-425`）。
- **验收引擎：** `AcceptanceCheck`（`arslan/companion/contracts.py:110-125`，三种评判：确定性 / 人 / 模型；关键项不许只靠模型）。聊天回合只用默认的「回答发出去了」（`task_service.py:1014` 的 `_acceptance or [ANSWER_DELIVERED]`，`:1028` 的 `_answer_only`）。后台任务有自己的验收项（`background_jobs.py:63`、`:133-134`）。
- **推送今天推什么：**
  - Mac 原生通知（`desktop/src-tauri/src/resident.rs:127-145`）：回合做完（ok）、需要注意、要批准、定时任务完成 / 失败 / 暂停、主动提醒。`lesson_learned` 不弹（没有对应的项，`:138` 返回 None；`server/services/desktop_status.py:28` 也写明它是安静的）。主动提醒弹，点开到 `@inbox`（`resident.rs:158-162`）。免打扰时段只管主动提醒（`arslan/proactive_policy.py:157-161`），不管别的通知。
  - iPhone：`notify=1` 的有：最终回复、报错、后台任务结束（done/partial/stuck/stopped）、要批准、批准失败或过期、设备被撤销（`docs/specs/mobile-bridge-protocol.md:228-230`，`spec/mobile-bridge/reference.py:196-205`）。手机端**没有收件箱帧**；`conversations.result` 已经带 `state`（协议 `:303-304`）。
- **简报：** 今天的早报 `build_brief`（`proactive_service.py:157-185`）不调模型，但「在跑的」读的是内存里的 `background_jobs._jobs`（`:168`）。重启以后它是空的，而被重启打断的任务在库里是 `waiting_user / process_interrupted`（`background_jobs.py:410-412`），应该算「卡住」，简报里却凭空消失了。
- **每次运行记了什么**（INB6 补）：
  - **有：** `runs`（模型、token、耗时、状态、报错类型，`models.py:541-590`）；`run_steps`（每次工具调用一行：`args_summary` 截到 200 字，`tool_loop.py:1397`；回答的 `output_preview` 截到 500 字，`server/services/run_recorder.py:252`）；改了哪些文件 = S3 检查点的清单（`server/services/checkpoints.py:112` `manifest(run_id)`）；任务的预算快照和验收结果（`server/db/task_models.py:34`、`:36`），任务和运行的对应（`task_attempts.run_ids`，`:59`）；产出文件按运行列（`server/services/phone_reads.py:66-82`，`artifact_store.list_artifacts`）；花费的 token（`usage_ledger`，`models.py:922-944`）。
  - **缺：** 读了哪些文件，没有单独的字段（只能从 `args_summary` 里猜，而且会被截断）；定时任务每次运行记的 `run_id` 永远是 None（`server/services/scheduler.py:471`、`:479`），所以定时任务的运行点不开；子会话没有父链接（SUB 的迁移加）。
  - **没核：** 产出（`artifact_store`）是不是每种交付都进了清单。INB6 开工先核。
  - `server/api/runs.py` 的诊断接口只认 `kind=="live"`（`:281`、`:347`、`:386`、`:466`），这个问题照旧在（§8 已登记），INB6 不顺手改，进展页也不读这几个接口。

## 改哪些文件

按 PR 列。每个 PR 产品代码不超过约 800 行（测试、翻译不算）。

### INB1 学到的做法直接生效（第 6 条）· 安全面 · effort=max

- `server/services/lessons.py`
  - 「直接生效」只去掉「等用户点头」这一步。今天会变成提案的五种情况（上面列的 1–5）**全部改成「没生效，但看得见」**，一条都不许变成生效。DB 里的值仍用 `proposed`，界面上叫「没生效」，并写明原因（设置关了 / 读过外部内容 / 判断没给答案 / 不像纠正 / 跟已有的冲突）。原因记进 `evidence`（JSON，不要迁移）。
  - **堵一个合并的口子：** `:296-304` 新条合并进一条旧的 `proposed` 时，只要新条能生效，就把旧条整条打开，而旧条的文字可能来自读过外部内容的那一轮（只有用户纠正才会用新文字覆盖，`:301-302`）。改成：合并进一条「没生效」的旧条时，用新条的文字覆盖再生效，或者保持不生效。
  - **连续失败自动停用：** `record_applied`（`:382-396`）里，用了这条做法而这一轮失败，`evidence["fail_streak"]` +1，成功清零；连续 3 次（跟定时任务「连续 3 次失败自动暂停」同一个数，`models.py:952`）就设成 `stale`，写明原因。`recall`（`:336` 起）本来就只取 `active`。
- `server/services/task_service.py:1088-1110` + `server/orchestrator/untrusted.py`：恢复的回合一开始就算「读过外部内容」（它带着上一次的进度）。例如给 `track_turn()` 一个起始值，由 `resume_turn` 设。改 `tool_loop.py` 只动 `:2812` 一行，按 §3 排在打开的 K 线 PR 后面。
- **`delegate_work` 的洞：** 本 PR 先写测试（今天会失败）：一轮里只用 `delegate_work` 读了网页，学到的做法不能生效。修法（把 `delegate_work` 算作外部内容，或者帮手读过网页时结果写 `external: True`）跟 SUB 卡**谁先合谁做**，⓪Plan 建议放在本 PR，因为本 PR 最先合、直接靠这道闸。
- `server/services/proactive_service.py:317-319`：`_memory_waiting` 不再数 `proposed` 的做法。
- `web/src/lib/pendingMemory.ts:53-60`：不再把做法放进「等你确认」。
- `web/src/components/LearnedLine.tsx`：对话里那一行不再问「记住 / 不用」（`:23-25`）。生效的照旧「学到了… [撤销]」；没生效的写「学到一条，没生效：<原因>」，加「在 Memory 里看」。
- Memory 页「学到的做法」列表（`web/src/components/companion/MemoryList.tsx` 里列做法的那块，开工时定位）：显示没生效 / 已停用和原因，能手动打开、能删（`server/api/lessons.py:50-69` 已有接口）。
- **测试：** 五种情况各一条，断言是 `proposed` 且原因对；读过外部内容的做法不生效、在 Memory 页列出；合并口子；连续 3 次失败 → `stale`、不再被回忆；恢复的回合不生效；`delegate_work` 那条；角标不再数做法。

### INB2 关于你的记忆直接记下（第 7 条）· 安全面 · effort=max

- `arslan/companion/memory.py` `decide_write`（`:97-153`）：给模型写的「关于你」加一条直接生效的路，条件全都要满足：
  - 这一轮没读过外部内容（`MemoryActor` 加一个字段，像 `auto_activate_own_notes` 那样由 `memory_tools_v2.py` 在写入时按 `untrusted.external_seen()` 设）；
  - 用户在场的回合（窗口或 iPhone 发起的）。后台任务、定时任务、子会话里**一律不直接写**；
  - 普通敏感度（关键词检查之后仍是 `normal`）；
  - 不带风格参考（`:133-134` 照旧）。
  **原样保留：** `no_learning`、`temporary` 拒绝写（`:100-101`）；钥匙不进记忆（`:102-104`）；任务范围不进长期记忆（`:105-106`）；范围检查（`:107-112`）；云端用不用照 `cloud_memory_allowed`，否则 `local_only`（`:141-147`）。
  不满足的仍落成 `proposed` 加一条 `memory_v2` 提案（`memory_repository.py:231-232`），但提案的 `reason` 写清楚（`external_seen` / `background` / `sensitive`），**不进任何队列、不进角标**，只在 Memory 页「待整理」里看得见。
- `server/services/memory_tools_v2.py`：`remember`（`:46-95`）和 `memory_note` 的 `about_you`（`:112-170`）设上面那个字段。`supersede`（改已有的一条）照旧是提案：改已确认的文字要用户看新旧两版（`:79-81` 的注释）。
- **敏感的「当场问一句」：**
  - 关键词表（`memory.py:118-121`）补上家人一类（中英文：家人、家属、孩子、父母、配偶、family 等，具体词表在 PR 里列出、⓪Plan 审）。只加，不删。
  - 对话里那一行（`web/src/components/RememberedLine.tsx:50-53`，今天是「想记住… [去 Memory 看]」）改成两个按钮：「记住（只在本机用）」「不用」。按钮绑定**那一条提案的 id、版本和原文**：`memory_proposed` 帧（`server/services/turn_facts.py:138`；`server/orchestrator/arslan.py:556`）加 `proposal_id`。答的走现有的 `POST /memory/proposals/{id}/resolve`，`sensitive_acknowledged=true`、`use_policy=local_only`（跟今天收件箱里的「记住」一样，`pendingMemory.ts:39`）。版本对不上就失败（`memory_repository.py:318` 已有）。这是窗口的 socket 帧，不是 Bridge 帧。
  - 没答的就留在「待整理」，不再问第二次，不推送、不进角标。
- **旧提案挪到「待整理」（不删用户数据）：**
  - Memory 页顶部现在就有「等你确认」（`MemoryList.tsx:200-221`、`:376-380`）。改名「待整理」，默认收起，只在 Memory 页里显示件数。
  - 里面放：旧的 `memory_v2` 提案（`server/api/companion.py:386-395`）和整理建议（`kind != "memory_v2"`，`server/api/brain.py:650-670`），加上 INB2 以后新落下的（按 `reason` 分组，旧的和新的分得开）。
  - **不动任何一行：** 不改状态、不批量接受、不删。「记住 / 不用」照旧能逐条点；`/memory/noticed-earlier` 的「全部采用」（`companion.py:398-430`）照旧。
  - v0.1.65 记忆文件化时并进去。代码注释写 `DELETE-BY: v0.1.65 when memory files land (the 待整理 rows are merged into them)`。
- `server/services/proactive_service.py:310-321`：`_memory_waiting` 整个删掉（INB1 之后它只剩记忆提案这一项）。`summary()` 里的 `memory` 字段同时删，`App.tsx:633` 跟着改。
- **测试：**
  - 没读过外部内容、用户在场、普通 → 生效；
  - 读过外部内容（含 `delegate_work`、恢复的回合）→ 不生效、有 `reason`、在待整理里；
  - 后台、定时、子会话 → 不生效；
  - 敏感（含「家人」）→ 不生效，对话里的按钮只能答那一条，版本变了就失败；
  - `no_learning` / `temporary` 照旧拒绝；
  - 角标不再数记忆；
  - 旧提案一条不少、状态不变。

### INB3 定时任务单独一个入口（第 3 条的基本版）

- `web/src/lib/sections.ts:14-22`：加 `scheduled`；侧边栏（`web/src/components/Sidebar.tsx`）加一项「定时任务」。外观先用现有样式。
- 新页面（例如 `web/src/components/scheduled/ScheduledPage.tsx`）：
  - 每个定时任务一行，点进去看每次运行。`ScheduledTasksCard` 从 Activity 页（`ActivityView.tsx:97`）挪过来，不是复制。
  - 「盯网页、盯文件夹」也在这里，各一行。`WatchesPanel.tsx` 连同静音列表一起挪过来。
  - 「现在检查一下」（`POST /proactive/scan`）放在这一页。
  - **标点：** 一个任务的运行失败或被暂停、有它的 `scheduled_problem`（`source_key` 为 `sched:<id>`）、有它在用户不在时没能问的操作，就在那一行上标点。网页、文件夹的变化（`web_change`、`folder_change`，`source_key` 为 `watch:<id>`）标在对应那一行，原来的「猜测 + 下一步」（`proactive_diagnosis`）照旧显示。
- `server/api/approvals.py:59-88`：`GET /approvals/refused` 加 `conversation_id` 过滤，前端按任务的对话取。定时任务的对话 id 是 `task.conversation_id or f"scheduled-{id}"`（`scheduler.py:421`、`:449`）。定时任务也可能写进一个普通对话，这时按 `decided_by=="policy"`（`unattended`）认作定时任务的那一份。`InboxRefused.tsx` 原样复用（「总是允许」和撤销不改）。
- **测试：** 任务、盯网页、静音都能在新页面找到；有问题的任务有点；refused 按对话过滤。

### INB4 去掉收件箱列表；停下来的任务和确认卡回到对话（第 1 条、第 8 条前半）

- **对话那边：**
  - 打开一个对话时，顶部列出这个对话里「你不在时没做的」：后台任务和聊天回合的那份，`decided_by=="away"`，用 INB3 的过滤，`InboxRefused` 复用。
  - 这个对话的 `job_followup`：显示成一张卡，带「接着做」（`proactive_service.py:344` `accept`）、「先放着」「不用了」。
  - 确认卡本来就在对话里；灵动岛和 iPhone 照旧能答。
- **角标：** `summary()`（`proactive_service.py:294-307`）换成「几个对话、项目或定时任务在等你」，不是条数。
  - 一个对话算「在等你」：有等批的卡、有没处理的「没做的」、有 `job_followup`、或者有 👀 项（INB9 以后）。
  - 定时任务算：有标点的。
  - 跟 INB7 的「要你做」**用同一个函数**（例如 `server/services/progress.py` 的 `waiting_on_user()`），不许两处各算各的。
- **删掉（§11，本 PR 内，`git grep` 查不到为证）：**
  - `web/src/components/proactive/ProactiveInbox.tsx`、`InboxApprovals.tsx`、`InboxMemory.tsx`；
  - `AskForFrame.tsx`：只有 `InboxApprovals` 引用它，PR 里贴 `git grep -w` 结果；
  - `sections.ts` 里的 `inbox`，`Sidebar.tsx:139-142` 的收件箱项，`App.tsx:127`、`:633-634`、`:803` 的收件箱分支；
  - `web/src/hooks/useProactiveSummary.ts`（换成新的计数）；
  - `web/src/lib/openConversation.ts:11-17` 的 `@inbox`，`resident.rs:158-162` 的 `@inbox`（和 `:815-826` 的测试）：改成到对话或进展页（`@progress`）；
  - 6 种语言里只给收件箱用的 key（`inbox.*`、`proactive.page.*` 中只有收件箱用的）。
  - `GET /proactive/items` 和 accept / snooze / dismiss 保留：对话和定时任务页还要用。
- **测试：** 每一块都能在新位置找到（五块各一条）；角标按对话数，同一对话三条也只算 1；`@inbox` 查不到。

### INB5 侧边栏状态点：「做完未看」和项目一级（第 2 条）

- **迁移（要一个号）：** 新表，例如 `conversation_seen(conversation_id, seen_message_id, seen_at)`。用新表，不往 `conversation_contexts` 加列，因为不是每个对话都有那一行（`server/services/task_context.py` 里 `row` 可能为 None）。
- `server/services/phone_reads.py:235-293` `describe()`：最后一条是做完的回复、且比已读标记新，`state` 给新值 `done_unseen`。
  - 窗口显示了最后一条就记已读；手机拉了 `chat.history` 也算已读。
- `web/src/lib/conversationMeta.ts:7`、`:21`，`ConversationGlyph.tsx`：加 `done_unseen` 的样子（先用现有样式，比如绿勾加一个小点）。
- **项目一级：** 项目行上取它下面对话里最要紧的那个状态：等你 > 在干活 > 做完未看。
- **手机：** `conversations.result` 的 `state` 多一个值，要改协议 `:303-304` 和测试向量。**等 Bridge 帧点头；没点头之前，发给手机的仍是 `done`。**
- **测试：** 做完未看 → 打开 → 变成做完；重启后已读还在；项目取最要紧的那个；没点头时手机收不到新值。

### INB6 先核每次运行的记录，缺的补上（第 4 条的数据部分）

- 先核，结果写进 PR：读改了哪些文件、跑了哪些命令、花费、产出、子会话，每样各在哪、缺什么。上面「每次运行记了什么」是 ⓪Plan 的初核。
- **补：**
  - `server/services/scheduler.py:471`、`:479`：记下真的 `run_id`（`scheduled_task_runs.run_id` 列本来就有，`models.py:992`，不要迁移）。
  - **读了哪些文件：** `read_file`、`search_files` 的完整路径写进那一步的 `run_steps.detail`（JSON，不要迁移），不再靠截断的 `args_summary` 去猜。
  - **产出：** 核过有缺再补。
- **子会话的父链接：** 不在本卡，用 SUB 的迁移（v0.1.64 README §6「Q1 + SUB」）。
- **不改：** `runs.py` 的四个诊断接口（见上）。
- **测试：** 定时任务的运行能点开；读文件的那一步有完整路径。

### INB7 进展页：最上面四行简报（第 4 条的简报）

- Activity 页改名「进展」，不删（用户点名要）。导航 key 换名，6 种语言同一个 PR。
- `server/services/progress.py`（新）：
  - 四个数**都从记录里取**：
    - **做完**：今天做完的对话和定时任务运行；
    - **在做**：`companion_tasks.phase` 是 `queued` / `running` / `verifying` 的，加上正在跑的回合；
    - **卡住**：没做成、停了、`waiting_user` 但不是在等用户回答（例如 `process_interrupted`、预算用完）、暂停的定时任务；
    - **要你做**：INB4 那个函数。
  - 单位跟角标一样，按对话、项目、定时任务数，不按条数。
  - 每一项都带能点开的列表（对话 id 或任务 id）。
  - 侧边栏「进展」的角标 = 要你做的件数，跟 INB4 是同一个数。
- **不用内存里的 `_jobs`：** 「在做」读持久化的 `companion_tasks`。重启打断的任务（`background_jobs.py:410-412`）算「卡住」。
- **模型只负责写成人话，不许报数：** v0.1.64 先用模板句（不调模型、零花费），⓪Plan 建议。以后要让模型润色，就把数字和列表当参数传进去，并检查模型回来的句子里每个数字都和记录一致，不一致就退回模板。
- **早报换掉（§11）：** 早报 `build_brief`（`proactive_service.py:157-185`）、`kind=="brief"` 的提醒、设置里早报的开关（`ProactiveSection.tsx:91-93`，配置里的 `brief_enabled` / `brief_time`）同一个 PR 删掉。四行简报就是这一页的开头，打开就是最新的，没有谁「发」简报。
- 在任何对话里问「进展怎么样」：给模型一个只读工具，返回同一份数据，不另算。工具说明要短，按 K 线的工具按需规则挂。
- **手机：** iPhone 快问输入框下面显示「要你做」的几件和四行简报，例如在 `status.snapshot` 加一个可选的 `brief` 字段。**等 Bridge 帧点头，可以顺延**；Mac 端不等。
- **测试：**
  - 每个数和手工从库里数的一致，含重启以后；
  - 同一个对话三件事只算 1；
  - 早报的代码查不到；
  - 模板句里没有不来自记录的数字。

### INB8 推送只推「要你做」的（第 5 条）

- **Mac**（`resident.rs:127-145`）：
  - 只弹这些：要批准、需要你看（`turn_finished` 的 `error` / `needs_review`）、定时任务失败 / 暂停、有 👀 项的验收单、`job_followup`；
  - 不再弹：做完（`notify_done`、`notify_scheduled_done`），以及网页、文件夹变化这类不需要用户做事的主动提醒；
  - 点开到那个对话或进展页（INB4 已换掉 `@inbox`）。
- **免打扰：** 今天只管主动提醒（`proactive_policy.py:157-161`）。改成管所有原生通知：服务端在状态里给一个「现在是不是免打扰时段」，`resident.rs` 照它办。
  - 免打扰不影响角标和进展页。
  - 要批准的卡在免打扰时段弹不弹，要用户定（见最后一节）。
- **手机：** `notify=1` 的范围要跟着改（协议 `:228-230`、`reference.py:196-205`、`make_vectors.py` 重新生成向量）。今天最终回复和后台任务结束都会提醒。这是协议改动，**等用户和 ①iOS 点头，可以顺延**。
- **测试：** 每种事件弹不弹的一张表；免打扰时段不弹；点开的目标对。

### INB9 验收单留在对话或项目里（第 8 条后半）

- **⓪Plan 的建议：v0.1.64 只给用户不在场的运行出验收单**：后台任务、定时任务、子会话。用户在场的聊天回合以后再做，到时要带跑分前后对比（M64）。原因：每个回合都多出一张单，会改每个回合（今天是只看回答发没发出去，`task_service.py:1014`、`:1028`），K 线的跑分要重测。
- **动手前写出「做完的样子」：**
  - 后台任务已经有自己的验收项（`background_jobs.py:63`、`:99-110`）；
  - 定时任务今天走 `run_turn`，没给 `_acceptance`（`scheduler.py:466` → `task_service.py:987`）。改成每次运行开头由模型写出验收项，写进任务说明（`TaskSpec.acceptance`），不加列、不要迁移。另一种做法是建任务时写好存下来（要加列）。⓪Plan 建议前一种，用户可以改。
  - 子会话的：等 SUB。
- **做完给三栏：**
  - ✅ 我验过的：确定性检查通过，附证据，比如文件路径、命令结果；
  - 👀 要你看一眼的：评判是「人」的，最多一两项，多的放进 ⚠️ 并写明；
  - ⚠️ 没验到的：没跑、失败、只有模型说过的。
  - 数据取 `companion_tasks.results` 和 `AcceptanceCheck.evaluator`（`contracts.py:113`）。
  - 发进那个对话或项目（像 `background_jobs.py:421-424` 那样写一条消息）。验收单不进收件箱，也没有收件箱了。
- 👀 项算进「要你做」（INB4 的函数），也会推送（INB8）。
- **测试：** 三栏各有来源；只靠模型的不进 ✅（`contracts.py:117-125` 的规则）；用户在场的回合没有验收单；👀 进了角标。

## 不许碰

- 外部内容那道闸本身的判定（`untrusted.counts_as_external`），只许加严（补 `delegate_work`、恢复的回合），不许放松。
- `decide_write` 里上面「原样保留」列的几条；#239 的回忆规则（读的一侧）。
- 「总是允许」建规则的方式（`POST /permissions/rules {refused_id}`）和撤销：只搬位置。
- 确认卡本身、灵动岛怎么答卡（`server/services/approvals.py:276` 的 `island_may_answer`）。
- Bridge 帧格式：没有用户点头，不改 `conversations.result` 的取值、`status.snapshot` 的字段、`notify` 的范围。这些在 INB5、INB7、INB8 里都是单独的一块，可以晚合。
- `/phone/inbox` 和 `Inbox/iPhone/` 文件夹。
- 记忆提案和整理建议的数据：不改状态、不删、不批量处理。
- 第 4 条的时间线和地图、第 3 条的外观：界面版的事。
- `server/api/runs.py` 的诊断接口。

## 怎么做（要点）

1. **INB1、INB2 先写会失败的测试：** 读过外部内容（含 `delegate_work` 和恢复的回合）以后学到的做法、写下的「关于你」不能生效；今天会变成提案的每一种情况，以后都是「没生效」，一种都不许变成生效。测试先红，再改代码。
2. **INB1、INB2 按 effort=max 写和审，再加 Codex 审**（v0.1.64 README §1）。审查要专门看：有没有哪条路能让「没生效」的东西被自动打开（合并、批量接受、旧数据迁移）。
3. **每个挪走的东西先在新位置做出来，再删旧的**，但新旧在同一版里做完（§11 第 1 条）。INB4 的验收是「收件箱的代码查不到」，`git grep` 的结果贴进 PR。
4. **「要你做」只有一个函数：** 角标、进展页的简报、推送、手机都读它。
5. 文案的写法跟 ACM、STY 对齐（任务汇报那四条原则）。文案先写中英文，其余四种语言同一个 PR 补上（§3）。

## 验收

- **INB1 / INB2：**
  - 测试全过，effort=max 审查和 Codex 审查的结论写进 PR；
  - 角标里不再有记忆和做法；
  - Memory 页能看到每一条没生效的做法和记忆，以及没生效的原因。
- **INB4 合并后：**
  - `git grep -n "ProactiveInbox\|InboxApprovals\|InboxMemory\|@inbox\|useProactiveSummary"` 没有结果（测试文件一起删）；
  - 收件箱五块，每块都能在新位置找到（逐块截图）。
- **INB7：**
  - 四个数和手工从库里数的一致，含重启以后；
  - 页面上看不到不来自记录的数字。
- **用户验收（R64）：** 改完后用户用一天，看角标是不是只剩真要他做的。

## 量级

| PR | 产品代码（约） | 说明 |
|---|---|---|
| INB1 | +200 | 加测试约 +250 |
| INB2 | +300 | 敏感那一行的按钮 + 待整理改名；测试约 +300 |
| INB3 | +300 | 多半是挪组件 |
| INB4 | +300，删约 −700 | 删的部分照总计划 U2 的整份删除算 |
| INB5 | +200 | 一个迁移；手机那半另算 |
| INB6 | +150 | 先核，可能更少 |
| INB7 | +350，删约 −150（早报） | 手机那半另算 |
| INB8 | +120 | Mac；手机那半是协议和向量 |
| INB9 | +300 | 只做用户不在场的运行 |

合计约 +2,200 / −850 产品行。§11 第 6 条的目标（本版净行数为负）要靠别的删除卡，本卡做不到净负。

## 风险与回退

- **风险 1：「直接生效」被当成「全部打开」。** 这是本卡最大的风险。今天会变成提案的五种情况，只要有一种被改成生效，网页里的一句话就能变成 Arslan 的做法或「关于你」的记忆。
  - 测试逐种断言；
  - 审查按 effort=max，加 Codex；
  - INB1、INB2 单独合，不跟界面的 PR 混在一起。
- **风险 2：东西挪丢了。** 例如「你不在时没做的」里，「总是允许」那一份没挪过去。
  - 按五块逐块验收；
  - INB4 在 INB3 之后合。
- **风险 3：「要你做」几处数得不一样。** 只有一个函数，测试断言角标、简报、手机三处相等。
- **风险 4：推送少了，用户错过要紧的事。**
  - INB8 合并前给用户看「弹 / 不弹」那张表；
  - 回退只改那张映射表。
- **旧路径：**
  - 「待整理」写 `DELETE-BY: v0.1.65`（记忆文件化时并入）；
  - 手机端在 Bridge 帧点头前发旧值（`done`）这条兼容，写 `DELETE-BY: v0.1.65 if the Bridge frame change is approved`；
  - 别的不留旧路径。
- **回退：**
  - 每个 PR 单独 revert。
  - INB4 revert 会把收件箱整个带回来，而且要在 INB5、INB7 之前 revert（它们读同一个函数）。
  - INB1、INB2 revert 后回到「等你确认」，数据不受影响：本卡不改任何旧行。

## 开工前要用户定的

1. **Bridge 帧（跟快问、能力卡、子会话一起问一次）：**
   - `conversations.result` 的 `state` 加 `done_unseen`；
   - `status.snapshot` 加四行简报和「要你做」（iPhone 快问输入框下面显示）；
   - `notify=1` 的范围改成只提醒「要你做」的。今天最终回复和后台任务结束都会提醒，改了以后手机上「做完了」不再响。
   三样都可以顺延，不挡 Mac 端。
2. **Mac 上「做完」的通知也不弹了**，可以吗？（第 5 条照字面就是这样，但跟今天差别大。）免打扰时段里，要批准的卡弹不弹？
3. **敏感关键词补「家人」一类：** 词表由 ⓪Plan 在 PR 里列出、用户过目。还有别的类别要补吗？
4. **验收单 v0.1.64 只给用户不在场的运行**（后台、定时、子会话）。用户在场的回合放到以后、带跑分数字再做（⓪Plan 的建议）。
5. **定时任务的「做完的样子」：** 每次运行开头写（不要迁移），还是建任务时写好存下来（要加列）？⓪Plan 建议前者。
6. **早报（设置里的开关）删掉，**由进展页的四行简报取代。
7. **四行简报 v0.1.64 先用模板句，不调模型**（⓪Plan 的建议）。
8. **学到的做法连续失败几次停用：** ⓪Plan 建议 3 次，跟定时任务一样。
9. **INB 由谁做：** ②Main 卡太多，要不要另开一个会话分走 INB3–INB9（INB1、INB2 留在 ②Main）。
