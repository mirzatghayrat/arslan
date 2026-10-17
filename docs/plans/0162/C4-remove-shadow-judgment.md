# C4 删影子评判；记下撤回决定 ②（D8）

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.63 |
| 分级 | 必须 |
| 依赖 | C1、C2c |
| 合并位置 | README §3 的链：C2c → **C4** → S2a → S4a。<br>也在 S2a 之前：S2a 卡写明要排在 C2c、C4 之后。<br>`server/ws/arslan.py` 不是 K 线热点，但 K2 改它的回合锁；K2 开着时，本卡排在 K2 后面 |
| 推动的门槛 | 无直接门槛；净减代码。间接：每张命令卡少一次后台模型调用。近 30 天的本机汇总里，52 张命令卡有 25 张影子评判没给出结论，其中 24 次是超时（reduce-proposal §1） |
| 分支 | `claude/0162-c4-remove-shadow-judgment` |
| 迁移号 | 无（`judgments` 表、`approval_events.reviewer` 列都保留） |

## 目标

影子评判（`tool.approval`）只记录，不参与任何决定，还经常超时。用户已撤回 10-11 的决定 ②「替我审批」（D8）。

删掉影子评判的全部接线，以及「活动」页里它的那一类行。spec 里写一句「已撤回」，免得以后有人照旧 spec 去做。

v0.1.65 要做的窄版审批员（D7），本卡不做，但给它留着：账本的 `reviewer` 列（`server/db/models.py:513`）。

## 改哪些文件

以下内容都在 `fb6d7230` 上核过。

`server/services/judgment.py`：
- 删 `tool.approval` 这个决策点（`:61-64`）。
- 删只给它用的函数：`approval_state`（`:217-227`）、`shadow`（`:230-235`）、`record_outcome`（`:238-257`）、`record_outcome_later`（`:260-264`）。
- `TIMEOUT_S`（`:32`）也只给它用：其余决策点都是 `after_turn=True`，见 `:190`。删掉它，`:190` 改成只用 `AFTER_TURN_TIMEOUT_S`。
- `:36` 的 `DAILY_TOKEN_CAP` 不要跟着删：所有决策点都用它，**保留**。

`server/services/approvals.py`（任务里的卡）：
- `_ask_with_shadow`（`:523-531`）改成直接 `self._card(frame)`；调用点在 `:496`。
- `_decide_with_shadow`（`:533-557`）改成在 `permissions.asking_with(self.asker)` 下直接 `decide`；调用点在 `:521`。
- 只删 shadow、`judged` 和 `record_outcome` 那几行；阶梯的其余部分不动。

`server/ws/arslan.py`（窗口里的卡）：
- `_sandbox_card`（`:533-548`）里的 `judgment.shadow`、`record_outcome_later`。
- `_decide_with_shadow`（`:600-626`）照上面一样改成直接 `decide`；调用点在 `:598`。
- `latest_request` 只给影子评判提供用户原话：定义在 `:294`，写入在 `:703`、`:793`。连同这三处一起删。

其他：
- `scripts/judgment_replay.py:47`：默认 `--point` 改成仍存在的决策点，或者改成必填。
- 网页：
  - `web/src/components/JudgmentsCard.tsx:21` 删 `tool.approval` 的映射；
  - `:38` 的 `tool.` 图标分支，没有别的 `tool.*` 决策点了，一起删；
  - 6 种语言的 `pointApproval`（`web/src/locales/panel.ts:40`、`:102`、`:164` 等）。
- 「活动」页不再显示旧的 `tool.approval` 行。在 `GET /judgments`（`server/api/judgments.py:13-17`）或 `judgment.recent()` 里过滤掉它。旧行留在库里，按 `KEEP_DAYS = 90` 自然清掉。
- spec：`docs/specs/2026-10-11-0161-smooth.md`
  - §12.1 第 2 条（`:1369`）下面加一行：「2026-10-17 用户撤回（v0.1.63 决定 D8）：不做『替我审批』，影子评判已删。窄版审批员见 v0.1.65（D7）。」
  - §A6 标题下（`:627`）加同样一行，并注明 `:663` 那句「影子评判继续」不再成立。
  - 只加这两处注记，不改写 spec 正文。
- 测试：删影子评判的测试；改 `approvals` 和 `ws` 里断言 `judgment.shadow` 被调用的测试。

## 不许碰

- 其他决策点及它们的调用方：`memory.*`、`job.accomplished`、`project.progress*`；`turn.completion` 是关着的，也不动。
- `judgments` 表、`judgment.judge`、`recent`、`prune`；`approval_events.reviewer` 列（D7 要用）。
- 确认阶梯本身：
  - 合并两份流程、出沙箱卡改走 `decide` 是 S4a；
  - 三层命令规则是 S2a。
- Bridge 契约文件。

## 怎么做（要点）

1. 先跑一遍引用，把结果贴进 PR：

   ```bash
   rg -n "tool\.approval|judgment\.(shadow|record_outcome|approval_state)|latest_request" server scripts web/src
   ```

2. 改完 `_decide_with_shadow` 的两个副本，确认卡片的「表面」绑定没丢：
   - 任务里仍是 `self.asker`；
   - 窗口里仍是 `permissions.current_asker()`，见 `ws/arslan.py:608`、`:620`。
3. 推送前跑 ruff。

## 验收

- 本地全量绿、CI 绿，贴 run id。
- 新测试：窗口里和任务里各弹一张命令卡并回答。`judgments` 表里没有新行，卡的结果和账本记录照旧。
- 上面那条 `rg` 命令只剩 spec 里的历史文字。
- 手动：「活动」页的判断列表里看不到「这条命令要问你吗？」这一类行。

## 量级

产品代码约 −150 到 −200 行；6 种语言各少 1 个 key；spec 加 2 行。

## 风险与回退

- **留着的旧路径和删除条件**（`docs/sessions.md` §9；代码注释里也写）：`judgments` 表和 `approval_events.reviewer` 列，留给 v0.1.65 的窄版审批员（D7）。v0.1.65 做了就接着用；那一版决定不做，就在那一版删列、删表。
- **风险：** M2 周报里 `judgments` 那一列会归零。这是预期的，M2 卡里已写明。
- **风险：** C2c、S2a、S4a 都改同一组阶梯。按 README 的顺序合，后合的 rebase。
- **风险：** C5a 也改这份 spec，删的是 `:3`、`:8-12` 和 §0.1–0.2，和本卡加注的两处不重叠。后合的那个 rebase。
- **回退：** revert 本 PR。表没删，回退后影子评判照旧写入。
