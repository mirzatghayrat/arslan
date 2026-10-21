# C9 自带技能只留两个；删掉 MCP 推荐目录

| 项 | 内容 |
|---|---|
| 道 | ③Hands（⓪Plan 2026-10-21 分；不是 Hands 的文件，由 ②Main 审） |
| 版本 | v0.1.63 |
| 分级 | 应该（用户 2026-10-21 定，U13 第 3 条） |
| 依赖 | **D7 先合**（否则退役会连带删掉用户导入的同名技能） |
| 合并位置 | 不进 K 线严格链；**C7 第二步里删 `arslan/spawn` 的那个 PR 之前合**（自带技能今天放在 `arslan/spawn/seeds/`）；和 C3a 谁先合，另一个 rebase（两边都删 deck 技能） |
| 推动的门槛 | 用户 2026-10-21 定的目标：到 v0.1.65 干净、简单、好用（`docs/sessions.md` §11） |
| 迁移号 | 无（退役走 seeder 的退役名单） |
| 来源 | ④参谋的清理清单 §3：46 个自带技能，近 30 天只读过 4 个；10 个 MCP 推荐全部和自带能力重复 |

## 目标

- **自带技能只留两个：**
  - `designed-html-report`：留着。升级到接近 Claude Code artifacts 的 HTML 质量是新功能，放到 v0.1.65 之后（README §8）。
  - `skill-creator`：**保留现在的改写版，原样搬进新文件夹，只加出处说明**（用户 2026-10-21 定，经 ④参谋转，U13 补充）。上游原文是给 Claude Code 写的，要模型跑 `claude -p`、开子 agent、跑评测脚本，这些 Arslan 都没有；Arslan 的种子解析也要求 `version` 字段，原文没有。
    - 照 Apache-2.0 §4 的最低要求：附上许可证全文（上游的 `LICENSE.txt` 放在技能旁边，或 `THIRD_PARTY_NOTICES.md` 里引全文）；改过的文件写明改过（SKILL.md 开头一句：改写自 Anthropic 的 skill-creator，Apache-2.0，`github.com/anthropics/skills` 的 `dbd4588f`，`skills/skill-creator`；改了什么：缩短、翻译，去掉 Claude Code 专用的评测工具）；在 `THIRD_PARTY_NOTICES.md` 保留上游的版权行（「Copyright 2026 Anthropic, PBC.」）和出处、提交号。
    - ③Hands 在上游核过：`skills/skill-creator/LICENSE.txt` 在 `dbd4588f` 是 Apache 2.0。
    - 除了出处说明，技能内容不改。
- **其余 44 个退役：**
  - 加进 `seeder.py` 的 `RETIRED_SKILL_KEYS`，老用户的库里开机时删掉。D7 合并后，这只删自带的行。
  - `deck-authoring` 和 `render_deck` 一起删，由 C3a 负责。C9 先合的话，C9 一并退役它。
- **删掉不在目录里的两个文件夹**（`github-eval`、`research`）和没有正文的占位记录（④参谋数到 11 行，开工时再核）。
- **两个留下的技能搬出 `arslan/spawn/seeds/`**（例如 `arslan/skills/bundled/`），`seeder.py` 的 `_SEEDS_DIR`（`:21`）跟着改。C7 第二步要整块删 `arslan/spawn`。
  - **`arslan/spawn/skillpack.py` 一起搬**（②Main 审 #284 时发现）。它是 SKILL.md 的格式定义，还活着：`seeder.py:13-14` 和 `server/services/skill_suggest.py:7` 都在用。
  - `pyproject.toml` 里打包数据的路径（`:184-190` 一带列着 `arslan/spawn/seeds/`）改成新位置。打出来的包里要有这两个技能：用干净拉取的代码打一次包核对（vendored 构建的规矩）。
- **拆成两个 PR**（③Hands 提出，⓪Plan 同意）：C9a 自带技能；C9b MCP 推荐目录。C9b 要改 `arslan.py`、`tool_loop.py`（K 线的热点文件），等 K5（#294）合并后、K7 开工前合。
- **MCP 推荐目录全删（C9b）：** `server/mcp/catalog.py` 的 `CONNECTORS`（10 条），以及网页上展示推荐的地方。
  - **连同模型的 `suggest_connector` 工具一起删**（③Hands 发现）：它只推荐目录里的连接器，目录空了它只会回答「没有」。一起删的还有它在 `arslan.py` 的说明、`tool_loop.py` 的参数表和分支、网页的 `propose_connect_mcp` 卡、`RecommendedMcp`、`GET /mcp/catalog`、`connectorCatalog.json`。
  - 不单独跑门槛：目录空了以后这个工具只能回答「没有」；K7 的门槛会量删掉它以后的工具表。PR 里写明。
  - 手工分级的 Playwright 工具档（`MANUAL_TIERS`）管的是已装的服务器，留着。
  - **你已经装好的 MCP 一律不动。**
  - 加 MCP 走 `find_capability`（它查官方 MCP Registry）和手动添加的表单。
  - 以后预装哪些技能、推荐哪些 MCP，放到 v0.1.65 之后单独开一轮再定（用户 2026-10-21 定，README §8）。
- **署名回源核：** `server/registry/seed_catalog.py` 开头写着目录来自 Hermes Desktop。删完之后，还留在目录里的条目（工具集说明等）逐条回 Hermes 的仓库核对出处。要署名的，在 `THIRD_PARTY_NOTICES.md` 补上（Hermes 是 MIT）。

## 不许碰

- 用户导入的技能、用户的 MCP 配置；`skill_import`（带许可证检查）；`find_capability`；手动添加 MCP 的表单。
- 能力发现中心的其他页面：归 v0.1.64 的「按需加能力」，那张卡同版删它们（§11 第 1 条）。

## 验收

- **测试：**
  - 自带技能只剩两个；
  - 旧库升级后，退役的自带行被删，导入的同名行留着（接 D7 的测试）；
  - MCP 推荐目录为空，已装的 MCP 照常连上；
  - `skill-creator` 带出处说明，许可证全文和版权行在仓库里（测试断言 SKILL.md 里有出处那句、许可证文件存在）。
- **PR 里贴：** 每次请求里 `read_skill` 说明的前后字符数（④参谋量到约 4,700 字）；删了哪些文件夹、怎么确认没人引用（`git grep -w` 加按字符串查，§11 第 4 条）。
- 完成证据四项（`docs/sessions.md` §8）。

## 量级

主要是整份删除（技能文件夹），照总计划 U2 的例外，可以超过 800 行。产品代码改动约 50 行。

## 风险与回退

- **风险：** 有用户正在用某个要退役的技能。近 30 天只读过 4 个：`designed-html-report` 留着，`frontend-design` 以后从上游一键装，`architecture-diagram` 和 `plan` 各用过一次。发布说明写明退役了哪些，以及怎么从上游装回来。
- **风险：** 删推荐目录后，新用户找不到 MCP。`find_capability` 会查官方 Registry；M3 里试一次「我想连 Notion」。
- **回退：** revert。退役的种子行开机时才删，revert 后重新种回。
