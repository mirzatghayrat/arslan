# Round 1(2026-07-17):趋势雷达 × Arslan 问题挖掘

> 本轮范围:承接 claude.ai 调研会话(flint-chart + 时态知识图谱)的三条登记,补上代码层坐实 + 四个互补趋势面(agent 可移植性、SKILL.md 生态、MCP 安全、竞品格局)。所有登记项已入 `BACKLOG.md`(R-001~R-006)。

## 一、代码层问题挖掘(本轮坐实/新挖)

| # | 问题 | 严重度 | 证据 | 去向 |
|---|------|--------|------|------|
| 1 | 用户事实库只增不减、全量注入每个 prompt(5 个注入点),读路径忽略全部元数据 | 中(审计既有项,本轮坐实) | `memory.py:310`、`models.py:129`、注入点 router/arslan/dispatcher/spawn_drafter/replay_run | R-002 |
| 2 | `sensitive` 标志零语义:敏感事实照样进分身派发和**评测重放**上下文 | 中(新挖) | `models.py:137` 有字段,`facts_text()` 不过滤,`replay_run.py:38` 进 eval ambient | R-004 |
| 3 | upflow 线性增长机制(每分身每会话 +1 条,仅 containment 去重) | 低-中(是 #1 的增长引擎) | `distill_service.py:53-96` | 并入 R-002 |

**最有意思的结构性发现:** 合并式记忆(每会话 LLM 把已有+新信号合并成 ≤8 条)**已经存在于代码库**——但只用于分身级 `Spawn.memory_facts`(`distill_service.py:32`),Arslan 级 `UserFact` 却是 append-only。修 R-002 时有现成的内部先例可抄。

## 二、趋势雷达(带来源)

### 1. Agent 记忆:mem0 的反向教训(修正 P3 假设)

mem0 的架构演进值得注意:早期版本在写时跑两遍 LLM(抽取 + 对既有记忆做 ADD/UPDATE/DELETE 仲裁),**当前版本已退回 ADD-only 单遍抽取 + 检索时排序**——"我搬到了 SF"不再写时覆盖"我住在 NYC",两条都留,靠读路径分辨哪条现在相关。
**对 Arslan 的含义:** S4 计划 P3 里"memory write-time update (mem0-style)"这行备注的假设已过时。R-002 的正确姿势:写时只做轻量 supersede 标记(不堆 LLM 调用),复杂分辨放读路径。这与 Graphiti/Zep 的时态字段思路(valid_from/superseded_by)兼容——借字段概念,不借写时仲裁,也不借图数据库。
来源:[mem0 docs — Update Memory](https://docs.mem0.ai/core-concepts/memory-operations/update)、[Inside Mem0, Supermemory, and Letta](https://kenhuangus.substack.com/p/how-ai-agents-actually-remember-inside)、[Mem0 论文](https://arxiv.org/html/2504.19413v1)、[2026 agent memory 系统对比](https://blog.devgenius.io/ai-agent-memory-systems-in-2026-mem0-zep-hindsight-memvid-and-everything-in-between-compared-96e35b818da8)

### 2. SKILL.md 已是行业标准,短板是安全与策展(Arslan 的顺风)

Anthropic 2025-12-18 将 Agent Skills 开放为标准(agentskills.io);2026-03 已有 **32 个工具**(VS Code、Codex、Gemini CLI、Junie、Kiro、Goose…)读同一 SKILL.md 结构;社区目录百万级(SkillsMP ~190 万条、skills.sh ~9 万条)。生态公认的短板:**分发已解决,质量与安全没有**——恶意 marketplace skill(ClawHub 事件)是 2026 年标志性事故之一。
**对 Arslan 的含义:** 见 R-006——原生 SKILL.md 是 launch 叙事资产;`skill_import.py` 的安全闸(license gate/caps/traversal guard/sandbox)恰好卡在生态最痛点上。
来源:[The New Stack — Agent Skills](https://thenewstack.io/agent-skills-anthropics-next-bid-to-define-ai-standards/)、[agentskills.io](https://agentskills.io/home)、[2026 生态报告](https://agentman.ai/blog/agent-skills-ecosystem-report-2026)、[32 工具互操作指南](https://www.paperclipped.de/en/blog/agent-skills-open-standard-interoperability/)

### 3. MCP:体量爆炸 + 安全数据支撑 S4.1-C 的保守默认

SDK 月下载 97M(2026-03),公共 server 超 1 万;但对 1800+ 已部署 MCP server 的系统分析发现 **>30% 至少有一个可利用漏洞**;另一份对 2614 个实现的分析:82% 的文件操作易受路径穿越、34% 易受命令注入。2026 版 MCP spec 引入 **incremental scope consent**(按操作申请最小权限)。
**对 Arslan 的含义:** S4.1-C 的锁定决策(read tools ON、`dispatch_spawn` OFF/opt-in、`query_brain` 信任边界反转要审计)与行业教训完全同向;C 的 spec 风险节可直接引用这些数据。跟进项:2026 spec 的 scope-consent 机制是否值得在 C 的 v2 采纳。
来源:[Practical DevSecOps — MCP 漏洞](https://www.practical-devsecops.com/mcp-security-vulnerabilities/)、[NSA/CISA MCP 安全指引 (PDF)](https://media.defense.gov/2026/Jun/02/2003943289/-1/-1/0/CSI_MCP_SECURITY.PDF)、[OX Security — MCP 供应链通告](https://www.ox.security/blog/mcp-supply-chain-advisory-rce-vulnerabilities-across-the-ai-ecosystem/)、[Aptible — MCP prompt injection](https://www.aptible.com/mcp-security/mcp-prompt-injection)

### 4. Agent 可移植性:.af 是唯一有名字的标准(D 的必答题)

Letta 的 Agent File (.af, 2025-04, ~1k★):JSON 人类可读,打包 system prompt + 可编辑记忆 + 工具配置 + LLM settings。生态尚早但方向明确。详见 R-005。
来源:[letta-ai/agent-file](https://github.com/letta-ai/agent-file)、[Letta blog — Agent File](https://www.letta.com/blog/agent-file)、[Letta docs](https://docs.letta.com/guides/core-concepts/agent-file)

### 5. 竞品格局:OpenClaw 是"个人 AI 助手"的引力中心,安全是它的公开软肋

OpenClaw(Peter Steinberger,前身 Clawd)2026-06 已 **346k★**、1200+ 贡献者——local-first 个人 AI 助手赛道的绝对引力中心,形态是"接管你已有的渠道"(WhatsApp/Telegram/语音/Canvas),BYOK 多模型。但其安全面是**公开的软肋**(社区熟知的低防护率数据、poisoned config、ClawHub 恶意 skill 事故;NSA/CISA 指引和多家安全厂商都拿它当案例)。
**对 Arslan 的定位含义:**
- **不要正面拼渠道覆盖**——那是 OpenClaw 的主场(也是它的攻击面来源)。Arslan 的差异化三支柱(kernel sandbox 默认安全 / 诚实守卫 / 可见可编辑的记忆+自进化团队)恰好都是 OpenClaw 的弱面或空白。
- go-public 的 README/叙事应显式做这个对比(不点名也行):"个人 agent 的能力大家都有,**默认安全 + 诚实 + 记忆可见**是我们不同的地方"。
- 渠道面(如 Telegram 桥)若未来要做,走 MCP preset 路线(用户自选),不进核心。
- 多 agent 编排赛道(DeerFlow 2026-02 登顶 trending、Omnigent、Agent Orchestrator)全部聚焦**编码 agent 车队**;Arslan 的"非编码个人 persona 团队 + 两层进化循环"位置仍然独特。
来源:[openclaw/openclaw](https://github.com/openclaw/openclaw)、[346k★ 全景指南](https://medium.com/data-science-collective/355k-github-stars-in-5-months-17-defense-rate-the-complete-honest-guide-to-openclaw-28d2f59598e1)、[NVIDIA blog — OpenClaw agents](https://blogs.nvidia.com/blog/what-openclaw-agents-mean-for-every-organization/)、[freeCodeCamp — 构建并加固 OpenClaw](https://www.freecodecamp.org/news/how-to-build-and-secure-a-personal-ai-agent-with-openclaw/)、[2026 agent 安全风险](https://blog.cyberdesserts.com/ai-agent-security-risks/)

## 三、对 S4 路线图的净影响

- **不动主线。** S4.1-C 的所有锁定决策被本轮外部证据加强,无一被推翻。
- **P3 描述需一行更新**(R-002 消化时顺带):"mem0-style write-time update"→"轻量 supersede 标记 + 读路径分辨"。
- **G(go-public)获得两个叙事弹药:** SKILL.md 标准兼容(R-006)、与 OpenClaw 的安全对比定位(本报告 §2.5)。
- **D(.af)获得一个前置必答题:** Letta .af 读兼容与否(R-005)。

## 四、下一轮候选(不承诺,供选)

1. 深读 agentskills.io 正式 spec ↔ `skill_import.py`/seeds 的逐条符合度(R-006 的执行前置)。
2. flint-mcp 发行方式实测(npx 包名/env/transport),把 R-001 变成可直接落地的 catalog 条目。
3. OpenClaw 的安全事故清单深读 → 反向核对 Arslan 的 SECURITY.md 威胁模型覆盖度(给 G 的 runbook 供料)。
4. 竞品第二梯队:Letta 本体、Cherry Studio、Open WebUI 的"persona 团队/记忆可见"功能对照。
