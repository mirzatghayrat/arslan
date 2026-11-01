# CAP 按需加能力：能力页、安装卡、插件

> ⓪Plan 2026-10-29 夜间起草，用户 10-28 已定分级。v0.1.64 计划（#434）由用户点合并后才开工。
>
> 10-29 按 #434 的审查改过一遍：②Main 指出的「现状」写错、CAP1 会弄坏留下的东西、漏了的死代码、迁移，③Hands 的安全收紧。

| 项 | 内容 |
|---|---|
| 道 | 新开一个会话（用户 10-28 定，为了和 ②Main 并行，见 `docs/plans/0164/README.md` §5）。CAP6b 并进 SBX，归写 SBX 的会话 |
| 版本 | v0.1.64 |
| 分级 | 必须（用户 2026-10-21 定，U13 第 2 条；10-28 的八条；10-27 的 Hermes 表里 v0.1.64 的三行） |
| 依赖 | **硬依赖 SBX（沙箱默认拒绝）**：跑陌生代码或者靠沙箱守边界的 PR，都排在 SBX 合并之后，没有例外。这包括 CAP5、CAP6b、CAP7b、CAP10。**CAP5 还要等 #432**。S1、S7 已在 v0.1.63 合并（10-21 安全底线的前提已满足）。CAP2a 和 C7c 都碰 `expert_conversion.py`，谁先合另一个 rebase。CAP3 的「专业工作方法」并进技能，和 SUB 一起改 |
| 合并位置 | 按 `docs/plans/0164/README.md` §4：SBX（和 S2a-3）之后。CAP1–CAP3 不跑陌生代码，#432 采纳「情况 B」时可以先做。CAP4 起按编号顺序。每张删表的迁移单独一个 PR，排在删代码的 PR 之后 |
| 推动的门槛 | 10-21 安全底线全部落地；10-28 八条（⑤ 等用户点头）；Hermes 表的 security / verify / import-agent 三行；`sessions.md` §11（同版删掉被替换的发现中心、创建技能页、候选表和评估门；`curator.py:28` 的 `DELETE-BY: v0.1.64`）；R64 安全门槛（每个碰安全面的 PR 有 effort=max 审查 + Codex 审查） **Changed (user, 2026-10-28 evening):** Codex only for what a Claude review cannot cover; see v0.1.64 README §1.3. |
| 分支 | `claude/0164-cap<N>-<主题>`，每个 PR 一条，例如 `claude/0164-cap1a-remove-discovery` |
| 迁移号 | 最多五个，开工时向 ②Main 申请（main 上最新是 0070；一个 PR 最多一个迁移）：CAP1b 删 `discovery_candidates`；CAP1c 删 `capability_finds`（`models.py:401`，看「开工前要用户定的」第 2 条）；CAP2b 给升过级的技能换标法、改 seeder，再删 `skill_candidates`；CAP3b 删 `professional_methods`、`professional_method_versions`（或者写 DELETE-BY）；CAP7a 重建 `capability_sources`，让 `kind` 能是 `plugin` |

## 目标

- 能力页只回答一件事：「Arslan 现在会什么」。装新东西在对话里说，或者贴链接，走安装卡。
- 安装卡把 10-21 的安全底线做全：来源白名单、钉版本、在钉的版本上读许可证和扫描、显示要什么权限、OSV 漏洞检查。
- 收插件（Claude Code 的格式，Codex 同理），拆出技能和连接；带钩子的整个不装。
- 读 `~/.agents/skills`，把 Claude Code / Codex 的技能、插件和 MCP 配置导进来（Hermes 表的 import-agent）。
- 加 `verify`：找出项目怎么运行，在沙箱里跑一遍冒烟测试（Hermes 表）。
- **同一版删掉**被替换的东西：能力发现中心（RepoDossier 长文、ToolHub 页签、收藏、打分）、「创建技能」页、技能候选表和评估门、整理器。
- 模型写的技能在任何时候都要过人这一关：v0.1.64 用过渡卡（完整 SKILL.md、用户点「可以」才启用、带脚本的直接拒）；「待你看」是 v0.1.65 的事，本卡不做。

## 现状（读 main `8db45ef9` 核过）

- **能力页**（`web/src/components/Capabilities.tsx`）有五个标签：
  - 能力开关（`:69`、`:80`）；
  - 「技能与工作流」（`:70`），里面是专业工作方法（`:102`）、导入面板（`:108`）、技能目录（`:110`）；
  - 连接（`:72`）；
  - 发现（`:73`、`:86-92`），ToolHub 搜索加右边的 FoundRail；
  - 旧专家（`:75`）。
  - 「创建技能」按钮（`:95-98`）切到 SkillForge（`:114`）。
  - 能力开关旁边那组「加别的」按钮（`CapabilitySwitches.tsx:108-109`，类型在 `:20`）会打开发现和 forge 两个标签。
- **用词**：`web/src/locales/capabilityList.ts:41` 的中文分组是「方法（技能）」，`:53` 的来源是「内置」「MCP 服务」「方法」。`web/src/locales/workspace.ts:66` 是「技能与工作流」（六种语言：`:27`、`:66`、`:105`、`:144`、`:183` 等）。
- **安装链**已经有：
  - 找：`capability_search.py`，查官方 Registry、GitHub 和 `SKILL_LIBRARIES = ("anthropics/skills",)`（`:45`）；
  - 卡：`capability_flow.py:50-66`。**出卡前不扫描任何东西。**
  - 装：`capability_install.py`，PyPI 只装 wheel，npm 加 `--ignore-scripts`，装完默认关着（`:13`）；
  - **先装后扫**：技能先装，再扫装进来的文件（`capability_flow.py:148-160`）；MCP 也是装完才扫（`:128-135`）；
  - 试：`:94-120`；最后开。
  - MCP 跑在 `capability_sandbox.py` 的默认拒绝 seatbelt 里。
- **技能钉在哪个版本：**
  - 技能库（`anthropics/skills`）里的技能，钉在搜索时拿到的 sha（`capability_flow.py:148`）；
  - 其他 GitHub 技能，在安装那一刻读 HEAD 再钉（`skill_import.py:253`）；
  - 「先读 HEAD、后钉版本」出在 `/discovery/skills/*` 这条路上：`scan_skills` 读的是 HEAD 的文件树和内容（`skill_import.py:195`、`:206`），导入时才钉。
- **10-21 列的洞，代码里都还在：**
  - 许可证读的是 HEAD（`capability_install.py:84-96`，README 写的 `:83-95` 差一行）；
  - Registry 的条目不看 `status`，删除了的也会出现（`capability_search.py` 的 `from_registry` 没有任何状态判断）；
  - 一键装的 MCP 共用下载缓存（`capability_install.py:128` 的 `uv-cache`、`:145` 的 `npm-cache`）；
  - `/discovery/skills/import` 不扫描（`server/api/discovery.py:134-142`）；
  - 第三方技能的 description 进了 `read_skill` 的工具说明（`server/orchestrator/arslan.py:1006-1023` 拼索引，`:1272-1276` 放进工具描述）；
  - 没有工具列表哈希。
- **`capability_sources` 表**有 `CHECK (kind IN ('mcp','skill'))`（`server/db/models.py:364`），要收插件就得重建这张表。
- **模型写技能**：
  - `create_skill` 只写一行候选（`server/registry/executors.py:585-614`），人在 SkillForge 页上批（`skill_forge.py:91-117`）。
  - 它今天不在主 agent 的工具里（C3 卡 `:77`；`arslan.py` 的 `_every_tool` 里也没有）。
  - 返回文字还写着「评估之后」（`executors.py:611-612`），可评估门早就没了（`skill_forge.py:4-6`）。
- **`run_python`** 也不在主 agent 的工具里（C3 卡 `:77`）。它的结果标的是 `external: False`（`executors.py:733`），在沙箱起不来时可能联网。
- **手机**：能力卡不发到手机（`docs/specs/mobile-bridge-protocol.md:283`）。服务端在 `server/ws/arslan.py:491-502` 用 `broadcast=False`（S7 卡写的 `:632-640` 已经挪了位置）。
- **找到的能力还连着侧边栏**：`capabilitiesApi.finds()` 给「能力」那一项算角标（`App.tsx:414-417`，传给 `:635`；`Sidebar.tsx:149-151` 画出来）。另外，用户拒绝安装卡时也会调 `record_find`（`capability_flow.py:255`）。
- **还没有的**：读 `~/.agents/skills`、读插件包、导入别的工具的设置、OSV 检查、verify，`git grep` 都查不到。
- **`arslan.plugin.json`**（`plugin_manifest.py`）是 2026-08 自己定的第三方格式，和 Claude Code 的插件不是一回事。

## README 和代码对不上的地方

1. **技能装到哪。** README 写「装进 `~/.agents/skills`」。今天技能装进数据库（`SkillPack`，`skill_import.py:327-332`），脚本放在数据目录的 `skill_scripts/<key>/`（`skill_import.py:281`）。注册表也直接读 `SkillPack`（`skill_forge.py:9-11`、`server/registry/service.py:17`）。这不是改个路径，是换存储，所以拆成 CAP6a。
2. **脚本只经 `run_python`。** 10-21 写「只经 `run_python` 跑（禁网）」。可 `run_python` 今天不在主 agent 的工具里，导入的技能正文却还在叫模型用它（`skill_import.py:316-320`）。实际上，主 agent 只能用 `run_command` 跑技能脚本。CAP5 按 ③Hands 的意见给脚本一条专用路径。
3. **①要删的不止 ②Main 列的那些。** 「页面上不放搜索框」以后，页面自己的搜索和安装也没有调用方了：
   - `/capability-search`、`/capability-candidates/check`、`/capability-candidates/install`、`/projects/{id}/capability-material`（`server/api/capabilities.py:32`、`:88`、`:103`、`:161`）；
   - `capability_dossier.py` 里存页面候选的那部分；
   - `CandidateDossier.tsx`；
   - 喂 FoundRail 的 `capability_lookahead.py`（`project_plan.py:251-253` 调它）。
4. **按名字查残留，会多出几处，还有几处删完会变死代码：**
   - `mcp_suggest`、`skill_suggest` 还作为字符串出现在 `server/api/usage.py:43-49` 的 `NOT_COVERED` 里；`skill_suggest` 还出现在 `arslan/skills/skillpack.py:4` 的说明里。
   - `server/services/prompts/` 下的 `mcp_suggest.py`、`repo_overview.py`、`skill_suggest.py` 只被那三个服务导入。
   - `plugin_manifest.py`、`github_eval.fetch_file` 和 `MANIFEST_PATH`（`github_eval.py:140-165`）、`github_eval.fetch_readme`（`:168`）只有 `discovery_service` 在用。
   - `App.tsx:36` 从 `CandidateDossier` 导入 `START_PROJECT_EVENT`。
   - `Capabilities.tsx:6` 经 `ToolHubDiscover` 导入 `McpPrefill`，它真正定义在 `api/client.types.ts:1041`。
5. **删 `skill_candidates` 表还牵着两处。**
   - seeder 靠 `SkillCandidate.promoted_at` 认出「用户自己的技能」（`server/registry/seeder.py:85-95`，D7）；
   - `run_redact.py:12`、`:50` 也读这张表。
6. **`expert_conversion.py`** 在 README 里是 CAP 的线头（`:57-59`），可它也在 C7c「旧专家转技能页」的删除范围里（`docs/plans/0164/README.md` §3.3）。C7c 先合，这个线头就自己没了。
7. **方法并进技能以后**，`professional_methods`、`professional_method_versions` 两张表（`server/db/worker_models.py:9-16`）README 没提，要一起删，或者写 DELETE-BY。
8. **「代码没有了」不能只按名字 grep**：`seeder.py:89` 的注释里有 `discovery_service`，`models.py:868` 有一个无关的 `curator`（lessons 那个）。验收改成按模块路径和导入语句查。

## 拆成的 PR

- 每个 PR 产品代码不超过约 800 行（测试、翻译、生成的文件不算）。整份删除的部分照 U2 例外，剪线的部分另算。
- **标「安全面」的：effort=max 写，effort=max 审，再加一道 Codex 审查**（`docs/plans/0162/README.md` §8「v0.1.64 的安全审查路径」：只看公开仓库、只读、结论写明模型、每一条都要在 PR 上回应）。 **Changed (user, 2026-10-28 evening):** Codex only for what a Claude review cannot cover; see v0.1.64 README §1.3.

| PR | 做什么 | 安全面 | 依赖 | 量级（产品代码） |
|---|---|---|---|---|
| CAP1a | 删能力发现中心和 FoundRail 的代码（服务端加网页），连带剪线 | `capability_flow.py` 剪线那几行是 | 用户定第 2 条 | 删约 2,600 行（U2）；剪线约 +/−150 |
| CAP1b | 迁移：删 `discovery_candidates` | 否 | CAP1a | 约 40 |
| CAP1c | 迁移：删 `capability_finds`（若第 2 条定为删） | 否 | CAP1a | 约 40 |
| CAP2a | 删「创建技能」页、整理器、候选的代码；`create_skill` 改成过渡卡 | 是 | CAP1a；C7c（软） | 约 −900 / +250 |
| CAP2b | 迁移：升过级的技能换一种标法，改 seeder 的 `_USERS_SKILL`，再删 `skill_candidates` | D7 那条是 | CAP2a | 约 +80 |
| CAP3a | 能力页只列「会什么」；用词改成 自带 / 技能 / 连接；方法并进技能 | 删除按钮的规则是 | CAP1a、CAP2a；SUB（方法那半） | 约 ±600，净减 |
| CAP3b | 迁移：删 `professional_methods`、`professional_method_versions`（SUB 还在用就改成写 DELETE-BY） | 否 | CAP3a；SUB | 约 40 |
| CAP4 | 安装卡的安全底线（一）：卡面只写事实、域名白名单、来源核对、锁文件在出卡前、在钉的版本上读许可证和扫描 | 是 | CAP1a | 约 +700 |
| CAP5 | 安全底线（二）：运行时补洞（名字、工具哈希、技能脚本专用路径、缓存、钉版本、导入补扫描） | 是 | CAP4；**SBX**；**#432** | 约 +500 |
| CAP6a | 技能目录：`~/.agents/skills` 当技能来源，加已有技能的一次性导出 | 是 | CAP4；CAP6b / SBX（目录先拒读拒写，不能比今天松） | 约 +700 |
| CAP6b | 技能、插件、MCP 配置目录对模型不可写（并进 SBX 的受保护写入） | 是 | **SBX**（并进它） | 约 +200 |
| CAP7a | 迁移：重建 `capability_sources`，`kind` 加 `plugin` | 否 | CAP6a | 约 80 |
| CAP7b | 插件包：拆出技能和连接，带钩子的不装 | 是 | CAP4、CAP5、CAP6a/b、CAP7a | 约 +700 |
| CAP8 | 导入 Claude Code / Codex 的设置，含 MCP 配置（import-agent） | 是 | CAP6a、CAP7b | 约 +500 |
| CAP8b | Import memories from ChatGPT / Claude: the user pastes, Arslan lists the entries it would keep, the user confirms before anything is stored (user, 2026-10-28) | yes (memory write) | MEM1 (merge by meaning, so imports do not duplicate) | about +250 |
| CAP9 | 安装卡上的 OSV.dev 漏洞检查（插进 CAP4 留的位置） | 是（卡面） | CAP4 | 约 +250 |
| CAP10 | `verify`：找出怎么运行，在沙箱里跑冒烟测试 | 是 | **SBX** | 约 +400 |
| CAP11 | ⑤ iPhone 能看安装卡、不能批（**用户点头才做**） | 是（Bridge 帧） | 用户定第 1 条；①iOS | 约 +150（Mac 端） |

## 改哪些文件

### CAP1a 删能力发现中心（不只是删除，还有剪线）

- **删（服务端）：**
  - `server/api/discovery.py` 的 `search`、`evaluate`、`/catalog` 四个路由、`skill/generate`、`skill`（`:23-108`）；
  - `server/services/discovery_service.py`、`mcp_suggest.py`、`repo_overview.py`、`skill_suggest.py`、`plugin_manifest.py`；
  - `server/services/prompts/` 下的 `mcp_suggest.py`、`repo_overview.py`、`skill_suggest.py`；
  - `github_eval.py` 的 `fetch_file`、`MANIFEST_PATH`（`:140-165`）、`fetch_readme`（`:168`）；
  - `DiscoveryCandidate` 模型（表在 CAP1b 删）。
- **删（页面自己的找和装，见上面第 3 条）：**
  - `server/api/capabilities.py` 的 `/capability-search`、`/capability-candidates/*`、`/projects/{id}/capability-material`；
  - `capability_dossier.py` 里页面候选那部分；
  - `capability_lookahead.py`。
- **FoundRail（按用户定的第 2 条，⓪Plan 的建议是删）：**
  - 删 `/capability-finds*`、`CapabilityFind` 模型（表在 CAP1c 删）、`capability_flow.record_find`。
  - **剪线：** `record_find` 有两个调用方。没人可问时（`capability_flow.py:238-247`），工具结果改成让模型在回答里说「缺 X，回到对话里说一声就能装」；用户拒绝时（`:255`）就不记了。`refuse_unattended` 和账本那两行不动。
  - **剪线：** 侧边栏「能力」的角标（`App.tsx:414-417`、`:635`；`Sidebar.tsx:149-151`）跟着删，测试 `capabilities-badge` 一起删。
- **删（网页）：**
  - `Capabilities.tsx` 的发现标签和 `saved`；
  - `ToolHubDiscover.tsx`、`RepoDossier.tsx`、`SavedCandidates.tsx`、`capabilities/DiscoverResults.tsx`、`capabilities/CandidateDossier.tsx`、`capabilities/FoundRail.tsx`；
  - `web/src/api/discovery.ts` 里除 `skills/scan`、`skills/import` 以外的部分，`web/src/api/capabilities.ts` 里对应的方法；
  - 对应的测试和六种语言的 key。
- **剪线（网页）：**
  - `START_PROJECT_EVENT` 先挪出 `CandidateDossier`（`App.tsx:36`）；
  - `Capabilities.tsx:6` 的 `McpPrefill` 改从 `api/client.types.ts` 导入；
  - `CapabilitySwitches.tsx` 的「加别的」（`:108-109`，类型 `:20`）去掉 `discover`：「贴一个 GitHub 链接」改为打开技能里的导入面板，`forge` 那一个留给 CAP2a 处理。
- **剪线（服务端）：** `project_plan.py:251-253` 去掉调用 `capability_lookahead` 的那段。
- **字符串残留：** `server/api/usage.py:43-49` 去掉 `mcp_suggest`、`skill_suggest`；改 `arslan/skills/skillpack.py:4` 的说明；`seeder.py:89` 的注释改成不再提 `discovery_service`。
- **留：**
  - `skills/scan`、`skills/import`（`discovery.py:123-142`，导入面板在用）；
  - `github_eval`（`capability_search` 和 `skill_import` 在用）；
  - `find_capability`、`propose_capability`；
  - 手动添加 MCP 的表单。
- **重新生成** `docs/CAPABILITY_INVENTORY.md`（`sessions.md` §3）。

### CAP1b / CAP1c 删表

- 每个 PR 只带一个迁移，排在 CAP1a 合并之后：
  - CAP1b：`discovery_candidates`；
  - CAP1c：`capability_finds`。
- 同步改 `runner.py`、`test_migration_runner.py`、`models.py`（`sessions.md` §4）。

### CAP2a 删「创建技能」页，`create_skill` 改成过渡卡

- **删：**
  - `web/src/components/SkillForge.tsx`；
  - `Capabilities.tsx` 的 forge 标签和按钮（`:95-98`、`:114`）；
  - `CapabilitySwitches.tsx` 里 `forge` 那个「加别的」按钮，改成一句「在对话里说『把刚才这套做法存成技能』」；
  - `workspace.createSkill`、`forge.*` 等 key（六种语言）；
  - `server/api/skills.py` 的 forge、candidates、promote、reject、curator 路由；
  - `server/services/curator.py`（`:28` 已写 `DELETE-BY: v0.1.64`）；
  - `skill_forge.py` 的 `create_candidate`、`promote_candidate`、`reject_candidate`、`list_candidates`；
  - `run_redact.py` 里读候选表的那段（`:12`、`:50`）。
- **留：** `skill_forge.validate` 和 `MAX_SKILL_BYTES`。`skill_import.py:32` 和 `expert_conversion.py` 在用，按调用方拆，不整个删。
- **`expert_conversion.py:57-59`：** C7c 先合就不用管。CAP2a 先合的话，`convert` 改成直接写 `SkillPack`（用户点「转换」本来就是人这一关）。
- **过渡卡（安全面）：**
  - `create_skill`（`executors.py:585-614`）改成出卡。卡上是完整的 SKILL.md，用户点「可以」才写进 `SkillPack` 并启用。
  - 带脚本或附件的直接拒，提示等 v0.1.65 的「待你看」。
  - 卡和安装卡走同一个通道（`ws/arslan.py:491-502`，`broadcast=False`），答完写一行账本（`permissions.record_card_outcome`，`permissions.py:307`）。
  - 没人可问时走 `refuse_unattended`（`permissions.py:420`），不留草稿。
  - 工具按需给，经 `find_tools` 拿到，不进常驻表（K7）。工具说明里写「用户说『把刚才这套做法存成技能』时用」。
  - 改 `tool_loop.py:2102` 的参数 schema。这是 K 线热点文件，只做小改，排在开着的 K 线 PR 之后。
  - 改 `seed_catalog.py:116-121` 的说明。

### CAP2b 删 `skill_candidates`

- 一个迁移按顺序做三件事：
  1. 把 `promoted_at` 有值的候选对应的 `SkillPack` 标成「用户的」（用现有的列，标法开工时定）；
  2. seeder 的 `_USERS_SKILL`（`seeder.py:85-95`）改认这个标法；
  3. 删表。
- D7 的测试照旧要过。再加一条：升级前的一个自写技能，升级后仍算用户的、不被退役。

### CAP3a 能力页只列「会什么」

- **页面结构：**
  - `Capabilities.tsx` 改成一个列表，不分标签，分自带 / 技能 / 连接三组。
  - 每项写一句用途、来源（自带 / 你装的 / Arslan 自己写的 / 来自 Claude Code 等），带开关、删除和最近一次使用的时间。
  - 保留 `CapabilityFilter`（#62，用户 10-28 定），只筛已装的，不联网。
  - 手动添加 MCP 的表单（`McpServers.tsx`）放进「连接」的详情里。「MCP」只在详情里出现。
  - 导入面板（`SkillImportPanel.tsx`）留着，改名「贴一个链接」。
- **用词：**
  - `capabilityList.ts` 的分组和来源标签（`:6`、`:18`、`:41`、`:53` 和另外四种语言）改成 自带 / 技能 / 连接。
  - `workspace.ts` 的 `skillsWorkflows` 改成「技能」，六种语言一起改。
- **专业工作方法**（`companion/ProfessionalMethods.tsx`、`locales/methods.ts`）并进技能列表，和 SUB 卡一起改：谁先合，谁做这一半，另一张卡写明。
- **最近一次使用：** 从现有的运行记录取，不加列。取不到的显示「还没用过」。
- **删除按钮（安全面）：** 只有 Arslan 自己装的才给删除。从别的工具读来的（CAP6a、CAP8）只给开关（README A 补的第 3 条）。服务端也要拒，不只是网页不显示按钮。

### CAP3b 删方法的两张表

- 方法都成了技能以后，删 `professional_methods`、`professional_method_versions`（`worker_models.py:9-16`）。
- 删之前，先把用户改过的方法版本导出成技能。
- 同一个文件里 SUB 用的 worker 记录不动。SUB 还要读方法表的话，这个 PR 不做，代码里写 `DELETE-BY: v0.1.65`，并写明条件。

### CAP4 安装卡的安全底线（一）

- **卡上只写事实，不写判断。**
  - 不写「服务官方」，写「发布者：已验证拥有 example.com」（Registry 反向域名命名空间验证过的那个域名），或者「发布者：GitHub 账号 X」。
  - 反向域名只证明那个域名归它，包的主页是它自己填的，都不能证明「官方」。
- **一键卡只给一张很短的域名白名单。** 这张单子用户能看到、能改，放在设置里。不在单子上的一律只提示「请手动安装」。
- **来源核对：**
  - 远程服务器：实际连接的主机必须在那个已验证的域名下。启动时再核一次，不只是出卡时核。
  - 包：Registry 里这个已验证命名空间下的条目，必须指向这个包名和这个版本。启动时回源再核一次。
- **技能来源：**
  - 只收 `anthropics/skills` 和用户显式信任过的 GitHub 账号。
  - 信任按账号的数字 id 记，不按登录名记（登录名可以改名、被人重新注册）。
  - 信任了也只是能出一键卡：每次照样钉 sha、扫描、出卡。
  - 信任从「贴一个链接」导入成功之后点一下记下，设置里能撤。
- 不接 ClawHub 一类的开放市场。
- 过滤 Registry 里 `status=deleted` 的条目（`from_registry` 加判断）。
- **顺序固定：解析 → 锁 → OSV → 卡 → 按锁安装。**
  - PyPI 只解析 wheel，npm 不跑脚本，所以出卡前不执行任何包里的代码。
  - 锁文件在出卡前生成；CAP9 的 OSV 检查插在锁和卡之间；装的时候照锁装（`--require-hashes`、`npm ci`）。
  - 锁和卡上显示的对不上就停。
  - 今天锁在用户点头之后才生成，紧接着就装（`capability_install.py:125-138`、`:141-151`），卡上没有锁。要把锁挪到出卡之前。
- **技能：** 出卡前在钉的 sha 上取全部文件、扫描、算每个文件的 sha256。装的时候照这份哈希核，对不上就停。今天是先装后扫（`capability_flow.py:148-160`）。`/discovery/skills/*` 这条路（`skill_import.py:195`、`:206` 读 HEAD）也改成先钉 sha 再读。
- **许可证在钉的版本上读：** `capability_install.source_license`（`:84-96`）改成按 sha 读，不再读 HEAD。
- **卡面**（`capability_flow.card_for`，`:50-66`；网页 `capabilities/CapabilityProposeCard.tsx`）：
  - 发布者（只写事实）；钉的版本和摘要；
  - 技能：扫描命中放最上面标红，下面是可以展开的全文和脚本清单；
  - MCP：启动命令、本地还是远程、实际连的主机、要哪些文件夹、要不要网络（要的话写明「可访问任何网站」）、要哪些钥匙。
- **扫描规则：** `capability_scan.py` 加一条「叫人或 agent 去下载、执行」的句子（ClawHavoc 走的就是这条路）。具体写法只放在测试里。

### CAP5 安全底线（二）：运行时补洞（等 #432）

- **第三方技能的名字**，进工具说明之前限制字符集和长度（例如只留字母、数字、连字符，不超过 60 个字符）。`read_skill` 的说明里第三方技能只放名字，不放 description（`arslan.py:1006-1023`）。
- **工具列表哈希：**
  - 哈希包括每个工具的名字、description 和 inputSchema；
  - 第一次测试通过时记下（`capability_flow.test_mcp`，`:94-120`）；
  - **每次连接、每次收到 `tools/list_changed`**（`server/mcp/session.py:292`、`server/mcp/discovery.py:273`）都比一次，变了就停用并重新出卡；
  - 存进 `CapabilitySource.test` 这一类现有的 JSON 列。
- **技能脚本只有一条专用路径（③Hands 的意见，用户定第 4 条）：**
  - `run_python` 只为技能脚本加回来，跑在断网的离线沙箱里；
  - 它的结果今天标 `external: False`（`executors.py:733`），沙箱起不来时还可能联网。改成：沙箱起不来就不跑；结果加外部内容的框，按外部内容算。
- **`run_command` 引用技能目录：**
  - 按命令文字匹配只是提示：匹配上了就出卡（只给「这一次」）、打外部内容标记。
  - 真正的边界在 SBX 的 profile：`run_command` 起的进程不能执行、也不能读技能脚本目录（数据目录的 `skill_scripts/`、`~/.agents/skills`、插件目录）。
  - 这一节等 #432 定了才写死放在哪一层；③Hands 审。
- **独立缓存：** 一键装的 MCP 用自己的缓存目录，不再共用 `uv-cache`、`npm-cache`（`capability_install.py:128`、`:145`）。
- **手动添加的 MCP 钉版本：** 表单里没写版本的 `npx` / `uvx` 包，查出当前版本写死，查不到就拒。
- **`/discovery/skills/import` 补扫描**（`discovery.py:134-142`），扫描结果和卡上的一致。

### CAP6a 技能目录当来源，加一次性导出

- 按用户定的第 3 条：Arslan 装的技能落到 `~/.agents/skills/<名字>/`（开放标准）。
- **不能比今天松（③Hands 复审 #434）：** 今天技能脚本在数据目录里（`skill_import.py:281`），数据目录在 `arslan_protected` 里（`command_sandbox.py:101`）：沙箱里的命令永远不能读写它（`:121-124` 的 `default_protected`），跑到沙箱外的命令最小 profile 也拒读拒写（`:197-198`）。挪到 `~/.agents/skills` 和数据目录外的插件目录，这两层就没了。所以 `~/.agents/skills` 和插件目录要**同时**进 `default_protected` 和最小 profile，**拒读也拒写**（SKILL.md 走 `read_skill`，脚本走 `run_python`）。**CAP6a 依赖 CAP6b / SBX 的这一步，不能比它先合。**
- 每个文件的哈希记在 Arslan 的数据目录里，不放在技能文件夹里。
- **注册表今天直接读 `SkillPack`**（`skill_forge.py:9-11`）。所以这个 PR 要让技能目录成为一个来源：启动时、以及每次 `read_skill` 时读目录，核哈希。哈希对不上（文件被改过）就停用并重新出卡。
- **别的工具放进来的技能**，显示「来自其他工具」，只给开关、不给删除，第一次启用前出卡（卡面同 CAP4）。
- **卡上写明：** `~/.agents/skills` 是几个工具共用的，装在这里的技能，别的工具也可能读到、用到。
- **已经导入的技能**（`SkillPack` 里 `category="imported"` 的和带 `source_id` 的）：同一版一次性导出到技能目录（§11 第 1 条）。导出前先备份，导出后核数量和哈希。

### CAP6b 模型不可写（并进 SBX 的受保护写入）

- 技能目录、插件目录、MCP 配置对模型的所有写路径都是硬拒，用户点头也不行。MCP 配置今天是数据库里的 `mcp_servers` 表（`capability_install.py:300-310`），所以要护的就是数据目录。
- 这几个目录加进 SBX 的受保护写入，和 `checkpoints/` 同一处；技能目录和插件目录还要拒读（见 CAP6a 第二条）。
- **内核拦不住的两条（③Hands 复审 #434）：** U11 批准过的单纯 osascript 和 `shortcuts run` 不套任何 profile（`terminal_exec.py:176-178` 遇到 `unwrapped` 不加包装，判断在 `task_service.unwrapped_once`）；Hands 在访达或编辑器里点按也不经过 seatbelt。卡里写明这是例外，「用户点头也不行」对这两条做不到。这两条的测试测兜底，不测拒写：文件被改了，下一次读时哈希对不上就停用并重新出卡；新冒出来的技能文件夹第一次启用前先出卡。
- 跑到沙箱外的命令用 S2a-1 的最小 profile（`command_sandbox.py:93-96` 的 `arslan_protected`、`:187` 的 `minimal_profile`），把这几个目录加进它的禁写。
- `capability_sandbox` 即使用户授权了上层文件夹，也排除这几个目录。
- **测试覆盖每一条写路径，各打一次：**
  - `write_file`、`edit_file`、`run_command`、`run_python`；
  - 授权了上层文件夹的 MCP 文件系统服务器；
  - Hands / 桌面点按（③Hands 审）；
  - 技能脚本自己；
  - 后台任务和子会话里的同一批路径。

### CAP7a 重建 `capability_sources`

- 一个迁移：重建表，让 `CHECK (kind IN (...))` 加上 `plugin`（`models.py:364`）。
- 照 0069 那样复制数据、换表名，迁移测试覆盖已有行原样保留。

### CAP7b 插件包

- 读 Claude Code 的 `.claude-plugin/plugin.json`（Codex 的插件同理，开工时回源核格式），拆出技能和 MCP。
- **按允许清单收：** 只认技能和 MCP。钩子、斜杠命令、agent 定义、认不出的部分，有一样就整个不装。
  - 带钩子的，卡上写「要靠自动运行的钩子工作，现在还不支持」（钩子支持排在 v0.1.65 之后）。
  - agent 定义等 SUB 合了再接（C 那条）。
- **README A 补的四条：**
  1. 来源白名单按插件自己的仓库查，不按市场查；各部分取最严的，一部分不过，整个插件改为「请手动安装」。
  2. 整个插件钉 commit sha 加每个文件的哈希，放在一个文件夹里（因为 `${CLAUDE_PLUGIN_ROOT}`），路径不能跑出这个文件夹。`.mcp.json` 里没钉版本的 `npx` 钉上固定版本，钉不了就拒装。
  3. 只删 Arslan 自己装的（CAP3a 的规则）。
  4. 工具列表的哈希变了，整个插件停用；许可证复用 `skill_import` 的检查；里面的技能和已有技能重名就拒装，不覆盖；插件带的 MCP 显示在插件下面，不进手动添加的表。
- 整组安装、整组开关、整组删除，不提供单独关掉插件里的某个技能（用户 10-28 定）。
- 插件里的 MCP 照样进 `capability_sandbox`；插件里的技能脚本照样只走 CAP5 的专用路径。
- **存法：** `CapabilitySource` 的 `kind="plugin"`（CAP7a 之后），各部分放进现有的 JSON 列。

### CAP8 导入 Claude Code / Codex 的设置（import-agent）

- 读 Claude Code 的技能目录和插件目录、它的 MCP 配置，以及 Codex 的 MCP 配置。各家的路径和格式开工时回源核，不凭记忆写。
- 读到的技能和插件按 CAP6a、CAP7b 处理：只给开关、不给删除；第一次启用前出卡；带钩子的照样拒。
- **MCP 配置**每个服务器一张卡，卡面同 CAP4。本地的进 `capability_sandbox`，没钉版本的钉上或拒。
- **钥匙：** 配置里的环境变量可能是真钥匙。由服务端直接读、加密存（同 `capability_install.py:304-305`），不进模型上下文、不进账本、不显示在卡上（卡上只写「带了 N 个钥匙」）。
- 这一切只在用户点「导入」时做。模型不能触发，也不能读这些文件。

### CAP8b Import memories from ChatGPT / Claude (user, 2026-10-28)

From the memory plan, item 17 (`docs/plans/0162/README.md` §8). The user pastes the memory export from ChatGPT or Claude into a conversation. Arslan splits it into candidate entries, drops one-off task state and anything that guesses the user's gender (MEM1 rules), merges by meaning against what is already stored (MEM1), and shows the list. Nothing is stored until the user confirms; the user can untick lines. Pasted text is treated as the user's own words only for this confirm step: it is shown, not executed, and it never switches on lessons or notes by itself. Merged with CAP8 in the cut order (CAP10 → CAP8 and CAP8b → CAP7).

### CAP9 OSV.dev 检查

- 新建 `server/services/osv_check.py`，向 OSV.dev 的批量查询接口发包名、生态和版本，不发任何用户数据。
- 插在 CAP4 定的「锁 → OSV → 卡」那一格：把锁里的全部包（含要装的那个）查一遍。
- 卡上一行「已知漏洞：无 / N 个（最高 X 级）」，可以展开看编号。命中以后怎么处理，按用户定的第 5 条。
- 技能没有依赖清单，卡上写「技能不查依赖漏洞」。插件里的 MCP 照样查。
- OSV 连不上就写「没查成」，不当成「没有漏洞」。

### CAP10 verify（只在沙箱里跑）

- 一个按需给的工具（经 `find_tools`）：
  - 给一个文件夹，先读出怎么运行：`package.json` 的 scripts、`pyproject` / pytest、Makefile 等，按允许清单认；
  - 再在 SBX 的默认拒绝沙箱里跑一遍冒烟测试；
  - 返回命令、退出码和输出的结尾，按外部内容算。
- 只在副本里跑，或者只给这个文件夹写权限；默认断网。缺依赖时报「需要装依赖」，要联网就出卡，只给「这一次」。
- 跑的是陌生代码，**SBX 没合，这个 PR 不开**。

### CAP11 ⑤ iPhone 能看、不能批（用户点头才做）

- 能力卡（安装卡和 CAP2a 的过渡卡）发到手机，手机上只显示，按钮是「回到 Mac 上确认」。
- Mac 端拒绝手机发来的这类批准（服务端判，不靠手机不显示按钮）。
- 改 Bridge 帧：`docs/specs/mobile-bridge-protocol.md:283` 那句改写；改 `server/ws/bridge.py`、`spec/mobile-bridge/**` 的向量。①iOS 做手机端。
- 和 Q1、SUB 的帧改动合成一次问用户（`docs/plans/0164/README.md` §2 第 3 条）。

## 不许碰

- SBX 的沙箱规则本身、S2a-3 的命令三层（③Hands）。CAP5、CAP10 用它们，不改它们；CAP6b 是并进 SBX 的那一块，由写 SBX 的会话做。
- Bridge 帧：用户点头之前一个字段都不加（CAP11 之外的 PR 都不碰）。
- 钩子支持、预装哪些技能、推荐哪些 MCP：v0.1.65 之后那一轮。
- 「待你看」和学习循环（自动写技能）：v0.1.65。
- 插件里的 agent 定义：等 SUB 合了再接（C 那条）。
- lsp、worktree 清理：Hermes 表里排在「以后」。
- `server/mcp/discovery.py`：名字陷阱，它是列 MCP 服务器工具的，和发现中心无关。CAP1a 不删它（CAP5 只在它的 `tools/list_changed` 处理里加哈希比对）。
- K 线热点文件（`arslan.py`、`tool_loop.py`）：只做小改，排在开着的 K 线 PR 后面。
- 定时任务、收件箱（INB 卡）。

## 怎么做（要点）

1. **先删后加，删代码和删表分开。** CAP1a、CAP2a 删干净代码，再由 CAP1b、CAP1c、CAP2b 各删一张表。`git grep` 的结果贴在 PR 里：
   - 逐个模块按导入语句和路径查；
   - 再按字符串查一遍（路由路径、注册表的键、翻译键、`usage.py` 那种名字列表）。
2. **每个安全面 PR 先写打不过去的测试。** 例如：今天能装 `status=deleted` 的条目、扫的是装完的文件、`read_skill` 里有第三方的 description、模型能写技能目录、带钩子的插件能装上一半、锁和卡对不上照样装。先红后绿，再做 mutation（改回去，测试要红）。
3. **卡和安全文案定稿后，先发云端审计看**（10-21 定的），再交 Codex 审合并前的头。 **Changed (user, 2026-10-28 evening):** Codex only for what a Claude review cannot cover; see v0.1.64 README §1.3.
4. **危险的写法只放在测试里**，PR 描述和卡里只写「哪一类」。
5. **每个 PR 都写完成证据四项**（`sessions.md` §8），说 CI 绿要附 run id 和结论。

## 验收

- **CAP1a：**
  - 能力页没有发现标签和收藏；侧边栏没有能力角标；「加别的」里没有指向发现的按钮。
  - 下面这些文件不存在（`git ls-files` 查不到）：`server/services/{discovery_service,mcp_suggest,repo_overview,skill_suggest,plugin_manifest,capability_lookahead}.py`、`server/services/prompts/{mcp_suggest,repo_overview,skill_suggest}.py`、`web/src/components/{ToolHubDiscover,RepoDossier,SavedCandidates}.tsx`、`web/src/components/capabilities/{DiscoverResults,CandidateDossier,FoundRail}.tsx`。
  - `git grep -nE 'from server\.services(\.prompts)? import .*(discovery_service|mcp_suggest|repo_overview|skill_suggest|plugin_manifest|capability_lookahead)'` 查不到；`git grep -nE 'fetch_readme|fetch_file|MANIFEST_PATH|/capability-search|/capability-finds|/discovery/(search|evaluate|catalog|skill/generate)'` 在 `server arslan web/src scripts` 里查不到。
  - `skills/scan`、`skills/import` 照旧能用。
- **CAP1b、CAP1c、CAP2b、CAP3b、CAP7a：** 各自的迁移测试过；从上一个正式版的数据库升级，启动正常。
- **CAP2a：**
  - `server/services/curator.py`、`web/src/components/SkillForge.tsx` 不存在；`git grep -nE 'services import .*curator|create_candidate|promote_candidate|reject_candidate|/skills/(forge|candidates|curator)'` 查不到。
  - 对话里说「把刚才这套做法存成技能」会出卡，卡上是完整的 SKILL.md；点「可以」才出现在技能列表。
  - 拒绝、过期、没人可问各写一行账本；带脚本的直接拒。
- **CAP2b：** `git grep -n 'SkillCandidate'` 只剩历史迁移文件；D7 的测试照旧过；升级前自写的技能仍算用户的。
- **CAP3a：** 能力页一个列表，分三组；六种语言里没有「工作流」「方法（技能）」「MCP 服务」这几个标签；从别的工具读来的那项，服务端拒绝删除（测试打接口）；`locale-parity` 过。
- **CAP4：**
  - 每一条白名单规则各一条正、反测试。
  - 远程主机不在已验证域名下的被拒；Registry 条目指向的包名、版本和要装的不一致就停。
  - 卡上的 sha 和锁等于装上的（测试：出卡后仓库 HEAD 变了，装的仍是卡上那个，或者停下；锁被换了就停）。
  - 许可证在 sha 上读；`status=deleted` 的条目不出现；GitHub 账号改名后，信任不跟着新登录名走。
- **CAP5：**
  - 第三方名字超长或带怪字符的进不了工具说明；`read_skill` 的说明里没有第三方 description。
  - 工具的 description 或 schema 变了（不只是名字）会被发现，重新连接和 `tools/list_changed` 两处都测。
  - 技能脚本只能经 `run_python` 跑；它在沙箱起不来时拒绝，结果带外部内容的框。
  - `run_command` 起的进程在 SBX 下读、执行技能脚本目录都失败（真沙箱测试，macOS CI）。
  - 两个一键装的 MCP 用不同的缓存目录；手动添加的没钉版本的包被钉上或被拒；`/discovery/skills/import` 命中高危就拒。
- **CAP6a：** `~/.agents/skills` 里别的工具放的技能出现在列表上，只能开关；文件改了以后，下一次 `read_skill` 就停用；导出前后的技能数量和哈希一致。
- **CAP6b：** 上面列的每一条写路径各一条测试，全部被拒（用户点头也不行）；授权了上层文件夹的 MCP 也写不进去。
- **CAP7b：**
  - 不带钩子的插件完整可用。
  - 带钩子、斜杠命令、agent 定义或认不出部分的，整个不装，什么都不留。
  - `.mcp.json` 没钉版本的被钉上或拒装；重名的拒装；能整组开关、整组删除。
- **CAP8：** 用假的配置文件（不用真钥匙）导入以后，技能、插件、MCP 都在列表上；钥匙不进模型上下文、账本和日志（测试断言）。
- **CAP9：** 用打桩的 OSV 回应（不连真网），卡上显示漏洞编号；OSV 连不上时卡上写「没查成」。
- **CAP10：** 在 SBX 沙箱里跑一个小项目的测试，结果能回来；项目试图联网、写文件夹外面，都被拒。
- **CAP11（若做）：** 手机上看得到卡，批不了；Mac 拒绝手机发来的批准（测试）。
- **整卡：** M3 式手动验收一次：对话里缺能力 → 找到 → 卡 → 装 → 用上，DeepSeek 和 Claude 各一遍；能力页截图，做了 CAP11 的话加 iPhone 截图。

## 量级

- 合计产品代码约 −3,500 / +4,500（CAP1a–CAP10），净数接近持平，主要看 CAP1a 删多少。
- 测试另算，安全面的测试会比产品代码多。
- CAP1a 超过 800 行，超出的部分都是整份删除，照 U2 例外。剪线部分约 150 行，按普通 PR 审，`capability_flow.py` 那几行按安全面审。
- CAP6a 的 +700 是估计：存储换成文件后，注册表、`read_skill`、导出都要动。开工时超了就再拆。

## 风险与回退

- **删 FoundRail 以后**，后台任务找到的能力没地方看了。缓解办法见第 2 条。
- **域名白名单太短，大多数只能手动装。** 这是有意的；单子用户能改。上线前拿 Registry 现有条目试一遍，在 PR 里写明有多少条能出一键卡。
- **改存储（CAP6a）可能丢掉用户已经装的技能。** 导出前先备份，导出后核数量和哈希。
- **import-agent 读别的工具的配置时会碰到真钥匙。** 只由服务端读；测试断言钥匙不进上下文、账本、日志；开发时只用假配置。
- **CAP5 和 #432、S2a-3 可能撞车。** #432 定了以后再写死这一节。
- **②Main 负载太大。** CAP 可以分给新会话。万一要砍，按事先定好的顺序顺延：CAP10 → CAP8 → CAP7（见第 9 条）。
- **旧路径：**
  - 过渡卡本身就是过渡，代码注释写 `DELETE-BY: v0.1.65 when 「待你看」 lands`。
  - CAP3b 如果不删表，写 `DELETE-BY: v0.1.65` 和条件。
  - 其余的删除都在同一版做完，不留兼容路径。
- **回退：**
  - 每个 PR 单独 revert。
  - 删表的 PR 都单独开、排在删代码之后，所以 revert 代码不需要回滚表。
  - 删表本身回不去（`runner.assert_supported_schema` 认迁移 id），合并前多审一遍。
  - 删的只是发现中心的缓存、找到的记录和候选表，不是用户的技能。CAP2b 先给用户的技能换好标法再删表。

## 开工前要用户定的

1. **⑤ iPhone 能看安装卡、不能批。** 这要改 Bridge 帧（今天能力卡根本不发到手机，`mobile-bridge-protocol.md:283`），归你点头。建议和 Q1、SUB 的帧改动一起问一次。不点头的话 CAP11 不做，手机照旧看不到。
2. **后台找到的能力放哪**（FoundRail 和侧边栏角标删掉以后）。
   - ⓪Plan 的建议：不再存。没人可问时，模型在回答或任务结果里说一句「缺 X，回到对话里说一声就能装」。项目开新关时的预判（`capability_lookahead`）整个删，`capability_finds` 表也删（CAP1c）。
   - 另一种做法：放进收件箱的「要你做」（INB 卡）。但那就是一条推荐，和「不推荐」有点冲突。
3. **技能装到哪。** README 说 `~/.agents/skills`，今天在数据库加数据目录。⓪Plan 的建议：新装的落到 `~/.agents/skills`，哈希记在 Arslan 的数据目录里；已经导入的技能在同一版一次性导出过去（§11），不留两套。注意这个文件夹别的工具也读。
4. **技能脚本怎么跑。** ③Hands 和 ⓪Plan 的建议：只给技能脚本把 `run_python` 加回来，跑在断网的离线沙箱里，结果按外部内容算；`run_command` 那边靠 SBX 的 profile 挡住，按文字匹配只当提示。
5. **OSV 查到已知漏洞以后**：拦，还是只提示？⓪Plan 的建议：要装的那个包本身有已知漏洞，默认按钮改成「不装」，你仍然可以装；依赖里有的，只列出来。
6. **一键安装的域名白名单**，第一版放哪几个域名（单子你能看、能改）。
7. **`arslan.plugin.json`（2026-08 自己定的第三方格式）跟发现中心一起删。** 改收 Claude Code 的插件格式以后它没用了。确认一下。
8. **过渡卡**（存成技能时出卡、带脚本的直接拒）是 ②Main 提、⓪Plan 同意的，你可以改。
9. **万一要砍范围，先定好顺延的顺序：CAP10 → CAP8 → CAP7。** 三个都是你 10-27、10-28 同意在 v0.1.64 做的，现在先点头这个顺序，到时候就不用再停下来问。
10. **这张卡给谁做。** ②Main 已经排满，建议开一个新会话专做 CAP（像 v0.1.63 的 ⑤C6、⑥C7）。CAP6b 交给写 SBX 的会话。

## Decided on 2026-10-30 (user, relayed by ④参谋)

The user's words: 「1. 接受建议改成 a；2.（1）现在就跟你说 直接按主流做法： Claude Code 和 Codex 对装过的技能一律信任，读的时候不加框。（2）也按主流做法；3.也按主流做法」. These override the sections above where they differ.

- **D1, CAP4a-2: option (a).** Arslan ships or fetches its own pinned, checksummed uv and Node runtime, as Claude Desktop ships a built-in Node runtime for `.mcpb` extensions. The lock is resolved with it before the card, so CAP4's order "resolve → lock → OSV → card → install from the lock" holds with one card that shows the locked versions. "Nothing third-party is installed before a yes" stays. Arslan's own pinned runtime counts as part of the app, not as third-party code. The runtime's pin and checksum live in the repository and are checked before use.
- **D2(1), skills follow mainstream practice: every skill the user has is trusted and read unframed,** as Claude Code and Codex do with installed skills.
  - `read_skill` and the skill index stop framing or marking by category. Reading a skill no longer marks the turn as "read outside content".
  - The origin marks (CAP2b's split by source, migration 0080's gh- marks) stay as data, for deletion and display only.
  - This replaces CAP2a's "keep the mark" and CAP2b's "split by source" for reading. CAP4's install-time checks are unchanged: pinned sha, scan, hashes, the card.
  - **Stated limit:** a skill's text reaches the model as trusted instructions, the same trust model as MCP tool descriptions from an approved server (user, 2026-10-29). The guard is at install time (the card, the scan and the pinned sha), not at read time. Skills that came in before CAP4's install-time checks (the old Discover page's `gh-` skills, Skill Forge's promoted ones, `create_skill` from outside text) never passed them; under D2 they read unframed too. Their origin mark still shows in Capabilities, and they can be deleted (D2(2)). Whether to re-check those rows once is the user's call (STATUS, "Waiting on the user"; ②Main's review of #540).
- **D2(2): skills of unknown origin are deletable,** like any other skill; the body goes to the Trash. Built-in and seeded skills stay non-deletable (user, 2026-10-30).

## Decided on 2026-10-31 (user, relayed by ④参谋)

The user's words: 「全按推荐，DIFF1 用左右对照，白名单选 D，UNI1b 草图推荐选 B（我还是那个要求 借鉴主流agent产品做法，不要过度防御）」. These override the sections above where they differ.

- **CAP4a-3, the allowlist: option D** (⑤CAP's Registry walk, #563 comment 6527457019: 2,583 one-click). Packages from any verified domain are one-click. The lock, the scan and the sandbox still apply. Remote servers are one-click only from B's list of about 40 vendors' own domains and GitHub orgs.
- **CAP4a-3, Q2:** a remote server whose publisher has no verified domain (`io.github.<account>`) is manual-only, as the card says.
- **CAP4a-3, Q3:** the start-time Registry re-check runs once a day per server, and on the first start after an update.
- **CAP4a-2, the runtimes:** fetched on first need against the SHA-256 pinned in the repository, not shipped in the app.
- **UNI1b:** option B of ⑤CAP's mock. A notice only, never blocking (D3).
- **Skills from before CAP4's checks (D2's remaining half):** left as they are, with no one-time rescan (the user, 2026-10-31 about 14:45 UTC, 「都按推荐」). This is what Claude Code and Codex do: they don't rescan installed skills. The skills keep their origin mark in Capabilities and stay deletable.
- **INB2 and skills:** INB2's allowlist (`server/orchestrator/untrusted.py:241-276` on main `2876f11a`) still counts a skill read as off the list. So after a skill read, "about you" memories wait for the user. Kept, and recorded as a stated limit: D2 covers reading, not memory writes.
- **The standing rule:** follow mainstream agent products, and don't over-defend (`docs/sessions.md` §12).

## Stated limits recorded on 2026-10-31

- **CAP5a (#577): a hand-added MCP server's tool list isn't pinned.** Pinning it would need a column, which this PR doesn't add. Only servers installed through a card are compared with their install test's listing.

## Decided on 2026-11-01 (user, relayed by ④参谋)

The user's words: 「1A，2 已知限制，3 去掉，额度按你的建议」.

- **CAP4a-3d (#604), KEEP_FOR: removed.** When the user keeps a server that the Registry shows as withdrawn, the keep holds until the Registry entry changes again. There is no 30-day re-park.
- **CAP4a-3d (#604), F3: a stated limit** (below).
- **UNI1a's "download and run" scan (#563): a known limit** (below).

## Stated limits recorded on 2026-11-01

- **CAP4a-3c/3d (#584, #604): cross-host redirects for remote MCP servers aren't checked.** The allowlist and the start-time re-check look at the server's declared URL. The SDK follows a redirect to another host, and that host isn't checked again. This matches mainstream MCP clients. Neither PR claims the other covers it.
- **UNI1a (#563): two parts of the scan weren't reviewed:** the 40-character window and the interpreter pattern. Classifier blocks stopped that part of the review. The scan is a heuristic, a first line before the lock and the sandbox, so the gap is accepted without an outside review.
