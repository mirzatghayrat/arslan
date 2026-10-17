# S7 安装能力卡也写一行账本

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.63 |
| 分级 | 必须（§5.4「所有卡片都写账本」是发版门槛） |
| 依赖 | S4a（两份确认流程合成一份以后再改，少一处冲突）；C4 |
| 合并位置 | S4a 之后（链：C2c → C4 → S2a → S4a → S7）。不等 S4b。改 `server/orchestrator/tool_loop.py`：热修版 v0.1.62 发布前不接别的 PR；有 K 线 PR 开着就排在它后面 |
| 推动的门槛 | §5.4「所有卡都写账本」 |
| 分支 | `claude/0162-s7-capability-ledger` |
| 迁移号 | 无 |

## 目标

- S4a 把出沙箱卡和远程卡收进了 `decide()`。剩下没写账本的，只有「安装能力」这一张。
- 它今天走的是 `_ask_everywhere(..., broadcast=False)`（`server/ws/arslan.py:632-640`），不经过 `decide()`，所以不写账本。
- 它也不适合直接改走 `decide()`：卡要把用户填的钥匙和选的文件夹带回来（`extras`），而 `decide()` 不传这些（见 S4a 卡「不许碰」）。
- **本卡只补记录，不改卡本身。** 用户答完以后补写一行账本，没人可问时的拒绝也写一行。

## 改哪些文件

- `server/services/permissions.py`
  - 新增一个公开函数，例如 `record_card_outcome(req, ctx, *, approved, expired=False)`，写一行账本：
    - `decided_by`：`user` 或 `expired`；
    - `decision`：`allow` / `deny` / `expired`。
  - 今天的 `record_standing`（`:232-240`）只接受 `by="rule"` 或 `by="mode"`，不能拿来记用户的回答，所以要新加。
  - 写法复用内部的 `_record`、`_filled`、`_mode`。
  - 请求的种类用 `KINDS` 里已有的 `capability`；`target` 写能力的名字或来源，`detail` 不放钥匙。
- `server/ws/arslan.py:632-640`：`confirm_capability` 拿到回答后调用这个函数；过期（没人答）记 `expired`。
- `server/orchestrator/tool_loop.py:2437-2453`：后台任务里没有卡面时，今天直接不问（`:2445`）。在这里补写一行 `policy` 账本，这样收件箱能列出来。用 S1 新增的 `refuse_unattended`，或者同样的写法。
- **测试：**
  - 答应、拒绝、过期各写一行；
  - 账本行里没有钥匙；
  - 后台任务里的拒绝写一行 `policy`，并且出现在 `GET /approvals/refused`。

## 不许碰

- 卡的样子和它带回钥匙、文件夹的方式（0.1.57 §3.1 的约定）。
- Bridge 帧格式：这张卡本来就只在提问的窗口出现（`broadcast=False`），手机收不到，本卡不变。
- 确认阶梯本身（S4a 已合并）。

## 怎么做（要点）

1. 先写测试：今天答完这张卡，账本里什么都没有。
2. 加记录函数，在两处调用。
3. 确认 `detail` 和 `extra` 里不带钥匙。账本保留 90 天，钥匙不能进去。

## 验收

- 测试全过。
- 发版前核对 §5.4：把每一种卡各触发一次，`approval_events` 里每张卡都有一行。

## 量级

产品代码约 +40 行，测试约 +60 行。

## 风险与回退

- **风险：** 账本行里不小心带上用户填的钥匙。测试专门断言没有。
- **本卡不留旧路径。**
- **回退：** 整个 PR revert，卡的行为不受影响。
