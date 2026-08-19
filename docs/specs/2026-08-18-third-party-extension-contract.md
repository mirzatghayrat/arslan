# 第三方扩展契约 + 装备面服务器级化

日期:2026-08-18 · 状态:待用户批 · 前情:v0.1.23 真机三报([[arslan-v0122-field-triage]])

## 0. 背景与两条用户裁决

外部评价说 Arslan「没有第三方扩展契约,加能力得读源码」。校准后一半成立:

- **实例级契约已存在且完整**:任何人写一个 MCP server(任何语言),走 Discover 贴链接 → `/discovery/evaluate` → 档案卡 Add → connect → 装备,零源码阅读。这层不缺。
- **真缺口有两个**:①没有**打包/分发单元**——第三方没法声明「怎么启动 + 要哪些密钥 + 配套技能 + 建议装备」,所以漏斗只能靠 LLM 猜启动命令;②**装备摩擦**——connect 完还要逐工具开两个开关,用户在真机上实证栽过(第三报)。

**用户裁决 A(2026-08-18)**:装备确认收到**服务器级**——connect 即给 Arslan(host);spawns 由服务器卡上「Allow for spawns」一个开关管;逐工具行降级为高级覆盖。

**用户裁决 B(2026-08-18)**:做 `arslan.plugin.json` 清单层。**不做进程内代码插件**(红线:绝不自动跑外部码、执行面语义留第一方——这条本 spec 视为永久非目标)。

---

## Part A:装备面服务器级化

### A1 host 维度:connect 即 Arslan 可用

**现状**(全部亲核):`_arslan_tools`(`server/orchestrator/arslan.py:1774-1790`)只送 `Tool.status=="wired" ∧ Tool.host_enabled` 的 MCP 工具;发现落库默认 `registered`+`False`(`models.py:199`)⇒ connect 完 Arslan 拿到零工具。

**改法**:

1. 新列 `mcp_servers.host_allowed` BOOLEAN NOT NULL DEFAULT 1(migration **0040**;加迁移=**三处 lockstep** 规矩,见 [[arslan-migration-boot-backfill]])。
2. `_arslan_tools` 的 MCP 段改判据:**属于 `host_allowed=True` 服务器的全部已发现 Tool 行**(带 `input_schema`,ORDER BY 不变——G1 §3 缓存前缀注释原样保留),不再看 per-tool `status`/`host_enabled`。
3. per-tool `host_enabled` 列**保留在库、退出闸**(死值);UI 移除逐行「allow Arslan」勾。**披露:host 维度失去工具级粒度**;将来要 opt-out 再加 blocklist,本轮不做。
4. 服务器卡新增「Arslan 可用」开关(默认开)。人闸语义:**connect 本身是用户动作 = 同意**;开关是可撤销面,不是第二道门。
5. **自知面同步**(#38 刚落的逻辑要跟着改):`list_my_capabilities` 的 `usable_by_me` 判据从 per-tool 改为 server 级;「connected 但零装备」的 note 场景在新语义下只剩 `host_allowed=False` 一种,文案改为指向服务器开关。**#38 的测试按新契约改写,mutation 重跑。**

**不变的安全面**:MCP 输出仍走 `wrap_external`(不可信框);spawn 咽喉(`is_assignable`/`wired_tools_for_spawn` 的 SQL)一字不动;网络钉扎/密钥面不动。**变宽的面如实说**:Arslan(host)获得已连接服务器全部工具的调用权,含写类动词(browser_click 等)——依据即裁决 A,connect 是人类动作。

### A2 spawn 维度:让「Allow for spawns」不再半假

**现状**:该勾(`set_exposed`,`mcp_service.py:127-134`)只把 Toolset 提 `safe`,但 spawn 咽喉要求**工具级** `tier=safe ∧ status=wired`(`tier_counts` docstring 引 `service.py:377-384`)⇒ **今天勾了它 spawns 也拿不到任何东西**,是个半假开关——正是「MCPS 让人勾一个永不生效的开关」家族。

**改法**:expose ⇒ 自动把 `suggest_tier==safe` 的工具(只读动词,`discovery.suggest_tier`)wire 成 `tier=safe/status=wired`;**suggest==orchestrator(写/危险动词)的不自动给 spawns**——spawn 面保留梯度,写类工具仍要逐工具手动 wire。取消勾选 ⇒ un-wire 本服务器全部工具(简单、诚实;不去区分「自动 wire 的」和「用户手动 wire 的」——**裁决点 ①**,如你要保留手动项改这里)。逐工具行(tier 下拉 + wire 勾)保留为高级覆盖。

### A3 验收

- mutation 硬要求(闸判据、expose 自动 wire 范围、un-wire、自知面新判据)。
- 真机:connect Playwright 后**不碰任何开关**,聊天里 Arslan 直接调 `browser_navigate`;勾 expose 后 spawn 装备菜单出现 `browser_console_messages` 等 safe 建议项、**不出现** `browser_click`;`list_my_capabilities` 报 usable 全量。

---

## Part B:`arslan.plugin.json` 清单层

### B1 格式(schema_version=1,repo 根目录)

```json
{
  "schema_version": 1,
  "name": "playwright-pack",
  "version": "0.1.0",
  "description": "Browser automation for Arslan",
  "min_app_version": "0.1.24",
  "mcp_servers": [{
    "label": "Playwright",
    "transport": "stdio",
    "command": "npx",
    "args": ["-y", "@playwright/mcp@latest", "--isolated"],
    "env": { "SOME_KEY": { "secret": true, "description": "..." } }
  }],
  "skills": ["skills/browsing.SKILL.md"],
  "suggest_spawn_expose": false
}
```

- `env` 只声明**槽位**(要什么 key、是否密钥),**绝不含值**;安装时表单收集,走现有加密存储。
- `skills[]` 指向 SKILL.md,**frontmatter 兼容格式**(借鉴映射 #7:与 ClawHub/Claude 生态互通),走现有 skill 摄取咽喉(段校验 + 人工可编辑)。
- `suggest_spawn_expose` 只**预勾选** UI 复选框,提交仍是用户按 Add——提议面宁开、执行面宁关。
- http transport 同理(`url` 替代 command/args);OAuth 远端零配置(③ 的基建自动接)。

### B2 检测与安装路径(零新咽喉)

- `github_eval.fetch_repo` 顺带取根目录 `arslan.plugin.json`(GitHub contents API,固定 host,非 SSRF 面);`/discovery/evaluate` 响应附 `manifest`(校验失败 ⇒ 附 `manifest_error`,fallback 到现有 LLM 猜测路径,**不挡评估**)。
- `RepoDossier` 检出清单 ⇒ 渲染「**作者自带配置**」卡:精确 server 列表 + 密钥表单 + 技能列表,取代 LLM 猜的可编辑命令(猜测路径保留为无清单 fallback)。
- Add 动作逐项走**既有锁死路径**:`addMcpServer` → `add_server` 咽喉;技能 → `create_skill` 咽喉。清单是纯数据,**装清单 ≠ 跑代码**;server 首次 connect 仍是用户按钮(= Part A 的人闸)。

### B3 非目标(v1)

- 进程内代码插件 / 自定义 executor 注入:**永不**(裁决 B 红线)。
- 中心化插件 registry、签名与作者身份、自动更新:登记为后续候选,GitHub 搜索漏斗即 v1 分发面。

---

## 实施切分(每 PR 独立全量 + mutation + 逐 id 基线比对)

| PR | 内容 | 量级 |
|---|---|---|
| PR-1 | Part A 全部(migration 0040 + 闸改 + expose 自动 wire + UI 简化 + #38 自知面同步) | 中 |
| PR-2 | B1+B2 后端(manifest 取回/校验、evaluate 附带) | 小 |
| PR-3 | B2 前端(清单卡 + 密钥表单 + 预勾选) | 小-中 |

**裁决点汇总**:① A2 取消勾选的 un-wire 是否保留用户手动项(默认:不保留,全撤);② PR-1 是否单独随 v0.1.24 先发、清单层随 v0.1.25(默认:攒一起)。

## 尚无证据、未声称已验

- Playwright MCP 工具在 free 模型上的 tool-calling 实际表现未验(装备面警告项 ① 的老账,不在本 spec 范围)。
- SKILL.md frontmatter 与 ClawHub 现行格式的逐字段兼容性开工前回源核(别凭 55 天前的记忆)。
