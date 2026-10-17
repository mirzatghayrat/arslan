# S1 MCP 按标注审批（R6）；定时任务不给后台工具（R7）

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | 0.1.62 |
| 分级 | 必须 |
| 依赖 | C1；F4a（`Request.once_only`）；F2、H2（`executed: False` 的约定）；F3 先合更好（同一条 MCP 调用链） |
| 合并位置 | C1 之后随时。K4 若同时开着，排在 K4 之后：两张都改 `server/orchestrator/arslan.py:1040-1052`。不碰 C2c / C4 / S4 改的确认阶梯 |
| 推动的门槛 | §5.4：R6、R7 各一个回归测试；MCP 的卡都写账本。附录 A「MCP 工具逐次审批」落后 → 追平，「定时任务」保持追平 |
| 分支 | `claude/0162-s1-mcp-approval` |
| 迁移号 | 无。标注已存在 `tools.annotations`；授权用现有的 `permission_grants` |

## 目标

- **R6：MCP 调用今天不经过任何审批。**
  - `MCPProxyExecutor.execute`（`server/mcp/executor.py:239-304`）在 `:253` 直接 `manager.call_tool`。
  - `permissions.KINDS` 里早有 `mcp_tool`（`server/services/permissions.py:43-46`），但没有调用方。
- **按服务器自报的标注决定。** 标注 0.1.61 已存好：`tool_hints` 读出（`server/mcp/discovery.py:131-154`），`:213-225` 写进 `tools.annotations`（列在 `server/db/models.py:229`，由 `server/db/migrations/versions/_0068_mcp_state.py:47-48` 加）。
  - `readOnlyHint: true`：直接放行，记一行账本；
  - `destructiveHint: true`：每次问，只给「这一次」；
  - 其余：出卡，窗口上默认勾「本对话」。
- **定时任务里，非只读的 MCP 调用一律拒绝。** 不读本对话授权；写一行账本，收件箱列出。
- **R7：定时任务里不再提供 `start_background_work`。**
  - 今天的条件只看 `current_task()` 和 `inside_job()`（`server/orchestrator/arslan.py:1040`）。
  - 定时任务两样都满足：`_fire`（`server/services/scheduler.py:515-525`）经 `task_context.execute_entry` 走 `task_service.run_turn`（`server/services/task_context.py:131-156`），不设 job 标记。于是它能开一个后台任务，借那个任务把卡弹到窗口上（⓪Plan 提案 §6 第 6 条）。

## 改哪些文件

- `server/mcp/executor.py`
  - `execute` 在 ready 检查之后、`call_tool` 之前做决定，读同一个 `Tool` 行的 `annotations`。
  - `timeout_s`（`:215`，130 秒）改成 `approvals.TIMEOUT_S` 加上原来的 130 秒。
    - 原因：卡在执行器里等，而工具循环按执行器自报的时限掐（`server/orchestrator/tool_loop.py:1266-1272`）；不改的话，卡开着 130 秒就被掐掉。
    - Hands 是同一做法（`server/registry/hands_tools.py:51-56`）。
    - 真正的调用仍由 `CALL_BOUND_S` 限住（`executor.py:35-39`）。
- `server/mcp/discovery.py`：在 `tool_hints` 旁加两个纯函数 `read_only(hints)`、`destructive(hints)`。K9（只读并行）和 S5（计划模式）复用它们。
- `server/services/permissions.py`：加一个小函数（例如 `refuse_unattended(req, ctx)`）：不查规则和授权，直接写一行 `decided_by=policy` 的拒绝。写法同 `_ask` 里「没人可问」那一支（`:342-351`）。
- `server/orchestrator/arslan.py:1040`：条件加上 `permissions.current_asker() is not None`。
  - 定时任务不绑任何卡面，`scheduler.py:473-505` 的文档写明了这一点，所以这就是「定时任务」的判据。
- `server/registry/task_tools.py:49`：执行器同样拒绝（双保险）。
- `server/services/task_service.py`
  - MCP 卡被拒、过期、没人可问时，调用没离开 Arslan，要算已知失败。
    - 结果带 `executed: False`（H2 的约定）。F2 合了以后，任何工具的这种结果都算已知失败（F2 卡第 ③ 条），`known_local_failure`（`:55-82`）就不用再改。
    - F2 还没合时，在 `:71-72`（`mcp_not_ready`）旁加一个码。
  - `effect_of` 的 MCP 分支（`:107-119`）：`readOnlyHint` 为真的也算 `read`。
- 网页（只改窗口卡的默认勾选）
  - `web/src/components/ActionApprovalCard.tsx:48-51`：初始 scope；
  - `web/src/components/kit/askParts.tsx`：加一个「默认勾本对话」的种类集合；
  - `tests/server/test_card_kinds.py`：把这个集合也纳入核对。
- `docs/CAPABILITY_INVENTORY.md`：C5b 没合时，改了 `task_tools.py` 就要重新生成。

## 不许碰

- **Bridge 帧格式。** 已核过 `desktop/bridge/Sources/BridgeCore/FrameMapper.swift`：
  - 未知的 `perm_kind` 回落到 `propose_action` 自己的规则（`:145-147`、`:206-214`）：`mcp_tool` 卡在手机上是 write 风险，只答第一项；
  - `destructive` 卡显示 delete。
  - 结论：不用改 Swift。如果想让手机默认「本对话」，就得改 `:185-196` 的 taskFirst 标题，那时**停下来找 ②Main / ⓪Plan**。
- **卡片选项顺序。** 不要把「本对话」排到 `options` 第一位：
  - 灵动岛和手机只答第一项（`server/services/approvals.py:41-43`）；
  - 灵动岛的按钮文字看 `options[0]`（`web/src/island/islandAsk.ts:92-96`）。
  - 排到第一位，手机上的「允许」就会悄悄变成整段对话的授权。
- 本卡不给「总是」。和 site、shortcut 同理（`permissions.py:59-63`）：能列出、删除它的页面是 S6，排在「可以」。
- ③Hands 的文件；确认阶梯（C2c、C4、S4 的地盘）；F3 的 schema 规整。

## 怎么做（要点）

1. **种类。**
   - 普通调用：`kind="mcp_tool"`，`target` = 工具 key，`always_label=""`；
   - 破坏性调用：用现成的 `destructive`，加上 F4a 给 `Request` 新增的 `once_only=True`（只给「这一次」，不查规则和授权）；`extra` 里记 MCP 工具名。
   - 用 `destructive` 的理由：网页把它画红（`askParts.tsx:73`），灵动岛不让答（`approvals.py:289-293` 不含它），手机显示 delete，一行都不用改。
   - 如果 ⓪Plan 坚持全部用 `mcp_tool`：要在 `island_may_answer`（`approvals.py:315-318`）里另加判断，而且手机上只能显示 write。
2. **卡的样子。**
   - 框：`protocol.propose_action(call_id, "mcp_tool", "<服务器>/<工具>", <参数 JSON>)`，照测试里已有的写法（`web/src/__tests__/inbox-cards.test.tsx:27-28`）；
   - 标题：`Use <服务器>’s <工具>?`。
3. **只读放行也记一行账本**：`permissions.record_standing(req, ctx, by="mode")`（`permissions.py:232-240`），账本才数得全。
4. **定时任务**（`current_asker() is None`）：非只读调用走 `refuse_unattended`。
   - 这一行属于 `permission_store.NOT_ASKED`（`server/services/permission_store.py:20-27`），`GET /approvals/refused`（`server/api/approvals.py:59-88`）会列出它。
   - 不给「总是」，所以收件箱里这一条没有「总是允许」按钮。
5. **拒绝的结果**：`{"ok": False, "code": …, "executed": False, "external": False}`。`external: False` 是因为这是 Arslan 自己的话，不当网页内容包；正文用 `Decision.model_text`。
6. **后台任务里**照常出卡（BroadcastAsker：窗口、收件箱、灵动岛、手机）。

## 验收

- **测试：**
  - 只读：不出卡，一行账本（`decided_by=mode`）。
  - 破坏性：卡只有「这一次」，`island_may_answer` 为假。
  - 其余：卡给「这一次 / 本对话」。答「本对话」后，同一对话再调同一工具不出卡，账本记 `grant`。
  - **R6 回归：** 定时任务里调一个非只读工具：
    - 即使有本对话授权也被拒，不出卡；
    - 一行 `policy` 账本，`/approvals/refused` 列出它；
    - 结果算已知失败，不以「需要你核对」收场。
  - **R7 回归：** 没绑卡面时组出来的工具表里没有 `start_background_work`；执行器在没卡面时也拒绝。
  - 卡等过 130 秒不被掐：断言 `timeout_s >= approvals.TIMEOUT_S`，并用一个慢的假 asker 跑一遍。
  - 网页：`mcp_tool` 卡默认勾「本对话」；`destructive` 卡只有一个选项。
- **手动：** 打开一个工具多的 MCP 服务器，普通对话照常（§5.3 第 4 条不退步）。

## 量级

- 产品代码约 +120 行：服务端约 100，网页约 20。
- 测试约 +200 行。

## 风险与回退

- **标注是服务器自报的。** 谎报「只读」的写操作会免卡。
  - 只有用户自己打开的服务器（`host_allowed`）才会被调用，所以把只读放行视为对服务器的信任。
  - 「不信这个服务器的标注」的开关记进 0.1.63 候选。
- **MCP 规范里 `destructiveHint` 缺省为 true**（只在 `readOnlyHint` 为 false 时有意义）。
  - 本卡按计划，把「没写标注」算「其余」（本对话），不按规范缺省算破坏性。
  - 若 ⓪Plan 要按规范：只改 `destructive()` 一行；代价是没写标注的工具每次都问。
- **回退：** 整个 PR revert；或者临时让 `read_only()` 恒为 False，所有 MCP 调用都出卡。
