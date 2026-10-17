# S5 一个模式设置：谨慎 / 标准 / 完全访问 / 计划

| 项 | 内容 |
|---|---|
| 道 | ②Main（完全访问对 Hands 种类的处理：③Hands 审） |
| 版本 | v0.1.63 |
| 分级 | 应该 |
| 依赖 | S2a（标准 = 三层）；S1（计划模式要用 MCP 的只读判断）；C4；F4a（`Request.once_only`）；S3（「不问」文件夹里的改动和删除，前提是能撤销）；S4b（软：没有它，只有工作文件夹算「能撤销」） |
| 合并位置 | S2a、S3 之后。S4a 若同时开着，排在 S4a 之后：S4a 把两份阶梯合成一份，本卡就只用改一处。改 `server/orchestrator/tool_loop.py`、`server/orchestrator/arslan.py`：热修版 v0.1.62 发布前 `tool_loop.py` 不接别的 PR；有 K 线 PR 开着就排在它后面 |
| 推动的门槛 | D9；审查 U4；附录 A「权限模式」中游 → 追平、「计划模式」落后 → 追平（领先路线 L12） |
| 分支 | `claude/0162-s5-mode-setting` |
| 迁移号 | 无：设置键值 |

## 目标

- **四个读取者，各回落各的 → 一个设置、一个读取函数。** 今天的 `shell_confirm_policy` 有 4 处读取，读不出来时的做法各不相同：
  - `server/orchestrator/tool_loop.py:826-834`：读不出算 `ask_all`（每条都问）；
  - `server/services/permissions.py:484-493`：读不出算 `standard`，只用来写账本；
  - `server/services/approvals.py:502`、`server/ws/arslan.py:575`：不接异常，直接抛。
  - 设置本身：`server/services/settings_service.py:409-413`。
- **四个值：**
  - **谨慎**：今天的 `ask_all`，每条命令都问；
  - **标准**：S2a 的三层；
  - **完全访问**：要先确认，开着时一直显示标记。原则是**能撤销的不问，撤不回的照问**（审查 U4，用户已批）：
    - **照问：** 付款（`money`）；安装能力（`capability`）；往外发送或提交，含 S2a 第②层的发信、发消息、上传、`git push`、发布，种类 `send`，网站上动手（`site`），以及读过外部内容后的联网卡（它防的就是借脚本往外发，仍给「本对话」）；AppleScript 和快捷指令（`apple-events`、`shortcuts`、Hands 的 `shortcut`）；改系统；检查点覆盖不到的删除（工作文件夹和允许的文件夹以外）；读不懂的命令。
    - **只给「这一次」的，任何模式下都不能被记住，也不被模式放行：** `_ONCE_ONLY` 里的种类（`permissions.py:54-55`，含 `remote`、`system`、`app_risky`、`takeover`）和带 `Request.once_only` 的请求。
    - **禁止层照旧。**
    - **不问：** 其余，含工作文件夹和允许的文件夹里的修改、删除（S3 能撤销，新建的文件撤销时进废纸篓），以及出沙箱、工作区写入、普通 MCP 调用、定时。
  - **计划**：只读。非只读的工具一律拒绝；`exit_plan` 出一张卡，批准后回到原来的模式接着做（领先路线 L12 的追平部分）。

## 改哪些文件

- `server/services/settings_service.py`
  - 新增 `permission_mode(db)`，返回 `careful | standard | full | plan`；
  - 新键 `permission_mode`。没设过就从 `shell_confirm_policy` 推出来（`ask_all` → careful，其余 → standard），并当场写进新键；
  - 另一个键 `permission_mode_before_plan`，存进计划模式之前的模式；
  - **读不出来一律算 careful**（执行面宁关），只有这一处回落；
  - 键登记在 `:19-35` 的 `_PLAIN_KEYS`、`server/schemas.py`、`web/src/api/adapters.ts`、`web/src/api/client.types.ts`。
- **四个读取者都改成用它**（S4a 已合并阶梯时，阶梯里只剩一处）。
- `server/services/permissions.py`
  - `_mode()` 改用它，账本的 `mode` 列从此有 4 个值；
  - **完全访问这一档**：放在付款之后、规则之前，即文件头 `:16-17` 写的「Approve for me and Full access … slot in between 1 and 2」的位置。
    - 放行条件：不在上面「照问」的种类里，不在 `_ONCE_ONLY` 里，请求不带 `once_only`。放行时记 `by=mode` 的账本行。
    - 「照问」写成一个常量：种类 `money`、`capability`、`send`、`site`、`shortcut`，加命令卡目标 `network:*`（其余照问的都已是只给「这一次」）。单独测试；`decide_many` 同样处理。
  - **新种类 `plan`**：加进 `KINDS`（`:43-46`）。请求带 F4a 加的 `once_only=True`，所以不用动 `_ONCE_ONLY` 和网页的 `ONCE_ONLY_KINDS`。
- `server/orchestrator/tool_loop.py`
  - 在 `run_native` 逐个处理调用的循环里（`:2388` 起），参数校验之后、`propose_capability` 等特例之前，加计划模式的门。特例在 `_dispatch_tool`（`:920`）之外处理，只守 `_dispatch_tool` 会漏掉它们：
    - 放行：`task_service._READ_TOOLS`（`server/services/task_service.py:37-45`）、MCP 只读工具（S1 的 `discovery.read_only`）、`exit_plan`、`update_plan`、`ask_user_choice`；
    - 其余一律拒绝，告诉模型「现在是计划模式，只能读；写好计划后调用 `exit_plan`」。
  - **完全访问下的命令：**
    - 禁止层照旧；第②层和读不懂的，照样出「这一次」卡；
    - 其余在沙箱外跑，不出卡，套 S2a-1 的最小配置，再加一条：工作文件夹、允许的文件夹、临时和缓存以外，不许删文件（`(deny file-write-unlink …)`，内核挡；`rm` 以外的脚本删除也挡得住）；
    - 被这条挡下，出「沙箱外重跑」卡，只给「这一次」；批准后这一次去掉它；
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
  - `web/src/components/settings/AdvancedSection.tsx:311-327`：今天的二选一，改成四个模式。切到完全访问前弹确认框，分两栏写清楚：仍然会问的（照上面的列表），不再问的（文件夹里的改动和删除，可以按回复撤销；在沙箱外跑命令）。
  - `web/src/components/OrchestratorChat.tsx:1140-1147`：今天只在 `ask_all` 时显示一行字，改成输入框旁一直显示的模式标签，点开能切换。完全访问时标签是红色的，一直在。
  - 6 种语言的新文案按冲突协议加。C1c 没合时，同一个 PR 改 `web/src/__tests__/locale-parity.test.ts:300` 的计数。
- `docs/CAPABILITY_INVENTORY.md`：新增了工具，C5b 没合时要重新生成。

## 不许碰

- **Bridge 帧格式。** 已核过 `desktop/bridge/Sources/BridgeCore/FrameMapper.swift`：`plan` 是未知的 `perm_kind`，回落到 `propose_action` 的规则，标题取帧里的 `title`（`:41-59`、`:145-147`）。手机能看见标题、能答第一项（「这一次」）。要在手机上看计划全文，是 v0.1.64 的事（L12），需要改 Swift → **停下来找 ②Main / ⓪Plan**。
- **③Hands 的文件。** 计划模式下，Hands 的动作工具在工具循环里就被拒，不改 `hands_tools.py`。
- **「终端沙箱」开关**（`AdvancedSection.tsx:328-345`）本卡不动；它和模式怎么合并，记进 v0.1.64 候选。
- 「替我审批」：D8 已撤回；AI 审批员是 v0.1.65 的事（D7）。

## 怎么做（要点）

1. **先做读取函数**，把四个读取者换过去，行为不变（谨慎、标准两个值），全量测试过。
2. **再加完全访问和计划**，各自带测试。
3. **在 Mac 上实测 `file-write-unlink`**：`rm`、`python3` 的 `os.remove` 和 `shutil.rmtree`、`mv` 出文件夹，都要被挡。实测不成立时，完全访问下的命令改为在工作区沙箱里跑（出沙箱照问），PR 里写明。
4. **Hands 种类由 ③Hands 审：** 本卡默认 `app`、`screen` 放行，`site`、`shortcut` 照问；`app_risky`、`takeover` 在 `_ONCE_ONLY` 里，任何模式都照问。③Hands 要调前四种，只改「照问」那个常量。
5. **后台任务和定时任务都按当时的模式。** 计划模式下，后台任务里的写操作也被拒。
6. **`shell_confirm_policy` 的推导代码，注释写「v0.1.64 删」。**

## 验收

- **测试：**
  - 设置读不出来时，四处都按谨慎处理（这是新的回落测试）；
  - 没设过 `permission_mode` 时，`ask_all` 的老用户读出来是谨慎，且新键已写入；
  - 完全访问：
    - 工作文件夹里 `rm -rf` 一个子文件夹、出沙箱、工作区写入、普通 MCP 调用都不出卡，各写一行 `mode` 账本；
    - 付款、安装能力、`git push`、`curl --data …`、`osascript`、读不懂的命令、`remote`、`app_risky`、读过网页后的 `curl` 照样出卡，且只给「这一次」的不出「本对话」；
    - 删工作文件夹以外的文件：命令写明的出卡；藏在脚本里的被内核挡下，再出卡（`macos` 标记）；
    - 禁止的命令照样拒；
  - 计划模式：
    - `write_file`、`run_command`、非只读 MCP 都被拒；`read_file`、`web_search` 照常；
    - `exit_plan` 批准后，同一回合能写文件；拒绝后，仍是计划模式；
  - 网页：切到完全访问必须经过确认框；开着时标签一直显示。
- **手动：** 计划模式下让它「整理下载文件夹」：它只出计划；批准后接着做完。

## 量级

产品代码约 +300 行：服务端约 180，网页约 120。

## 风险与回退

- **完全访问下，命令在沙箱外跑，能读 `~/.ssh` 和各种凭据**（S2a-1 的最小配置只挡 Arslan 自己的数据）。往外发仍要过联网卡或第②层的卡，所以读得到也发不出去；没读过外部内容的回合，网络本来就开着，靠的是那一轮没有外来指令。确认框写明。
- **完全访问下，覆盖（不是删）文件夹以外的文件不问，也撤不回。** U4 只把删除列为照问。确认框写明。
- **计划模式挡掉了 `run_command`**，计划时不能 `ls`、`git log`，只能用文件工具读。「计划模式下用只读沙箱跑命令」记进 v0.1.64 候选。
- **留着的旧东西：** `shell_confirm_policy` 键和从它推导的代码，v0.1.64 删（那时所有用户都已写入新键）。代码注释写同样的话。
- **回退：** 整个 PR revert。新的设置键留着没有害处；`shell_confirm_policy` 在 v0.1.64 之前一直保留，老代码照旧读它。
