# Round 3(2026-08-02):四仓快查 —— Auto-Company / beautiful-mermaid / OpenGOO / Graphify(复核)

> **方法:** 直接检索 + 本仓单点亲核(未起编排调研)。Graphify 为 round-2 前已调研项的**复核**,结论有实质变化。
>
> **登记去向:** R-011(升级)、R-015、R-023、R-024,见 `BACKLOG.md`。

## 0. 一句话结论

**这轮终于有能直接接的了。** 两个可落地(beautiful-mermaid 直接 `npm install`;Graphify 从"蓝图"升级为可接 preset)、一个借两个想法(Auto-Company)、一个与 Arslan 无关(OpenGOO,疑似链接贴错)。

## 1. beautiful-mermaid —— 接(本轮性价比最高)

| | |
|---|---|
| 出品 | Craft 团队(笔记 app),为自家 Craft Agents 而做 |
| 规模/许可 | 10.8k★,**MIT** |
| 形态 | npm 包,纯 TypeScript,**零 DOM 依赖**,**同步渲染**(配 React `useMemo`) |
| 输出 | SVG **或 ASCII/Unicode**;6 种图型;15 套主题 + 兼容 Shiki |
| 依赖 | 内置 ELK.js 布局(FakeWorker 同步跑) |

### ✅ 已亲核的缺口

`web/package.json` 的依赖里**没有 mermaid**:

```
echarts, d3-drag, d3-force, d3-selection, d3-zoom, react-markdown,
remark-gfm, motion, ogl, lucide-react, i18next…
```

而 `arslan/spawn/seeds/` 下有 `architecture-diagram` 与 `excalidraw` 两个产图技能。

**→ agent 写出的 mermaid,现在在聊天里就是一段纯代码块。**

### 接法与价值

给 `react-markdown` 的代码块渲染器加一个 ```mermaid 分支即可。**LLM 天生爱吐 mermaid**,这是零训练成本的能力升级:架构图、流程图、时序图从"一段代码"变成"一张图"。第二大脑图谱视图(R-003)与 deck/report seeds 均受益。

**额外的巧合价值:ASCII 输出模式**对 S4.1-C 的 MCP server 侧有用——Arslan 被 Claude Code / Cursor 这类**终端环境**消费时,ASCII 图是终端里唯一能看的形态。

### ⚠ 两个必须处理的注意

1. 它是 mermaid 的**重新实现**,只支持 6 种图型(flowchart/state/sequence/class/ER/XY)。agent 吐 gantt/pie/mindmap 会渲染不出 → **必须保留回落到代码块**,否则成了"看着支持实际瞎了"。
2. 内置 ELK.js,**前端包体会涨,接前量一下**(Arslan 正走向 Tauri 打包)。

## 2. Graphify —— 复核有实质变化:蓝图 → 可接 preset

上一轮结论是"R-002/R-003 的架构蓝图"。本次复核发现**三件事变了**:

1. **它有 MCP server** —— `graphify --mcp`(stdio)+ `python -m graphify.serve`(HTTP),工具 `query_graph` / `get_node` / `get_neighbors` / `shortest_path` / `list_prs` / `get_pr_impact`。
2. **双许可 Apache-2.0 / MIT** —— 对 Apache-2.0 的 Arslan 完全干净。
3. **星数 90.6k → 100.3k**(约一周涨 1 万)。

→ **从"参照实现"升级为 R-001 同级的 preset 候选**:PyPI 包名 `graphifyy`,走 `uvx` 模式(与现有 `mcp-server-fetch` 同款形状),无 key = one-click。分身可以查代码库知识图谱、问"auth 和数据库之间有什么连接"。

**⚠ 待工程侧复核:** 确切 CLI 命令行/包名/参数未亲核。catalog 纪律要求**静态已审数据**,加进目录前必须人工验证。与 R-001(flint-mcp)、R-008(playwright-mcp)同批处理。

**架构背书价值不变**(原登记保留):它用 100k★ 证明了"**真图谱可以不背图数据库**"——嵌入式 `graph.json` + `graph.html`,Neo4j/FalkorDB 只是可选 `--push` 导出;每条边带 provenance + confidence("every edge is explained"),而 `server/api/brain.py` **已经**在按 provenance/confidence 组装节点边。这是"借概念不借基建"的实锤背书。

## 3. Auto-Company —— 借两个想法

MaxMiksa(CMU),**2.2k★,MIT**。14 个专家 persona 模拟一家公司 24/7 自主运转,每轮**动态组队 2-5 人**,`memories/consensus.md` 作为轮次间的"接力棒",人类编辑其中的 **"Next Action" 字段**掌舵。引擎是 Claude Code 或 Codex CLI,核心循环 Bash,daemon 跑(launchd/systemd)。自称实验性。

### 借

1. **动态组队** —— Arslan 现在路由到**单个** spawn。"按当前优先级选 2-5 个分身协同"是 persona 团队叙事的自然下一步,**也是目前的真空白:卖的是"团队",实际跑的是"轮流单干"。**
2. **人类方向盘字段** —— "改一个字段,下一轮 agent 立刻读到"比审批弹窗更适合长周期自主。与 R-014(OpenWorker)的"无人值守请求停进 inbox"同族,**建议一起设计**(对应 Arslan 的 evolution inbox + scheduled tasks)。

### 不借

- 又是**租引擎**(Claude Code/Codex CLI)——本轮研究里第四个同款模式;
- Bash 核心循环与 Python 栈不可组合;
- **persona 直接用在世真人命名**(贝索斯、DHH、Paul Graham、Seth Godin、Ben Thompson…)——产品里这么做有身份/声誉气味。Arslan 的分身是用户自养角色,不学。

### 定位验证(本条最大价值)

"AI persona 团队"这个概念在野外最像的实现,**只有 2.2k★,是 Bash + 租 CLI + 自称实验性**,没有真后端、没有进化循环、没有可见记忆。

**没有人把它认真做出来过——赌注那块地目前还空着。** 这与 round 2 及此前竞品轮的结论一致。

## 4. OpenGOO —— 与 Arslan 无关

经核实:**World of Goo(粘粘世界)的开源克隆游戏**。Qt5 + OpenGL + C++,**GPLv3**,153★,24 fork,543 commit,pre-alpha,README 自陈"还不能玩"。

**未找到任何与 Arslan 的接点,不强行制造关联。** 疑似链接贴错。登记于此仅为留痕。

## 5. 本轮净影响

- 主线不动。
- **两条 catalog 数据批次的候选就位**(R-011 Graphify + R-008 playwright-mcp + R-001 flint-mcp)——同批人工验证后一次性加进 `server/mcp/catalog.py`。
- **一条前端门面活就位**(R-015),与 E 批次同做。
- **一条能力空白被点名**(多分身组队),是"persona 团队"叙事与实现之间目前最大的落差。
