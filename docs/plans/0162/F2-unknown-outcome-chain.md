# F2 「结果不明」链四处修正：没发生的事不再要你去核对

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | 热修版 |
| 分级 | 必须 |
| 依赖 | F5a；软依赖 H2（H2 没合时，先按现有代码 `declined` / `no_answer` / `no_one_to_ask` / `not_allowed` / `reviewer_denied` 处理） |
| 合并位置 | F 线；最好在 H2 和 F1 之后（F1 带来 `code: "time_limit"`） |
| 推动的门槛 | §5.2「任务停在『等你』≤15%」与「其中『需要你核对』≤5%」；§5.3 第 1、6 条 |
| 分支 | `claude/0162-f2-unknown-outcome-chain` |
| 迁移号 | 无 |

## 目标

只有真的可能已经在外面留下痕迹的动作，才以「需要你核对」（`task_reconciliation_required`）收场。

聊天回合也走 `task_service.run_turn`（`server/services/task_service.py:489-530`），所以这条链对聊天和后台任务同样生效。

## 现状（亲核）

1. **命令一律算「对外写」。** `effect_of` 把整条命令字符串当程序名交给 `command_policy.classify`（`task_service.py:101-106`）。
   - `classify` 只拿它和只读程序名单比（`server/services/command_policy.py:81-106`）。
   - 所以 `ls -la x`、`git status` 都是 HIGH，都成了 `external_write`。
2. **被自己的时限停掉的命令算未知。** 判断在 `task_service.py:78-79`（计划写的 `:72-74` 是 MCP 未就绪和写文件那两行）。
3. **只认三种工具的已知失败。** `known_local_failure`（`:55-82`）只认 `run_command`、`write_file`、`edit_file` 和 MCP 未就绪，其他工具一律返回 False。
   - Hands 卡被拒（`server/registry/hands_tools.py:111-132` 的 `_no`，在执行器里问卡：`:1009-1014`）于是变成 `uncertain`：
     - 状态映射在 `server/services/task_repository.py:454-456`；
     - 黏住在 `task_service.py:330-333`。
   - 抛异常的调用也一样标成未知（`:300-306`）。
   - 同一个调用再试会被拒（`task_repository.py:404-406`），模型还被要求「告诉用户去核对」（`server/orchestrator/tool_loop.py:1292-1299`）。
   - 只要有 `uncertain` 的非读动作，任务就不能以「成功」收尾（`task_repository.py:292-295`）。
4. **交付物已经保存，回合仍会挂起。** 回合碰上「没有进展」或「预算」时，即使 `saved` 为真，也照样写 `pause_reason`，挂成「等你」（`tool_loop.py:2272-2283`）。聊天回合在硬预算用完后的收尾也一样（`:2029-2042`）。
5. **命令卡被拒，今天不会走到这条链上。** 命令卡在 `tool_loop.py:1094-1099` 提前返回，不经过 `TaskRuntime.execute_tool`，所以按代码读，今天不会标「结果不明」。下面那条回放测试是回归守卫：如果它在 main 上已经通过，PR 里要写明。

## 改哪些文件

- **`server/services/task_service.py`：**
  - ① `effect_of` 的 `run_command` 分支：
    - 命中 `_OUTBOUND_RULES`（`:51-52`，用 `terminal_policy.ask_rules`）的算 `external_write`；
    - 其余算 `local_write`；
    - 可选：只有不含任何 shell 运算符或重定向的单条简单命令，用 `shlex` 拆出 argv 再交给 `command_policy.classify(argv[0], argv[1:])`，判成 LOW 的才算 `read`。做不到简单可靠，就不做 `read` 这一档。
  - ② `known_local_failure`：被 Arslan 自己的时限停掉的命令，满足下面三条就算已知失败：
    - `code == "time_limit"` 或 `error` 以 `stopped after` 开头；
    - 结果里 `sandbox == "workspace"`（在沙箱里跑的）；
    - 不命中对外规则。
  - ③ 下面两种结果算已知失败：
    - 任何工具的结果带 `executed: False`（H2 的约定）；
    - Hands 的工具（`desktop_*`、`mac_*`、`browser_*`）返回的 `code` 在 `_no` 那 5 个码里。只认 Hands，因为别的工具（比如 MCP）可能带着同名的码。
  - 边界保持不变：本地脚本自己联网发了东西再失败，仍按本地处理（`:65-67` 原文已写）。
- **`server/orchestrator/tool_loop.py`**（热点文件，只改这两处）：
  - ④ `:2280-2283`：本轮已有成功的 `write_file` / `edit_file`（`WRAP_UP_TOOLS`，`:1999`）时，不写 `runtime.pause_reason`。判断看整个 `tool_trace`，不只看 `finish_from` 之后。
  - `:2039-2042`（聊天回合硬预算用完后的收尾）同理。
- **测试：**
  - `tests/server/test_job_checks_0159.py` 加用例，沿用 `run_contract` / `command_result` / `act` 的写法（`:162-182`）。
  - `test_a_command_stopped_by_its_timeout_still_asks_the_user_to_check`（`:231-236`）：保留，用来覆盖「不在沙箱里」的情况。
  - `:254` 那条断言：同样保留，用来覆盖不在沙箱里的情况。

## 不许碰

- `_OUTBOUND_RULES` 的内容；命令卡本身（S2a 的事）；`task_repository.py` 的状态机（只靠 `error_code="known_local_failure"` 走现有映射）。
- `server/registry/hands_tools.py`：③Hands 的文件，代码由 H2 改。
- Bridge 文件。

## 怎么做（要点）

1. 先写「验收」里的回放测试，看它们在 main 上失败。第 3 条是回归守卫，可能已经通过。
2. ①②③ 都在 `task_service.py` 里，彼此独立，提交分开，方便逐条审。
3. ④ 只改 `tool_loop.py` 那两处，不动停止策略本身（停止策略归 K4）。
4. H2 已合，就加带 `executed: False` 的那组测试；没合，就只认 `_no` 那 5 个码，并在 PR 里写明。

## 验收

**回放测试**（任务层，不调模型），三种情况都不以 `task_reconciliation_required` 收场：

1. 读命令在沙箱里被时限停掉（`code: "time_limit"`、`sandbox: "workspace"`）；
2. Hands 卡被用户拒绝（`code: "declined"`；H2 合了以后再加带 `executed: False` 的一组）；
3. 命令卡被拒（回归守卫，见现状第 5 条）。

**另外：**

- 一条真的对外的命令失败了，仍然要你核对：
  - `git push` 退出码 1：现有 `:214` 的测试照旧通过；
  - 发信命令被时限停掉：新加的测试。
- 保存了交付物、又碰上「没有进展」的回合：任务不挂起。
- `test_which_failures_are_known_and_local`（`:247-258`）补上新情况，原有断言都不变。

## 量级

产品代码约 60–80 行，外加测试。

## 风险与回退

- **把真的可能做过的事判成「已知没做」，是本卡最大的风险。**
  - 所以 ② 只放过沙箱里的命令；
  - ③ 只认「执行前就拒了」的码，H2 会列一张固定清单；
  - `unknown`、`TIMEOUT`、`submit_unsure`、`takeover_paused` 这类都不算。
- **改成 `local_write` 之后，一条已成功的命令原样再跑一次仍会被拒**（`task_repository.py:404-406`）。今天就是这样，不是本卡带来的。要放宽，记进 README §8「0.1.63 候选」。
- **回退：** revert 合并提交。已经记成 `uncertain` 的旧任务不受影响。
