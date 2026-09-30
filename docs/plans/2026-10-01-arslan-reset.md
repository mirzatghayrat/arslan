# Arslan 重整方案（2026-10-01）：能力先行，界面做减法

调研对象：Claude（2026-09-16 起 Cowork/Design 并入主界面）、OpenAI Codex / Dots（2026-09-29）、
Grok Bot（2026-08 beta，9 月加语音）、Meta Muse（2026-09-08）、Hermes Agent（NousResearch，MIT，
★25 万，2026-09-24 v0.21.5，本机装有 08-03 版）、GitHub 开源（goose、openai-agents、Langfuse、Opik、
promptfoo、inspect_ai）。Arslan 部分全部对照代码核实。

## 一、为什么现在 Arslan 不靠谱（代码里的根因，不是模型不行）

| 你看到的 | 根因 | 位置 |
| --- | --- | --- |
| 「把今天的待办加进提醒事项」→ 回一句英文「没有预设」，追问也一样 | 每条消息先过一个「路由器」模型分类（answer/route/suggest_create/…/suggest_connect_mcp）。它把这句判成「要连接 MCP」，直接回写死的英文，**带工具的 Arslan 根本没收到这条消息** | `server/orchestrator/router.py`、`server/orchestrator/arslan.py:760-772` |
| LinkedIn 任务：抓到 34 个岗位却写不出文件 | 没设工作区时，写文件工具根本不注册；默认就是没设 | `server/registry/file_tools.py:53-61`，`settings_service.workspace_dir` |
| 「run_command 只允许 git/gh/ffmpeg/pandoc」 | 命令白名单，python/node/sh/curl 全禁 | `server/services/command_policy.py:26` |
| 「Arslan 浏览器未安装」 | 浏览器要用户去 设置→高级 手动装 | `server/services/managed_browser.py` |
| 路由器提示词说 Arslan 只有 web_search/web_extract/render_chart | 专家时代的自我描述，早已过时 | `router.py` `_SYSTEM` |

结论：**关卡设在「给不给工具」这一层**，所以模型再聪明也没手。头部产品的关卡设在「动作要不要确认」这一层。

## 二、头部产品的共识做法（我们照抄这个方向）

- **一个 agent 循环 + 工具**，由它自己决定怎么做；没有前置路由器（Claude、Codex、Hermes、Dots）。
- **读和研究自动做；对外或破坏性的动作要确认**（发消息、删除、付款、发帖）——Dots、Muse。
- **终端默认开放，危险命令才问**：危险模式识别→询问；可「总是允许」并记住；可选「智能批准」让小模型放行低风险命令；另有一层极端命令永远禁止的底线——Hermes `tools/approval.py`。
- **密码永不进模型上下文**：用户自己在 agent 的浏览器里登录，或走密码管理器（Dots、Muse、Operator）。
- **每个任务有完整活动记录**，可以回看、可以撤销规则（Dots「Activity View」、Muse audit trail）。
- **Skill = 文件夹里的 SKILL.md**（agentskills.io 开放标准）：写明需要什么命令行工具、什么时候用/不用、可以直接执行的命令；背后必须有真工具。Hermes 的「提醒事项」skill 就是 `remindctl` 的用法说明 + 终端工具。
- **记忆要简单**：Hermes 只有两个有上限的 md 文件（关于你 / 它自己的笔记），会话开始注入，外加「搜过去的对话」。Dots 也是「浓缩后的笔记」而不是全文。
- **信息架构**（Hermes 桌面端 DESIGN.md）：对话是主页；技能、产出物是常驻页；设置、定时任务是浮层；预览/文件/审查/终端是挂在当前任务上的工作面板。
- **诊断/评测**：给用户看的是任务活动记录和用量；评测（promptfoo、inspect_ai）放在开发 CI 里，不给用户看。Langfuse/Opik 要自建数据库，对单机个人 agent 太重。

## 三、改什么（按优先级）

### P0 能力解锁（0.1.48，这一轮最重要）
1. **删掉前置路由器**：每条消息直接进带工具的 Arslan 循环。「记住的事实」改由循环里的 `remember` 工具做（已有）。
2. **默认工作区** `~/Arslan`（首次启动自动建）：在里面读写不问；工作区外写入要确认。
3. **终端工具取代 run_command 白名单**：任意命令都能跑；危险模式（删除、sudo、改系统、上传、curl|sh 等）弹确认；卡片上有「总是允许这类命令」；极端命令永远禁止；后台作业里同样规则。
4. **浏览器默认就绪**：首次需要时自动装，不再让用户去高级设置里装。
5. **自我描述改成实话**：系统提示词列出真实可用的工具和 skill。

### P1 专家整体下线 + 界面做减法（0.1.48 同轮）
- 后端：路由器、专家调度/staffing、进化循环、按专家蒸馏、专家直聊路由全部删除；数据表保留不删数据。
- **侧栏**：新对话 / 收件箱 / 技能（原 Capabilities）/ 记忆 / 项目；底部只留设置（「连接与权限」并进设置和技能页）。对话列表照旧。
- **右侧栏**：从「专家流水线 / 邀请专家 / 等级进度 / 评测胶囊」改为**当前任务面板**：进度与步骤、产出的文件（可打开/在 Finder 显示）、用到的来源、待批准的动作、浏览器实时画面。
- **设置清理**：删 自动进化 + 最大派发、专家模式（spawn_mode）、路由器模型槽、综合（synthesis）模型槽、朗读（read out loud）、诊断入口；Automation 只剩真正会花钱的（整理、来源复核、主动性诊断上限、周期清单）。
- **连接页两块占位卡片删掉**（App Store Connect、本地图像生成：接口能力全是 false）。
- **诊断 / 评测页 → 活动页**：每个任务的时间线（工具调用、文件、确认、花费）+ 用量；评测留在 CI。

### P2 技能库重做（0.1.49）
- 技能页按 agentskills.io 标准展示：名称、一句话用途、**需要的工具是否就绪**（缺什么一键装）、来源与许可证。
- 首批内置（许可证已回源核）：Hermes MIT 的 苹果 提醒事项 / 备忘录 / iMessage / 查找、X（xurl）、Google Workspace、带引用研究、arXiv、博客订阅；Anthropic 金融 Apache-2.0 的 竞品分析 / 行业概览 / 可比公司 / DCF / 财报分析。
- **不能打包**：Anthropic 的 docx/pdf/pptx/xlsx（保留所有权利，Hermes 版也是改编自它）。文档输出用开源库自写。
- 每个技能上线前必须过一件真任务。

### P3 账号 + 盯梢升级（0.1.50）
- 「登录某个网站」：在 Arslan 自己的浏览器窗口里由你亲自登录，会话保留（`agent_browser.py` 已用持久化配置目录），Arslan 不碰密码；列表可一键登出。
- 盯梢可以走已登录的浏览器（只读）；新增 RSS、邮件、日历、GitHub 通知。
- key 存进 macOS 钥匙串。

### P4 记忆（0.1.50 前后，需要单独一轮）
- 对照 Hermes / Dots：主体改为「关于你」和「Arslan 的笔记」两份可直接编辑的文本 + 搜过去的对话。
- 现有第二大脑（图谱、提案箱、时间轴）先收进「高级视图」，看使用数据再决定去留。

### 语音
- 删「朗读」开关；保留并强化对话模式（你体验过的 Grok Bot 那种）。实时语音另开一轮单独做。

## 四、要你拍板的一件事

**执行内核要不要直接换成 Hermes？** 它 MIT、Python、25 万 star、每周发版，终端/浏览器/电脑操控/记忆/技能/定时/MCP/审批全都有，而且能导入 OpenClaw 配置。
- 换：Arslan 变成「Mac 驾驶舱 + Hermes 引擎」，能力一步到位，我们专注 Mac 体验、收件箱、语音、安全默认值；代价是一次大迁移，以及跟随上游节奏。
- 不换：按上面 P0–P4 在现有内核上解锁，风险小、节奏可控。
- 我的建议：**先按 P0/P1 做 0.1.48**（这些不管换不换都要做），同时用一个下午做对比验证：同一批 5 件真实任务（提醒事项、LinkedIn 岗位清单存文件、查财报出表格、盯一个需要登录的页面、整理下载文件夹）分别给 Arslan 0.1.48 和 Hermes 跑，看谁完成得好，再决定。

## 附：内核候选（2026-10-01 GitHub 实查；许可证回源核）

| 项目 | ★ | 许可 | 语言 | 定位 | 对 Arslan |
| --- | --- | --- | --- | --- | --- |
| NousResearch/hermes-agent | 25.0 万 | MIT | Python | 通用个人 agent：终端/浏览器/电脑操控/记忆/技能/定时/MCP/审批 | 与后端同语言，能力面最全，最接近目标 |
| deepseek-ai/deepseek-harness | 24.1 万 | MIT | TS | 微内核，一切皆插件（2026-08 开源，开发者预览） | 架构干净但尚在预览；需 Node 旁路进程 |
| sst/opencode | 21.1 万 | MIT | TS | 编码 agent | 偏编码 |
| openclaw/openclaw | 39.1 万 | MIT | TS | 多渠道个人助理网关，内核用 Pi | 重在消息渠道；曾有默认值安全问题（见记忆） |
| badlogic/pi-mono | 11.1 万 | MIT | TS | 极简内核：4 个工具 + 扩展 SDK，可嵌入 | 小而可控，能力要自己补 |
| openai/codex | 12.7 万 | Apache-2.0 | Rust | 编码 agent，可接 OpenAI 兼容模型 | 强在编码，个人事务弱 |
| block/goose | 5.5 万 | Apache-2.0 | Rust | 通用 agent，MCP 原生，有桌面端 | 通用但生态较小 |
| anthropics/claude-code | 14.9 万 | 保留所有权利 | — | 不开源，仓库只有插件/示例，仅 Claude 模型 | **排除** |

对比验证入围：Hermes、DeepSeek Harness、Pi、goose（Codex 作编码基线）。同一 5 件真实任务、同一模型（DeepSeek），比完成度、步数、花费、出错时是否如实报告。
