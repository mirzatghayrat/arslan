# 0.1.62：任务卡清单与分道表

- **状态：等用户看过再开工**（2026-10-17）。
- **总计划：** `docs/plans/2026-10-17-0162-execution-first.md`，先看开头的「决定记录」和「更正记录」。
- **补充：** `docs/plans/2026-10-17-0162-lead-roadmap.md`。
- **规矩：** `docs/sessions.md`。
- **版本号还没定（更正 E1）。**
  - 热修线发的那一版，下文叫「热修版」。
  - 「0.1.62」指执行内核那一版的计划。
  - 用户定了版本号之后，只改这里和 FR 卡。

---

## 1. 先开的几道（互不依赖）

| 道 | 卡 | 谁 |
|---|---|---|
| 热修 | F5a 先合（CI 解堵）；然后 F1、F2、F3、F4a、F4b；H2 是 F2 的软依赖；最后 FR 发热修版 | ②Main（H2 由 ③Hands 做） |
| 跑分基线 | M1 → 热修版发布后做 M1B | ⓪Plan；M1B 由用户在本机用自己的 key 跑 |
| 本机周报 | M2 | ⓪Plan |
| 让测试测产品 | C1（F5a 之后） | ②Main |

## 2. 任务卡清单

每张卡一个 PR。卡里写了：目标、改哪些文件、不许碰、怎么做、验收、量级、风险。

「状态」列由 ②Main 维护：待开工 → 开发中 → 待合并（附 PR 号）→ 已合并（附合并提交）。

| 卡 | 做什么 | 道 | 版本 | 分级 | 依赖 | 状态 |
|---|---|---|---|---|---|---|
| [F5a](F5a-ci-unblock.md) | CI 解堵：去掉 Cua Driver 的 CI 步骤 | ②Main | 热修版 | 必须 | — | 待开工 |
| [F1](F1-command-timeout.md) | `run_command` 时限跟参数走，超时带输出 | ②Main | 热修版 | 必须 | F5a | 待开工 |
| [F2](F2-unknown-outcome-chain.md) | 「结果不明」链四处修正 | ②Main | 热修版 | 必须 | F5a；H2（软） | 待开工 |
| [F3](F3-mcp-schema.md) | MCP schema 规整，坏工具单独降级 | ②Main | 热修版 | 必须 | F5a | 待开工 |
| [F4a](F4a-terminal-osascript-once.md) | 终端 osascript / `shortcuts run` 只给「这一次」；更正 v0.1.61 说明 | ②Main | 热修版 | 必须 | F5a | 待开工 |
| [F4b](F4b-write-no-symlink.md) | 写文件不跟随符号链接 | ②Main | 热修版 | 必须 | F5a | 待开工 |
| [FR](FR-hotfix-release.md) | 发热修版（版本号见 E1）；从 v0.1.61 拉发版分支，只挑热修提交；另开一个只改文档的 PR 记录发版 | ②Main | 热修版 | 必须 | F5a、F1–F4b（H2 若已合） | 待开工 |
| [F5b](F5b-delete-cua-engine.md) | 删 Cua Driver 引擎代码（③Hands 审）；默认拆两个 PR：F5b-1 断开接线，F5b-2 删整文件 | ②Main | 0.1.62 | 必须 | F5a | 待开工 |
| [H1](H1-hands-chat-cap-answer.md) | 书面回答：聊天里 5 步上限防什么 | ③Hands | 0.1.62 | 必须 | — | 待开工 |
| [H2](H2-hands-not-executed-codes.md) | Hands 没执行时的明确结果代码 | ③Hands | 热修版 | 必须 | — | 待开工 |
| [H3](H3-hands-chat-cap-change.md) | 按 H1 的结论改聊天上限 | ③Hands | 0.1.62 | 必须 | H1、K4 | 待开工 |
| [M1](M1-bench-upgrade.md) | 基准升级：「等你」算失败、5 道新题、Claude Code 参赛；拆两个 PR：M1a 判分与参赛者，M1b 新题 | ⓪Plan | 脚本 | 必须 | — | 待开工 |
| [M1B](M1B-baseline.md) | 在热修版上跑基线 | ⓪Plan + 用户 | 脚本 | 必须 | M1、FR | 待开工 |
| [M2](M2-weekly-usage-report.md) | 本机用量周报脚本（只读、只出数字） | ⓪Plan | 脚本 | 必须 | — | 待开工 |
| [M3](M3-acceptance-checklist.md) | 10 条体感验收清单 | ⓪Plan | 文档 | 必须 | — | 待开工 |
| [C1](C1-tests-test-product.md) | 让测试测产品：删打开专家的 fixture 和只在专家开启时跑的路径 | ②Main | 0.1.62 | 必须 | F5a | 待开工 |
| [C1b](C1b-expert-modules.md) | 删 9 个不可达的专家模块 | ②Main | 0.1.62 | 必须 | C1 | 待开工 |
| [C1c](C1c-expert-leftovers-web.md) | 专家残留（函数、网页帧、翻译）；locale 测试不再写死总数；拆两个 PR：C1c-1 服务端，C1c-2 网页 | ②Main | 0.1.62 | 必须 | C1 | 待开工 |
| [C2a](C2a-memory-v1.md) | 删记忆 v1 死分支（超 800 行时拆两个） | ②Main | 0.1.62 | 必须 | C1 | 待开工 |
| [C2b](C2b-evolution-first-batch.md) | 删进化第一批；拆两个 PR：C2b-1 接口，C2b-2 自动路径 | ②Main | 0.1.62 | 必须 | C1 | 待开工 |
| [C2c](C2c-0161-leftovers.md) | 0.1.61 遗留死代码 | ②Main | 0.1.62 | 必须 | C1 | 待开工 |
| [C2d](C2d-legacy-cli.md) | 删旧命令行 | ②Main | 0.1.62 | 必须 | C1 | 待开工 |
| [C2e](C2e-misc-python.md) | Python 杂项死代码；拆两个 PR：C2e-1 杂项，C2e-2 媒体与 MCP 探测 | ②Main | 0.1.62 | 必须 | C1 | 待开工 |
| [C2f](C2f-misc-web-repo.md) | 网页杂项与误提交文件 | ②Main | 0.1.62 | 必须 | C1 | 待开工 |
| [C3](C3-tool-exposure.md) | 删 / 降级没人用的工具；拆两个 PR：C3a 删除，C3b 降级（紧挨 K7） | ②Main | 0.1.62 | 必须 | C1 | 待开工 |
| [C4](C4-remove-shadow-judgment.md) | 删影子评判；记录撤回决定 ② | ②Main | 0.1.62 | 必须 | C1、C2c | 待开工 |
| [C5a](C5a-process-docs-privacy.md) | 过程文档移到存档分支；从文件里删隐私段落 | ②Main | 0.1.62 | 应该 | — | 待开工 |
| [C5b](C5b-version-source-inventory.md) | 唯一版本来源；能力清单只在发版时生成（**越早合越好**：之后别的 PR 不用再为能力清单解冲突） | ②Main | 0.1.62 | 应该 | — | 待开工 |
| [C6](C6-ci-parallel-coverage.md) | CI 并行与覆盖率 | ②Main | 0.1.62 | 应该 | F5a | 待开工 |
| [K1](K1-native-tool-protocol.md) | Claude、Gemini 走原生工具协议 | ②Main | 0.1.62 | 必须 | C1 | 待开工 |
| [K2](K2-context-by-window.md) | 跨轮上下文按窗口；工具摘要；回合后工作挪出锁 | ②Main | 0.1.62 | 必须 | K1 | 待开工 |
| [K3](K3-prompt-layout-cache.md) | 提示词布局与缓存 | ②Main | 0.1.62 | 必须 | K2 | 待开工 |
| [K4](K4-one-stop-policy.md) | 一个停止策略，聊天和后台同一套规矩 | ②Main | 0.1.62 | 必须 | K3、H1 | 待开工 |
| [K5](K5-working-method-tool-docs.md) | 工作方法与工具说明 | ②Main | 0.1.62 | 必须 | K4、F1 | 待开工 |
| [K7](K7-tools-on-demand.md) | MCP 和少用的工具按需取用 | ②Main | 0.1.62 | 必须 | K5、C3、F3 | 待开工 |
| [K6](K6-file-tools.md) | 文件工具补齐 | ②Main | 0.1.62 | 应该 | K7 | 待开工 |
| [K8](K8-true-streaming-guards-after.md) | 真流式，守卫改为事后更正 | ②Main | 0.1.62 | 必须 | K6 | 待开工 |
| [K9](K9-parallel-reads-steering.md) | 只读工具并行 + 回合中插话 | ②Main | 0.1.62 | 必须 | K8 | 待开工 |
| [K10](K10-agents-md.md) | 读 AGENTS.md | ②Main | 0.1.62 | 应该 | K9 | 待开工 |
| [S1](S1-mcp-approval-by-hints.md) | MCP 按标注审批（R6）；定时任务不给后台工具（R7） | ②Main | 0.1.62 | 必须 | C1、F4a、F2（H2） | 待开工 |
| [S2a](S2a-command-three-layers.md) | 命令「沙箱优先」三层；受保护路径补全 | ②Main | 0.1.62 | 必须 | F4a、C1 | 待开工 |
| [S2b](S2b-drop-vendored-hermes.md) | 删整份引入的 Hermes 规则 | ②Main | 0.1.62 | 必须 | S2a | 待开工 |
| [S3](S3-checkpoints.md) | 检查点：文件和命令都能撤销 | ②Main | 0.1.62 | 必须 | C1（最好在 S2a 之前合） | 待开工 |
| [S4](S4-allowed-folders-decide.md) | 「允许的文件夹」；出沙箱 / 远程卡走 `decide()` | ②Main | 0.1.62 | 应该 | S3、C4、S2a | 待开工 |
| [S5](S5-mode-setting.md) | 一个模式设置（含计划模式） | ②Main | 0.1.62 | 应该 | S2a、S1、C4、F4a | 待开工 |
| [S6](S6-remembered-answers-page.md) | 「记住的回答」页 | ②Main | 0.1.62 | 可以 | S4、S2a | 待开工 |
| [S7](S7-capability-card-ledger.md) | 安装能力卡也写一行账本（§5.4 门槛） | ②Main | 0.1.62 | 必须 | S4、C4 | 待开工 |

## 3. 合并顺序

**热修线**（合进 main，FR 再从 v0.1.61 拉发版分支，只挑这些提交）：

```
F5a ─┬─ F1
     ├─ H2 ── F2
     ├─ F3
     ├─ F4a
     └─ F4b ──→ FR（热修版）
```

**K 线：严格按顺序，一次只开一个。**

```
C1 → K1 → K2 → K3 → K4 → K5 → K7 → K6 → K8 → K9 → K10
```

**和 K 线交错的固定位置：**

- C2a 在 K2 开工前合，两张都改 `server/orchestrator/memory.py`。
- H1 在 K4 开工前交；H3 在 K4 之后合。
- C3 紧挨在 K7 之前合。

**C、S 两线：并行，但有先后：**

- C2c → C4 → S2a → S4 → S7（都改 `server/services/approvals.py` 和 `server/ws/arslan.py` 的确认阶梯）；
- S2a → S2b，S2a → S5，S1 → S5；
- S3 → S4 → S6；S3 最好在 S2a 之前合（S2a 之后，工作文件夹里的删除不再出卡，要靠撤销）。
- 其余 C 卡都在 C1 之后，什么时候合都行。

**M 线：** 随时，不进 App。M1B 要等 M1 和热修版。

**规则：**

- 同一时间，改同一个热点文件的打开 PR 最多一个。K 线优先。
- 其他 PR 等当前这个 K 线 PR 合了，再 rebase。
- **建议的例外（等用户点头）：** 只做整份删除的 PR，可以超过 800 行，例如 C1b、F5b、S2b。条件是只删不可达或第三方的整个文件，不夹带别的改动。

## 4. 分道表

| 道 | 负责的卡 | 拥有的文件 | 不许碰 |
|---|---|---|---|
| ⓪Plan | M1、M1B（和用户一起）、M2、M3；维护总计划、本表和任务卡；发版前判定门槛 | `scripts/kernel_bench/**`、M2 新增的周报脚本、`docs/plans/**`、`docs/sessions.md` | 产品代码 |
| ②Main | F5a、F1、F2、F3、F4a、F4b、FR、F5b；全部 C、K、S 卡；合并队列、本表的「状态」列、迁移号登记、CI 健康、发版准备 | `server/**`、`arslan/**`、`web/**`、`.github/**`、`packaging/**`、`docs/releases/**`、`docs/CAPABILITY_INVENTORY.md`。<br>以下除外：③Hands 的文件；Bridge 契约文件的帧格式 | ③Hands 的文件（要改须由 ③Hands 审，例如 F5b、C2c 里 AppleScript 那两行）；Bridge 帧格式 |
| ③Hands | H1、H2、H3；审 F5b 和任何改 Hands 文件的卡 | `desktop/hands/**`、`server/registry/hands_tools.py`、`server/services/hands_service.py`、`server/api/hands.py`、`scripts/hands_smoke.py` | 其他所有文件。本版不新增 Hands 能力 |
| ①iOS | 无 | iOS 仓库 | 本版 Mac 端不改 Bridge 帧格式（`desktop/bridge/**`、`server/ws/bridge.py`、`spec/mobile-bridge/**`）。哪张卡如果发现需要改，先停下来找 ②Main 和 ①iOS |

## 5. 迁移号登记表

- 原来 PR 3、6、5、7 的 0069–0072 预留**全部作废**。
- skills v2 分支上的 `_0070_skills_v2` 随该分支不合并，一起作废。

| 号 | 归属 | 状态 |
|---|---|---|
| 0067 | 0.1.61 权限核心 | 已发布（v0.1.61），冻结 |
| 0068 | 0.1.61 MCP 状态 | 已发布（v0.1.61），冻结 |
| 0069 | 空 | 下一个可用的号 |

- 0.1.62 预计只有 S3（检查点索引）可能需要 1 个迁移号。S3 优先用数据目录里的清单文件，不建表。
- 其他卡都设计成不要迁移：
  - K2 的工具摘要存在现有 `arslan_messages` 里；
  - S1 和 S4 用现有的权限规则表和授权表；
  - S5 用设置键值。
- 需要迁移号时，向 ②Main 申请，②Main 在上表登记，规则见 `docs/sessions.md` §4。

## 6. 开工前

1. **用户：** 看过本表和任务卡，点头。
2. **用户：** 定热修版的版本号（更正 E1）。建议 v0.1.62；执行内核版随之顺延为 v0.1.63。
3. **用户，开工前顺带定这几件：**
   - **800 行规矩的例外**（§3）：只做整份删除、不夹带别的改动的 PR，可以超过 800 行吗？
     - 同意的话，F5b、C1b、S2b 不用再拆。
   - **D10 的折中**（更正 E7）：没登记机器时，保留 `ssh_probe` 和 `enroll_node`，只去掉 `ssh_run` 和 `list_nodes`。
     - 不保留的话，就没有办法登记第一台机器。
   - **S5「完全访问」下仍要问的种类：** 卡里默认是付款、安装能力和禁止层。
     - 删除、发送要不要也照问，S5 开工前再定也行。
   - **H1 / H3：** 聊天里 Hands 最多 5 步，是你 10-08 自己定的「D-inline」（更正 E6）。放宽多少，等 ③Hands 交了 H1 由你点头。
4. **⓪Plan：** 开一个只改文档的 PR，把下面这些合进 main：
   - `docs/plans/2026-10-17-0162-*.md`；
   - `docs/plans/0162/**`；
   - `docs/sessions.md`；
   - 根目录的 `CLAUDE.md`。

   用户合了以后，各会话从 main 读到的就是同一份。
5. **把简报发给各会话（§7）。**

## 7. 开工简报（复制粘贴给对应的会话）

### ②Main

```
你是 ②Main，负责 Arslan 0.1.62 的实现和合并协调。

开工前读：
- docs/sessions.md
- docs/plans/0162/README.md
- docs/plans/2026-10-17-0162-execution-first.md（先看「决定记录」和「更正记录」）

你负责 F、C、K、S 四条线，每张卡一个分支、一个 PR，卡在 docs/plans/0162/。
- 第一个做 F5a（CI 解堵）。
- 然后并行做 F1、F2、F3、F4a、F4b 和 C1。
- 热修版的版本号等用户定，定了再做 FR。

规矩：
- 一个 PR 只做一件事，产品代码不超过约 800 行。
- K 线严格按 README §3 的顺序，一次只开一个；每个 K 线 PR 贴 M1 前后对比。
- 合并由用户点。你维护 README 的「状态」列和迁移号登记表。
- 要改 ③Hands 的文件或 Bridge 帧格式时，先停下来问。
- 新想法记进 README §8「0.1.63 候选」。
- 不写本机路径和隐私；草稿区不算交接。

每合一个 PR：更新状态列，附 PR 号和 CI run id。
热修版打 tag 前，先问用户。
```

### ③Hands

```
你是 ③Hands。0.1.62 里你只做三件事，加上审稿。

开工前读：
- docs/sessions.md
- docs/plans/0162/README.md

1. H1：书面回答「聊天里 Hands 最多 5 步（server/registry/hands_tools.py 的 INLINE_ACTIONS）防的是什么」，
   并建议放宽到多少、或改成按时长。K4 开工前交。
2. H2：所有没执行的 Hands 结果，返回固定列表里的代码和 executed: false。
   F2 要用这个列表，所以尽量在 F2 之前合。
3. H3：K4 合了以后，按 H1 的结论改聊天上限。

另外审 F5b（删 Cua Driver 引擎），以及任何改你文件的卡。
本版不新增 Hands 能力。卡在 docs/plans/0162/H*.md。合并由用户点。
```

### ⓪Plan（M 线）

```
你是 ⓪Plan。按 docs/plans/0162/M1、M2、M3 三张卡做跑分升级、本机周报脚本和体感验收清单。
M1B 的基线等热修版发布后，由用户在本机用自己的 key 跑。
另外：维护总计划和本表；发版前对照总计划 §5 判定门槛。
```

### ①iOS

```
告知：Mac 端 0.1.62 不改 Bridge 帧格式。
如果某张卡发现必须改，②Main 会先来问你。你这边照常推进。
```

## 8. 0.1.63 候选（范围冻结后的新想法）

- 旧的扁平 `llm_*` 设置键：要先写数据迁移才能删（C2c 发现）。
- 读 `~/.agents/skills`：总计划 §3.1 决定放到 0.1.63。
- `click`、`rich` 两个依赖只有旧命令行在用（C2d 发现），删旧命令行后可以去掉。
- 专家时代剩下的 REST 接口：`spawns`、`recipes`、`expert_conversion` 等（C1 发现，本版不动）。
- 设置页加「添加机器」的入口：有了它，没登记机器时连 `ssh_probe` / `enroll_node` 也可以不给（C3b 的折中，见更正 E7）。
- 命令卡改用 `send` / `destructive` / `system` 等种类，手机上的风险词会更准（S2a）。
- 沙箱挡读凭据目录以后，`aws`、`kubectl`、`npm` 等可能读不到配置，按 M2 的数据再细分（S2a）。
- 「不信某个 MCP 服务器的标注」开关（S1）。
- 「记住的回答」页上线后，网站卡和快捷指令卡恢复「总是」（S6，③Hands 审）。
- 计划模式下，允许在只读沙箱里跑命令（S5）。
- 放宽「已成功的同一条命令不能再跑」（F2）。
- 其余见领先路线 §3、§4 的 0.1.63 列：
  - 卡片界面与文案大合并（D1）；
  - diff 预览；
  - 网络出口控制；
  - 子 agent 统一成一个工具；
  - 后台进程与进程工具；
  - 目标模式；
  - ACP。
