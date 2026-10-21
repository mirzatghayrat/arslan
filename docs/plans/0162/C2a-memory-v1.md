# C2a 删记忆 v1 的死分支

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.63 |
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

- **留着的旧路径和删除条件**（`docs/sessions.md` §9；代码注释里也写）：
  - 旧表、兼容视图、`guard_legacy_*` 触发器：等一个迁移把旧表里的数据并进 v2，或者确认旧表为空之后再删。本版不动，这件事记进 README §8。
  - `is_active`：删完调用后只剩测试在用，和旧表同一次删。
- **风险：活跃窗口外的情况。** `phase` 只在 `memory_repository.py:496-515` 擦除旧数据的事务里临时改成 `maintenance`，提交前就改回来。所以产品里没有长期不活跃的窗口。
  - 例外：恢复备份或导入旧库之后、下次启动之前，是否会有短暂的非 active 状态，未核。实施时查 `memory_restore` 的流程，确认恢复后会重跑激活。
- **热点：**
  - `memory.py`：K2 的主改文件，所以本卡必须在 K2 开工前合。
  - `learning_service.py`：C1c（`:160-165`）、C2e（`:168-172`）也改，行不重叠，后合的 rebase。
  - `server/main.py`：只删几行，按 `docs/sessions.md` §3。
- **回退：** revert 本 PR。没有数据变化。

## 实施记录（C2a-1）

- **K2 只等 C2a-1。** C2a-2 不碰 `memory.py`，K2 不用等它。
- **测试库的建法要和启动一致。** 夹具改成 `tests/server/conftest.py` 的 `boot_schema`：建表 → 跑迁移 → 激活 v2，和 `storage_boot.initialize` 同序（不含加密步骤）。
  - 只建表就激活（本卡原写法：`create_all` 加 `activate_sync`）会留下指向还不存在的表的视图，下次真启动报 `view learnings already exists`。
- **先修了一个产品 bug（#233）。** 测试库处于 v2 后，每个聊天回合都按任务跑。窗口在回合收尾时断开，任务会卡在「运行中」，这个对话后面的消息全被拒，要重启才恢复。#233 修好之前本卡不能合。
- **`memory_v1` 标记**（`pyproject.toml` 登记了删除条件）：标了的文件，共享测试库停在 v1。哪些文件能标，由 `tests/server/test_memory_v1_marker_scope.py` 钉死，同一个文件里也断言四个共享夹具建出来的库 `is_active()` 为真。
  - 到 C2a-2 删：`test_brain_payload_shape`、`test_brain_undo_supersede`、`test_curation_proposals`、`test_memory_proposals_api`、`test_spawn_preferences_api`。它们测的 brain、提案、专家偏好代码还有 v1 分支，C2a-2 删分支时一起删标记。
  - 永久：`test_memory_activation`，以及 `test_memory_deletion_manifest` 的 `legacy` 一例。激活和从 v1 迁移本身就是它们要测的。
- **删了什么。**
  - `memory.py` 的 v1 分支：`save_facts`、`list_facts`、`add_manual_fact`、`update_fact`、`delete_fact`、`facts_text` 只剩 v2 那条路。另删 `existing_norms_safe` 和 `_FACTS_MAX_COUNT`。
  - `fact_dedup` 只被它用的 `existing_norms`、`exact_norm_dup`、`find_near_dup`、`is_stale`。删前用 `git grep -nE` 加正对照核过零调用者。`similar`、`fuzzy_kind`、`norm` 还有 v2 或 `learning_service` 在用，保留。
- **恢复备份后的窗口（风险一节「未核」那条），已核。**
  - `backup.restore` 只在 app 停着时运行，装到新路径。
  - 下次启动 `storage_boot` 先激活 v2，再跑种子和后台任务。`test_memory_activation` 的启动顺序测试钉住了这个顺序。
  - 所以恢复出来的库没有「没激活就被用」的窗口。
- **对 C2a-2 的影响。** 有几处 v1 分支调 `memory.py` 的函数，C2a-1 之后它们走到 v2：`memory_executors.py` 的 recall/remember，`distill_service.py` 的 upflow，`brain.py` 收下 user_facts 提案。这些分支在产品里本来就走不到，C2a-2 删。
- **原表漏了一处（C2a-2 要一起删）：** `server/orchestrator/dispatcher.py:325-337` 用别名 `memory_v2_active` 调 `is_active`。本卡按 `await is_active(` 数没数到它，实际是 27 处、14 个文件。
  - 同一个分支里还有一件事：v2 下 `:371` 的 Tier-1 进化规则后缀不拼进专家提示词，只有 v1 拼。
  - C2a-2 删 v1 分支前，要先定这些规则在 v2 下是不是该进提示词（和 C2b 进化卡相关）。本卡不改行为。
- **测试的处置。** 自建 v1 库、经过 `memory.py` v1 路径的测试（先读的 4 个文件，加上跑出来的 16 个文件 45 个），先全部改成启动建法跑一遍分类：
  - v1 下挂、v2 下过的，搬到 v2。
  - 测通用行为的，改到 v2：facts 接口带版本号、`facts_text` 的敏感门、记忆往返、contextvar 不残留、预算不被超长首条绕过。
  - 只测 v1 的删掉，PR 里逐组写了理由和 v2 对应的测试。

## 实施记录（C2a-2，⓪Plan，2026-10-22）

- **再拆两个 PR**（U2 只放过「整份删除」；这里是文件内删除，算进 800 行）：
  - **C2a-2a：** 记忆工具（`recall`、`remember`、`memory_note`）和提炼（`distill_service`），产品约 −680 行。
  - **C2a-2b：** 记忆服务（`fact_dedup`、`fact_classify`、`knowledge`、`learning_service`、`memory_temporal`、`api/facts.py`、`main.py` 开机补分类）。产品约 −690 行，又超了一半，所以再拆：
  - **C2a-2c：** `run_recorder`、`task_context`、`api/brain.py`、`api/spawns.py`、`dispatcher.py`，连同 5 个 `memory_v1` 标记。
- **和 C7 / C8 的分工**（②Main 2026-10-22 核过）：这些文件 C2a-2 先删 v1 分支；C7 之后整份删 `dispatcher.py`、`api/spawns.py`，C7b、C8 合了以后 `distill_service.py` 可能整份删。
- **C2a-2a 删了哪些测试，为什么：** 都是自己用 `create_all` 建 v1 库、只走 v1 写法的测试，产品里没有一次启动走得到：
  - 整份：`test_memory_write_tiers.py`（10）、`test_meta_upflow.py`（3）、`test_memory_dual_track.py`（1）；
  - 部分：`test_memory_scope_isolation.py` 19、`test_distill_service.py` 10、`test_curation_loop.py` 6、`test_curation_proposals.py` 5、`test_memory_tools_register.py` 3、`test_conversation_distill.py` 2、`test_complete_chat.py` 1。
  - 收集到的测试名 = 删之前 − 这 60 个，逐个比对过。
- **v2 下本来就是这样、本卡不改的：** 专家直聊的「完结」（`complete_chat`）在没有记忆上下文时，提炼返回 `learning_disabled`，不算失败，所以会归档。这条路今天产品里走不到（`EXPERTS_ENABLED = False`），C7 删它。
- **新加的测试：** 两个提炼入口都走 v2，没有记忆上下文时不调模型、不报「学到了」。
- **C2a-2b 做了什么：**
  - 整份删掉 `fact_classify.py`（v1 后台分类，v2 下从不启动）和 `learning_service.py`（C2a-2a 删掉 v1 的 `remember` 以后没有调用者）；
  - `fact_dedup` 只留 `memory_compat` 用的 `similar` / `norm`；
  - `knowledge.retrieve_scoped` 只留 v2 的范围（这一轮项目的资料库），删掉 v1 的分身深井、「主脑看全部共享库」和心得 / 笔记两路；
  - `memory_temporal` 只留调用方的检查和 v2 的拒绝（`versioned_review_required`）；
  - `POST /facts/dedup`、`POST /facts/classify` 保留接口形状，直接返回 v2 下本来的结果，**DELETE-BY: v0.1.64**（和 v1 旧表一起）；
  - `server/main.py` 删开机补分类；`usage.py` 的未计入清单去掉 `fact_classify`。
- **C2a-2b 的测试：** 删 54 个只测 v1 的（整份：`test_fact_classify` 12、`test_rule_supersede` 11、`test_notes_retrieval` 1、`test_learning_service` 2、`test_fact_dedup_merge` 2；其余见 PR），收集到的测试名逐个比对过；**改到 v2 上的**：`test_retrieve_scoped`（项目范围、没有上下文就什么都不读、向量路、只有 FTS、空向量范围不付 embedding、没有云端同意不调 API embedding）、`test_retrieval_quality`、`test_retrieve_usage`、`test_active_only_retrieval` 的 `record_usage=False` 回归（原来在 v2 下变成空过）。
- **C2a-2c 做了什么：**
  - `task_context`：`scoped_turn` 和 `execute_entry` 总是绑定记忆上下文（v2 本来就这样）；`run_recorder`：没有上下文的运行算「不学习」（`unscoped = privacy is None`），后台评审不读它；
  - `api/brain.py` 收下提案：不是 `notes` 表的卡一律 409（`versioned_memory_review_required`，v2 本来就这样）；`notes` 卡只做两件事：追加笔记、删笔记，别的种类 422。删掉 v1 的 user_facts / learnings / spawns 各分支、编辑与偏好覆盖两个助手；
  - `api/spawns.py` 专家偏好：只读写这个专家范围的记忆条目；
  - `dispatcher.py` 专家提示词：只留 v2 的记忆；**Tier-1 进化规则后缀照 v2 现状不拼进提示词**（C2a-1 记下的那条决定：专家关着、C7 整份删 dispatcher，所以不改行为）；
  - 5 个 `memory_v1` 标记删掉 4 个。`test_brain_payload_shape` 留着，只为造数据：它直接写 user_facts / learnings，v2 下这两张是只读视图；它测的 brain 接口已经没有 v1 分支。**随 brain 页一起删（v0.1.65，U13）**，`test_memory_v1_marker_scope` 和 `pyproject.toml` 里写明了。
  - `server` 和 `arslan` 里已经没有 `is_active(` 的调用；`is_active` 本身留给测试断言测试库处于激活状态（和 v1 旧表一起删）。
- **C2a-2c 的测试：** 删 19 个只测 v1 的（v1 表上的收下分支、偏好覆盖、进化后缀、v1 偏好注入）；**改到 v2 上的**：提案接口（`test_memory_proposals_api` 重写：列表、v1 表的卡 409、笔记追加 / 删除、其他种类 422、同对话兄弟卡、old_id 0 不误伤、驳回）、撤销取代的请求检查、专家偏好、回放不写用量、三个评分相关文件（绑一个允许学习的回合上下文），并新加「没有上下文的运行不学习」。
