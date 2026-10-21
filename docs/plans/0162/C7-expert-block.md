# C7 删掉专家时代的那一大块（先剪线，再整块删，v0.1.64 用一次迁移收尾）

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | 第一、二步 v0.1.63；第三步 v0.1.64 |
| 分级 | 应该（用户 2026-10-21 定，U13 第 1 条）；其中 C2b 那部分照旧是「必须」 |
| 依赖 | C1（已合）；第二步里删 `arslan/spawn` 的 PR 要等 C9（自带技能今天放在 `arslan/spawn/seeds/`） |
| 合并位置 | C 线，和 K4b、K5 并行（用户定），不进 K 线严格链；碰到热点文件（`docs/sessions.md` §3）的 PR，在 K 线 PR 之间的空档合 |
| 推动的门槛 | 用户 2026-10-21 定的目标：到 v0.1.65 干净、简单、好用（`docs/sessions.md` §11） |
| 迁移号 | 第一、二步无；第三步要一个（v0.1.64 开工时在 README §5 登记） |
| 来源 | ④参谋的清理清单 §4、§6 第 1 条：约 6.7k 行专家代码，只靠技能锻造「评估要选分身」这一根线连着 |

## 第一步 C7a：剪线（一个小 PR）

- 去掉技能锻造里「评估要选分身」这一步。⓪Plan 在 main 上核过这根线：
  - 网页 `web/src/components/SkillForge.tsx:110-120`：先要选一个目标分身，再调 `api.evaluateSkillCandidate(id, { target_spawn_id })`；
  - 接口 `server/api/skills.py:47-52`：`/skills/candidates/{id}/evaluate`，跑 paired-ReplayGate（开技能对关技能）；
  - 服务 `skill_forge.evaluate_candidate`。
- 剪掉以后，技能候选不再需要分身来评估。整个能力发现中心（包括候选表和评估门）由 v0.1.64 的「按需加能力」替换，那张卡同版删掉剩下的部分（§11 第 1 条）。
- 这一步改了行为（技能锻造少了一步），用户已经定了（U13 第 1 条）。

## 第二步 C7b：整块删（按区域分 2–3 个 PR）

- **合成一组删：**
  - C2b（进化第一批，卡照旧，作为这一组的第一个 PR）；
  - 「进化第二批」（C2b 卡记下的：`evolution_watcher` 的手动路径、`replay_*`、`compare_judge`、`evolution_estimate`、`optimizer`、`synthetic_corpus`，以及 `evolution.*` 里没人用的翻译键）；
  - dispatcher；`replay_gate`、`replay_run`（连同 `server/main.py` 里 `replay_gate` 的开机自检）；`recipes`；
  - 专家相关的 REST 接口（`spawns`、`recipes`、`expert_conversion` 等，原来在 README §8）；
  - `arslan/spawn` 整个包，以及只有它在用的 `jinja2` 依赖（⓪Plan 查过：只有 `arslan/spawn/manager.py` import 它）；
  - 分身的会话提炼（`distill_service` 里和分身缠在一起的部分，见 C8）。
- **走总计划 U2 的整份删除例外：** 只删不可达的整个文件；别处只去引用，合计 ≤50 行；不改行为；PR 里列出删了哪些文件、怎么确认不可达（`git grep -w` 加按字符串查，§11 第 4 条）。
- **不跑 DeepSeek 门槛**（用户定：这些代码不在聊天主路径上），CI 全量绿即可。开工前在计划里贴调用关系：从 `tool_loop.py`、`arslan.py`、`server/ws/arslan.py` 出发，没有一条路径进到要删的代码。万一有，那一处单独拿出来，跑门槛再删。
- **`promise_guard` 里「分身」那一档**在 `arslan.py`，随 K5 一起改（见 K5 卡）。

## 第三步 C7c：v0.1.64 用一次迁移收尾

- **先留着、写明 `DELETE-BY: v0.1.64`**（§9、§11 第 2 条）：
  - 「旧专家转技能」页面（LegacyExperts）；
  - 专家表；
  - 旧对话里 `spawn_summary` 的显示。
- v0.1.64 用一次迁移把旧数据转好，再把它们连同记忆 v1 的旧表、`router_decisions` 一起删。
- 这一步现在只写进 README §8 和代码注释，不在 v0.1.63 动。

- **跟着一起变成死代码的，也在这一步删**（②Main 审 #284 时提出）：
  - `tool_loop.py` 里只给评测、回放用的分支：评测的网页读取额度（`HERMETIC_FETCH_BUDGET`、`_check_hermetic_fetch_budget`；K4b 只留下了这一份）和 hermetic 兜底；
  - `replay_safety`；
  - 只测它们的两个测试文件；
  - `promise_guard` 里零工具那一档（「去找专家」那段文字）：**归这一步**（②Main 定），放在删 `dispatcher.py` 的那个 PR 里，因为它唯一的调用方在 dispatcher（`:415`）。K5 不碰它。
- **`arslan/spawn` 里还活着的 `skillpack.py`**（SKILL.md 的格式定义，`seeder.py`、`skill_suggest.py` 在用）由 C9 搬走。`evolution_service`、`spawn_service` 里对 `arslan.spawn` 的引用，随这一步一起删。

## 不许碰

- 聊天主路径（`tool_loop.py` 的回合循环、`arslan.py` 的工具表）。只有两种改法可以：去掉 import；删上面列的那几处只给评测、回放用的分支。改 `tool_loop.py` 的 PR 在 K 线 PR 之间的空档合。
- Bridge 契约文件；Hands 的文件。
- 旧对话的显示（第三步之前都要能看）。

## 验收

- **第一步：** 技能锻造里没有「选分身」；评估接口和 `evaluate_candidate` 删掉；网页测试和后端测试跟着改。
- **第二步：**
  - 每个 PR 列出删了哪些文件，并附上不可达的证据；
  - CI 全量绿（附 run id）；
  - `uv sync --frozen` 后锁文件里没有 `jinja2`（除非别的包间接要它）；
  - 产品代码净行数贴在 PR 里（§11 第 6 条）。
- **第三步：** v0.1.64 的卡写。
- 完成证据四项（`docs/sessions.md` §8）。

## 量级

- 第一步：约 −100 行；
- 第二步：产品代码约 −6.7k 行，加对应的测试，分 2–3 个 PR，走 U2 的例外；
- 第三步：v0.1.64 再估。

## 风险与回退

- **风险：** 有一处主路径其实还在用要删的代码。所以开工前先贴调用关系，删完跑 CI 全量。
- **风险：** 老用户库里的专家数据。第三步之前不删表，旧对话照常显示。
- **回退：** 每个 PR 单独 revert。
