# H3 按 H1 的结论改聊天里的 Hands 上限

| 项 | 内容 |
|---|---|
| 道 | ③Hands |
| 版本 | v0.1.63 |
| 分级 | 应该（U6：③Hands 交了 H1、用户点头之后才做；赶不上 v0.1.63 就顺延） |
| 依赖 | H1（回答已获用户点头）、K4（K4a、K4b 都合了以后） |
| 合并位置 | K4b 之后 |
| 推动的门槛 | D4「聊天和后台同一套规矩」；§5.3 第 2 条（Hands 的场景不被要求转后台）；§5.4「CI 全绿」与 Hands 冒烟 |
| 分支 | `claude/0162-h3-hands-chat-cap-change` |
| 迁移号 | 无 |

## 目标

按 H1 里用户点过头的方案，改聊天回合里 Hands 的动作上限：放宽次数，或者改成按时长，或者并进 K4 的步数上限。

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
  - 上限的值或者算法：常量、`_inline` 计数，以及上面两处检查；
  - `_inline_refusal` 的文字。
- **`scripts/hands_smoke.py:423-428`：** 冒烟项按新规则改。
- **测试：**
  - 按新规则改：`tests/server/test_hands_0153.py:397-408`、`tests/server/test_hands_p2_2.py:62`；
  - 新加的测试见「验收」。
- **`docs/specs/2026-10-08-0157-hands-v2.md`：** 在 §15「Amendments」里加一条修订，写日期、新规则和 H1 的结论。§5.7 原文不改。
  - 这份 spec 有代码引用，留在 main 上（决定 D13）。
- **`docs/CAPABILITY_INVENTORY.md`：** rebase 后重新生成（`.venv/bin/python -m scripts.capability_inventory > docs/CAPABILITY_INVENTORY.md`）。

## 不许碰

- 卡片和授权：`_decide_app`、`_decide`、`permissions.decide`；
- 危险词表：`hands_service.risky_label` 等；
- 永不碰名单；
- 接管：照旧只在后台任务里；
- `server/orchestrator/**`：K4 的文件，本卡只读它的新规则；
- Bridge 文件。

## 怎么做（要点）

1. 开工前，把 H1 的回答和 K4 的合并提交都读一遍。核对聊天回合现在的步数上限和墙钟，再和 H1 的方案对一遍。
2. 如果方案是「并进 K4 的上限」：
   - 删掉 `INLINE_ACTIONS` 和 `_inline` 计数；
   - 「一个 App」的规则按 H1 的结论决定留不留；
   - 测试改成断言「到 K4 的上限才停」。
3. 如果方案是「按时长」：时钟的起点和暂停规则要和 K4 一致。等卡的时候不算时长，K4 保留了「等卡时暂停」。

## 验收

- **新测试：** 聊天回合里在同一个 App 连续动作。到新上限之前都照常执行；到了上限，返回 K4 统一的那句话。
- **新测试：** 上限之内，每个 App 照旧一张卡，危险步骤照旧每次问。这两件不因为放宽而变少。
- **`desktop_batch`：** 每一步照旧单独计数（或者按时长计）。
- **冒烟：** ③Hands 在开发版上跑一遍 `scripts/hands_smoke.py`，改过的那一项通过，其余和改动前一致。结果写进 PR。
- **跑分：** M1 里有 Hands 的题时，贴改动前后的对比（K 线规矩）。没有就写明「无对应题」。

## 量级

产品代码约 10–40 行，外加测试、冒烟和 spec 修订。

## 风险与回退

- **放宽以后，一轮里占用 App 的时间变长。**
  - 靠 H1 确认过的那些保护兜底：Stop、等用户停手、每个 App 一张卡。
  - 冒烟要覆盖「用户中途动了鼠标或键盘」这一项。
- **回退：** revert 合并提交，上限回到 5 次。
