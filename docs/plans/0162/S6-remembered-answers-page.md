# S6 「记住的回答」页

| 项 | 内容 |
|---|---|
| 道 | ②Main（列出 Hands 的「总是允许」App：③Hands 审） |
| 版本 | 0.1.62 |
| 分级 | 可以（D14 第二条承诺；可能顺延到 0.1.63） |
| 依赖 | S4（出沙箱授权要先存进库）；S2a（命令的「总是」从此不起作用，页面要这样标） |
| 合并位置 | S3 → S4 → S6。不碰确认阶梯；改 `server/api/settings.py` 和 `web/src/components/settings/AdvancedSection.tsx`，和 S4、S5 的网页改动可能挨着，谁后合谁 rebase |
| 推动的门槛 | D14 第二条：v0.1.61 发布说明承诺的「能列出、撤销的设置页」；附录 A「允许/拒绝规则」 |
| 分支 | `claude/0162-s6-remembered-answers` |
| 迁移号 | 无 |

## 目标

- **今天「记住的回答」分在几处，大多看不见。**
  - 规则表：有 `GET /permissions/rules`（`server/api/permissions.py:39-41`），但网页从没调过。网页只用了同一个文件里的「总是允许」（POST，`:44-64`）和收件箱的 10 秒撤销（DELETE，`:67-72`），见 `web/src/components/proactive/InboxRefused.tsx:99`、`:125`。
  - 本对话授权：`permission_store` 只有查、加、按任务删（`server/services/permission_store.py:81-122`），没有列出的接口。只有删掉整段对话，它们才会消失。
  - 出沙箱授权：S4 之后存成 `kind="outside"` 的本对话授权，同上。
- **做一个设置页，列出全部，每条都能删：**
  - **「总是」规则：** 按种类分组。
    - Hands 的「总是允许」App 在同一张表里（`kind="app"`，`server/services/hands_service.py:103-111`），一起列出。
    - 0.1.61 以前的命令规则（`legacy_rule`）在 S2a 之后不再起作用，标「旧规则，已无作用」，可以删。
  - **本对话授权：** 按对话分组，写出对话标题、种类、目标。「为这个任务」的授权随任务结束就删，不列。
- **它取代单独的终端规则面板**：`web/src/components/settings/TerminalRulesPanel.tsx`，在 `web/src/components/settings/AdvancedSection.tsx:347` 使用，读 `/settings/terminal-rules`（`server/api/settings.py:181-195`）。

## 改哪些文件

- `server/services/permission_store.py`
  - 新增 `list_grants(db)`：只列本对话授权（`task_id == ""`），新的在前；
  - 新增 `delete_grant(db, grant_id)`。
- `server/api/permissions.py`
  - `GET /permissions/grants`：返回 `id`、对话 id、对话标题（取法沿用对话列表，`server/api/conversations.py:85` 一带，未核细节）、`kind`、`target`、`created_at`；
  - `DELETE /permissions/grants/{id}`；
  - `GET /permissions/rules` 在列出之前调一次 `hands_service.migrate_always()`（`hands_service.py:86-100`）。没打开过 Hands 设置的老用户，旧名单这样才能出现在页面上。只调用，不改 Hands 的文件；③Hands 审。
- **删除（S2a 合并后只剩旧面板在用；删前用 grep 核一遍）：**
  - `server/api/settings.py:181-195`：`/settings/terminal-rules` 的 GET 和 DELETE；
  - `terminal_policy.forget`（`server/services/terminal_policy.py:240-243`）：今天只有 `settings.py:194` 调它；
  - `terminal_policy.always_allowed`（`:220-227`）：今天还有两条阶梯在读（`server/services/approvals.py:504`、`server/ws/arslan.py:577`），S2a 删掉它们之后才只剩 `settings.py:185`；几个测试也直接调它（如 `tests/server/test_run_command_sandbox_ws.py:66`），随之改；
  - `web/src/components/settings/TerminalRulesPanel.tsx` 和它的测试；`tests/server/test_terminal_rules_api.py`。
- **网页：**
  - 新的设置页组件，例如 `web/src/components/settings/RememberedAnswers.tsx`；
  - `web/src/components/settings/AdvancedSection.tsx:22`、`:347`：旧面板换成指向新页的入口；
  - `web/src/components/settings/sectionRegistry.ts:117`：`advanced.terminal_rules` 改为新页的 id；
  - API 客户端类型；
  - 6 种语言。C1c 没合时，同一个 PR 改 `web/src/__tests__/locale-parity.test.ts:300` 的计数。

## 不许碰

- **`permissions._NEVER_ALWAYS`**（`server/services/permissions.py:59-65`）。
  - 那里的注释说：这个页面上线后，就把 `site`、`shortcut` 移出去，让它们的卡重新给「总是」。
  - 这是卡片行为的变化，而且是 Hands 的卡，单独做一个小 PR（③Hands 审）。记进 README §8「0.1.63 候选」，本卡不做。
- **Hands 设置页自己的名单**（`web/src/components/settings/HandsSection.tsx:43-45`，读写 `/hands/always`）：保留不动。两边删的是同一张表里的同一行，`stop_always`（`server/services/hands_service.py:122-127`）只做这一件事。
- 加规则的入口：仍然只有收件箱的「总是允许」（`server/api/permissions.py:1-14` 的约定）。本页只列、只删，不加。
- Bridge 帧格式；③Hands 的文件。

## 怎么做（要点）

1. **先写接口和测试**（列出、删除；删一个不存在的 id 返回 404），再做页面。
2. **每条用大白话写它允许什么。** 规则沿用 `_out` 的标签（`server/api/permissions.py:75-80`）；授权按种类给一句：
   - 「这段对话里的命令可以在沙箱外跑」；
   - 「这段对话里可以用某 MCP 工具」；
   - ……
3. **删除之后立刻生效**：下一次同样的请求就会出卡。
4. **页面上说清楚两件事：**
   - 付款、删除、发送这类，本来就每次都问，从不记住，所以这里没有它们；
   - 「为这个任务」的授权随任务结束就没了，所以这里也不列。

## 验收

- **测试：**
  - 列出：规则（含 `app` 和 `legacy_rule`）、本对话授权（含 S4 的 `outside`）都在；
  - 删一条授权后，同一对话再做同样的事会出卡；
  - 删一条 `app` 规则后，Hands 设置页里也没有它；
  - `/settings/terminal-rules` 已经不存在。
- **手动：**
  - 在某段对话里答一次「本对话」，打开页面能看到，删掉后再做同样的事，会重新问；
  - v0.1.61 发布说明里那句承诺，旁边注明对应的测试名（§5.4）。

## 量级

- 产品代码约 +200 行（主要是网页）、约 −80 行（旧面板和旧接口）。
- 测试约 +120 行。

## 风险与回退

- **用户以为删的是「总是」，其实删的是本对话授权**，或者反过来。页面分两栏，标题写清楚。
- **旧的 `legacy_rule` 出现在列表里，会让人困惑。** 标「已无作用」，并给一个「全部删除旧规则」的按钮。
- **回退：** 整个 PR revert。旧面板和接口随之回来；数据没有任何改动。
