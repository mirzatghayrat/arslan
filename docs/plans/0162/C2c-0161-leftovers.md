# C2c 删 0.1.61 留下的死代码

| 项 | 内容 |
|---|---|
| 道 | ②Main（AppleScript 那一处：服务端③Hands 自己改、②Main 审；网页②Main） |
| 版本 | v0.1.63 |
| 分级 | 必须 |
| 依赖 | C1 |
| 合并位置 | C1 之后，**C4 之前**（README §3：C2c → C4 → S2a → S4a）。也排在 S2a 之前：三张卡都改 `server/services/approvals.py` 和 `server/ws/arslan.py`。这两个文件不是 K 线热点；但 K2 改 `ws/arslan.py` 的回合锁（`:708`、`:740`、`:801`），K2 开着时排在它后面 |
| 推动的门槛 | 无直接门槛；净减代码。间接：C4、S2a、S4a 改确认阶梯时，面对的是一套干净的代码 |
| 分支 | `claude/0162-c2c-0161-leftovers` |
| 迁移号 | 无 |

## 目标

0.1.61 把卡片都迁到了 `permissions.decide`，留下一批只剩测试在用、或者永远走不到的代码。删掉它们，用户可见的行为不变。唯一的例外是 `_legacy_scope`，见风险。

## 改哪些文件

以下行号都在 `fb6d7230` 上核过。

**`server/services/approvals.py`**
- `ask`（`:160-186`）：产品里没有调用者。Hands 已经走 `decide`，`ask` 只剩测试在用。
  - `scheduler.py:492` 的 docstring 还提到它，跟着改。
- `island_may_answer` 里卡片不带 `perm_kind` 的分支（`:319-326`），以及只给它用的 `_RISKY_SCRIPT`（`:282-283`）。
  - 现在每张卡都由 `permissions._ask` 盖上 `perm_kind`：`server/services/permissions.py:354`；
  - Hands 的卡也一样：`hands_tools.py:67-77`、`:90-102`。
- `_legacy_scope`（`:234-243`）：`:223` 的调用改成 `options[0] if options else None`；`:196-199` 的 docstring 一起改。

**`server/ws/arslan.py`**
- `_cmd_sig`（`:83-98`）：零调用。
- `may_skip_card` 的 `always_allowed` 参数（`:66-80`）：两个调用方都不传，`server/services/approvals.py:506`、`server/ws/arslan.py:579`。

**其他服务端文件**
- `server/services/permissions.py`：`would_ask`（`:219-224`）只剩测试在用；`:39` 的注释跟着改。
- `server/services/permission_store.py`：`refused_since`（`:149-155`）只剩测试在用；`:160` 的 docstring 跟着改。
- 死设置 `voice_output_enabled`：
  - 定义在 `server/services/settings_service.py:40`、`server/schemas.py:90`、`:163`；
  - 网页测试里有一行：`settings-put-carries-only-what-was-touched.test.ts:153`。

**网页卡片里走不到的 v1 分支**

这三种卡都由 `decide` 发出，一定带 `options`：
- 写入卡：`server/ws/arslan.py:518-521`、`server/services/approvals.py:470`；
- 定时卡：`server/ws/arslan.py:527-530`、`server/services/approvals.py:480`；
- 动作卡：经 `hands_tools._decide`、`permissions._generic_frame`。

要删的分支：
- `web/src/components/WorkspaceWriteCard.tsx`：`:40` 的 `v2`，以及 `:48-60` 里所有 `v2 ? … : …` 的旧分支；
- `web/src/components/ScheduleGrantCard.tsx`：`:64`、`:72-85`；
- `web/src/components/ActionApprovalCard.tsx`：`:49`、`:75`、`:91-98`。

两个只给旧分支用的文案 key：`wswrite.scope`、`schedgrant.scope`。
- 6 种语言一起删；
- `web/src/__tests__/locale-parity.test.ts:324-345` 里检查 `schedgrant.scope` 的断言跟着删；
- `web/src/__tests__/card-choices.test.tsx:71` 跟着改。

**AppleScript 的 `app` 死路（服务端：③Hands 的 PR，②Main 审；网页：②Main）**
- `server/registry/hands_tools.py:404-405` 把 `script_kind` 返回的 `app` 一律改成 `app_risky`（0.1.61 发版门：每个脚本都问）。所以灵动岛的 `scriptAlsoHands` 永远不会出现。
- 服务端不搬（⓪Plan 2026-10-21 同意③Hands 的改法）：`script_kind` 照旧分 `app` 和 `app_risky`。改写是策略，留在它唯一的调用处。并进 `script_kind` 会让到达分析（#232 的 `_SCRIPT_REACH_OTHERWISE`、高到达 App、删除/发送词）不再影响任何结果，可放开发版门要的正是这层区分；K2a 的 `turn_tools` 标签也会跟着变。
  - 改写处的注释写明删除条件：0.1.61「每个脚本都问」的门放开时删，由它自己的卡来删，`scriptAlsoHands` 那时一起回来。
  - 加一条行为测试：只对一个 App 的普通脚本，`script_kind` 仍是 `app`；卡是 `app_risky`、只给「这一次」；答「总是」也不留规则，第二次照样问。
- 网页这一半（②Main）：删 `web/src/island/islandAsk.ts:84-87` 的 `alsoAllowsKey`、`web/src/island/IslandApp.tsx:267` 对它的使用（和 `:6` 的 import）、`web/src/locales/island.ts` 里 6 种语言的 `scriptAlsoHands`，以及只测它的 `web/src/__tests__/island-applescript-line.test.tsx`。卡或注释里写一句：发版门放开时这些要回来。

## 不许碰

- `terminal_policy.allow_always`（`server/services/terminal_policy.py:230`，零调用）：S2a 要重写 `terminal_policy`，留给它。
- 旧的扁平 `llm_*` 设置键（`settings_service.py:21-22`、`:45`）：要先写数据迁移才能删，已记进 README §8「v0.1.64 候选」。
- 影子评判：C4 的范围。`server/services/approvals.py:523-557`、`server/ws/arslan.py:533-548`、`:600-626` 本卡不动。
- 确认阶梯本身的合并、出沙箱卡改走 `decide`：S2a、S4a 的范围。
- Bridge 契约文件。`FrameMapper.swift` 认的 `propose_*` 帧格式不变。

## 怎么做（要点）

1. 每删一项，先跑 `rg -n "<名字>" server arslan web/src`，确认产品调用者为 0。把结果贴进 PR。
2. AppleScript 那一处：服务端在③Hands 的 PR 里（只改注释和测试）；网页那一半在本卡的 PR 里，单独一个提交。两半都在 C4 之前合。
3. 6 种语言同一个提交删 key；`locale-parity.test.ts` 通过才算完。
4. 推送前跑 ruff。

## 验收

- 本地全量绿、CI 绿，贴 run id。
- 新测试：一个没带 `scope` 的「允许」回复（模拟旧客户端），只得到卡上的第一个选项，不会被放宽到「本对话」或「总是」。
- `npm run lint`、`npm test` 通过。

## 量级

产品代码约 −150 行；文案 2 个 key × 6 种语言，另加 `scriptAlsoHands` × 6。

## 风险与回退

- **`_legacy_scope` 不是纯死代码：** 回复里没有有效 `scope` 时，`answer()` 会走到它（`server/services/approvals.py:218-223`）。
  - 今天：带 `remember=true` 的旧回复会被放宽到 `always` 或 `conversation`。
  - 改后：一律只给第一个、最窄的选项。
  - 这个方向更安全，和 `:219-222` 注释的本意一致。窗口、收件箱都会发 `scope`，正常使用碰不到。写进 PR 描述。
- **回退：** revert 本 PR。没有数据变化。
