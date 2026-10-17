# C2e Python 杂项死代码

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.63 |
| 分级 | 必须 |
| 依赖 | C1 |
| 合并位置 | C1 之后随时。拆成两个 PR，顺序不限。<br>• 不碰 K 线热点；<br>• C2e-2 在 `server/main.py` 只删几行，按 `docs/sessions.md` §3，不重排 |
| 推动的门槛 | 无直接门槛；净减代码。间接：启动时不再有已被 supervisor 取代的 MCP 巡检开关 |
| 分支 | `claude/0162-c2e1-misc-python`、`claude/0162-c2e2-media-mcp-probe` |
| 迁移号 | 无 |

## 目标

删掉 Python 侧没有调用者的代码。每一项都在 `fb6d7230` 上用 `rg` 核过：产品代码调用为 0，测试调用也为 0（另有说明的除外）。

## 改哪些文件

**C2e-1 占位实现与零引用函数**（约 −400 行）：

整块删除：
- `arslan/tools/`：6 个文件，185 行，没有任何外部 import；配套测试 `tests/tools/` 3 个文件。
- `arslan/config/settings.py`、`arslan/config/__init__.py`：37 行，只有它们自己互相引用。
  - C2d 删掉 `requirement_tree.yaml` 以后，整个 `arslan/config/` 目录就没了。
- `server/orchestrator/confirm_lexicon.py`：71 行，零引用。

零引用函数，产品和测试都为 0：

| 位置 | 函数 |
|---|---|
| `server/orchestrator/dispatcher.py:95` | `last_spawn_output` |
| `server/schemas.py:585` | `EvolveProposalOut` |
| `server/services/code_sandbox.py:139-147` | `readonly_profile`（`computation_profile`，`:150`，**保留**） |
| `server/services/learning_service.py:168-172` | `distill_from_feedback` |
| `server/services/provider_config_service.py:223` | `get_primary` |
| `server/services/runtime_messages.py:217` | `has_findings` |
| `server/services/runtime_messages.py:226` | `is_round_incomplete` |

`server/services/command_policy.py:116-178` 的网络辅助函数：
- 包括 `_GIT_NETWORK`、`is_network_command`、`_url_host`、`resolve_target_host`、`_GITHUB_HOSTS`、`is_host_allowed`、`push_targets_current_branch`；
- 产品调用为 0（已核）；据 reduce-proposal §4.1，它们唯一的调用者在 0.1.48 就删了；
- 配套测试：`tests/server/test_command_network_policy.py`。

**C2e-2 媒体后端与 MCP 的 PB-4 巡检**（约 −570 行）：

媒体：
- 整文件删：`server/media/journal.py`（69 行）、`server/media/contracts.py`（91 行）。`journal.py` 只有测试在用；`contracts.py` 只被 `journal.py` 和 `comfyui.py` 里要删的两段用。
- `server/media/comfyui.py`：删 `_runtime_and_model`（`:44-84`）和 `ComfyUIBackend`（`:87-309`）。
  - 保留模块常量和 `capabilities()`（`:34-41`）：`server/api/companion.py:108-112` 在用。
  - **同时更正** `capabilities()` 里的 `implemented`：实现删了以后，`generate`、`targeted_cancel`、`verified_png` 不能再写 `True`。
- 测试：`tests/server/test_media_backend.py`。

MCP 的 PB-4 巡检（已被 supervisor 取代）：
- `server/main.py:180-186`：只在 supervisor 没开、并且 `ARSLAN_MCP_HEALTH_ON_BOOT=1` 时才跑的开机巡检。删掉后 `_boot_mcp` 只剩启动 supervisor；`:170-172` 的 docstring 跟着改。
- `server/services/mcp_service.py:294-415`：`check_health`、`_health_state_answer`、`check_health_all`。
- `server/api/mcp.py:172-178`：`POST /mcp/{id}/health`。
- `web/src/api/client.ts:630-640`：`checkMcpHealth`，组件里调用为 0。
- 测试：`tests/server/test_mcp_health.py`，以及 `test_mcp_wiring.py`、`test_mcp_exposure.py` 里相关的断言。

## 不许碰

- App Store Connect 的写入链路：`server/services/asc_draft_execution.py`、`server/connectors/app_store_connect/*`、`server/api/companion.py:102-105`。用户还没说是不是路线图预留，本版不动、不删。
- C1c 的函数：`learning_service.distill_from_event`、`phase_service` 等；C2b 删的进化 schema。
- `command_policy.classify`、`validate`：仍在用。F2 可能新增对 `classify` 的调用（F2 卡「改哪些文件」①），本卡不改它们。
- `mcp_service.last_error_text`、`reconnect`（`:417` 起）：它们不是 PB-4，还在用。
- `code_sandbox.computation_profile`：`run_python` 的离线沙箱，C3 和总计划 §3.2 第 4 条都要求保留。

## 怎么做（要点）

1. 每删一项，先跑 `rg -n "\b<名字>\b" server arslan scripts packaging evals tests web/src`，把结果贴进 PR。
   - `check_health` 要按限定名搜（`mcp_service.check_health`）：`api/mcp.py:173` 的路由函数也叫这个名字。技能的 health 接口（`web/src/api/client.ts:442`）是另一回事，不删。
2. 媒体的 `capabilities()` 更正是对外说法的修改，在 PR 描述里单独写一句。
3. 两个 PR 各自跑 ruff 和全量测试。

## 验收

- 两个 PR 各自本地全量绿、CI 绿，贴 run id。
- 用这条命令核对：

  ```bash
  rg -n "arslan\.tools|arslan\.config|confirm_lexicon|ComfyUIBackend|MediaJournal|check_health_all|ARSLAN_MCP_HEALTH_ON_BOOT|is_network_command" server arslan web/src scripts packaging
  ```

  应该只剩已知的无害注释，或者一处都没有。
- `GET /api/v1/connections/local-media/capabilities` 照常返回，而且不再声称已实现生成功能。有测试断言。

## 量级

- C2e-1 约 −400 行；
- C2e-2 约 −570 行。

两个 PR 都在 800 行以内。测试另计。

## 风险与回退

- **风险：** `learning_service.py` 也被 C2a（`:49`、`:142`）、C1c（`:160-165`）改。行不重叠，后合的 rebase。
- **风险：** F2 不改 `command_policy.py` 本身，只可能在 `task_service.py` 里调用 `classify`。所以和本卡删的 `:116-178` 不冲突。
- **回退：** 各 PR 单独 revert，没有数据变化。
