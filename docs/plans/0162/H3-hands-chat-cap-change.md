# H3 去掉聊天里 Hands 自己的上限，Stop 对聊天回合也停住

| 项 | 内容 |
|---|---|
| 道 | ③Hands |
| 版本 | v0.1.63 |
| 分级 | 应该（U6：③Hands 交了 H1、用户点头之后才做；赶不上 v0.1.63 就顺延） |
| 依赖 | H1（用户 2026-10-18 已同意，决定 U8）、K4（K4a、K4b 都合了以后） |
| 合并位置 | K4b 之后 |
| 推动的门槛 | D4「聊天和后台同一套规矩」；§5.3 第 2 条（Hands 的场景不被要求转后台）；§5.4「CI 全绿」与 Hands 冒烟 |
| 分支 | `claude/0162-h3-hands-chat-cap-change` |
| 迁移号 | 无 |

## 目标

按决定 U8（H1 的推荐，用户 2026-10-18 同意）做两件事，**在同一个 PR 里**：

1. 去掉聊天回合里 Hands 自己的「最多 5 次」和「一轮一个 App」，并进 K4 的聊天步数上限。
2. 把 Hands 的 Stop 补成对聊天回合也停住：今天聊天回合没有 job id，Stop 只停正在跑的那一步，下一步照样能做（`hands_service.py:385-397`、`hands_tools.py:972`）。改完以后，同一回合后面的 Hands 调用都返回 `stopped_by_user`，和后台任务一样。第 1 件依赖它，不能单独合。

H1 列出的那些保护都要留着：每个 App 一张卡、危险步骤每次问、永不碰名单、借前台时等用户停手、Stop。被上限挡下时，告诉模型的话要和 K4 的新说法一致。

## 现状（亲核，K4 合并后要再核一次）

- 上限和计数：`server/registry/hands_tools.py:918-933`。
- 两处检查：
  - `_DesktopAct.execute`：`:962-969`；
  - `desktop_open`：`:1289-1296`，计数在 `:1328`。
- 「一轮只在一个 App」：`:1000-1006`。
- 被挡时的话：`_inline_refusal`（`:923-925`），现在说的是「Call start_background_work」。K4 会删掉「Do NOT do such work inline」，这句要跟着改。
- 规则的出处：`docs/specs/2026-10-08-0157-hands-v2.md:350-354`（§5.7）、`:122`（D-inline）。

## 改哪些文件

- **`server/registry/hands_tools.py`：**
  - 删 `INLINE_ACTIONS`、`_inline` 计数和上面两处检查，删「一轮只在一个 App」（`:1000-1006`），删 `_inline_refusal`；
  - 聊天回合调用 Hands 时，先查这个（对话, run）有没有被 Stop 停住。
- **`server/services/hands_service.py`：** `stop_running_jobs`（`:385-392`）旁边，把按下 Stop 时正在跑的聊天回合（对话, run）也记成已停；`stopped()` 认这两种。
  - **认哪些回合：** 按下 Stop 时**所有**在跑的聊天回合，不只限已经调过 Hands 的，和 `stop_running_jobs` 标所有在跑的后台任务一致。名单用 `server/services/desktop_status.py` 的 `_working`（它记着在跑的回合和对话），不在 `hands_tools` 里另记一份。
  - **什么时候清：** 回合结束就删掉标记，挂在回合结束的回调上（`desktop_status.when_work_ends`），不然标记越攒越多。同一对话的下一个回合 run 不同，不受影响（③Hands 审 #188）。
- **Hands 的 trace：** 加 `mode_used` 字段（只加字段），M2 用它数一个聊天回合里借前台的次数（H1 回答第 5 条）。
- **`scripts/hands_smoke.py:423-428`：** 冒烟项按新规则改。
- **测试：**
  - 按新规则改：`tests/server/test_hands_0153.py:397-408`、`tests/server/test_hands_p2_2.py:62`；
  - 新加的测试见「验收」。
- **`docs/specs/2026-10-08-0157-hands-v2.md`：** 在 §15「Amendments」里加一条修订，写日期、新规则和 H1 的结论。§5.7 原文不改。
  - 这份 spec 有代码引用，留在 main 上（决定 D13）。
- **`docs/CAPABILITY_INVENTORY.md`：** 不在本 PR 里改。C5b（#201）之后能力清单只在发版 PR 里重新生成（R63），两次发版之间 main 上的那份本来就会过时（2026-10-21 ③Hands 提出，⓪Plan 改卡）。

## 不许碰

- 卡片和授权：`_decide_app`、`_decide`、`permissions.decide`；
- 危险词表：`hands_service.risky_label` 等；
- 永不碰名单；
- 接管：照旧只在后台任务里；
- `server/orchestrator/**`：K4 的文件，本卡只读它的新规则；
- Bridge 文件。

## 怎么做（要点）

1. 开工前，把 H1 的回答和 K4 的合并提交都读一遍。核对聊天回合现在的步数上限和墙钟，再和 H1 的方案对一遍。
2. 先写 Stop 的测试：今天聊天回合里按 Stop 后，下一次 Hands 调用照样送出（红）；改完返回 `stopped_by_user`（绿）。
3. 再去掉上限：被挡下时 Hands 不再有自己的话，到了 K4 的上限就说 K4 统一的那句。`desktop_batch` 一批算一次工具调用，K4 要是按「步」算，跟它对齐。
4. 工具说明里提到「five」或「in one app」的地方一起改（开工时 grep）。

## 验收

- **新测试：** 聊天回合里连续动 6 次以上、跨两个 App，都照常执行；每个 App 只问一次卡；到了 K4 的上限，返回 K4 统一的那句话。
- **新测试：** 聊天回合里按 Stop 之后，同一回合的下一次 Hands 调用不送到 Hands，返回 `stopped_by_user`；新的回合不受影响。
- **新测试：** 上限之内，每个 App 照旧一张卡，危险步骤照旧每次问。这两件不因为放宽而变少。
- **`desktop_batch`：** 一批算一次工具调用，跟 K4 的计法一致。
- **冒烟：** `scripts/hands_smoke.py:423-428` 那一项换成两项：聊天回合连续动 6 次以上照常执行；聊天回合里按 Stop，正在跑的一步 1 秒内停，同一回合下一次调用返回 `stopped_by_user`。再加一项：连着几次借前台、同时模拟用户打字，按键一个不丢、前台都还回来。③Hands 在开发版上跑全套，结果写进 PR。
- **跑分：** M1 里有 Hands 的题时，贴改动前后的对比（K 线规矩）。没有就写明「无对应题」。

## 量级

产品代码约 40–80 行（删上限约 −40，Stop 停聊天回合约 +40），外加测试、冒烟和 spec 修订。

## 风险与回退

- **放宽以后，一轮里占用 App 的时间变长。**
  - 靠 H1 确认过的那些保护兜底：Stop、等用户停手、每个 App 一张卡。
  - 冒烟要覆盖「用户中途动了鼠标或键盘」这一项。
- **聊天窗口自己的「停止」不给 Hands 发 `stop`**，正在跑的那一步会跑完（≤30 秒）。本卡不改，已记进 README §8。
- **本卡不留旧路径：** 上限和「一轮一个 App」整个删掉。
- **回退：** revert 合并提交，上限回到 5 次，Stop 回到只停当前一步。
