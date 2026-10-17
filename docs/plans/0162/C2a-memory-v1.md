# C2a 删记忆 v1 的死分支

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | 0.1.62 |
| 分级 | 必须 |
| 依赖 | C1 |
| 合并位置 | C1 之后、**K2 开工前**合：K2 要重写 `server/orchestrator/memory.py`（K 线热点）。K1 卡不改 `memory.py`，所以和 K1 可以同时开；如果 K1 最终也动了它，按 README §3 排在 K1 之后。超 800 行时拆成两个 PR，见「量级」 |
| 推动的门槛 | 无直接门槛；净减代码。间接：K2 改 `memory.py` 时只面对 v2 一套写法。K2 推动 §5.1「三轮追问 3/3」和 §5.2「回合后的额外调用不再挡住下一条消息」 |
| 分支 | `claude/0162-c2a-memory-v1` |
| 迁移号 | 无（`legacy_user_facts`、`legacy_learnings` 等旧表和兼容视图都保留） |

## 目标

每次启动都会把记忆切到 v2，事实在 `server/services/storage_boot.py:19` 的 `activate_sync`（reduce-proposal §4.2 写的 `:18` 实为 `:19`；`memory_activation.py` 把 phase 写成 `active`）。所以 `is_active()`（`server/services/memory_repository.py:45-49`）在产品里恒为真，它后面的 v1 分支永远走不到。删掉这些分支，同时让测试库也处在激活状态，和产品一致。

## 改哪些文件

全仓库共 32 处调用，分在 14 个文件里，`fb6d7230` 上逐处核过：不带参数的 `await is_active()` 23 处、10 个文件（reduce-proposal 只数了这一种），带参数的 `await is_active(db)` / `is_active(session)` 9 处、另 4 个文件。计划只列了前 5 个文件，下表是全集：

| 文件 | 行 | v1 在哪 |
|---|---|---|
| `server/orchestrator/memory.py` | `:250`、`:360`、`:387`、`:439`、`:462`、`:486` | 每个函数 `if` 之后的部分。`save_facts` 的 v1 写法在 `:253-331` |
| `server/services/distill_service.py` | `:93`、`:256`、`:441` | 同上 |
| `server/services/fact_dedup.py` | `:166`、`:201` | 同上 |
| `server/registry/memory_executors.py` | `:78`、`:142`、`:476` | `:476` 是反过来写的：`if not` 时返回 `memory_store_unavailable`。这个 `if` 直接删 |
| `server/services/learning_service.py` | `:49`、`:142` | `if` 之后的 v1 写法 |
| `server/services/fact_classify.py` | `:120`、`:169` | v1 的后台分类整段 |
| `server/services/task_context.py` | `:106`、`:135` | `if not … : return` 的「不绑上下文」路径，删掉 |
| `server/services/run_recorder.py` | `:104` | `unscoped = privacy is None and await is_active()` 改成 `privacy is None` |
| `server/services/titler.py` | `:76` | 有 `conversation_id` 时永远走本地标题；`:84-107` 的模型标题仍给没有 `conversation_id` 的调用用，**保留** |
| `server/api/facts.py` | `:87` | 返回 `legacy_classification_disabled` 那一支保留（接口形状不变），删 `:90-91` |
| `server/services/knowledge.py` | `:110`、`:132`、`:155`、`:225` | 前两处在 v2 下直接 `return {}`，后面的旧检索整段删；后两处删 `if` 之外的 v1 写法 |
| `server/services/memory_temporal.py` | `:56`、`:132` | v2 下直接抛 `versioned_review_required`，后面的旧表改写整段删 |
| `server/api/spawns.py` | `:105`、`:120` | 专家偏好：只留 v2 那支 |
| `server/api/brain.py` | `:984` | **是复合条件**：`is_active(session) and p.table_name != "notes"`。只把 `is_active(session) and` 去掉，`notes` 那条路照旧 |

- 删完后只被 v1 用的辅助函数，确认零调用者再删。候选有 `fact_dedup` 的 `exact_norm_dup`、`find_near_dup`、`existing_norms`，以及 `memory.existing_norms_safe`（`:334-342`）。
  - 被 `memory_compat` 等 v2 代码用的保留，例如 `norm`。
  - 以上未逐个核，删前 `rg`。
- 变成空操作的调用点：`fact_classify.classify_missing()` 在 v2 下立即返回 0。
  - 所以 `server/main.py:250-258` 开机补分类那段可以一起删：只删这几行，不重排启动步骤。
  - `is_active` 本身保留：删完以后产品代码不再调用它（上表 32 处就是全部调用，已核），但本卡的验收测试要用它断言测试库处于激活状态。
- 测试：
  - 建库夹具改成激活状态。在 `tests/server/conftest.py` 的建库处（`:100-111`、`:250-275`，以及 `:417`、`:470` 附近）加一个激活步骤。
  - 现成写法在 `tests/server/test_memory_compat.py:10-15`：`migrate_legacy_sync` 加 `activate_sync`。
  - 只测 v1 行为的测试删掉；测通用行为的改到 v2 上。

## 不许碰

- 记忆 v2 的存储、`memory_compat`、`memory_tools_v2`、迁移和激活代码本身。
- `memory.py` 里 K2 要改的部分：`_DEFAULT_TOKEN_BUDGET`、`assemble_working_context`、`maybe_compact`（`:19`、`:72-186`）。本卡只删 v1 分支，不调预算和压缩。
- 旧表、兼容视图、`guard_legacy_*` 触发器。不加迁移、不删表。

## 怎么做（要点）

1. **第一个提交只改测试夹具**，让测试库处于激活状态，然后跑全量。红掉的就是「靠 v1 才过」的测试，把这份名单贴进 PR。
2. 再逐文件删 v1 分支。每个函数删完，只剩 v2 那条路。
3. 推送前跑 ruff。改了 `memory_executors.py`，C5b 没合的话要重新生成 `docs/CAPABILITY_INVENTORY.md`。

## 验收

- 本地全量绿，CI 也绿，贴 run id。
- `rg -n "await is_active\(" server arslan` 无结果。
- PR 描述列出删掉或改写的测试，以及原因。
- 有一个测试断言：测试夹具建出来的库 `is_active()` 为真。防止以后又有夹具悄悄退回 v1。

## 量级

产品代码约 −600 到 −750 行：⓪Plan 静态估了 −600，没算带参数的 9 处。仅 `memory.py` 就约 −185 行。测试改动另计。

超过 800 行就拆成两个 PR：
- **C2a-1**：`memory.py`、只被它用的 v1 辅助函数、测试夹具激活。K2 前必须合；
- **C2a-2**：其余文件，不赶 K2。

## 风险与回退

- **风险：活跃窗口外的情况。** `phase` 只在 `memory_repository.py:496-515` 擦除旧数据的事务里临时改成 `maintenance`，提交前就改回来。所以产品里没有长期不活跃的窗口。
  - 例外：恢复备份或导入旧库之后、下次启动之前，是否会有短暂的非 active 状态，未核。实施时查 `memory_restore` 的流程，确认恢复后会重跑激活。
- **热点：**
  - `memory.py`：K2 的主改文件，所以本卡必须在 K2 开工前合。
  - `learning_service.py`：C1c（`:160-165`）、C2e（`:168-172`）也改，行不重叠，后合的 rebase。
  - `server/main.py`：只删几行，按 `docs/sessions.md` §3。
- **回退：** revert 本 PR。没有数据变化。
