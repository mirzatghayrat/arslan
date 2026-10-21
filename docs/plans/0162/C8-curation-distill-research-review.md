# C8 删掉整理层、回合结束提炼和研究复核

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.63 |
| 分级 | 应该（用户 2026-10-21 定「现在就删」，U13 第 2 条） |
| 依赖 | C1（已合）；研究类回答的引用要求写进 K5 的工作方法（见 K5 卡） |
| 合并位置 | C 线，不进 K 线严格链；碰到 `arslan.py`、`tool_loop.py` 的部分，在 K 线 PR 之间的空档合；`distill_service` 和 C7 第二步缠在一起的部分，由 ②Main 在计划里定先后 |
| 推动的门槛 | 用户 2026-10-21 定的目标：到 v0.1.65 干净、简单、好用（`docs/sessions.md` §11） |
| 迁移号 | 无（表留着，见下面） |
| 来源 | ④参谋的清理清单 §2：整理层每 15 分钟跑一次，模型调用一次都没有过；回合结束提炼最后一次是 09-05；研究复核没有信号，开关却开着 |

## 删什么

- **整理层：**
  - `server/services/curation_loop.py`、`server/services/curator.py`；
  - 开机时挂上的每 15 分钟一次的循环；
  - 设置键 `curation_enabled`、`curation_backfill_from` 的读取代码（`server/services/settings_service.py:21`、`:32`、`:152`、`:235` 附近）；
  - 网页上的开关、提案箱里整理层那一类；`/skills/curator_review` 接口；
  - 对应的翻译键。
- **回合结束提炼：** `server/services/distill_service.py` 里回合结束那条入口、`server/services/prompts/distill.py`、设置键 `distill_on_session_end`（`settings_service.py:22`、`:218`）。分身的手动提炼（`server/api/conversations.py:171-198` 一带）是专家时代的，随 C7 第二步删。
- **研究复核：** 只删复核本身。
  - **先把 `compact_saved_context` 原样搬出去**（②Main 审 #284 时发现）。它也在 `server/orchestrator/research_review.py` 里（main 上 `:25`），但不是复核：所有非 Claude 的供应商存了报告以后都走它（`tool_loop.py:2891-2899`），把之前的网页正文换成收据。删掉它，DeepSeek 看到的东西就变了。所以一个字不改搬到别的模块，加一条测试证明搬前搬后它给模型的上下文逐字一样，再删复核。
  - 复核的各个出口一起删：`tool_loop.py` 里复核的函数（`:2168-2196` 一带）和调用它的地方（`:2880-2887`）；`research_source_feedback` 留着，`compact_saved_context` 要用；设置键 `research_review_enabled`（`settings_service.py:32`）和网页上的开关；`artifact_store` 里复核笔记的读写；`server/api/runs.py:527-538` 的接口；网页的 `ArtifactReviewNotes`（加它的测试）；`research_review` 这个帧。
  - 复核今天做什么（②Main 核过）：代码里默认关，你的设置里开着（④参谋查的）。开着时它不改回答，只多出三样：一行 `note`、一条存下的复核笔记，以及每次多一个模型请求。删掉以后，这三样就没了。
  - 它要做的事改成一句工作方法：「研究类回答只引用这一轮真正读过的来源，查不到的要明说」。写进 K5 的工作方法，由 K5 的测试管。
- 删了哪些、怎么确认没人引用：`git grep -w` 加按字符串查（注册表、翻译键、设置键），写进 PR（§11 第 4 条）。

## 留着的（写明删除期限）

- 数据库表：`_0013_distilled_sessions`、`_0034_curation_layer` 建的表。读写代码删掉以后，表里的数据没人读。
- 代码注释和 README §8 写 `DELETE-BY: v0.1.65`：v0.1.65 的「每 N 轮后台回顾一次」用一次迁移收掉这些表（§11 第 1 条，那张卡写明删它们）。
- 库里已存的设置值：不删、不迁移。读的代码没了，也就没人读了。

## 不许碰

- 记忆 v2 本身、回合后抽事实（K2 挪出回合锁的那条路）：归 v0.1.65 的记忆文件化。
- 提案箱的其他种类、后台任务、定时任务。

## 验收

- **测试：**
  - 开机后没有整理层的循环在跑；
  - 设置页没有这三个开关；
  - 回答路径不再调研究复核（删掉对应的测试，加一条「回答路径不 import `research_review`」）。
- CI 全量绿（附 run id）。不跑 DeepSeek 门槛，前提有两个：
  - 复核在回答之后跑，删掉它不改模型看到的东西；
  - `compact_saved_context` 原样搬走，并有「搬前搬后逐字一样」的测试。
  做不到第二条，就跑一次门槛。
- 产品代码净行数贴在 PR 里（§11 第 6 条）。
- 完成证据四项（`docs/sessions.md` §8）。

## 量级

产品代码约 −1.2k 行（整理层约 1.0k，研究复核约 0.2k），加翻译和测试。超过 800 行就按区域拆，整份删除照 U2 的例外。

## 风险与回退

- **风险：** 研究复核其实在某些回答上起作用。④参谋查到它没有留下任何信号。PR 里写明它在什么条件下会改回答、改了会不会留记录，读代码说清楚就行，不去翻你的数据。
- **回退：** revert。表和设置值都还在，恢复后照常能读。
