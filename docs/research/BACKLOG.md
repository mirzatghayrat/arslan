# Research-driven backlog(登记簿)

> 规则见 `README.md`:登记不插队,每条带证据 + 归属建议。
>
> **状态:** `登记` → `已消化`(进主线 spec/plan)→ `已落地` / `已否决`
>
> **每条必带:** 结论(接 / 借 / 拒 / 决策)· 依据 · 许可状态 · `⚠ 待工程侧复核` 标记(凡未经本仓代码亲核的技术断言一律打标)
>
> **日期说明:** R-001~R-006 首轮登记与 R-007~R-024 同属 2026-08-02 一次调研会话;R-001 引用的上游来源来自更早的 claude.ai 会话。

> ### 🔴 工程侧复核覆盖面(2026-08-02,main=`09917c2`)
>
> **只复核了三条**——R-015、R-016、R-017——理由是**只有这三条我将来要亲手动代码**。
> **其余 21 条未逐条亲核**,登记册里各自的 `⚠ 待工程侧复核` 标记**依然有效**,
> 不因为本次复核而降级。**动某一条之前先核那一条。**
>
> 新增 R-025(前缀缓存约束)为设计规则,已亲核。

## 索引

| # | 标题 | 结论 | 复核 |
|---|------|------|------|
| R-001 | flint-mcp preset | 接(待确认发行方式) | ⚠ |
| R-002 | 用户事实库时态化 | 接 | **已落地(P1)** |
| R-003 | 第二大脑图谱视图门面 | 接(门面批次) | — |
| R-004 | `sensitive` 标志零语义 | 接(P2) | 已亲核 |
| R-005 | `.af` = Letta 既成格式 | 借(D spec 输入) | — |
| R-006 | SKILL.md 已成行业标准 | 借(叙事)+ 符合度核对 | ⚠ |
| R-007 | Mac App Store 姿态 | 决策:双轨减配 | ⚠ |
| R-008 | playwright-mcp preset | 接 | ⚠ |
| R-009 | GUI 自动化 / UI-TARS 姿态 | 拒(全桌面)+ 观察 | — |
| R-010 | DeerFlow 竞品定位 | 借(定位教训) | — |
| R-011 | Graphify → preset | 接(升级自"蓝图") | ⚠ |
| R-012 | 定位收窄 + 进化循环 kill-criteria | 决策 + 实验 | — |
| R-013 | apple/container 沙箱升级 | 借(spike) | ⚠ |
| R-014 | OpenWorker:威胁 + F 蓝图 | 借 | — |
| R-015 | beautiful-mermaid | 接 | ✅ 工程侧复核(2026-08-02) |
| R-016 | **MCP 客户端零 OAuth** | 接(真缺口) | ✅ 工程侧复核(2026-08-02) |
| R-017 | **工具 schema 无预算全量入 prompt** | **部分证实,严重性证伪** | ✅ 已亲核(三步) |
| R-018 | 记忆策略接口 + 记忆质量基准 | 借(最高杠杆) | — |
| R-019 | github/copilot-sdk | **拒接**,借思想 | — |
| R-020 | yc-software/qm | **拒接**,借思想 | — |
| R-021 | zhaoxuya520/reverse-skill | **拒** | — |
| R-022 | different-ai/openwork | **拒接**,借 2 项 | — |
| R-023 | Auto-Company:多分身组队 + 人类方向盘 | 借 | — |
| R-024 | 竞品雷达汇总 | 参考 | — |
| **R-025** | 🔴 **前缀缓存约束**(设计规则,非某项的脚注) | **决策** | ✅ 已亲核 |

---

## R-001 flint-mcp 加入 preset connector 目录

- **结论:接**(待确认发行方式后落地)
- **状态:** 登记
- **是什么:** 微软 flint-chart(1.8k★,v0.2)自带 MCP server(flint-mcp):agent 给紧凑的语义类型描述,编译器自动推导优化图表配置,输出 Vega-Lite/ECharts/Chart.js(30+ 图型)。
- **依据:** 大概率无 API key = one-click 级 preset,给对话式 MCP 接入添第一个高展示价值新预置;其"语义类型→自动调优"路线可作内置 `render_chart` 的质量参照。
- **许可:** MIT(可安全作为 preset 引用;preset 只是启动第三方进程,不构成分发)。
- **代码接点:** `server/mcp/catalog.py` 的 `CONNECTORS`(静态、已审数据,禁运行时拉取)。
- **⚠ 待工程侧复核:** flint-mcp 的确切发行方式(npx/uvx 包名)、env 需求、transport 均未亲核。Python 移植仍是 preview。
- **归属:** S4.1-C 合并后的顺手小活(≤0.5d)。与 R-011 同批处理。

## R-002 用户事实库时态化(修复"只增不减"中危项)

- **结论:接 → 已落地**
- **状态:** ✅ 已落地(第二大脑 P1,分支 `spec/brain-p1-temporal`)
- **原始问题证据(登记时坐实):**
  - `server/db/models.py:129-141` — `UserFact` 无 `valid_from`/`superseded_by`/细粒度 provenance,无衰减、无上限。
  - `server/orchestrator/memory.py:310-315` — `facts_text()` 把**全部** facts 渲染成 bullet 注入 prompt,`list_facts()` 无 LIMIT。
  - 注入点 5 处:`router.py:143`、`arslan.py:943`、`dispatcher.py:285`、`spawn_drafter.py:42`、`replay_run.py:38`。
  - 增长机制:`distill_service.py:53-96` `distill_meta_upflow` 每分身每会话最多上浮 1 条 → 随使用量线性增长。
- **内部先例:** 分身级记忆早已是合并式(`distill_service.py:32` `_MAX_FACTS=8`),同一代码库里合并模式存在,只是没应用到 Arslan 级用户画像层。
- **落地形态(P1 实际交付,优于原登记稿):** migration 0032 三处 lockstep;取代执行器 `memory_temporal.py`(单指针写、旧行永不删、可 undo、防自环/重指/链环/悬空);规则发起方向锁死(只有"新扩展旧"containment 自动取代,反向 shrink + 非 containment fuzzy → 并存 + 提案);检索默认活跃-only 走 `facts_text` 单一咽喉,五个注入点零改动继承;provenance 强制;提案裁决 API。
- **mem0 教训(修正 S4 计划 P3 的过时表述):** mem0 已从"写时两遍 LLM 做 ADD/UPDATE/DELETE 仲裁"退回 **ADD-only 单遍 + 检索时排序**。P3 里"memory write-time update (mem0-style)"应改为"轻量 supersede 标记 + 读路径分辨"。**⚠ 待主线消化时改 S4 计划正文。**
- **诚实账:** 活跃-only 让 replay ambient 第三次变更 → 进化评分输入变,合并后前几轮评分基线漂移不应误读为回归。

## R-003 第二大脑图谱视图 = 知识地图门面

- **结论:接**(门面批次,低优先)
- **状态:** 登记
- **现状:** 基础已存在——README 即宣传 Obsidian-style force-directed graph;`server/api/brain.py` 已按 provenance/confidence 组装 nodes/links。不是从零建,是把已有图谱打磨成展示门面。
- **依据:** "记忆可见可编辑"是差异化支柱,知识地图可视化是其自然延伸。R-011(Graphify)是成熟度参照,R-015(beautiful-mermaid)可复用于此。
- **归属:** 与 E(evolution-inbox UX)同批,launch 叙事素材。

## R-004 `sensitive` 标志是装饰性的

- **结论:接**(P2 范围)
- **状态:** 登记 —— **P1 未关闭此项,勿误记为已修**
- **问题:** `UserFact.sensitive` 有 schema 字段(`models.py:137`)、REST 可编辑(`api/facts.py`)、WS 协议回显(`ws/protocol.py:111`)、router 抽取时会判定(`router.py:42`)——但 `facts_text()` 注入时**完全不过滤**。敏感事实与普通事实一样流进:路由、回答、**分身派发**(`dispatcher.py:285`)、分身起草、以及**评测重放臂**(`replay_run.py:38` `snapshot_ambient` → 进化循环的 eval 上下文)。
- **P1 的关系(必须区分):** P1 的 D2 做的是"读 API 诚实"(端点照样返回敏感内容,只是现在**声明**了);R-004 担忧的是 **injection 侧**(分身派发 + replay/eval ambient)。**不同的面,injection 侧语义仍开着。**
- **P1 带来的红利:** 读路径已收敛成 `facts_text` 单一咽喉,过滤从"改 5 处"变成"改 1 处"。
- **依据:** 用户显式标记"敏感"的心智模型是"被特殊对待",实际零语义;敏感事实进 eval/replay 与 `run_redact.py` 的隐私保留姿态不一致。
- **归属:** P2(三级写授权)同一 spec,读侧敏感语义与写授权一起定。**决策比代码贵——需产品先拍板语义。**

## R-005 `.af` = Letta 的既成格式(S4.1-D 的必答题)

- **结论:借**(作为 D spec 的前置决策输入,不新增工作项)
- **事实:** Agent File (.af) 是 Letta 2025-04 发布的开放格式(letta-ai/agent-file,~1k★),序列化 system prompt + 可编辑记忆 + 工具配置 + LLM settings,JSON 人类可读。目前是该领域唯一有名字的标准,生态尚早。
- **对 D 的输入:** "Arslan 自有 bundle vs 兼容 Letta .af"必须是 D spec 的第一个决策。互操作趋势(见 R-006)支持至少**读**兼容;写格式可自有扩展(spawn 的 evolution 状态、SKILL.md 引用是 Letta 没有的概念)。
- **许可:** Apache-2.0(格式本身开放)。

## R-006 SKILL.md 已成行业开放标准

- **结论:借**(叙事资产)+ 符合度核对(小活)
- **事实:** Anthropic 2025-12-18 将 Agent Skills 发布为开放标准(agentskills.io);48 小时内 VS Code/ChatGPT/Codex 跟进;2026-03 已有 32 个工具读同一 SKILL.md 结构;社区目录百万级。生态短板是**质量与安全**(ClawHub 恶意 skill 事件)。
- **对 Arslan:** ① 原生就说 SKILL.md,是 go-public 叙事的现成资产;② `skill_import.py` 的 license gate/caps/traversal guard/sandbox 恰好卡在生态最痛点上,launch 时值得写进 README。
- **⚠ 待工程侧复核:** 与 agentskills.io 正式 spec 的逐条符合度未核。2026-07-09 已有 pc-skill-compatibility 计划,**先查它是否已覆盖**,再决定是否需要新工作项。
- **许可雷区(重要):** [anthropics/skills](https://github.com/anthropics/skills) 官方仓库中 pptx/docx/xlsx/pdf 那组文档技能是 **source-available 不是开源** —— **Arslan 不得捆进 seeds**(Apache-2.0 产品不能分发)。用户自行经 `skill_import` 导入自用不受此限(license gate 正是干这个的)。仅可作为质量参照。

---

## R-007 Mac App Store 姿态 = 双轨减配(F spec 决策 5 的答案)

- **结论:决策——可上架,但上架的是减配版;Tauri 同源出双 build**
- **状态:** 登记(回答 S4 计划中悬置的"决策 5:Windows/macOS-App-Store 姿态")
- **技术依据(查实):**
  - App Sandbox 内**子进程强制继承父沙箱,进程不允许更换自己的沙箱**;自定义 sandbox-exec profile 无法覆盖已有 entitlements → **"每次生成代码跑在独立网络拒止 seatbelt"在 MAS 内技术上不成立**。
  - `npx`/`uvx` 型 MCP 连接器断(运行时下载可执行代码,违反审核 2.5.2 + 沙箱内无工具链)。remote/HTTP 型 MCP 不受影响。
  - **不是障碍的:** 内嵌签名 Python 解释器可过审且保持沙箱完整;localhost 监听有 entitlement;BYOK 有活先例(Geeps、Pal Chat 在 App Store)。
- **关键洞察:** 该"砍"不是新成本——**MAS 版 ≈ Windows 姿态的 macOS 化**。S4 计划已定"Windows 无沙箱 → `run_python`/`run_command` 默认关闭/fail-closed",fail-closed 开关已在代码里。
- **先例:** CodeRunner 4(MAS 沙箱版上架 + 受限场景指引官网完整版,对 MAS 买家免费);Home Assistant companion(App Store 接受"价值依赖自架服务器"的客户端,minimum-functionality 不是障碍)。
- **市场判断:** Mac App Store 边际价值低(品类惯例是官网 DMG);**真正价值在 iOS/iPadOS companion**——iPhone 上 App Store 是唯一的门,而"手机上使唤 Mac 上的分身团队 + human-confirm 天生是手机交互"是 Arslan 形态里最消费级的故事。
- **建议路线:** 开源 → Tauri(DMG 完整版,主线不变)→ iOS companion(SwiftUI 瘦客户端,上架)→(可选)Mac MAS 减配版当获客漏斗。**不需要"纯原生重写"——Tauri 本身能上 MAS,障碍是能力集不是框架。**
- **⚠ 待工程侧复核:** 全部为外部文档与先例研究,未做任何打包/提审验证。真启动 F 时需实机 spike。
- **归属:** F(Tauri)spec 的决策 5 输入。

## R-008 playwright-mcp 进 preset connector 目录

- **结论:接**(优先级高于 R-001)
- **依据:** microsoft/playwright-mcp(33.8k★)是 2026 年 agentic 浏览器自动化的事实默认;走**可访问性树**语义快照(单次 200-400 token,不吃像素),暴露 `browser_navigate`/`browser_click`/`browser_snapshot` 等 ~30 个确定性工具。
- **为什么天作之合:** ① **不引入新模型依赖**——用户自己的 BYOK 模型直接驱动;② `npx` 一键、无 key(one-click),与现有 catalog 的 fetch/memory 同款形状;③ 浏览器作用域可收容(独立 profile、默认不带登录态);④ seeds 里已有 `webapp-testing/SKILL.md`,加了这个 preset 那个 seed 才真正长出手来。
- **许可:** Apache-2.0(微软)——preset 引用无问题。
- **⚠ 待工程侧复核:** 确切包名/参数/是否需 `--headless` 等默认值未亲核。
- **归属:** 与 R-001、R-011 同批(catalog 数据批次)。

## R-009 GUI 自动化姿态:拒全桌面,浏览器作用域为限

- **结论:拒**(全桌面 computer use)+ **观察**(UI-TARS / Agent-TARS)
- **格局(查实):** ① playwright-mcp = 浏览器自动化引擎的 MCP 化,任何 LLM 可驱动;② computer use(Claude/OpenAI Operator)= 前沿模型的像素级桌面能力,按 token 计费、绑定该家模型;③ UI-TARS-desktop(字节,38.1k★)= 专训开源 GUI 模型(7B 可本地跑)+ 桌面 App,Local/Remote/Browser 三种 Operator。
- **诚实标注:** UI-TARS-2 论文"超 CUA/Claude 35+ 分"是 2025-09 对当时产线系统的数字;十个月后前沿通用模型已在桌面基准反超。专用小模型的持久优势是**开源、本地、便宜**,不是"最强"。
- **拒的理由:** 全桌面 GUI 控制是 Arslan 差异化的**反物质**——它操作用户真实登录态的整个会话,天然绕过一切沙箱;屏幕内容是 prompt-injection 的天然入口。OpenClaw 的安全灾难恰在这一层。**留活口:** power user 自己经 MCP 挂 computer-use server,Arslan 不背。
- **将来若做,形状是 UI-TARS 式的:** 本地开源 VLM + 浏览器作用域。把桌面截图(可能正显示第二大脑)持续发云端 API,是隐私姿态的自我反转。
- **另记:** Agent-TARS 整个栈是 TypeScript 的"个人多模态 agent"框架,邻位竞品,进 R-024 雷达。

## R-010 DeerFlow 竞品定位:管道已成 table-stakes

- **结论:借**(定位教训,不接任何代码)
- **事实:** bytedance/deer-flow 2.0(2026-06),**77.3k★**,v2 是彻底重写,LangGraph + Docker/K8s + PostgreSQL/SQLite,定位从"深度研究框架"长成通用 **super agent harness**;lead-delegate-synthesize 多 agent、子 agent 隔离上下文、历史压缩、长期记忆去重、MCP + OAuth、SkillScan 安装前安全扫描、cron 定时 + pause/resume、SKILL.md 渐进加载、每任务 sandbox、local-first 127.0.0.1、全 IM 渠道。
- **最贵的信息——它告诉你哪里不该花力气:** MCP 集成、定时任务、skill 安全扫描、多 agent 编排、local-first **已是入场券不是卖点**。go-public 叙事不能再吹这些。
- **但不是正面竞品:** 它是"开发者基础设施"(要你自己部署、Docker/K8s sandbox),不是桌面产品;**缺 Arslan 三支柱**——可见可编辑第二大脑、诚实守卫、两层自进化 persona 团队。
- **许可:** 未逐条核(MIT/Apache 系),**不接代码故无关**。

## R-011 Graphify → 从"架构蓝图"升级为可落地 preset

> **⚠ 动手前置(未做,catalog 既定纪律)**:确切 PyPI 包名(`graphifyy`?)与 uvx 命令行**人工确认**;
> 许可**回源核**(源仓库 LICENSE + 包内文件),**PyPI 元数据不作依据**——这条骗过我们两次且方向相反。

- **结论:接**(preset 目录)+ 借(架构背书)
- **状态:** 登记 —— **本条已升级**,原登记为"仅蓝图参照"
- **升级依据(复核发现):** ① **它有 MCP server** —— `graphify --mcp`(stdio)+ `python -m graphify.serve`(HTTP),工具 `query_graph`/`get_node`/`get_neighbors`/`shortest_path`/`list_prs`/`get_pr_impact`;② **双许可 Apache-2.0 / MIT**,对 Apache-2.0 的 Arslan 完全干净;③ PyPI 包名 `graphifyy`,走 `uvx` 模式,与现有 `mcp-server-fetch` 同款形状;④ 无 key = one-click。
- **是什么:** tree-sitter 本地 AST 抽取(零 LLM、代码不出机器)把代码库/文档/媒体建成可查询知识图谱;YC S26;星数 90.6k → **100.3k**(约一周涨 1 万)。
- **架构背书价值(原登记保留):** 它用 100k★ 证明了"**真图谱可以不背图数据库**"——输出嵌入式 `graph.json` + `graph.html`,Neo4j/FalkorDB 只是可选 `--push` 导出;每条边带 provenance + confidence(`EXTRACTED` vs `INFERRED`,"every edge is explained"),而 `server/api/brain.py` **已经**在按 provenance/confidence 组装节点边。这是给 R-002/R-003"借概念不借基建"路线的实锤背书,也是 R-003 门面工作的成熟度参照。
- **⚠ 待工程侧复核:** 确切 CLI 命令行、包名、参数未亲核;catalog 纪律要求静态已审数据,加进目录前必须人工验证。
- **归属:** 与 R-001、R-008 同批。

## R-012 定位收窄 + 进化循环 kill-criteria 实验

- **结论:决策(收窄)+ 实验(必做,launch 前)**
- **背景:** 连续多轮竞品对比(DeerFlow / OpenClaw / Manus / Sim / OpenWorker / Auto-Company)浮出的 Arslan 优势**每次都收敛到同一组**:BYOK 省钱 / 本地隐私 / 开源可控 / 诚实可见 + 会进化的团队。这种收敛本身是信号。
- **决策:不砍项目,换重心。** 停止把 Arslan 当"再造一个 agent 平台"推;编排/MCP/定时/sandbox 降级为"够用就行,别再打磨";力气收拢到**一个整合赌注**:会进化的 persona 团队 + 可见可编辑记忆 + 诚实,做成**给个人的桌面产品**(不是给人部署的 infra)。go-public 不能以"又一个 agent harness"身份出场。
- **kill-criteria 实验(本条的硬核):** 进化循环是三支柱里唯一 novel 且**尚未证明**的(README 自陈"being hardened, not yet claimed as fully proven")。**做一次诚实 A/B:同一批任务,进化前 vs 进化 N 轮后,LLM-judge 盲评。拉不出统计显著增益,这根柱子就是空的。**
- **零件齐备:** `replay_gate.py`(paired-holdout 评分、`_delta`、`GateResult`、`Corpus`)、`evaluator.py`(LLM judge)、`compare_judge.py`、`synthetic_corpus.py`。
- **及格线已被别人画出(见 R-024/OpenSpace):** OpenSpace 公布了 Terminal-Bench 2.1 上 65.2% → 78.7% 的 skill 进化增益。**从此光喊 "self-evolving" 已落后——launch 时要么拿得出自己的前后数字,要么这根柱子在明眼人面前就是没兑现的口号。**
- **方法论抄作业:** OpenSpace 选了**更容易测**的单元(skill 挂 benchmark 出干净数)。Arslan 进化的是 persona(system prompt + skill + 工具 + memory_facts,更丰富但更难量)。**先在能拿到干净数字的层级测(单 spawn 挂一个任务集的前后盲评),别一上来测"整个团队变没变好"。**
- **与 R-018 的关系:** R-018(记忆质量基准)是同一战略动作的另一面——两个都把主张变成测量。

## R-013 apple/container:生成代码执行环境的结构性解锁

- **结论:借**(先做 1-2 天 spike,不插主线队)
- **是什么:** apple/container 1.0(2026-06-09),**Apache-2.0**,Swift,**每容器一台轻量 VM**(经 Virtualization framework),OCI 兼容(Docker Hub 镜像直接用)。官方场景明确包含"跑 AI 生成的代码"。
- **为什么是结构性的:** 当前 seatbelt 沙箱是"网络拒止跑 Python"——安全但**装不了包、联不了网、无完整工具链**,这正是"Manus 能折腾出结果、Arslan 只能小打小闹"的根因。apple/container 让生成代码从此变成"**一台可丢弃的完整 Linux**:pip/npm 随便装(装在 VM 里不碰宿主)、出网走策略闸、用完即销毁"。**逃逸要穿过 hypervisor,隔离比 seatbelt 更硬——安全故事不是被牺牲,是被加强。**
- **代价:** 要 macOS 26。对 macOS-first 的 pre-v1 产品可接受。
- **⚠ 待工程侧复核:** 未做任何本机验证;与现有 `code_sandbox.py`/`command_sandbox.py` 的 `SandboxBackend` 抽象如何对接未设计。**它动 sandbox 地基,必须 spike 后再决策,spike 结论喂给 F 的 spec 一起定。**
- **相关:** `code_sandbox.py` 的 Linux `BubblewrapBackend` 槽位存在但返回 False —— 填它是 Linux/Windows code-exec 的另一条解锁路径。

## R-014 OpenWorker(Andrew Ng):最近的正面竞品 + F 阶段蓝图

- **结论:借**(F spec 直接输入)+ 战略警报
- **事实:** Andrew Ng 与 Rohit Prasad 于 **2026-07-23** 发布,MIT,**Tauri 2 + React 壳 + 本地 Python FastAPI agent server(基于 aisuite)**,BYOK 多模型 + Ollama,25+ 连接器,签名公证 + 自动更新,mac 已发 Windows 在路上,发布两天 4.4k★。
- **为什么是警报:** 之前的竞品都是斜的(OpenClaw=渠道、DeerFlow=dev harness、Manus=云、Sim=画图),**这个是正面同格**:形态、架构、许可、BYOK、local-first 全部重合,而它有品牌、有分发、有 polish。
- **可借(它 MIT,合法白拿):**
  1. **F 阶段最难的问题它趟完了** —— "Tauri 2 + Python sidecar + React,签名公证自动更新跨 Win"正是 S4 标注"~3-5 周/平台、design doc 从未写过"的那座山,现在有活的 MIT 参考实现。**F 的 spec 成本和风险直接砍半。**
  2. **类型化风险审批** —— 每个工具调用先分四类:`read`(无副作用放行)/ `write_local`(改工作区,路径限定)/ `exec` / `external`。Arslan 有 safe/orchestrator 两层 + confirm 闸,这个四类清晰度值得吸收进能力层分类学。
  3. **"无人值守的运行把请求停进收件箱"** —— 定时任务遇到需审批动作不自己动,停进 inbox 等人,带完整 transcript。与 Arslan 的 scheduled tasks + evolution inbox 是现成拼图(与 R-023 的"人类方向盘"同族,一起设计)。
  4. **OAuth broker 模式** —— 云端小服务只做 OAuth 握手中转,token 落本地 secret store。解决 MCP preset "填 API key"到不了消费级(Gmail/Slack 要 OAuth app)的鸿沟。代价是引入托管组件,是权衡不是白拿。**与 R-016 强相关。**
  5. **"要一个结果,不是要一个 prompt"的 UX 语言。**
- **它没有的(护城河被衬清楚):** 无沙箱(terminal 直跑靠审批闸——长期用户会审批疲劳,而 Arslan 的内核沙箱是"不需要每次点头也安全")、无 persona/subagent 体系(单 agent)、无自进化、记忆故事几乎空白。**三支柱一根都没被碰。**
- **战略含义:** ① 方向获最高级别背书,但**这个格子从 2026-07-23 起有主人了**——**S4.2 go-public 紧迫度上调一档**;② launch 话术须预设"OpenWorker 已存在",出场身份不能再是"本地优先的 AI 同事"(被占了)。
- **注意与 R-022 区分:** OpenWorker(andrewyng)与 OpenWork(different-ai)是**两个不同项目**,勿混。

## R-015 beautiful-mermaid:聊天内 mermaid 渲染

> ✅ **工程侧复核(2026-08-02,main=`09917c2`)**:`web/package.json` 中 mermaid 计数 **0**,`web/src/` 零引用。缺口属实,可按计划接。
>
> **⚠ 动手前置(未做):** ① 量前端体积(内置 ELK.js);② 实测它那 6 种图型的覆盖,
> 并确认 gantt/pie/mindmap 的**回落到代码块**路径真的存在。两条都在接入前,不在接入后。

- **结论:接**(本轮唯一能直接 `npm install` 的)
- **是什么:** Craft 团队(笔记 app)为 Craft Agents 做的 mermaid 渲染库,**10.8k★,MIT,纯 TypeScript,零 DOM 依赖,同步渲染**(配 React `useMemo`),输出 SVG **或 ASCII/Unicode**,6 种图型(flowchart/state/sequence/class/ER/XY),15 套主题 + 兼容 Shiki。内置 ELK.js 布局(FakeWorker 同步跑)。ASCII 引擎移植自 Alexander Grooff 的 mermaid-ascii(Go→TS)。
- **✅ 已亲核的缺口:** `web/package.json` 依赖里**没有 mermaid**(现有:echarts、d3-*、react-markdown、remark-gfm、motion、ogl、zustand…)。→ **agent 写出的 mermaid 现在在聊天里是一段纯代码块**,而 seeds 里有 `architecture-diagram` 和 `excalidraw` 两个产图技能。
- **接法:** 给 `react-markdown` 的代码块渲染器加 ```mermaid 分支。LLM 天生爱吐 mermaid,零训练成本的能力升级。第二大脑图谱(R-003)与 deck/report seeds 均受益。
- **额外价值:** **ASCII 输出模式**对 S4.1-C 的 MCP server 侧有用——Arslan 被 Claude Code / Cursor 等**终端环境**消费时,ASCII 图是终端里唯一能看的形态。
- **⚠ 两个必须处理的注意:** ① 它是 mermaid 的**重新实现**,只支持 6 种图型——agent 吐 gantt/pie/mindmap 会渲染不出,**必须保留回落到代码块**,否则成了"看着支持实际瞎了";② 内置 ELK.js,前端包体会涨,接前量一下。
- **许可:** MIT —— 可安全作为前端依赖分发。
- **归属:** 与 E(inbox UX)同批门面活,0.5-1d。

---

## R-016 【真缺口】MCP 客户端零 OAuth 支持

> ✅ **工程侧复核(2026-08-02,main=`09917c2`)**:`server/mcp/` 与 `server/services/` 全树无 `oauth`/`pkce`/`authorization_code`;`server/mcp/session.py:38` 是 `streamablehttp_client(server["url"], headers=server.get("env") or {})` —— **仅 header 认证**。缺口属实。

- **结论:接**(独立于任何外部项目的自有缺口,本轮最高价值发现之一)
- **依据:** 两个独立 agent 分别 grep 确认:`server/` 下**无任何** `oauth` / `pkce` / `authorization_code` / `client_credentials` 命中;`server/mcp/session.py:36-40` 的 http transport 只把 env dict 当 **HTTP headers** 传(即仅支持 header 认证)。
- **后果:** **生态里所有 OAuth 网关的远程 MCP server,通过 Arslan 最宽的那扇门(MCP 客户端)全都够不着。** 而 MCP 是 Arslan **唯一**的运行时可扩展执行面(见下方"架构事实")。
- **相关:** R-014 的 OpenWorker OAuth broker 模式是一种解法参照;R-022 的 OpenWork 亦以账号托管 OAuth 为其能力面核心。
- **⚠ 待工程侧复核:** grep 阴性结论置信度高,但**建议工程侧再确认一次**(尤其确认是否有第三方库层面的隐式支持)。
- **归属:** 建议独立 backlog 项,优先级高于本轮多数借鉴项。

## R-017 【疑似,未证实】工具 schema 无预算全量注入 prompt

- **结论:待证实** —— ⚠⚠ **本条是代码级疑似,不是已证实缺陷,不得据此排期**
- **断言(来自 workflow agent 的代码阅读,未经本人亲核):** `server/orchestrator/tool_loop.py:749` 附近的 `_native_tool_schemas`,把**每个已 wire 工具的完整 schema 预加载进每次 prompt**,而编排层与 registry 中**没有任何数量预算/上限**。
- **若属实的后果:** 与"随便挂 MCP server"的产品主张直接冲突——挂多了就撑爆上下文。
- **现成解法参照:** copilot-sdk 的 `toolSearch: {defer:'auto'}`(工具搜索延迟加载)。
- **⚠ 复核要求(必做,优先于任何修复):** ① 亲自读 `tool_loop.py` 确认 `_native_tool_schemas` 的实际行为;② 确认是否真无任何上限/过滤(注意 `Tool.host_enabled` 默认 False、discovery 锁 `registered` 等既有闸门可能已实际限制了规模);③ 量一次真实 prompt 体积再判严重性。**证实前不要动代码。**

---

### ✅ 三步复核结果(2026-08-02,工程侧亲核,main=`09917c2`)

**裁决:结构性主张成立,严重性主张证伪。不排期为缺陷;deferral 思路另有价值(见末段)。**

**行号先更正**:声称的 `tool_loop.py:749` 命中不了,实际在 **`:938`**(审计怀疑的行号漂移属实)。
**行号错不等于主张错**,所以三步照做。

**① 实际行为 —— 主张的这一半成立。**
`_native_tool_schemas`(`tool_loop.py:938-953`)对 `wired` 里**每一项**都吐一份完整 schema,
**没有任何上限、过滤或预算**;`_tool_params` 的优先级是 内置硬编码 > 存储的 `input_schema` > 宽松兜底。

**② 既有闸门 —— 这一半被漏算了,而它决定严重性。**
| 路径 | 边界 | 出处 |
|---|---|---|
| **spawn** | `wired ∩ safe ∩ equipped` —— **天然有界**,取决于用户装备了什么 | `spawn_loop.py:30` |
| **host** | MCP 工具必须 `status=="wired"` **且** `host_enabled==True`,**默认 False** | `models.py:199`、`arslan.py` 的 `_arslan_tools` |

`host_enabled` 是**逐个工具的人工准入闸**。它管准入**不管数量** —— 所以"无预算"成立,
但"挂多了就撑爆"要求用户**逐个手动开启几十个**。

**③ 实测体积(真实代码 + 真实库,只读)。**
| 库 | tools | toolsets | MCP | MCP wired | **MCP wired + host_enabled** |
|---|---|---|---|---|---|
| 打包版(用户在用) | 18 | 10 | **0** | 0 | **0** |
| dev | 78 | 14 | 60 | 27 | **1** |

⇒ 研究里的「16 工具/9 toolsets」是**注册表数量**,不是进 prompt 的数量。

真实 prompt 贡献(`_native_tool_schemas` 真实输出序列化):
- 今天的 host 集合 = 7 内置 + escalate = **8 个 schema,2,563 字节 ≈ 730 token**
- 加上 dev 库里唯一那个 host_enabled 的 MCP 工具:**2,973 字节**
- 假想开启 50 个 MCP 工具:25,403 字节 ≈ 7,258 token

**⇒ 缺陷在结构上真实,在当前效果上不真实。** 不构成缺陷排期理由。

### 🔴 deferral 与 prompt 缓存直接冲突 → **规则已单独立项,见 R-025**

本轮复核最有价值的产出不属于 R-017,已按用户 2026-08-02 裁定**升级为独立设计规则 R-025**
(前缀缓存约束)——它将来还会撞上能力卡、动态组队、MCP 扩展,不该埋在某一条的脚注里。

对 R-017 的直接结论只有一句:**`toolSearch {defer:'auto'}` 不可照搬**——
它每轮换工具集,而 G1 之后 tools 位于被缓存的前缀里,逐轮变化 = 每次请求击穿整个前缀。
**理由、判据与未验项全部见 R-025,此处不复述**(规则只能有一处真源)。

**⚠ 动手前置(压在 R-017 自己头上):** R-025 的未验项——OpenAI 系是否同样把 tools
计入可缓存前缀——**必须先补测**,否则不知道这条约束适用一家还是全部。

## R-018 记忆策略接口 + 记忆质量基准(借自 qm)

- **结论:借**(本轮最高杠杆的单条借鉴)
- **想法:** 把记忆的**巩固与检索策略**抽成可插拔接口(现在是硬编码且未测量),然后**骑在已有评测机器上建一个记忆质量基准**:`replay_gate.py`(paired-holdout、`_delta`、`GateResult`、`Corpus`)+ `evaluator.py`(LLM judge)+ `synthetic_corpus.py`。
- **为什么高杠杆:** **这个市场里没有任何人公布记忆评测数**——OpenWorker、DeerFlow、OpenClaw、Manus、Sim 全都没有。它把"记忆可见可编辑"从一句主张变成一个可测量的数字,直接喂差异化支柱 #2。与 R-012(进化循环 kill-criteria)是同一战略动作的两面。
- **qm 的 `scratch-promote` 策略**与 Arslan 已有的 SkillCandidate → ReplayGate → 人工 promote 模式(`skill_forge.py`)1:1 对应——**把该模式从 skill 扩展到 fact/learning 即可**。
- **⚠ 风险(必须遵守):** 会引入**第二个检索抽象**与现有 hybrid FTS5+vector RRF 路径(`knowledge.py` `rrf_merge`/`_fts_route`/`_vector_route`)竞争。**缓解不可谈判:当前行为必须"是"新接口背后的默认策略,而不是一个兄弟系统。** 另:bench 必须用 `replay_safety.py` 的 hermetic sentinel conversation id,不能手写 id。
- **许可:** qm 为 MIT,思想无需许可;若采用代码片段需 THIRD_PARTY_NOTICES 署名。
- **⚠ 待工程侧复核:** 上述文件/函数名来自 agent 阅读,排期前需亲核。
- **规模:** L,1-2 周(接口抽取触及检索热路径;bench 主要是既有 eval 代码的组合)。

---

## R-019 github/copilot-sdk —— 拒接,借思想

- **结论:拒接**(任何形式的依赖)+ 借 3 项
- **依据:MIT 是个诱饵。** 绑定层 MIT,但每条代码路径都要**闭源、不可 fork、不可改的 Copilot CLI 二进制**,而规划循环、工具循环、文件编辑、shell 执行全在它手里。接入等于给 Arslan 装第二个**审计不了、打不了补丁、沙箱不住**的循环,一次性击穿四条硬约束:内核沙箱、fail-closed 人工确认、`promise_guard` 诚实性、**每次调用一次的 usage 记账**(它内部跑 N 轮只报一个数 → 成本层开始撒谎)。
- **且无 MCP 门:** Copilot CLI 是 MCP **客户端**不是服务端,Arslan 最宽的零代码面对不上。
- **许可:** 绑定 MIT / 运行时二进制**专有**。Apache-2.0 产品捆专有二进制 = 红线(尤其临近 go-public)。
- **借(3 项):** ① 把 `copilot-cli` 作为**诚实目录条目**加进 `seed_catalog.py` 既有的 autonomous-ai-agents 块(claude-code / codex / opencode 已按"decision §9:registered、orchestrator-only、**unwired**"处理),3 行,不 wire;② 它是 **Arslan-as-MCP-server(S4.1-C)的反向机会**——它是 MCP 客户端,意味着 Arslan 做成 server 后可直接被这个 10.2k★ 生态消费,**Arslan 供给它缺的记忆与 persona 层,而不是租它的循环**;③ tool-search deferral → 见 R-017。
- **市场:** 采纳 = 强稀释(三支柱同时受损,且比最近竞品 OpenWorker **更不 local-first、更不可审计**);作为参照与 MCP 消费方 = 温和增强。

## R-020 yc-software/qm —— 拒接,借思想

- **结论:拒接**(无门可接)+ 借 4 项(详见 R-018 为首)
- **是什么:** Y Combinator 的开源**多人协作 agent harness**,MIT,v0.1.0,三天 ~4.3k★。
- **依据:没有集成面。** 其 `@modelcontextprotocol/sdk` 是 **devDependency**,MCP 仅用于**进程内**把工具桥进 Claude Agent SDK(`mcp__qm__*`),**它不对外暴露 MCP server** → Arslan 最宽的运行时门无处可指。
- **接了会破坏什么:** 它是一整个敌对 harness——自己的 agent 循环(第二个循环)、自己的记忆库(第二个记忆)、**强制 Postgres + pg-boss(无 SQLite 路径)→ 直接违反单一数据根不变量**、Node≥24.15 ESM/TS(而 Arslan 是 Python 3.12 + 即将 Tauri 打包)。治理上**不接受代码 PR**(只收散文 ADR,YC 自行实现)、3 天大的 v0.1.0、~47 个开放 PR → 任何依赖都会变成永久私有 fork,零上游杠杆。
- **许可:** **MIT,与 Apache-2.0 干净兼容** —— 许可不是障碍,这正是"借"而非"拒"的原因;采用片段需 THIRD_PARTY_NOTICES 署名。
- **四项借鉴:** ① **R-018**(记忆策略接口 + 基准,最高价值);② **姿态门控的本地分类器**放进 `untrusted.py` 的 `wrap_external` —— Arslan 目前**框定**外部内容但从不**筛查**,而该 chokepoint 已经是单一且强制的(`MCPProxyExecutor` 故意不带 `external:False`,使所有 MCP/web 结果都汇入);③ 把 `orchestrator_shell_enabled` + `shell_confirm_policy` + `ARSLAN_ALLOW_UNSANDBOXED_PY` 逃生阀**形式化成一个单调 posture 且显式命名"任何 posture 都抬不动的底线层"**(`command_policy.ALLOWED_BINARIES` + argv 硬拒扫描 + sandbox-required)——这是"把已在执行的不变量变成可声明的安全故事";④ quickstart SKILL.md seed(零代码,顺手交付 S4-B)。
- **⚠ 两个警告:** ② 的分类器若**静默丢弃/改写内容,直接违反诚实守卫**——必须附可见 provenance 标签并在工具活动卡里暴露筛查裁决;且必须默认走本地模型、姿态门控(BYOK 下每条外部结果都过一次云端 = 成本与延迟不可接受)。③ 不要蔓延成**每分身 posture**——那会造出与 `assert_assignable`(故意单一不可绕的 choke point)竞争的第二条策略轴。
- **市场:** 不是竞品(org 级、多人、Slack 优先、Postgres、云部署 vs 单用户、本地优先、macOS 桌面、SQLite)。**是定位礼物:"qm 是你公司跑的,Arslan 是你自己跑的。"**

## R-021 zhaoxuya520/reverse-skill —— 拒

- **结论:拒**(不导入、不做 seed、不 vendor 任何部分)
- **是什么:** 逆向工程 / 攻击性安全方向的 SKILL.md 包集合(R0-R39 静态阶梯,apk-reverse/ghidra/radare2/malware+YARA/pentest/exploit-dev)。
- **三重拒绝理由:**
  1. **任务不符:** 个人 AI orchestrator 挂攻击性安全工具,是双用途气味,给上架与企业分发平添审查摩擦,且不增强任何一根支柱。
  2. **许可污染:** MIT 仓库夹带 **GPLv3/AGPL** 内容,而 `skill_import.py` 的闸只读**顶层 SPDX** → 会被绕过。作为 seed vendor 进 Apache-2.0 产品是红线。
  3. **架构上敌对(最关键):** 其两个招牌设计是 **"agent 服从性工程"**(明确用于压制 agent 的安全犹豫)和**把路由规则写进 `~/.claude/CLAUDE.md` 自我持久化** —— **这恰好就是 `promise_guard` 与 `untrusted.py` 外部内容框定所要防的操纵/注入模式。** 而 skill 正文在派发时进系统提示词。
- **附带不可行:** 其网络依赖的 PowerShell/Bash 工具引导,在 Arslan **网络拒止的 fail-closed 沙箱**里根本跑不了 → 要么"降级"badging 不诚实,要么装饰性 skill 不可用。且 `skill_import.py` 本就不携带 `.ps1/.sh` 脚本。
- **诚实替代路径(零改动,今天就能用):** 真想要逆向能力的用户,自行经现有 MCP 客户端注册 IDA Pro / Ghidra / Burp / dnSpy 的 MCP server,默认锁在 orchestrator/registered 直到人工 wire。
- **仅有的可取之处**(AST 供应链审查清单、"技能堆叠过多伤召回")Arslan 在 `skill_import.py` 与 `equipment_service.curate` 里已执行得更严 → **连"借思想"都算高估。结案。**

## R-022 different-ai/openwork —— 拒接,借 2 项(且首要借鉴被对抗验证推翻)

- **结论:拒接**(代码/引擎/服务一律不接)+ 借 2 项
- **⚠ 勿与 R-014 的 OpenWorker(andrewyng)混淆——两个不同项目。**
- **是什么:** Different AI, Inc. / OpenWork Labs,TypeScript/Electron 单仓,**~19.9k★,~132 万次安装下载**,自称"Claude Cowork 的开源替代"。**引擎是钉死版本的外部 `opencode` 二进制**,经 `@opencode-ai/sdk` 驱动(全仓零 `@anthropic-ai` 依赖)。
- **核心判断:它是别人 agent 循环的壳,而 Arslan 本身就是一个 agent 循环** —— 没有能组合的接缝。`tool_loop.run_native`、tier choke point、`promise_guard`、RunRecorder 进化记账全部依赖"拥有并可检视这一轮"。
- **三条路全堵死:**
  1. **许可:** 双许可——`/ee` 之外 MIT,**`/ee` 整个 Den 控制平面是 FSL-1.1-MIT(source-available,带竞业限制,而该条款描述的正是 Arslan 这类产品)**。Apache-2.0 不能捆。
  2. **账号:** 唯一有意思的能力面(托管 meta-MCP,`api.openworklabs.com/mcp/agent`,浏览器 OAuth + 组织选择)要 openworklabs.com 账号 → 违反 local-first。
  3. **二进制:** 接引擎须把 `opencode` 加进 `command_policy.ALLOWED_BINARIES`(现为 `{git, gh, ffmpeg, pandoc}`),而 2026-07-03 orchestrator-shell spec 的**非目标里白纸黑字禁止该类二进制**;`seed_catalog.py` 里 `opencode` 已是 registered/unwired 的既定决策。
- **✅ 可借的 2 项:**
  - **降级状态语义** —— 能力不可用时返回 `needs_connection` / `needs_install` + 可操作解锁提示,而非空结果/灰掉。Arslan 已算出底层布尔值(`service.py` 的 skill_is_assignable / toolset 有 safe+wired 工具;`assert_assignable` 已拒绝非功能项),今天把这信息**当作拒绝丢掉了**。解锁动作(`propose_connect_mcp` 卡片)现成。**⚠ 硬约束:解锁提示只能由仓内静态已审 catalog 数据构造,绝不能用 discovery 时抓来的 `Tool.description`——否则成为第三方文本进 prompt 的注入路径。**
  - **脱敏启动快照** —— 给每个 stdio MCP 子进程记一份脱敏的 command/args/cwd/env(`TOKEN|PASSWORD|AUTH|SECRET|KEY|CREDENTIAL` 正则),放在 `server/mcp/session.py`。**⚠ 必须在采集时脱敏而非渲染时**,否则在 data_dir 下造出用户密钥的第二份未加密副本,违反"密钥静态加密、读取时掩码"。这条确实来自 MIT 那半边(`apps/server/src/managed-opencode.ts`)。
- **❌ 被对抗验证双面推翻的首要借鉴(记录在案,勿再提议):** 分析 agent 曾建议把 S4.1-C 的 server 侧收成"两工具能力轨"(`search_capabilities` + `execute_capability`)。**两个验证器独立推翻,理由成立:**
  1. **前提是假的** —— skill 在 Arslan 里**不是 tool**(`dispatcher.py:129` 把 SKILL.md 正文注入系统提示词),spawn 早已是"一个工具带 id 参数";内置面共 16 工具 / 9 toolset,C 的锁定读范围就是"列 spawn、列 skill、查 brain"。**本来就是常数,不存在要解决的爆炸。**
  2. **会推翻已锁决策** —— 外部客户端(Claude Desktop/Cursor)按**工具名**授权,合并后用户无法"允许读、拒绝派发",一次批准等于批准背后全部能力,**包括进化循环在批准之后新长出来的能力**;且无法标 `readOnlyHint`。这正是 S4 计划"dispatch_spawn 默认关、允许列表、审计"要防的。
  3. **许可陷阱** —— 那条轨的代码**只存在于 `ee/apps/den-api/src/mcp/` 即 FSL 那半边**。写成"MIT 先例"是**假的出处声明**,且"去参考实现"等于指挥实现者打开唯一不能打开的文件。
  - **正确替代:** C 按原计划出小而固定的具名读工具集;若能力宇宙确实增长,用**一个具名读工具**(如 `list_capabilities`)把目录**作为数据**返回(这本就是 Arslan `safe_menu()` 的习惯用法);**写侧永不藏进通用 executor**。
- **另两条 C 的 spec 必须预算的成本(验证过程附带发现,⚠ 待亲核):** ① **confirm 通道** —— `tool_loop.py:301-316` 的 `run_command` 在 `confirm_command` 回调为 None 时**拒绝执行**(安全默认),而该回调是 WS/UI 绑定的;stdio 上没有这个通道,特权能力要么 fail closed(写侧变惰性),要么需要新的 confirm 传输(MCP elicitation)。② **服务抽取** —— `server/api/brain.py` 的 tree/graph/entry 处理器是**内联裸 SQL**,不是可调用 service,"复用已有读服务"只对 `notes.py` 成立;且 `require_auth` 是 HTTP 层的,stdio server 继承不到。
- **市场:** 它的记忆是自述 v0 显式词法 + 人工确认写入(明确弱于 Arslan 的时态第二大脑);无自进化 persona 团队;隔离故事自标 "Partial"。**三支柱在一个 19.9k★ 竞品面前完好无损。** 但它已把"一个 MCP URL 带着整套配置进 Claude Code/Cursor"变成品类预期——而它是**账号托管 + FSL**的实现,**Arslan 能纯本地、无账号做同一件事,这是它因商业模式结构性做不到的楔子** → S4.1-C 更紧迫。

## R-023 Auto-Company:多分身组队 + 人类方向盘字段

- **结论:借 2 个想法**(不接代码)
- **是什么:** MaxMiksa(CMU,Zheyuan Kong),**2.2k★,MIT**。14 个专家 persona 模拟一家公司 24/7 自主运转,每轮**动态组队 2-5 人**,`memories/consensus.md` 作为轮次间传递的"接力棒",人类通过编辑其中 **"Next Action" 字段**掌舵。引擎是 **Claude Code 或 Codex CLI**,核心循环 Bash,以 daemon 跑(launchd/systemd)。自称实验性、不保证稳定。
- **借 1 —— 动态组队:** Arslan 现在路由到**单个** spawn。"按当前优先级选 2-5 个分身协同"是 persona 团队叙事的自然下一步,**也是目前的真空白——卖的是"团队",实际跑的是"轮流单干"。**
- **借 2 —— 人类方向盘字段:** "改一个字段,下一轮 agent 立刻读到"比审批弹窗更适合长周期自主。与 R-014 的"无人值守请求停进 inbox"同族,**建议一起设计**(Arslan 侧对应 evolution inbox + scheduled tasks)。
- **不借:** ① 又是租引擎(Claude Code/Codex CLI,本轮第四个同款模式);② Bash 核心循环与 Python 栈不可组合;③ **persona 直接用在世真人命名**(贝索斯、DHH、Paul Graham、Seth Godin…)——产品里这么做有身份/声誉气味,Arslan 的分身是用户自养角色,不学。
- **定位验证(本条最大价值):** "AI persona 团队"这个概念在野外最像的实现,只有 2.2k★、Bash + 租 CLI + 自称实验性,**没有真后端、没有进化循环、没有可见记忆。没有人把它认真做出来过——赌注那块地目前还空着。**
- **另记:** 它的 24/7 本地 daemon 是"Manus 云端自主"的本地答案形态,与 R-013 相关。

## R-024 竞品雷达汇总

- **结论:参考**(定位用,无集成动作)
- **四个极(定位坐标系):**
  | 项目 | 极 | 规模 | 对 Arslan |
  |---|---|---|---|
  | **OpenWorker**(andrewyng) | 正面同格:local-first 桌面交付成品 | 4.4k★(发布 2 天) | **最近的正面竞品**,见 R-014 |
  | **OpenClaw** | 渠道覆盖(接管你已有的 IM/语音) | 346k★ | 引力中心;安全是公开软肋 → 别拼渠道,打"默认安全"对比 |
  | **DeerFlow** | 开发者 harness(K8s/Postgres) | 77.3k★ | 管道已成 table-stakes,见 R-010 |
  | **Manus** | 云端黑箱代劳(信用点计费) | 商业闭源 | 最好的磨刀石,见下 |
  | **Sim** | 可视化工作流编排(AI 版 n8n) | 29.2k★ | 反面参照:Sim 让你**画 DAG**,Arslan 让你**说话养团队**;"没有图要画"对非技术用户是差异化 |
- **Manus(蝴蝶效应/Monica):** 云端自主 agent,任务跑在**它的云沙箱 VM**,24/7 自跑,信用点计费($20/4000 点、$40/8000 点、Pro ~$199/月;复杂任务 500-900 点/次);GAIA 自报 L1 86.5% / L2 70.1% / L3 57.7%。**Arslan 的真优势:** ① **成本模型碾压**(BYOK 按 API 原价直付,无每任务计量、无加价);② 本地隐私/数据主权;③ 开源可审查无锁定;④ 诚实 + 可见记忆。**Manus 真赢的:** 现在就能用且已被证明、零门槛、云端长时自主(合上笔记本继续跑)、资源速度。**诚实结论:Arslan 的优势目前全是"潜在"的——因为还没做到能真正服务哪怕"注重掌控+省钱+隐私"这个细分人群(macOS-only、开发者级安装、进化未兑现)。活路不是变成更好的自主 agent,是把"你拥有、你掌控、你看得懂"做到那个人群真的能用。**
- **OpenSpace(HKUDS 港大,6.9k★,MIT,v2 2026-07):** "质量优先的 Skill Hub",插进别的 harness 当**进化/质量层**;四层——质量信号(selected/applied/completed/fell-back)、受控进化(FIX/DERIVED/CAPTURED + 版本 DAG)、本地优先 hub、证据采集。**公布 Terminal-Bench 2.1 上 65.2% → 78.7% 的进化增益。** 双面含义见 R-012。**可抄的两个设计:** 质量信号四分类(比"跑完没报错"细)、进化模式三分类(比"优化一轮"清楚)。**区别:** 它进化 **skill**(可移植、更易测),Arslan 进化 **persona**(更丰富、更难出干净数)。**它甚至可能互补而非对手,但哲学上重叠,持续盯(出自 LightRAG 实验室,会持续出货)。**
- **PentestGPT(GreyDGL,14.6k★,MIT,USENIX Security 2024):** 自主渗透测试框架,多阶段流水线(CTF:侦察→利用→走查;Pentest:资产发现→漏洞识别→报告),agentic 模式挂 Claude Code/Codex。**与 Arslan 是斜的**,但两个观察:① 它是"**一个 spawn 做到极致**"的样板(垂直域工作流固化成多阶段流水线 + 领域工具 + 报告产出);② 它挂成熟 coding agent 当执行底座 —— **执行底座正在商品化**,是本轮反复出现的模式(见 R-019/R-022/R-023)。安全域高危,真做需授权/沙箱重闸。
- **UI-TARS / Agent-TARS(字节,38.1k★):** 见 R-009。其 Remote Operator(免配置点击连接远端机器)与 R-007 的 iOS companion 设想同构,值得抄作业。
- **Mandarancio/OpenGOO —— 与 Arslan 无关。** 经核实是 **World of Goo(粘粘世界)的开源克隆游戏**:Qt5 + C++,GPLv3,153★,pre-alpha,README 自陈"还不能玩"。**未找到任何与 Arslan 的接点,不强行制造关联。** 登记于此仅为留痕(疑似链接贴错)。

---

## 附:本轮确立的架构事实(供后续评估复用)

> 来自一次针对 `/home/user/arslan` 的接入面测绘。**⚠ 全部待工程侧复核**,但对判断第三方项目可行性很有用。

1. **没有插件加载器。** 无 entry_points/setuptools 插件机制,无第三方 Python 动态导入。**除 MCP 与 SKILL.md 外,每个能力都经由仓内硬编码的 dict 进入。**
2. **MCP 是唯一的运行时可扩展执行面** —— 这也是 R-016(零 OAuth)后果严重的原因。
3. **外部 agent(非 model)当前完全无法作为执行后端插入。** `LLMAdapter` 的契约是 `chat(system, user, history, tools) -> LLMResponse`,**单轮补全**;agent 循环(`tool_loop.run_native`)是 Arslan 自己的,不可替换,**没有"把这一轮委派给外部 agent"的接缝**。最接近的东西是**已编目但刻意未接线**的 `claude-code` / `codex` / `opencode`(`seed_catalog.py`,tier=orchestrator、status=registered,decision §9"透明目录条目")—— **项目已明确拒绝 CLI-agent 委派。本轮四个项目的评估结论与该既定决策一致。**
4. **零代码接入面(最宽的门,按成本排序):** ① MCP 任意 server 运行时注册(UI 或 `POST /api/v1/mcp/servers`);② MCP preset catalog(`server/mcp/catalog.py` 加一条 dict ≈ 10 行纯数据,同时点亮 Settings 推荐列表 + 对话式"连一下 GitHub",前端零改动);③ SKILL.md(shipped seeds 或经 `skill_import.py` 的 GitHub 导入,后者有 SPDX 许可白名单硬闸);④ 说 OpenAI `/chat/completions` 的 LLM provider(presets 一条 dict 或现成的 custom base_url)。
5. **MCP server 侧(S4.1-C)当前在代码中不存在。** `mcp>=1.0` 是依赖但**仅作客户端使用**;近期那批 commit 发的是对话式 MCP **客户端**接入。**server 侧是 greenfield**:需要新模块、一个 auth 模型(`require_auth` 仅 Bearer/HTTP 层)、以及 `dispatch_spawn` 的 tier 决策。
6. **MCP 客户端的三道默认关闭闸(设计正确,勿动):** ① discovery 出来的一切锁死 tier=orchestrator/status=registered;② `wire_tool` 是**逐工具**的人工动作(`suggest_tier` 仅 UI 提示,从不强制);③ `Tool.host_enabled` 默认 False。外部输出被当作不可信,经 `wrap_external` 包进 EXTERNAL_WEB_CONTENT 数据帧。

---

## R-025 🔴 前缀缓存约束 —— 任何"按轮变更提示前缀"的设计都要先过这一关

- **结论:决策**(**持久设计规则,不是 R-017 的脚注**——用户 2026-08-02 裁定单独立项)
- **状态:** 登记(规则即时生效,无需排期)
- **⚠ 复核:** ✅ 工程侧亲核(2026-08-02,main=`09917c2`)

### 规则

> **提示前缀里的东西,一旦按轮变化,就不再是"多花几个 token",而是"每次请求丢掉整个缓存前缀"。
> 任何让前缀内容随轮次/上下文/选择而变的设计,必须先算这笔账,再谈它省了多少 token。**

### 为什么现在成立(G1 之后才成立)

- Anthropic 的渲染序是 **tools → system → messages**,缓存断点打在 **system 前缀**;
- **G1(2026-08-01,`bebb87a`)之前 Anthropic 根本不发 `tools`**,所以这条约束当时够不着工具;
- G1 之后 **tools 块进入被缓存的前缀**,这条约束从此对**工具集**生效。

⇒ 两个方向相反的后果,都要记住:
1. **大前缀比看起来便宜**:一个大 tools 块每个缓存窗口只付一次,不是每次请求都付。
2. **动态前缀极贵**:每轮换一批工具 ⇒ tools 数组逐轮不同 ⇒ **每次请求击穿整个前缀**。

### 已知会撞上它的设计(登记时可预见的)

| 设计 | 怎么撞 |
|---|---|
| **R-017 工具 schema deferral**(`toolSearch {defer:'auto'}`) | 每轮按需选工具子集 = 逐轮不同的 tools 数组。**这就是 R-017 不该照搬 copilot-sdk 的原因**——那个形状是给**没有前缀缓存**的架构设计的 |
| **能力卡 / Capability Library 诚实化** | 若把"当前可用能力"按会话状态注入前缀 |
| **动态组队(R-023)** | 按任务选 2-5 个分身 ⇒ 每个分身的工具/persona 若进前缀,组队变化即前缀变化 |
| **MCP 扩展**(R-001、graphify preset、任何新 preset) | 新增工具本身没问题(前缀变一次);**按条件启用/禁用**才是问题 |

### 判据(拿来直接用)

- **兼容**:静态分层——前缀内容由**慢变量**决定(用户装备了什么、开启了哪些 host 工具)。变一次,缓存重建一次,之后稳定。
- **不兼容**:前缀内容由**快变量**决定(本轮问题、检索结果、模型的选择)。
- **已有的护栏**:G1 加的 `order_by(Tool.key)`(`arslan.py` `_arslan_tools`)+ `tests/llm/test_tool_transport.py::test_the_serialised_tools_are_byte_identical_across_calls`。
  **任何新的前缀内容都要有同形状的稳定性断言**,否则它是"看起来稳定"。

### 参照数字

prompt-cache 轮把命中率从 **80.5% → 98.5%**。这是一项**已经兑现的资产**;
动态前缀方案在提案里必须**先扣掉这笔损失再算收益**,不能只报自己省的 token。

### ⚠ 未验

**OpenAI 系(含 DeepSeek——用户日主力)是否同样把 `tools` 计入可缓存前缀,本轮未核。**
只核了 Anthropic 的渲染序。这决定本规则的适用面是"一家"还是"全部",
**在动 R-017 或任何前缀设计之前必须先补这一测。**
