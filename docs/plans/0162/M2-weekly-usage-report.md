# M2 本机用量周报脚本（只读、只出数字）

| 项 | 内容 |
|---|---|
| 道 | ⓪Plan |
| 版本 | —（脚本，不随 App 发布） |
| 分级 | 必须 |
| 依赖 | —（F1、F3 合并后能数得更准，见下） |
| 合并位置 | M 线随时；要在 v0.1.62 发布前合，这样发布前后能用同一把尺子 |
| 推动的门槛 | §5.2 全部（这张表就是 §5.2 的测量工具） |
| 分支 | `claude/0162-m2-weekly-usage-report` |
| 迁移号 | 无 |

## 目标

用户在本机跑一条命令，就能出一张按周统计的表，回答 §5.2 的每一行。

- **只读：** 用 SQLite 的 `mode=ro`，不写库、不加锁、不做 checkpoint。
- **只出数字：** 不出对话内容、命令、路径、App 名、错误原文、工具参数。

## 每周要出的数（和数据从哪来，亲核）

| 指标 | 来源 |
|---|---|
| 运行数 | `runs`（`server/db/models.py:539-585`）：按 `started_at` 分周，只数 `kind = 'live'` |
| 任务停在「等你」的占比，以及按原因分布 | `companion_tasks.phase = 'waiting_user'`，原因是 `pause_reason`（`server/db/task_models.py:13-38`）。原因是 `task_reconciliation_required` 这类固定代码，可以原样输出 |
| 工具调用失败率 | `run_steps` 里 `kind = 'tool_call'` 的行，读 `ref` 里的 `tool` 和 `ok`（`models.py:591-601`；写入在 `server/services/run_recorder.py:241`、`:485-487`）。MCP 工具合并成一行 `mcp`，不输出各自的名字 |
| `run_command` 的时限类失败 | `ref.tool = 'run_command'` 且 `ok` 为假，再在 SQL 里拿 `detail` 的 `$.error`（`tool_loop.py:345-346` 只是转写；文字本身出自 `tool_loop.py:1303` 和 `terminal_exec.py:149`）和产品自己的固定文字比：`tool 'run_command' timed out`（20 秒截断），`stopped after %`（命令自己的时限）；F1 合并后再加它新加的那句固定文字 `stopped by the time limit; no output was captured`（外层兜底超时，见 F1 卡）。只按固定文字数：`code` 只存在 `result_raw` 里，本卡不读它（实现时核过，PR #193）。只返回计数。`duration_ms` 落在 19,500–21,500 之间作为旁证 |
| MCP 引起的整轮失败 | **F3 合并前：** `runs.error_kind = 'ModelCallError'`，且 `error_text` 在 SQL 里匹配出「HTTP 400 + 工具参数表」的形状，只返回计数，标「按文字推断」。**F3 合并后：** 另外数 `conversation_events.kind = 'mcp_schema_relaxed'` 的行数（`models.py:751-758`） |
| 卡片数（按种类） | 账本 `approval_events`（`models.py:492-514`）：`decided_by` 是 `user` 或 `expired` 的，算「真的出过卡」，按 `kind` 分；其余的（rule、grant、floor、mode、policy，以及 reviewer、away）算「自动决定」，单独一列 |
| 账本之外的命令卡 | `judgments` 里 `point = 'tool.approval'` 的行（`models.py:896-914`），只读 `state` 里的 `sandboxed` 和 `rule` 两个键，再加 `outcome`。出沙箱卡不写账本，它们只留在这里 |
| 回合后的额外模型调用 | `usage_ledger`（`models.py:926-938`）里 `scope` 为 `memory_facts`（抽事实，`server/services/turn_facts.py:105`）和 `memory`（摘要，`server/orchestrator/memory.py:165`）的行数 |

### 两点注意

1. **「卡片数」一节分两列给，不要相加。**
   - 账本这一列和 `judgments` 这一列会有重叠：走 `decide()` 的命令卡两边都记。
   - C4 删掉影子评判以后，`judgments` 那一列会归零；出沙箱卡要等 S4a 改走 `decide()`，才回到账本里。
   - **已随 C4 删除（2026-10-21，⓪Plan 同意）：** 「账本之外的命令卡」这一列和「Command cards in judgments」那张表随影子评判一起删了；`judgments` 里的旧行按 `KEEP_DAYS` 自然清掉。
   - 这些在表下面用一句话写明。
2. **`usage_ledger` 的行数约等于调用次数**（一个 scope 一次写一行）。同一个 scope 里换过模型，一次会多出一行，未核。

## 怎么做（要点）

1. JSON 列只用 `json_extract` 取上表点名的那几个键；文字匹配也在 SQL 里做。返回 Python 的只有计数和固定代码，不把任何一列的原文读进来。
2. 一周按本地时间，从周一算起。表头写清起止日期。
3. 输出只拼聚合后的数字，从不拼单行记录。
4. 推断出来的数字（按耗时、按文字）在格子里标「≈」，表下用一句话说明。

## 改哪些文件

- **新增 `scripts/usage_report.py`：**
  - 参数：`--db PATH`（可选）、`--weeks N`（默认 4）、`--since YYYY-MM-DD`。
  - 不给 `--db` 时，按 `server/config.py:126-127` 的同一规则找数据库：`ARSLAN_DB_PATH`，否则 `data_dir()/arslan.db`。`data_dir()`（`:65`）只算路径，不建目录。
  - 打开方式：`sqlite3.connect("file:…?mode=ro", uri=True)`。
  - 输出 Markdown 表，只有数字和固定代码。
- **新增 `tests/test_usage_report.py`：**
  - 在 `tmp_path` 里建一个合成库（只建要读的几张表和列）；
  - 写入几行假数据，断言输出的数字；
  - 断言输出里不出现假数据里埋的「机密」字符串：路径、命令、App 名、错误原文。

## 不许碰

- 产品代码和数据库结构。不加迁移，不改任何写入方。
- 用户的真实数据目录。测试只用合成库，见 `tests/real_data_dir_guard.py`。
- `run_steps.detail` 里的 `args_full` 和 `result_raw`、`judgments.state` 里的 `command` 和 `user_request`、`approval_events` 的 `target` 和 `detail`：一律不输出。脚本内部只按上表取那几个键。

## 验收

- 合成库上的测试全过，其中包括「不泄漏」那条。
- 用户在本机跑一次，看到一张表。
  - 表里只有数字和固定代码；
  - 0.1.61 安装后那几周的数，和 ⓪Plan 提案 §1 的汇总数（`run_command` 失败、「等你」占比）量级一致，误差要能说清。
- 脚本运行期间，数据库文件的修改时间不变（测试里断言）。

## 量级

脚本约 150–200 行，外加测试约 100 行。

## 风险与回退

- **按文字推断的两项（F1、F3 合并前）会有误差。** 表里会标出来；发布之后改用结构化的码。
- **App 运行时也能读**，因为是只读打开；数据库在 WAL 模式下的边角情况未核。
- **回退：** 删掉这个脚本即可，它不影响产品。
