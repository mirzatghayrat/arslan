# CAP 按需加能力：能力页、安装卡、插件

> 草稿（⓪Plan 2026-10-29 夜间起草），用户批准 v0.1.64 计划之前不开工。

| 项 | 内容 |
|---|---|
| 道 | ②Main（⓪Plan 的建议。②Main 卡太多，开工前可能分给新开的会话，见 `docs/plans/0164/README.md` §5） |
| 版本 | v0.1.64 |
| 分级 | 必须（用户 2026-10-21 定，U13 第 2 条；10-28 的八条；10-27 的 Hermes 表里 v0.1.64 的三行） |
| 依赖 | **硬依赖 SBX（沙箱默认拒绝）**：跑陌生代码的 PR（CAP5 的命令规则、CAP6 的「模型不可写」、CAP10 verify，以及插件里的脚本）都排在 SBX 合并之后，没有例外。S1、S7 已在 v0.1.63 合并（10-21 安全底线的前提已满足）。CAP2 和 C7c 都碰 `expert_conversion.py`，谁先合另一个 rebase。CAP3 的「专业工作方法」并进技能列表，和 SUB 一起改。#432 定了以后可能改 CAP5 的命令规则放在哪一层 |
| 合并位置 | 按 `docs/plans/0164/README.md` §4：SBX（和 S2a-3）之后。CAP1–CAP3 不跑陌生代码，#432 采纳「情况 B」时可以先做；CAP4 起按编号顺序 |
| 推动的门槛 | 10-21 安全底线全部落地；10-28 八条（⑤ 等用户点头）；Hermes 表的 security / verify / import-agent 三行；`sessions.md` §11（同版删掉被替换的发现中心、创建技能页、候选表和评估门；`curator.py:28` 的 `DELETE-BY: v0.1.64`）；R64 安全门槛（每个碰安全面的 PR 有 effort=max 审查 + Codex 审查） |
| 分支 | `claude/0164-cap<N>-<主题>`，每个 PR 一条，例如 `claude/0164-cap1-remove-discovery` |
| 迁移号 | 预计两个，开工时向 ②Main 申请（main 上最新是 0070）：CAP1 删 `discovery_candidates`（和 `capability_finds`，看「开工前要用户定的」第 2 条）；CAP2 删 `skill_candidates`。CAP7 尽量用现有 JSON 列，不加迁移 |

## 目标

- 能力页只回答一件事：「Arslan 现在会什么」。装新东西在对话里说，或者贴链接，走安装卡。
- 安装卡把 10-21 的安全底线做全：来源白名单、钉版本、在钉的版本上读许可证和扫描、显示要什么权限、OSV 漏洞检查。
- 收插件（Claude Code 的格式，Codex 同理），拆出技能和连接；带钩子的整个不装。
- 读 `~/.agents/skills`，把 Claude Code / Codex 的技能、插件和 MCP 配置导进来（Hermes 表的 import-agent）。
- 加 `verify`：找出项目怎么运行，在沙箱里跑一遍冒烟测试（Hermes 表）。
- **同一版删掉**被替换的东西：能力发现中心（RepoDossier 长文、ToolHub 页签、收藏、打分）、「创建技能」页、技能候选表和评估门、整理器。
- 模型写的技能在任何时候都要过人这一关：v0.1.64 用过渡卡（完整 SKILL.md、用户点「可以」才启用、带脚本的直接拒）；「待你看」是 v0.1.65 的事，本卡不做。

## 现状（读 main `8db45ef9` 核过）

- **能力页**（`web/src/components/Capabilities.tsx`）有五个标签：能力开关（`:69`、`:80`）、「技能与工作流」（`:70`，里面是专业工作方法 `:102`、导入面板 `:108`、技能目录 `:110`）、连接（`:72`）、发现（`:73`、`:86-92`，ToolHub 搜索加右边的 FoundRail）、旧专家（`:75`）。「创建技能」按钮（`:95-98`）切到 SkillForge（`:114`）。
- **用词**：`web/src/locales/capabilityList.ts:41` 中文分组「方法（技能）」，`:53` 来源「内置」「MCP 服务」「方法」；`web/src/locales/workspace.ts:66` 「技能与工作流」（六种语言 `:27`、`:66`、`:105`、`:144`、`:183` 等）。
- **安装链**已经有：找（`capability_search.py`，官方 Registry、GitHub、`SKILL_LIBRARIES = ("anthropics/skills",)` `:45`）→ 卡（`capability_flow.py:50-66`）→ 装（`capability_install.py`，PyPI 只装 wheel、npm `--ignore-scripts`、装完是关着的 `:13`）→ 扫（`capability_scan.py`）→ 试（`capability_flow.py:94-120`）→ 开。MCP 跑在 `capability_sandbox.py` 的默认拒绝 seatbelt 里。
- **10-21 列的洞，代码里都还在：**
  - 许可证读的是 HEAD（`capability_install.py:84-96`，README 写的 `:83-95` 差一行）；
  - Registry 的条目不看 `status`，删除了的也会出现（`capability_search.py` 的 `from_registry` 没有任何状态判断）；
  - 一键装的 MCP 共用一个下载缓存（`capability_install.py:128` 的 `uv-cache`、`:145` 的 `npm-cache`）；
  - `/discovery/skills/import` 不扫描（`server/api/discovery.py:134-142`）；
  - 第三方技能的 description 进了 `read_skill` 的工具说明（`server/orchestrator/arslan.py:1006-1023` 拼索引，`:1272-1276` 放进工具描述）；
  - 没有工具列表哈希。
- **模型写技能**：`create_skill` 只写一行候选（`server/registry/executors.py:585-614`），人在 SkillForge 页上批（`skill_forge.py:91-117`）。它今天不在主 agent 的工具里（C3 卡 `:76`，`arslan.py` 的 `_every_tool` 里没有）。返回文字还写着「评估之后」（`executors.py:611-612`），可评估门早就没了（`skill_forge.py:4-6`）。
- **手机**：能力卡不发到手机（`docs/specs/mobile-bridge-protocol.md:283`；服务端 `server/ws/arslan.py:491-502` 用 `broadcast=False`。S7 卡写的 `:632-640` 已经挪了位置）。
- **还没有的**：读 `~/.agents/skills`、读插件包、导入别的工具的设置、OSV 检查、verify，`git grep` 都查不到。`arslan.plugin.json`（`plugin_manifest.py`）是 2026-08 自己定的第三方格式，和 Claude Code 的插件不是一回事。

## README 和代码对不上的地方

1. **技能装到哪。** README 写「装进 `~/.agents/skills`」。今天技能装进数据库（`SkillPack`，`skill_import.py:327-332`），脚本放在数据目录的 `skill_scripts/<key>/`（`skill_import.py:281`）。这不是改个路径，是换存储，见「开工前要用户定的」第 3 条。
2. **脚本只经 `run_python`。** 10-21 写「只经 `run_python` 跑（禁网）」。可 `run_python` 今天不在主 agent 的工具里（C3 卡 `:76`），导入的技能正文却还在叫模型用它（`skill_import.py:316-320`）。实际上，主 agent 只能用 `run_command` 跑技能脚本。见第 4 条。
3. **①要删的不止 ②Main 列的那些。** 「页面上不放搜索框」以后，页面自己的搜索和安装也没有调用方了：`/capability-search`、`/capability-candidates/check`、`/capability-candidates/install`、`/projects/{id}/capability-material`（`server/api/capabilities.py:32`、`:88`、`:103`、`:161`），`capability_dossier.py` 里存页面候选的那部分，`CandidateDossier.tsx`。还有喂 FoundRail 的 `capability_lookahead.py`（`project_plan.py:251-253` 调它）。这些都列进 CAP1。
4. **按名字查残留，会多出几处。** `mcp_suggest`、`skill_suggest` 还作为字符串出现在 `server/api/usage.py:43-49` 的 `NOT_COVERED` 里，`skill_suggest` 还出现在 `arslan/skills/skillpack.py:4` 的说明里。`plugin_manifest.py`、`github_eval.fetch_file` 和 `MANIFEST_PATH`（`github_eval.py:140-165`）只有 `discovery_service` 在用，要一起删。`App.tsx:36` 从 `CandidateDossier` 里导入 `START_PROJECT_EVENT`，删之前要先把这个常量挪走。
5. **删 `skill_candidates` 表还牵着两处。** seeder 靠 `SkillCandidate.promoted_at` 认出「用户自己的技能」（`server/registry/seeder.py:85-95`，D7）。`run_redact.py:12`、`:50` 也读这张表。迁移要先把升过级的那些技能换一种标法，再删表。
6. **`expert_conversion.py`** 在 README 里是 CAP 的线头（`:57-59`），可它也在 C7c「旧专家转技能页」的删除范围里（`docs/plans/0164/README.md` §3.3）。C7c 先合，这个线头就自己没了。

## 拆成的 PR

每个 PR 产品代码不超过约 800 行（测试、翻译、生成的文件不算）。只做整份删除的（CAP1）照 U2 例外。**标「安全面」的：effort=max 写，effort=max 审，再加一道 Codex 审查**（`docs/plans/0162/README.md` §8「v0.1.64 的安全审查路径」：只看公开仓库、只读、结论写明模型、每一条都要在 PR 上回应）。

| PR | 做什么 | 安全面 | 依赖 | 量级（产品代码） |
|---|---|---|---|---|
| CAP1 | 删能力发现中心（服务端加网页）和 FoundRail | 只有 `capability_flow.py` 剪线那几行 | 用户定第 2 条 | 约 −2,500 / +50（U2） |
| CAP2 | 删「创建技能」页、候选表、整理器；`create_skill` 改成过渡卡 | 是 | CAP1；C7c（软） | 约 −900 / +250 |
| CAP3 | 能力页只列「会什么」；用词改成 自带 / 技能 / 连接；方法并进技能 | 删除按钮的规则是 | CAP1、CAP2；SUB（方法那半） | 约 ±600，净减 |
| CAP4 | 安装卡的安全底线（一）：卡面、来源白名单、钉版本、在钉的版本上读许可证和扫描 | 是 | CAP1 | 约 +600 |
| CAP5 | 安全底线（二）：运行时补洞 | 是 | CAP4；**SBX**；#432 | 约 +400 |
| CAP6 | 技能目录：装进 `~/.agents/skills`、读它、模型不可写 | 是 | CAP4；**SBX** | 约 +500 |
| CAP7 | 插件包：拆出技能和连接，带钩子的不装 | 是 | CAP4–CAP6 | 约 +700 |
| CAP8 | 导入 Claude Code / Codex 的设置，含 MCP 配置（import-agent） | 是 | CAP6、CAP7 | 约 +500 |
| CAP9 | 安装卡上的 OSV.dev 漏洞检查 | 是（卡面） | CAP4 | 约 +250 |
| CAP10 | `verify`：找出怎么运行，在沙箱里跑冒烟测试 | 是 | **SBX** | 约 +400 |
| CAP11 | ⑤ iPhone 能看安装卡、不能批（**用户点头才做**） | 是（Bridge 帧） | 用户定第 1 条；①iOS | 约 +150 Mac 端 |

## 改哪些文件

### CAP1 删能力发现中心

- **删（服务端）：** `server/api/discovery.py` 里 `search`、`evaluate`、`/catalog` 四个路由、`skill/generate`、`skill`（`:23-108`）；`server/services/discovery_service.py`、`mcp_suggest.py`、`repo_overview.py`、`skill_suggest.py`、`plugin_manifest.py`；`github_eval.py` 的 `fetch_file`、`MANIFEST_PATH`（`:140-165`）；`DiscoveryCandidate` 模型和表（迁移）。
- **删（页面自己的找和装，见上面第 3 条）：** `server/api/capabilities.py` 的 `/capability-search`、`/capability-candidates/*`、`/projects/{id}/capability-material`，`capability_dossier.py` 里页面候选那部分；`capability_lookahead.py` 和 `project_plan.py:251-253` 那处调用。
- **FoundRail（按用户定的第 2 条）：** ⓪Plan 建议删掉 `/capability-finds*`、`CapabilityFind` 表、`capability_flow.record_find`。没人可问时（`capability_flow.py:238-247`），工具结果改成让模型在回答里说「缺 X，回到对话里说一声就能装」。`refuse_unattended` 和账本那两行不动。
- **删（网页）：** `Capabilities.tsx` 的发现标签和 `saved`；`ToolHubDiscover.tsx`、`RepoDossier.tsx`、`SavedCandidates.tsx`、`capabilities/DiscoverResults.tsx`、`capabilities/CandidateDossier.tsx`（先把 `START_PROJECT_EVENT` 挪出来，`App.tsx:36`）、`capabilities/FoundRail.tsx`；`web/src/api/discovery.ts` 里除 `skills/scan`、`skills/import` 以外的部分；`web/src/api/capabilities.ts` 里对应的方法；对应的测试和六种语言的 key。
- **字符串残留：** `server/api/usage.py:43-49` 去掉 `mcp_suggest`、`skill_suggest`；`arslan/skills/skillpack.py:4` 的说明。
- **留：** `skills/scan`、`skills/import`（`discovery.py:123-142`，导入面板在用）、`github_eval`（`capability_search` 和 `skill_import` 在用）、`find_capability`、`propose_capability`、手动添加 MCP 的表单。
- **重新生成** `docs/CAPABILITY_INVENTORY.md`（`sessions.md` §3）。

### CAP2 删「创建技能」页，`create_skill` 改成过渡卡

- **删：** `web/src/components/SkillForge.tsx`；`Capabilities.tsx` 的 forge 标签和按钮（`:95-98`、`:114`）；`workspace.createSkill` 等 key（六种语言）；`server/api/skills.py` 的 forge、candidates、promote、reject、curator 路由；`server/services/curator.py`（`:28` 已写 `DELETE-BY: v0.1.64`）；`skill_forge.py` 的 `create_candidate`、`promote_candidate`、`reject_candidate`、`list_candidates`；`SkillCandidate` 模型和表（迁移）；`run_redact.py` 里读这张表的那段。
- **留：** `skill_forge.validate` 和 `MAX_SKILL_BYTES`。`skill_import.py:32` 和 `expert_conversion.py` 在用，按调用方拆，不整个删。
- **迁移：** 先把 `promoted_at` 有值的候选对应的 `SkillPack` 标成「用户的」（标法开工时定，用现有的列），再删表；同时改 seeder 的 `_USERS_SKILL`（`seeder.py:85-95`），D7 的测试照旧要过。
- **`expert_conversion.py:57-59`：** C7c 先合就不用管。CAP2 先合的话，`convert` 改成直接写 `SkillPack`（用户点「转换」本来就是人这一关）。
- **过渡卡（安全面）：**
  - `create_skill`（`executors.py:585-614`）改成出卡：卡上是完整的 SKILL.md，用户点「可以」才写进 `SkillPack` 并启用。带脚本或附件的直接拒，提示等 v0.1.65 的「待你看」。
  - 卡和安装卡走同一个通道（`ws/arslan.py:491-502`，`broadcast=False`），答完写一行账本（`permissions.record_card_outcome`，`permissions.py:307`）。没人可问时走 `refuse_unattended`（`permissions.py:420`），不留草稿。
  - 工具按需给，经 `find_tools` 拿到，不进常驻表（K7）。工具说明里写「用户说『把刚才这套做法存成技能』时用」。
  - 改 `tool_loop.py:2102` 的参数 schema。这是 K 线热点文件，只做小改，排在开着的 K 线 PR 之后。改 `seed_catalog.py:116-121` 的说明。

### CAP3 能力页只列「会什么」

- `Capabilities.tsx` 改成一个列表，不分标签：自带 / 技能 / 连接三组。每项写一句用途、来源（自带 / 你装的 / Arslan 自己写的 / 来自 Claude Code 等），带开关、删除和最近一次使用的时间。
- 保留 `CapabilityFilter`（#62，用户 10-28 定），只筛已装的，不联网。
- 手动添加 MCP 的表单（`McpServers.tsx`）放进「连接」的详情里。「MCP」只在详情里出现。
- 导入面板（`SkillImportPanel.tsx`）留着，改名「贴一个链接」。
- `capabilityList.ts` 的分组和来源标签（`:6`、`:18`、`:41`、`:53` 和另外四种语言）改成 自带 / 技能 / 连接。`addMethod` 那几行（`:65` 等）改成「在对话里说『存成技能』」。
- `workspace.ts` 的 `skillsWorkflows` 改成「技能」，六种语言一起改。
- 「专业工作方法」（`companion/ProfessionalMethods.tsx`、`locales/methods.ts`）并进技能列表，和 SUB 卡一起改：谁先合，谁做这一半，另一张卡写明。
- **最近一次使用：** 从现有的运行记录取，不加列。取不到的显示「还没用过」。
- **删除按钮（安全面）：** 只有 Arslan 自己装的才给删除。从别的工具读来的（CAP6、CAP8）只给开关（README A 补的第 3 条）。服务端也要拒，不只是网页不显示按钮。

### CAP4 安装卡的安全底线（一）

- **来源白名单：**
  - 一键卡只给两类 MCP：官方的远程 OAuth 服务器；命名空间属于服务方官方组织的包。
  - 「服务官方」怎么判，⓪Plan 的提议：Registry 命名空间是反向域名（Registry 已验证过），并且远程地址或包的主页在同一个域名下。其余的，包括 `io.github.<个人账号>`，都算第三方，卡上标「第三方」，只提示「请手动安装」。这条判法 effort=max 审。
  - 技能只收 `anthropics/skills` 和用户显式信任过的 GitHub 账号。信任从「贴一个链接」导入成功之后点一下记下，设置里能撤。
  - 不接 ClawHub 一类的开放市场。
  - 过滤 Registry 里 `status=deleted` 的条目（`from_registry` 加判断）。
- **钉版本，卡上显示的就是要装的：**
  - 技能：commit sha 加每个文件的 sha256。扫描挪到出卡之前，在这个 sha 上扫；装的时候再核一遍哈希，对不上就停。今天是先扫 HEAD、装时才钉（`capability_flow.py:145-160`）。
  - MCP：包@版本加锁文件哈希。
- **许可证在钉的版本上读：** `capability_install.source_license`（`:84-96`）改成按 sha 读，不再读 HEAD。
- **卡面**（`capability_flow.card_for`，`:50-66`；网页 `capabilities/CapabilityProposeCard.tsx`）：
  - 发布者，标「服务官方 / 第三方」；钉的版本和摘要；
  - 技能：扫描命中放最上面标红，下面是可以展开的全文和脚本清单；
  - MCP：启动命令、本地还是远程、要哪些文件夹、要不要网络（要的话写明「可访问任何网站」）、要哪些钥匙。
- **扫描规则：** `capability_scan.py` 加一条「叫人或 agent 去下载、执行」的句子（ClawHavoc 走的就是这条路）。具体写法只放在测试里。

### CAP5 安全底线（二）：运行时补洞

- **`read_skill` 的工具说明：** 第三方技能只放名字，不放 description（`arslan.py:1006-1023`）。
- **工具列表哈希：** 第一次测试通过时（`capability_flow.test_mcp`，`:94-120`）记下工具列表的哈希。之后启动时变了，就停用并重新出卡。存进 `CapabilitySource.test` 这一类现有 JSON 列。
- **独立缓存：** 一键装的 MCP 用自己的缓存目录，不再共用 `uv-cache`、`npm-cache`（`capability_install.py:128`、`:145`）。
- **手动添加的 MCP 钉版本：** 表单里没写版本的 `npx` / `uvx` 包，查出当前版本写死，查不到就拒。
- **`/discovery/skills/import` 补扫描**（`discovery.py:134-142`），扫描结果和卡上的一致。
- **命令规则（依赖 SBX，层次看 #432）：** `run_command` 里引用第三方技能目录（数据目录的 `skill_scripts/`、`~/.agents/skills`、插件目录）时，每次都出卡，只给「这一次」，断网，并且当作读过外部内容。这条和 S2a-3 / SBX 的命令判定是同一层，③Hands 要审。

### CAP6 技能目录

- 按用户定的第 3 条：Arslan 装的技能落到 `~/.agents/skills/<名字>/`（开放标准）。数据库里只留索引和每个文件的哈希。哈希放在 Arslan 的数据目录里，不放在技能文件夹里。
- 启动时读 `~/.agents/skills`：别的工具放进来的，显示「来自其他工具」，只给开关、不给删除，第一次启用前出卡（卡面同 CAP4）。
- 哈希对不上（文件被改过）就停用并重新出卡。
- **模型不可写（硬依赖 SBX）：** 技能目录、插件目录、MCP 配置（今天是数据库里的 `mcp_servers` 表，`capability_install.py:300-310`，所以就是数据目录）对模型的所有写路径都是硬拒：`write_file`、`edit_file`、`run_command`，用户点头也不行。测试按「每一条写路径各打一次」来写。
- **已经导入的技能**（`SkillPack` 里 `category="imported"` 的和带 `source_id` 的）：按用户定的第 3 条，一次性导出到技能目录，或者留在数据库并写 `DELETE-BY`。

### CAP7 插件包

- 读 Claude Code 的 `.claude-plugin/plugin.json`（Codex 的插件同理，开工时回源核格式），拆出技能和 MCP。
- **按允许清单收：** 只认技能和 MCP。钩子、斜杠命令、agent 定义、认不出的部分，有一样就整个不装。带钩子的，卡上写「要靠自动运行的钩子工作，现在还不支持」（钩子支持排在 v0.1.65 之后；agent 定义等 SUB，即 C 那条）。
- **README A 补的四条：**
  1. 来源白名单按插件自己的仓库查，不按市场查；各部分取最严的，一部分不过，整个插件改为「请手动安装」。
  2. 整个插件钉 commit sha 加每个文件的哈希，放在一个文件夹里（因为 `${CLAUDE_PLUGIN_ROOT}`），路径不能跑出这个文件夹。`.mcp.json` 里没钉版本的 `npx` 钉上固定版本，钉不了就拒装。
  3. 只删 Arslan 自己装的（CAP3 的规则）。
  4. 工具列表的哈希变了，整个插件停用；许可证复用 `skill_import` 的检查；里面的技能和已有技能重名就拒装，不覆盖；插件带的 MCP 显示在插件下面，不进手动添加的表。
- 整组安装、整组开关、整组删除，不提供单独关掉插件里的某个技能（用户 10-28 定）。
- 插件里的 MCP 照样进 `capability_sandbox`；插件里的技能脚本照样只能按 CAP5 的规则跑。
- **存法：** 用 `CapabilitySource`，`kind="plugin"`，各部分放进现有 JSON 列。要加列就向 ②Main 申请迁移号。

### CAP8 导入 Claude Code / Codex 的设置（import-agent）

- 读 Claude Code 的技能目录和插件目录、它的 MCP 配置，以及 Codex 的 MCP 配置。各家的路径和格式开工时回源核，不凭记忆写。
- 读到的技能和插件按 CAP6、CAP7 处理：只给开关、不给删除；第一次启用前出卡；带钩子的照样拒。
- **MCP 配置**每个服务器一张卡，卡面同 CAP4。本地的进 `capability_sandbox`，没钉版本的钉上或拒。
- **钥匙：** 配置里的环境变量可能是真钥匙，由服务端直接读、加密存（同 `capability_install.py:304-305`）。不进模型上下文，不进账本，不显示在卡上（卡上只写「带了 N 个钥匙」）。
- 这一切只在用户点「导入」时做。模型不能触发，也不能读这些文件。

### CAP9 OSV.dev 检查

- 新建 `server/services/osv_check.py`，向 OSV.dev 的批量查询接口发包名、生态和版本（不发任何用户数据）。
- **出卡时**查要装的那个包；**锁文件生成之后、任何东西运行之前**（PyPI 只装 wheel、npm 不跑脚本，所以这一步还没有执行过代码），把锁里的全部依赖查一遍。
- 卡上一行「已知漏洞：无 / N 个（最高 X 级）」，可以展开看编号。命中以后怎么处理按用户定的第 5 条。
- 技能没有依赖清单，卡上写「技能不查依赖漏洞」。插件里的 MCP 照样查。
- OSV 连不上就写「没查成」，不当成「没有漏洞」。

### CAP10 verify（只在沙箱里跑）

- 一个按需给的工具（经 `find_tools`）：给一个文件夹，先读出怎么运行（`package.json` 的 scripts、`pyproject` / pytest、Makefile 等，按允许清单认），再在 SBX 的默认拒绝沙箱里跑一遍冒烟测试，返回命令、退出码和输出的结尾。
- 只在副本或者只给这个文件夹写权限；默认断网。缺依赖时报「需要装依赖」，要联网就出卡，只给「这一次」。
- 跑的是陌生代码，**SBX 没合，这个 PR 不开**。

### CAP11 ⑤ iPhone 能看、不能批（用户点头才做）

- 能力卡（安装卡和 CAP2 的过渡卡）发到手机，手机上只显示，按钮是「回到 Mac 上确认」。
- Mac 端拒绝手机发来的这类批准（服务端判，不靠手机不显示按钮）。
- 改 Bridge 帧：`docs/specs/mobile-bridge-protocol.md:283` 那句改写；改 `server/ws/bridge.py`、`spec/mobile-bridge/**` 的向量。①iOS 做手机端。和 Q1、SUB 的帧改动合成一次问用户（`docs/plans/0164/README.md` §2 第 3 条）。

## 不许碰

- SBX 的沙箱规则本身、S2a-3 的命令三层（③Hands）。CAP5、CAP6、CAP10 用它们，不改它们。
- Bridge 帧：用户点头之前一个字段都不加（CAP11 之外的 PR 都不碰）。
- 钩子支持、预装哪些技能、推荐哪些 MCP：v0.1.65 之后那一轮。
- 「待你看」和学习循环（自动写技能）：v0.1.65。
- 插件里的 agent 定义：等 SUB 合了再接（C 那条）。
- lsp、worktree 清理：Hermes 表里排在「以后」。
- `server/mcp/discovery.py`：名字陷阱，它是列 MCP 服务器工具的，和发现中心无关。CAP1 不碰它；查残留时不能只搜「discovery」。
- K 线热点文件（`arslan.py`、`tool_loop.py`）：只做小改，排在开着的 K 线 PR 后面。
- 定时任务、收件箱（INB 卡）。

## 怎么做（要点）

1. **先删后加。** CAP1、CAP2 删干净，`git grep` 的结果贴在 PR 里：逐个名字 `git grep -w` 查，再按字符串查一遍（路由路径、注册表的键、翻译键、`usage.py` 那种名字列表）。
2. **每个安全面 PR 先写打不过去的测试：** 今天能装 `status=deleted` 的条目、扫的是 HEAD、`read_skill` 里有第三方的 description、模型能写技能目录、带钩子的插件能装上一半……先红后绿，再做 mutation（改回去，测试要红）。
3. **卡和安全文案定稿后，先发云端审计看**（10-21 定的），再交 Codex 审合并前的头。
4. **危险的写法只放在测试里**，PR 描述和卡里只写「哪一类」。
5. **每个 PR 都写完成证据四项**（`sessions.md` §8），说 CI 绿要附 run id 和结论。

## 验收

- **CAP1：** 能力页没有发现标签和收藏；`git grep -n 'discovery_service\|mcp_suggest\|repo_overview\|skill_suggest\|plugin_manifest\|DiscoveryCandidate\|RepoDossier\|ToolHubDiscover\|SavedCandidates\|FoundRail\|capability_lookahead'` 在 `server arslan web/src scripts` 里查不到（按第 2 条留下的除外）；`skills/scan`、`skills/import` 照旧能用；迁移测试过。
- **CAP2：** 没有「创建技能」页；`git grep -n 'SkillCandidate\|promote_candidate\|curator'` 查不到（迁移文件和历史迁移除外）；对话里说「把刚才这套做法存成技能」出卡，卡上是完整的 SKILL.md；点「可以」才出现在技能列表；拒绝、过期、没人可问各写一行账本；带脚本的直接拒；D7 的测试照旧过。
- **CAP3：** 能力页一个列表，三组；六种语言里没有「工作流」「方法（技能）」「MCP 服务」这几个标签；从别的工具读来的那项，服务端拒绝删除（测试打接口）；`locale-parity` 过。
- **CAP4：** 每一条白名单规则各一条正、反测试；卡上的 sha 等于装上的 sha（测试：两次请求之间仓库 HEAD 变了，装的仍是卡上那个，或者停下）；许可证在 sha 上读；`status=deleted` 不出现。
- **CAP5：** `read_skill` 的说明里没有第三方 description；工具列表变了就停用并出卡；两个一键装的 MCP 用不同的缓存目录；手动添加的没钉版本的包被钉上或拒绝；`/discovery/skills/import` 命中高危就拒；命令规则的测试：引用技能目录的命令每次出卡、断网、带外部内容标记。
- **CAP6：** `~/.agents/skills` 里别的工具放的技能出现在列表上，只能开关；模型从每一条写路径写技能目录、插件目录、数据目录都被拒（用户点头也不行）；文件改了就停用。
- **CAP7：** 不带钩子的插件完整可用；带钩子、斜杠命令、agent 定义或认不出部分的，整个不装，什么都不留；`.mcp.json` 没钉版本的被钉上或拒装；重名拒装；整组开关和删除。
- **CAP8：** 一台装了 Claude Code 的测试机上（用假的配置文件，不用真钥匙），导入以后技能、插件、MCP 都在列表上；钥匙不进模型上下文、账本和日志（测试断言）。
- **CAP9：** 用一个已知有漏洞的旧版本测试包（测试里打桩，不连真网），卡上显示编号；OSV 连不上时卡上写「没查成」。
- **CAP10：** 在 SBX 沙箱里跑一个小项目的测试，结果回来；项目试图联网、写文件夹外面，都被拒。
- **CAP11（若做）：** 手机上看得到卡，批不了；Mac 拒绝手机发来的批准（测试）。
- **整卡：** M3 式手动验收一次：对话里缺能力 → 找到 → 卡 → 装 → 用上，DeepSeek 和 Claude 各一遍；能力页、iPhone（若做 CAP11）截图。

## 量级

合计产品代码约 −3,400 / +3,800（CAP1–CAP10），净数接近持平，主要看 CAP1 删多少。测试另算，安全面的测试会比产品代码多。CAP1 一个 PR 就超过 800 行，但只做整份删除，照 U2 例外。

## 风险与回退

- **风险：** 删 FoundRail 以后，后台任务找到的能力没地方看了。缓解办法见第 2 条。
- **风险：** 「服务官方」的判法太松就放进第三方，太严就什么都只能手动装。上线前拿 Registry 现有条目试一遍，在 PR 里写明有多少被判成官方。
- **风险：** 改存储（CAP6）丢了用户已经装的技能。导出前先备份；导出后核数量和哈希。
- **风险：** import-agent 读别的工具的配置时碰到真钥匙。只由服务端读，测试断言钥匙不进上下文、账本、日志；开发时只用假配置。
- **风险：** CAP5 的命令规则和 #432、S2a-3 撞车。#432 定了以后再写这一节。
- **风险：** ②Main 负载太大。CAP 可以分给新会话；砍范围的话，⓪Plan 建议的顺延顺序是 CAP10 → CAP8 → CAP7（用户 10-27、10-28 同意过 v0.1.64 做，顺延要用户逐条点头）。
- **旧路径：** 过渡卡本身就是过渡，代码注释写 `DELETE-BY: v0.1.65 when 「待你看」 lands`。CAP6 如果把已导入的技能留在数据库，写 `DELETE-BY: v0.1.65`。其余的删除都在同一版做完，不留兼容路径。
- **回退：** 每个 PR 单独 revert。CAP1、CAP2 带迁移：revert 代码不回滚表（`runner.assert_supported_schema` 认迁移 id），所以这两个合并前要多审一遍；删的只是发现中心的缓存和候选表，不是用户的技能。

## 开工前要用户定的

1. **⑤ iPhone 能看安装卡、不能批**：这要改 Bridge 帧（今天能力卡根本不发到手机，`mobile-bridge-protocol.md:283`），归你点头。建议和 Q1、SUB 的帧改动一起问一次。不点头的话，CAP11 不做，手机照旧看不到。
2. **后台找到的能力放哪**（FoundRail 删掉以后）：⓪Plan 建议不再存，没人可问时模型在回答或任务结果里说一句「缺 X，回到对话里说一声就能装」；项目开新关时的预判（`capability_lookahead`）整个删。另一种做法：放进收件箱的「要你做」（INB 卡），但那就是一条推荐，和「不推荐」有点冲突。
3. **技能装到哪**：README 说 `~/.agents/skills`，今天在数据库加数据目录。⓪Plan 建议新装的落到 `~/.agents/skills`，哈希记在 Arslan 的数据目录里。已经导入的技能在同一版一次性导出过去（§11），不留两套。
4. **技能脚本怎么跑**：10-21 写「只经 `run_python`」，可 `run_python` 已经不在主 agent 的工具里（C3）。两种做法：只给技能脚本把 `run_python` 加回来（断网的离线沙箱）；或者不加，只靠 CAP5 的 `run_command` 规则（每次出卡、断网）。⓪Plan 倾向第一种，更窄。
5. **OSV 查到已知漏洞以后**：拦，还是只提示？⓪Plan 建议：要装的那个包本身有已知漏洞，默认按钮改成「不装」，你仍然可以装；依赖里有的，只列出来。
6. **`arslan.plugin.json`（2026-08 自己定的第三方格式）跟发现中心一起删**：改收 Claude Code 的插件格式以后它没用了。确认一下。
7. **过渡卡**（存成技能时出卡、带脚本的直接拒）是 ②Main 提、⓪Plan 同意的，你可以改。
8. **这张卡给谁做**：②Main 已经排满，建议开一个新会话专做 CAP（像 v0.1.63 的 ⑤C6、⑥C7）。
