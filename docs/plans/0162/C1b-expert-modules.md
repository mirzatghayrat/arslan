# C1b 删 9 个不可达的专家模块

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.63 |
| 分级 | 必须 |
| 依赖 | C1 |
| 合并位置 | C1 之后随时。不碰 K 线热点；`server/main.py` 只删 `:247-248` 两行注释 |
| 推动的门槛 | 无直接门槛；净减代码（产品 −753 行，测试 −834 行）。间接：「活动」页用量卡片（`UsageCard`，在 `ActivityView` 里）的「未计入」列表不再列已删的模块 |
| 分支 | `claude/0162-c1b-expert-modules` |
| 迁移号 | 无 |

## 目标

删掉 9 个运行时没有任何入口的专家时代模块，以及它们专属的 8 个测试文件。同时修正 `server/api/usage.py:42-61` 的 `NOT_COVERED`。这张清单会显示给用户（`web/src/components/UsageCard.tsx:133-136`），里面的名字必须都还存在。

## 改哪些文件

删除的 9 个文件（共 753 行，`fb6d7230` 上核过）。每个都写明了 `rg` 找到的全部引用。除了这 9 个文件之间互相 import，没有别的地方 import 它们：

| 文件 | 行数 | 现有引用 |
|---|---:|---|
| `server/services/staffing_gather.py` | 108 | 只在 `usage.py` 的字符串里 |
| `server/orchestrator/update_drafter.py` | 138 | 只在 `usage.py` 的字符串里 |
| `server/services/persona_lint.py` | 117 | 只被 `update_drafter.py` import |
| `server/services/spawn_match_service.py` | 112 | `usage.py` 的字符串；`replay_gate.py:61` 的注释 |
| `server/services/storage_intent.py` | 38 | `usage.py` 的字符串；`server/services/tool_intent.py:3` 的 docstring |
| `server/services/prompts/storage_intent.py` | 12 | 只被上一个文件用 |
| `server/services/sandbox_service.py` | 27 | 只在 `usage.py` 的字符串里 |
| `server/services/spawn_trust.py` | 40 | 无 |
| `server/services/default_spawns.py` | 161 | 只有 `server/main.py:247-248` 的注释 |

删除的 8 个专属测试（共 834 行）：

- `tests/server/test_staffing_gather.py`、`test_spawn_update.py`、`test_persona_lint.py`、`test_spawn_match.py`；
- `test_storage_intent.py`、`test_sandbox_service.py`、`test_spawn_trust.py`、`test_default_spawns.py`。

要跟着改的：

- `server/api/usage.py:42-61` 的 `NOT_COVERED`：
  - 去掉 `spawn_match_service`、`staffing_gather`、`update_drafter`、`storage_intent`、`sandbox_service`；
  - 再去掉 `_route_announcement`（C1 已删）；
  - 剩下的每一项，用 `rg` 确认它还存在。
- `tests/server/test_usage_api.py:293`、`:295`、`:300`：改断言。`len(nc) == 18` 改成剩下的个数。
- 只是顺带提到上面这些模块的测试：
  - `tests/server/test_promise_guard.py:37-41`，monkeypatch 了 `staffing_gather`；
  - `tests/server/test_arslan_loop.py:55`，在 docstring 里提到它；
  - `tests/server/test_deck_html_default.py:11`、`tests/server/test_designed_html_report.py:10`，import 了 `DEFAULT_SPAWNS`。
  
  只删掉跟专家有关的那几条断言。`test_deck_html_default.py` 如果 C3 已经合了，整个文件已经没了。
- 注释：`server/main.py:247-248`、`server/services/replay_gate.py:61`、`server/services/tool_intent.py:3`。

## 不许碰

- `server/services/spawn_drafter.py`：`server/api/create.py` 还在用。
- `NOT_COVERED` 里其他的名字：`compare_judge`、`optimizer`、`synthetic_corpus` 等。它们留给进化后续批次，不在本卡。
- C1c 的范围：`phase_service`、`roster_service`、网页端、翻译。
- 不加迁移、不删表。

## 怎么做（要点）

1. 每删一个文件，先跑一遍 `rg -n "<模块名>" server arslan scripts packaging evals tests`，确认结果和上表一致。还要确认没有 `importlib` 动态加载：全仓库 `server/` 里没有 `import_module` 调用。
2. 整文件删除，不留兼容壳。
3. ruff + 全量测试。

## 验收

- 本地全量绿，CI 也绿，贴 run id。
- `rg -n "staffing_gather|update_drafter|persona_lint|spawn_match_service|storage_intent|sandbox_service|spawn_trust|default_spawns|_route_announcement" server arslan web/src` 只剩 0 处，或者只剩已确认无害的历史注释。
- `GET /api/v1/usage/summary` 的 `not_covered` 里，每个名字在代码里都能找到。由 `test_usage_api.py` 断言。

## 量级

产品代码 −753 行，外加约 15 行列表和注释。测试 −834 行，外加几处断言修改。

## 风险与回退

- **风险：** 打包会不会要求这些模块存在。已核两处，都不会：
  - `packaging/arslan-server.spec` 用 `collect_submodules`，删掉的模块不会被要求存在；
  - 打包自检的必需清单（`packaging/server_entry.py:322-342`）里没有这 9 个名字。
- **回退：** revert 本 PR。没有数据变化。
