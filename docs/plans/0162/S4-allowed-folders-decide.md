# S4 「允许的文件夹」；出沙箱卡和远程卡走 `decide()`

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | 0.1.62 |
| 分级 | 应该 |
| 依赖 | S3（问得少了，就得回得去）、C4（先删掉同一组阶梯里的影子评判）；S2a 也要先合（同一组阶梯） |
| 合并位置 | 按 README §3：C2c → C4 → S4，S3 → S4 → S6；也在 S2a 之后。S5 若同时开着，S4 先合：S4 把两条阶梯合成一条，S5 就只用改一处 |
| 推动的门槛 | §5.4「所有卡片都写账本」；附录 A「审批日志」；⓪Plan 提案 §5.2：0.1.61 之后用户答的 21 张卡里，12 张是出沙箱卡 |
| 分支 | `claude/0162-s4-allowed-folders` |
| 迁移号 | 无：文件夹存设置键值；授权用现有的 `permission_grants` |

## 目标

1. **「允许的文件夹」：用户选一次，之后在这些文件夹里写东西，就在沙箱里直接做，不出卡。** 这是减卡的主力。
2. **出沙箱卡和远程卡改走 `decide()`**，种类分别是 `outside`、`remote`（都在 `permissions.KINDS` 里，今天没有调用方）。这样每张都写账本、进收件箱、能撤销。今天它们绕开了 `decide()`：
   - 任务：`server/services/approvals.py:492-498`（出沙箱）、`:508-511`（远程）；
   - 窗口：`server/ws/arslan.py:533-548`（出沙箱卡）、`:566-571`、`:581-587`。
   - 现在的出沙箱卡不写账本。过期的卡，在影子评判里被记成「拒绝」（`server/ws/arslan.py:546-547`，handover §6）。
3. **内存里的「本对话剩余时间」出沙箱授权，改成存库的本对话授权，后台任务也认。**
   - 今天它在 `command_sandbox._granted`（`server/services/command_sandbox.py:44`、`:191-201`）：重启就没，看不见，任务里不认（`server/orchestrator/tool_loop.py:1059-1063` 只认窗口的回调）。
4. **窗口和任务的两条确认阶梯合成一条。**
   - 窗口：`server/ws/arslan.py:506-631`；任务：`approvals.py:436-557`。各约 125 行，只有三处不同。

## 改哪些文件

- **设置：** 新键 `allowed_folders`，存绝对路径的 JSON 列表。
  - 要登记的地方：`server/services/settings_service.py:20-35` 的 `_PLAIN_KEYS`、`server/schemas.py` 两个 schema、`web/src/api/adapters.ts`、`web/src/api/client.types.ts`。
  - 校验：必须存在、必须是文件夹；不能是 `/`、家目录本身、系统根目录或受保护路径（`default_protected`，`server/services/command_sandbox.py:88-103`）。
- **命令沙箱：**
  - `default_writable`（`command_sandbox.py:82-85`）加上允许的文件夹。
  - 「桌面、文稿、下载」关着时，允许的文件夹若在它们里面，要重新打开。`profile` 已经能处理这种情况（`command_sandbox.py:128-136`）。
  - 调用处：`server/registry/executors.py:792-812`。
- **S3 的命令检查点**：范围加上允许的文件夹，沿用 S3 的克隆和上限。
- **文件工具：** 在允许的文件夹里写也不出卡。
  - `server/registry/file_tools.py:80-92` 的 `_resolved` 认多个根；
  - `server/services/workspace_paths.py:52` 的 `resolve_in_workspace` 不改规则，只是多试几个根；
  - `_writing_in_own_folder`（`server/orchestrator/tool_loop.py:898-906`）改成看写入的路径。
  - 这一部分若让本卡超过 800 行，拆成 S4b。
- **新模块**（例如 `server/services/command_confirm.py`）：一条阶梯。
  - 包括命令卡、出沙箱、远程、工作区写入、定时；
  - 用 `permissions.current_asker()` 取卡面，用传进来的 `Context` 带 `job_id`。
  - 窗口（`server/ws/arslan.py:506-598`）和任务（`approvals.JobConfirmations`，`approvals.py:436-521`）只剩薄壳。
- **出沙箱：**
  - `Request(kind="outside", target="*", conversation_ok=True, always_label="")`，选项是「这一次 / 本对话」；
  - 「本对话」= 这段对话里的命令都可以在沙箱外跑，和今天的复选框同义；
  - 沙箱拦下后的重跑卡（`tool_loop.py:1283-1290`）走同一个请求。
- **远程：** `Request(kind="remote", …)`，`remote` 本来就只给「这一次」（`server/services/permissions.py:54-55`）。
- `server/orchestrator/tool_loop.py`
  - `:1059-1063`：不再读 `command_sandbox.granted`，改成「这一对话有没有 `outside` 授权」，经 `decide()` 查，并写账本行（`by=grant`）。
  - 有授权时，命令直接在沙箱外跑，后台任务也一样；S2a 第③层那张「不进沙箱」卡也不再出（授权就是同意）。
- **删除：**
  - `grant`、`granted`、`_granted`（`command_sandbox.py:44`、`:191-201`），以及 `_reset_for_tests`（`:204-208`）里对应的部分；
  - `confirm_command.honours_session_grants`（`server/ws/arslan.py:630`）。
- **网页：**
  - `web/src/components/settings/AdvancedSection.tsx`：在工作文件夹输入框旁（`:135-151`）加「允许的文件夹」列表，可加、可删；
  - 命令卡的「本对话」文案说清楚覆盖什么；
  - 6 种语言。C1c 没合时，同一个 PR 改 `web/src/__tests__/locale-parity.test.ts:300` 的计数。

## 不许碰

- **Bridge 帧格式。** 已核过 `desktop/bridge/Sources/BridgeCore/FrameMapper.swift`：
  - `perm_kind` 为 `outside` 时风险词是 install（`:206-214`）；
  - `remote` 不在映射里，回落到命令文字规则，带 `remote_host` 就是 send（`:218-228`）；
  - 手机只答第一项（「这一次」）。不用改 Swift。
  - 多出来的 `title`、`options`、`expires_at` 等键，`decide()` 本来就会加，命令卡已经带着它们在跑。
- **灵动岛的行为不变：** `outside`、`remote` 不在可答的种类里（`approvals.py:308-312`），岛上显示现成的提示（`web/src/island/islandAsk.ts:64-77`）。
- **安装能力卡**（`server/ws/arslan.py:632-640`）不在本卡：那张卡要带回用户填的钥匙和文件夹，`decide()` 现在不传这些。
- 宽 profile、「Run it anyway」、按命令前缀记住：⓪Plan 提案 §5.2 明确不做。
- ③Hands 的文件。

## 怎么做（要点）

1. **先合并阶梯，行为不变**，全量测试过；再改出沙箱和远程。两步可以是同一个 PR 里的两个提交。
2. **无人可问时也走 `decide()`。** 定时任务里，工作区写入、定时、出沙箱、命令、远程这几种拒绝（`tool_loop.py:1008`、`:1027`、`:1067`、`:1087`、`:1110`）改为调用合并后的阶梯。
   - `decide()` 在没有卡面时立刻拒绝（`permissions.py:342-351`），不等，不出卡，写一行 `policy` 账本，收件箱列出。
   - 安全性不变，账本却补全了（`server/services/scheduler.py:487-489` 自己写着「这些拒绝还不写账本」）。
   - 远程那一支保持「先拒、后探测」（`server/orchestrator/tool_loop.py:1105-1119`）：没有卡面时先写 `policy` 行就返回，不跑 `prepare_confirmation`，定时任务连网络都不碰。
3. **过期就是过期。** 出沙箱卡没人答，记 `expired`，不再记成拒绝。
4. **升级后的第一次：** 内存里的旧授权随重启消失，不用迁移。

## 验收

- **测试：**
  - 允许的文件夹里，`cp`、`mv` 进去不出卡；文件夹外仍被沙箱拦下，出重跑卡。
  - 出沙箱卡答「本对话」后：同一对话的下一条命令在沙箱外跑，不出卡；后台任务也认；重启后还在；账本有 `grant` 行。
  - 远程卡只有「这一次」，每张都有一行账本。
  - 定时任务里被拒的命令和出沙箱请求，进 `/approvals/refused`。
  - 出沙箱卡过期时，记 `expired`。
  - 两条阶梯合并后，原有的窗口和任务测试都过。
- **M2（装上后 7 天）：** 出沙箱卡明显减少。

## 量级

- 产品代码约 +300 / −250 行：阶梯合并净减，文件夹和网页净增。
- 超过 800 行就拆 S4b（文件工具那部分）。

## 风险与回退

- **「本对话」的出沙箱授权变成存库的，而且任务也认，范围比今天大。**
  - 卡上写明「这段对话里的命令（包括后台任务）都可以在沙箱外跑」；
  - S6 的页面能看见、能删。
- **允许的文件夹里的改动只靠 S3 撤销。** 所以必须在 S3 之后合，并且 S3 的检查点要覆盖这些文件夹。
- **回退：** 整个 PR revert。设置键 `allowed_folders` 留着没有害处，旧代码不读它。
