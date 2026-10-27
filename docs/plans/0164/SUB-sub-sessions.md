# SUB 总指挥 + 子会话的底子（一个子 agent 工具做成子会话）

> 草稿（⓪Plan 2026-10-29 夜间起草），用户批准 v0.1.64 计划之前不开工。

| 项 | 内容 |
|---|---|
| 道 | ②Main（⓪Plan 的建议） |
| 版本 | v0.1.64 |
| 分级 | 应该（⓪Plan 的建议，用户定）。其中 SUB1 是安全修复，不跟着分级走 |
| 依赖 | SBX（沙箱默认拒绝，用户定的顺序：本卡排在它后面）；M64 的「拆开、分给子会话、汇总」题和反面题；Q1 的迁移（`kind` 列 + 父对话 id，两张卡共用，Q1 先申请）；手机上显示子会话要改 Bridge 帧，要用户点头 |
| 合并位置 | SUB1 不等 SBX，随时可合（修安全问题不受 §11 第 3 条限制）。SUB2 在 Q1 的迁移合了以后。SUB3–SUB5 叠着做，M64 的题在叠起来的最上面跑过了才一起合。SUB6 最后。改到 `tool_loop.py`、`arslan.py` 的，排在当时打开的 K 线 PR 后面 |
| 推动的门槛 | 领先路线 C 行「子 agent」落后 → 追平（`docs/plans/2026-10-17-0162-lead-roadmap.md:243`）；R64 的跑分（拆分派汇总题出数）；R64 的安全条（SUB1） |
| 分支 | `claude/0164-sub1-delegate-taint`、`claude/0164-sub2-sub-data`、`claude/0164-sub3-runner`、`claude/0164-sub4-report`、`claude/0164-sub5-lifecycle`、`claude/0164-sub6-delete-delegate` |
| 迁移号 | SUB2 不另要（用 Q1 那一次）。SUB6 删 `task_workers` 表要一个迁移：⓪Plan 建议并进 C7c 那一次迁移，C7c 已经合了就向 ②Main 申请下一个空号 |

## 目标

- 用户 10-27 定的分两步（`docs/plans/0162/README.md` §8「项目里的『总指挥 + 子会话』」）。本卡只做第一步，v0.1.64 的**底子**：
  - 一个主会话（总指挥）开出几个子会话分工干活，子会话在后台跑，做完向总指挥汇报；
  - 每个子会话都是一段真对话，能点开、能直接跟它说话；
  - 最多三层：总指挥 → 子会话 → sub-agent。最下层拿不到这个工具，执行时也拒；
  - 领先路线里「子 agent 统一成一个工具」就是它，不另做一套。
- **先证明模型会用：** M64 的「拆开、分给子会话、汇总」题和反面题（一步就能做完的不开子会话）过了，工具才合。
- **先补洞：** `delegate_work` 今天不传「读过外部内容」的标记。第一个 PR 先写测试证实，再修。
- **本卡不做：** 项目页的总指挥 / 子会话树、子会话对上关卡检查点、关卡条跟着动，都是 v0.1.65（README §8 同一条）。旁聊用同一套底子（`kind`、父对话 id、只继承的设置），但旁聊本身另开卡，而且用户还没确认它进 v0.1.64。
- **同一版里替换（sessions §11 第 1 条）：** 新工具上线的同一版删掉 `delegate_work` 和 `TaskWorker`（SUB6）。

### main 现状（⓪Plan 读 main `8db45ef9` 核过）

- **`delegate_work`：**
  - 一次最多 4 个帮手（`server/services/task_workers.py:45`），同时最多跑 2 个（`task_service.py:622` 的 `Semaphore(2)`，`task_workers.py:111`）；
  - 只能用 `web_search`、`web_extract`（`:27`、`:34`）；
  - 只在有 Task 的回合里能用：`:213-215` 在没有 Task、已经在帮手里、或在专家里时报 `worker_host_only`；工具也只在这时提供（`server/orchestrator/arslan.py:1118-1123`）。C3b 已经把它降成按需发（`arslan.py:1034`）；
  - 预算：`WorkerBrief` 带一个 `shared_budget_id=budget.id`（`task_workers.py:242`），但这只是个没人读的标签（`arslan/companion/contracts.py:203`）。帮手共用预算，是因为它们跑在父回合里，经 ContextVar 看到同一个内存里的 `Budget`（`arslan/execution_budget.py:283`）。每次运行的默认上限是 $2（`execution_budget.py:66`）。
- **标记的洞（SUB1 要证实的）：**
  - `delegate` 返回 `"external": False`（`task_workers.py:268`），所以 `tool_loop.py:373-374` 把帮手从网页得来的文字原样交给父回合，不加外部内容的框；
  - `counts_as_external` 没列它（`server/orchestrator/untrusted.py:72-73` 的名单、`:79-84` 的判断；README 写的是 `:72-79`，行号有一点漂移，内容一致）；
  - 每个帮手的 `run_native` 开一个自己的标记（`tool_loop.py:2812` 的 `track_turn()`），帮手读网页只标它自己的；结果里的 `external_seen`（`:2819`）`task_workers` 没读。父回合的标记一直是干净的，S2a-1 的断网卡（`tool_loop.py:1261`、`:1300`）和笔记的自动启用（`memory_tools_v2.py:137`）都不会触发。
  - 这些是读代码得出的，**没跑过**。
- **后台任务（子会话打算借用的运行器）：**
  - 全局最多同时跑 3 个（`background_jobs.py:27`）；每个任务在一个全新的 Context 里跑（`:162`），拿自己的预算（`:294-336` 的 `run_budget(tier, usd_cap)`）；
  - 确认卡走 `JobConfirmations`，广播给这段对话的所有连接，授权也按这段对话算（`approvals.py:409-417`）；
  - 结果推回：任务的最后一段话直接存成这段对话里的一条 Arslan 消息（`background_jobs.py:362-372`），不加框、不带标记；
  - 任务以 `done` 结束时，`job_finished` 给交到这段对话的检查点打勾（`background_jobs.py:266` → `project_evidence.py:268-296`）。
- **对话设置：** `ConversationContext` 有 `project_id`、`no_memory`、`no_learning`、`temporary`、`cloud_memory_allowed`、`allow_sensitive`（`server/db/companion_models.py:16-29`）；没有 `kind`，没有父对话 id。权限模式今天是一个全局设置（`permissions.py:575` 的 `_mode()` 读 `shell_confirm_policy`），不是按对话的。
- **学习和项目证据：**
  - 只有「Arslan 自己的回合」才学（`tool_loop.py:2857`）；帮手的 `actor="worker"` 不学（`task_workers.py:152`）。`lessons.after_turn` 遇到 `no_learning` 不学（`lessons.py:405`）；
  - 项目证据：后台任务的回合 `said=False`（`task_service.py:1036-1041`，按 `inside_job()` 判断），聊天回合 `said=True`（`project_evidence.py:300`）。
- **重启：** 开机时还在跑的帮手一律改成 `interrupted`（`task_repository.py:500-501`）；后台任务不跨重启（`background_jobs.py` 的 `report_interrupted`）。
- **花费的记录：** 运行的预算快照只在运行结束时写进 `runs.execution_budget`（`run_recorder.py:383-387`）。被重启打断的运行，它花的钱不在库里。

### README 和代码对不上的地方（⓪Plan 核）

1. **第 3 条「第二个动作回 409」：** `companion.py:256` 的 409 `conversation_running` 是**改对话设置**（`PUT /conversations/{id}/context`）时回的。聊天里第二条消息不回 409：它排队（`server/ws/arslan.py:225-241`），或者在下一个工具边界插进正在跑的回合（K9b，`:294-301`）。另外，后台任务的回合不拿这把锁，它和同一段对话里的聊天回合是并行的（0.1.42「边聊边干」）。所以「一段对话同时只跑一个回合」今天只对聊天成立。
2. **第 6 条「`parallel_reads.py:30-31` 已经让浏览器、桌面串行」：** 那两行是注释，意思是 `browser_*`、`desktop_*` 不进「可以并行的读」（`READS`，`:32-34`），只管**一个回合里**的一批调用。两个子会话是两个回合，中间没有任何锁。读网页用的浏览器是按对话开的（`browser_reader.py:57-63` 的 `ReaderSession(conversation_id, …)`），两个子会话会各开一个。
3. **README 没提的方向：标记往下也会丢。** 后台任务在全新的 Context 里跑（`background_jobs.py:162`），所以总指挥读过网页、再把网页里来的东西写进交代，子会话的回合照样从「干净」开始。新工具要往下也传。
4. **「像后台任务推回结果那样」不能照抄：** 后台任务的结果是不加框的 Arslan 消息（`background_jobs.py:362-372`）。子会话的汇报照这样推回，就和 `delegate_work` 是同一个洞。

## 改哪些文件

按 PR 列。产品代码的行数是 ⓪Plan 的估计，不含测试和翻译。

### SUB1 `delegate_work` 补上外部内容标记（S 线，安全；effort=max 写和审，Codex 审）

- `tests/server/test_task_workers.py`：**先写一个测试证实洞。** 假模型：帮手调一次 `web_extract`（假的成功结果，文字里带一个标记串），父回合调 `delegate_work`。断言：父回合的 `external_seen()` 是 True；交给父模型的那段工具结果在外部内容的框里。今天这两条都应该失败。
- `server/services/task_workers.py:268`：不再返回 `"external": False`。
- `server/orchestrator/untrusted.py`：`delegate_work` 进 `_WEB_TOOLS`（`:52`，按网页内容加框）和 `_OUTSIDE_TOOLS`（`:72-73`，算读过外部内容）。帮手只能用两个网页工具（`task_workers.py:27`），所以一律按外部算，不必逐个帮手去查。
- 量级：产品代码约 +3 / −1 行，测试约 +80 行。

### SUB2 子会话的数据：父对话、只继承的设置、列表里不出现

- **迁移：** 用 Q1 那一次（`conversation_contexts` 加 `kind` 和父对话 id）。`kind` 的取值 ⓪Plan 建议：`chat`（默认）、`quick`（Q1）、`sub`（本卡）、`side`（旁聊，先留着值，不用）。Q1 的迁移如果没带父对话 id，SUB2 自己带一个迁移，向 ②Main 申请号。
- `server/services/sub_sessions.py`（新）：
  - `create_child(parent_id, title)`：建子对话的 `ConversationContext`，从父对话复制 `project_id`、`no_memory`、`temporary`、`cloud_memory_allowed`、`allow_sensitive`，`no_learning` 一律 True（第 9 条）；
  - `depth(conversation_id)`：沿父对话往上数，最多数 3 步；
  - `children(parent_id)`、`tree(root_id)`：给后面几个 PR 用。
- `server/api/companion.py:250-300`（改对话设置）：子对话的设置不能比父对话松，松了回 422 `sub_session_inherits`。
- **列表默认不列 `sub`：** `server/api/conversations.py:33`（Mac 侧栏）、`server/api/projects.py:236`（项目的「对话」标签）、`server/api/phone.py:105`（Bridge 的 `conversations.result` 从这里取，见 `desktop/bridge/Sources/BridgeCore/ConversationLinks.swift:430`）、`server/api/phone.py:288`（`/phone/live`）。和 Q1 用同一个过滤函数（Q1 卡定名字）。`phone.py` 是 Bridge 契约文件：这里只改列出哪些对话，不改帧格式，但合并前告诉 ①iOS。
- 量级：产品代码约 +200 行（迁移不算，若要自带约 +40）。

### SUB3 子会话工具和运行器（叠着做，跑分过了才合）

- `server/services/sub_sessions.py`：`start(parent_id, title, brief, tools)`：
  - 查层数和数量（第 10 条），建子对话（SUB2），把交代存成子对话的第一条消息；
  - 用后台任务的运行器在子对话里跑（`background_jobs.start`，加一个 `parent_id` 参数）；
  - 确认卡发到**总指挥**那段对话的连接上（`JobConfirmations` 的 asker 换成父对话的），授权仍按子对话算（第 2 条）；
  - 交代里如果有总指挥读过的外部内容：总指挥这一回合 `external_seen()` 为 True 时，交代按外部内容加框，子会话的第一个回合一开始就带标记（上面「对不上」第 3 条）。
- `server/registry/task_tools.py`：新执行器，例如 `StartSubSessionExecutor`（工具名在本 PR 定，⓪Plan 建议 `start_sub_session`）。马上返回 `{ok, sub_session_id, status: "queued"}`，不等子会话做完。
- `server/orchestrator/arslan.py`（工具表，按需发那一组，`:1034` 一带）：总指挥和第一层子会话有这个工具；第二层没有。
- `server/orchestrator/tool_loop.py`：工具的参数 schema（照 `:2042` 一带 `delegate_work` 的写法）。
- **工具收窄（第 6 条）：** 子会话只给文件、命令、网页读取、`update_plan` 这一组；不给 Hands、桌面、托管浏览器的点击输入。照后台任务和快问的收窄写法（`arslan.py:721-728`）。
- **一棵树的花费上限：** 每次向模型发请求前查。已花的钱 = 树里每段对话在 `runs.execution_budget` 里的花费加总，加上正在跑的运行在内存里的 `Budget.usd`。每次运行自己的 $2 上限照旧，两个都查，先到哪个停哪个。树的上限默认值用户定（见文末）。
- 量级：产品代码约 +450 行。

### SUB4 汇报和总指挥的汇总回合（叠着做）

- `server/services/sub_sessions.py`：
  - 子会话结束（`done` / `partial` / `blocked` / `stopped` / `out_of_budget`）时，记下它的结果、改过的文件，还有它所有回合里有没有读过外部内容（`run_native` 结果里的 `external_seen`，`tool_loop.py:2819`）；拿不到就当读过（照 `untrusted.py:106-108`「不知道就算是」）；
  - 总指挥的直接子会话**都**结束了（或者有一个停在「等你」），开**一个**总指挥的汇总回合。它是总指挥对话里的一个后台任务，所以 `said=False`（`task_service.py:1036-1041`）、卡照常出；
  - 汇报一律按外部内容加框；有任何一个子会话读过外部内容，汇总回合一开始就带标记（第 1 条）。
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
- **浏览器和桌面**（第 6 条）：SUB3 已经不给子会话 Hands 和托管浏览器的点击输入，所以不用排队，也不用动 ③Hands 的文件。读网页的浏览器按对话开，两个子会话各开一个；SUB5 加一个数量上限（⓪Plan 建议同时最多 2 个）。
- **Web 界面（最简）：**
  - 总指挥的对话里每个子会话一行：名字、状态、「打开」；
  - 子会话的对话顶上一行「这是〇〇的子会话，做完向它汇报」；
  - 新文案 6 种语言同一个 PR 加（sessions §3）。外观等界面版统一。
- 量级：产品代码约 +350 行（服务端约 200、web 约 150）。

### SUB6 删掉 `delegate_work` 和 `TaskWorker`（§11 第 1 条）

- 删：`server/services/task_workers.py` 整个文件；`server/registry/task_tools.py:21-33`（`DelegateWorkExecutor`）；`arslan.py:1118-1123`；`tool_loop.py` 里 `delegate_work` 的 schema（`:2042` 一带）和超时（`:1791`）；`server/registry/seed_catalog.py:26`；`server/services/task_service.py:42` 里的名字；`server/services/task_repository.py:328-329`、`:500-501`；`server/services/task_restore.py` 里的 `TaskWorker`；`server/api/tasks.py:75-76`；`server/db/worker_models.py` 的 `TaskWorker`；`web/src/lib/toolWords.json:16`；`web/src/locales/process.ts` 里 6 种语言的 `t_delegate_work`；`parallel_reads.py:31` 的注释；`untrusted.py` 里 SUB1 加的两处名字。
- 要先查的：`WorkerBrief` 和 `shared_budget_id`（`contracts.py:203`）还有没有别人用；`professional_methods`（`research`、`apple-growth`、`product-design`）除了帮手还有能力页在用（`web/src/components/Capabilities.tsx:13`），**不跟着删**，删不删另问用户；`personal_context.worker_context` 还被 `memory_tools_v2.py:21` 用，留着。
- **SUB1 的测试不删：** 改成测子会话的汇报（帮手 → 子会话，父回合 → 汇总回合），断言不变：汇报加框、汇总回合带标记。
- 删表：`task_workers` 表的迁移（见表头「迁移号」）。
- 量级：产品代码约 −500 行（整份删除，照总计划 U2 的例外不受 800 行限制）。

## 不许碰

- Bridge 的帧格式。手机上显示子会话、手机上直接跟子会话说话，都要改帧，用户点头前不做（和 Q1 的帧一起问一次，见 v0.1.64 README §2 第 3 条）。v0.1.64 手机上能看到的只有：总指挥对话里的汇总，以及发到总指挥对话的确认卡（这两样今天的帧就有）。
- ③Hands 的文件。子会话不给 Hands 工具，就不用改它们。
- 项目页、关卡地图、关卡条（v0.1.65）。
- Q1 的卡和它的迁移文件：只用它的列，不改它。要多一个列，跟 Q1 的作者和 ②Main 商量。
- 每次运行自己的预算规则（`execution_budget.py`）：树的上限是另加的一道检查，不改原来那道。
- 学习层、`lessons.py` 本身：子会话靠 `no_learning` 不学，不改学习的规则。

## 怎么做（要点）

1. **SUB1 先做，effort=max。** 先让测试在 main 上失败，贴失败输出；再改；Codex 审，结论写明模型。不等 SBX。
2. **SUB2** 等 Q1 的迁移合了再开。只加数据和过滤，用户看不到变化。
3. **SUB3、SUB4、SUB5 叠在一起做，先不合。** 最上面那个 PR 的头上跑 M64 的拆分派汇总题和反面题（DeepSeek 当总指挥），加上全套旧题。过了，三个 PR 按顺序合，每个都要 CI 绿。没过，三个都不合，结论写进早报，回来改。理由：先合进 main 而工具没开放，就是一堆没人调的代码；跑分不过要么返工，要么撤。
4. **跑分过的标准（⓪Plan 建议，用户定）：**
   - 拆分派汇总题三次里至少两次过：开了 2–4 个子会话，每块都有产物，汇总覆盖了每一块，两个子会话没写同一个文件；
   - 反面题三次都不开子会话；
   - 旧题照 K 线的规矩：通过不降、「等你」不增、没有新的报错类型；
   - 记下来不设门槛的：这道题的花费（和不开子会话的同题比是几倍）、服务商回了几次 429。
5. **SUB6** 在 SUB5 合了以后马上做，同一版里删完。删之前每个名字 `git grep -w` 一遍，再按字符串查一遍（注册表的键、翻译键），结果贴进 PR。
6. **每个 PR 都写完成证据四项**（sessions §8）。SUB3–SUB5 叠着时，跑分的命令、run 的位置和三次的结果写进最上面那个 PR。

### ②Main 的 12 条，在本卡怎么定

1. **汇报带着「读过外部内容」的标记（安全）：** 本卡定（⓪Plan）：汇报一律按外部内容加框；有一个子会话读过外部内容（或不知道），汇总回合一开始就带标记。另外往下也传（交代里有外部内容时子会话的回合带标记）。SUB4、SUB3 做，SUB1 的测试在 SUB6 改成测这条。
2. **设置和权限只继承、不放宽：** 本卡定（⓪Plan）：子对话复制父对话的 5 个设置，`no_learning` 一律开；子对话的设置不能改得比父对话松（SUB2）。权限模式今天是全局的，自然一样；以后改成按对话时，子对话照抄父对话、不能更松。授权按对话存，子会话的「本对话都允许」不覆盖别的对话。**子会话要不要继承总指挥已有的「本对话都允许」，用户定**（⓪Plan 建议不继承：卡都发到总指挥窗口，用户一处批）。
3. **一段对话同时只跑一个回合：** 本卡定（⓪Plan）：在子会话窗口打字，排到它的后台回合结束再跑；汇报等总指挥空闲才开汇总回合（SUB4、SUB5）。见「对不上」第 1 条：今天的 409 不是这件事。
4. **重启：** 本卡定（⓪Plan）：见 SUB5 的重启矩阵。全部中断，不自动重跑，总指挥那里写一行说明。
5. **停止、删除、撤销：** 本卡定（⓪Plan）：见 SUB5。其中「删总指挥连子会话一起删」用户定。
6. **只有一个浏览器、一个桌面：** 本卡定（⓪Plan）：v0.1.64 子会话不给 Hands、桌面和托管浏览器的点击输入；这些只留在总指挥那里。以后放开要排队，那时再问 ③Hands。**放开的时间用户定。**
7. **不同时改同一个文件：** 本卡定（⓪Plan）：每个子会话一个自己的文件夹，靠 SBX 的可写目录管；SBX 做不到就退回「同一时间只有一个子会话写」。
8. **列表：** 本卡定（⓪Plan）：和 Q1 共用 `kind` 列，加父对话 id；所有列表默认不列 `sub`；Mac 上从总指挥的对话里点开。**手机上显示子会话要改 Bridge 帧，用户定**（⓪Plan 建议 v0.1.64 不做）。
9. **学习和项目证据：** 本卡定（⓪Plan）：子会话 `no_learning`（`lessons.py:405` 已经认）；子会话的后台回合和总指挥的汇总回合都是后台任务，`said=False`。用户在子会话窗口里自己打的字算用户说的话，`said=True`。
10. **层数和数量在代码里管：** 本卡定（⓪Plan）：层数沿父对话往上数；第二层不给工具，执行时也拒（错误码 `sub_session_depth`，照 `worker_host_only` 的写法）。数量：一个总指挥最多 4 个直接子会话，一个子会话最多 2 个 sub-agent，一棵树同时最多 6 个活着的；同时跑的个数由后台任务的全局上限 3 管（`background_jobs.py:27`）。数字在跑分上再调。
11. **`delegate_work` 怎么办：** 本卡定（⓪Plan）：v0.1.64 同一版删掉它和 `TaskWorker`（SUB6），不留作最下层；第三层就是同一个工具开出来的子对话。在那之前 SUB1 先补洞，因为 SUB6 至少要排在 SBX 和 SUB5 之后，中间几周它还在。
12. **跑分题：** 本卡定（⓪Plan）：题在 M64 卡（拆分派汇总题 + 反面题），记花费和 429。过的标准见「怎么做」第 4 条，用户定。

README 里「开工前要先想好」的另外两条：

- **整个项目一个花费上限：** v0.1.64 先做「一棵树一个上限」（项目树是 v0.1.65）。已花的钱从 `runs.execution_budget` 加总，跨重启都算，每次请求前查；和每次运行的 $2 上限两个都查。**缺口：** 运行的花费只在运行结束时写库（`run_recorder.py:383-387`），被重启打断的那次花的钱会漏掉。SUB3 要么在每次模型请求后顺手更新一次，要么在卡里写明这个缺口；⓪Plan 建议前者，开工时 ②Main 看改动大小再定。
- **总指挥要排先后（例如视频先定大纲）：** 本卡定（⓪Plan）：不做依赖关系的语法。总指挥分几波开：先开大纲那个，等它汇报，再开其余的。跑分题里放一道有先后的，看 DeepSeek 会不会这样做。

## 验收

- **SUB1：** 新测试在 main 上失败、在 PR 上通过（两次结果都贴）；Codex 的审查结论写明模型。
- **SUB2：** 子对话不出现在 Mac 侧栏、项目的「对话」标签、`/phone/conversations`、`/phone/live`；子对话的设置改松回 422；层数数到第 3 层。
- **SUB3–SUB5（叠起来验）：**
  - M64 拆分派汇总题和反面题按「怎么做」第 4 条过；
  - 测试：第二层调工具被拒；超过数量被拒；汇报在框里、汇总回合带标记（真跑一个读网页的假子会话，断言 `external_seen()`）；交代里有外部内容时子会话的第一个回合带标记；子会话的卡出现在总指挥窗口；子会话不学（`lessons.after_turn` 没被调用）；`said` 的三种情况；子会话的 `done` 不打勾；
  - 重启矩阵的四行各一个测试（照 `task_repository` 的 interrupted 测试写法）；
  - 停总指挥时子会话也停；删在跑的总指挥回 409；
  - 两个子会话写同一个文件：第二个被沙箱拒（SBX 提供可写目录时），或者第二个排队（退回方案时）；
  - 树的花费上限：假价格下，树里第二个子会话的请求在树上限处停住，单次运行的 $2 还没到。
- **SUB6：** `git grep -nw delegate_work`、`git grep -nw TaskWorker`、`git grep -n t_delegate_work` 都查不到（SUB1 改写后的测试除外，测试里不再出现这个名字）。
- **手工：** 在 Mac 上开一个项目对话，让它「做一个短视频的标题、大纲、素材清单」，看子会话一行行出现、能点开、能直接说话，最后总指挥出汇总。截图进 PR。

## 量级

| PR | 产品代码 | 测试 |
|---|---|---|
| SUB1 | 约 +3 / −1 | 约 +80 |
| SUB2 | 约 +200（自带迁移再 +40） | 约 +150 |
| SUB3 | 约 +450 | 约 +250 |
| SUB4 | 约 +300 | 约 +200 |
| SUB5 | 约 +350（web 约 150） | 约 +250 |
| SUB6 | 约 −500 | 约 −300（SUB1 的测试改写，不删） |

合计净增约 +800 行产品代码。每个 PR 都在约 800 行以内。

## 风险与回退

- **风险：DeepSeek 拆不好**（开太多、该开不开、汇总漏块）。跑分不过就不合 SUB3–SUB5；SUB1、SUB2 已经合了也不受影响（SUB2 只是数据和过滤）。
- **风险：花费成倍、服务商 429。** N 个子会话就是 N 倍的请求。全局 3 个的并发上限和树的花费上限兜底；跑分记 429 次数，太多就把同时跑的上限调小。
- **风险：标记漏传**（往上、往下两个方向）。SUB1 和 SUB4 的测试都要真跑一个读网页的假回合，不能只断言源码里有这个名字。
- **风险：可写目录。** 「每个子会话一个文件夹」靠 SBX。SBX 的接口和本卡设想的不一样时，退回「同一时间只有一个子会话写」，并在 PR 描述里写明。
- **风险：违反 sessions §11 第 3 条。** 子会话是新子系统：v0.1.63 排了的删除没合完之前不开，同一时间只做一个新子系统。和 Q1、CAP、INB 谁先谁后，用户定。SUB1 是安全修复，不受这条限制。
- **旧路径：** 本卡唯一「先留着」的是 SUB1 之后、SUB6 之前的 `delegate_work`。代码注释写 `DELETE-BY: v0.1.64`（随 SUB6 删）。
- **回退：**
  - SUB1：单独 revert，回到有洞的状态，所以不建议回退；有问题改测试或改法，不撤。
  - SUB2：revert 后子对话重新出现在列表里；迁移不回退（列留着，没人读）。
  - SUB3–SUB5：按倒序 revert，工具从工具表里消失；已经建出来的子对话变成普通对话（`kind` 还是 `sub`，但没人特殊处理），列表过滤要跟着 SUB2 一起撤。
  - SUB6：revert 会把 `delegate_work` 带回来，只在 SUB3–SUB5 也撤了的时候才做。

## 开工前要用户定的

1. **SUB1 现在就修，还是等 SUB6 删掉 `delegate_work` 时一起收掉？** ⓪Plan 建议现在修：改动约 4 行，而 SUB6 至少排在 SBX 和 SUB5 之后。两种都保留那个测试。
2. **跑分过的标准**（「怎么做」第 4 条）：拆分派汇总题三次过两次、反面题三次全不开、旧题不退步。
3. **一棵树的花费上限默认多少？** ⓪Plan 建议每次运行上限的 3 倍（默认 $6），在设置里和每次运行的上限放一起。
4. **子会话继承不继承总指挥已有的「本对话都允许」？** ⓪Plan 建议不继承。
5. **删总指挥时子会话一起删吗？** ⓪Plan 建议一起删（有子会话在跑时先拒）。
6. **手机上显示子会话**（改 Bridge 帧）：⓪Plan 建议 v0.1.64 不做，手机上只看总指挥的汇总和发到总指挥的卡；要做就和 Q1 的帧一起问。
7. **子会话什么时候能用 Hands 和托管浏览器的点击输入？** ⓪Plan 建议 v0.1.64 不给。
8. **和 Q1、CAP、INB 的先后**（§11 第 3 条：同一时间只做一个新子系统）。
9. **`professional_methods`**（`research`、`apple-growth`、`product-design` 三个方法和能力页上的编辑）：SUB6 删掉帮手以后它们没有别的调用方了，要不要另开一张卡删。SUB6 本身不删它们。
