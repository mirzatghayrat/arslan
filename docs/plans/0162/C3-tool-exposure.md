# C3 工具表：删用不了的，降级没人用的

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | 0.1.62 |
| 分级 | 必须（和 K7 一起） |
| 依赖 | C1；C1b 最好先合，因为 C1b 和 C3a 都改 `tests/server/test_deck_html_default.py` |
| 合并位置 | 两个 PR，都在 K5 合并之后、K7 开工之前合（README §3「C3 紧挨在 K7 之前」）：<br>• C3a 先合；<br>• C3b 紧挨着 K7。<br>C3a 改 `arslan.py`、`tool_loop.py`，C3b 只改 `arslan.py`，都是 K 线热点，按 `docs/sessions.md` §3 排在打开的 K 线 PR 之后。C3b 合并到 K7 合并之间不发版 |
| 推动的门槛 | 和 K7 一起推动 K7 的验收：每次请求的工具 JSON ≤ 约 12k 字符。间接：§5.2 的工具失败率，因为不再给模型用不了的工具 |
| 分支 | `claude/0162-c3a-remove-dead-tools`、`claude/0162-c3b-demote-unused-tools` |
| 迁移号 | 无（目录行用 seeder 的退役清单删，不写迁移） |

## 目标

- **C3a：删除。** 删掉给了模型也用不了的工具和目录项。
- **C3b：降级。** 近 30 天没人用的工具移出常驻工具表。K7 再让它们按需可取。

使用数字取自 reduce-proposal §2，只是汇总：
- 浏览器的 back、click、type、select、press：0 次；
- `delegate_work`、`create_skill`、`propose_capability`、`propose_plan_change`、`suggest_connector`：0 次；
- `run_python`：最后一次在 07-28；
- `render_deck`：0 次；
- SSH：登记的机器 0 台，`list_nodes` 3 次。

## 改哪些文件

**C3a 删除**（约 −700 行）

`render_deck` 和 deck 技能。deck 技能让主 agent 调 `render_deck`，可 `_arslan_tools` 从来不给主 agent 这个工具：
- `server/registry/executors.py`：`_DECK_MAX_*`（`:536-540`）、`_is_scalar`（`:545-547`，只给 deck 校验用）、`_deck_data_slide_error`（`:550-598`）、`DeckExecutor`（`:601-654`），以及 `EXECUTORS` 里的 `DeckExecutor()`（`:934`）。
- `server/services/deck_pptx.py`：456 行。
- `server/registry/seed_catalog.py`：`deck` 工具集（`:124-162`）、`deck-authoring` 技能行（`:225-228`）；再删 `arslan/spawn/seeds/deck-authoring/`。
- `server/registry/seeder.py`：`deck` 加进 `RETIRED_TOOLSET_KEYS`（`:40-47`），`deck-authoring` 加进 `RETIRED_SKILL_KEYS`（`:27-39`）。
- `server/orchestrator/tool_loop.py`：
  - `render_deck` 的参数表（`:1513-1515`）；
  - deck 声明检查 `_CLAIMS_DECK_RE`、`_claims_deck`（`:108-128`），以及 `_unverified_claim` 里的 deck 分支（`:1806-1807`）。
  - 这几处必须一起删：`render_deck` 没了以后，模型用 `run_command` 真做出 .pptx 再说「已生成」，也会被当成没有凭据的声明。
- 其他：`server/services/replay_safety.py:13`、`:44`；`server/services/task_service.py:41` 的 `_LOCAL_WRITE_TOOLS`。
- `packaging/server_entry.py:328`：打包自检要求能 import `server.services.deck_pptx`，这是 PIL 的回归探针。
  - 改成直接探 `pptx`：`server/resources/artifact_inspector.py` 仍用 python-pptx，探针的本意保留；
  - 不改的话，打包自检会失败。

目录里没有执行器的 6 行：
- 整个工具集退役：`session_search`（`seed_catalog.py:60-67`）、`skills_management`（`:69-80`，含 `skills_list`、`skill_view`、`skill_manage`）、`task_planning`（`:82-89`，`todo`）。加进 `RETIRED_TOOLSET_KEYS`。
- `patch`（`:56`）不一样：它是 `file_operations` 工具集里的一行，而这个工具集还在用。`RETIRED_TOOLSET_KEYS` 只能整组删，所以：
  - 在 `seeder.py:63-69` 旁边加一个 `RETIRED_TOOL_KEYS = ("patch",)`；
  - 删除条件写成 `Tool.key.in_(...)`。

聊天里的 `desktop_takeover`：
- 在聊天里调用必被拒（`server/registry/hands_tools.py:877-879`），却出现在聊天的工具表里：`server/orchestrator/arslan.py:1129-1133`，在 `:1119` 的 `if True:` 块里。
- 改成只在 `in_job` 时给。只改 `arslan.py`，不改 Hands 的文件，**知会 ③Hands**。

恒为真的判断：
- `server/orchestrator/arslan.py:1157`、`:1179`、`:1194`、`:1200` 的 `"x" in EXECUTORS`。这几个 key 在 `server/registry/executors.py:932-963` 里是无条件注册的。
- `:1010`、`:1015` 是同类写法，一起清。
- `:1040` 留给 S1：S1 也改 `:1040-1052`。

测试：
- 删 `tests/server/test_deck_pptx.py`、`test_deck_html_default.py`；
- 改 `test_executors.py`、`test_tool_loop.py` 里 deck 的断言；
- 新测试：旧库里的 `deck`、`patch` 等行，开机后被删掉。

**C3b 降级**（约 −80 行）

在 `arslan.py` 的 `_arslan_tools` 旁边放一个常量，写清「不常驻的工具」。K7 按它做按需取用。

要移出常驻表的：
- 浏览器的 `browser_back`（`:1074`，聊天里也给）；`browser_click`、`browser_type`、`browser_select`、`browser_press`（`:1075-1082`，今天就只在后台任务里给）。
- `delegate_work`（`:1015-1020`）、`suggest_connector`（`:1163-1168`）、`propose_capability`（`:1187-1193`）。
- SSH（D10），在 `:1273-1297` 判断已登记的机器数（`server/services/ssh_nodes.py:33` 的 `list_nodes`）：
  - 0 台时，不给 `ssh_run`、`list_nodes`；
  - `ssh_probe`、`enroll_node` 保留，因为它们是登记第一台机器的唯一入口。设置页只能列出和撤销机器（`web/src/components/settings/SshNodesPanel.tsx:24`、`:39`），不能添加。
  - 如果用户要的是全部不给，就得先在设置页加「添加机器」的入口。那超出本卡，交给 ⓪Plan。

本卡不改、只加断言测试的（计划和代码对不上，见风险）：
- `run_python`、`create_skill`：今天就不在 `_arslan_tools` 里（`server/orchestrator/arslan.py:982-1369` 没有它们），只有专家和配方的派发路径按装备给。
- `run_python` 的离线沙箱（`code_sandbox.py:150`，`computation_profile`）保持不动。
- `propose_plan_change`：今天就只在项目对话里给（`:1169-1178`）。D11 冻结了项目，本卡不动它。

## 不许碰

- ③Hands 的文件（`hands_tools.py` 等）。
- MCP 工具的取用：K7 的事。
- S1 改的 `:1040-1052`。
- 网页里 `render_deck` 的显示文案和 `DeckDownloadCard`：
  - 涉及 `web/src/lib/toolHumanize.ts`、`toolWords.json`、`locales/process.ts`；
  - 旧对话里的步骤和附件还要能显示。历史里到底有没有这样的记录，未核。
- `scan_local_network`：D10 只说 SSH。

## 怎么做（要点）

1. C3a 先写测试，量出今天渲染后工具 JSON 的字符数。K7 卡里也要这个数字，两边用同一个测量函数。
2. 每个被删或降级的工具，`rg` 一遍它的名字在提示词和说明里还有没有出现，有就改掉，免得模型去找一个不存在的工具。
3. C5b 没合时，两个 PR 都要重新生成 `docs/CAPABILITY_INVENTORY.md`：目录和 `executors.py` 都变了。

## 验收

- 两个 PR 各自本地全量绿、CI 绿，贴 run id。
- 测试断言：
  - 默认配置下，常驻工具表里没有上面列出的工具；
  - 聊天回合里没有 `desktop_takeover`，后台任务里有；
  - SSH 开着、0 台机器时，只有 `ssh_probe` 和 `enroll_node`。
- PR 里贴两个数字：默认配置下渲染后的工具 JSON 字符数，前后对比。

## 量级

- C3a 约 −700 行，其中 `deck_pptx.py` 占 456 行；
- C3b 约 −80 行。

两个都在 800 以内。

## 风险与回退

- **计划和代码对不上：**
  - reduce-proposal §2 说 `create_skill` 等「每轮都在工具表里」，代码里 `create_skill`、`run_python` 并不在主 agent 的工具表里；
  - `propose_plan_change` 只在项目对话里给；
  - 浏览器点击类今天只在后台任务里给。
  - 所以 C3b 实际要动的，比计划写的少。
- **退役目录行：** 走现成机制 `_retire_removed_seeds`（`seeder.py:63-69`），此前已经用它退役过 22 个工具集。新加的只有按工具 key 删 `patch` 这一条，测试要覆盖。
- **K7 之前的空窗：** 用户在对话里点名一个降级的工具，比如「帮我连 GitHub」，模型拿不到 `suggest_connector`。C3b 和 K7 之间不发版。
- **回退：** C3b 可以单独 revert。C3a revert 后，目录里又有了这些行、退役清单里也没了它们，下次启动时 seeder 会按目录把它们写回（`seeder.py:72-95` 每次启动都 upsert），不用迁移。
