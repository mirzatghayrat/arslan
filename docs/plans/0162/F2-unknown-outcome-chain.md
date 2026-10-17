# F2 「结果不明」链四处修正：没发生的事不再要你去核对

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.62 |
| 分级 | 必须 |
| 依赖 | F5a；F1（认它的 `code: "time_limit"`）；软依赖 H2（没赶上时见第 ③ 条） |
| 合并位置 | 合进 `release/0.1.62`，排在 F1 之后；H2 赶上热修的话，排在 H2 之后。发版后随分支合回 main |
| 推动的门槛 | §5.2「任务停在『等你』≤15%」与「其中『需要你核对』≤5%」；§5.3 第 1、6 条 |
| 分支 | `claude/0162-f2-unknown-outcome-chain`（从 `release/0.1.62` 拉，PR 的 base 是 `release/0.1.62`） |
| 迁移号 | 无 |

## 目标

只有真的可能已经在外面留下痕迹的动作，才以「需要你核对」（`task_reconciliation_required`）收场。聊天回合也走 `task_service.run_turn`（`server/services/task_service.py:489-530`），所以这条链对聊天和后台任务同样生效。

## 现状（亲核）

1. **命令一律算「对外写」。** `effect_of` 把整条命令字符串当程序名交给 `command_policy.classify`（`task_service.py:101-106`），所以 `ls -la x`、`git status` 都成了 `external_write`。
2. **「结果不明」只认是不是 `read`**（审查 §3）：抛异常时 `effect != "read"`（`:305`），失败时 `not succeeded and effect != "read" and not known`（`:332-333`）。`local_write` 和 `external_write` 在这里一样。
3. **`local_write` 的普通失败记成「失败」：** `task_repository.py:454-456` 只把 `local_write` 加 `error_code == "tool_failed"` 留成 `failed`。`failed` 的同一个动作可以原样再跑（`:404`）。
4. **被自己的时限停掉的命令算未知**（`task_service.py:78-79`）。
5. **只认三种工具的已知失败**（`:55-82`）。Hands 卡被拒（`server/registry/hands_tools.py:111-132` 的 `_no`）于是变成 `uncertain`，同一个调用再试被拒（`task_repository.py:404-406`），任务不能以「成功」收尾（`:292-295`）。
6. **有几种对外写法认不出**（审查亲核，本卡复核）：`curl --request=POST https://…`（不带数据参数）、`gh api … -f …`（gh 带参数时默认 POST）、`gh api --method POST …`、HTTPie 的 `http POST …`、`xh POST …`，今天都判成 `run`，`ask_rules` 为空。它们失败了也会被当成本地的已知失败。
7. **交付物已经保存，回合仍会挂起**（`tool_loop.py:2272-2283`；聊天回合硬预算后的收尾 `:2029-2042`）。
8. **命令卡被拒，今天不走这条链**（`tool_loop.py:1094-1099` 提前返回）。下面那条回放测试是回归守卫。

## 改哪些文件

**`server/services/task_service.py`：**

- ① **`effect_of`：读命令判成 `read`。** 这一档是必须的，不是可选（审查 §3）。
  - 只收单条简单命令：不含 shell 运算符、重定向、命令替换。用 `shlex` 拆出 argv，`command_policy.classify(argv[0], argv[1:]) == "LOW"`。
  - LOW 名单不能原样照搬，这几种会改东西或跑别的程序，不算 `read`：`find` 带 `-delete`、`-exec*`、`-ok*`、`-fprint*`、`-fls`；`git branch`、`git remote` 带任何参数（如 `-D`、`add`）；`git` 带 `--output`；`rg` 带 `--pre`。
  - 其余命令保持 `external_write`（今天的值）。**不改成 `local_write`：** 见现状第 3 条，那样被信号杀掉、在沙箱外被时限停掉的命令都会记成 `failed`，能原样重跑，等于把「未知」当成「已知」。
- ② **`known_local_failure`：沙箱里被时限停掉的命令算已知失败**，三条都满足才算：
  - `code == "time_limit"`（F1）；
  - 结果里 `sandbox == "workspace"`；
  - 不对外（`_OUTBOUND_RULES` 加下面的 ②a）。
  - 时限停止时 `exit_code` 也是 -9（`killpg` 发的 SIGKILL，`terminal_exec.py:117-122`），所以这条判断要排在 `:78` 的「信号」判断之前。
  - **仍然未知：** 在沙箱外被时限停掉的；不带 `time_limit` 却被信号杀掉的（`exit_code` 为负或不是整数，`:78`）；被用户停止的（`CancelledError`，`:298-299`）；所有对外的。
- ②a **补认几种对外写法**（新常量 `_OUTBOUND_EXTRA`，只在本文件里用，不改出卡）：
  - `curl` 带 `--request=POST|PUT|PATCH|DELETE`；
  - `gh api` 带 `-f`、`-F`、`--field`、`--raw-field`、`--input`，或 `--method` 不是 GET；
  - HTTPie 和 xh（`http`、`https`、`xh`、`xhs`）带 `POST|PUT|PATCH|DELETE`，或带数据项（`a=b`、`a:=b`）。
  - 这几种写法归 S2a 的「对外」组（S2a 卡已列）：S2a 把它们并进 `terminal_policy` 后，命令卡也会出，本常量随之删掉。
- ③ **下面两种结果算已知失败：**
  - 任何工具的结果带 `executed: False`（H2 的约定；F1 的「没时间就不启动」也用它）；
  - Hands 的工具（`desktop_*`、`mac_*`、`browser_*`）返回的 `code` 在 `_no` 那 5 个码里。只认 Hands，因为别的工具（比如 MCP）可能带着同名的码。
- ④ **`_run` 的收尾（`:378-399`）**：配合下面 `tool_loop.py` 的改动，见第 ④ 条。
- 边界保持不变：本地脚本自己联网发了东西再失败，仍按本地处理（`:65-67` 原文已写）。

**`server/orchestrator/tool_loop.py`**（热点文件，只改这两处）：

- ④ **存过交付物，并且验收通过，才不挂起**（审查 §3）。
  - `:2280-2283`：本轮已有成功的 `write_file` / `edit_file`（`WRAP_UP_TOOLS`，`:1999`；看整个 `tool_trace`）时，不直接写 `runtime.pause_reason`，改记一个只在内存里的 `runtime.limit_reason`。`:2039-2042` 同理。
  - `task_service._run` 验收之后：至少有一项检查的是存下的文件（`task_validation.py:106` 的「文件已存盘」，或 `validation_report["artifacts"]` 里的项），而且全部通过，才算成功；否则照旧挂成「等你」，原因用 `limit_reason`。
  - 只有「有回答」那一项（`ANSWER_DELIVERED`，`task_service.py:458-459`）不算。聊天回合默认只有这一项（`:513`），所以聊天回合照旧挂起，放宽归 K4。

**测试：** `tests/server/test_job_checks_0159.py` 加用例，沿用 `run_contract` / `command_result` / `act` 的写法（`:162-182`）。`test_a_command_stopped_by_its_timeout_still_asks_the_user_to_check`（`:231-236`）和 `:254` 那条断言保留，用来覆盖「不在沙箱里」。

## 不许碰

- `_OUTBOUND_RULES` 的内容和 `terminal_policy` 的规则（出卡归 S2a）；
- `task_repository.py` 的状态机：只靠选哪个 `error_code` 走现有映射；
- `server/registry/hands_tools.py`：③Hands 的文件，代码由 H2 改；
- Bridge 文件。

## 怎么做（要点）

1. 先写「验收」里的测试，看它们在 v0.1.61 上失败。命令卡那条是回归守卫，可能已经通过，PR 里写明。
2. ①②②a③ 都在 `task_service.py` 里，提交分开，方便逐条审。
3. ④ 只改 `tool_loop.py` 那两处和 `_run` 的收尾，不动停止策略本身（归 K4）。
4. 留着的两条临时路径（见「风险与回退」），代码注释写明什么时候删（`docs/sessions.md` §9）。

## 验收

**回放测试**（任务层，不调模型），下面都不以 `task_reconciliation_required` 收场：

1. 读命令在沙箱里被时限停掉（`code: "time_limit"`、`sandbox: "workspace"`）；
2. Hands 卡被用户拒绝（`code: "declined"`；H2 合了以后再加带 `executed: False` 的一组）；
3. 命令卡被拒（回归守卫）；
4. `ls -la x` 被信号杀掉（`exit_code: -15`）：effect 是 `read`，不要你核对。

**仍然要你核对：**

- `git push` 退出码 1：现有 `:214` 的测试照旧通过；
- 发信命令被时限停掉；
- 非读命令不带 `time_limit` 被信号杀掉（`exit_code: -15`）；在沙箱外被时限停掉；
- `curl --request=POST https://x`、`gh api repos/a/b/issues -f title=x`、`gh api --method POST x`、`http POST https://x a=b`、`xh POST https://x a=b` 退出码非 0，或在沙箱里被时限停掉。

**能不能重跑**（审查 §3）：

- 读命令成功后，原样再跑一次照样能跑（`read` 每次的指纹都不同，`task_repository.py:60-62`）；
- 已知失败（沙箱里被时限停掉的 `python3 build.py`、退出码 1 的本地命令）之后，原样再跑能跑；
- 未知结果（非读命令被信号杀掉、在沙箱外被时限停掉）之后，原样再跑被拒，`code == "task_reconciliation_required"`；
- `find . -delete`、`git branch -D x` 的 effect 不是 `read`。

**收尾：**

- 保存了交付物、文件检查通过、又碰上「没有进展」的后台任务：成功，不挂起；
- 同样情况但文件检查没过，或只有「有回答」这一项检查：照旧挂起，原因是 `task_no_progress` 或 `task_budget_exhausted`。

`test_which_failures_are_known_and_local`（`:247-258`）补上新情况，原有断言都不变。

## 量级

产品代码约 90–120 行，外加测试。

## 风险与回退

- **把真的可能做过的事判成「已知没做」，是本卡最大的风险。** 所以 ② 只放过沙箱里的命令；③ 只认「执行前就拒了」的码，H2 会列一张固定清单；`unknown`、`TIMEOUT`、`submit_unsure`、`takeover_paused` 这类都不算。
- **沙箱今天不挡网络**（`(allow default)`，更正 E11）。一个在沙箱里被时限停掉的本地脚本，可能自己联网发过东西。这和 0.1.59 起「本地脚本失败按本地算」是同一个边界（`:65-67`），PR 和发布说明都要写明。S2a 收紧沙箱后才真正堵上。
- **非读命令成功后原样再跑仍会被拒**（`task_repository.py:404-406`）。今天就是这样，读命令这次已放开；其余的放宽已记在 README §8「v0.1.64 候选」。
- **留着的临时路径和删除条件**（`docs/sessions.md` §9，代码注释同样写）：
  - ②a 的 `_OUTBOUND_EXTRA`：S2a 把这几种写法并进 `terminal_policy` 的「对外」组时，在同一个 PR 里删（v0.1.63）。
  - ③ 里「Hands 的 `_no` 5 个码」这条：H2 赶上热修，本卡就不写它；赶不上，H2 合进 main 之后由 ②Main 开小 PR 删（v0.1.63 内）。
- **回退：** 在 `release/0.1.62` 上 revert 合并提交。已经记成 `uncertain` 的旧任务不受影响。
