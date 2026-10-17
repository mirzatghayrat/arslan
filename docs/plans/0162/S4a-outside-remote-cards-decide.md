# S4a 出沙箱卡和远程卡走 `decide()`、写账本；两份确认流程合成一份

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.63 |
| 分级 | 必须（§5.4「所有卡片都写账本」是发版门槛；审查 A2：原 S4 拆出的必须部分） |
| 依赖 | C4（先删掉同一组阶梯里的影子评判）；S2a（同一组阶梯，S2a-2 先改命令卡） |
| 合并位置 | 按 README §3 的链：C2c → C4 → S2a → **S4a** → S7；S4b 在本卡之后。S5 若同时开着，S4a 先合：两份阶梯合成一份，S5 就只用改一处。改 `server/orchestrator/tool_loop.py`：热修版 v0.1.62 发布前不接别的 PR；有 K 线 PR 开着就排在它后面 |
| 推动的门槛 | §5.4「所有卡片都写账本」；附录 A「审批日志」；⓪Plan 提案 §5.2：0.1.61 之后用户答的 21 张卡里，12 张是出沙箱卡 |
| 分支 | `claude/0162-s4a-cards-decide` |
| 迁移号 | 无：授权用现有的 `permission_grants` |

## 目标

1. **出沙箱卡和远程卡改走 `decide()`**，种类分别是 `outside`、`remote`（都在 `permissions.KINDS` 里，今天没有调用方）。这样每张都写账本、进收件箱、能撤销。今天它们绕开了 `decide()`：
   - 任务：`server/services/approvals.py:492-498`（出沙箱）、`:508-511`（远程）；
   - 窗口：`server/ws/arslan.py:533-548`（出沙箱卡）、`:566-571`、`:581-586`（远程）。
   - 现在的出沙箱卡不写账本。过期的卡，在影子评判里被记成「拒绝」（`server/ws/arslan.py:546-547`，handover §6；C4 删掉影子评判后，连这一行也没了）。
2. **内存里的「本对话剩余时间」出沙箱授权，改成存库的本对话授权，后台任务也认。**
   - 今天它在 `command_sandbox._granted`（`server/services/command_sandbox.py:44`、`:193-201`）：重启就没，看不见，任务里不认（`server/orchestrator/tool_loop.py:1059-1063` 只认窗口的回调）。
3. **窗口和任务的两份确认流程合成一份。**
   - 窗口：`server/ws/arslan.py:506-631`；任务：`approvals.py:436-557`。各约 125 行，只有三处不同。

## 改哪些文件

- **新模块**（例如 `server/services/command_confirm.py`）：一份阶梯。
  - 包括命令卡（含 S2a 的联网卡）、出沙箱、远程、工作区写入、定时；
  - 用 `permissions.current_asker()` 取卡面，用传进来的 `Context` 带 `job_id`；
  - 窗口（`server/ws/arslan.py:506-598`）和任务（`approvals.JobConfirmations`，`approvals.py:436-521`）只剩薄壳。
- **出沙箱：**
  - `Request(kind="outside", target="*", conversation_ok=True, always_label="")`，选项是「这一次 / 本对话」；
  - 「本对话」= 这段对话里的命令都可以在沙箱外跑（套 S2a-1 的最小配置），和今天的复选框同义；
  - 沙箱拦下后的重跑卡（`tool_loop.py:1283-1290`）走同一个请求。
- **远程：** `Request(kind="remote", …)`。`remote` 本来就只给「这一次」（`server/services/permissions.py:54-55`）。
- `server/orchestrator/tool_loop.py`
  - `:1059-1063`：不再读 `command_sandbox.granted`，改成「这一对话有没有 `outside` 授权」，经 `decide()` 查，并写账本行（`by=grant`）。
  - 有授权时，命令直接在沙箱外跑，后台任务也一样；S2a 第③层那张「不进沙箱」卡也不再出（授权就是同意）。
- **删除：**
  - `grant`、`granted`、`_granted`（`command_sandbox.py:44`、`:193-201`），以及 `_reset_for_tests`（`:204-208`）里对应的部分；
  - `confirm_command.honours_session_grants`（`server/ws/arslan.py:630`）。
- **网页：** 命令卡的「本对话」文案说清楚覆盖什么（「这段对话里的命令，包括后台任务，都可以在沙箱外跑」）；6 种语言。C1c 没合时，同一个 PR 改 `web/src/__tests__/locale-parity.test.ts:300` 的计数。

## 不许碰

- **Bridge 帧格式。** 已核过 `desktop/bridge/Sources/BridgeCore/FrameMapper.swift`：
  - `perm_kind` 为 `outside` 时风险词是 install（`:206-214`）；
  - `remote` 不在映射里，回落到命令文字规则，带 `remote_host` 就是 send（`:218-228`）；
  - 手机只答第一项（「这一次」）。不用改 Swift。
  - 多出来的 `title`、`options`、`expires_at` 等键，`decide()` 本来就会加，命令卡已经带着它们在跑。
- **灵动岛的行为不变：** `outside`、`remote` 不在可答的种类里（`approvals.py:309-312`），岛上显示现成的提示（`web/src/island/islandAsk.ts:64-77`）。
- **安装能力卡**（`server/ws/arslan.py:632-640`）不改走 `decide()`：那张卡要带回用户填的钥匙和文件夹（`extras`），`decide()` 不传这些。它的账本由 S7 补。
- 宽 profile、「Run it anyway」、按命令前缀记住：⓪Plan 提案 §5.2 明确不做。
- 「允许的文件夹」（S4b）；模式设置（S5）；③Hands 的文件。

## 怎么做（要点）

1. **先合并阶梯，行为不变**，全量测试过；再改出沙箱和远程。两步可以是同一个 PR 里的两个提交。
2. **无人可问时也走 `decide()`。** 定时任务里，工作区写入、定时、出沙箱、命令、远程这几种拒绝（`tool_loop.py:1008`、`:1027`、`:1067`、`:1087`、`:1110`）改为调用合并后的阶梯。
   - `decide()` 在没有卡面时立刻拒绝（`permissions.py:342-351`），不等，不出卡，写一行 `policy` 账本，收件箱列出。
   - 安全性不变，账本却补全了（`server/services/scheduler.py:487-489` 自己写着「这些拒绝还不写账本」）。
   - 远程那一支保持「先拒、后探测」（`tool_loop.py:1105-1119`）：没有卡面时先写 `policy` 行就返回，不跑 `prepare_confirmation`，定时任务连网络都不碰。
3. **过期就是过期。** 出沙箱卡没人答，记 `expired`，不再记成拒绝。
4. **升级后的第一次：** 内存里的旧授权随重启消失，不用迁移。

## 验收

- **测试：**
  - 出沙箱卡答「本对话」后：同一对话的下一条命令在沙箱外跑，不出卡；后台任务也认；重启后还在；账本有 `grant` 行。
  - 远程卡只有「这一次」，每张都有一行账本。
  - 定时任务里被拒的命令、出沙箱、远程请求，都进 `/approvals/refused`。
  - 出沙箱卡过期时，记 `expired`。
  - 两份阶梯合并后，原有的窗口和任务测试都过。
- **发版前（§5.4）：** 出沙箱、远程、命令、工作区写入、定时各触发一次，`approval_events` 里各有一行。

## 量级

产品代码约 +200 / −250 行：阶梯合并净减，出沙箱和远程各加一点。

## 风险与回退

- **「本对话」的出沙箱授权变成存库的，而且任务也认，范围比今天大。**
  - 卡上写明「这段对话里的命令（包括后台任务）都可以在沙箱外跑」；
  - S6 的页面能看见、能删。
- **本卡不留旧路径：** 内存授权和 `honours_session_grants` 直接删；窗口、任务两个薄壳是新阶梯的入口，不是兼容层。
- **回退：** 整个 PR revert。存库的 `outside` 授权留在表里，旧代码不读它们；重新合并后照常生效。
