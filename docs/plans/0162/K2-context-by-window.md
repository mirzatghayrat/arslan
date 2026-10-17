# K2 跨轮上下文按窗口来

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.63 |
| 分级 | 必须 |
| 依赖 | K1；C2a 先合（同改 `server/orchestrator/memory.py`） |
| 合并位置 | K 线第 2 个 |
| 推动的门槛 | §5.1「三轮追问 3/3」；§5.3 第 3 条；§5.2「回合后的额外模型调用」那一行，按 U5 改成两条：① 抽事实和摘要不在回合锁里，由测试断言；② 回答一结束马上发下一条，不出现「排队」（M3 第 11 条）。调用次数到 v0.1.65 前不设门槛 |
| 分支 | `claude/0162-k2-context-window` |
| 迁移号 | 无（不加角色、不加列；工具摘要写进现有的 `content` 列） |

## 目标

下一轮知道上一轮做了什么、动了哪些文件；历史长度按模型窗口算，不再固定 3,000；回合后的抽事实和压缩不再挡住下一条消息（v0.1.63 计划 K-2）。

今天的情况（`fb6d7230`）：

- 每轮只存用户原文和最终回答（`server/orchestrator/arslan.py:513`、`:904`），工具调用和结果不入库。
- 历史预算固定 3,000 估算 token（`server/orchestrator/memory.py:19`；环境变量可改，`:26-27`），组装在 `:100-125`。
- 超过预算就把除最后一条以外的全部折叠进摘要（`maybe_compact`，`:146-168`）。
- 回答后的抽事实和压缩都在回合锁里（`arslan.py:539-545`；锁在 `server/ws/arslan.py:265-272`，调用点 `:708`、`:740`、`:801`）。

## 改哪些文件

- `server/orchestrator/memory.py`
  - `:19`：历史预算改为模型窗口的一定比例，并加封顶。窗口从 `server/services/model_catalog.py` 取（`_info` 的 `context_window`，`:62-69`）。这个值来自供应商的模型列表，可能为空，取不到时用保守默认值。
  - `:100-125`：按新预算组装；最近 N 轮保留原文。
  - `maybe_compact`（`:128-186`）：只在约 75% 时压缩一次。先把旧的工具摘要换成占位（免费），不够再摘要。摘要用固定结构（目标、进度、决定、动过的文件、下一步），原地更新。
- `server/orchestrator/arslan.py`
  - `:904`：回答入库时，把本轮的工具摘要接在回复后面写进 `content`，`display_content` 存回复原文。`add_message` 已经支持 `display_content`（`memory.py:36-60`）。
  - `:539-545`：`turn_facts.capture` 和 `memory.maybe_compact` 挪到回合锁外。
- `server/services/conversation_search.py`：搜索片段改读 `display_content`（见下表）。
- 测试：见验收。

**不新增角色。** 界面继续读 `display_content`（`server/db/models.py:140-141`）。读 `arslan_messages` 的地方逐个核过：

| 读取方 | 读什么 | 要不要改 |
|---|---|---|
| 网页历史 `server/ws/arslan.py:121` | `display_content or content` | 不改 |
| iPhone 历史 `server/api/phone.py:126-127` | 同上；非用户的角色一律当助手消息发 | 不改，iPhone 显示不变 |
| iPhone 对话列表预览 `server/services/phone_reads.py:285` | 同上 | 不改 |
| 任务结果 `server/services/task_service.py:642-644` | 同上 | 不改 |
| `server/api/runs.py:126-128` | 只取 id 和 `job_outcome`，不读正文 | 不改。要是加新角色，这里会把它当成一条回答，这也是不加角色的原因 |
| 搜索 `server/services/conversation_search.py` | 匹配和片段都读 `content`（`:53-58`、`:74`）；全文索引也只建在 `content` 上（`server/db/migrations/versions/_0059_messages_fts.py:11-19`） | **要改：** 片段改读 `display_content`。摘要里的文件名能被搜到，可以接受 |
| 模型的历史 `memory.py:88-99`；压缩 `memory.py:154` | `content` | 不改，正好带上工具摘要 |

Bridge 帧格式不变，iPhone 端不用改。

## 不许碰

- Bridge 帧格式；记忆 v2 的长期记忆存储（C2a 只删 v1 死分支）。
- 提示词布局（K3）。
- `server/orchestrator/tool_loop.py`：工具摘要用 `_handle_answer` 已经拿到的 `tool_trace` 生成（`arslan.py:899`），不用改循环。

## 怎么做（要点）

1. **先写测试：** 窗口 200k 的模型和窗口 32k 的模型，进提示词的历史上限不同。
2. **工具摘要：** 回合结束时由 `tool_trace` 生成，一个回合一段：工具名、关键参数、结果前约 500 字或落盘路径。
   - 用一个固定标记包起来。模型照抄进回答时，界面滤掉，做法同 `agent_status.strip_echo`（`server/orchestrator/agent_status.py:151-154`）。
   - **外部内容只记来源，不抄正文。** 网页、MCP、读到的文件（`untrusted.counts_as_external`，`server/orchestrator/untrusted.py:57`）只记 URL 或路径。否则网页里的指令，下一轮会变成「Arslan 自己说过的话」。
   - 回答为空时不写摘要。读取方用的是 `display_content or content`，空字符串会退回 `content`，把摘要露出来。
3. **抽事实和压缩挪到锁外：** 回合返回后排一个后台任务；下一轮组装历史时读已经提交的状态，不等它。
   - **不加新锁**，复用 `memory_snapshot_guard`（`maybe_compact` 已经在用：`memory.py:133-136`、`:166`、`:179-182`）。摘要写入再加一个条件：最新摘要的 `up_to_message_id` 没变；变了就丢掉这次结果。
   - 后台任务要带上本回合的判断（临时对话、关了记忆或学习，`arslan.py:541-542`）和记账分类（`memory_facts`、`memory`），不能丢计费。
   - 抽事实会往界面发「记住了」的事件（`server/services/turn_facts.py:125-128`）。挪出锁后，它在 `stream_end` 之后才到。网页和 iPhone 要能接住；连接已经断了就不发，不报错。
4. **先遮蔽、后摘要：** 参考领先路线 L8。
5. **留着的回退写删除版本：** 旧固定预算的设置和关掉工具摘要的开关，代码注释写「v0.1.64 删」（见「风险与回退」）。

## 验收

- **测试：**
  - 历史上限随窗口变化；
  - 压缩只在约 75% 时触发一次，最近 N 轮保留原文；
  - 下一轮的提示词里有上一轮的工具摘要；外部内容的正文不进摘要；
  - **（U5 ①）** 回合锁释放时，抽事实和摘要还可以没跑完；第二条消息不等它们就开始；
  - 网页历史、iPhone 历史、对话列表预览、搜索片段里，都看不到工具摘要。
- **M1（贴在 PR 里）：** 三轮追问题 3/3；其余题不差于 K1 之后。
- **M3（U5 ②）：** 第 11 条「回答一出现马上发下一条，不出现『排队』」通过。
- **M2（装上后 7 天）：** 只记录回合后的调用次数，不当门槛（U5）。

## 量级

产品代码约 +220 / −100 行。

## 风险与回退

- **风险：大窗口模型的 token 成本上升。** 历史上限加封顶（例如窗口的一半，且不超过一个固定值），数值在 PR 里写明。
- **风险：锁外任务和下一轮同时写摘要。** 按要点 3 条件写入，过时的结果丢掉。
- **风险：进程退出时，排着的后台任务丢失。** 只丢这一次抽事实，下一次压缩会补上，不影响对话。
- **回退：** 一个设置切回旧的固定预算；工具摘要的写入可以单独关掉。
- **留着的旧路径与删除条件**（代码注释里同样写）：
  - 「切回旧固定预算」的设置，以及 `ARSLAN_WORKING_TOKEN_BUDGET`（`memory.py:26-27`）：**v0.1.64 删**。条件：v0.1.63 装上后 7 天内没有用到这个回退，M3 第 3、11 条都通过。
  - 「关掉工具摘要」的开关：**v0.1.64 删**，条件同上。
