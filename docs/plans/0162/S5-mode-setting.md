# S5 一个模式设置：谨慎 / 标准 / 完全访问 / 计划

| 项 | 内容 |
|---|---|
| 道 | ②Main（完全访问对 Hands 种类的处理：③Hands 审） |
| 版本 | 0.1.62 |
| 分级 | 应该 |
| 依赖 | S2a（标准 = 三层）；S1（计划模式要用 MCP 的只读判断）；C4；F4a（`Request.once_only`） |
| 合并位置 | S2a 之后。S4 若同时开着，排在 S4 之后：S4 把两条阶梯合成一条，本卡就只用改一处。要改 `server/orchestrator/tool_loop.py`、`server/orchestrator/arslan.py`，有 K 线 PR 开着就排在它后面 |
| 推动的门槛 | D9；附录 A「权限模式」中游 → 追平、「计划模式」落后 → 追平（领先路线 L12） |
| 分支 | `claude/0162-s5-mode-setting` |
| 迁移号 | 无：设置键值 |

## 目标

- **四个读取者，各回落各的 → 一个设置、一个读取函数。** 今天的 `shell_confirm_policy` 有 4 处读取，读不出来时的做法各不相同：
  - `server/orchestrator/tool_loop.py:826-834`：读不出算 `ask_all`（每条都问）；
  - `server/services/permissions.py:484-493`：读不出算 `standard`，只用来写账本；
  - `server/services/approvals.py:502`、`server/ws/arslan.py:575`：不接异常，直接抛。
  - 设置本身：`server/services/settings_service.py:411-415`。
- **四个值：**
  - **谨慎**：今天的 `ask_all`，每条命令都问；
  - **标准**：S2a 的三层；
  - **完全访问**：要先确认，开着时一直显示标记；付款和禁止层照旧（D9）；
  - **计划**：只读。非只读的工具一律拒绝；`exit_plan` 出一张卡，批准后回到原来的模式接着做（领先路线 L12 的追平部分）。

## 改哪些文件

- `server/services/settings_service.py`
  - 新增 `permission_mode(db)`，返回 `careful | standard | full | plan`；
  - 新键 `permission_mode`。没设过就从 `shell_confirm_policy` 推出来：`ask_all` → careful，其余 → standard；
  - 另一个键 `permission_mode_before_plan`，存进计划模式之前的模式；
  - **读不出来一律算 careful**（执行面宁关），只有这一处回落；
  - 键登记在 `:20-35` 的 `_PLAIN_KEYS`、`server/schemas.py`、`web/src/api/adapters.ts`、`web/src/api/client.types.ts`。
- **四个读取者都改成用它**（S4 已合并阶梯时，阶梯里只剩一处）。
- `server/services/permissions.py`
  - `_mode()` 改用它，账本的 `mode` 列从此有 4 个值；
  - **完全访问这一档**：放在付款之后、规则之前，即文件头 `:16-17` 写的「Approve for me and Full access … slot in between 1 and 2」的位置。除 `money`、`capability` 以外的种类，直接放行，记 `by=mode` 的账本行。
    - `capability` 也照旧问：那张卡要用户填钥匙、选文件夹，不是一个是或否。
    - `decide_many` 同样处理。
  - **新种类 `plan`**：加进 `KINDS`（`:43-46`）。请求带 F4a 加的 `once_only=True`，所以不用动 `_ONCE_ONLY` 和网页的 `ONCE_ONLY_KINDS`。
- `server/orchestrator/tool_loop.py`
  - 在 `run_native` 逐个处理调用的循环里（`:2388` 起），参数校验之后、`propose_capability` 等特例之前，加计划模式的门。特例在 `_dispatch_tool`（`:920`）之外处理，只守 `_dispatch_tool` 会漏掉它们：
    - 放行：`task_service._READ_TOOLS`（`server/services/task_service.py:37-45`）、MCP 只读工具（S1 的 `discovery.read_only`）、`exit_plan`、`update_plan`、`ask_user_choice`；
    - 其余一律拒绝，告诉模型「现在是计划模式，只能读；写好计划后调用 `exit_plan`」。
  - **完全访问下的命令**：禁止层照旧；其余直接在沙箱外跑，不出卡。
    - 不先在沙箱里试一次再重跑：同一条命令跑两遍可能有副作用。
    - S3 的检查点照常存。
- `server/orchestrator/arslan.py`
  - 计划模式下，工具表只给上面那几种，外加 `exit_plan`；
  - 告诉模型现在是什么模式：K3 合了就放进本轮的上下文块，没合就放系统提示的动态段。
- **`exit_plan` 的执行器**（例如放在 `server/registry/task_tools.py`）：
  - 参数：计划全文；
  - 走 `permissions.decide(Request(kind="plan", target=<计划第一行，≤300 字>, title="Start working on this plan?", detail=<计划全文>, once_only=True))`。手机只拿得到标题和 `target`，所以 `target` 要能看懂；
  - 批准：模式切回 `permission_mode_before_plan`，然后照 `propose_capability` 的做法，在同一回合里重新取一次工具表（`tool_loop.py:2437-2453`），接着做。
  - 定时任务里没有卡面，`decide()` 直接拒绝并写账本。
- `server/api/settings.py`：读写 `permission_mode`。
- **网页：**
  - `web/src/components/settings/AdvancedSection.tsx:311-327`：今天的二选一，改成四个模式。切到完全访问前弹确认框，写清楚哪些仍然会问：付款、禁止的命令、安装新能力。
  - `web/src/components/OrchestratorChat.tsx:1140-1147`：今天只在 `ask_all` 时显示一行字，改成输入框旁一直显示的模式标签，点开能切换。完全访问时标签是红色的，一直在。
  - 6 种语言的新文案按冲突协议加。C1c 没合时，同一个 PR 改 `web/src/__tests__/locale-parity.test.ts:300` 的计数。
- `docs/CAPABILITY_INVENTORY.md`：新增了工具，C5b 没合时要重新生成。

## 不许碰

- **Bridge 帧格式。** 已核过 `desktop/bridge/Sources/BridgeCore/FrameMapper.swift`：`plan` 是未知的 `perm_kind`，回落到 `propose_action` 的规则，标题取帧里的 `title`（`:41-59`、`:145-147`）。手机能看见标题、能答第一项（「这一次」）。要在手机上看计划全文，是 0.1.63 的事（L12），需要改 Swift → **停下来找 ②Main / ⓪Plan**。
- **③Hands 的文件。** 计划模式下，Hands 的动作工具在工具循环里就被拒，不改 `hands_tools.py`。
- **「终端沙箱」开关**（`AdvancedSection.tsx:328-345`）本卡不动；它和模式怎么合并，记进 0.1.63 候选。
- 「替我审批」：D8 已撤回；AI 审批员是 0.1.64 的事（D7）。

## 怎么做（要点）

1. **先做读取函数**，把四个读取者换过去，行为不变（谨慎、标准两个值），全量测试过。
2. **再加完全访问和计划**，各自带测试。
3. **完全访问对 Hands 的影响**（`app`、`app_risky`、`screen`、`takeover`、`site`、`shortcut` 也免卡）由 ③Hands 审：
   - 本卡默认按 D9 原文，只有付款和禁止层照旧（另加 `capability`）；
   - ③Hands 若认为 `app_risky` 或 `takeover` 必须照旧问，改「完全访问仍要问的种类」那一行即可。
4. **后台任务和定时任务都按当时的模式。** 计划模式下，后台任务里的写操作也被拒。

## 验收

- **测试：**
  - 设置读不出来时，四处都按谨慎处理（这是新的回落测试）；
  - 没设过 `permission_mode` 时，`ask_all` 的老用户读出来是谨慎；
  - 完全访问：
    - 命令卡、出沙箱卡、MCP 卡都不出，各写一行 `mode` 账本；
    - 付款照样出卡；
    - 禁止的命令照样拒；
  - 计划模式：
    - `write_file`、`run_command`、非只读 MCP 都被拒；
    - `read_file`、`web_search` 照常；
    - `exit_plan` 批准后，同一回合能写文件；拒绝后，仍是计划模式；
  - 网页：切到完全访问必须经过确认框；开着时标签一直显示。
- **手动：** 计划模式下让它「整理下载文件夹」：它只出计划；批准后接着做完。

## 量级

产品代码约 +250 行：服务端约 130，网页约 120。

## 风险与回退

- **完全访问会让发信、推送、删除都不问。**
  - 这是用户 10-11 的决定 ③（D9 保留），和 ⓪Plan 提案 §3.2「每次都问：付款、删除、发送、提交」有张力；
  - 确认框把这件事写在第一行；S3 的撤销只管工作文件夹。
- **计划模式挡掉了 `run_command`**，所以计划时不能 `ls`、`git log`，只能用文件工具读。「计划模式下用只读沙箱跑命令」记进 0.1.63 候选。
- **回退：** 整个 PR revert。新的设置键留着没有害处；`shell_confirm_policy` 一直保留，老代码照旧读它。
