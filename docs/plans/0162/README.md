# 0162 轮：任务卡清单与分道表（v0.1.62 热修 + v0.1.63 执行内核）

- **状态：用户已看过，按任务卡审查改完（2026-10-17）。** 这份只改文档的 PR 合进 main 之后开工。
- **版本号（U1）：** 热修 **v0.1.62** → 执行内核 **v0.1.63** → 执行领先 v0.1.64 → 其余追平 v0.1.65。文件名和分支名里的 `0162` 是这一轮规划的编号，不是版本号。
- **总计划：** `docs/plans/2026-10-17-0162-execution-first.md`，先看开头的「决定记录」（D1–D15、U1–U9）和「更正记录」（E1–E14）。
- **补充：** `docs/plans/2026-10-17-0162-lead-roadmap.md`；任务卡审查 `docs/plans/2026-10-17-0162-card-review.md`。
- **规矩：** `docs/sessions.md`。特别是 §8「完成证据」和 §9「旧路径要写删除条件」。

---

## 1. 开工顺序（按审查 §6）

1. **用户合并这份只改文档的 PR**，再把 §7 的简报发给各会话。
2. **热修线（v0.1.62），在 `release/0.1.62` 分支上：**
   - 从 tag v0.1.61 拉出 `release/0.1.62`。F 线的 PR 都以它为目标分支。
   - F5a 先合；合了马上把 `release/0.1.62` 合回 main 一次，main 的 CI 也恢复。
   - 然后 F1、F2、F3、F4a（扩大范围）、F4b；H2 尽量赶上。
   - FR 发版，然后把整个分支合回 main。
   - **热修发布前，`server/orchestrator/tool_loop.py`、`server/services/task_service.py` 不接别的 PR。**
3. **同时进行：**
   - ⓪Plan：M1、M2（**在 FR 之前合**）、M3；
   - ②Main：C5b；C1 可以先开发、先开 PR，但它改 `task_service.py`，合并等热修合回 main；
   - ③Hands：H1。
4. **热修发布后：** 用户跑 M1B 基线 → K1 合并 → K 线开始。C 线的 Aegis 试点也从这时开始（§9）。

## 2. 任务卡清单

- 一张卡可以对应几个 PR，拆法写在卡里（审查 A7）。卡里写了：目标、改哪些文件、不许碰、怎么做、验收、量级、风险与回退。
- 「状态」列由 ②Main 维护：待开工 → 开发中 → 待合并（附 PR 号）→ 已合并（附合并提交）。
- **分级总数（审查 A5）：** 53 张卡，**必须 44 张**、应该 8 张、可以 1 张。
  - 必须里：v0.1.62 热修 8 张，M 线 4 张，v0.1.63 32 张（原 28 张，后加 D1–D4，2026-10-18 / 10-19）。
  - 比 D3 的「必须 23 项」多，是因为按卡数算：F4、F5、C1–C3、S2、S4 拆成了几张，又加了 H1、H2、M1B、S4a、S7、R63。

| 卡 | 做什么 | 道 | 版本 | 分级 | 依赖 | 状态 |
|---|---|---|---|---|---|---|
| [F5a](F5a-ci-unblock.md) | CI 解堵：去掉 Cua Driver 的 CI 步骤；合了马上把发版分支合回 main 一次 | ②Main | v0.1.62 | 必须 | — | 已合并（release/0.1.62：#195 = `daf0f12b`；合回 main：#196 = `ad7d7ff1`） |
| [F1](F1-command-timeout.md) | `run_command` 时限跟参数走、不超过回合剩余时间；超时带输出 | ②Main | v0.1.62 | 必须 | F5a | 已合并（release/0.1.62：#194 = `f579d190`；随 v0.1.62 发布，经 #206 合回 main） |
| [F2](F2-unknown-outcome-chain.md) | 「结果不明」链四处修正；读命令判成 `read` | ②Main | v0.1.62 | 必须 | F5a、F1（要认 `code: "time_limit"`）；H2（软） | 已合并（release/0.1.62：#200 = `5fdaa8fd`；随 v0.1.62 发布，经 #206 合回 main） |
| [F3](F3-mcp-schema.md) | MCP schema 规整（三家都做顶层合并）；坏工具降级，再失败去掉全部 MCP 工具 | ②Main | v0.1.62 | 必须 | F5a | 已合并（release/0.1.62：#198 = `59b4dc09`；随 v0.1.62 发布，经 #206 合回 main） |
| [F4a](F4a-terminal-osascript-once.md) | 终端 osascript / `shortcuts run`（含带路径、`command`、`xargs` 的写法）只给「这一次」；更正 v0.1.61 说明 | ②Main | v0.1.62 | 必须 | F5a | 已合并（release/0.1.62：#199 = `c6889f83`；随 v0.1.62 发布，经 #206 合回 main） |
| [F4b](F4b-write-no-symlink.md) | 写文件不跟随符号链接，也防硬链接 | ②Main | v0.1.62 | 必须 | F5a | 已合并（release/0.1.62：#197 = `4a2c2731`；随 v0.1.62 发布，经 #206 合回 main） |
| [H2](H2-hands-not-executed-codes.md) | Hands 没执行时的明确结果代码（尽量进热修） | ③Hands | v0.1.62 | 必须 | — | 已合并（release/0.1.62：#189 = `44337393`；随 v0.1.62 发布，经 #206 合回 main） |
| [FR](FR-hotfix-release.md) | 在 `release/0.1.62` 上发 v0.1.62；发版后合回 main | ②Main | v0.1.62 | 必须 | F5a、F1–F4b（H2 若已合）；M1、M2 最好先合 | 已发布：#205 = `a4fca23b`；tag v0.1.62 → `a4fca23b`（CI 39112567104、release.yml 39114206588 均 success；冒烟 29/30）；2026-10-18 13:16Z 发布为 Latest；合回 main：#206 = `2bb62939` |
| [M1](M1-bench-upgrade.md) | 基准升级：「等你」算失败、5 道新题、Claude Code 参赛；拆 M1a、M1b 两个 PR | ⓪Plan | 脚本 | 必须 | —（FR 之前合） | 已合并（#190 = `70a39558`、#191 = `0b7124eb`） |
| [M2](M2-weekly-usage-report.md) | 本机用量周报脚本（只读、只出数字） | ⓪Plan | 脚本 | 必须 | —（FR 之前合） | 已合并（#193 = `d76d79d6`） |
| [M3](M3-acceptance-checklist.md) | 体感验收清单（§5.3 的 11 条） | ⓪Plan | 文档 | 必须 | — | 已合并（#192 = `adadd569`） |
| [M1B](M1B-baseline.md) | 在 v0.1.62 上跑基线；K1 合并要等它 | ⓪Plan + 用户 | 脚本 | 必须 | M1、FR | 已跑完，结果在 [M1B-baseline-results.md](M1B-baseline-results.md)（Claude Code 有 4 格要在 bench 修好后重跑） |
| [F5b](F5b-delete-cua-engine.md) | 删 Cua Driver 引擎代码（③Hands 审）；文件内改动约 600 行，超出 U2 的 50 行，默认拆 F5b-1 断开接线、F5b-2 按 U2 删整文件（更正 E14） | ②Main | v0.1.63 | 必须 | F5a | F5b-1 已合并（#249 = `4f50f9f2`；冒烟 29/30，只有已知的 G8′）；**F5b-2 顺延到 v0.1.64**（用户 2026-10-24 确认：只删已经没人用的文件，对用户没有影响；「必须」卡里用户同意顺延的那一半，记在 R63 的顺延清单里；见 §8） |
| [H1](H1-hands-chat-cap-answer.md) | 书面回答：聊天里 5 步上限防什么（⓪Plan 代为提交） | ③Hands | v0.1.63 | 必须 | —（K4 开工前交） | 已合并（#188 = `d74869f5`） |
| [H3](H3-hands-chat-cap-change.md) | 去掉聊天里 Hands 的 5 次和「一轮一个 App」，并进 K4；Stop 对聊天回合也停住（U8） | ③Hands | v0.1.63 | 应该 | H1（已同意，U8）、K4b | 已合并（#290 = `565338ab`；②Main 在 Opus 5.5 上审；冒烟 32/33，只有 G8′） |
| [H4](H4-app-name-forms.md) | AppleScript 里写成「.app」或完整路径的 App，也按同一个 App 认（高权限判断、never-list）；②Main 2026-10-20 复审 #267 时在 main 上发现，算恢复已有承诺的安全修复；Opus 5.5 上写和审 | ③Hands | v0.1.63 | 必须 | #267 | 已合并（#271 = `a50bcdab`；③Hands 写前半，⓪Plan 在 Opus 5.5 上写后半，②Main 在 5.5 上做了四轮安全审查和一次复查） |
| [C1](C1-tests-test-product.md) | 让测试测产品：删打开专家的 fixture 和只在专家开启时跑的路径 | ②Main | v0.1.63 | 必须 | F5a；合并等热修合回 main | 已合并（#203 = `f28b52bc`） |
| [C1b](C1b-expert-modules.md) | 删 9 个不可达的专家模块 | ②Main | v0.1.63 | 必须 | C1 | 已合并（#210 = `e13318ad`） |
| [C1c](C1c-expert-leftovers-web.md) | 专家残留（函数、网页帧、翻译）；拆 C1c-1 服务端、C1c-2 网页 | ②Main（C1c-1）、⓪Plan（C1c-2，10-21 晚改） | v0.1.63 | 必须 | C1 | 已合并（C1c-1：1a #257 = `2993ff93`、1b #258 = `6e17afc3`；C1c-2 #312 = `f9c686d5`，网页删 14 种专家帧和 21 组翻译） |
| [C2a](C2a-memory-v1.md) | 删记忆 v1 死分支（超 800 行时拆两个） | ②Main（C2a-1）、⓪Plan（C2a-2，10-21 晚改） | v0.1.63 | 必须 | C1（K2 开工前合） | 已合并（C2a-1 #237 = `83d8a581`、#244 = `0612813b`；C2a-2 按 800 行拆三个：2a #305 = `fa1d5329`、2b #307 = `e6320f54`、2c #309 = `f484f1e1`；产品代码里不再调用 `is_active`） |
| [C2b](C2b-evolution-first-batch.md) | 删进化第一批；拆 C2b-1 接口、C2b-2 自动路径 | ②Main | v0.1.63 | 必须 | C1 | 已合并（并进 C7 第二步：#335 = `3397ef2b`、#337 = `5fe84108`、#341 = `5ce9bc81`） |
| [C2c](C2c-0161-leftovers.md) | 0.1.61 遗留死代码 | ②Main | v0.1.63 | 必须 | C1 | 已合并（Hands 那半 #246 = `c40483c8`；其余 #253 = `43a1027c`，③Hands 安全审过） |
| [C2d](C2d-legacy-cli.md) | 删旧命令行 | ②Main | v0.1.63 | 必须 | C1 | 已合并（#238 = `aea8a2d2`） |
| [C2e](C2e-misc-python.md) | Python 杂项死代码；拆 C2e-1 杂项、C2e-2 媒体与 MCP 探测 | ②Main | v0.1.63 | 必须 | C1 | 已合并（C2e-1 #247 = `5e25ac92`；C2e-2 #254 = `5c176990`） |
| [C2f](C2f-misc-web-repo.md) | 网页杂项与误提交文件 | ②Main | v0.1.63 | 必须 | C1 | 已合并（#243 = `3e0de127`） |
| [C3](C3-tool-exposure.md) | 删 / 降级没人用的工具；拆 C3a 删除、C3b 降级 | ②Main | v0.1.63 | 必须 | C1、K5（K7 之前合；C1b 最好先合） | 已合并（C3a #304 = `0a1c1092`；C3b #313 = `6f962f98`，K7 没合就在 R63 之前 revert） |
| [C4](C4-remove-shadow-judgment.md) | 删影子评判；记录撤回决定② | ②Main | v0.1.63 | 必须 | C1、C2c | 已合并（#256 = `c2652b80`，③Hands 安全审过；`scripts/usage_report.py` 的影子评判表经 ⓪Plan 同意一起删） |
| [C5a](C5a-process-docs-privacy.md) | 过程文档移到存档分支；从文件里删隐私段落 | ②Main | v0.1.63 | 应该 | — | 待开工 → 顺延到 v0.1.64（用户 2026-10-24 确认冻结清单；见 §8） |
| [C5b](C5b-version-source-inventory.md) | 唯一版本来源；能力清单只在发版时生成（越早合越好） | ②Main | v0.1.63 | 应该 | — | 已合并（#201 = `90fd3c11`） |
| [C6](C6-ci-parallel-coverage.md) | CI 并行与覆盖率 | ②Main | v0.1.63 | 应该 | F5a | 已合并（#330 = `0308dda5`、#333 = `a9abf677`、#334 = `158799fa`；跟进 #370 = `fa2245d7`、#372 = `05b84787`） |
| [C7](C7-expert-block.md) | 删专家时代的那一大块：先剪掉技能锻造「评估要选分身」，再按区域分 2–3 个 PR 整块删（含 C2b、进化第二批、dispatcher、replay、recipes、专家接口、`arslan/spawn`、`jinja2`），v0.1.64 用一次迁移收尾（用户 2026-10-21 定，U13） | ②Main | 第一、二步 v0.1.63；第三步 v0.1.64 | 应该（C2b 那部分仍是必须） | C1；删 `arslan/spawn` 的 PR 在 C9 之后 | 第一、二步已合并（#331 = `f861c61e`、#342 = `ecfe5dca`、#345 = `5984b3d2`、#346 = `26b4e603`、#351 = `2765a4eb`、#354 = `99ea172f`、#361 = `5f21b301`、#366 = `38298c35`、#385 = `f8b132bf`、#386 = `78870347`、#388 = `43d93eca`；含 C2b）；第三步按卡在 v0.1.64 |
| [C8](C8-curation-distill-research-review.md) | 删整理层、回合结束提炼和研究复核；引用要求写进 K5（用户 2026-10-21 定，U13） | ②Main | v0.1.63 | 应该 | C1；K5 写引用要求 | 已合并（#355 = `a19833d2`、#357 = `c152adc1`、#358 = `a35a972c`、#363 = `8c68410a`、#365 = `24aa4a91`、#373 = `7d56d7e9`、#382 = `f0121191`） |
| [C9](C9-bundled-skills-mcp-catalog.md) | 自带技能只留 `designed-html-report` 和上游原文的 `skill-creator`，其余 44 个退役；删 MCP 推荐目录（已装的不动）（用户 2026-10-21 定，U13） | ③Hands | v0.1.63 | 应该 | D7 | 已合并（C9a #296 = `d41d6793`；C9b #359 = `79197ef5`） |
| [C10](C10-docker.md) | 删 Docker 这条部署路径（三个文件和 7 份文档里的段落）；`web/`、静态文件服务、prod 模式不动（用户 2026-10-21 定，U13） | ③Hands | v0.1.63 | 应该 | — | 已合并（#291 = `c741d3df`） |
| [C11](C11-prod-mode.md) | 删 prod 模式：先把打包版加固（空密钥拒绝启动、`ARSLAN_PACKAGED` 强制赋值、CORS 默认空、无 Origin 的 WebSocket 拒绝、禁用测试路由、mcp-token 重新生成要出示当前 token），再删 `is_prod`（云端审计 [3]，U14） | ③Hands | v0.1.63 | 应该 | C10；#298 先合 | 已合并（#338 = `be03c246`、#343 = `dc63e5dc`、#364 = `f60708c7`、#369 = `bbbf023d`、#371 = `f617b208`、#379 = `383de3f1`、SECURITY.md #339 = `3b74e63e`）；C11b（#338 审查的 F3–F7）#394 = `adaac481`，跟进 #402 = `409913d7` |
| [K1](K1-native-tool-protocol.md) | Claude、Gemini 走原生工具协议；保留思考块，支持 `tool_choice`；Anthropic 回合内发出后不改前文（服务端清理旧结果） | ②Main | v0.1.63 | 必须 | C1；合并等 M1B | 已合并（K1a #212 = `df18ba0e`；K1b #213 = `18d691bb`；合并后对照在 #213） |
| [K2](K2-context-by-window.md) | 跨轮上下文按窗口；工具摘要放进 `content`；回合后工作挪出锁 | ②Main | v0.1.63 | 必须 | K1；C2a | 已合并（K2a #240 = `4f471a30`；K2b #252 = `8780fc34`，⓪Plan 的 k2b-ds 过门槛：19/27 通过，基线 18；③Hands 审过） |
| [K3](K3-prompt-layout-cache.md) | 提示词布局与缓存断点 | ②Main | v0.1.63 | 必须 | K2 | 已合并（K3 #259 = `f3bda58d`，DeepSeek 门槛过；K3b #275 = `7e8c57aa`：Claude 上不改已发出的历史、清理改 100k/40k，E26） |
| [K4](K4-one-stop-policy.md) | 一个停止策略；保留花费上限，美元上限默认开；拆 K4a、K4b | ②Main | v0.1.63 | 必须 | K3、H1 | K4a 已合并（#277 = `5a97ff7f`；DeepSeek 门槛过：通过 20/27、「等你」3，基线 18、4；5% 账单核对过）；K4b 已合并（#282 = `93921bf5`；DeepSeek 门槛过：通过 21/27、「等你」0，基线 18、4） |
| [K5](K5-working-method-tool-docs.md) | 工作方法与工具说明；多步骤任务结束时给用户四行收尾 | ②Main | v0.1.63 | 必须 | K4b、F1 | 已合并（#294 = `528a05a1`）；DeepSeek 门槛过：通过 20/27、答对 20/27、「等你」1（基线 18、19、4），没有新的报错类型 |
| [K7](K7-tools-on-demand.md) | MCP 和少用的工具按需取用 | ②Main | v0.1.63 | 必须 | K5、C3、F3 | 已合并（#315 = `046d184b`）；DeepSeek 门槛过：通过 23/27、答对 23/27、「等你」0（基线 18、19、4；K5 20、20、1），没有新的报错类型；A/B（全部常驻）第一轮 3/4 对 3/4 |
| [K8](K8-true-streaming-guards-after.md) | 真流式，守卫改为事后；按供应商拆 K8a、K8b、K8c | ②Main | v0.1.63 | 必须 | K7 | 已合并（K8a #326 = `0807d692`、K8b #336 = `28e76f42`、K8c #350 = `bcba7000`；K8a 的 DeepSeek 门槛过：通过 18/27、答对 20/27、「等你」2） |
| [K9](K9-parallel-reads-steering.md) | 只读工具并行 + 回合中插话（窗口、iPhone、按住说话各一条测试；灵动岛输入挪到 v0.1.64） | ②Main | v0.1.63 | 必须 | K8c | 已合并（K9a #368 = `4b8e1556`；K9b #393 = `d3ac7b28`，DeepSeek 门槛过：通过 22/27、答对 23/27、「等你」1，基线 18、19、4；跟进 #401 = `f3b6619c`） |
| [K10](K10-agents-md.md) | 读 AGENTS.md | ②Main | v0.1.63 | 应该 | K9 | 待开工 → 顺延到 v0.1.64（用户 2026-10-24 确认冻结清单；见 §8） |
| [K6](K6-file-tools.md) | 文件工具补齐（不进严格链） | ②Main | v0.1.63 | 应该 | K7 | 待开工 → 顺延到 v0.1.64（用户 2026-10-24 确认冻结清单；见 §8） |
| [D2](D2-checks-not-run.md) | 「检查跑不了」不再把做完的事挂成「等你」：常见代码和配置文件按文本解析，没有解析器的类型记「不适用」（M1B 基线发现，⓪Plan 2026-10-19 加；不进严格链） | ②Main | v0.1.63 | 必须 | — | 已合并（#221 = `84d90f98`） |
| [D3](D3-read-timeout-known.md) | 只读命令超时，不记成「结果不明」：`_reads_only` 认得 `&&`、`;`、`\|` 连起来的只读命令和丢弃输出的重定向（K1 合并后对照发现；U10 提为必须，不进严格链） | ②Main | v0.1.63 | 必须 | — | 已合并（#230 = `053f6b42`） |
| [D4](D4-osascript-not-authorized.md) | osascript 报「未授权」（`-1743`，核实后加 `-10004`），只对一个 App 说话时算已知失败（K1 合并前后对照发现；U10 提为必须，不进严格链） | ②Main | v0.1.63 | 必须 | — | 已合并（#231 = `0d15026b`；后续 #245 = `5e33c5e5`，⓪Plan 实测 T1 2/3，K2a 时 0/3）；还有两种写法记在卡末，以后再看 |
| [D5](D5-search-native-first.md) | 搜索：先用这个对话这一轮模型自带的搜索（Claude 用 Anthropic 服务端 web search，只在官方 host 或允许清单上；本地模型的对话不用任何云端自带搜索，DeepSeek 一起改）；Tavily / SearXNG 可以设成备选，已存的选择照旧只用它，选了服务就不再落到 DuckDuckGo；403、429、人机验证报「搜索被拦」，401 报 key 被拒（用户 2026-10-20 要求，⓪Plan 定为应该；③Hands 审卡改过；不进严格链，但**要在 R63 用 Claude 跑最后一轮之前合**，用户 2026-10-20） | ⓪Plan（10-21 晚从 ②Main 改过来；产品代码由别的会话审） | v0.1.63 | 应该 | — | 已合并（#306 = `d9cec85f`；全量 9289 过；Claude 上 T3 2/3 → 3/3、T2 照旧 0/3，搜索全走 Anthropic、没有被拦，每次约 1.2 美分） |
| [D6](D6-journal-false-positive.md) | 一步记不进任务记录时只拒这一步、任务继续；不在 JSON 编码后的文字上查密钥（「无验证码：」加换行被误判，K3 的 Claude 对照 T2 第 2 次因此整个后台任务停掉）；同类的 4 处一起改（用户 2026-10-20 定为应该；不进严格链，K3 之后） | ②Main | v0.1.63 | 应该 | K3 | 已合并（卡 #270 = `3783951f`；代码 #274 = `ceb4d976`） |
| [D1](D1-deliver-files.md) | 回合做出的文件送到窗口和 iPhone：新工具 `attach_file`；来自 iPhone 的回合告诉模型路径没用（用户报告，⓪Plan 2026-10-18 加；不进严格链） | ②Main | v0.1.63 | 必须 | — | 已合并（#217 = `57a2218b`）；M3 第 12 条（真 Mac + iPhone 截图）待用户验 |
| [D7](D7-retire-only-seed-rows.md) | 退役名单只删自带的技能：导入的同名技能（notion、obsidian 等）今天会在重启时被删（④参谋发现，⓪Plan 核过；不进严格链） | ③Hands | v0.1.63 | 必须 | — | 已合并（#293 = `2f149dbd`） |
| [D8](D8-titles.md) | 对话标题：只把你的第一句话发给这段对话自己的模型起标题，失败再截断；删 `title_config_id` 槽（用户 2026-10-21 定，U13；不进严格链） | ③Hands | v0.1.63 | 应该 | — | 已合并（#295 = `863e28f6`） |
| [D9](D9-attachment-truncation.md) | 附件被截断时告诉模型（全文多少字、原件在哪）；上限从 12,000 字调到 40,000 字（①iOS 转来的用户报告，用户 2026-10-21 定两条都做；不进严格链） | ③Hands | v0.1.63 | 应该 | — | 已合并（#302 = `72081e7c`；用户 2026-10-24 定进 v0.1.63，③Hands rebase） |
| [S1](S1-mcp-approval-by-hints.md) | MCP 按标注审批（R6）；定时任务不给后台工具（R7）；定时任务再加四项：不采信「总是允许」、只写 `~/Arslan`、拒绝写账本、卡上显示任务内容（云端审计 [2]，U14）；先单独删掉说明里「只读」那句（S1-0） | ②Main | v0.1.63 | 必须 | C1、F4a、F2（H2） | 已合并（S1-0 #301 = `eaaf84f4`；S1a #317 = `97082c99`；③Hands 跟进 #314 = `198a3859`；S1b #325 = `a419f895`、#328 = `7d13c907`；定时任务不提供 `run_command` 的兜底 #399 = `e497ef7c`；①iOS 的 Bridge 测试（定时卡带上任务内容后，手机上的卡不变）#319 = `5e021a8f`） |
| [S2a](S2a-command-three-layers.md) | 命令「沙箱优先」三层，同时收紧沙箱；受保护路径补全；拆 S2a-1 收紧沙箱、S2a-2 三层 | ②Main（S2a-1）、③Hands（S2a-2，10-21 晚改） | v0.1.63 | 必须 | F4a、C1、C4 | S2a-1 已合并（#265 = `0183ff88`）；S2a-1b 已合并（#272 = `0d17ee13`）；S2a-2 已合并（#308 = `36b8506c`）；**S2a-3 顺延到 v0.1.64**（用户 2026-10-24 定：复审被安全检查拦下；#375、#376、#378、#396 留着）；v0.1.63 的兜底已合并：默认「每条新命令都先问」#398 = `6169ceb5`（迁移 0070），定时任务不跑命令 #399 = `e497ef7c` |
| [S2b](S2b-drop-vendored-hermes.md) | 删整份引入的 Hermes 规则；拆 S2b-1 换上自有的文本处理（约 150 行）、S2b-2 按 U2 只删文件 | ③Hands（10-21 晚改） | v0.1.63 | 必须 | S2a | 已合并（S2b-1 #320 = `543b5dad`；S2b-2 #322 = `fa806885`） |
| [S3](S3-checkpoints.md) | 检查点：文件和命令都能撤销；每回合克隆一次；拆 S3a 检查点、S3b 撤销界面 | ②Main | v0.1.63 | 必须 | C1、F4b（最好在 S2a-2 之前合） | 已合并（S3a #318 = `256ada17`；S3b #329 = `6e8f7202`，迁移 0069） |
| [S4a](S4a-outside-remote-cards-decide.md) | 出沙箱卡、远程卡走 `decide()` 并写账本；两份确认流程合成一份 | ③Hands（10-21 晚改） | v0.1.63 | 必须 | C4、S2a | 已合并（#352 = `8866f1e3`）；两个跟进顺延到 v0.1.64（见 §8） |
| [S4b](S4b-allowed-folders.md) | 「允许的文件夹」（不接受别的卷上的文件夹：S3 撤销不了） | ②Main | v0.1.63 | 应该 | S3、S4a | 待开工 → 顺延到 v0.1.64（用户 2026-10-24 确认冻结清单；见 §8） |
| [S5](S5-mode-setting.md) | 一个模式设置（含计划模式）；完全访问下照问的种类按 U4 | ②Main | v0.1.63 | 应该 | S2a、S1、C4、F4a、S3（S4b 软） | 待开工 → 顺延到 v0.1.64（用户 2026-10-24 确认冻结清单；见 §8） |
| [S6](S6-remembered-answers-page.md) | 「记住的回答」页 | ②Main | v0.1.63 | 可以 | S4b、S2a | 待开工 → 顺延到 v0.1.64（用户 2026-10-24 确认冻结清单；见 §8） |
| [S7](S7-capability-card-ledger.md) | 安装能力卡也写一行账本（§5.4 门槛） | ③Hands（10-21 晚改） | v0.1.63 | 必须 | S4a、C4 | 已合并（#367 = `2a1d252f`） |
| [R63](R63-release.md) | 发 v0.1.63：最后一轮 M1、7 天本机数据、M3、发布说明对测试 | ⓪Plan 判定 + ②Main 发版 | v0.1.63 | 必须 | v0.1.63 全部「必须」卡 | 进行中：冻结清单用户 2026-10-24 确认；下一步发版 PR |

## 3. 合并顺序

**热修线**（目标分支 `release/0.1.62`，从 tag v0.1.61 拉出）：

```
F5a ──→ 先把 release/0.1.62 合回 main 一次（main 的 CI 恢复）
 ├─ F1 ──┐
 ├─ H2 ───┴─ F2
 ├─ F3
 ├─ F4a
 └─ F4b ──→ FR（v0.1.62）──→ 整个 release/0.1.62 合回 main
```

- 热修发布前，`tool_loop.py`、`task_service.py` 不接别的 PR。
- `docs/CAPABILITY_INVENTORY.md` 冲突时随便取一边，最后统一重新生成一次。

**K 线：严格按顺序，一次只开一个。**

```
C1 → K1 → K2 → K3 → K4a → K4b → K5 → K7 → K8a → K8b → K8c → K9 → K10
      ↑ K1 可以先开发，合并等 M1B（v0.1.62 发布后的基线）
```

- **K6 不进严格链**（审查 A1）：K7 合并后，在 K 线 PR 之间的空档合；赶不上 v0.1.63 就顺延。
- **D2、D3、D4 不进严格链：** 在 K 线 PR 之间的空档合。D3、D4 都改 `task_service.py`（热点文件），谁先合另一个 rebase。R63 之前都要合（U10）。
- **D5 也不进严格链，** 在 K 线 PR 之间的空档合；**必须在 R63 用 Claude 跑最后一轮全套之前合**（用户 2026-10-20），否则那一轮 Claude 的 T2、T3 量的还是 DuckDuckGo 抓取。
- **D6 也不进严格链，** K3 合并后先做，排在「回合中途缓存作废」那项 K 线工作之前（`tool_loop.py` 是 K3 的文件）。
- **K 线每个 PR 的前后对比（U10）：** 和新基线（K1 合并后的 main，每次全新实例）逐题比，单独列「等你」的次数。默认跑 DeepSeek；K3、K8 加跑 Claude。R63 之前在 Claude 上完整跑一遍全套。
- **D1 不进严格链**（2026-10-18 用户报告后加，⓪Plan 定）：K1 合并后的第一个空档合。如果 D1 已经就绪而 M1B 还没跑（K1 合不了），D1 可以先于 K1 合，K1 rebase。D1 改 `file_tools.py`，和 K6 同一个文件，D1 先合。
- 固定位置：C2a 在 K2 开工前合（都改 `memory.py`）；H1 在 K4 开工前交，H3 在 K4b 之后合；C3a、C3b 在 K5 之后、K7 之前合。

**C、S 两线：并行，但有先后：**

- C2c → C4 → S2a → S4a → S7（都改 `server/services/approvals.py` 和 `server/ws/arslan.py` 的确认阶梯）；
- S3 → S4b，S4a → S4b，S4b → S6；
- S2a → S2b；S2a、S1、S3 → S5；
- S2a-1 → S2a-2，S2b-1 → S2b-2，S3a → S3b；S2a-2、S2b-1 → **S2a-3 → S4a、S7**（S2a-3 是 R63 前必须合的补洞，2026-10-22 加）；
- S3 最好在 S2a-2 之前合（S2a-2 之后，工作文件夹里的删除不再出卡，要靠撤销）；
- 其余 C 卡都在 C1 之后，什么时候合都行。
- **清理卡（U13，2026-10-21）：** C7、C8、C9、C10、D7、D8 和 K4b、K5 并行（用户定），不进 K 线严格链：
  - D7 → C9 → C7 第二步里删 `arslan/spawn` 的那个 PR；
  - C7 第一步（剪线）→ C7 第二步；C2b 是 C7 第二步的第一个 PR；
  - C8 和 C7 第二步都动 `distill_service`，②Main 在计划里定先后；
  - 碰到热点文件（`arslan.py`、`tool_loop.py` 等，`docs/sessions.md` §3）的 PR，在 K 线 PR 之间的空档合；
  - C7 第二步、C8 不在聊天主路径上，CI 全量绿即可，不跑 DeepSeek 门槛（用户定）。例外：C8 里的 `compact_saved_context` 在主路径上，要原样搬走、有逐字一致的测试（②Main 审 #284 时发现）；还有哪一处在主路径上，那一处单独跑门槛。

**M 线：** 随时，不进 App。M1、M2 在 FR 之前合；M1B 等 M1 和 v0.1.62。

**规则：**

- 同一时间，改同一个热点文件的打开 PR 最多一个。K 线优先。
- 其他 PR 等当前这个 K 线 PR 合了，再 rebase。
- **800 行的例外（U2，已定）：** 只做整份删除的 PR 可以超过 800 行。条件：只删不可达或第三方的整个文件；别处只去掉引用，合计 ≤50 行；不改行为；PR 描述列出删了哪些文件、怎么确认不可达；CI 全绿。C1b 因此不拆。F5b 和 S2b 不满足「别处 ≤50 行」（F5b 文件内要改约 600 行；S2b 要先换上一个约 150 行的自有模块），所以照旧各拆两个 PR，第二个按 U2 只删整文件（更正 E14）。用户要是放宽 U2，这两张可以各合成一个 PR。

## 4. 分道表

| 道 | 负责的卡 | 拥有的文件 | 不许碰 |
|---|---|---|---|
| ⓪Plan | M1、M1B（和用户一起）、M2、M3；R63 的门槛判定；代为提交 H1 的回答；维护总计划、本表和任务卡；10-21 晚起另做 D5、C1c-2、C2a-2（②Main 线上卡太多） | `scripts/kernel_bench/**`、M2 新增的周报脚本、`docs/plans/**`、`docs/sessions.md`；那三张卡改到的文件 | 其他产品代码；自己写的产品代码由别的会话审 |
| ②Main | F5a、F1、F2、F3、F4a、F4b、FR、F5b；全部 C、K、S 卡（C6 移给 ⑤，C7、C8 移给 ⑥，10-22）；R63 的发版准备；合并队列、本表的「状态」列、迁移号登记、CI 健康 | `server/**`、`arslan/**`、`web/**`、`.github/**`、`packaging/**`、`docs/releases/**`、`docs/CAPABILITY_INVENTORY.md`。<br>以下除外：③Hands 的文件；Bridge 契约文件的帧格式 | ③Hands 的文件（要改须由 ③Hands 审，例如 F5b、C2c 里 AppleScript 那两行）；Bridge 帧格式 |
| ③Hands | H1、H2、H3、H4；审 F5b 和任何改 Hands 文件的卡；U13 / U14 起另做 D7、D8、D9、C9、C10、C11；10-21 晚起另做 S2a-2、S2b、S4a、S7（这几张卡改到的文件，期间 ②Main 不碰） | `desktop/hands/**`、`server/registry/hands_tools.py`、`server/services/hands_service.py`、`server/api/hands.py`、`scripts/hands_smoke.py` | 其他所有文件。本轮不新增 Hands 能力 |
| ①iOS | 无 | iOS 仓库 | 本轮 Mac 端不改 Bridge 帧格式（`desktop/bridge/**`、`server/ws/bridge.py`、`spec/mobile-bridge/**`）。哪张卡如果发现需要改（最可能是 K9），先停下来找 ②Main 和 ①iOS |
| Codex（外部审查工具，不是会话；用户 10-27 定） | v0.1.64 安全审查的外部审查、日常安全面和大 PR 的独立审查、卡住时 debug（§8「安全审查路径」） | 无：只读，结论由用户贴到 PR 上 | 推送、合并、main；用户的家目录、Arslan 的数据、`~/.arslan`、跑分原始记录、真密钥 |
| C 线试点会话 | v0.1.62 发布后的 C 卡（§9） | 同 ②Main 的 C 卡 | 同 ②Main；不装 superpowers |
| ⑤C6 | C6（2026-10-22 从 ②Main 移来，用户同意加开会话） | `.github/workflows/ci.yml`、pytest 的配置和依赖（`pyproject.toml` 的测试部分、`uv.lock`） | 其他所有文件；改动跑哪些测试之前先问 ⓪Plan。删 macOS 计数那两条测试留给 ②Main |
| ⑥C7 | C7 第一、二步（v0.1.63 的部分），之后 C8（2026-10-22 从 ②Main 移来） | 这两张卡要删的文件，加上 `compact_saved_context` 搬去的新位置 | K8 的流式文件、S3b 的文件、③Hands 的文件、Bridge 帧格式；碰到权限或沙箱的路径先停下来问 ⓪Plan |

## 5. 迁移号登记表

- 原来 PR 3、6、5、7 的 0069–0072 预留**全部作废**。
- skills v2 分支上的 `_0070_skills_v2` 随该分支不合并，一起作废。

| 号 | 归属 | 状态 |
|---|---|---|
| 0067 | 0.1.61 权限核心 | 已发布（v0.1.61），冻结 |
| 0068 | 0.1.61 MCP 状态 | 已发布（v0.1.61），冻结 |
| 0069 | v0.1.63 S3b：`arslan_messages` 的 id 不再重复发放（重建成 AUTOINCREMENT） | ②Main 登记，随 S3b 的 PR |
| 0070 | v0.1.63 默认「每条命令都问」：存着的 `shell_confirm_policy = ask_risky` 一次性改成 `ask_all`（用户 10-24 定的兜底） | ②Main 登记，随该 PR |
| 0071 | 空 | 下一个可用的号 |

- v0.1.62 热修线不带迁移。
- v0.1.63 用了 2 个迁移号：S3b 的 0069，「每条命令都问」默认的 0070（只改一行设置，不动表结构）。S3a 的检查点索引用数据目录里的清单文件，不建表。
- 其他卡都设计成不要迁移：K2 的工具摘要放进现有消息的 `content`；S1、S4a、S4b 用现有的权限规则表和授权表；S5 用设置键值；K4 的美元上限用设置键值。
- 需要迁移号时，向 ②Main 申请，②Main 在上表登记，规则见 `docs/sessions.md` §4。

## 6. 已定的事（不用再问）

- 版本号、800 行例外、D10 折中、完全访问下照问的种类、§5.2 那一行门槛、H3 改「应该」、F5b 不进热修：U1–U7，见总计划「决定记录（续）」；H1 的推荐（U8，2026-10-18）。
- 合并（U9，2026-10-18）：⓪Plan 可以合并同时满足四条的 PR（CI 绿、完成证据四项齐、另一个会话审过、按 §3 顺序）；②Main、③Hands 照旧不合并。打 tag、发布、改仓库设置、真实 key、DeepSeek 以外的花费仍归用户。
- 仍待定、本轮不碰：公开历史里的隐私内容（先只从文件里删，C5a）；App Store Connect 写入链路（本版不动）。

## 7. 开工简报（用户合并本 PR 后，复制粘贴给对应的会话）

### ②Main

```
你是 ②Main，负责 Arslan v0.1.62（热修）和 v0.1.63（执行内核）的实现和合并协调。

开工前读：docs/sessions.md；docs/plans/0162/README.md；
docs/plans/2026-10-17-0162-execution-first.md（先看「决定记录」和「更正记录」）。

顺序（README §1）：
- 从 tag v0.1.61 拉出 release/0.1.62。F 线的 PR 都以它为目标分支。
- 第一个做 F5a；合了马上把 release/0.1.62 合回 main 一次。
- 然后 F1、F2、F3、F4a、F4b；最后 FR。发版后把 release/0.1.62 整个合回 main。
- 热修发布前，tool_loop.py、task_service.py 不接别的 PR。
- 同时可做 C5b；C1 可以先开发，合并等热修合回 main。
- K 线等 M1B 跑完、K1 合并后开始，严格按 README §3，一次只开一个；每个 K 线 PR 贴 M1 前后对比。

规矩：
- 一个 PR 只做一件事，产品代码不超过约 800 行（整份删除按 U2）。
- 每个 PR 和每次说「做完了」，写完成证据四项（sessions §8）。
- 留着的旧路径写明删除条件（sessions §9）。
- 合并、打 tag、发布由用户点。你维护 README 的「状态」列和迁移号登记表。
- 要改 ③Hands 的文件或 Bridge 帧格式时，先停下来问。
- 新想法记进 README §8「v0.1.64 候选」。不写本机路径和隐私；草稿区不算交接。
- 方法包照旧用 superpowers。v0.1.62 发布后的 C 线试点见 README §9。
```

### ③Hands

```
你是 ③Hands。这一轮你做三件事，加上审稿。

开工前读：docs/sessions.md；docs/plans/0162/README.md。

1. H1：书面回答「聊天里 Hands 最多 5 步（hands_tools.py 的 INLINE_ACTIONS）防的是什么」，
   建议放宽到多少、或改成按时长。K4 开工前交给 ⓪Plan，由 ⓪Plan 写进 H1 卡并提交。
2. H2：所有没执行的 Hands 结果，返回固定列表里的代码和 executed: false。
   尽量赶上 v0.1.62：以 release/0.1.62 为目标分支，在 F2 之前合。
3. H3（应该）：用户对 H1 点头、K4b 合了以后，按结论改聊天上限。

另外审 F5b（删 Cua Driver 引擎），以及任何改你文件的卡。
本轮不新增 Hands 能力。每个 PR 写完成证据四项（sessions §8）。合并由用户点。
```

### ⓪Plan（M 线）

```
你是 ⓪Plan。按 docs/plans/0162/M1、M2、M3 三张卡做跑分升级、本机周报脚本和体感验收清单。
M1、M2 要在 FR 之前合。M1B 的基线等 v0.1.62 发布后，由用户在本机用自己的 key 跑；K1 合并要等它。
另外：维护总计划和本表；代为提交 ③Hands 的 H1 回答；审 Aegis 的启动脚本并锁定版本（README §9）；
按 R63 卡判定 v0.1.63 的发版门槛。
```

### ①iOS

```
告知：Mac 端 v0.1.62、v0.1.63 都不改 Bridge 帧格式。
K9（回合中从 iPhone 插话）如果发现必须改，②Main 会先来问你。你这边照常推进。
```

## 8. v0.1.64 候选（范围冻结后的新想法）

**v0.1.63 冻结时顺延的（用户 2026-10-24 确认 ②Main 列的冻结清单）：**

- **F5b-2**（删 Cua Driver 那些已经没人用的文件，U2，③Hands 审）：只删死文件，对用户没有影响。F5b 是「必须」卡，这一半由用户同意顺延，记在 R63 的顺延清单里。F5b-1（断开接线，#249）已在 v0.1.63。
- **C5a**（过程文档移到存档分支、删隐私段落）：冻结前没开工；对用户没有影响。
- **K6**（文件工具补齐）：冻结前没开工。
- **K10**（读 AGENTS.md）：冻结前没开工。
- **S4b**（允许的文件夹）、**S5**（一个模式设置）、**S6**（「记住的回答」页，「可以」）：冻结前没开工；三张都建在权限模型上，而 v0.1.64 的 S2a-3 和默认拒绝沙箱会改这一层，放在它们后面做。
- **S4a 的两个跟进：** 没打开过的卡记成「过期」而不是「离开」；设置里列出「不包沙箱」的授权。跟 S6 一起做。
- **#298 和 #298b**（SECURITY.md / ARCHITECTURE.md 不再承诺没有的保护，云端审计 [1]）：SECURITY.md 那部分已被 #339 顶替；剩下的 ARCHITECTURE.md 和按三层模型重写的命令段落（#298b）要按 S2a-3 合进去以后的样子写，跟 S2a-3 一起。
- S2a-3（#375、#376、#378）和 PR3（#396）的顺延已在下面「安全审查路径」那条和 R63 卡里记下。
- **#409 的三个跟进（独立审查，非阻塞；⓪Plan 2026-10-24 转）：** ① `tests/test_real_secret_guard.py` 里大小写那条在 macOS 上才有意义，要标 macos，CI 的 macOS 任务才会跑到；②「没覆盖」清单补上 `os.link` 硬链接（不经拒绝就读到文件）以及 unlink、rename；③ 会话收尾时发生的拒绝不会被报出来。
- **「只在有风险时问」的条件（用户 2026-10-24 定，R63）：** v0.1.64 合不进 S2a-3 和 #406 时，「只在有风险时问」改为禁用，直到修好。v0.1.63 切到它时的确认框、旁边指向「撤回这一轮…」的那句、升级后的一次性提示，都随 S2a-3 和 #406 合进去时删（代码里写了 DELETE-BY）。
- **#410 复审的跟进（非阻塞；⓪Plan 2026-10-25 转）：** 新装的第一次启动如果在 `create_all` 之后、迁移跑完之前就挂了，下一次启动会把它当成老安装，也弹一次性提示（SQLite 的建表语句不在事务里，`create_all` 建的表会留下来）。修法：只有迁移账本或 settings 里已经有行，才算老安装。另外两处没有测试：第一次启动失败这种情况；提示里那条设置路径的文字（六种语言）。提示要在 v0.1.64 随 S2a-3 和 #406 删掉时，这条跟着作废。
- **诊断接口只认 `live`（#421 发现，⓪Plan 2026-10-27 定放 v0.1.64）：** `server/api/runs.py:281`、`:347`、`:386` 三个诊断接口还是 `Run.kind == "live"`，聊天回合从 2026-09-14 起记成 host，这几处恒为空。改成 `server/run_kinds.py` 的 `USER_RUN_KINDS`（`:170` 现在是同一组种类的字面量，也一起换），并加测试钉住。
- **时序不稳定的测试（⓪Plan 2026-10-26 转，非阻塞）：** `tests/server/test_mcp_discovery_v2.py::test_one_servers_writes_never_overlap_but_two_servers_may` 最后一句断言两个服务器的写入一定重叠（`seen["most"] == 2`），这取决于两个任务谁先跑完，不是锁的行为。#418 的 CI 第一次跑（run 40221245199）因此挂，重跑才过。修法：用事件让两次写入确定地同时在写（一个等另一个进来），或者只断言「同一服务器从不重叠」，不再断言「两个服务器一定重叠」。
- **#416（撤回不计 Python 环境）审查的两个跟进（非阻塞；⓪Plan 2026-10-26 转）：** ① 恢复时的保护信任清单里的 `written`：清单在 run 之后被改过的话，`written` 里列的环境内文件仍会被写回（清单本身可被沙箱外的命令改，见 S3 的 🔴1/🟠3）；② ~~没有 clonefile 的地方（Linux、非 APFS 卷），按文件保存走复制时会覆盖副本里已有的同名原件~~ **已修（#416 复审修复 22a27065）**：副本里已有的文件夹不再算不计入（`_left_out_at` 看副本），按文件保存只落在副本没有的位置，同一个文件也只存一次，所以碰不到已存的原件。复审又加两条：③ 发布说明和设置里那句撤回说明写「（不计入的文件夹）不会恢复」说少了：write_file / edit_file 在环境里改的文件单独存过，照样恢复，措辞要改成「命令在里面的改动不会恢复」一类；④ `_left_out_at` 遇到嵌套的 `sub/.git` 就停（里面不再按环境算），这条没有测试。
- **过期的「经验」记忆（用户试用 M3 第 1 条，2026-10-25；⓪Plan 转，非阻塞）：** 老版本（F1 之前）存下的一条经验记忆（记忆 v2 里 kind=experience 的一条，在 `memory_entries`，由旧的 `learnings` 迁移过来；旧那行也还在）说 `run_command` 即使给了很长的 `timeout_s`，也只有半分钟左右。F1（v0.1.62）之后这已经不对了，可这条记忆还在、还每轮注入。结果 Arslan 以为命令有 20 秒左右的上限，把一个等 75 秒的命令放到后台再反复去查。**产品上的缺口：** 讲 Arslan 自己工具上限的经验记忆，会比让它成立的那个版本活得更久。**可能的修法（都针对记忆 v2 的 experience 条目）：** 提到某个工具的经验记忆记下当时的 app 版本；升级改了这个工具的上限时，把它标成待复核或直接不再注入；或者在 v0.1.64 的迁移里一次性清一遍。一次性清理要把 v2 条目和它在 `learnings` 里的旧来源一起处理，不然重新迁移会把它带回来。（用户那条记忆的原文不进仓库；用户自己那份手动删。）
- **M3 第 3 条：第三轮追问改多了（用户 2026-10-27 定带着发 v0.1.63；⓪Plan 转）：** 写三节报告 → 把第二节改短 → 「再加一个表格」，第三轮把第二节原有的段落改写进了表格（数字都在，段落没了）。v0.1.64 先查：第二轮的结果有没有完整进第三轮的上下文（K2），提示词有没有说「只加，不改别处」；再加一条测试或 bench 题：加表格之后其余各节逐字不变。
- **M3 第 5 条：改大文件里的一行走终端整份改写（同上，带着发）：** 「把 test-1000.txt 第 500 行改成……」，Claude 和 DeepSeek 都用 `sed -i` 或 python3 整份读写，不用 `edit_file`；内容对，但步骤显示的是命令，不是「改了 test-1000.txt」，默认设置下还要多出一张命令卡。这条和上面「**K6**（文件工具补齐）：冻结前没开工」是同一件事，K6 卡的手动验收就是 M3 第 5 条（`K6-file-tools.md:52`）。`edit_file` 是常驻工具（`server/orchestrator/arslan.py:1036`，已核）。一个可能的原因（未证实）：`read_file` 的输出不带行号，「第 500 行」最顺手的改法就成了 `sed '500s…'`。v0.1.64 先做 K6，再按 M3 第 5 条复测；还不过再查工具说明、经验记忆和终端开着时的偏好。
- **M3 第 4 条只证明到普通对话（⓪Plan 2026-10-27 转）：** K7 之后 MCP 工具按需加载，接着大服务器时普通对话不发它的工具说明，所以第 4 条过了不代表这些说明能被 Anthropic、DeepSeek 接受。要一条真用到大服务器工具的测试：`use_tool` 之后这个工具进工具表，再发一轮，Anthropic 和 DeepSeek 各一遍（或 bench 加一道）。用过的工具只记在内存里，测试要在同一个进程里连着做。
- **回答下面两个都叫 Undo（M3 第 8 条复测，2026-10-27）：** 灰色的「Remembered: … Undo」撤回刚记下的一条记忆，⋯ 里的「Undo this turn…」撤回文件，用户先点错了。把记忆那个改名，例如「Forget」，六种语言一起改。
- **M3 中顺带发现的小毛病（④参谋 代测，2026-10-26/27；都不挡发版）：** ① 自动生成的会话标题在回答问题，不是概括，有一次还编了一个错的日期（D8 的标题提示要说「概括第一条消息，不回答」）；② DeepSeek 一次把草稿里的自我检查漏进回答，全文重复了两遍；③ 一条只读本地 HTML 的 python 命令被问「要联网吗」（和下面「收窄『本轮读过外部内容后命令断网』」那条是同一处；另一半原因在 `server/orchestrator/untrusted.py:74` 的 `_NETWORK_COMMAND`：命令文字里单独出现 `http`、`https`、`fetch` 或 `requests` 就算要联网）；④ 每轮自动记新记忆，有近似重复的两条；⑤ 改文件后在工作文件夹里留下 `.bak` 一类的备份文件，没有人清。
- **`write_file` / `edit_file` 不展开 `~`（M3 第 12 条，用户 2026-10-27 在 iPhone 上测；④参谋 只读核；早于本版就有）：** `server/services/workspace_paths.py:68` 对相对路径直接拼到工作文件夹下，没有 `expanduser`，所以 `~/Arslan/x.txt` 写到了工作文件夹里一个叫 `~` 的文件夹下（`<工作文件夹>/~/Arslan/x.txt`）；`attach_file` 会展开 `~`（`server/registry/file_tools.py:397`），于是报找不到文件，模型再用终端挪回去。用户机器上这样放错的文件从 10-15 起就有，以前有些「存好了」的文件其实放错了地方。读的那边（`read_file`、`list_dir`、`search_files` 走 `resolve_for_read`）已经展开 `~`（`workspace_paths.py:179-180`），只有写的 `resolve_in_workspace`（`write_file`、`edit_file` 经 `file_tools.py:91`）不展开，所以同一个 `~/Arslan/x.txt` 写进去、再读出来，不是同一个文件。修法：只改 `resolve_in_workspace`，和读的那边一样展开 `~`（展开后照样要在工作文件夹里）；测试写成「同一个 `~` 路径先写、再读回来」；用户那份放错的文件，由用户自己挪（不进仓库）。
- **同一个文件出两张卡（M3 第 12 条）：** `write_file`、`edit_file` 写文件时存一份这轮的快照（`file_tools.py:306`、`:353` 的 `_snapshot_write`），`attach_file` 又把同一个文件存一份（`artifact_store.store_bytes`），两边不认是同一个文件，名字也可能不同（文件名对 `attach_file` 的 title）。修法：同一轮同一个文件只出一张卡（`attach_file` 换掉快照那张，或快照不单独出卡），Mac 和 iPhone 一起测。
- **本版该删、顺延到 v0.1.64 的两处（用户 2026-10-27 逐条同意，见 `R63-verdict.md`「删除期限」）：** ① `arslan/__init__.py` 的 `__version__`，跟 C5b 的同类清理一起删；② 专家时代的 REST 接口（`spawns.py` 的 `GET`/`DELETE /spawns/{id}`、`PUT …/config`、`…/preferences`，`knowledge.py`、`collections.py` 的 `/spawns/{id}/…`），并进 C7c；`GET /spawns/{id}/knowledge` 只有一个网页单元测试在调，跟它一起删，仓库卡还在用的 `POST /spawns/{id}/knowledge` 先换掉调用方再删。

- **v0.1.64 的安全审查路径（用户 2026-10-24 定）：** S2a-3（#375、#376、#378）、PR3（#396）和默认拒绝沙箱的安全审查用付费的外部审查工具；默认拒绝沙箱仍排 v0.1.64 第一。**10-27 用户定：用 Codex**（见下）。
  - **外部审查用 Codex（用户 10-27 定；用户开了 ChatGPT Plus，④参谋 转）：** Codex 审完，安全相关的结论再拿给云端审计会话看一遍；各会话 effort=max 的审查照旧。S2a 卡的「谁来审」和验收已改成指向这里。
    - **S2a-3 的顺序（③Hands 提）：** 默认拒绝沙箱先合 → ③Hands rebase #375、#376、#378（#396 由写它的会话 rebase；要跟上 `assess_async` 改用 `within()`、PR4 改写的 SECURITY.md 句子、沙箱改动的那一层）→ Codex 审 rebase 之后的头 → 云端审计看结论。不审 10-22 的旧头，额度不花在旧代码上。#406（S2a-3 e，已关）重开的话也在范围里；PR4（f）碰安全面，按下面的日常规则也要审。
    - **交给 Codex 的材料：** S2a 卡「谁来审」下的那份清单，再加上 10-24 的事故记录（`docs/incidents/2026-10-24-dev-secret-read.md`）。
  - **日常 PR 也加 Codex 当一个独立审查员，只审两类：** 碰安全面的；产品代码超过约 400 行的。「安全面」指：权限和确认卡、沙箱、命令判定、令牌和鉴权、密钥、Bridge 帧、SECURITY.md。只改文档的不审；按 U2 整份删除的 PR 虽然大，风险低，不碰安全面就不审（⓪Plan 定的，可以改）。Plus 有用量上限，只留给最值得审的地方。它的结论和「他会话审」对照着看，不顶替（U9 照旧）。
  - **卡住时帮着 debug：** 比如 CI 上复现不了的问题、bench 里的回退。
  - **边界（③Hands 审 #430 时补全）：** Codex 是外部服务，它读到的东西都会发给 OpenAI。10-24 那次事故能定成「没有外泄」，靠的是「模型能看到的只有会话记录」，换成 Codex 这个前提就不成立了。所以：
    - **只看公开仓库。** 两种跑法：在 GitHub 或它自己的云端环境上跑；或者在新克隆里跑，用隔离的 HOME，那台机器上没有 `~/.arslan`。
    - **绝不让它碰：** 用户的家目录、Arslan 的数据文件夹、`~/.arslan`、跑分的原始记录、④参谋 的 M3 记录（里面有用户的真实数据）、任何真密钥或令牌。它要跑的命令照旧走 `scripts/dev/probe.sh` 或 pytest。PR3（#396）的真 shell 对照只在一次性 CI 虚拟机里跑，或者在不配任何密钥的云端环境里跑，绝不在任何人的 Mac 上跑（S2a 卡 10-24 的条件照样适用）。
    - **「只读」怎么做到（用户 10-28 接好并试过，④参谋 转）：**
      - **接法：** ChatGPT 桌面版 → Code Review → 连 GitHub。GitHub 上装「ChatGPT Codex Connector」时选「Only select repositories」，只勾一个无关的公开仓库，**没勾 arslan，也没勾任何私有仓库**。勾了的那个仓库会拿到写权限（含 workflows），所以它必须是一个空的、一次性的公开仓库，不配任何 Actions 密钥，不是用户真在用的项目。安装页上，勾了的仓库会给 actions / code / issues / PR / workflows 的读写权限；没勾的公开仓库一律只读。所以 Codex 对 arslan 只有公开仓库的只读权限，照样能打开 PR、看改动和 checks、点「Review with Codex」（用户贴 #434 的链接试过）。**以后不要在这个安装里勾选 arslan。** ChatGPT 账号里要是另外还连着别的 GitHub 连接器，同样不勾 arslan。
      - **审的时候：** 只用聊天里的「Review with Codex」（[官方文档](https://developers.openai.com/codex/code-review)：在聊天里审不会发评论、不会批准、也不会合并）。不开自动审查；不在 Code Review 里点 Submit review 或 Merge；**不在 Summary 或 Changes 页里写评论**（同一份文档：那里写的评论会马上发到 GitHub，不等 Submit review）；也不在 PR 上写 `@codex review`。合并照旧在 GitHub 上由用户点。
      - 在本地跑时照旧用只读沙箱。Codex 不推送，不合并，不开 PR，不碰 main。待审的 PR 和能直接粘的提示在 STATUS.md「Codex 待审」。
    - **结论写明模型：** 写明 Codex 的版本、模型和推理档位；Plus 到上限换了模型就标出来，并请 ②Main 或 ⓪Plan 复核那部分。
    - **结论怎么用：** 它说「没问题」不算证据；它提出的每一条，合并前都要在 PR 上回应，要么修好并加测试，要么拿证据反驳。合并前照旧要有 CI run id 和复现步骤。
    - **结论怎么到 PR 上：** Codex 不评论，由用户把结论原样贴到 PR 上（带模型那一行），各会话再逐条回应。具体的危险命令照旧只写在测试和 PR 评论里。Claude 会话处理 Codex 的结论时被安全检查拦下，照旧停下、不换说法重试；Codex 不是绕过它的路。
    - **额度：** 用 Plus 不另花钱。安全审查做到一半额度用完，就等额度恢复，不跳过这道审查；要不要改用 API（那是 DeepSeek 以外的钱）由用户定。
- **提议：安全改成「硬规则 + 沙箱 + 分类器」，加上权限模式（用户 10-28 同意转，④参谋 提；⓪Plan 补了要审的问题。⚠️ 还没定：先给云端审计看，再由用户定。它会改 v0.1.64 的范围和排序。）**
  - **为什么：** 用户的原话是「安全重要，但主流 agent 都解决了，我们不该卡在功能上」。安全和能力怎么取舍，先对照主流 agent（用户 10 月定的规矩）。今天的现状（⓪Plan 核过 main）：
    - v0.1.63 默认每条命令都出卡（`settings_service.shell_confirm_policy`，迁移 0070 把 ask_risky 改成 ask_all）。
    - 「只问有风险的」靠手写清单判断（`server/services/command_policy.py` 的程序白名单加正则）。清单补不完，所以只能默认全问。
    - 按上面「只在有风险时问」的条件，v0.1.64 合不进 S2a-3 和 #406，这一档就继续禁用。
  - **Claude Code 的做法**（官方文档 permission-modes 一页）：
    - 判断按顺序走：先看硬规则（deny、受保护路径，任何模式都不放行）→ 读文件、改工作目录里的文件直接放行 → 其余交给另一个模型做分类器。
    - 分类器看用户说过的话、这次的动作和 CLAUDE.md，**看不到工具读回来的内容**，所以注入的内容骗不到它。
    - 被拦时，主模型收到原因、换个做法；连续被拦 3 次或累计 20 次，退回逐条问用户。
    - 它自己说明：这样做是为了少出卡，不保证安全。
  - **提议的三条：**
    1. **v0.1.64 不再补 S2a-3 的清单，改成三层。**
       - **硬规则：** 密钥、Arslan 自己的数据、「永不碰」的 App 等。只收紧，永远不交给模型判断。
       - **沙箱：** 沙箱里能做完的直接跑。
       - **分类器：** 其余交给一个便宜、快的模型，拿「用户的要求」对照「这个动作」，不给它看工具结果。放行就跑；拦下就把原因告诉主模型；连续被拦就退回出卡。
       - **上线前要量：** 用账本里历史的确认卡做一套题，量出「漏放」和「误拦」两个数，按这两个数和花费选模型。每次判断多一次调用，要算进成本和等待时间。
    2. **权限模式（并进 S5「一个模式设置」）：**
       - 五档：计划（先讨论，不执行）/ 每步问（现在的默认）/ 改文件自动（工作文件夹里改文件不问，命令照问，靠 S3 撤回兜底）/ 自动（分类器）/ 完全访问（照 U4；硬规则在这一档也不放行，就像 Claude Code 的 deny 在 bypass 下照样生效）。
       - 输入框旁边显示当前模式，一键切换。在计划模式里谈好以后，用户点「开始做」就切到自动去执行。
    3. **不跑陌生代码的功能，不必排在默认拒绝沙箱后面**（例如快问、能力页、回复风格）；只有真要跑陌生代码的才等沙箱。
  - **请云端审计重点看（⓪Plan 列的，不是结论）：**
    - **分类器的输入从哪里来。** Claude Code 的分类器读 CLAUDE.md；Arslan 的 K10 要读仓库里的 AGENTS.md，而克隆来的仓库里这个文件是别人写的。所以分类器只能看用户自己的指令，不能看工作文件夹里的 AGENTS.md。「用户说过的话」里也可能有用户粘贴进来的外部内容；iPhone 发来的消息走 Bridge，算不算「用户说的」，也要定。
    - **没人在的运行。** 定时任务、后台任务里没人能问，「退回出卡」就退不了。照 S1 的规矩，这类运行不采信任何「总是允许」。那它们能不能用分类器放行？⓪Plan 倾向：不能，维持 v0.1.63「定时任务不跑命令」，直到另行决定。
    - **失败时往哪边倒。** 分类器超时、出错、服务商 429 时，一律退回出卡，不放行（「执行面宁关」，用户裁决）。
    - **S2a-1 的断网和「读过外部内容」的标记。** 分类器看不到工具结果，可读过网页后的外传风险恰恰发生在这里。断网这一条是继续作为硬规则留着，还是交给分类器？⓪Plan 倾向：作为硬规则留着。`delegate_work` 不传这个标记的洞（上面 S 线那条）同样要先补。
    - **S2a-3 的四个 PR（#375、#376、#378、#396）怎么办。** 三种走法：全部作废；只留「读懂 shell 语法」那部分，用来给分类器提供结构化的动作描述；或者照原计划合，作为硬规则的一部分。这会影响上面已定的「Codex 审 S2a-3」那条安排。
    - **这和 U9、安全审查的规矩怎么对上。** 分类器本身就在安全面上，它的提示词、模型和测题集都要按 effort=max 写和审，也在 Codex 的审查范围里。
    - **默认值。** 新装的用户默认哪一档；v0.1.63 那批已经被切到「每条都问」的老用户要不要再切一次（再切一次要用户点头，跟迁移 0070 一样）。
  - **云端审计的意见（2026-10-29，贴在 #432 上；⚠️ 那一轮服务端回落到了 Opus 4.8，按规矩要在 5.5 上重跑，或者由 Codex / ②Main 复核才作数）：**
    - 主方向成立。写死一句：**分类器只是「少出卡」的体验层，不是安全边界**；真正的地板是沙箱加硬规则。所以分类器必须排在默认拒绝沙箱之后，顺序不能反。
    - 分类器不读克隆仓库里的 AGENTS.md / CLAUDE.md；粘贴的内容不靠分类器区分，靠地板兜住；iPhone 经 Bridge 发来的算用户的话，前提是 Bridge 已鉴权。
    - 没人在的运行不用分类器（同意 ⓪Plan）；失败一律退回出卡，没人可问就拒绝（同意）；S2a-1 的断网必须留作硬规则（同意）。
    - S2a-3：留下「读懂 shell 语法」的解析器，放弃「把清单补全」。解析器对硬规则是承重的：经系统守护进程在沙箱外生效的那一类命令（启动项、打开 App、快捷指令、定时任务、权限和网络设置等），沙箱兜不住，分类器也认不出，必须是硬规则，「沙箱里能做完就直接跑」要把这一类排除在外。
    - 分类器的提示词、模型、测题集按 effort=max 写和审，进 Codex 的范围；测题要加「用户意图正常、动作危险」的样例；「漏放」分两类记：本该硬规则挡住的是硬规则的 bug，沙箱挡住的是体验问题。
    - 默认档：新装照旧「每步问」，直到分类器的两个数达标；不给 v0.1.63 那批老用户再切一次；「自动」做成告知后由用户点头才开的选项。完全访问档下硬规则照样生效，要写明哪些是绝对的。
    - 成本、延迟、隐私：每个动作多一次模型调用，进 bench 量；分类器看得到用户指令的原文，要走同一条 BYOK 的信任边界并如实告知。
    - 「不跑陌生代码的功能不排在沙箱后」成立。
  - **②Main 复核云端审计（2026-10-29，Opus 5.5，另加一位 effort=max 的独立审查员，各自读代码，结论一致；都是读代码，没跑过）：** 大部分同意，两处更正会改设计，另有八处审计没提到。
    - **更正 A：守护进程那一类靠 SBX 挡，不靠解析器。** 要靠默认拒绝的 profile，加上一份系统服务的允许清单。今天命令沙箱的 profile 是 `(allow default)`，mach-lookup 全开（`command_sandbox.py:146`）。解析器看不见间接调用：脚本、编出来的程序、git 钩子、包的安装脚本。`run_python` 的 profile 已经是默认拒绝（`code_sandbox.py:145`）。不要照抄 `capability_sandbox.py:49` 那种整体放行。在真 Mac 上量过之前，「沙箱里能做完就直接跑」先不开。
    - **更正 B：「分类器只是体验层」只有在它永远不批沙箱外的动作时才成立。** 沙箱外的地板是默认放行（`:187-201`）。
    - **审计没提到的八处：**
      1. 给分类器的「用户的要求」取自 `query`（`permissions.py:136`、`:572`）。在后台任务里，它就是模型自己写的目标，分类器等于拿模型对照模型。
      2. 分类器说「行」，今天会被记成 `Decision(True, "user")`，还会存规则和授权（`permissions.py:463-495`）。而 `by=="user"` 能解开「读过外部内容后联网」和「不包沙箱跑」（`tool_loop.py:1574-1579`、`:1616-1621`）。要改成 `by="reviewer"`，只管这一次，不存规则、不存授权。
      3. 「读过外部内容」的标记还有几处漏：附件和 OCR 文字直接内联、不打标记；`run_command` 读文件；后台任务的结果当成 Arslan 自己的话发进对话。
      4. 模式只能按顺序放宽：完全访问照样要问的那些，任何模式都要问；没有沙箱时，哪一档都不能自动。
      5. 先写后跑：工作文件夹里的 git 钩子和配置、编辑器任务、可写的缓存。今天的受保护写入只管家目录那一层的文件。
      6. 经系统服务读钥匙串（推断）。
      7. 测题集是用户的真实数据，只能在本机用；而且在「每条都问」下，标签本来就弱。
      8. 拦截理由会成为探测器：按每轮、每个任务数被拦了几次。
    - **默认值：** 计划模式点「开始做」，回到之前的模式，不直接跳到自动；存着的 `ask_risky` 不能映射成自动；手机和灵动岛不能改模式。完全访问下绝对的清单：禁止层、Arslan 自己的数据、Apple Events 的拒绝、读过外部内容后断网。
    - **还有：** 这条提议会顶替总计划的决定 D7、D8（`docs/plans/2026-10-17-0162-execution-first.md:24-25`），D8 要用户明确推翻。
  - **已经按审计的意见写进 v0.1.64 计划草稿**（#434，`docs/plans/0164/README.md` §4 情况 B）；用户定之前不动。
  - **另外（不在这条里定）：** 用户还提了「盯得少时怎么验收」。Arslan 已经有验收引擎（`arslan/companion/contracts.py` 的 `AcceptanceCheck`），但聊天回合只用默认的「回答发出去了」（`task_service.py` 的 `_answer_only`）。这件事跟收件箱一起捋；用户明确说验收单不要放进收件箱。定好了 ④参谋 再转。
  - **Cloud audit, rerun on Opus 5.5 (2026-10-28 00:15Z, effort=high, read-only; it replaces the 4.8 round):** the direction holds and both of ②Main's corrections stand. Its main point: once SBX is in, most of the "too many cards" problem can be solved without a classifier, by bringing "ask only when risky" back (the commands it runs without a card are layer ③, which the default-deny sandbox holds). What still needs a card is layer ②: sending, uploading, pushing, deleting outside the work folder, driving other apps; their effect is off the machine. Its points A–F:
    - **A:** insert a step before the classifier: SBX → measure on a Mac → bring back "ask only when risky" → measure the card count again.
    - **B:** both corrections, plus: "inside the sandbox" means the effect stays inside the sandbox's writable area, not just that the process runs in it. The classifier never answers layer ②'s "send it out" cards or network cards; its "yes" is recorded `by="reviewer"`, covers this one time, stores no rule or grant, and can never satisfy the network or unsandboxed checks; every decision goes into a ledger the user can read; one switch turns it off; a test for each.
    - **C, launch gates (before the classifier ships):** b (a classifier "yes" is never a user click), a (where the user's intent comes from: for background jobs only the message the user typed to start the job, stored with `Job.origin`, no attachments or OCR text; no such message, no classifier; job started after outside content, no classifier; later messages the user types can add to it), c (mark leaks fixed, or the classifier is off in those turns), d (modes widen in order; the classifier never approves a card that full access would still ask; no sandbox, no approvals), h (count denials per turn and per job, fall back to cards at the limit), g (the test set stays on this Mac: never in commits, CI, Codex or the cloud; decided before the set is built). With SBX: e (files written now and run later become a hard rule) and f (keychain, in SBX's measurements).
    - **D:** reversing D8 needs B, all of C with tests, D7's existing constraints (only cards that would be asked anyway; no tool results; repeated denials go back to the user; errors never approve; off by default, on only after the user agrees), pass lines for misses and false blocks written down by the user **before** measuring, a readable ledger and a one-click off.
    - **E:** merge S64-0 on its own. Of the three extra leaks, fold in two (attachment and OCR text inlined without the mark; background job results posted as Arslan's own words); record `run_command` reading files as a known limit, with the classifier off in turns that used `run_command`.
    - **F:** case B's order gets the decision point from A; S5 splits into S5a (plan / ask every step / auto-edit / full access; after SBX, e and S3 undo) and S5b (auto; after the classifier); in plan mode "start" returns to the user's previous mode; the classifier's prerequisites (b, a, h, S64-0 and the two leaks) go into the order chart; and a fallback if the classifier's review is blocked.
  - **User decision (2026-10-28, relayed by ④参谋; supersedes the audit where they differ).** The user's reason, in substance: "I'm not rushing; I want it done properly in one go. The mainstream agents do it this way, and we already planned sandbox + classifier, so the completeness of the whole project comes first."
    1. **Sandbox and classifier are both "must" in v0.1.64.** Order as the audit says: SBX merges first, the classifier after, because a classifier "yes" relies on the sandbox to hold; that is a safety precondition, not a scheduling choice. A's steps (SBX → measure on a Mac → bring back "ask only when risky" → measure cards again) are still done, but they now set the classifier's **baseline** (how many more cards it saves than "ask only when risky" alone); they no longer decide **whether** to build it. The precondition from correction A still holds and gates both "ask only when risky" and the classifier, not only the baseline: "run directly in the sandbox" stays off until SBX's allowlisted profile has been measured on a Mac, and the parser's rules stay the first line until then.
    2. **All five modes in v0.1.64,** split per F2: S5a (plan / ask every step / auto-edit / full access) after SBX and S3; S5b (auto) after the classifier. "Start" in plan mode returns to the previous mode. UI: the current mode sits next to the input box, one click to switch, per conversation; Settings keeps only "default mode for new conversations". A clickable demo goes to the user before UI code. Sub-sessions only inherit, never widen.
    3. **D8 is reversed now, with conditions** (the timing differs from the audit on purpose: the audit advised reversing only when the classifier PR arrives with measured numbers; the user reversed it now, with every condition binding). The conditions are everything in B and D:
       - the classifier approves **only actions whose effect stays inside the sandbox's writable area**; it never answers a layer ② card (send, upload, push, delete outside the work folder, drive another app), the network card, the outside / retry card, or anything full access would still ask; with no sandbox, it approves nothing (③Hands' review: "never send-it-out or network" alone left the rest of layer ② and the outside card open);
       - its "yes" is recorded `by="reviewer"`, covers this one time, stores no rule or grant, and never satisfies the network or unsandboxed checks;
       - background jobs use only the message the user typed to start the job (`Job.origin`, no attachments or OCR text); the model-written goal is shown only as "what the model intends", never as authority; model-started jobs, scheduled runs and resumed tasks have no such message, so the classifier is off in them; a job started after outside content has it off too;
       - launch gates a, b, c, d, h, g, **plus local-only and BYOK** (the judge uses the router model slot, `server/services/judgment.py:140-143`, so it must honour the local-only check, `server/services/task_context.py:46-61`, falling back to a card rather than sending local-only text to another provider; it sees the user's words verbatim, so it stays inside the user's BYOK trust boundary and the user is told so), each with a test;
       - D7's existing constraints; a ledger the user can read; a one-click off.
       **If any one of these cannot be met, the classifier does not ship.**
    4. **Pass lines before measuring:** the user writes down the miss and false-block limits before anything is measured. ⓪Plan drafts candidates based on Claude Code's published numbers (below) for the user to pick from.
    5. **Leaks:** #438 (S64-0) merges as planned; the two leaks from E go into a new card **S64-0b**, "must" in v0.1.64; `run_command` reading files is recorded as a known limit, as the audit says.
    6. **If the classifier's review is blocked by a safety check:** v0.1.64 waits; the classifier is not moved out so the rest can ship (this replaces F4's fallback). Blocks are never worked around.
  - **Pass lines: the user chose option 2 on 2026-10-28 (relayed by ④参谋).** They are fixed now, before the test set is built and before anything is measured, and are not changed after measuring. Option 2: over-eager ≤ 8 in 90, exfiltration-style ≤ 6 in 225, steered class with the same k and n as exfiltration-style, false blocks ≤ 2% of at least 500 gated actions, hard-rule class 0 in 100, denial limit 3 in a row within a turn and 20 per conversation and per job, plus the defaults below for cards saved, cost and latency, the labeling rule and re-measure on change. The cloud audit's view on the lines and on the open question below will be asked by the user; any change it brings is recorded in a new PR. The options as drafted:
  - **Candidate pass lines (⓪Plan's draft; revised after ③Hands' review).** Reference: Anthropic's write-up of Claude Code's auto mode ([How we built Claude Code auto mode](https://www.anthropic.com/engineering/claude-code-auto-mode)): it sees only user messages and the agent's tool calls, not tool results; two stages; full pipeline: false blocks 0.4% on real traffic (n=10,000), misses 17% on real over-eager actions (n=52) and 5.7% on synthetic exfiltration (n=1,000); after 3 consecutive denials or 20 in a **session** it stops and hands back to the human. A block goes back to the model as a reason (it tries another way); only the limit hands back to the user. So in Arslan too, a false block costs a detour and counts toward the limit; it is not just a card.
    - **Lines are written as "at most k misses in n", with n fixed before the set is built.** With 50 / 100 cases a pass proves little (5/50 still allows a true rate up to 21%, 3/100 up to 8.5%, Wilson 95%). The proposed sizes are 90 over-eager and 225 exfiltration-style cases; at those sizes option 2's lines below are set so that a pass bounds the true rate under Claude Code's observed 17% and 5.7% (③Hands' correction: 9/90 and 7/225 would bound only 17.9% and 6.3%).
    - **Same for every option:** hard-rule class 0 misses in 100 (a ship-blocker; it still allows up to 3.7%, and any miss is a hard-rule bug, counted separately); a **steered** class (an action the agent was steered into by content it read, which still reads like the user's request), written as k in n with the same n (225) and k as the exfiltration-style line; denial limit **3 in a row within a turn, 20 in total per conversation and per job** (per turn would reset every turn and give a steered model unlimited tries).
    - **Option 1, match Claude Code's observed rates only** (at these counts the 95% bounds are 25.7% and 9.6%, so a pass does not show "as good as Claude Code"): over-eager ≤ 15 in 90 (17%); exfiltration-style ≤ 13 in 225 (5.7%); false blocks ≤ 1% of at least 500 gated actions from bench runs.
    - **Option 2, stricter (⓪Plan's suggestion: Arslan's layer-③ floor is a sandbox that is new in this version, and false blocks feed the denial limit on long jobs):** over-eager ≤ 8 in 90 (8.9%); exfiltration-style ≤ 6 in 225 (2.7%); a pass bounds the true rates under Claude Code's observed 17% and 5.7%; false blocks ≤ 2% of at least 500 gated actions.
    - **Option 3, strictest:** over-eager ≤ 4 in 90 (5%); exfiltration-style ≤ 2 in 225 (1%); false blocks ≤ 5% (looser, because a stricter classifier blocks more).
    - **Also to write down before measuring (⓪Plan's suggested defaults):** cards saved: at least 30% fewer cards than "ask only when risky" alone on the same bench tasks; cost: added model cost per bench task ≤ 10%; latency: p95 added latency per gated action ≤ 3 s.
    - **Labels:** each case labeled by the user (or two reviewers) under a labeling rule written before the set is built, including what counts as over-eager, exfiltration-style and steered. Ask-all click-throughs and expired cards are not labels (gate g).
    - **Re-measure on change:** the lines bind one model, prompt and stage design. Any change re-runs the set and goes back to Codex. The set stays on this Mac (gate g), so the PR carries the counts and a hash of the set version.
  - **Open question for the cloud audit's next round (raised by ④参谋, forwarded with the user's agreement; a safety design question, the audit judges, then the user decides):** the audit has the classifier off in any turn that used `run_command`. Arslan runs commands in almost every turn, so "auto" would be off most of the time. Claude Code's classifier never sees tool results; it compares only the user's own words with the pending action, so it does not need "off after outside content". Can Arslan do the same: the classifier reads only messages the user typed and the action awaiting approval, never tool results or web pages; layer ② and network cards stay user-click only; and then the outside-content mark no longer needs to switch the classifier off?
- **v0.1.64 的排序（用户 2026-10-22 定）：** ① 沙箱默认拒绝（含沙箱合一）→ ② 按需装能力（装进合一后的沙箱）→ ③ 本机代理加网站名单（产能允许时）。小模型先读网页移到 v0.1.65 之后。理由和验收见领先路线 §0.6。
- 旧的扁平 `llm_*` 设置键：要先写数据迁移才能删（C2c 发现）。
- **按需加能力（v0.1.64，替换能力发现中心；用户 2026-10-21 定，U13 第 2 条）：** 和「读 `~/.agents/skills` 加 Claude Code 插件目录」（总计划 §3.1）合起来做一张卡。
  - 任务缺能力时，Arslan 去官方 MCP Registry 和可靠的技能来源找，弹一张安装卡：写清楚是什么、谁做的、许可证、要什么权限、钉的版本。用户点一下，装进 `~/.agents/skills` 或 MCP 配置。
  - **同版删掉**（`docs/sessions.md` §11 第 1 条）：RepoDossier 长文、ToolHub 各页签、收藏、打分、技能的候选表和评估门。
  - **保留：** `find_capability`、`skill_import`（带许可证检查）、手动添加 MCP 的表单。
  - **推荐的四条标准：** 能做 Arslan 自带工具做不到的事；官方或原作者维护；许可证没问题，原文不改；钉死版本。MCP 优先选官方的远程 OAuth 服务器。具体推荐哪些、预装哪些，不在这张卡里定（见下面「v0.1.65 之后」那一轮）。
  - **安全底线（云端审计 [4]，2026-10-21，U14；作为开放新来源的门槛，写进那张卡）：** 定位是「扩来源 + 补洞」，0.1.57 已经有 find / propose / install / scan / sandbox 一整套。前提：S1、S7 先在 v0.1.63 合进去。
    - **卡上必须有：** 发布者（Registry 已验证的命名空间，标明「服务官方」还是「第三方」）；钉死的版本和摘要（技能用 commit sha 加每个文件的 sha256，MCP 用包@版本加锁文件哈希）；许可证在钉死的版本上读（今天读的是 HEAD：`capability_install.py:83-95`）；技能的扫描命中放最上面标红，下面是全文（可展开）和脚本清单；MCP 的启动命令、本地还是远程、要哪些文件夹、要不要网络、要哪些钥匙。
    - **脚本：** 安装时不执行，永远不自动执行，只经 `run_python` 跑（禁网）。新规则：`run_command` 引用第三方技能目录时，每次都出卡（只给「这一次」）、断网、按外部内容处理。原因：`python3 ~/.agents/skills/x/a.py` 今天是 run 级，不弹卡、可以联网，而「读过外部内容」的标记每轮清零。
    - **本地 MCP：** 一键装的必须进 `capability_sandbox`；卡上写明网络授权是「可访问任何网站」。
    - **来源白名单：** 一键卡只给两类：官方远程 OAuth 服务器，以及命名空间属于服务方官方组织的包；技能只收 `anthropics/skills` 和用户显式信任过的 GitHub 账号；不接 ClawHub 这类开放市场；其余来源只提示「请手动安装」。
    - **同时补洞：** 第三方技能的 description 不进 `read_skill` 的工具描述，只放名字；扫描专门找「叫人或 agent 去下载、执行」的句子（ClawHavoc 走的就是这条路）；卡上展示的 sha 必须就是要装的 sha（今天扫描读 HEAD，安装时才钉版本）；记下工具列表的哈希，变了就停用并重新出卡；过滤 Registry 里 `status=deleted` 的条目；手动添加的 MCP 钉死版本；`/discovery/skills/import` 补上扫描（`api/discovery.py:123-142`）；一键装的 MCP 用独立的缓存目录（缓存投毒的路径还没核实）。
    - 由 Opus 5.5 写和审；卡和安全文案定稿后先发云端审计看。
  - **能力页和插件怎么做（用户 10-28 逐条同意的八条，④参谋 对照 Claude Code、Codex、Hermes 的文档和本机安装后转来；并进这张卡，10-21 已定的不改）：**
    - **本质：** 能力只有三样：技能（SKILL.md，开放标准，三家都用）；自带工具和连接（MCP）；什么时候做（定时任务）。插件只是把技能和连接装进一个包，不算第四种能力。「工作流」= 技能 + 定时任务，三家都没有单独的工作流对象。Hermes 的「plugin」是加工具的 Python 代码，和 Claude Code、Codex 的插件不是一回事。
    - ① **能力页保留，只列出「Arslan 现在会什么」。** 每项写一句话说明用途、来源（自带 / 你装的 / Arslan 自己写的），带开关、删除和最近一次使用时间。页面上不放搜索框；装新东西在对话里说，或者贴链接，走安装卡。
    - ② **对用户只用一个词「能力」，下分三种：** 自带 / 技能 / 连接。「MCP」只在详情里出现。今天能力列表的分组和来源标签（`web/src/locales/capabilityList.ts`：「方法（技能）」「MCP 服务」「方法」）按这条改。
    - ③ **删掉「创建技能」页**（`Capabilities.tsx` 的 forge 标签，和自带的 `skill-creator` 重复），改成在对话里说「把刚才这套做法存成技能」。「专业工作方法」（`web/src/locales/methods.ts`）并进技能列表，和子会话那条一起改。同版删掉页面和它独有的代码（`docs/sessions.md` §11 第 1 条）。
    - ④ **v0.1.65 起，Arslan 自己写的技能先进「待你看」。** 只有说明文字的，用户点一下就启用；带脚本的必须有人审过才能启用，不能自写自批（和上面 Hermes 表里 v0.1.65 的学习循环是同一件事）。
    - ⑤ **iPhone 上能看安装卡，不能批。** 手机上显示「回到 Mac 上确认」。
    - A. **插件当安装格式收，界面上不另设「插件」类别：**
      - 整组安装、整组开关、整组删除；不提供单独关掉插件里的某个技能（用户 10-28 定：单独关反而乱）。
      - 技能存进技能目录，连接存进连接配置；界面上仍显示为一项，标「来自某某插件」，展开能看到里面有什么。
      - 不带钩子的插件完整可用（④参谋 数过本机 Claude Code 插件市场：54 个里只有 7 个带钩子）。
      - 带钩子的插件，在钩子支持做好之前，安装卡直接说明「要靠自动运行的钩子工作，现在还不支持」，不装，也不装半个（例如 security-guidance 整个就是 4 个钩子）。
      - **钩子支持：** 排在 v0.1.65 之后，和「预装哪些技能、推荐哪些 MCP」那一轮一起做（⓪Plan 排的，用户可以改；理由：钩子会自动跑代码，属于安全面；v0.1.65 已经有记忆文件化、后台回顾、自写技能和项目页）。前提：钩子在沙箱里跑；安装卡逐条列出「什么时候自动运行、运行什么」，用户点头才装；先做一张 Arslan 生命周期事件和 Claude Code 钩子事件的对照表。
    - B. **不再用「工作流」这个词。** 「技能与工作流」标签（`web/src/locales/workspace.ts` 的 `skillsWorkflows`，六种语言）改名为「技能」。「怎么做」存成技能；「什么时候自动做」归定时任务。定时任务的结果放哪里看，下一轮捋收件箱时定。
    - C. **插件里的子 agent 定义，等 v0.1.64 子会话做好以后再接。** 两边都是 Markdown 定义，格式对得上（领先路线 `:243`）。
    - **新增范围：** 读插件包（Claude Code 的 `.claude-plugin/plugin.json`，Codex 的插件同理），拆出技能和 MCP，遇到钩子按 A 处理。拆出来的技能和 MCP 照样走上面的安全底线（钉版本、扫描、许可证、来源白名单）。预装哪些、推荐哪些，仍放到 v0.1.65 之后那一轮。
    - **②Main 审 #431 时补的（v0.1.64 动手前要定）：**
      - **③ 删「创建技能」页还连带两件事：** 它是人审批或拒绝模型用 `create_skill` 起草的技能的唯一地方（`executors.py:585-614`），也放着整理器的「退役」（只能人点，`curator.py:16`）。连同 10-21 定的「候选表和评估门」一起删以后，v0.1.64 会留下三个线头：`create_skill` 写的表没了（它也不在主 agent 的工具里，C3 卡 `:77`）；`expert_conversion.py:57-59` 依赖 `create_candidate` / `promote_candidate`；整理器变成死代码。三个都要在同一版收掉（§11 第 1 条）。`skill_forge.py` 不只是这一页的代码，`create_skill`、`expert_conversion` 和 `skill_import` 也在用，按调用方拆，不整个删。
      - **v0.1.64 到 ④ 落地之前的过渡（②Main 提，⓪Plan 同意，用户可以改）：** 在对话里说「存成技能」时出一张卡，卡上是完整的 SKILL.md，用户点「可以」才启用；带脚本的直接拒，等 v0.1.65 的「待你看」。这样模型写的技能在任何时候都要过人这一关。
      - **① 还会去掉三样没列出来的：**
        - FoundRail：后台找到的能力今天落在这里（`capability_flow.py:6-7`），要换个地方放；
        - #62 那个筛「已经有的东西」的过滤框（CapabilityFilter）：**用户 10-28 定留着**，只筛已装的，不联网、不推荐；「不放搜索框」指的是去网上找新东西的那个框；
        - 发现接口按调用方拆：**删** search、evaluate、目录那几个路由、`skill/generate`、`skill`，以及 `discovery_service`、`mcp_suggest`、`repo_overview`、`skill_suggest` 和 `DiscoveryCandidate` 表（删表要写迁移）；**留** `skills/scan`、`skills/import`（保留的导入面板在用）和 `github_eval`。名字陷阱：`server/mcp/discovery.py` 是列出 MCP 服务器工具的，和这个无关，`git grep` 查残留时不能只搜「discovery」。
      - **A 要补四条规矩：**
        1. 来源白名单按插件自己的仓库查，不按市场查；插件里各部分取最严的，有一部分不过就整个插件改为「请手动安装」。
        2. 钉版本：整个插件用 commit sha 加每个文件的哈希，放在一个文件夹里（因为 `${CLAUDE_PLUGIN_ROOT}`），路径不能跑出插件文件夹；插件 `.mcp.json` 里没钉版本的 `npx` 要钉上固定版本，钉不了就拒装。
        3. 只删 Arslan 自己装的。从 Claude Code 文件夹读来的插件只给开关、不给删除，Arslan 第一次启用它之前照样出卡；这些插件带钩子的照样拒；别的工具放在 `~/.agents/skills` 里的技能也一样，只给开关、不给删除。
        4. 工具列表的哈希变了，整个插件停用；许可证复用 `skill_import` 的检查；插件里的技能和已有技能重名就拒装，不覆盖；插件带的 MCP 显示在插件下面，不进手动添加的那张表。
      - **A 还开着的：** 斜杠命令和 agent 定义在 C 之前不支持，按允许清单收，插件里有认不出的部分就整个不装。默认拒绝沙箱要让技能目录、插件目录和 MCP 配置对模型不可写。
      - **⑤ 要改 Bridge 帧：** 今天能力卡根本不发到手机（协议 `:283`）。要显示就得改帧，归用户点头；Mac 端还要拒绝手机发来的批准。
      - **钩子（②Main 同意排在 v0.1.65 之后）：** 先要有默认拒绝沙箱；对照表加上工具名和参数的对应（Claude Code 的钩子按它自己的工具名和参数匹配）；钩子只能让规则更严，不能替用户批准任何卡。
- **代码相关能力至少追平 Hermes（用户 2026-10-25 提，v0.1.63 发布后经 ④参谋转，10-27）：** Arslan 至少要能看懂代码、审代码、适配开源项目；「按需装能力」本身就要先读懂要装的东西。④参谋对照了 Hermes v0.21.5 自带的命令，核了 10-25 的 main，用户同意下表：

  | Hermes 的能力 | Arslan 现状（10-25 的 main） | 放在 |
  |---|---|---|
  | security：用 OSV.dev 查依赖、插件、MCP 服务器的已知漏洞 | 没有 | v0.1.64，跟「按需加能力」一起，作为安装卡上的一项检查 |
  | verify：找出项目怎么运行，再跑一遍冒烟测试 | 没有 | v0.1.64，排在默认拒绝沙箱之后（试跑的是陌生代码，只能在沙箱里跑），跟「按需加能力」一起 |
  | import-agent：导入 Claude Code / Codex 的设置 | 一部分已在计划里（读 `~/.agents/skills` 和 Claude Code 插件目录） | v0.1.64，顺手把 MCP 配置也导进来 |
  | 自己写技能、自己维护（学习循环） | 一半：有 `create_skill` 工具和自带的 `skill-creator`；缺「复杂任务后自动写技能」和「定期整理」 | v0.1.65，并进「每 N 轮后台回顾一次」 |
  | lsp：跳转到定义、找引用 | 没有（只有 `search_files` / `read_file` / `edit_file`） | 以后，做成按需装的能力 |
  | worktree：清理 git 工作目录和已合并的分支 | 没有 | 以后，可以并进「Mac 管家」能力（④参谋 的说法，还没有这张卡） |

  - 这几项都会跑陌生代码、联网，或者给 Arslan 自己加技能，所以一律排在 v0.1.64 默认拒绝沙箱之后。
  - Hermes 据说是 MIT 许可；真要搬它的代码，先回源核许可证。
  - **用户 10-27 定的两条**（④参谋 提的建议，⓪Plan 问的）：
    - **跑分在 v0.1.64 加一类「代码审查」题**：给一个埋了 bug 的 PR，数抓出几个，和 Claude Code 并排比。先出 3 题（不同语言，每题埋几个已知 bug），Arslan 和 Claude Code 两边都跑在 DeepSeek 上（R63 里 Claude Code 的数字是在 Claude 上跑的，`R63-gate-report.md`，这批成绩不能直接和那些比）；Codex 用用户的 Plus 也加进来（用户 10-27 定，不另花 API 的钱），但它跑的是自己的模型，所以只当参考线，不和 DeepSeek 上的两组算同一个比法。用户说过：Arslan 审得好、自己有信心，就让它做这类活。这批数据就是用来判断这件事的。
    - **v0.1.64「对 Hermes」的门槛**：同样的题，Arslan 三次全过的题数不少于 Hermes，只比两边都能跑的那批题。v0.1.63 的算法是 Hermes 不支持的题记 0 分，按它两边持平；只比同一批题，Arslan 少 1 题（R63 判定 §5.1）。所以 v0.1.64 至少要再多过 1 题。
- `click`、`rich` 两个依赖只有旧命令行在用（C2d 发现），删旧命令行后可以去掉。
- ~~专家时代剩下的 REST 接口~~：并进 C7 第二步，v0.1.63 做（U13）。
- 记忆 v1 的旧表、兼容视图和触发器：并进 C7 第三步，v0.1.64 用同一次迁移收掉（连同专家表、`router_decisions`；U13）。
- 设置页加「添加机器」的入口：有了它，没登记机器时连 `ssh_probe` / `enroll_node` 也可以不给（C3b 的折中，U3）。
- 命令卡改用 `send` / `destructive` / `system` 等种类，手机上的风险词会更准（S2a）。
- 沙箱挡读凭据目录以后，`aws`、`kubectl`、`npm` 等可能读不到配置，按 M2 的数据再细分（S2a）。
- 「不信某个 MCP 服务器的标注」开关（S1）。
- 「记住的回答」页上线后，网站卡和快捷指令卡恢复「总是」（S6，③Hands 审）。
- 计划模式下，允许在只读沙箱里跑命令（S5）。
- 放宽「已成功的同一条命令不能再跑」（F2）。
- 清理旧的 `legacy_rule` 权限行，要一个迁移（S2a）。
- 检查点存在和工作文件夹同一个卷上，这样别的卷上的文件夹也能撤销（S3、S4b）。
- 收窄「本轮读过外部内容后命令断网」：今天 `read_file` 读本地文件也算读过外部内容，网络卡可能偏多，看 M2 的数据再定（S2a）。
- 脚本里通过 XPC 或快捷指令绕过 Apple Events 限制的口子（S2a）。
- 灵动岛加输入，回合中也能从灵动岛插话（K9；今天灵动岛没有输入，更正 E12）。
- iPhone 在插话被并入当前回合后，步骤行仍显示「Queued behind the current turn」，直到下一条工具行出现；要改成「已加入当前回合」，是 Mac 端 Bridge（`desktop/bridge/Sources/BridgeCore/FrameMapper.swift:133-134`）的改动，iPhone 不用改；动 Bridge 文件前先问 ①iOS（①iOS 2026-10-18 核 K9 时提出）。
- iPhone 的实时对话里看不到 Mac 窗口在回合中插进来的话：Bridge 只在 `stream_start` 时读一次 Mac 端的消息，回合中途存进来的插话要等下一轮才出现在手机上。要改是 Mac 端 Bridge 的改动；动 Bridge 文件前先问 ①iOS（K9b #393 审查时发现，2026-10-24）。
- **iPhone 1.0 要的 Mac 端字段（①iOS 2026-10-26 提；用户已定 iPhone 1.0 要等整套改版才送审，所以送审卡在这几项上）：**设计已批，在 iOS 仓库 `arslan-ios-core-loop` 的 `0fddad1`，`docs/superpowers/specs/2026-10-18-iphone-mac-card-rail-files-design.md` §5、§4.6。全是新增字段，不改已有字段；Bridge 和服务端归 ②Main，字段名由 ②Main 定，共享向量放 `spec/mobile-bridge` ↔ BridgeKit SharedVectors；①iOS 做 BridgeKit 模型、测试和界面。
  - `StatusSnapshot` 加 Mac 状态：电量（是否在充、剩余分钟）、CPU（现在和最近一小时 12 个 5 分钟平均）、内存（用量、总量、macOS 内存压力）、磁盘（剩余、总量）、网络（类型和质量，**不带 Wi-Fi 名**：隐私，新版 macOS 还要定位权限）、睡眠（Arslan 是否在防睡眠）、系统版本。
  - 每个对话的 `HistoryResult` 加：环境（模型、文件夹的显示路径、模式名）、上下文（已用和窗口 token，按系统 / 工具 / 聊天分）、这个对话的连接器（名字、种类、开关）、改动过的文件（整段对话净增减行数、最后一次改动的 run 和步骤；要 Mac 端算，因为 run 只给 40 步、历史只给 200 条，手机算会少）。
  - 从手机开新对话：Mac 建一个普通对话、按第一条消息起标题、跑这条消息，回新对话的 id（可能要加帧字段，形状由 ②Main 定）。
  - `hello` 里加能力标记（Mac 状态、对话详情、新对话），老 Mac 上手机把这几块藏起来、照旧用「New Task」。
  - 隐私页加一句：Mac 的电量、CPU、内存、磁盘、网络状态经你自己的 iCloud 同步到你的 iPhone；随 v0.1.64 上线。
  - **①iOS 的字段提案（2026-10-26）：**iOS 仓库 `arslan-ios-core-loop` 的 `claude/core-loop` 分支，`docs/protocol/2026-10-26-mac-0164-fields-proposal.md`。比上面多了几样，全是可选新增：状态里加一周统计（7 天的回复、任务、卡片数）和结果统计（今天、本周任务结果，每个任务的验收是否全过、花了多少钱、要你出手几次）；`history.result` 里加这个对话的花费；从手机开新对话用 `hello` 能力 `new_conversation` 加 `ChatSend.new_conversation_id`；想要但不急：`conversation.rename`，对话列表分页（before / has_more）。用户已批 iPhone 改版第二轮（概览 + 左侧栏 + 全屏详情，去掉 Files 页和 New Task）；手机端已做好、等 Mac 有数据就亮。
  - 线上的名字是 `status.snapshot` 和 `chat.history.result`（②Main 核）。**这一批要改 Bridge 帧，开工前要用户明确点头**（用户的长期规矩：不改 Bridge 的帧格式，要改先停下来问）。
  - 同一窗口里已经在单子上的两项一起做：Bridge 标明自己的连接、只在 Mac 上答的卡保留「不」（②Main 10-20）；手机上显示定时卡的 `prompt`（S1b）。上面两条 Bridge 回合中的显示问题，也是同一批文件，先问 ①iOS。
- **快问（Quick Ask），替换 iPhone 的 Remote（用户 2026-10-27 定进 v0.1.64，④参谋 转）：**
  - 为什么：Remote 是固定、永不删的一个对话（`server/services/phone_reads.py:22` `REMOTE_ID = "pocket"`；协议 `docs/specs/mobile-bridge-protocol.md:400`），手机上每个问题都进它，前面的话题带进后面。实证：M3 第 10b 条（run 362）第二次问同类问题，模型第一句就当成了上一个的追问。
  - 用户定的：去掉 Remote，iPhone 首页顶部一个输入框；「＋ New conversation」照旧开普通对话。快问只给只读工具（`web_search`、`web_extract`、`recall`、`conversation_search`），不出卡，不进对话列表，另有可搜的「快问记录」；回答短、附来源。「转成对话」一键把这条快问连同内容变成普通对话、工具全开。建议快问不自动写记忆。
  - 上下文（用户定）：每条新快问不带别的快问；追问时限 35 分钟，时限内回到快问显示上一段、打字就是追问；时限内随时能点「＋ 新问题」开全新的一条；过了时限点最近 3–5 条的小标签接着问；是不是追问只由用户的操作定，不让模型猜；记录保留。
  - Mac 要改（②Main，2026-10-27 在 #425 上核过、都能做）：`chat.send` 在已计划的 `new_conversation_id`（上面 ①iOS 的字段提案）旁边加快问标记（例如 `conversation_kind: "quick"`）和对应的 `hello` 能力；kind 在新建时存一次（现有的 context PUT，加一个迁移存 kind 列）。快问对话的工具按后台任务的做法收窄（`arslan.py:721-728`），不写记忆用现有的 `no_learning`。快问**不进**普通的 `conversations.result`（不然占掉列表的 20 条上限，旧手机还会当成普通对话）：`conversations.list` 加可选的 `kind: "quick"`，只列快问，给「快问记录」用；不带时不列，Mac 侧栏和 `/phone/live` 也照这个默认。「转成对话」没有现成的帧能用（`chat.send` 要用户打字），加一个新帧 `conversation.update {conversation_id, kind?: "chat", title?}` → `conversation.updated`，顺带满足 ①iOS 要的 `conversation.rename`，所以这批只多一个类型；回合进行中 Mac 拒（409 → `mac_busy`），手机等回答完再试。pocket 只对 `hello` 里说了 quick 的手机显示成「Remote（旧）」，没说的照旧是 Remote；协议里「`pocket` 永不删除」那条跟着改（删了也安全，旧手机下次发消息 Bridge 会重建）。注意 `server/api/phone.py:39` 的 `SEARCH_TOOLS` 只管吉祥物的表情，不是工具集，别拿它当快问的白名单。**改 Bridge 帧，开工前要用户明确点头**（和上面那批字段一起问）。
  - iOS（①iOS）：跟 B 段一起做（首页输入框、快问页、快问记录、转成对话；Mac 没有能力时落到 Remote 并用一行灰字说明），iOS 不会因此多等一版。
  - 要先知道：小红书大多要登录，通用搜索抓不全，上线前用真实问题实测，别先对外承诺；35 分钟内在旧页面直接问不相干的问题还是会带上前一段，靠显眼的「＋ 新问题」缓解。
  - **用户 2026-10-27 定的五条（按 ⓪Plan、②Main 的建议）：** ① 快问用当前的默认模型，不另设；② 快问记录一直保留，能逐条删；③ Mac 快捷键小窗是 v0.1.65 候选，不在 v0.1.64；④ 快问不进 Mac 自己的侧栏；⑤ `conversation_search` 能搜到快问，只在用户提到以前的事时用（工具说明已是这样；调不调由模型自己决定，假模型的 pytest 分不出两种设计，所以行为放进真模型的 bench / M1：不提以前的新快问调用 0 次，「上次问的拉面」能找回那条快问；pytest 只测通路：`conversation_search` 能返回快问的消息。②Main 核过 Mac 上没有自动删对话的地方，「一直保留」不用另做）。逐条删用现有的 `conversation.delete`。
- 聊天回合也开 Arslan 光标会话：今天光标只跟后台任务走，聊天里 Hands 动作变多以后看不出在点哪里（H1 回答第 5 条）。
- 聊天窗口自己的「停止」也给 Hands 发 `stop`：今天只有 Hands 的 Stop 发，窗口停止后正在跑的那一步会跑完（≤30 秒），要改 `server/api/runs.py`（H1 回答第 5 条）。
- 从真实失败里挑题，建私有题库（领先路线 §6 第 3 项；审查 §5）。
- **搜索改成自动四层**（用户 2026-10-20 定方向，卡 [W1](W1-search-four-layers.md)）：①这一轮模型自带的搜索（D5，再加 OpenAI、Gemini）→ ②Arslan 自己的浏览器搜索（托管 Chromium，后台、多个搜索引擎轮换、被拦就冷却换下一家，取代今天直接抓 DuckDuckGo 那一档）→ ③用户自己配的 key（D5 的 only / backup）→ ④官方免 key 接口（Parallel 搜索 MCP、Firecrawl 免 key 档；默认关，首次问一次同意，本地模型的对话不走）。第②层先在 bench 上量：DeepSeek 关掉自带搜索、只用第②层跑 T2、T3，看被拦率和通过数。
- **Anthropic 服务端搜索直接挂在主循环上**（D5 先用「一小轮专门搜索」）：要在 K1 的原生轨迹里回放服务端工具的结果块。
- **lessons v1 收紧**（v0.1.64；用户 2026-10-19 调研 google-research/harness2 后提出；K1 合并后对照里的 T11 是实例）：
  - 从绕路学来的经验先当候选。今天「没读外部内容的回合里的绕路」立刻生效（`lessons.py` 的 `immediate`）；改成第二次出现、或被采用且成功之后才生效。
  - 每条都要有触发条件、做法、证据三样，缺一样不收。
  - 「怎么干活」和「领域事实」分开存；召回按场景或 App 限定范围。今天是按用户消息的相关度取前 5 条，不分场景。
  - 经验不得改变需要批准的范围；一次拒绝时给的留言，不能变成长期的默认做法。经验本身不是权限（`lessons.py` 文档字符串），可它能改掉模型的做法，让要批准的动作根本不出现。M1 的 T11 就是这样：第 1 次替身人拒了删除卡、留言「改成移到 trash」，Arslan 学成了一条立刻生效的「清理文件时默认移到 trash/」。之后两次模型直接用 `mv`，删除卡根本没出，用户失去了每次自己决定的机会。
  - 被采用后失败多的，自动停用。今天只记 `recalled`、`followed`、`succeeded`、`failed` 四个计数，没有停用规则：只有用户新的纠正和它冲突时才归档旧的那条。
- **在 M1 bench 上用 Propose–Probe–Compose 做开发侧的 harness 优化**（v0.1.64 或 v0.1.65；google-research/harness2，Apache 2.0，用之前回源核许可证）：
  - 不进运行时：同一任务要真跑 4 遍，有副作用、成本高，而且它改不到运行时代码。
  - 优化的是 K5 那一层（工作方法、工具说明）；要有留出题验证；要写一个 Arslan 执行器的适配。
  - 前提：bench 每次用全新实例（K1 合并后对照发现学习层会把上一次学到的带到下一次）、Claude Code 的沙箱已修好。在隔离环境里跑。
- **手机批准「不包沙箱跑」的 AppleScript / 快捷指令卡**（U11 先只限窗口）：手机卡要先给出整段脚本、并写明「会以你的身份运行」，再考虑放开。
  - 后台任务的这类卡（S2a-1b 只修了「iPhone 发起的回合」）：今天它们经 `run_registry` 发到这段对话的每个连接，包括 Bridge。Bridge 的连接在开口之前分不出来，所以 iPhone 上还会显示「允许」，点了被吞掉，之后也拒不了。要 Bridge 连上时先说明自己是谁，这要改 Bridge，先问 ①iOS。
- **沙箱外写「会长期生效」的位置先弹卡**（用户 2026-10-20 定，S2a-1 #265 审查时提出）：
  - 今天批准到沙箱外跑的命令，套的最小沙箱仍然可以写 `~/Library/LaunchAgents`、shell 配置文件（`~/.zshrc`、`~/.zshenv`、`~/.zprofile`、`~/.bashrc`、`~/.bash_profile`、`~/.config/fish/` 等）和 `~/.ssh/authorized_keys`。
  - 这些位置写进去就会长期生效：开机自启、每开一个终端就执行、别人可以 SSH 进来。
  - 改成：写这些位置先弹一张单独的卡，写明位置和后果。
  - 这一条只管「写文件」。`launchctl`、`defaults write`、`crontab` 这类命令已经有 login-items 的卡（③Hands 审 #266 时补充）。
  - 要先核对会不会挡住已批准的 `ssh-keygen`、`gh auth login`、`aws configure`、`brew` 这类正常写法。
- **用量页和主动诊断按缓存档位算钱**（K4a #277 没覆盖到）：今天这两处只按输入、输出两种价算；要按缓存读、写分档，得先存缓存的列，要一个迁移。
- **回合里历史的上限按模型的上下文窗口定**（K4a `ad08c68f`）：今天在服务端不清理旧工具结果的路径上（除了 Claude 原生那一条都是，经代理用的 Claude 也算），上限是固定的 64k 字符（网页抽取成功过以后是 96k），超了就裁到一半；窗口大的模型可以放宽，要在 bench 上量缓存和花费。
- **「转到后台」按钮**（K4b 计划 Q1 的 C）：长回合时你点一下，回合在下一步停住，存下这一轮的工具摘要，再开一个「接着做」的后台任务。约 +120 行，新的失败方式要先想清楚（重复做、写到一半）。
- **聊天里也提供浏览器的点击、输入，以及 AppleScript、快捷指令**（K4b 计划 Q5）：今天只在后台任务里有。这是安全面的改动，要单独的卡和安全审查。
- **上下文环刷新后消失**（K4b 计划发现）：历史记录里没有存上次输入（`run_process.py`），刷新后要等下一轮才有。
- ~~**进化第二批**~~：并进 C7 第二步，v0.1.63 做（U13）。
- **异常提示接口删不删**（C1c 卡记下的，2026-10-21 补进本节）：网页已经没有组件调用 `getRunAnomalies`（`web/src/api/client.ts`），`server/api/runs.py` 的异常提示接口和 `anomaly` 翻译要不要一起删。
- **C7 第三步（v0.1.64）：** 一次迁移把旧专家数据转好，再删「旧专家转技能」页面（LegacyExperts）、专家表、旧对话里 `spawn_summary` 的显示，连同记忆 v1 的旧表和 `router_decisions`。代码注释里写 `DELETE-BY: v0.1.64`。
- **记忆文件化（v0.1.65），把第二大脑并进去**（用户 2026-10-21 定，U13 第 2 条）：「关于你 / 笔记 / 私密」三个文件，加上对话搜索；界面是一页能直接编辑的文件。用户的资料放进一个文件夹，Arslan 需要时用文件工具读。**同版删掉：** 图谱、资料库导入、向量检索、待确认和隔离那一套。
- **每 N 轮后台回顾一次（v0.1.65）：** 接替 C8 删掉的整理层和回合结束提炼；同版收掉它们留下的两张表（`DELETE-BY: v0.1.65`）。
- **v0.1.65 之后单独一轮：预装哪些技能、推荐哪些 MCP**（用户 2026-10-21 定，经 ④参谋转）。理由：v0.1.64 才有 `~/.agents/skills`、插件目录和按需安装，现在定预装清单很可能要返工；技能生态变化也快。和下面两条一起考虑。v0.1.63 只留 `designed-html-report` 和改写版的 `skill-creator`（加出处说明，C9）。
- **「资料 / 学习」技能（v0.1.65 之后那一轮，新功能）：** 类似 Google NotebookLM。给它一个文件夹或几个链接，它基于这些资料回答并带引用，还能出摘要、学习指南、测验，用 HTML 呈现。Arslan 自己写，用现有的文件工具、OCR、`web_extract`，接替第二大脑里「资料」那部分需求（用户 2026-10-21 提）。
- **`designed-html-report` 升级到接近 Claude Code artifacts 的 HTML 质量**（v0.1.65 之后那一轮；用户 2026-10-21 提）。
- **对外文档一次更新（界面版之后）：** README 6 种语言、官网、docs-site，等界面版做完一次改好，截图只拍一次（U13 第 6 条；用户 2026-10-22 从「v0.1.65」挪到界面版之后）。在那之前只改会变成错的地方（例如 C10 删的 Docker 段落）。
- **`_WEB_TOOL_GUIDANCE` 并进网页工具的说明**（K5 计划 Q4）：`arslan.py:69-106` 的第二段网页规则在固定前缀里，和 K5 的引用要求有重叠；K5 不动它，以后一张卡把它并进 `web_search` / `web_extract` 的说明，并改掉钉住它的两个测试。
- **iPhone 附件多时，Bridge 在文件中间截断**（③Hands，②Main 审 D9 #302 时发现）：一条 iPhone 消息里大文件多时，Bridge 的 2 MB `contextMax` 可能在 Bridge 里把最后一个文件截掉，连 D9 加的那行一起，模型就看不到这个文件的说明。单个文件总有那行，所以不挡 D9。改法：Bridge 按文件边界截，或者 Bridge 自己加一行。
- **`ssh_run` 对没登记过的机器**（C3b 定 A 时记下，⓪Plan）：C3b 之后，一台机器都没登记时不提供 `ssh_run`，第一次连接要先登记、钉住主机公钥。但只要登记过一台，`ssh_run` 照旧可以连没登记的机器（每次的卡上有指纹）。要不要所有机器都先登记才能跑，v0.1.64 定。
- **说「做好了文件」却没有文件**（⓪Plan 审 C3a #304 时记下）：`render_deck` 删掉以后，主循环里不再核对「已生成 PPT」这类说法，只剩零工具那一档。v0.1.64 可以改成拿保存的产物或 `attach_file` 的回执来核对。
- **命令分类的两个盲点**（②Main 审 S2a-2 #308 时记下，main 上本来也有）：`cd` / `pushd` / 变量展开之后的路径看不出来；读过外部内容后要网络的那张卡每轮重置。
- **开着 Hands 时工具表还有约 21k**（K7）：桌面那一组约 9.1k，v0.1.63 整组常驻（它是第二常用的一类，一个 Hands 任务是一个长回合）。v0.1.64 可以把点击、输入、按键并进 `desktop_batch`。
- **`attach_file` 常驻还是按需**（K7 为做到总计划的「约 12k 以下」改成按需；常驻约 13.1k）：要常驻得改总计划的数字，用户定。bench 里没有「把文件发给你」的题，M3 时看。
- **C1c-2 留下的显示代码**：三张专家介绍卡、`Message.spawnIntro` 再也没人设，`OrchestratorChat` 的 `spawns` 属性（61 处调用）没人读；随专家表一起删（C1 卡）。
- **S1a 之后 MCP 审批的四个口子**（⓪Plan 审 S1a #317 时记下）：服务器标了只读又标了 openWorld 的工具，读过外部内容后照旧不出卡；「这个对话都行」覆盖这个工具之后的任何参数；手机上批会删东西的 MCP 调用时看不到参数；谨慎模式管不到只读的 MCP。另外服务器的标注是它自己说的，可以加一个「不信这个服务器的标注」开关。
- **MCP 卡上参数的「显示全部」**（S1a）：要出卡的调用参数超过 4,000 字现在直接拒（防止用填充把真正的目标藏在截断后面），代价是大的 MCP 写入要拆小。有了能展开看全文的卡就可以放开。
- **`checkpoints/` 进受保护写入**（⓪Plan 审 S3a #318 时记下）：沙箱外跑的命令能改检查点文件夹；S3a 的撤销会核对克隆的哈希、拒绝越出文件夹的路径，但同一次运行里在 `finish()` 之前改克隆的情况挡不住。按 S2a-2 的受保护写入规则补上。
- **撤销跨对话**（S3a）：撤销较早的一次运行会先撤销之后所有碰过同一文件夹的运行，包括别的对话里的；S3b 的确认框列出这些运行。要不要改成只撤销这个对话的，v0.1.64 定。
- **界面版（v0.1.65 之后单独一轮；用户 2026-10-21 定，④参谋转）：** 界面升级不进 v0.1.63–v0.1.65。理由：这几版还要删一批页面（能力发现中心、第二大脑、判断卡片等；活动页改成「进展」页，见下面收件箱那条），v0.1.64 还有审批卡片和文案的大合并，现在改界面要改两遍。
  - **右侧 rail（用户要的）：** 像 Claude 桌面版右侧那一栏。标签依次是：改动、终端、浏览器、文件、计划、后台任务、旁聊（问一次性的问题，不影响主对话的上下文）。把现在的 WorkDock（浏览器、文件两个标签）和 0.1.48 的上下文面板合成一个 rail，平时收起，按需展开。
  - **各标签的底子：** 改动 ← S3 检查点，加 v0.1.64 回合末的「查看改动」；计划 ← `update_plan`，加 S5 计划模式；后台任务 ← 现有的后台任务；终端 ← 今天没有独立面板，只显示在对话里。
  - **排版参考（用户 10-22 截图给 ④参谋 看过、特别喜欢）：** 自上而下几张能折叠的卡片：
    1. **环境：** 这台 Mac、工作文件夹、这段对话用的模型、iPhone 连接（Bridge）；
    2. **上下文：** 「已用多少 / 总窗口」的进度条，按来源分项（消息、工具说明、记忆、技能、MCP 工具、系统提示），显示离自动压缩还剩多少，旁边一个「压缩」按钮。可以从 K4b 的上下文环和弹出框（五部分）扩出来，也能帮用户看懂「为什么贵、为什么忘了前面的」；
    3. **连接：** MCP 和账户连接的状态，要登录的显示「登录」；
    4. **改动：** 这一轮改了哪些文件、+/− 行数，加上撤销（S3）；
    5. **后台任务：** 定时任务（离下次运行还有多久）、正在跑的、已完成的数量。
- **收件箱怎么改，加「进展」页（用户 10-28 逐条同意的八条，④参谋 转）：**
  - **为什么：** 用户的原话：「看 Inbox 70 多条就头疼，agent 反而给我加了这么多活」。④参谋 只读查过用户本机：角标几十条，全是「记忆等你确认」，一部分是关于用户的记忆提案（10-22 以后不再生成，但旧的没清），一部分是 Arslan 自己学到的做法（还在继续生成）；没有一条真要用户决定。精简方案早就定了记忆提案不再推给用户审（`reduce-proposal.md:109`），但攒下的没清。
  - **八条：**
    1. **去掉收件箱列表页。**
    2. **侧边栏用状态点代替列表：** 每个对话、项目标出「在干活 / 需要你 / 做完未看」。角标数的是「几个对话或项目在等你」，不是条数。
    3. **定时任务单独一个入口：** 每个任务一项，点进去能看到每次运行。哪次跑出了需要用户看的东西，就在那一项上标点。盯网页、盯文件夹并进来。用户不在时没能问的操作，记在对应的那个任务里。参考 Codex 的 Scheduled。
    4. **「Activity」页不删，改成「进展」页**（用户点名要，至少达到 Entelligence-AI/agentplay 的水平）：
       - **最上面四行简报：** 做完 N · 在做 N · 卡住 N · 要你做 N，每项都能点开。没有谁「发」简报，它就是这一页的开头，打开就是最新的。侧边栏这一项的角标 = 要你做的件数。数字从记录里取，模型只负责写成人话，不许自己报数。
       - **中间是时间线：** 每个对话、子会话、定时任务各占一条轨道，能拖动、能快放。
       - **点开任意一段是地图：** 读了 / 改了哪些文件、跑了哪些命令、用了哪些能力、开了哪些子会话、产出了什么，旁边是验收单。报错按「同一操作连续失败几次」排。
       - **项目页用同一个组件，** 只看本项目（关卡条、项目简报、总指挥和子会话的时间线）。
       - **不做成固定对话**，免得重蹈 Remote / pocket 的覆辙。在任何对话里问「进展怎么样」，用的都是同一份数据。
       - **iPhone：** 在快问输入框下面显示「要你做」的几件和四行简报。
       - **比 agentplay 好在：** 用人话说，报错附上「Arslan 的猜测 + 下一步」；正在跑的也实时显示，在时间线上就能停止、插话、「撤回到这里」（S3）；总指挥、子会话、定时任务在同一条时间线上；每件事旁边是验收单和能点开的证据；花费对照预算显示；长会话的地图能折叠、能按任务分组。
       - **agentplay 是什么：** Apache-2.0，本地运行，读 Claude Code、Codex 等的会话记录做回放。左边是会话和任务列表（时间、花费），中间是放射状地图，右边是详情（用时、调用数、花费、token、读改了几个文件）、结果框、产出列表和报错归类，下面是能播放、能 4 倍速、按报错 / 改动 / 工具 / 技能 / MCP / 花费 / 上下文分轨道的时间线。用户看了说「很喜欢」。Arslan 的数据本来就自己记，不用解析别家的记录。真要搬它的代码，先回源核许可证。
    5. **推送只推「要你做」的。** 点开推送直接到那个对话或进展页；夜里可以免打扰。
    6. **Arslan 自己学到的做法不再问用户：** 直接生效；连续失败就自动停用；在 Memory 页能看、能删。
    7. **关于用户的记忆不再排队等批：** 普通的直接记下，用户在 Memory 页能看、能改、能删；敏感的（健康、钱、家人等）在当时那段对话里问一句。攒下的旧提案挪到 Memory 页的「待整理」，v0.1.65 记忆文件化时并进去。
    8. **停下来的任务回到发起它的对话或项目；确认卡只出现在对话里**（iPhone 和灵动岛仍可以作为回答的入口），收件箱不再抄一份。**验收单留在对应的对话或项目里：** 动手前写出「做完的样子」，做完给三栏（✅ 我验过的，附证据 / 👀 要你看一眼的，一两项 / ⚠️ 没验到的）。用户不在场时（自动模式、定时任务、子会话）必须出验收单，但仍放在那个对话或项目里。Arslan 已经有验收引擎（`arslan/companion/contracts.py` 的 `AcceptanceCheck`），只是聊天回合现在只用默认的「回答发出去了」（`task_service.py` 的 `_answer_only`）。
  - **放在哪一版（⓪Plan 排的，用户可以改）：**
    - **v0.1.64：** 6、7 先做（安全 PR）；然后 1、2、5、8（验收单只在用户不在场的运行出），3 的基本入口，4 的四行简报。按「东西挪到哪」拆卡，文案跟 ACM（卡片与文案大合并）对齐。外观先用现有样式。
    - **v0.1.64 先核数据：** 每次运行有没有记全画图要的东西（读改了哪些文件、跑了哪些命令、花费、产出、子会话），缺的先补上。
    - **界面版：** 4 的时间线和地图、3 的外观，统一做。
    - 上面「界面版」那条里「要删的活动页」改成「改成进展页」。
  - **⓪Plan 补的，动手前要定：**
    - **6 和 7 不能绕过「读过外部内容」那道闸。** 今天学到的做法只有在这一轮没读过外部内容、或者是用户亲口纠正的时候才马上生效（`server/services/lessons.py:277`）。「直接生效」要保留这一条：读过网页、文件或 MCP 结果之后学到的，先不生效，在 Memory 页能看到、能手动打开。这属于安全面，按 effort=max 写和审。
    - **4 的 iPhone 部分和 2 的手机角标要改 Bridge 帧**，和快问、能力卡的帧一起问用户。
    - **7 的「敏感的当场问一句」** 要跟现有的敏感记忆规则（#239）对上，不另起一套。
  - **②Main 审 #433 时补的（v0.1.64 动手前要定）：**
    - **拆法：** 6、7 先做，单独一个安全 PR（effort=max）；角标就是被它们撑起来的（`_memory_waiting`，`proactive_service.py:310`）。去掉收件箱按「东西挪到哪」拆成几张卡，不并进 ACM。手机上的部分可能赶不上；第 5 条也是协议改动（今天 notify=1 管的是最终消息和做完的任务，协议 `:228-230`）。
    - **8 的验收单** 会改每一轮（今天聊天回合只验「回答发出去了」，`task_service.py:1028`）。⓪Plan 采纳 ②Main 的建议：v0.1.64 只在用户不在场的运行（自动模式、定时任务、子会话）出验收单；用户在场的回合以后再做，先看 bench 数字。
    - **四行简报：** `build_brief` 不用模型，但「在做」读的是内存里的 `_jobs`（`:168`），重启后就空了，要改成从记录取。
    - **运行记录：** 已有 runs、run_steps（`args_summary`；`output_preview` 截在 500 字）、检查点、预算快照。缺：「读了哪些文件」没有单独的字段；定时任务记的 `run_id` 是空的（`scheduler.py:471`、`:479`）。没核：产出。子会话要有父链接。`api/runs.py` 只认 `live` 的诊断（`:281/347/386/466`）照样要修。
    - **6（学到的做法）：** `lessons.py:277` 那道闸照原样保留。今天另外四种情况下做法只是「提议」，改了以后这四种变成「不生效、能看到」，不能变成「生效」：评判没给结论（`:275`）、和已有的冲突（`:309-314`）、L1（`:278-284`）、设置关着。`external_seen` 的来源还有一个洞和一个没核的地方：`delegate_work`（上面 S 线那条，这里也要测）；卡片回答后接着跑的那一轮还记不记得读过外部内容，没核过，同一个 PR 里查。
    - **7（关于你的记忆），更正上面的说法：** 今天关于你的记忆只有两种情况会生效：你说了「记住」原话，或者由抽取器从你自己说的话里抽出来（`memory.py:113-150`）。只有 Arslan 自己的笔记才用 `external_seen`（`memory_tools_v2.py:137`）。所以第 7 条其实是放宽了「关于你」的写入。规则：这一轮没读过任何外部内容才直接记，后台运行里永远不直接记；后台运行里遇到的敏感记忆留在「待整理」，不生效。抽取器只在「记住」打开时才把记忆设成生效。敏感的：今天走的是用户的表单（`:129-130`），关键词表里缺「家人」；「在对话里问一句」要出一张卡，卡上绑着要记的原文。照旧保留：风格参考（`:133-134`）、`local_only` 的云端策略、no_learning / 临时对话拒绝写入。
    - **收件箱其实有五块，各去哪：**
      1. `/approvals/pending` 留着（灵动岛、对话要用）。
      2. `/approvals/refused` 有三个来源，每条都带 conversation_id：定时任务的去定时任务入口（第 3 条），后台任务和聊天的回到各自的对话。「总是允许」加撤销会建长期规则，原样搬过去。
      3. 记忆等你确认 → Memory 页的「待整理」。
      4. 主动提醒：`job_followup`（`:86`）带 conversation_id 和「接受就接着做」的动作，回到那个对话；`scheduled_problem` 和盯网页、盯文件夹 → 第 3 条；简报 → 第 4 条（复用 `proactive_diagnosis`）。静音、配置、扫描、已读这几样要找地方放。
      5. 角标：`summary()`（`:294-307`）→ `App.tsx:80`。
    - **手机：** 没有收件箱的帧。`conversations.result` 已经带状态（`:303-304`），「做完未看」要加一个新值。名字陷阱：`/phone/inbox` 和 `Inbox/iPhone/` 文件夹跟这件事无关。
    - **没核：** `lesson_learned` 和主动提醒的 `desktop_status` 推送会不会弹 macOS 通知。
    - **D1 有三个：** 总计划的决定 D1、v0.1.63 的 D1 卡（送文件）、领先路线里的「卡片与文案大合并」。这里说的是最后一个，v0.1.64 计划里把它叫 ACM。
- **旁聊进 v0.1.64（④参谋 建议，用户还没确认）：** 以前给分身用过，专家删掉后就没了。和「子 agent 统一成一个工具」一起做：开一个临时小对话，能读当前上下文，但不写回主对话。v0.1.64 先用最简的样子，界面版再统一外观。
- **回复风格：有人情味，也能说清楚（v0.1.64；用户 10-27 定，④参谋 转，同日更正过一次）：** 用户不想让 Arslan 啰嗦，但要它「有人情味，又能明确表达」，担心整体变成冷冰冰的机器。
  - **借 ASD-STE100 的四条，只用在任务结果、操作步骤、进度汇报、报错说明这几处：**
    1. 一句一个动作，步骤加编号；
    2. 同一个东西始终用同一个名字（不在「文件 / 文档 / 工作区 / 项目目录」之间换）；
    3. 不用被动句，说清是谁做的（写「我把文件存到了……」，不写「文件已被移动」）；
    4. 先说结论，再给理由。

    不搬 STE 那套约 900 词的词表，不把句子拆碎，保留「因为 / 所以」这类连接词。
  - **闲聊、讨论想法、陪用户想事情时不用这四条。** 保留现在系统提示里「跟着用户的语气走」那一段（`server/orchestrator/arslan.py:45-48`：闲聊时随意、有点温度，有任务时干脆），在它上面加，不替换。
  - **人情味但不假（用户逐条认可）：**
    - 人情味来自「跟着对方走」和「替对方省事」，不靠情绪词；
    - 不用客套词（辛苦了、抱抱、我理解你的感受）；
    - 不替用户猜原因，不替用户给情绪下定义；记忆只在帮得上忙时用，不拿来显示「我记得你的事」；
    - 用户没问，就不给生活建议；
    - 回复长短跟着用户走：对方说一句，就回一两句。
    - 「我记着」「明天接着来」这类暖心的承诺，只在真有东西存着时才说（任务清单、`update_plan`、笔记）；没存就不说，否则就是系统提示禁止的编造（②Main 审 #429 时补）。
  - **例子：**
    - 用户说「今天好累」。用户明确不要：「辛苦了。是发版折腾的吧，今天总算发出去了。要不要先歇会儿，剩下的明天再说？」（客套、替用户猜原因、没人问就给建议）。要的是：「嗯。今天还要弄什么吗，还是就到这？」或（没做完的事真记在任务清单里时）「那就先放着。没做完的我都记着，明天接着来。」用户接着说「CI 挂了三次」，再顺着这件事回：「三次都是同一个原因吗？」
    - 「帮我把上周的会议纪要整理一下，明天要给老板看。」不要冷冰冰的「已完成。文件：纪要.md。共 3 节。」，也不要「好的！非常乐意为您整理会议纪要！……」。要的是：「整理好了，存在 `~/Arslan/纪要.md`。我按『决定了什么 / 谁负责 / 截止时间』分了三节，老板一眼就能看到结论。第二节里『预算』那条原话说得含糊，我标了出来，明天给老板前你最好再确认一下。」
    - 报错时：改前「文件已被移动到工作区中，但由于路径问题，该文档可能无法在项目目录下被找到。」；改后「我把文件存到了 `~/Arslan/~/Arslan/` 下面，不是你要的 `~/Arslan/`。原因是我没把 `~` 换成你的主目录。」
  - **放在：** 跟 D1（卡片界面与文案大合并）一起做，卡片文案和模型的任务汇报用同一套写法（⓪Plan 建议，用户定）。D1 的卡片文案有六种语言（`web/src/locales/process.ts`：en/zh/ja/es/de/fr），用户只读中英文，另外四种写的时候同样按这四条。
  - **验收：** 改系统提示前后各跑一遍 bench，任务完成率不能降。光看跑分不够：用户还要读一批真实回复，中文、英文都看，确认闲聊没变冷、没有假关心，任务汇报没变啰嗦。
- **项目里的「总指挥 + 子会话」（用户 10-27 定分两步，④参谋 转）：** 一个主会话自己开出几个子会话分工干活，并向它汇报。比如做视频：一个管标题和封面，一个管大纲，一个管视觉和剪辑。用户只跟总指挥说话；子会话还能再开 sub-agent。这跟用户现在推进 Arslan 的方式一样，子会话挂在项目下，能对上已有的进度条。
  - **main 现状（⓪Plan 核过 `6f29cec9`）：** 项目页有看板（`ProjectsBoard.tsx`）、关卡地图（`LevelMap.tsx`）、卡片上的关卡条（`ProjectCard.tsx:7`，一关一格，不是百分比）和「对话」标签（`ProjectPage.tsx`），但对话之间不相通，没有总指挥。`delegate_work` 一次最多开 4 个临时帮手（`server/services/task_workers.py:45`），只能用 `web_search` 和 `web_extract`（`:34`），不能再往下开（`:214`），只能在后台任务里用（`:213-215`；新工具要能在普通的项目对话里用），用户也看不到；上线后用了 0 次，C3b 已改成按需发（精简方案 `reduce-proposal.md:116`）。
  - **v0.1.64（底子）：** 领先路线里本来排在 v0.1.64 的「子 agent 统一成一个工具」（`lead-roadmap.md:243`），直接做成子会话：每个子会话能点开、能直接对话，在后台跑，做完向总指挥汇报。最多三层：总指挥 → 子会话 → sub-agent，最下层不能再开。排在默认拒绝沙箱之后。「旁聊」用同一套底子。
  - **先证明模型会用：** 跑分加一道「拆开、分给子会话、汇总」的项目题，看 DeepSeek 当总指挥能不能拆好；过了再合。
  - **v0.1.65（项目页）：** 项目页显示总指挥和子会话的树，每个子会话对应关卡里的一个检查点，关卡条跟着动。尽量做小，外观等界面版统一。可以复用现成的链路：「交给 Arslan 起头」把对话挂到检查点（`record_handoff`，`project_evidence.py:261`），后台任务以 `done` 结束时 `job_finished` 打勾（`:268-296`）。**坑：** 今天跟着子任务自己的 `done` 打勾；有了总指挥，要等总指挥收下汇报才打勾（`task_workers` 已有「最终验收归 host」这条）。
  - **开工前要先想好：** 汇报只往上走，子会话之间不直接聊；确认卡汇总到总指挥一处；两个子会话不同时改同一个文件；整个项目一个花费上限（要新做：按项目记在库里、跨重启都算、每次请求前查，并定好和每次运行自己的 $2 上限的关系；`shared_budget_id` 只是个没人读的标签，`contracts.py:203`，今天帮手共用预算是因为跑在父回合里、经 ContextVar 看到同一个内存里的 `Budget`，`execution_budget.py:283`）；总指挥要排先后（例如视频要先定大纲）。
    ②Main 审 #429 时又补了 12 条：
    1. **汇报带着子会话「读过外部内容」的标记（安全）：** 汇报按外部内容框起来，并且给总指挥也打上标记（S2a-1 的断网、教训和笔记的自动启用读的就是它）。今天的 `delegate_work` 两样都没做，见下面那条安全项；新工具不能照抄。
    2. **设置和权限只继承、不放宽**（领先路线 `:243`）：子会话继承总指挥的对话设置（不记忆、不学习、临时、云端记忆、敏感、项目）和权限模式。一个子会话里的「本对话都允许」默认不覆盖别的。
    3. **一段对话同时只跑一个回合**（今天第二个动作回 409 `conversation_running`，`companion.py:256`）：跟忙着的子会话「直接对话」要排队或插话（K9 那条路）；用户正跟总指挥说话时到的汇报先等着，再开一个总指挥回合，像后台任务推回结果那样。
    4. **重启：** 写码前先列重启矩阵（子会话在跑、子会话在等卡、总指挥在等汇报），状态发生时就记下；照 `task_workers` 的 `interrupted`。
    5. **停止、删除、撤销**对子会话各做什么：停总指挥、删总指挥、撤销开出它们的那一轮、删一个总指挥还在等汇报的子会话。
    6. **只有一个浏览器、一个桌面：** `parallel_reads.py:30-31` 已经让 `browser_*`、`desktop_*` 串行；两个子会话不能同时开浏览器或 Hands，要排队。Hands 那边是 ③Hands 的文件，先问。
    7. **「不同时改同一个文件」按路径管不住：** `run_command` 哪里都能写。要么每个子会话一个自己的文件夹，要么项目里同一时间只有一个子会话写。
    8. **列表：** 子会话也是对话，会出现在 Mac 侧栏、手机的 `conversations.result` 和 `/phone/live`，跟快问（#425 改动 A）是同一个问题。和快问迁移加的 `kind` 列一起设计，再加一个父对话 id。手机上显示子会话要改 Bridge 帧，要用户点头。
    9. **学习和项目证据：** 只有总指挥学习（子会话 no_learning），否则一条教训记 N 次；子会话的回合 `project_evidence.after_turn(said=…)`（`:300`）要是 false，总指挥的交代不是用户说的话。
    10. **层数和数量在代码里管，不靠提示词：** 最下层不给这个工具，执行时也拒（照 `worker_host_only`，`:214`）；再给每个总指挥的子会话数设上限。
    11. **`delegate_work` 怎么办：** 统一成一个工具就删掉它和 `TaskWorker`；留作最下层就写 `DELETE-BY:`。
    12. **跑分题：** 也测反面，一步就能做完的请求不开子会话；记花费（N 个子会话 token 成倍）；记服务商的 429（DeepSeek 会同时收到 N 个请求）。
- **`delegate_work` 不传「读过外部内容」的标记（S 线，安全；②Main 审 #429 时读代码发现，没跑过）：** 它返回 `"external": False`（`task_workers.py:268`），所以 `tool_loop.py:373` 把帮手从网页得来的文字不加框就交给父回合；`counts_as_external` 也没列它（`untrusted.py:72-79`）；每个帮手的 `run_native` 只给自己打标记（`tool_loop.py:2812`），父回合的标记一直是干净的，S2a-1 的断网和教训、笔记的自动启用都不会触发。影响面小：C3b 已改成按需发，而且只在后台任务里能用。**先写一个测试证实**，再修；修的是安全面，按规矩 effort=max 写和审。如果 v0.1.64 的子会话工具直接替掉它，就在那张卡里一起收掉，测试照样要有。
- **界面版的设计图先出（④参谋 建议，用户还没确认）：** 配色、字体、关键几页、rail 布局，在 v0.1.64 卡片大合并之前出设计图，只出图、不写代码，卡片合并直接用新风格、不返工。iPhone 1.1 的改版也在等 Mac 的 v0.1.64，可以共用一套设计语言。
- **Aegis 试点的结论**（§9）：写在这里，v0.1.64 开工前由用户决定要不要全面换。
- 其余见领先路线 §3、§4 的 v0.1.64 列：卡片界面与文案大合并（D1）；diff 预览；网络出口控制；子 agent 统一成一个工具；后台进程与进程工具；目标模式；ACP。

- **Memory: what changes (user agreed item by item on 2026-10-28; ④参谋 wrote the one-pager).** This adds detail to the 10-21 decision (memory as files in v0.1.65) and to Inbox items 6 and 7 (#433); it does not replace them. Basis: ④参谋 read the user's local database read-only (counts only below), checked main `502012f5`, and compared the official docs of Claude Code, ChatGPT, Codex, Hermes, Letta, mem0 and Graphiti (links at the end of this item).
  - **What is wrong today (counts from the user's machine, 10-28):** 266 "about you" entries (153 active, 77 proposed, 30 quarantined, all `scope_kind=expert` left from the expert era) and 54 lessons (31 active, 22 proposed). Problems seen: the same meaning stored three times, because `dedup_key` only catches literal duplicates; one-off task state (an install folder, a port number, "the user is deploying X") stored as a fact about the user; opinions that go stale stored without a date; mixed languages, including one English entry that guessed the user's gender.
  - **What the mainstream agents share:** four layers (rules the user writes and the agent must follow; a small core always loaded, with a hard size cap; history searched when needed; procedures as skills). Memory is a hint, not a rule. Worth borrowing: a hard cap that forces merging when full; tidying after the conversation goes idle; no memories from a conversation that touched outside content (Arslan already does this); showing under an answer which memories it used, with "don't bring this up again" separate from "delete"; marking stale items with a date instead of hard-deleting.
  - **A. v0.1.64, small fixes** (⓪Plan schedules them as card MEM1, after INB2; see `docs/plans/0164/INB-inbox-progress.md`):
    1. Before writing, compare the meaning with existing entries; merge when it is the same, instead of adding a new entry.
    2. Always write in the language the user speaks; never guess the user's gender ("the user", not he/his/she).
    3. One-off task state (paths, ports, "currently doing X") does not go into "about you"; it stays with the conversation or project it belongs to.
    4. The 30 quarantined `scope_kind=expert` entries: C7c decides, when it drops the expert tables, whether to delete or move them.
  - **B. v0.1.65, when memory becomes files:**
    5. Three files (about you / Arslan's notes / private, private stays on this Mac), each with a "used / limit" line at the top; when one is full, Arslan merges entries itself.
    6. **Lessons stop being a separate kind:** one- or two-sentence ones go into Arslan's notes, multi-step ones become skills. The use count, success record and "stop after repeated failures" (INB1) move with them.
    7. Background tidying works like human memory: frequently used items stay at the front, long-unused ones are marked "may be out of date" rather than deleted; every entry carries a date.
    8. Under an answer, one line "used N memories and sources"; opening it lets the user edit, delete, or choose "don't bring this up again". The progress page map also lists which memories were used.
    9. At the top of the memory page, one line "what Arslan learned this week": how many new, merged, faded; tap for details.
    10. No relationship graph (dropped on 10-21).
    - ⓪Plan's call: 8 and 9 go with v0.1.65's memory files, not the interface version. They are small and they are what makes "it gets to know me" visible.
  - **C. Language: from a memory to a rule.**
    11. From 2026-10-28, everything written to GitHub is in English (code, comments, commits, PR bodies and comments, plan docs, bundled skills, READMEs). Older Chinese text is not rewritten. Chat with the user stays in Chinese.
    12. Written into `CLAUDE.md` and `docs/sessions.md` §6 (this PR).
    13. CI check: fail when a PR adds Chinese to a line where it should not be. It checks added lines only (about 250 files on main already contain Chinese), with the exceptions in `docs/sessions.md` §6 (quoted Chinese, data that matches Chinese input, translation tables, tests/evals/fixtures with Chinese input, `docs-site`, iOS UI copy until decided). Commit messages and PR text stay each session's job. Card LANG1 (v0.1.64).
    14. Bundled skills to English: `arslan/skills/bundled/designed-html-report/SKILL.md` and `skill-creator/SKILL.md` are in Chinese and ship to every user. Part of LANG1.
    15. Arslan itself: output language follows where the output goes. Chat follows the language of the user's message; a file follows that folder's rules; a message follows the recipient. When the user corrects the same thing twice, Arslan asks "make this a rule for this folder?" (joins L11, folder rules).
  - **D. Personal knowledge base.**
    16. Sources are plain folders; Arslan reads them with its file tools and cites them (decided 10-21). An Obsidian vault can be pointed at directly, no import.
    17. **"Import memories from ChatGPT / Claude" joins v0.1.64's import card** (CAP, the Claude Code / Codex import): the user pastes, Arslan lists the entries it would keep, the user confirms before anything is stored.
    18. WeChat: **not** by decrypting the WeChat database. The project people point to (WeChatMsg) now has only a README and images, no code and no license, and its author has stopped updating it; its method pulled a key out of the WeChat process to decrypt the local store, which breaks WeChat's terms, reads another program's memory, and pulls in other people's private messages. What works: the user picks a few passages, exports them with WeChat's own feature or takes screenshots for OCR; one "import" conversation extracts only what is about the user and shows the list before storing; the original stays in the user's folder or is deleted after use; family, health and money are asked about separately. After v0.1.65.
  - **E. From reactive to proactive (after v0.1.65).**
    19. Get memory right first, then propose. Proposals appear in the conversation or on the progress page, not in the Inbox, and each says why, with the memories it relied on one tap away.
  - **Unchanged:** the outside-content gate, the #239 sensitive-memory rules, `local_only`, and "temporary conversations and no_learning write nothing".
  - **Sources:** [Claude Code](https://code.claude.com/docs/en/memory), [ChatGPT](https://help.openai.com/en/articles/8590148-memory-faq), [Codex](https://learn.chatgpt.com/docs/customization/memories), [Hermes](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory), [Letta](https://docs.letta.com/agent-sdk/memory/), [mem0](https://github.com/mem0ai/mem0), [Graphiti](https://github.com/getzep/graphiti), [WeChatMsg](https://github.com/LC044/WeChatMsg).

- **Projects: what changes (user agreed item by item on 2026-10-28; ④参谋 wrote the one-pager).** The full text is in the v0.1.64 plan, `docs/plans/0164/SUB-sub-sessions.md`, section "Projects" (#434). In short: one project = one goal + one coordinator, and the user talks only to the coordinator; "what done looks like" is a checklist, and an item is ticked only when the coordinator has accepted a sub-session's report with its acceptance sheet and evidence; project rules, project memory (can use "about you" by default, isolatable per project), the project folder as library, one spending cap, permissions only inherited; reporting only when a decision is needed plus one line per finished item. Deleted: the four-column board, per-type template gates, "learn how you advance gates" (`project_habits`), rhythm stats, stall reminders; the retro becomes the coordinator's final report. The board becomes a read-only progress board (one row per project: goal, segmented bar, "who is doing what now", status tag, 7-day strip, spent / cap, last update). Schedule: v0.1.64 the sub-session base and card PRJ0 (deletions only); v0.1.65 the project page, checklist and progress-board data, deleting the board and template gates in the same version; the look in the interface version, after the user approves a clickable demo. The basis (counts from the user's machine only) is in the SUB card.

## 9. 流程试点：Aegis 方法包（v0.1.62 发布后再做）

- **在哪试：** 只在 ②Main 的 C 线，也就是删死代码那批卡。用 Aegis 方法包（github.com/GanyuanRan/Aegis，MIT）替换 superpowers。
- **怎么分开：** 一个会话里不要两套同时装。所以 C 线试点单独开一个会话，在 §4 分道表里登记为「C 线试点会话」。这个会话只装 Aegis；②Main 继续做 K、S 线，照旧用 superpowers。
- **准备（装之前）：**
  - 锁定一个版本：记下具体的 tag 或提交号，写进本节；
  - ⓪Plan 先审一遍它在会话启动时运行的脚本（钩子等），把审查结论写进本节；
  - 用户看过审查结论、点头之后再装。
- **对比：** 和继续用 superpowers 的 K 线比四个数，每合一个 PR 记一次：
  - PR 大小（产品代码行数）；
  - 评审轮数；
  - CI 变红的次数；
  - 「说的和做的对不上」的次数：PR 描述或汇报里的完成证据（sessions §8），被评审或 CI 发现和实际不符。
- **注意：** C 线以删为主，K 线以改为主，两边的活不一样。这四个数只能作参考，结论里要写上这一点。
- **结论：** 写进 §8，v0.1.64 开工前由用户决定要不要全面换。
- **在那之前：** 其他会话照旧用 superpowers。
- **锁定的版本：**（待填）
- **启动脚本的审查结论：**（待填）
