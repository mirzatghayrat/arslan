# F1 `run_command` 的时限跟它自己的参数走，超时也把输出交给模型

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.62 |
| 分级 | 必须 |
| 依赖 | F5a |
| 合并位置 | 合进 `release/0.1.62`；F5a 之后，和 F3、F4a、F4b 不分先后；F2 要排在本卡之后（它认本卡的 `code`）。发版后随分支合回 main |
| 推动的门槛 | §5.2「`run_command` 的时限类失败 = 0」；§5.3 第 1 条；§5.1 新题「长命令」 |
| 分支 | `claude/0162-f1-command-timeout`（从 `release/0.1.62` 拉，PR 的 base 是 `release/0.1.62`） |
| 迁移号 | 无 |

## 目标

1. **时限按命令自己的参数算。** 一条命令能跑满它自己的时限：默认 120 秒，最长 600 秒。工具循环不再统一在 20 秒掐断它。
2. **时限不超过回合剩下的时间。** 取「请求的时限」和「回合剩余时间 − 余量」里小的那个，和 `delegate_work` 的做法一样（`tool_loop.py:1270`）。否则回合自己的超时先到，命令被整个掐掉，一行输出都拿不到（审查 §3）。
3. **超时也把输出交给模型。** 不管是哪一层的时限到了，模型都能拿到 stdout / stderr 的尾巴，外加一句「被时限停止」。

## 现状（亲核）

**谁在掐 20 秒：**

- 循环给每个工具 20 秒（`server/orchestrator/tool_loop.py:31`，`TOOL_TIMEOUT_S = 20.0`）。
- 只有声明了 `timeout_s` 的执行器能拿到更长的时间（`:1269-1271`）：取 `max(20, own)`，再用 `asyncio.wait_for` 包住。`delegate_work` 例外，直接用 `budget.remaining_seconds()`（`:1270`）。
- `RunCommandExecutor`（`server/registry/executors.py:775-816`）没有声明 `timeout_s`。它只把参数换算后交给 `terminal_exec`（`:808-809`）。

**回合自己的时限：**

- 回合和任务外面套着 `asyncio.timeout(budget.remaining_seconds())`：`arslan/execution_budget.py:317`（`governed`），任务里是 `server/services/task_service.py:361`。
- 聊天回合软限 600 秒，硬停是 1.5 倍、900 秒（`execution_budget.py:30`、`:85-98`）。等卡的时间不算（`:228-286` 的暂停）。

**`terminal_exec` 自己的时限：**

- 默认 120 秒、上限 600 秒（`server/services/terminal_exec.py:31-32`）。
- `timeout_of()` 把参数夹在 5–600 之间（`:64-69`）。
- 时限到了：整组杀掉进程，结果写成 `error: "stopped after N s"`（`:113-150`）。
- 输出用 `proc.communicate()` 一次读完，没有上限（`:115`）。一条刷屏的命令能把内存吃光。

**被循环掐掉时，模型拿到什么：** 只有一句 `tool 'run_command' timed out`，一行输出都没有（`tool_loop.py:1302-1303`）。

**输出可能在两层时限下都丢（推断，未跑测试证实）：**

- 按 CPython 3.11 的源码：`asyncio.wait_for` 取消 `proc.communicate()` 时，已经读出的数据块会一起丢掉。
- 所以 `terminal_exec.py:115-122` 杀掉进程后再调一次 `communicate()`，多半只拿到杀掉之后剩下的一点。
- 现有测试 `tests/server/test_run_command_executor.py:54-58` 只断言错误文字，没断言输出。

## 改哪些文件

- `server/registry/executors.py`（`RunCommandExecutor`）：
  - 声明 `timeout_s = terminal_exec.MAX_TIMEOUT_S + 15`，外层只作兜底。
  - 实际时限 = min(`timeout_of(请求值)`, 回合剩余 − 30 秒)。剩余时间从当前预算取（`execution_budget.current()`），和 `delegate_work` 一样。30 秒余量留给命令返回后那一次收尾的模型调用。
  - 算出来不到 5 秒（`terminal_exec` 的下限）时不启动命令，直接返回 `ok: False`、`code: "time_limit"`、`executed: False`（F2 认 `executed: False`）。
- `server/orchestrator/tool_loop.py`（热点文件，只改两处）：
  - `:1269-1271`：`run_command` 的外层兜底 = min(615, 回合剩余 − 10 秒)。顺序因此固定：`terminal_exec` 先到，外层兜底其次，回合超时最后。
  - `:1302-1303`：外层兜底超时时，`run_command` 的结果改成「stopped by the time limit; no output was captured」，带同一个 `code`。其他工具的措辞不变。这句新的固定文字告诉 ⓪Plan，M2 按它计数（M2 卡「`run_command` 的时限类失败」那一行）。
- `server/services/terminal_exec.py`：
  - 输出改为边跑边读：两个读取任务，加 `wait_for(proc.wait(), timeout_s)`。时限到了，已经读到的输出不丢。
  - **缓冲设上限**（审查 §3）：每一路最多留 8 MB，超出时只留开头和结尾，丢掉多少写进结果。落盘的完整输出同样受这个上限。
  - 杀掉进程之后，收尾读取最多等 5 秒。脱离进程组的子进程可能一直占着管道，不能无限等。
  - 超时的结果加结构化字段 `"code": "time_limit"`，保留现有的 `error: "stopped after N s"`，措辞不改。F2 认这个 code；M2 按 `error` 的固定文字计数（存在 `run_steps.detail` 里），改了措辞周报就数不到。
- `docs/CAPABILITY_INVENTORY.md`：rebase 到 `release/0.1.62` 后重新生成（`.venv/bin/python -m scripts.capability_inventory > docs/CAPABILITY_INVENTORY.md`）。它记着 `executors.py` 的哈希（`:122`），不重新生成 `tests/test_capability_inventory.py` 会红。冲突时随便取一边，再重新生成，不手工合。
- 测试见「验收」。

## 不许碰

- `TOOL_TIMEOUT_S` 的数值。其他工具照旧 20 秒。
- `run_command` 的参数说明（`tool_loop.py:1516-1521` 已经写着默认 120、最长 600）。工具说明的整体改写归 K5。
- 聊天回合的预算和墙钟本身（`arslan/execution_budget.py`）。这些归 K4。
- `server/ws/bridge.py`、`desktop/bridge/**`。

## 怎么做（要点）

1. 先写验收里的测试，再改代码。「长命令能跑完」和「超时带输出」在 v0.1.61 上应当失败，后者是按推断；「700 秒按 600 秒算」已经成立，留作守卫。
2. 截断规则不变：输出照旧过 `fold_repeats` 和 `clip`，长输出照旧落盘（`terminal_exec.py:131-146`）。
3. 被用户停止（`CancelledError`）的路径照旧整组杀掉、再抛出（`:123-130`）。不要把它当成超时。
4. 30 秒、10 秒两个余量和 8 MB 上限写成模块常量，注释写明为什么是这个数。

## 验收（新测试，放在 `tests/server/test_run_command_executor.py` 或新文件）

- **长命令能跑完：** 以 `tool_timeout_s=1` 跑工具循环，命令是 `sleep 2; echo done`。结果 `ok`，输出里有 `done`。这证明循环不再拿 20 秒去掐 `run_command`。
- **请求 700 秒按 600 秒算：** `timeout_of(700) == 600`；回合剩余充足时，执行器把 600 传给了 `terminal_exec.run`（替换掉 `run` 来抓参数，不真等）。
- **不超过回合剩余：** 预算只剩 100 秒时，请求 600 秒，传给 `terminal_exec.run` 的是 70 秒。
- **没时间就不启动：** 预算只剩 20 秒时，`run` 没被调用，结果是 `code == "time_limit"`、`executed is False`。
- **后台任务同样适用**（审查 §3）：在后台任务的预算下（`job_budget`，`execution_budget.py:83-89`；后台任务走 `server/orchestrator/arslan.py:707-740` 的 `background_body`），剩余时间足够时请求 600 秒就给 600 秒，剩余不够时按上一条截短。
- **超时带输出：** 命令是 `echo started; sleep 30`，`timeout_s` 设 5（最小就是 5）。
  - 结果 `ok` 为假；`code == "time_limit"`；stdout 里有 `started`；用时小于 15 秒。
- **缓冲有上限：** 命令输出约 20 MB，内存里留下的不超过上限，结果里写了丢掉的字节数。
- **原有测试照旧通过：** `test_a_timeout_stops_the_command_and_its_children`（`:54-58`）。

## 量级

产品代码约 60–90 行，外加测试。

## 风险与回退

- **聊天回合的墙钟仍会挡长命令：** 一条 600 秒的命令会把聊天回合推进收尾，剩余时间不够时会被截短。本卡只保证截短时带着输出返回，不改墙钟本身（归 K4）。PR 里要写明这一点。
- **真机上要过一遍 §5.3 第 1 条**（1–2 分钟的命令），确认它在聊天回合的墙钟内跑得完。
- **留着的东西：** 外层兜底不是旧路径，是长期保留的安全网：`terminal_exec` 自己卡住时（比如收尾读取出了问题），由它把回合救回来。所以不设删除版本，代码注释写明这一点。
- **回退：** 在 `release/0.1.62` 上 revert 合并提交即可。没有存下来的状态。
