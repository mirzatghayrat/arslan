# F1 `run_command` 的时限跟它自己的参数走，超时也把输出交给模型

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | 热修版 |
| 分级 | 必须 |
| 依赖 | F5a |
| 合并位置 | F 线；F5a 之后，和 F2、F3、F4a、F4b 不分先后 |
| 推动的门槛 | §5.2「`run_command` 的时限类失败 = 0」；§5.3 第 1 条；§5.1 新题「长命令」 |
| 分支 | `claude/0162-f1-command-timeout` |
| 迁移号 | 无 |

## 目标

1. **时限按命令自己的参数算。** 一条命令能跑满它自己的时限：默认 120 秒，最长 600 秒。工具循环不再统一在 20 秒掐断它。
2. **超时也把输出交给模型。** 不管是哪一层的时限到了，模型都能拿到 stdout / stderr 的尾巴，外加一句「被时限停止」。

## 现状（亲核）

**谁在掐 20 秒：**

- 循环给每个工具 20 秒（`server/orchestrator/tool_loop.py:31`，`TOOL_TIMEOUT_S = 20.0`）。
- 只有声明了 `timeout_s` 的执行器能拿到更长的时间（`:1267-1272`）：取 `max(20, own)`，再用 `asyncio.wait_for` 包住。
- `RunCommandExecutor`（`server/registry/executors.py:775-816`）没有声明 `timeout_s`。它只把参数换算后交给 `terminal_exec`（`:809`）。

**`terminal_exec` 自己的时限：**

- 默认 120 秒、上限 600 秒（`server/services/terminal_exec.py:31-32`）。
- `timeout_of()` 把参数夹在 5–600 之间（`:64-69`）。
- 时限到了：整组杀掉进程，结果写成 `error: "stopped after N s"`（`:113-150`）。

**被循环掐掉时，模型拿到什么：**

- 只有一句 `tool 'run_command' timed out`，一行输出都没有（`tool_loop.py:1302-1303`）。

**输出可能在两层时限下都丢（推断，未跑测试证实）：**

- 按 CPython 3.11 的源码：`asyncio.wait_for` 取消 `proc.communicate()` 时，读取协程里已经读出的数据块会一起丢掉（`asyncio/streams.py` 的 `StreamReader.read`、`asyncio/subprocess.py` 的 `communicate`）。
- 所以 `terminal_exec.py:115-122` 杀掉进程后再调一次 `communicate()`，多半只拿到杀掉之后剩下的一点。
- 现有测试 `tests/server/test_run_command_executor.py:53-57` 只断言错误文字，没断言输出。
- 计划里「terminal_exec 超时时保留输出」这一句，要靠本 PR 的新测试来证实。

## 改哪些文件

- `server/registry/executors.py`：`RunCommandExecutor` 声明 `timeout_s = terminal_exec.MAX_TIMEOUT_S + 15`。
  - 外层留 15 秒余量，保证总是 `terminal_exec` 自己的时限先到、先带着输出返回。
  - 外层只作兜底。
- `server/services/terminal_exec.py`：
  - 输出改为边跑边读进两个缓冲区：两个读取任务，加 `wait_for(proc.wait(), timeout_s)`。时限到了，已经读到的输出不丢。
  - 杀掉进程之后，收尾读取最多等 5 秒。脱离进程组的子进程可能一直占着管道，不能无限等。
  - 超时的结果加结构化字段 `"code": "time_limit"`，保留现有的 `error: "stopped after N s"`，措辞不改。F2 认这个 code；M2 按 `error` 的固定文字计数（存在 `run_steps.detail` 里），改了措辞周报就数不到。
- `server/orchestrator/tool_loop.py:1302-1303`（热点文件，只改这一处）：
  - 外层兜底超时时，`run_command` 的结果改成「stopped by the time limit; no output was captured」，带上同一个 `code`。
  - 其他工具的措辞不变。
- `docs/CAPABILITY_INVENTORY.md`：rebase 后重新生成（`.venv/bin/python -m scripts.capability_inventory > docs/CAPABILITY_INVENTORY.md`）。它记着 `server/registry/*.py` 的哈希（`:122-126`），不重新生成 `tests/test_capability_inventory.py` 会红。
- 测试见「验收」。

## 不许碰

- `TOOL_TIMEOUT_S` 的数值。其他工具照旧 20 秒。
- `run_command` 的参数说明（`tool_loop.py:1516-1521` 已经写着默认 120、最长 600）。工具说明的整体改写归 K5。
- 聊天回合的预算和墙钟（`arslan/execution_budget.py`）。这些归 K4。
- `server/ws/bridge.py`、`desktop/bridge/**`。

## 怎么做（要点）

1. 先写验收里的测试，再改代码。「长命令能跑完」和「超时带输出」在 main 上应当失败，后者是按推断；「700 秒按 600 秒算」在 main 上已经成立，留作守卫。
2. 截断规则不变：输出照旧过 `fold_repeats` 和 `clip`，完整内容照旧落盘（`terminal_exec.py:131-146`）。
3. 被用户停止（`CancelledError`）的路径照旧整组杀掉、再抛出（`:123-130`）。不要把它当成超时。

## 验收（新测试，放在 `tests/server/test_run_command_executor.py` 或新文件）

- **长命令能跑完：** 以 `tool_timeout_s=1` 跑工具循环，命令是 `sleep 2; echo done`。
  - 结果 `ok`，输出里有 `done`。
  - 这证明循环不再拿自己的时限去掐 `run_command`。
- **请求 700 秒按 600 秒算：**
  - `timeout_of(700) == 600`；
  - 执行器把 600 传给了 `terminal_exec.run`（替换掉 `run` 来抓参数，不真等）。
- **超时带输出：** 命令是 `echo started; sleep 30`，`timeout_s` 设 5（最小就是 5）。
  - 结果 `ok` 为假；
  - `code == "time_limit"`；
  - stdout 里有 `started`；
  - 用时小于 15 秒。
- **原有测试照旧通过：** `test_a_timeout_stops_the_command_and_its_children`（`:53-57`）。

## 量级

产品代码约 40–60 行，外加测试。

## 风险与回退

- **聊天回合的墙钟仍会挡长命令：** 软限 600 秒，1.5 倍硬停 900 秒（`arslan/execution_budget.py:30`、`:85-98`）；整个回合还套着 `asyncio.timeout`（`:309-326`）。
  - 一条 600 秒的命令会把聊天回合推进收尾，甚至撞上硬停。
  - 本卡不改这些，归 K4。PR 里要写明这一点。
- **真机上要过一遍 §5.3 第 1 条**（1–2 分钟的命令），确认它在聊天回合的墙钟内跑得完。
- **回退：** revert 合并提交即可。没有存下来的状态。
