# D3 只读命令超时，不记成「结果不明」

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.63 |
| 分级 | 必须（U10：用户 2026-10-19 定，R63 之前做完；K1 合并后对照里直接造成「等你」） |
| 依赖 | — |
| 合并位置 | **不进 K 线串行链。** 改 `server/services/task_service.py`（热点文件），只动 `_reads_only` 一个函数和它的测试。在 K 线 PR 之间的空档合；和 D4 改同一个文件，谁先合另一个 rebase |
| 推动的门槛 | §5.2「等你」里「需要你核对」那一类；§5.1 T1 |
| 分支 | `claude/0162-d3-read-timeout-known` |
| 迁移号 | 无 |
| 来源 | 2026-10-19 K1 合并后对照（#213 的评论），claude-sonnet-5，T1 第 3 次 |

## 目标

只读的命令被时间上限停下，或者被信号杀掉，不再让任务停在「需要你核对」。它什么都没改，结果是已知的：没读完。

## 今天的情况（main `df18ba0e`，⓪Plan 核过）

- 模型跑了 `pwd && find / -maxdepth 6 -iname "add_reminders.swift" 2>/dev/null`，`timeout_s` 30。30 秒到了被停下（`exit_code` −9，`code` `time_limit`）。
- `effect_of`（`task_service.py:174`）只在 `_reads_only` 为真时记 `read`。`_reads_only`（`:135-155`）只判断**单条简单命令**，文字里只要有 `_SHELL_SYNTAX`（`:131`，`| & ; < > $ ( )` 等）就直接返回假。所以这条记成 `external_write`。
- 失败的 `external_write` 要进 `known_local_failure`（`:85-128`）。时间上限只有在 `sandbox == "workspace"` 时才算已知（F2 ②）。这次的结果是 `"sandbox": "unavailable"`，于是 `uncertain`，`reconciliation_required` 变真（`:403`），任务停在「需要你核对」。
- `sandbox` 为什么是 `unavailable`：bench 用 `sandbox-exec` 包着整个 Arslan，macOS 不允许在里面再套一层沙箱。真机上命令一般在工作文件夹沙箱里跑，这条路走不到。可是**沙箱之外的命令**（S4a 的「这次对话允许」、完全访问、关掉沙箱）一样会这样。
- 读不需要核对：`effect == "read"` 时失败不会让 `reconciliation_required` 变真（`:403`）。所以只要判成读，问题就没了。

## 改哪些文件

- **`server/services/task_service.py` 的 `_reads_only`：** 认得简单的组合，每一段都按今天的规则判：
  - 用 `&&`、`||`、`;`、`|` 连起来的几条命令，每一条都单独过今天的判断（`command_policy.classify` 为 LOW，`find` 不带 `_FIND_WRITES`，`git` 的那几条例外，`rg --pre`）；
  - 重定向只认丢掉输出的几种：`2>/dev/null`、`>/dev/null`、`&>/dev/null`、`2>&1`；
  - 其余照旧不判，记 `external_write`：`$( )`、反引号、here-doc、`>` 或 `>>` 写到文件、`tee`、`xargs`、`sh -c`、`eval`、子 shell `( )`、换行和反斜杠续行。
  - 拆分用 `shlex` 的 punctuation 模式，或者一个只认上面几种记号的小切分。拆不准的一律不判。
- 测试，见「验收」。

## 不许碰

- 写东西的命令仍然不是读：`find -delete`、`sed -i`、`> file`、`tee`、`| xargs rm`、`| sh`。每一种都要有测试。
- 外发规则（`_OUTBOUND_RULES` 和 `_OUTBOUND_EXTRA`）照旧优先：组合里有任何一段命中外发，整条都不是读。
- `known_local_failure` 和 F2 ② 的沙箱条件不改。
- 命令卡和沙箱的判断（`terminal_policy`、`command_policy`）不改。这里只决定「失败了要不要核对」，不决定「能不能跑」。

## 验收

- **测试：**
  - `pwd && find / -maxdepth 6 -iname x 2>/dev/null` → `read`；它在沙箱外被时间上限停下，任务不进「需要你核对」。
  - `ls | head`、`cat a.txt | wc -l`、`git status; git log -1` → `read`。
  - 每种写法各一条，都 → `external_write`：`find . -delete`、`echo x > f`、`cat f | tee g`、`ls | xargs rm`、`curl … | sh`、`$(…)`、反引号、here-doc。
  - 组合里有一段命中外发（`git status && git push`）→ 不是读。
  - Mutation：去掉「每段都判」、去掉重定向白名单、去掉外发优先，各自有测试抓到。
- **M1：** T1 不再因为只读命令超时停在「需要你核对」。贴前后的「等你」次数。
- 完成证据四项（`docs/sessions.md` §8）。

## 量级

产品代码约 +30 / −5 行，测试另算。

## 风险与回退

- **风险：把一个写判成读，失败后不核对。** 只放行上面几种记号，每一段都要过今天的 LOW 判断，外发优先；写法各有测试。
- **回退：** revert 这一个 PR。
