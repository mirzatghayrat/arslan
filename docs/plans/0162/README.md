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
| [F5b](F5b-delete-cua-engine.md) | 删 Cua Driver 引擎代码（③Hands 审）；文件内改动约 600 行，超出 U2 的 50 行，默认拆 F5b-1 断开接线、F5b-2 按 U2 删整文件（更正 E14） | ②Main | v0.1.63 | 必须 | F5a | F5b-1 #249：③Hands 已批代码、CI 绿（39343358885 / 39343362761），等用户在场跑 `hands_smoke.py` 再合；F5b-2 分支已备好（`claude/0162-f5b2-remove-cua-files`），#249 合后开 PR |
| [H1](H1-hands-chat-cap-answer.md) | 书面回答：聊天里 5 步上限防什么（⓪Plan 代为提交） | ③Hands | v0.1.63 | 必须 | —（K4 开工前交） | 已合并（#188 = `d74869f5`） |
| [H3](H3-hands-chat-cap-change.md) | 去掉聊天里 Hands 的 5 次和「一轮一个 App」，并进 K4；Stop 对聊天回合也停住（U8） | ③Hands | v0.1.63 | 应该 | H1（已同意，U8）、K4b | 待开工 |
| [H4](H4-app-name-forms.md) | AppleScript 里写成「.app」或完整路径的 App，也按同一个 App 认（高权限判断、never-list）；②Main 2026-10-20 复审 #267 时在 main 上发现，算恢复已有承诺的安全修复；Opus 5.5 上写和审 | ③Hands | v0.1.63 | 必须 | #267 | 已合并（#271 = `a50bcdab`；③Hands 写前半，⓪Plan 在 Opus 5.5 上写后半，②Main 在 5.5 上审了三轮） |
| [C1](C1-tests-test-product.md) | 让测试测产品：删打开专家的 fixture 和只在专家开启时跑的路径 | ②Main | v0.1.63 | 必须 | F5a；合并等热修合回 main | 已合并（#203 = `f28b52bc`） |
| [C1b](C1b-expert-modules.md) | 删 9 个不可达的专家模块 | ②Main | v0.1.63 | 必须 | C1 | 已合并（#210 = `e13318ad`） |
| [C1c](C1c-expert-leftovers-web.md) | 专家残留（函数、网页帧、翻译）；拆 C1c-1 服务端、C1c-2 网页 | ②Main | v0.1.63 | 必须 | C1 | C1c-1 已合并（1a #257 = `2993ff93`；1b #258 = `6e17afc3`）；C1c-2 待开工 |
| [C2a](C2a-memory-v1.md) | 删记忆 v1 死分支（超 800 行时拆两个） | ②Main | v0.1.63 | 必须 | C1（K2 开工前合） | C2a-1 已合并（#237 = `83d8a581`；测试库开机顺序补丁 #244 = `0612813b`）；C2a-2 待开工 |
| [C2b](C2b-evolution-first-batch.md) | 删进化第一批；拆 C2b-1 接口、C2b-2 自动路径 | ②Main | v0.1.63 | 必须 | C1 | 待开工（卡的决定和命令更正已合并：#248 = `fc505f24`） |
| [C2c](C2c-0161-leftovers.md) | 0.1.61 遗留死代码 | ②Main | v0.1.63 | 必须 | C1 | 已合并（Hands 那半 #246 = `c40483c8`；其余 #253 = `43a1027c`，③Hands 安全审过） |
| [C2d](C2d-legacy-cli.md) | 删旧命令行 | ②Main | v0.1.63 | 必须 | C1 | 已合并（#238 = `aea8a2d2`） |
| [C2e](C2e-misc-python.md) | Python 杂项死代码；拆 C2e-1 杂项、C2e-2 媒体与 MCP 探测 | ②Main | v0.1.63 | 必须 | C1 | 已合并（C2e-1 #247 = `5e25ac92`；C2e-2 #254 = `5c176990`） |
| [C2f](C2f-misc-web-repo.md) | 网页杂项与误提交文件 | ②Main | v0.1.63 | 必须 | C1 | 已合并（#243 = `3e0de127`） |
| [C3](C3-tool-exposure.md) | 删 / 降级没人用的工具；拆 C3a 删除、C3b 降级 | ②Main | v0.1.63 | 必须 | C1、K5（K7 之前合；C1b 最好先合） | 待开工 |
| [C4](C4-remove-shadow-judgment.md) | 删影子评判；记录撤回决定② | ②Main | v0.1.63 | 必须 | C1、C2c | 已合并（#256 = `c2652b80`，③Hands 安全审过；`scripts/usage_report.py` 的影子评判表经 ⓪Plan 同意一起删） |
| [C5a](C5a-process-docs-privacy.md) | 过程文档移到存档分支；从文件里删隐私段落 | ②Main | v0.1.63 | 应该 | — | 待开工 |
| [C5b](C5b-version-source-inventory.md) | 唯一版本来源；能力清单只在发版时生成（越早合越好） | ②Main | v0.1.63 | 应该 | — | 已合并（#201 = `90fd3c11`） |
| [C6](C6-ci-parallel-coverage.md) | CI 并行与覆盖率 | ②Main | v0.1.63 | 应该 | F5a | 待开工 |
| [K1](K1-native-tool-protocol.md) | Claude、Gemini 走原生工具协议；保留思考块，支持 `tool_choice`；Anthropic 回合内发出后不改前文（服务端清理旧结果） | ②Main | v0.1.63 | 必须 | C1；合并等 M1B | 已合并（K1a #212 = `df18ba0e`；K1b #213 = `18d691bb`；合并后对照在 #213） |
| [K2](K2-context-by-window.md) | 跨轮上下文按窗口；工具摘要放进 `content`；回合后工作挪出锁 | ②Main | v0.1.63 | 必须 | K1；C2a | 已合并（K2a #240 = `4f471a30`；K2b #252 = `8780fc34`，⓪Plan 的 k2b-ds 过门槛：19/27 通过，基线 18；③Hands 审过） |
| [K3](K3-prompt-layout-cache.md) | 提示词布局与缓存断点 | ②Main | v0.1.63 | 必须 | K2 | 已合并（K3 #259 = `f3bda58d`，DeepSeek 门槛过；K3b #275 = `7e8c57aa`：Claude 上不改已发出的历史、清理改 100k/40k，E26） |
| [K4](K4-one-stop-policy.md) | 一个停止策略；保留花费上限，美元上限默认开；拆 K4a、K4b | ②Main | v0.1.63 | 必须 | K3、H1 | K4a #277：代码已批（⓪Plan，Opus 5.5），5% 账单核对过；DeepSeek 门槛待重跑（bench 每次上限调到 $2.50 后）；K4b 待开工 |
| [K5](K5-working-method-tool-docs.md) | 工作方法与工具说明；多步骤任务结束时给用户四行收尾 | ②Main | v0.1.63 | 必须 | K4b、F1 | 待开工 |
| [K7](K7-tools-on-demand.md) | MCP 和少用的工具按需取用 | ②Main | v0.1.63 | 必须 | K5、C3、F3 | 待开工 |
| [K8](K8-true-streaming-guards-after.md) | 真流式，守卫改为事后；按供应商拆 K8a、K8b、K8c | ②Main | v0.1.63 | 必须 | K7 | 待开工 |
| [K9](K9-parallel-reads-steering.md) | 只读工具并行 + 回合中插话（窗口、iPhone、按住说话各一条测试；灵动岛输入挪到 v0.1.64） | ②Main | v0.1.63 | 必须 | K8c | 待开工 |
| [K10](K10-agents-md.md) | 读 AGENTS.md | ②Main | v0.1.63 | 应该 | K9 | 待开工 |
| [K6](K6-file-tools.md) | 文件工具补齐（不进严格链） | ②Main | v0.1.63 | 应该 | K7 | 待开工 |
| [D2](D2-checks-not-run.md) | 「检查跑不了」不再把做完的事挂成「等你」：常见代码和配置文件按文本解析，没有解析器的类型记「不适用」（M1B 基线发现，⓪Plan 2026-10-19 加；不进严格链） | ②Main | v0.1.63 | 必须 | — | 已合并（#221 = `84d90f98`） |
| [D3](D3-read-timeout-known.md) | 只读命令超时，不记成「结果不明」：`_reads_only` 认得 `&&`、`;`、`\|` 连起来的只读命令和丢弃输出的重定向（K1 合并后对照发现；U10 提为必须，不进严格链） | ②Main | v0.1.63 | 必须 | — | 已合并（#230 = `053f6b42`） |
| [D4](D4-osascript-not-authorized.md) | osascript 报「未授权」（`-1743`，核实后加 `-10004`），只对一个 App 说话时算已知失败（K1 合并前后对照发现；U10 提为必须，不进严格链） | ②Main | v0.1.63 | 必须 | — | 已合并（#231 = `0d15026b`；后续 #245 = `5e33c5e5`，⓪Plan 实测 T1 2/3，K2a 时 0/3）；还有两种写法记在卡末，以后再看 |
| [D5](D5-search-native-first.md) | 搜索：先用这个对话这一轮模型自带的搜索（Claude 用 Anthropic 服务端 web search，只在官方 host 或允许清单上；本地模型的对话不用任何云端自带搜索，DeepSeek 一起改）；Tavily / SearXNG 可以设成备选，已存的选择照旧只用它，选了服务就不再落到 DuckDuckGo；403、429、人机验证报「搜索被拦」，401 报 key 被拒（用户 2026-10-20 要求，⓪Plan 定为应该；③Hands 审卡改过；不进严格链，但**要在 R63 用 Claude 跑最后一轮之前合**，用户 2026-10-20） | ②Main | v0.1.63 | 应该 | — | 待开工 |
| [D6](D6-journal-false-positive.md) | 一步记不进任务记录时只拒这一步、任务继续；不在 JSON 编码后的文字上查密钥（「无验证码：」加换行被误判，K3 的 Claude 对照 T2 第 2 次因此整个后台任务停掉）；同类的 4 处一起改（用户 2026-10-20 定为应该；不进严格链，K3 之后） | ②Main | v0.1.63 | 应该 | K3 | 已合并（卡 #270 = `3783951f`；代码 #274 = `ceb4d976`） |
| [D1](D1-deliver-files.md) | 回合做出的文件送到窗口和 iPhone：新工具 `attach_file`；来自 iPhone 的回合告诉模型路径没用（用户报告，⓪Plan 2026-10-18 加；不进严格链） | ②Main | v0.1.63 | 必须 | — | 已合并（#217 = `57a2218b`）；M3 第 12 条（真 Mac + iPhone 截图）待用户验 |
| [S1](S1-mcp-approval-by-hints.md) | MCP 按标注审批（R6）；定时任务不给后台工具（R7） | ②Main | v0.1.63 | 必须 | C1、F4a、F2（H2） | 待开工 |
| [S2a](S2a-command-three-layers.md) | 命令「沙箱优先」三层，同时收紧沙箱；受保护路径补全；拆 S2a-1 收紧沙箱、S2a-2 三层 | ②Main | v0.1.63 | 必须 | F4a、C1、C4 | S2a-1 已合并（#265 = `0183ff88`，⓪Plan 在 Opus 5.5 上三轮安全审查；Hands 词表 #267 = `5ddc8e4a`、#276 = `893fdd55`）；S2a-1b 已合并（#272 = `0d17ee13`）；S2a-2 待开工 |
| [S2b](S2b-drop-vendored-hermes.md) | 删整份引入的 Hermes 规则；拆 S2b-1 换上自有的文本处理（约 150 行）、S2b-2 按 U2 只删文件 | ②Main | v0.1.63 | 必须 | S2a | 待开工 |
| [S3](S3-checkpoints.md) | 检查点：文件和命令都能撤销；每回合克隆一次；拆 S3a 检查点、S3b 撤销界面 | ②Main | v0.1.63 | 必须 | C1、F4b（最好在 S2a-2 之前合） | 待开工 |
| [S4a](S4a-outside-remote-cards-decide.md) | 出沙箱卡、远程卡走 `decide()` 并写账本；两份确认流程合成一份 | ②Main | v0.1.63 | 必须 | C4、S2a | 待开工 |
| [S4b](S4b-allowed-folders.md) | 「允许的文件夹」（不接受别的卷上的文件夹：S3 撤销不了） | ②Main | v0.1.63 | 应该 | S3、S4a | 待开工 |
| [S5](S5-mode-setting.md) | 一个模式设置（含计划模式）；完全访问下照问的种类按 U4 | ②Main | v0.1.63 | 应该 | S2a、S1、C4、F4a、S3（S4b 软） | 待开工 |
| [S6](S6-remembered-answers-page.md) | 「记住的回答」页 | ②Main | v0.1.63 | 可以 | S4b、S2a | 待开工 |
| [S7](S7-capability-card-ledger.md) | 安装能力卡也写一行账本（§5.4 门槛） | ②Main | v0.1.63 | 必须 | S4a、C4 | 待开工 |
| [R63](R63-release.md) | 发 v0.1.63：最后一轮 M1、7 天本机数据、M3、发布说明对测试 | ⓪Plan 判定 + ②Main 发版 | v0.1.63 | 必须 | v0.1.63 全部「必须」卡 | 待开工 |

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
- S2a-1 → S2a-2，S2b-1 → S2b-2，S3a → S3b；
- S3 最好在 S2a-2 之前合（S2a-2 之后，工作文件夹里的删除不再出卡，要靠撤销）；
- 其余 C 卡都在 C1 之后，什么时候合都行。

**M 线：** 随时，不进 App。M1、M2 在 FR 之前合；M1B 等 M1 和 v0.1.62。

**规则：**

- 同一时间，改同一个热点文件的打开 PR 最多一个。K 线优先。
- 其他 PR 等当前这个 K 线 PR 合了，再 rebase。
- **800 行的例外（U2，已定）：** 只做整份删除的 PR 可以超过 800 行。条件：只删不可达或第三方的整个文件；别处只去掉引用，合计 ≤50 行；不改行为；PR 描述列出删了哪些文件、怎么确认不可达；CI 全绿。C1b 因此不拆。F5b 和 S2b 不满足「别处 ≤50 行」（F5b 文件内要改约 600 行；S2b 要先换上一个约 150 行的自有模块），所以照旧各拆两个 PR，第二个按 U2 只删整文件（更正 E14）。用户要是放宽 U2，这两张可以各合成一个 PR。

## 4. 分道表

| 道 | 负责的卡 | 拥有的文件 | 不许碰 |
|---|---|---|---|
| ⓪Plan | M1、M1B（和用户一起）、M2、M3；R63 的门槛判定；代为提交 H1 的回答；维护总计划、本表和任务卡 | `scripts/kernel_bench/**`、M2 新增的周报脚本、`docs/plans/**`、`docs/sessions.md` | 产品代码 |
| ②Main | F5a、F1、F2、F3、F4a、F4b、FR、F5b；全部 C、K、S 卡；R63 的发版准备；合并队列、本表的「状态」列、迁移号登记、CI 健康 | `server/**`、`arslan/**`、`web/**`、`.github/**`、`packaging/**`、`docs/releases/**`、`docs/CAPABILITY_INVENTORY.md`。<br>以下除外：③Hands 的文件；Bridge 契约文件的帧格式 | ③Hands 的文件（要改须由 ③Hands 审，例如 F5b、C2c 里 AppleScript 那两行）；Bridge 帧格式 |
| ③Hands | H1、H2、H3；审 F5b 和任何改 Hands 文件的卡 | `desktop/hands/**`、`server/registry/hands_tools.py`、`server/services/hands_service.py`、`server/api/hands.py`、`scripts/hands_smoke.py` | 其他所有文件。本轮不新增 Hands 能力 |
| ①iOS | 无 | iOS 仓库 | 本轮 Mac 端不改 Bridge 帧格式（`desktop/bridge/**`、`server/ws/bridge.py`、`spec/mobile-bridge/**`）。哪张卡如果发现需要改（最可能是 K9），先停下来找 ②Main 和 ①iOS |
| C 线试点会话 | v0.1.62 发布后的 C 卡（§9） | 同 ②Main 的 C 卡 | 同 ②Main；不装 superpowers |

## 5. 迁移号登记表

- 原来 PR 3、6、5、7 的 0069–0072 预留**全部作废**。
- skills v2 分支上的 `_0070_skills_v2` 随该分支不合并，一起作废。

| 号 | 归属 | 状态 |
|---|---|---|
| 0067 | 0.1.61 权限核心 | 已发布（v0.1.61），冻结 |
| 0068 | 0.1.61 MCP 状态 | 已发布（v0.1.61），冻结 |
| 0069 | 空 | 下一个可用的号 |

- v0.1.62 热修线不带迁移。
- v0.1.63 预计只有 S3（检查点索引）可能需要 1 个迁移号。S3 优先用数据目录里的清单文件，不建表。
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

- 旧的扁平 `llm_*` 设置键：要先写数据迁移才能删（C2c 发现）。
- 读 `~/.agents/skills`：总计划 §3.1 决定放到 v0.1.64。
- `click`、`rich` 两个依赖只有旧命令行在用（C2d 发现），删旧命令行后可以去掉。
- 专家时代剩下的 REST 接口：`spawns`、`recipes`、`expert_conversion` 等（C1 发现，本版不动）。做的时候，连同 C1、C1c 卡里留着的专家兼容路径和专家表一起删。
- 记忆 v1 的旧表、兼容视图和触发器：数据并进 v2 或确认为空后再删（C2a）。
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
- **Aegis 试点的结论**（§9）：写在这里，v0.1.64 开工前由用户决定要不要全面换。
- 其余见领先路线 §3、§4 的 v0.1.64 列：卡片界面与文案大合并（D1）；diff 预览；网络出口控制；子 agent 统一成一个工具；后台进程与进程工具；目标模式；ACP。

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
