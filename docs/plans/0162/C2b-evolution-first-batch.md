# C2b 删进化第一批：没有界面的接口、自动路径、诊断

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.63 |
| 分级 | 必须 |
| 依赖 | C1。C1 之后，自动路径里的开关检查已经变成直接 `return None` |
| 合并位置 | C1 之后随时。拆成两个 PR，先 C2b-1 后 C2b-2。<br>• 不碰 K 线热点；<br>• 都只在 `server/main.py` 删几行，按 `docs/sessions.md` §3，不重排 |
| 推动的门槛 | 无直接门槛；净减代码。间接：启动时少开一个后台循环。这个循环每 5 分钟扫一遍所有专家，并刷新进化提案（`server/services/evolution_watcher.py:484-493`） |
| 分支 | `claude/0162-c2b1-evolution-api`、`claude/0162-c2b2-evolution-auto` |
| 迁移号 | 无（进化相关的表和设置值都留在库里） |

## 决定（⓪Plan 2026-10-20）

- **Tier-1 进化规则不进 v2 的提示词。**
  - v2 从 v0.1.40 起就是在用的路径，一直没拼过这些规则（`dispatcher.py:371` 只在没有 v2 时拼）。这是保持今天的行为，不算用户的设计决定。
  - C2b 删进化第一批；`dispatcher.py` 里只有 v1 才走的拼接，随 C2a-2 删 v1 分支时一起删。
  - C2a 实施记录里提出的问题，到此定了。

## 目标

「进化」在网页上没有入口。删掉它对外的接口、开机自启的自动路径和诊断工具。`replay_gate`、`replay_run`、`compare_judge` 和 `skill_forge`、`evaluator` 共用，本批不动。

## 改哪些文件

**C2b-1 服务端接口**（产品代码约 −640 行）：

- `server/api/evolution.py`：整文件删，450 行，14 个路由。
- `server/main.py:520-522`：路由注册。
- `server/schemas.py`：只被 `api/evolution.py` 用的响应模型，大致在 `:579-790`，删前逐个 `git grep -nw`。
  - `EvolveProposalOut`（`:585`）归 C2e，别重复删。
- 测试：进化接口的测试。

**C2b-2 网页客户端、自动路径、设置、诊断**（产品代码约 −740 行，另有脚本 −301 行）：

- 网页客户端：
  - `web/src/api/client.ts`：`getEvolution`（`:361`）和 `:590-617` 那一组。组件里的调用都是 0，只有测试在用；
  - `web/src/api/client.types.ts`：对应的类型，在 `:474-486`、`:901-1116`。删前逐个 `git grep -nw`，别的地方在用的保留。
- `server/services/evolution_watcher.py`：
  - 自动路径：`_in_budget_refusal_cooldown`（`:429-443`）、`trigger_spawn`（`:446-464`），以及 `_is_eligible`（`:209`；C1 合并后已零调用，只在 `trigger_spawn` 的文档字符串里提到，更正 E20）；
  - 循环：`tick`、`watch_loop`、`start`、`stop`（`:484-537`）；
  - `notify_spawn`（`:540-552`）。
- `arslan/spawn/evolve.py`：`consolidate_evolution`、`reset_evolution`。
  - C2d 删了旧命令行之后，它们没有产品调用了，只有 `tests/spawn/test_consolidate.py` 测前者。
  - 一起删，删前 `git grep -nE` 加正对照。`apply_tier1_evolution` 还有 `evolution_service` 在用，保留。
- 调用点：
  - `server/services/run_recorder.py:460-469`：调用 `notify_spawn` 的那段；
  - `server/main.py`：开机启动（`:330-339`）和关机停止（`:395-401`）。
- 诊断：
  - `server/services/evolution_diagnostics.py`：整文件删，253 行。C2b-1 之后它只剩脚本在用；
  - `scripts/diagnose_evolution.py`：整文件删，301 行。
- 设置：
  - `server/services/settings_service.py:426-495`：`evolution_auto`、`legacy_token_cap_if_set`、`evolution_max_dispatches`；
  - 它们在 `:31`、`:42`、`:200`、`:590` 的登记；
  - `server/schemas.py` 的 `evolution_auto`（`:56`、`:135`）和 `evolution_max_dispatches`（`:74`、`:147`）。
- 测试：
  - watcher、诊断、网页客户端的测试；
  - `web/src/__tests__/settings-put-carries-only-what-was-touched.test.ts:135-136`；
  - `tests/server/conftest.py:460-495` 的共享夹具：只在它引用的东西被删时改。
- 如果实测超过 800 行：把诊断的两个文件单独拆成 C2b-3。

## 不许碰

- `replay_gate`、`replay_run`、`compare_judge`、`skill_forge`、`evaluator`；`server/main.py:310-328` 的 `replay_gate` 开机自检。
- `evolution_watcher` 的手动路径：`enqueue_attempt`、`_perform_attempt*`、`_running_spawns`、`_tasks`。
  - C2b-1 之后它没人调用了，但和 `replay_*` 缠在一起，留给「进化第二批」，记进 README §8「v0.1.64 候选」。
- `evolution_estimate`、`optimizer`、`synthetic_corpus`，以及 `server/api/usage.py` 的 `NOT_COVERED` 里的对应项。
- 6 种语言的翻译：本卡不动 locales。`evolution.*` 里变成没人用的 key，留给第二批。
- 库里已存的 `evolution_auto` 等设置值：不删、不迁移。读的代码没了，它们也就没人读了。

## 怎么做（要点）

1. **删接口前**，确认谁在调这些地址：

   ```bash
   git grep -nE "/evolution|evolve/estimate|/evolve([^A-Za-z0-9_]|$)" -- web/src desktop scripts evals docs-site
   ```

   今天命中四个文件。除了本卡要删的网页客户端（`web/src/api/client.ts`、`client.types.ts`）和它的测试（`web/src/__tests__/knowledge-client.test.ts`），只剩 `scripts/diagnose_evolution.py`，它在 C2b-2 删。
2. **删设置项**会让 `GET /settings` 少两个字段。确认网页不读它们：

   ```bash
   git grep -nE "evolution_auto|evolutionAuto|evolution_max" -- web/src
   ```

   今天命中一个测试（`settings-put-carries-only-what-was-touched.test.ts:135-136`，本卡改），另有 `locale-parity.test.ts:118-119` 两行注释，只是记录翻译 key 数量的变化，不读设置，不用改。
3. 两个 PR 各自跑 ruff 和全量测试。

## 验收

- 两个 PR 各自本地全量绿、CI 绿，贴 run id。
- 合完以后：
  - 下面这条命令无结果：

    ```bash
    git grep -nE "evolution_watcher\.start|trigger_spawn|notify_spawn|evolution_diagnostics|api import evolution" -- server scripts
    ```

  - 启动日志里没有 evolution watcher 的启动行。
- `GET /api/v1/settings` 的返回里没有 `evolution_auto`、`evolution_max_dispatches`；`PUT` 不带它们也正常。

## 量级

产品代码约 −1,380 行，拆成两个 PR，各在 800 行以内。脚本另有 −301 行。测试另计。

## 风险与回退

- **老用户开过 `evolution_auto`：** 删掉以后，后台不再花他的额度。这正是 `settings_service.py:426-455` 注释里要的结果。写进发布说明。
- **开发者靠 `diagnose_evolution.py` 排查：** 进化本身已经没有入口，可以接受。脚本留在 git 历史里。
- **回退：** 两个 PR 各自 revert，没有数据变化。
