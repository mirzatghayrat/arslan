# INB 收件箱拆掉，东西回到各自的地方；加「进展」页的四行简报

> ⓪Plan 2026-10-29 夜间起草，用户 10-28 已定分级。v0.1.64 计划（#434）由用户点合并后才开工。

| 项 | 内容 |
|---|---|
| 道 | ②Main（⓪Plan 的建议；②Main 卡太多时可以另开一个会话分走 INB3–INB9） |
| 版本 | v0.1.64 |
| 分级 | 必须（⓪Plan 建议，用户定） |
| 依赖 | **S64-0**（堵外部内容那道闸的漏洞，不归本卡，见下）先合。文案跟 ACM（卡片界面与文案大合并，领先路线里叫 D1）对齐，但不并进 ACM、不等 ACM 合并。SUB：子会话的父链接、子会话的验收单。Q1：iPhone 快问输入框，四行简报挂在它下面。Bridge 帧的一次性决定（v0.1.64 README §2 第 3 条） |
| 合并位置 | S64-0 → INB1 → INB2（安全面，先合；INB2 是放宽，必须在 S64-0 和 INB1 之后）→ INB3 → INB4 → INB5 → INB6 → INB7 → INB8 → INB9。手机那半（INB4、INB7、INB8 里标了「手机」的部分）等 Bridge 帧点头，可以顺延，不挡 Mac 端 |
| 推动的门槛 | R64「用户验收：收件箱改完后用户一天的使用感受」；R64 安全（碰安全面的 PR 都有 effort=max 审查 + Codex 审查）；§11「换掉就删掉」（收件箱的代码本版删完） |
| 分支 | `claude/0164-inb1-lessons-direct`、`claude/0164-inb2-memory-direct`、`claude/0164-inb3-scheduled-entry`、`claude/0164-inb4-sidebar-dots`、`claude/0164-inb5-inbox-out`、`claude/0164-inb6-run-records`、`claude/0164-inb7-progress-brief`、`claude/0164-inb8-push`、`claude/0164-inb9-acceptance-sheet` |
| 迁移号 | INB4 要一个（已读标记）；INB2 可能要一个（每次运行记「读过外部内容」，见 INB2）。开工时向 ②Main 申请，其余 PR 不要迁移 |

## 目标

- **用户的原话：** 「看 Inbox 70 多条就头疼，agent 反而给我加了这么多活」。用户 10-28 逐条同意了八条（`docs/plans/0162/README.md` §8「收件箱怎么改，加『进展』页」）。本卡做 v0.1.64 那部分：第 1、2、5、6、7、8 条，第 3 条的基本入口，第 4 条的四行简报，加上先核每次运行记了什么。第 4 条的时间线和地图、第 3 条的外观，是界面版的事，不在本卡。
- **角标为什么满：** 角标是 `summary()` 的三项相加（`server/services/proactive_service.py:294-307` → `web/src/App.tsx:80`、`:633-634`）：没看过的主动提醒、等批的卡、记忆等你确认。最后一项 `_memory_waiting`（`proactive_service.py:310-321`）数的是 `memory_proposals` 里所有 pending 的行，加上 `lessons` 里 `status="proposed"` 的行。所以先做第 6、7 条（INB1、INB2），角标就降下来了；其余按「东西挪到哪」拆。
- **收件箱今天有五块**（`web/src/components/proactive/ProactiveInbox.tsx`），每块都要有去处，不能丢：

| 今天在收件箱里的 | 来源 | 挪到哪 | PR |
|---|---|---|---|
| 现在就要你批准的卡 | `GET /approvals/pending`（`server/api/approvals.py:30-32`；`InboxApprovals.tsx:54`） | 对话里本来就有；灵动岛（`web/src/island/feed.ts:117`）和 iPhone 照旧能答。收件箱这一份删掉 | INB5 |
| 「你不在时没做的」 | `GET /approvals/refused`（`approvals.py:59-88`，`permission_store.refused_groups` `:165-182`） | 定时任务的（`decided_by=policy`）→ 定时任务入口里那个任务；后台任务和对话里的 → 那个对话。今天不是按对话分的，要先改接口（见下）。「总是允许」和撤销会建长期规则，规则怎么建不改 | INB3、INB5 |
| 记忆等你确认 | `InboxMemory.tsx` ← `web/src/lib/pendingMemory.ts:27-62`（三个来源） | Memory 页的「待整理」；学到的做法回「学到的做法」列表 | INB1、INB2 |
| 主动提醒 `proactive_items` | `proactive_service.py`；五种 `kind`（`server/db/models.py:1087`） | `job_followup` 带 `conversation_id` 和「接着做」（`proactive_service.py:344` `accept`）→ 那个对话；`scheduled_problem`、`web_change`、`folder_change` → 定时任务入口（第 3 条），沿用 `proactive_diagnosis` 的「猜测 + 下一步」；`brief` → 被进展页的四行简报取代 | INB3、INB5、INB7 |
| 侧栏的「在盯着」和静音 | `WatchesPanel.tsx`（静音列表也在这里管） | 定时任务入口 | INB3 |

  另外几样没有界面块、但要有去处：
  - `POST /proactive/scan`（「现在检查一下」）→ 定时任务入口；
  - `POST /proactive/items/seen` → 在新位置看到时标已读；
  - `/proactive/config` 已经在设置里（`web/src/components/settings/ProactiveSection.tsx:57-58`）；
  - 「待处理 / 放着的 / 已处理」三个标签页（`ProactiveInbox.tsx:20-23`、`:198-201`）**还没有去处**，见最后一节第 7 条。
- **名字陷阱：** `POST /phone/inbox`（`server/api/phone.py:261`）和工作区里的 `Inbox/iPhone/` 文件夹（`phone.py:235-237`）是 iPhone 发来的文件，跟收件箱无关，不删、不改名。

## 先核过的现状（⓪Plan 读 main `8db45ef9`；#434 的审查意见已逐条亲核）

- **侧边栏已经有状态图标。** 每个对话一个：在干活（进度环）、等你（琥珀色 !）、做完（绿勾）、没做成、停了、定时、Remote（`web/src/components/ConversationGlyph.tsx:9-45`）。状态来自 `GET /conversations` 的 `state`（`server/services/phone_reads.py:235-293`）：
  - `waiting` 取自灵动岛的等卡对话（`:271-272`）；
  - `working` 取自运行中的任务（`:273-274`）；
  - 其余按最后结果（`:276-280`）。**普通聊天没有 `job_outcome`，所以永远是 `idle`，不是 `done`**；`idle` 的聊天画成普通对话图标（`ConversationGlyph.tsx:12`）。
  缺的是：「做完未看」、普通聊天回合的「做完」怎么算、项目一级的点、角标按「几个对话在等」数。
- **定时任务现在在「Activity」页里**（`web/src/components/ActivityView.tsx:98` 的 `ScheduledTasksCard`），能看每次运行（`GET /scheduled-tasks/{id}/runs`，`server/api/scheduled_tasks.py:267`）。
- **「你不在时没做的」不是按对话分的：**
  - `refused_groups` 按（种类、目标、谁拒的）跨对话合成一组（`server/services/permission_store.py:173-180`）；
  - 一组带的 `conversation_id` 只是最新那一行的（`server/api/approvals.py:76-81`）；
  - 所以按对话过滤必须在合组**之前**做；
  - 前端写死了 `?hours=24`（`web/src/components/proactive/InboxRefused.tsx:77`），不能原样复用；
  - 这些行**没有「处理过」的状态**：只会过期（`hours`），或者被一条「总是」规则盖住时消失（`approvals.py:78-79`）。
- **学到的做法（第 6 条）今天在哪几处变成「等你确认」**（`server/services/lessons.py`）：
  1. 设置「学到的做法直接生效」关着（`:265-266`；默认开，`settings_service.py:247-252`）；
  2. 这一轮读过外部内容，而且不是用户亲口纠正（`:277`，就是 README 说的那道闸）；
  3. 判断模型没给答案，而来源是用户纠正（`:275` 放行、`:277` 的 `bool(worth)` 让它不生效）；
  4. L1：纠正不是在回应 Arslan 之前做的事，或者跟这一轮刚走通的路线相反（`:278-284`）；
  5. 跟已有的一条冲突，又不是用户纠正盖掉旧的（`:309-314`）。
  另外：`stale` 状态在表约束里有（`models.py:874` 的 `ck_lesson_status`），但**没有任何代码把一条做法设成 `stale`**；`failed` 只是累计数（`lessons.py:382-396`），不是「连续失败」。第 6 条的「连续失败就自动停用」是新做的。
- **关于你的记忆（第 7 条），README 的说法要改正：**
  - 今天「关于你」的记忆只有两条路直接生效：
    - 用户这句话明确说了「记住」（宿主的显式保存，摘要要对上，`arslan/companion/memory.py:124-128`）；
    - 事实提取器（`server/services/turn_facts.py:93-108`）。它**只读用户自己的消息**，按构造就碰不到网页和文件，不靠 `external_seen`。
  - 用 `external_seen` 的只有 Arslan 自己的笔记（`server/services/memory_tools_v2.py:137` → `memory.py:137-139` 的 `own_note`）。
  - 所以第 7 条其实是**放宽**：模型通过 `remember`、`memory_note` 写的「关于你」，今天没有「记住」二字就是提案（`memory.py:140-153` 落到 `proposed`，`memory_repository.py:231-232`、`:238-248` 建一条 `memory_v2` 提案）。
  - 敏感的今天不是「当场问一句」，是要用户在表单里确认（`memory.py:129-130`，`sensitive_acknowledged` 只有 `origin=="user"` 才算）。关键词表（`memory.py:118-121`）有健康、钱、证件、住址，**没有家人**。
  - **只有提取器发 `memory_proposed` 帧**（`turn_facts.py:137-140`）；`remember`、`memory_note` 不发任何帧（`memory_tools_v2.py` 里没有 `emit`）。
  - README 说「跟现有的敏感记忆规则（#239）对上」。#239 是**读**这一侧：专家 / 子任务的回忆永远拿不到敏感记忆（`server/services/personal_context.py:323-325`）。**写**这一侧的规则在 `decide_write`（`memory.py:113-130`）。两边都要留。
  - 精简方案早就定了「记忆提案不再推给用户审，需要确认的敏感记忆照旧问」（`docs/plans/2026-10-17-0162-reduce-proposal.md:109`），代码没跟上：`_memory_waiting` 照数，`InboxMemory` 照列。
- **外部内容那道闸的漏洞，归 S64-0（③Hands 审 #434 时提的，⓪Plan 另立一张卡，不归 INB）：** 四件事：
  1. `delegate_work`：帮手会读网页，但工具结果写的是 `"external": False`（`server/services/task_workers.py:268`），它也不在 `_OUTSIDE_TOOLS` 里（`server/orchestrator/untrusted.py:72-73`），所以 `tool_loop.py:375-377` 不会把这一轮标成「读过外部内容」（⓪Plan 已亲核）；
  2. 后台任务开头的标记是「没读过」（③Hands 提的，本卡没复核）；
  3. 学到的做法合并的口子：`lessons.py:296-304` 新条合并进一条旧的 `proposed` 时，只要新条能生效，就把旧条整条打开，而旧条的文字可能来自读过外部内容的那一轮（只有用户纠正才会用新文字覆盖，`:301-302`）。修法：用干净那一轮的文字覆盖，再生效（⓪Plan 已亲核）；
  4. 用户点「接着做」恢复的回合（`server/services/task_service.py:1088-1110`）把上一次的进度当外部数据放进提示（`wrap_external`），但新回合的标记从「没读过」开始（`untrusted.py:92-94`，`tool_loop.py:2812`）；`task_progress` 读回来的旧进度也一样（③Hands 提的，`task_progress` 那半本卡没复核）。
  INB1、INB2 只靠 S64-0 修好的这道闸，自己不再修。
- **停下来的任务：**
  - 后台任务的 `job_followup` 提醒带 `conversation_id`（`models.py:1098`）。
  - 被重启打断的后台任务：开机时先被标成 `waiting_user / process_interrupted`（`server/services/task_repository.py:495-496`，由 `task_service.recover_interrupted` 调），接着 `background_jobs.report_interrupted`（`server/main.py:385-387`）把它**取消**。取消写的原因是 `pause_reason="user_cancelled"`（`task_repository.py:322-323`），再往原对话写一条 `job_outcome="interrupted"` 的消息（`server/services/background_jobs.py:421-425`）。
  - 结果是：库里看起来像「用户自己取消的」；`describe()` 的结果对照表里也没有 `interrupted`（`phone_reads.py:278-280`），那个对话显示成 `idle`。
- **验收引擎：** `AcceptanceCheck`（`arslan/companion/contracts.py:110-125`，三种评判：确定性 / 人 / 模型；关键项不许只靠模型）。
  - 聊天回合只用默认的「回答发出去了」（`task_service.py:1014` 的 `_acceptance or [ANSWER_DELIVERED]`，`:1028` 的 `_answer_only`）。
  - 后台任务有自己的验收项，由 `criteria_to_acceptance` 生成（`background_jobs.py:69-97`）。
- **推送今天推什么：**
  - **Mac 原生通知**（`desktop/src-tauri/src/resident.rs:127-145`）：回合做完（ok）、需要注意、要批准、定时任务完成 / 失败 / 暂停、主动提醒。
    - `lesson_learned` 不弹：映射表里没有它，落到 `:138` 返回 None；`server/services/desktop_status.py:28` 也写明它是安静的。
    - 主动提醒只有 `web_change`、`folder_change`、`brief` 三种会弹（`arslan/proactive_policy.py:35`）。任务和定时任务的问题不弹，因为任务或运行结束时已经弹过（`:33-34` 的注释）。
    - 弹的那条事件**不带是哪一种**：`desktop_status.push("proactive", outcome="ok")`（`proactive_service.py:151`），`resident.rs:137` 一律用同一句话。点开到 `@inbox`（`resident.rs:158-162`）。
    - 免打扰时段只管主动提醒（`proactive_policy.py:157-161`），不管别的通知。
  - **iPhone：**
    - `notify=1` 的有：最终回复、报错、后台任务结束（done/partial/stuck/stopped）、要批准、批准失败或过期、设备被撤销（`docs/specs/mobile-bridge-protocol.md:228-230`，`spec/mobile-bridge/reference.py:196-205`）。
    - 手机端**没有收件箱帧**。
    - `conversations.result` 已经带 `state`（协议 `:303-304`）。
- **简报：** 今天的早报 `build_brief`（`proactive_service.py:157-185`）不调模型，但「在跑的」读的是内存里的 `background_jobs._jobs`（`:168`），重启以后它是空的。被重启打断的任务又被记成「用户取消」（上面那条），所以「卡住」也数不到它们。
- **每次运行记了什么**（INB6 补）：
  - **有：**
    - `runs`：模型、token、耗时、状态、报错类型（`models.py:541-590`）；
    - `run_steps`：每次工具调用一行。`args_summary` 截到 200 字（`tool_loop.py:1397`），回答的 `output_preview` 截到 500 字（`server/services/run_recorder.py:252`）；
    - 改了哪些文件：S3 检查点的清单（`server/services/checkpoints.py:112` `manifest(run_id)`）；
    - 任务的预算快照和验收结果（`server/db/task_models.py:34`、`:36`），任务和运行的对应（`task_attempts.run_ids`，`:59`）；
    - 产出文件按运行列（`server/services/phone_reads.py:66-82`，`artifact_store.list_artifacts`）；
    - 花费的 token（`usage_ledger`，`models.py:922-944`）。
  - **缺：**
    - 读了哪些文件，没有单独的字段。只能从 `args_summary` 里猜，而且会被截断；
    - 定时任务每次运行记的 `run_id` 永远是 None（`server/services/scheduler.py:471`、`:479`），所以定时任务的运行点不开；
    - 子会话没有父链接（SUB 的迁移加）。
  - **没核：** 产出（`artifact_store`）是不是每种交付都进了清单。INB6 开工先核。
  - `server/api/runs.py` 的诊断接口只认 `kind=="live"`（`:281`、`:347`、`:386`、`:466`），这个问题 §8 已登记，归 INB6（见下）。

## 改哪些文件

按 PR 列。每个 PR 产品代码不超过约 800 行（测试、翻译不算）。

### S64-0（不归本卡，列在这里只为说清依赖）

③Hands 审 #434 时提的四个洞，⓪Plan 另立 S64-0，由 INB 以外的会话做：`delegate_work`、后台任务开头的标记、学到的做法合并的口子、`resume_turn` 和 `task_progress`。INB1、INB2 都排在它后面。

### INB1 学到的做法直接生效（第 6 条）· 安全面 · effort=max

- `server/services/lessons.py`
  - 「直接生效」只去掉「等用户点头」这一步。今天会变成提案的五种情况（上面列的 1–5）**全部改成「没生效，但看得见」**，一条都不许变成生效。
  - DB 里的值仍用 `proposed`，界面上叫「没生效」。
  - **没生效的原因在发生时记进 `evidence`**（JSON，不要迁移）：设置关了 / 读过外部内容 / 判断没给答案 / 不像纠正 / 跟已有的冲突。
  - **旧行没有原因记录的，一律按「读过外部内容」算。** 不去猜，也不批量打开。
  - **连续失败自动停用：**
    - 在 `record_applied`（`:382-396`）里：用了这条做法而这一轮失败，`evidence["fail_streak"]` +1，成功清零；
    - 连续 3 次就设成 `stale`，写明原因。3 次跟定时任务「连续 3 次失败自动暂停」同一个数（`models.py:952`）；
    - `recall`（`:336` 起）本来就只取 `active`。
- `server/services/proactive_service.py:317-319`：`_memory_waiting` 不再数 `proposed` 的做法。
- `web/src/lib/pendingMemory.ts:53-60`：不再把做法放进「等你确认」。
- `web/src/components/LearnedLine.tsx`：对话里那一行不再问「记住 / 不用」（`:23-25`）。
  - 生效的照旧「学到了… [撤销]」；
  - 没生效的写「学到一条，没生效：<原因>」，加「在 Memory 里看」。
- **Memory 页「学到的做法」列表**（`web/src/components/companion/MemoryList.tsx` 里列做法的那块，开工时定位）：
  - 显示没生效、已停用，各带原因；
  - 能删（`server/api/lessons.py:61-69`）；
  - 手动打开前，**先显示全文和它没生效的原因**，用户看完再点打开（`lessons.py:50-53` 已有接口）。
- **测试（只管做法这一侧，闸本身的测试在 S64-0）：**
  - 五种情况各一条，断言是 `proposed`、原因对；
  - 没有原因记录的旧行按外部内容算；
  - 读过外部内容的做法不生效，在 Memory 页列出；
  - 手动打开要先给出全文和原因；
  - 连续 3 次失败 → `stale`，不再被回忆；
  - 角标不再数做法。

### INB2 关于你的记忆直接记下（第 7 条）· 安全面 · effort=max · 放宽，排在 S64-0 和 INB1 之后

- **直接生效的条件**（`arslan/companion/memory.py` `decide_write`，`:97-153`），全都要满足：
  - **用户在场，用白名单：** 只有这两种回合算——窗口的 `user_message`（`server/ws/arslan.py:561` 起）和 iPhone 的 `chat.send`（协议 `:246`）发起的回合。在回合开始时记下来，放进 `MemoryActor`。
    - 不用「排除后台任务」这种黑名单：以后新加的入口（快问、旁聊……）会漏进来。
    - 新入口要算「在场」，必须改白名单，并且单独审。
  - **整段对话里没读过外部内容：**
    - 每一轮结束时，把这一轮读没读过外部内容记在那次运行上。用 `runs` 新加一列（要一个迁移号），还是放进已有的 JSON 字段，开工时 ②Main 定。
    - 写「关于你」之前查：这个对话读过外部内容（至少是还留在上下文里的那几轮读过），就不直接写。
    - 只看当前这一轮的标记不够：第 N 轮读了网页，第 N+1 轮写「关于你」，今天的标记已经回到「没读过」。
    - **没有记录的运行一律当读过外部内容**（③Hands 复审 #434）：被重启打断、出错退出的运行走不到「结束时」，INB2 之前的旧运行也没有记录；规矩和 INB1 处理旧行一样。能做到的话，在标记变成「读过」的那一刻就写进去（发生时就记），不等回合结束。
    - 查「整段对话」时，后台任务在这段对话里的运行也要算进去：它的结果是写进这段对话的。
  - **普通敏感度：** 关键词检查之后仍是 `normal`。
  - **不带风格参考**（`:133-134` 照旧）。
- **原样保留：**
  - `no_learning`、`temporary` 拒绝写（`:100-101`）；
  - 钥匙不进记忆（`:102-104`）；
  - 任务范围不进长期记忆（`:105-106`）；
  - 范围检查（`:107-112`）；
  - 云端用不用照 `cloud_memory_allowed`，否则 `local_only`（`:141-147`）；
  - `supersede`（改已有的一条）照旧是提案：改已确认的文字要用户看新旧两版（`memory_tools_v2.py:79-81` 的注释）。
- **不满足的：** 仍落成 `proposed`，加一条 `memory_v2` 提案（`memory_repository.py:231-232`）。
  - 提案的 `reason` 写清楚：`external_seen` / `not_present` / `sensitive`；
  - **不进任何队列，不进角标**，只在 Memory 页「待整理」里看得见。
- `server/services/memory_tools_v2.py`：`remember`（`:46-95`）和 `memory_note` 的 `about_you`（`:112-170`）把上面的条件交给 `decide_write`。
- **敏感的「当场问一句」：**
  - 关键词表（`memory.py:118-121`）补上家人一类（中英文：家人、家属、孩子、父母、配偶、family 等）。具体词表在 PR 里列出，⓪Plan 审；只加不删。
  - **要新加一个窗口帧**（socket 帧，不是 Bridge 帧）：`remember`、`memory_note` 今天不发帧。提取器那条路（`turn_facts.py:137-140`）的 `memory_proposed` 也加上字段。帧里带提案的 id、版本和原文。
  - 对话里那一行（`web/src/components/RememberedLine.tsx:50-53`，今天是「想记住… [去 Memory 看]」）改成两个按钮：「记住（只在本机用）」「不用」。
    - 按钮绑定**那一条提案的 id、版本和原文**；
    - 答的走现有的 `POST /memory/proposals/{id}/resolve`，`sensitive_acknowledged=true`、`use_policy=local_only`（跟今天收件箱里的「记住」一样，`pendingMemory.ts:39`）；
    - 版本对不上就失败（`memory_repository.py:318` 已有）。
  - 没答的就留在「待整理」，不再问第二次，不推送，不进角标。
- **旧提案挪到「待整理」（不删用户数据）：**
  - Memory 页顶部现在就有「等你确认」（`MemoryList.tsx:356-383`）。改名「待整理」，默认收起，只在 Memory 页里显示件数。
  - 里面放：
    - 旧的 `memory_v2` 提案（`server/api/companion.py:386-395`）；
    - 整理建议（`kind != "memory_v2"`，`server/api/brain.py:650-670`）；
    - INB2 以后新落下的，按 `reason` 分组，跟旧的分得开。
  - **不动任何一行：**
    - 不改状态、不批量接受、不删；
    - 「记住 / 不用」照旧能逐条点；
    - `/memory/noticed-earlier` 的「全部采用」（`companion.py:398-430`）照旧。
  - v0.1.65 记忆文件化时并进去。代码注释写 `DELETE-BY: v0.1.65 when memory files land (the 待整理 rows are merged into them)`。
- `server/services/proactive_service.py:310-321`：`_memory_waiting` 整个删掉，`summary()` 里的 `memory` 字段同时删，`App.tsx:633` 跟着改。
- **测试：**
  - 白名单里的回合、整段对话没读过外部内容、普通 → 生效；
  - **第 N 轮读了网页、第 N+1 轮写「关于你」→ 不生效**；
  - 白名单以外的回合（后台、定时、子会话，以及一个假装的新入口）→ 不生效；
  - 敏感（含「家人」）→ 不生效，对话里的按钮只能答那一条，版本变了就失败；
  - `supersede` 仍是提案；`no_learning`、`temporary` 照旧拒绝；
  - 角标不再数记忆；
  - 旧提案一条不少、状态不变。

### INB3 定时任务单独一个入口（第 3 条的基本版）

- `web/src/lib/sections.ts:14-22` 加 `scheduled`；侧边栏（`web/src/components/Sidebar.tsx`）加一项「定时任务」。外观先用现有样式。
- **新页面**（例如 `web/src/components/scheduled/ScheduledPage.tsx`）：
  - 每个定时任务一行，点进去看每次运行。`ScheduledTasksCard` 从 Activity 页（`ActivityView.tsx:98`）挪过来，不是复制；
  - 「盯网页、盯文件夹」也在这里，各一行，连同静音列表。`WatchesPanel` 设置页也在用（`ProactiveSection.tsx:5`、`:98`），组件保留，两处都引用；
  - 「现在检查一下」（`POST /proactive/scan`）放在这一页；
  - **标点：** 有下面任何一样，就在那一行上标点：
    - 一个任务的运行失败或被暂停；
    - 有它的 `scheduled_problem`（`source_key` 为 `sched:<id>`）；
    - 有它在用户不在时没能问的操作。
    网页、文件夹的变化（`web_change`、`folder_change`，`source_key` 为 `watch:<id>`）标在对应那一行，原来的「猜测 + 下一步」（`proactive_diagnosis`）照旧显示。
- **「你不在时没做的」按对话取：**
  - `server/services/permission_store.py:165-182` 的 `refused_groups` 加 `conversation_id` 参数，**在合组之前**过滤；
  - `server/api/approvals.py:59-88` 把它传下去；
  - 定时任务的对话 id 是 `task.conversation_id or f"scheduled-{id}"`（`scheduler.py:421`、`:449`）。定时任务也可能写进一个普通对话，这时按 `decided_by=="policy"` 认作定时任务的那一份。
- `InboxRefused.tsx` 改成接收 `conversationId` 和时长，不再写死 `?hours=24`（`:77`）。「总是允许」和撤销的做法不改。
- **测试：**
  - 任务、盯网页、静音都能在新页面找到；
  - 有问题的任务有点；
  - 两个对话里同一种拒绝，各自只看到自己的那一份（今天会合成一组）。

### INB4 侧边栏状态点：「做完未看」、项目一级、已读标记（第 2 条）

- **迁移（要一个号）：** 新表，例如 `conversation_seen(conversation_id, seen_message_id, seen_at)`。
  - 用新表，不往 `conversation_contexts` 加列，因为不是每个对话都有那一行（`server/services/task_context.py` 里 `row` 可能为 None）；
  - 定时任务的入口用同一张表记「上次打开」（键用 `scheduled-<id>`）。
- **先定义普通聊天的「做完」：** 今天普通聊天永远是 `idle`（`phone_reads.py:276-280`）。
  - ⓪Plan 建议：一轮聊天的最终回复发出去了、没报错，就算这一轮做完；
  - 比已读标记新，`state` 给新值 `done_unseen`；
  - 看过以后回到 `idle`，不是 `done`，这样看过的聊天图标跟今天一样。
  - 后台任务照旧：看过后是 `done`。
- `server/services/phone_reads.py:235-293` `describe()` 按上面算。窗口显示了最后一条就记已读；手机拉了 `chat.history` 也算已读。
- `web/src/lib/conversationMeta.ts:7`、`:21`，`ConversationGlyph.tsx`：加 `done_unseen` 的样子，先用现有样式，比如绿勾加一个小点。
- **项目一级：** 项目行上取它下面对话里最要紧的那个状态：等你 > 在干活 > 做完未看。
- **手机：** `done_unseen` 是 `conversations.result` 的新值。按 ①iOS 的意见（Q1 卡最后一节）：
  - 手机的 hello 里说了支持 `done_unseen`，才发给它；
  - 没说的就发旧值：普通聊天是 `idle`，后台任务是 `done`；
  - 协议 `:303-304` 和测试向量跟着改。**等 Bridge 帧点头。**
- **测试：**
  - 聊天回合做完 → `done_unseen` → 打开 → `idle`；后台任务 → `done`；
  - 重启后已读还在；
  - 项目取最要紧的那个；
  - hello 没说支持的手机收到旧值。

### INB5 去掉收件箱列表；停下来的任务和确认卡回到对话（第 1 条、第 8 条前半）

- **先抽出来再删：** `ProactiveInbox.tsx` 里有两块要搬进共用组件，对话和定时任务页都用：
  - 提醒卡：诊断、「先放着 / 不用了 / 静音」几个菜单（`:42-95`）；
  - 「接着做」的流程：检查有没有配模型，没有就带去模型设置（`:145-160`）。
- **对话那边：**
  - 打开一个对话时，顶部列出这个对话里「你不在时没做的」：后台任务和聊天回合的那份，`decided_by=="away"`，用 INB3 改好的接口；
  - 这个对话的 `job_followup` 显示成一张卡（用抽出来的提醒卡），带「接着做」「先放着」「不用了」；
  - 确认卡本来就在对话里；灵动岛和 iPhone 照旧能答。
- **「你不在时没做的」什么时候算处理过：** 今天这些行没有处理状态。⓪Plan 建议用 INB4 的已读标记：比用户上次打开那个对话（或那个定时任务）新的，才算「在等你」；打开看过就不再进角标，行本身照旧列着，照旧会过期。另一种做法是加一个「处理过」标记（要动 `approval_events`），见最后一节。
- **角标：** `summary()`（`proactive_service.py:294-307`）换成「几个对话、项目或定时任务在等你」，不是条数。
  - 一个对话算「在等你」，满足任何一样就算：
    - 有等批的卡；
    - 有比上次打开新的「没做的」；
    - 有 `job_followup`；
    - 有 👀 项（INB9 以后）。
  - 定时任务算：有标点的。
  - 跟 INB7 的「要你做」**用同一个函数**（例如 `server/services/progress.py` 的 `waiting_on_user()`），不许两处各算各的。
- **删掉（§11，本 PR 内，`git grep` 查不到为证）：**
  - `web/src/components/proactive/ProactiveInbox.tsx`、`InboxApprovals.tsx`、`InboxMemory.tsx`；
  - `AskForFrame.tsx`：产品代码里只有 `InboxApprovals` 引用它，PR 里贴 `git grep -w` 结果；
  - `sections.ts` 里的 `inbox`，`Sidebar.tsx:139-142` 的收件箱项，`App.tsx` 的收件箱分支：
    - `:57` 的导入；
    - `:127` 的通知目标；
    - `:607` 的 `openInboxConversation`，只给收件箱用，删掉；
    - `:633-634` 的角标；
    - `:803` 的页面；
  - `web/src/hooks/useProactiveSummary.ts`，换成新的计数；
  - `web/src/lib/openConversation.ts:11-17` 的 `@inbox`，`resident.rs:158-162` 的 `@inbox`（和 `:815-826` 的测试）：改成到对话或进展页（`@progress`）；
  - 6 种语言里只给收件箱用的 key（`inbox.*`，`proactive.page.*` 中只有收件箱用的）。
  - **保留：**
    - `InboxRefused.tsx`（INB3 改过，换个名字放到共用目录）；
    - `GET /proactive/items` 和 accept / snooze / dismiss：对话和定时任务页还要用。
- **测试：**
  - **改，不删：** `web/src/__tests__/card-v2.test.tsx:11`、`s1b-schedule-prompt.test.tsx:7`（这两个导入 `AskForFrame`）、`hands-card-copy.test.tsx:249`（导入 `InboxApprovals`），改成测对话里的同一张卡；
  - `inbox-*.test.tsx`、`proactive-inbox.test.tsx` 测的组件删了，测试跟着删，但里面保护行为的断言要搬到新位置的测试里，PR 里逐条列出搬到哪；
  - 新加：
    - 每一块都能在新位置找到（五块各一条）；
    - 同一对话三条也只算 1；
    - 看过的「没做的」不进角标；
    - `@inbox` 查不到。

### INB6 先核每次运行的记录，缺的补上（第 4 条的数据部分）

- 先核，结果写进 PR：读改了哪些文件、跑了哪些命令、花费、产出、子会话，每样各在哪、缺什么。上面「每次运行记了什么」是 ⓪Plan 的初核。
- **补：**
  - `server/services/scheduler.py:471`、`:479`：记下真的 `run_id`。`scheduled_task_runs.run_id` 列本来就有（`models.py:992`），不要迁移；
  - **读了哪些文件：** `read_file`、`search_files` 的完整路径写进那一步的 `run_steps.detail`（JSON，不要迁移），不再靠截断的 `args_summary` 去猜；
  - **产出：** 核过有缺再补。
- **`runs.py` 只认 `live`**（`:281`、`:347`、`:386`、`:466`）：
  - 进展页数后台任务和定时任务的运行，要按运行的种类数（v0.1.63 #421 的 `run_kinds.py` 那套）；
  - 进展页用到的接口在本 PR 改；
  - 没用到的四个诊断接口改不改，开工时 ②Main 看用的人多不多再定，写进 PR。
- **子会话的父链接：** 不在本卡，用 SUB 的迁移（v0.1.64 README §6「Q1 + SUB」）。
- **测试：**
  - 定时任务的运行能点开；
  - 读文件的那一步有完整路径；
  - 后台任务和定时任务的运行都被数到。

### INB7 进展页：最上面四行简报（第 4 条的简报）

- Activity 页改名「进展」，不删（用户点名要）。导航 key 换名，6 种语言同一个 PR。
- **`server/services/progress.py`（新）：四个数都从记录里取。**
  - **做完：** 今天做完的对话和定时任务运行。
  - **在做：** `companion_tasks.phase` 是 `queued` / `running` / `verifying` 的，加上正在跑的回合。
  - **卡住，下面任何一样：**
    - 没做成、停了；
    - `waiting_user`，但不是在等用户回答；
    - 被重启打断的；
    - 暂停的定时任务。
  - **要你做：** INB5 那个函数。
  - 单位跟角标一样，按对话、项目、定时任务数，不按条数。
  - 每一项都带能点开的列表（对话 id 或任务 id）。
  - 侧边栏「进展」的角标 = 要你做的件数，跟 INB5 是同一个数。
- **被重启打断的，在发生时写下自己的原因：**
  - `background_jobs.report_interrupted`（`background_jobs.py:398-425`）今天用 `repo.cancel`，写的是 `user_cancelled`（`task_repository.py:322-323`）。改成写 `process_interrupted` 这类原因，例如给 `cancel` 加一个原因参数；
  - `describe()` 的对照表（`phone_reads.py:278-280`）加上 `interrupted` → `unfinished`；
  - 不在事后从消息里倒推。
- **不用内存里的 `_jobs`：** 「在做」读持久化的 `companion_tasks`。
- **模型只负责写成人话，不许报数：**
  - v0.1.64 先用模板句，不调模型、零花费（⓪Plan 的建议）。
  - 以后要让模型润色：把数字和列表当参数传进去，并检查模型回来的句子里每个数字都和记录一致，不一致就退回模板。
- **早报换掉（§11）：** 同一个 PR 删掉：
  - 早报 `build_brief`（`proactive_service.py:157-185`）和 `kind=="brief"` 的提醒；
  - `proactive_policy.py` 里 brief 那一种（`:32`、`:35`、`:49`、`:51`、`:77-78`、`:173-176`）；
  - 设置里早报的开关（`ProactiveSection.tsx:91-93`，`SettingsScreen.tsx:270` 的 `only={['looking', 'brief']}`）。
  四行简报就是这一页的开头，打开就是最新的，没有谁「发」简报。
- **在任何对话里问「进展怎么样」：** 给模型一个只读工具，返回同一份数据，不另算。工具说明要短，按 K 线的工具按需规则挂。
- **手机：** iPhone 快问输入框下面显示「要你做」的几件和四行简报，例如在 `status.snapshot` 加一个可选的 `brief` 字段。**等 Bridge 帧点头，可以顺延**；Mac 端不等。
- **测试：**
  - 每个数和手工从库里数的一致，含重启以后：被打断的进「卡住」；
  - 同一个对话三件事只算 1；
  - 早报的代码查不到；
  - 模板句里没有不来自记录的数字。

### INB8 推送只推「要你做」的（第 5 条）

> **用户 10-28：** Bridge 帧照 ①iOS 的建议定了，但这一条会改变所有手机（含旧版）收到的推送，**单独问用户，还没定**。定之前 INB8 不开工；INB1–INB7、INB9 不等它。

- **主动提醒的通知事件带上种类：** `proactive_service.py:151` 推的事件加上提醒的 `kind`，`resident.rs:137` 按种类用不同的话。
- **Mac**（`resident.rs:127-145`）：
  - **只弹：**
    - 要批准；
    - 需要你看：`turn_finished` 的 `error` / `needs_review`；
    - 定时任务失败 / 暂停；
    - 有 👀 项的验收单；
    - `job_followup`。这是**新加的通知**：今天它不弹（`proactive_policy.py:35`），而它的「接着做」要用户点。
  - **不再弹：**
    - 做完：`notify_done`、`notify_scheduled_done`；
    - 网页、文件夹变化（今天会弹）；
    - 早报（INB7 删了）。
  - 点开到那个对话或进展页（INB5 已换掉 `@inbox`）。
- **免打扰：** 今天只管主动提醒（`proactive_policy.py:157-161`）。改成管所有原生通知：服务端在状态里给一个「现在是不是免打扰时段」，`resident.rs` 照它办。
  - 免打扰不影响角标和进展页。
  - 要批准的卡在免打扰时段弹不弹，要用户定（见最后一节）。
- **手机：**
  - `notify=1` 的范围要跟着改：协议 `:228-230`、`reference.py:196-205`，`make_vectors.py` 重新生成向量。今天最终回复和后台任务结束都会提醒。
  - 这是协议改动。①iOS 要求**单独问用户一次**，不跟别的帧改动捆在一起。可以顺延。
- **测试：**
  - 每种事件弹不弹的一张表；
  - `job_followup` 会弹，网页变化不弹；
  - 免打扰时段不弹；
  - 点开的目标对。

### INB9 验收单留在对话或项目里（第 8 条后半）

- **⓪Plan 的建议：v0.1.64 只给用户不在场的运行出验收单**：后台任务、定时任务、子会话。
  - 用户在场的聊天回合以后再做，到时要带跑分前后对比（M64）。
  - 原因：每个回合都多出一张单，就改了每个回合。今天聊天回合只看回答发没发出去（`task_service.py:1014`、`:1028`），K 线的跑分要重测。
- **动手前写出「做完的样子」：**
  - 后台任务已经有自己的验收项（`background_jobs.py:69-97`）。
  - 定时任务今天走 `run_turn`，没给 `_acceptance`（`scheduler.py:466` → `task_service.py:987`）。
    - ⓪Plan 建议：每次运行开头由模型写出验收项，写进任务说明（`TaskSpec.acceptance`），不加列、不要迁移。
    - 另一种做法是建任务时写好存下来（要加列）。用户可以改。
  - 子会话的等 SUB。
- **做完给三栏：**
  - ✅ 我验过的：确定性检查通过，附证据，比如文件路径、命令结果；
  - 👀 要你看一眼的：评判是「人」的，最多一两项，多的放进 ⚠️ 并写明；
  - ⚠️ 没验到的：没跑、失败、只有模型说过的。
  - 数据取 `companion_tasks.results` 和 `AcceptanceCheck.evaluator`（`contracts.py:113`）。
  - 发进那个对话或项目，写一条消息，像 `background_jobs.py:423-425` 那样。验收单不进收件箱，也没有收件箱了。
- 👀 项算进「要你做」（INB5 的函数），也会推送（INB8）。
- **测试：**
  - 三栏各有来源；
  - 只靠模型的不进 ✅（`contracts.py:117-125` 的规则）；
  - 用户在场的回合没有验收单；
  - 👀 进了角标。

## 不许碰

- 外部内容那道闸本身：归 S64-0，本卡不改。本卡只许读它。
- `decide_write` 里上面「原样保留」列的几条；#239 的回忆规则（读的一侧）。
- 「总是允许」建规则的方式（`POST /permissions/rules {refused_id}`）和撤销：只搬位置、改取数的范围。
- 确认卡本身、灵动岛怎么答卡（`server/services/approvals.py:276` 的 `island_may_answer`）。
- Bridge 帧格式：没有用户点头，不改 `conversations.result` 的取值、`status.snapshot` 的字段、`notify` 的范围。这些在 INB4、INB7、INB8 里都是单独的一块，可以晚合。
- `/phone/inbox` 和 `Inbox/iPhone/` 文件夹。
- 记忆提案和整理建议的数据：不改状态、不删、不批量处理。
- 第 4 条的时间线和地图、第 3 条的外观：界面版的事。

## 怎么做（要点）

1. **INB1、INB2 先写会失败的测试：**
   - 今天会变成提案的每一种情况，以后都是「没生效」，一种都不许变成生效；
   - INB2 加「第 N 轮读网页、第 N+1 轮写」那条。
   测试先红，再改代码。
2. **INB1、INB2 按 effort=max 写和审，再加 Codex 审**（v0.1.64 README §1）。审查专门看：有没有哪条路能让「没生效」的东西被自动打开（合并、批量接受、旧数据、新入口算成「在场」）。
3. **每个挪走的东西先在新位置做出来，再删旧的**，但新旧在同一版里做完（§11 第 1 条）。INB5 的验收是「收件箱的代码查不到」，`git grep` 的结果贴进 PR。
4. **「要你做」只有一个函数：** 角标、进展页的简报、推送、手机都读它。
5. **文案：** 写法跟 ACM、STY 对齐（任务汇报那四条原则）。先写中英文，其余四种语言同一个 PR 补上（§3）。

## 验收

- **INB1 / INB2：**
  - 测试全过，effort=max 审查和 Codex 审查的结论写进 PR；
  - 角标里不再有记忆和做法；
  - Memory 页能看到每一条没生效的做法和记忆，以及没生效的原因。
- **INB5 合并后：**
  - `git grep -n "ProactiveInbox\|InboxApprovals\|InboxMemory\|@inbox\|useProactiveSummary\|openInboxConversation"` 没有结果；
  - 收件箱五块，每块都能在新位置找到（逐块截图）。
- **INB7：**
  - 四个数和手工从库里数的一致，含重启以后；
  - 页面上看不到不来自记录的数字。
- **用户验收（R64）：** 改完后用户用一天，看角标是不是只剩真要他做的。

## 量级

| PR | 产品代码（约） | 说明 |
|---|---|---|
| INB1 | +150 | 闸的修法移到 S64-0 后变小；测试约 +200 |
| INB2 | +350 | 白名单、按对话查外部内容、新窗口帧、待整理改名；可能带一个迁移；测试约 +300 |
| INB3 | +300 | 多半是挪组件；refused 接口按对话过滤 |
| INB4 | +200 | 一个迁移；手机那半另算 |
| INB5 | +300，删约 −504 | 删的是 `ProactiveInbox`、`InboxApprovals`、`InboxMemory`、`AskForFrame`、`useProactiveSummary`；`InboxRefused` 保留 |
| INB6 | +150 | 先核，可能更少 |
| INB7 | +350，删约 −70（早报） | 手机那半另算 |
| INB8 | +150 | Mac，含事件带种类；手机那半是协议和向量 |
| INB9 | +300 | 只做用户不在场的运行 |

合计约 +2,250 / −574 产品行。§11 第 6 条的目标（本版净行数为负）要靠别的删除卡，本卡做不到净负。

## 风险与回退

- **风险 1：「直接生效」被当成「全部打开」。** 这是本卡最大的风险。今天会变成提案的五种情况，只要有一种被改成生效，或者「在场」的白名单漏进一个新入口，网页里的一句话就能变成 Arslan 的做法或「关于你」的记忆。
  - 测试逐种断言；
  - 审查按 effort=max，加 Codex；
  - S64-0、INB1、INB2 单独合，不跟界面的 PR 混在一起。
- **风险 2：东西挪丢了。** 例如「你不在时没做的」按对话分以后，某一类（定时任务写进普通对话的那种）两边都不显示。
  - 按五块逐块验收；
  - INB5 在 INB3、INB4 之后合。
- **风险 3：「要你做」几处数得不一样。** 只有一个函数，测试断言角标、简报、手机三处相等。
- **风险 4：推送少了，用户错过要紧的事。**
  - INB8 合并前给用户看「弹 / 不弹」那张表；
  - 回退只改那张映射表。
- **旧路径：**
  - 「待整理」写 `DELETE-BY: v0.1.65`，记忆文件化时并入；
  - 手机端没在 hello 里说支持 `done_unseen` 时发旧值，这条兼容写 `DELETE-BY: v0.1.65 if every supported iPhone build says done_unseen in hello`；
  - 别的不留旧路径。
- **回退：**
  - 每个 PR 单独 revert。
  - INB5 revert 会把收件箱整个带回来，而且要在 INB7 之前 revert，因为它们读同一个函数。
  - INB1、INB2 revert 后回到「等你确认」，数据不受影响：本卡不改任何旧行（只往 `evidence` 和 `reason` 里加字段）。

## 开工前要用户定的

1. **Bridge 帧（跟快问、能力卡、子会话一起问一次）：**
   - `conversations.result` 的 `state` 加 `done_unseen`，只发给 hello 里说支持的手机；
   - `status.snapshot` 加四行简报和「要你做」，在 iPhone 快问输入框下面显示。
   两样都可以顺延，不挡 Mac 端。
2. **iPhone 提醒收窄（①iOS 要求单独问）：** `notify=1` 改成只提醒「要你做」的。今天最终回复和后台任务结束都会提醒；改了以后，手机上「做完了」不再响。
3. **Mac 上「做完」的通知也不弹了，**网页、文件夹变化也不弹了，可以吗？（第 5 条照字面就是这样，但跟今天差别大。）免打扰时段里，要批准的卡弹不弹？
4. **敏感关键词补「家人」一类：** 词表由 ⓪Plan 在 PR 里列出、用户过目。还有别的类别要补吗？
5. **验收单 v0.1.64 只给用户不在场的运行**（后台、定时、子会话）。用户在场的回合放到以后，带跑分数字再做（⓪Plan 的建议）。
6. **定时任务的「做完的样子」：** 每次运行开头写（不要迁移），还是建任务时写好存下来（要加列）？⓪Plan 建议前者。
7. **收件箱的「待处理 / 放着的 / 已处理」三个标签页去掉以后：** 放着的、处理过的提醒去哪看？⓪Plan 建议：定时任务页和对话里，每一行自己显示「放到哪天」或「已处理」，不再有单独的列表。
8. **「你不在时没做的」怎么算处理过：** 用「比上次打开新」（⓪Plan 的建议，不改账本表），还是在 `approval_events` 加一个「处理过」标记？
9. **早报（设置里的开关）删掉，**由进展页的四行简报取代。
10. **四行简报 v0.1.64 先用模板句，不调模型**（⓪Plan 的建议）。
11. **学到的做法连续失败几次停用：** ⓪Plan 建议 3 次，跟定时任务一样。
12. **INB 由谁做：** ②Main 卡太多，要不要另开一个会话分走 INB3–INB9（INB1、INB2 留在 ②Main）。
