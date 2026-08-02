# Round 2(2026-08-02):四仓集成评估 —— copilot-sdk / qm / reverse-skill / openwork

> **方法:** 17-agent 编排调研(~127 万 token)。四路项目深挖 + 一路 `/home/user/arslan` 接入面测绘并行 → 逐项目集成可行性分析(喂入真实代码测绘)→ 对每条首要结论做**技术面 + 战略面双重对抗验证**。
>
> **登记去向:** R-016~R-022 + 架构事实附录,见 `BACKLOG.md`。
>
> **⚠ 复核状态:** 除 §5 明确标注"已亲核"者外,所有代码断言均来自 agent 阅读,**排期前需工程侧复核**。

## 0. 一句话结论

**四个项目,零个该接。** 三个"借思想不接代码"(copilot-sdk / qm / openwork),一个直接拒绝(reverse-skill)。但过程中挖出**三件白捡的**,其中两件是 Arslan 自有的代码级发现,价值高于任何一项借鉴。

## 1. 逐项目结论

| 项目 | 结论 | 一句话依据 | 许可 |
|---|---|---|---|
| github/copilot-sdk | **拒接**,借 3 项 | MIT 绑定是诱饵,运行时是闭源不可 fork 的 Copilot CLI 二进制,它拥有循环 | 绑定 MIT / 二进制**专有** |
| yc-software/qm | **拒接**,借 4 项 | 无门:MCP SDK 是 devDependency,不对外暴露 server;且强制 Postgres | **MIT,干净兼容** |
| zhaoxuya520/reverse-skill | **拒** | 任务不符 + 许可污染 + 架构上敌对 | MIT 仓夹带 **GPLv3/AGPL** |
| different-ai/openwork | **拒接**,借 2 项 | 它是别人循环的壳,Arslan 本身就是循环——没有接缝 | MIT / **`/ee` 为 FSL-1.1-MIT 带竞业条款** |

详细依据、可借项、硬约束见 `BACKLOG.md` R-019~R-022。

## 2. 贯穿四个项目的同一个模式

**copilot-sdk 租 GitHub 的循环;openwork 租 opencode 二进制;qm 把 harness 做成可替换的;Auto-Company(round 3)租 Claude Code CLI。**

执行底座正在商品化,而**这四个都在示范同一件事:壳 + 别人的循环**。

这恰好定义了 Arslan 不能交易的东西:

- 你不可能**进化**一个不由你运行的 persona;
- 你不可能在你**不拥有的 trace** 里拦截捏造;
- 你不可能给你 **shell 出去的二进制**套沙箱。

三个差异化支柱全是"租引擎的人装不上"的架构属性。**"都不接"本身就是竞争力。**

这也与代码库里的既定决策一致:`seed_catalog.py` 已把 `claude-code` / `codex` / `opencode` 登记为 tier=orchestrator、status=registered、**刻意未接线**("decision §9:透明目录条目")。**本轮四项评估独立地得出了同一结论。**

## 3. 三件白捡的(本轮真收获)

### 3.1 【真缺口】MCP 客户端零 OAuth —— R-016

两个独立 agent 分别 grep 确认:`server/` 下无任何 `oauth`/`pkce`/`authorization_code`/`client_credentials` 命中;`session.py` 的 http transport 仅支持 header 认证。

**后果:生态里所有 OAuth 网关的远程 MCP server,通过 Arslan 最宽的那扇门全都够不着。** 而 MCP 是 Arslan **唯一**的运行时可扩展执行面。这条与四个被评估项目全都无关,是独立发现,**价值高于本轮任何借鉴项**。

### 3.2 【疑似,未证实】工具 schema 无预算全量入 prompt —— R-017

断言:`tool_loop.py` 的 `_native_tool_schemas` 把每个已 wire 工具的完整 schema 预加载进每次 prompt,编排层与 registry 无任何数量预算。若属实,与"随便挂 MCP server"的产品主张直接冲突。

**⚠ 这是代码级疑似,不是已证实缺陷。** 注意既有闸门(`host_enabled` 默认 False、discovery 锁 registered)可能已实际限制规模。**证实前不要动代码**,复核步骤见 BACKLOG R-017。现成解法参照:copilot-sdk 的 `toolSearch: {defer:'auto'}`。

### 3.3 【最高杠杆借鉴】记忆策略接口 + 记忆质量基准 —— R-018

来自 qm。把记忆的巩固/检索策略抽成可插拔接口,骑在已有的 `replay_gate.py` + `evaluator.py` + `synthetic_corpus.py` 上建基准。

**这个市场里没有任何人公布记忆评测数**——OpenWorker、DeerFlow、OpenClaw、Manus、Sim 全都没有。它把"记忆可见可编辑"从主张变成测量。与 R-012(进化循环 kill-criteria)是同一战略动作的两面。

**⚠ 不可谈判的缓解:** 当前行为必须"是"新接口背后的默认策略,而不是与 hybrid FTS5+vector RRF 路径并列的第二个系统。

## 4. 对抗验证的价值:一条首要结论被双面推翻

分析 agent 曾把"两工具能力轨"(把 S4.1-C 的 server 侧收成 `search_capabilities` + `execute_capability`)列为 openwork 的**首要借鉴**。**两个对抗验证器独立推翻,理由成立,已采纳推翻:**

1. **前提是假的** —— skill 在 Arslan 里不是 tool(SKILL.md 正文进系统提示词),spawn 早已是"一个工具带 id 参数";内置面共 16 工具 / 9 toolset,C 的锁定读范围是"列 spawn、列 skill、查 brain"。**本来就是常数,不存在要解决的爆炸。**
2. **会推翻已锁决策** —— 外部客户端按**工具名**授权;合并成两个工具后,用户无法"允许读、拒绝派发",一次批准等于批准背后全部能力,**包括进化循环在批准之后新长出来的能力**;且无法标 `readOnlyHint`。
3. **许可陷阱** —— 那条轨的代码**只存在于 FSL 那半边**(`ee/apps/den-api/src/mcp/`)。写成"MIT 先例"是假的出处声明;"去参考实现"等于指挥实现者打开唯一不能打开的文件。

**正确替代:** C 按原计划出小而固定的具名读工具集;若能力宇宙确实增长,用**一个具名读工具**把目录**作为数据**返回(本就是 `safe_menu()` 的习惯用法);**写侧永不藏进通用 executor。**

> 记录此条不是为了自责,而是为了**留下"这个提议已被否决"的痕迹**,防止后续有人重新提出同一设计。

## 5. 附带发现:S4.1-C spec 必须预算的两项成本

**⚠ 待亲核。**

1. **confirm 通道:** `tool_loop.py:301-316` 的 `run_command` 在 `confirm_command` 回调为 None 时**拒绝执行**(安全默认),而该回调是 WS/UI 绑定的。stdio 上没有这个通道 → 特权能力要么 fail closed(写侧变惰性),要么需要新的 confirm 传输(MCP elicitation)。**这不在任何现有估算里。**
2. **服务抽取:** `server/api/brain.py` 的 tree/graph/entry 处理器是**内联裸 SQL**,不是可调用 service。"复用已有安全层读服务"只对 `notes.py` 成立。且 `require_auth` 是 HTTP 层的,stdio server 继承不到。

## 6. 市场竞争力净判断

- **采纳任何一个 = 强稀释。** 尤其 copilot-sdk:会让 Arslan 比最近的正面竞品 OpenWorker(MIT、Tauri+Python、local-first)**更不 local-first、更不可审计**,并在 go-public 前把专有二进制放进 Apache-2.0 分发包。
- **openwork 已把"一个 MCP URL 带着整套配置进 Claude Code/Cursor"变成品类预期** —— 但它是**账号托管 + FSL 许可**的实现。**Arslan 能纯本地、无账号做同一件事,这是它因商业模式结构性做不到的楔子。** → **S4.1-C 的紧迫度上调。**
- **qm 是定位礼物而非竞品:** "qm 是你公司跑的,Arslan 是你自己跑的。"
