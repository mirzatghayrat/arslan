# M1B 基线结果：v0.1.62，2026-10-19

基线卡：[M1B-baseline.md](M1B-baseline.md)。这张表是 v0.1.63 每个 K 线 PR 比较的「前」。只放数字和必要的说明。

## 设置

| 项 | 值 |
|---|---|
| 被测版本 | v0.1.62（tag，`a4fca23b`），测试实例从空的数据目录起，跑完就关 |
| bench 代码 | M1 合并后的 main（驱动的动作卡策略按 #218：只批 T1 的「提醒事项」脚本、T12 的 Hands Fixture；T1 那一块跑在 #218 之前，所有题都没出过动作卡） |
| 模型 | DeepSeek：`deepseek-v4-pro`（推理档位用默认）；Claude：`claude-sonnet-5`（和用户的默认配置一致，用户定） |
| 参赛者 | Arslan v0.1.62；Hermes Agent v0.21.5（2026.9.24）；Claude Code 2.1.300（钉的 2.1.96 会发 `thinking.type: enabled`，claude-sonnet-5 不接受，用户同意改装 2.1.300） |
| 次数 | 每格 3 次（Pass^3），同一轮里参赛者交替跑 |
| 日期 | 2026-10-19 |

## 结果

「通过」按 judge v2：分数 3，且 Arslan 必须以 `done` 结束（停在「等你」算失败）。「答对」只看分数是不是 3。

| 题 | 模型 | 参赛者 | Pass^3 | 通过 | 答对（3 分） | 平均 $ | 平均模型用时 | 平均调用 | Arslan 停在「等你」的原因 |
|---|---|---|---|---|---|---|---|---|---|
| T1 | claude-sonnet-5 | arslan | 否 | 1/3 | 3/3 | 0.065 | 35s | 5.7 | task_checks_not_run×2 |
| T1 | claude-sonnet-5 | claude-code | 否 | 0/3 | 0/3 | 0.044 | 39s | 8.7 | **环境**：它的进程没拿到「提醒事项」权限，如实说做不到（1 分） |
| T1 | deepseek-v4-pro | arslan | 否 | 0/3 | 3/3 | 0.068 | 118s | 8.7 | task_checks_not_run×2（存下的 `.swift`）、task_reconciliation_required×1（一条 AppleScript 失败，F2 按设计当作结果不明；从实例的任务记录核对） |
| T1 | deepseek-v4-pro | hermes | 否 | 0/3 | 0/3 | 0.093 | 192s | 16.3 | **环境**：它的进程没拿到「提醒事项」权限，如实说做不到（1 分） |
| T2 | claude-sonnet-5 | arslan | 否 | 0/3 | 0/3 | 0.536 | 197s | 24.3 | task_no_progress×1 |
| T2 | claude-sonnet-5 | claude-code | 否 | 0/3 | 0/3 | 0.064 | 56s | 10.7 | **无效**：bench 沙箱里 Claude Code 的 Bash 写不了自己的临时目录、也没有网络 |
| T2 | deepseek-v4-pro | arslan | 否 | 0/3 | 1/3 | 0.210 | 337s | 30.7 | task_checks_not_run×2、task_no_progress×1 |
| T2 | deepseek-v4-pro | hermes | 是 | 3/3 | 3/3 | 0.230 | 402s | 24.0 |  |
| T3 | claude-sonnet-5 | arslan | 否 | 0/3 | 0/3 | 0.139 | 98s | 11.3 | task_no_progress×3 |
| T3 | claude-sonnet-5 | claude-code | 否 | 0/3 | 0/3 | 0.070 | 54s | 7.3 | **无效**：bench 沙箱里 Claude Code 的 Bash 写不了自己的临时目录、也没有网络 |
| T3 | deepseek-v4-pro | arslan | 否 | 1/3 | 2/3 | 0.060 | 92s | 9.7 | task_checks_not_run×1 |
| T3 | deepseek-v4-pro | hermes | 是 | 3/3 | 3/3 | 0.064 | 99s | 10.0 |  |
| T5 | claude-sonnet-5 | arslan | 否 | 0/3 | 3/3 | 0.143 | 74s | 8.7 | task_checks_not_run×3 |
| T5 | claude-sonnet-5 | claude-code | 否 | 0/3 | 0/3 | 0.057 | 58s | 10.7 | **无效**：bench 沙箱里 Claude Code 的 Bash 写不了自己的临时目录、也没有网络 |
| T5 | deepseek-v4-pro | arslan | 否 | 1/3 | 3/3 | 0.151 | 297s | 11.3 | task_checks_not_run×2 |
| T5 | deepseek-v4-pro | hermes | 是 | 3/3 | 3/3 | 0.076 | 188s | 10.0 |  |
| T7 | claude-sonnet-5 | arslan | 否 | 0/3 | 3/3 | 0.071 | 82s | 9.3 | job_blocked×1、job_partial×1、task_checks_not_run×1 |
| T7 | claude-sonnet-5 | claude-code | 否 | 0/3 | 0/3 | 0.098 | 89s | 22.0 | **无效**：bench 沙箱里 Claude Code 的 Bash 写不了自己的临时目录、也没有网络 |
| T7 | deepseek-v4-pro | arslan | 否 | 0/3 | 3/3 | 0.018 | 93s | 5.7 | task_checks_not_run×3 |
| T7 | deepseek-v4-pro | hermes | 是 | 3/3 | 3/3 | 0.018 | 72s | 5.0 |  |
| T8 | claude-sonnet-5 | arslan | 否 | 0/3 | 0/3 | 0.123 | 116s | 18.0 | task_checks_not_run×2、task_input_required×1 |
| T8 | claude-sonnet-5 | claude-code | 否 | 2/3 | 2/3 | 0.064 | 47s | 13.3 |  |
| T8 | deepseek-v4-pro | arslan | 否 | 0/3 | 1/3 | 0.064 | 142s | 14.0 | task_checks_not_run×3 |
| T8 | deepseek-v4-pro | hermes | — | — | — | — | — | — | 不支持：hermes: several turns in one session not set up |
| T9 | claude-sonnet-5 | arslan | 否 | 0/3 | 3/3 | 0.037 | 18s | 6.0 | task_checks_not_run×3 |
| T9 | claude-sonnet-5 | claude-code | 是 | 3/3 | 3/3 | 0.039 | 30s | 8.3 |  |
| T9 | deepseek-v4-pro | arslan | 否 | 0/3 | 3/3 | 0.033 | 37s | 7.7 | task_checks_not_run×3 |
| T9 | deepseek-v4-pro | hermes | 是 | 3/3 | 3/3 | 0.025 | 18s | 5.7 |  |
| T10 | claude-sonnet-5 | arslan | 是 | 3/3 | 3/3 | 0.056 | 18s | 5.7 |  |
| T10 | claude-sonnet-5 | claude-code | 是 | 3/3 | 3/3 | 0.757 | 60s | 17.0 |  |
| T10 | deepseek-v4-pro | arslan | 是 | 3/3 | 3/3 | 0.023 | 31s | 6.7 |  |
| T10 | deepseek-v4-pro | hermes | 是 | 3/3 | 3/3 | 0.071 | 27s | 7.3 |  |
| T11 | claude-sonnet-5 | arslan | 是 | 3/3 | 3/3 | 0.048 | 29s | 12.0 |  |
| T11 | claude-sonnet-5 | claude-code | — | — | — | — | — | — | 不支持：claude-code: no way to decline a card with a note |
| T11 | deepseek-v4-pro | arslan | 否 | 1/3 | 1/3 | 0.024 | 48s | 9.7 | 另外 2 次以 `done` 结束，但答案不对（没停在「等你」） |
| T11 | deepseek-v4-pro | hermes | — | — | — | — | — | — | 不支持：hermes: no way to decline a card with a note |

**没有跑的题：**
- T4、T4x（登录后盯页面）：所有参赛者都标「—」。Arslan 和 Claude Code 按设计不支持；Hermes 浏览器怎么保持登录还没配好（bench README 里列着的未完成项）。
- T6（发到手机）：「—」。Hermes 的 Telegram 启动还没验证；另外两个没有消息通道。
- T12（Hands）：不在基线里，只用于 K1 的验收（见下）。

## 这张表说明了什么（一两句一条）

- **Arslan 的分大多是答对了却停在「等你」：** 两个模型上，Arslan 停在「等你」的原因主要是 `task_checks_not_run`。它顺手存下的辅助文件（`.swift` 等）检查器没有解析器，记成「没跑」，挡住了成功。这正是新卡 D2（#221，已合并）修的事；D2 之后这几格要重跑。
- **另几类停止原因：**
  - `task_no_progress`（Claude 上的 T2 一次、T3 三次）和 `task_budget_exhausted`（K1 合并前那一次的 T2）归 K4；
  - 后台作业被挡或只做了一部分（Claude 上的 T7：`job_blocked`、`job_partial` 各一次）；
  - `task_input_required` 一次（Claude 上的 T8）；
  - `task_reconciliation_required` 一次（DeepSeek 上的 T1）是 F2 有意的谨慎：一条 AppleScript 失败了，没法确定它有没有动到外面。
- **Claude Code 那一列有 4 格无效**（T2、T3、T5、T7）：bench 沙箱里它的 Bash 写不了自己的临时目录、也没有网络，每次都如实说做不到。这是 bench 的问题，修好后重跑这 4 格；所以「Claude 上对 Claude Code」这条门槛现在还没法核。
- **Hermes 和 Claude Code 的 T1** 都是 1 分：它们的进程没拿到「提醒事项」权限，如实说了做不到。这是本机授权的差别，不是能力的差别。

## 和 10-02 那轮的差别

新加了 T7–T11（长命令、三轮追问、精确修改、长日志、被拒后换路），判分改成 judge v2（停在「等你」算失败），Claude 上加了 Arslan 和 Claude Code，所以和 10-02 的总分不能直接比。

## §5.1 门槛用这张表重新核

| 门槛 | 今天（v0.1.62） | 说明 |
|---|---|---|
| 不退步 | — | 这张表本身就是「前」 |
| DeepSeek 上对 Hermes（全套 Pass^3） | Arslan 1 格 / Hermes 6 格 | 差距大多来自「检查没跑」（D2）；D2 之后先重跑再判断门槛要不要调 |
| Claude 上对 Claude Code | 暂时没法核 | Claude Code 有 4 格无效，修好 bench 后重跑 |
| 新题（T7、T8、T11）3/3 | DeepSeek：T7 0/3、T8 0/3、T11 1/3；Claude：T7 0/3、T8 0/3、T11 3/3 | T7、T8 Arslan 答对了但停在「等你」 |

门槛值暂时不调，等 D2 和 bench 修好后重跑这几格再说（⓪Plan 建议，由用户拍板）。

## K1 验收的「合并前」那一次（claude-sonnet-5-5，v0.1.62）

用户定：K1 的验收用 `claude-sonnet-5-5`，K1 合并前后各跑一次。这是合并前那一次，走旧路径（K1b 之前 Claude 的原生协议没开），所以验不出思考块和 `input_transformations`，只当逐题的对照。

| 题 | 分数 | 通过 | $ | 模型用时 | 调用 | 停在「等你」的原因 |
|---|---|---|---|---|---|---|
| T1 | 3/3 | 否 | 0.152 | 61s | 14 | task_reconciliation_required |
| T2 | 2/3 | 否 | 0.487 | 140s | 11 | task_budget_exhausted |
| T8 | 2/3 | 否 | 0.184 | 119s | 21 | task_checks_not_run |
| T9 | 3/3 | 否 | 0.085 | 41s | 11 | task_checks_not_run |
| T12 | 3/3 | 是 | 0.087 | 36s | 9 | — |

T12：三次带截图的查看，读回了标题，报出了保存后的状态。点击结果是「发了、没确认」，它没有再点一次，而是再看了一眼。

## 花费（以代理记的为准）

| 代理 | 总数 | 说明 |
|---|---|---|
| DeepSeek（:8900） | $3.77 | 含冒烟测试和第 3 轮重跑；第 3 轮中途 DeepSeek 账户余额用完（HTTP 402），用户充值后重跑了那 9 次 |
| Claude（:8901） | $8.83 | 含冒烟测试、作废的 Arslan T1 三次（bench 的列表名撞了，已修 #219，已重跑）和 K1 合并前的五次 |

## 作废、重跑过的

- DeepSeek 第 3 轮的 9 次（Arslan 的 T7–T11、Hermes 的 T5、T7、T9、T10）：撞上余额不足（402），充值后重跑，表里是重跑的数。
- Claude 上 Arslan 的 T1 三次：bench 的列表名没带模型，提醒加进了 DeepSeek 那一跑的列表（每条两份，判 0 分）。修复见 #219，表里是重跑的数。
