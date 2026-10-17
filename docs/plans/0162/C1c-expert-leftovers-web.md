# C1c 专家残留：只剩测试在用的函数、从不发出的帧、网页的专家帧处理、没人用的翻译

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | 0.1.62 |
| 分级 | 必须 |
| 依赖 | C1。C1 删掉专家路径以后，下面好几项才变成零调用 |
| 合并位置 | C1 之后。拆成两个 PR：<br>• **C1c-1 服务端**：随时合；<br>• **C1c-2 网页**：建议在 K8 之前合。K8（真流式）、K9（插话）可能改 `web/src/stores/arslanStore.ts`，未核。<br>两个都不碰 K 线热点文件。C1c-2 和 C2c 都改 6 个 locale JSON 和 `locale-parity.test.ts`，后合的那个 rebase |
| 推动的门槛 | 无直接门槛；净减代码。间接：`locale-parity.test.ts:300` 写死的 key 总数没了，以后 S3、S4、S5、S6 并行加文案不再在同一行冲突 |
| 分支 | `claude/0162-c1c1-expert-leftovers-server`、`claude/0162-c1c2-expert-leftovers-web` |
| 迁移号 | 无 |

## 目标

清掉 C1 之后剩下的专家时代残留。删之前，每一项都要证明产品代码里没有调用者、服务端也不会发出。

## 改哪些文件

**C1c-1 服务端**（`fb6d7230` 上核过；「C1 后」表示 C1 合并后才变成零调用）：

- 只被测试调用或零引用的函数：
  - `phase_service`、`roster_service`：C1 后整个模块都可删（199、97 行）。
    - 今天它们的产品调用者只有 `server/orchestrator/arslan.py:108`、`:535`、`:1530`、`:1543`，C1 全部删掉。
    - 表保留：删对话时 `conversations.py:226-227` 直接按 model 清行。
  - `spawn_service`：
    - `normalize_draft`（`:37-43`）；
    - `find_overlap`（`:66-83`），连同只被它用的 `_names_overlap`（`:49-63`）；
    - `apply_conversational_update`（`:205-238`）；
    - `load_one_spawn`（`:284-293`，零引用）。
  - `evolution_service.record_verdict`（`:89-118`）。
  - `persona_seed_service.import_from_repo`（`:152-186`），连同只被它用的 `_list_md_paths`、`_fetch_md`、`_parse_persona`、`_is_persona_path`。
  - `learning_service.distill_from_event`（`:160-165`）。同文件的 `distill_from_feedback` 归 C2e。
  - C1 后：`server/registry/service.py` 的 `unready_mcp_servers`（`:516-530`）、`grant_temporary`（`:579-600`）。
- `server/ws/protocol.py` 里从不发出的帧构造函数：
  - 今天就零调用：`question`（`:7`）、`progress`（`:24`）、`build_complete`（`:28`）、`spawn_meta`（`:91`）、`spawn_created`（`:115`）、`proposal`（`:166`）、`attachment_stored`（`:174`）、`spawn_updated`（`:178`）；
  - C1 后零调用：`routing`（`:69`）、`escalation`、`escalation_refused`、`escalation_resolved`、`orchestrator_action`（`:149-163`）、`roster_update`（`:170`）、`roster_event`（`:332`）；
  - 还有 `server/ws/arslan.py` 的 `_to_frame` 里对应的分支：`:840-842`、`:855-870`。
- 测试：`tests/server/test_ws_protocol.py` 等，删对应的断言。

**C1c-2 网页**：

- `web/src/stores/arslanStore.ts`
  - 删 14 种专家帧的处理：
    - `proposal`、`routing`、`auto_continue`：`:644-679`；
    - `spawn_meta`：`:899-925`；
    - `spawn_updated`、`spawn_created`、`escalation`、`escalation_resolved`、`escalation_refused`、`verdict_recorded`、`deliverable_finalized`、`roster_update`：`:962-1077`；
    - `roster_event`、`attachment_stored`：`:1212-1246`；
    - `:545` 的 `RESPONDING_TYPES` 里的 `spawn_updated`。
  - 删专家字段：`streamSpawnId`、`streamSpawnName`、`pendingRoute`、`spawnNames`（`:54-57`）；`pendingSpawnMeta`（`:62-65`）；`pendingProposalSpawnId`（`:69-71`）；`roster`（`:72-73`）。`streamSource`（`:53`）的类型里去掉 `"spawn"`。
  - **保留** `:926-961`：`plan_proposed`、`lesson_learned`、`fact_saved`、`memory_proposed`。它们夹在计划给的行号范围里，但不是专家帧。
- 只由上述帧产生的显示代码：
  - `web/src/api/adapters.ts`：`escalation`（`:318-341`）、`isRouteAnnouncement`（`:345-355`）、`rosterAction`（`:357-368`）、`__SPAWN_UPDATED__`（`:370-391`）这几支，以及 `__SPAWN_CREATED__` 的 `spawnIntro` 部分（`:392-404`）。
    `:405-413` 那个通用的 `system` 返回**保留**：MCP 连接的后续说明等别的系统行也走它（`arslanStore.ts:1199-1209`）；
  - `web/src/App.tsx:232-239` 翻译 `__ATTACHMENT_STORED__` 的代码；
  - `web/src/components/OrchestratorChat.tsx` 的 `rosterAction`（`:547`）、`isRouteAnnouncement`（`:586`）、`EscalationNotice`（`:789`、`:899`、`:1010`、`:1182`）；
  - `client.types.ts`、`types.ts` 里对应的类型。
- **保留** `rowToItem` 的 `spawn_summary` 分支（`arslanStore.ts:562-581`）。旧对话里专家的回答照常显示。
  - `spawnNames` 删掉后，名字回落到对话标题。这是可接受的显示变化，写进 PR 描述。
- 翻译：6 个 `web/src/locales/*.json` 删 21 个顶层组，en 里共 265 个 key。名单用下面的命令生成，不要手抄。
  - 名单：`dashboard`、`build`、`conversation`、`artifact`、`feedback`、`manual_create`、`invite_card`、`gap_fill`、`spawn_studio`、`spawn_edit`、`equipment`、`escalation`、`facts`、`spawn_chat`、`rail`、`modal`、`spawn`、`staffing_card`、`eval`、`diag`、`diagnosis`。
  - **保留** `anomaly`、`recap`：服务端会发这两组的 key（`server/api/runs.py:409-447`、`server/api/conversations.py:173`）。
  - 随 `EscalationNotice` 变成没人用的 `orchestrator.escalation_*` 等 key，也一起删，6 种语言同步。
- `web/src/__tests__/locale-parity.test.ts`：删 `:35-301`，也就是计数历史的注释和 `toHaveLength(1771)` 那个测试。
  - 逐语言比对 key 集合的测试已经在 `:370-377`（`toEqual(enKeys)`），保留它。可以改名为「六种语言的 key 集合相同」。

## 不许碰

- Bridge 契约文件。删掉的帧 Bridge 都不认：`desktop/bridge/Sources/BridgeCore/FrameMapper.swift:62-158` 只处理 `stream_*`、`message`、`error`、`history`、`tool_call`、`working`、`queued`、`propose_*`、`card_resolved`、`job_update`。
- `stream_start_src`（`protocol.py:81`）：Arslan 自己的流还在用。
- `server/services/run_recorder.py`、`server/api/runs.py` 对旧 Run 里 `routing` 步骤的处理：旧数据还要能看。
- `server/api/runs.py` 的异常提示接口和 `anomaly` 翻译。
  - 网页现在没有组件调用 `getRunAnomalies`（`web/src/api/client.ts:508`）。要不要连接口一起删，记进 README §8「0.1.63 候选」。

## 怎么做（要点）

1. 没人用的翻译组，用一条可复现的命令生成名单，把输出贴进 PR：

   ```bash
   python3 - <<'EOF'
   import json, os, re
   en = json.load(open("web/src/locales/en.json"))
   src = "\n".join(open(os.path.join(r, f)).read() for r, _, fs in os.walk("web/src")
                   if "/locales" not in r and "__tests__" not in r
                   for f in fs if f.endswith((".ts", ".tsx")))
   print([g for g in en if not re.search(r"""['"`]%s\.""" % re.escape(g), src)])
   EOF
   ```

   然后对结果里每一组，再做两次搜索：
   - `git grep -nE "[\"']<组>\." -- server`：服务端会发的组不删；
   - 拿这一组的完整 key 搜 `web/src/__tests__`：有测试断言某个 key 的，连测试一起改。起草时只命中一处注释（`empty-states.test.tsx:113` 提到 `diag.loading`）。
2. 帧和函数：每删一个，先 `rg` 它的名字。产品调用者为 0、Bridge 不认，才删。

## 验收

- 两个 PR 各自的本地全量绿、CI 绿，贴 run id。
- C1c-2：`npm run lint` 和 `npm test` 通过；`locale-parity.test.ts` 里不再出现任何 key 总数。
- 手动：打开一个含旧专家回答的对话，回答照常显示。

## 量级

产品代码约 −1,000 行，所以拆两个 PR：

- C1c-1 约 −650；
- C1c-2 约 −400，另有翻译约 6 × 265 行，不计入。

## 风险与回退

- **计划数字与代码不符：** 计划说 16 组、约 216 个 key；用上面的命令实测是 21 组、265 个。多出来的 5 组（`conversation`、`artifact`、`facts`、`escalation`、`spawn`）名字太常见，所以前一次统计没算进去，可整 key 搜索也零命中。
- **回退：** 各 PR 单独 revert，没有数据变化。
