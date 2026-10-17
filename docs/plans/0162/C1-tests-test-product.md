# C1 让测试测产品：删掉默认打开专家的 fixture 和只在专家开着时才跑的路径

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.63 |
| 分级 | 必须 |
| 依赖 | F5a（CI 恢复绿色；本卡的验收是「全量测试绿」，CI 红着就没法判。F5a 合进 `release/0.1.62` 后会马上合回 main 一次） |
| 合并位置 | K 线第一个：C1 → K1。本卡改 `task_service.py`，而热修发布前这个文件不接别的 PR（FR 卡），所以**可以先开发、先开 PR，合并等 v0.1.62 发布、`release/0.1.62` 合回 main 之后**。K 线反正要等 M1B，不损失时间。依赖 C1 的卡（K 线、C1b–C4、S1–S3）都等它合了再合；C5a、C5b、C6 不依赖它 |
| 推动的门槛 | 无直接门槛；净减代码。间接：§5.4「CI 全绿」从此说的是产品配置；K 线每个 PR 的测试结果才可信（计划 §4.3「为什么 C1 必须第一个」） |
| 分支 | `claude/0162-c1-tests-test-product` |
| 迁移号 | 无（`scheduled_tasks.target`、专家相关表都保留） |

## 目标

`EXPERTS_ENABLED = False`（`server/orchestrator/arslan.py:492`），但 `tests/server/conftest.py:65-79` 的 autouse fixture `_legacy_expert_path` 对所有没标 `one_arslan` 的测试把它打开。删掉这个 fixture、这个开关，以及只在开关打开时才会跑的产品路径（D12）。合并后，全量测试跑的就是用户手里的配置。

## 改哪些文件

产品代码（行号都已在 `fb6d7230` 上核过）：
- `server/orchestrator/arslan.py`
  - `:488-492` 开关和注释；
  - `:50-123` 路由播报：`_is_cjk`、`_STAGE_ALIAS_GROUPS`、`_spawn_terms`、`_find_second_stage`、`_route_announcement`。`_is_cjk` 只被 `_route_announcement` 用；
  - `:535` `phase_service.clear(...)`，这是专家时代的停放状态；
  - `:955-959` `_arslan_fetch_executor`，只被 `:1430` 用；
  - `:1372-1699`：`_match_safe_toolset`、`_handle_escalation`、`_dispatch_spawn`；
  - 随之不用的 import：`dispatcher`（`:17-23`）、`phase_service`/`roster_service`（`:32-38`）等。未用的 import 由 ruff 报出来。
- `server/orchestrator/escalation.py`（76 行）：唯一调用者是 `server/orchestrator/arslan.py:1389`，整文件删。
- `server/services/scheduler.py`
  - `:388-470` `_dispatch_recorded`；
  - `:508-512` `_target`：恒为 `"arslan"`。迁移 0056 已改写旧行，见它自己的 docstring；
  - `:524` `driver={"kind": "expert", ...}`；
  - `_fire_body` 里的专家分支 `:581-618`。
- `server/services/task_service.py:606-608`：恢复一个 0.1.44 之前的专家任务时，不再走 `_dispatch_spawn`，落到 `:612` 的 `_handle_answer`，由 Arslan 接手。
  - `checked_driver`（`:462-474`）**保留**对 `"expert"` 的接受，否则旧任务一恢复就报 `task_invalid_driver`。
- `server/services/evolution_watcher.py:451-456`：开关没了，这里直接 `return None`，并注明「C2b 删整条自动路径」。
- 顺手做（量级允许时）：三处 `if True:` 去缩进，约 70 行。
  - 位置：`server/api/conversations.py:55`、`:221`，`server/orchestrator/arslan.py:1119`。
  - 超出 800 行就挪进 C1c-1。

测试：
- `tests/server/conftest.py:65-79` 删 fixture；`pyproject.toml:214` 删 `one_arslan` 标记的注册。
- 14 个文件里的 `pytestmark = pytest.mark.one_arslan` 删掉。这 14 个是 13 个 Hands 测试和 `test_one_arslan_0144.py`，只是删一行，**知会 ③Hands**。
- 起点清单：下面这些测试文件引用了本卡删掉的符号，挨个判断是删还是改写。
  - `test_escalation_resolution`、`test_run_cancel`、`test_spawn_vision`、`test_usage_scope_all_dispatch_paths`、`test_roster_autojoin`；
  - `test_arslan_loop`、`test_task_entrypoints`、`test_scheduler_loop`、`test_scheduled_arslan_turn`；
  - `test_usage_ledger`、`test_mcp_exposure`、`test_eval_sealing`、`test_one_arslan_0144`（`:146` 那条「开关打开时旧路径还能用」直接删）。
- 判断规则：测的是专家路径本身 → 删；只是碰巧经过它、测的是别的 → 改成走 Arslan。

## 不许碰

- `_team_roster()`（`server/orchestrator/arslan.py:416-426`、`:726`、`:759`）：K3 删。`spawn_service` 的 import 因此先留着。
- `server/api/usage.py:42-61` 的 `NOT_COVERED`（C1b 统一修）；web store 的专家帧、`server/ws/protocol.py`、`server/ws/arslan.py` 的 `_to_frame`（C1c）。
- 专家时代其余的 REST 面：`spawns`、`create`、`seeds`、`templates`、`recipes`、`expert_conversion`。`recipes` 仍在用 `dispatcher.dispatch`，`expert_conversion` 是老用户把专家转成技能的入口。要动就记进 README §8「v0.1.64 候选」。
- `dispatcher.py` 本身：`server/services/recipes.py:174`、`server/services/replay_run.py:66` 仍在用。
- 不加迁移、不删表。`conversations.py:226-227` 照旧清掉 `ConversationSpawn`、`SpawnPhase` 的行。
- ③Hands 的产品文件。
- Bridge 契约文件：`desktop/bridge/**`、`server/ws/bridge.py`、`spec/mobile-bridge/**`、`server/api/phone.py`、`server/services/phone_*.py`（`docs/sessions.md` §2）。

## 怎么做（要点）

1. 第一个提交只删 fixture 和开关，跑全量。红掉的测试就是「依赖专家开关」的全集，把这份名单贴进 PR 描述。
2. 再删产品路径。每删一块就 `rg` 一次它的符号，确认产品代码里没有调用者，剩下的只在测试里。
3. 删完列出新变成零引用的函数，写进 PR 描述交给 C1c。已知会有：
   - `roster_service`、`phase_service` 整个模块；
   - `registry_service.grant_temporary`、`unready_mcp_servers`。
4. 推送前跑 ruff 和 gitleaks。

## 验收

- 本地全量绿，CI 也绿。按产品配置跑：`uv sync --frozen --extra dev --extra server --extra ocr`，然后 `pytest tests/ -q -rfEs`。CI 要贴 run id 和 conclusion。
- `rg -n "EXPERTS_ENABLED|one_arslan|_legacy_expert_path" server arslan tests pyproject.toml` 无结果。
- PR 描述写明：删了几个测试、改写了几个、各自为什么。按文件列。
- 新测试：恢复一个 driver 为 `{"kind": "expert", "id": N}` 的旧任务，走的是 `_handle_answer`，不报错。
- 新测试：`target="spawn"` 的旧定时任务行，触发时由 Arslan 执行。

## 量级

产品代码约 −650 到 −720 行（静态估）：
- `arslan.py` 约 −425；
- `scheduler.py` 约 −135；
- `escalation.py` −76；
- `if True` 去缩进约 70。

测试改动不计入 800 行。

## 风险与回退

- **留着的旧路径和删除条件**（`docs/sessions.md` §9；代码注释里也写同样的话）：
  - `checked_driver` 接受 `"expert"`：做 README §8「专家时代剩下的 REST 接口」那一项时删。先用一个迁移把库里残留的 `driver = expert` 任务标成已结束，再删这条接受。
  - 专家相关的表：和上一条同一个迁移里清，本版不动。
  - `spawn_service` 的 import：K3 删 `_team_roster()` 时一起删。
- **热点：** `arslan.py`、`task_service.py`。F2（热修）也改 `task_service.py`，在 `:55-78`、`:101-105`、`:300-305`，和本卡的 `:605-608` 不重叠。但热修发布前这个文件冻结，本卡照样等热修合回 main 之后再合，再 rebase 一次。
- **行为变化：** 唯一的用户可见变化，是老专家任务恢复时由 Arslan 接手。这是 D12 已定的，写进发布说明。
- **回退：** revert 这一个 PR。没有迁移，数据不受影响。
