# STY 回复风格：有人情味，也能说清楚

> ⓪Plan 2026-10-29 夜间起草，用户 10-28 已定分级。v0.1.64 计划（#434）由用户点合并后才开工。

| 项 | 内容 |
|---|---|
| 道 | ②Main 改提示词；⓪Plan 出测题、跑 bench（⓪Plan 的建议） |
| 版本 | v0.1.64 |
| 分级 | 必须（用户 10-28） |
| 依赖 | ACM（卡片与文案大合并）：卡片文案和模型的任务汇报用同一套写法，ACM 写文案时照这张卡的四条 |
| 合并位置 | 不进严格链。改系统提示是热点（`server/orchestrator/arslan.py`），有 K 线那类改提示词的 PR 开着就排在它后面 |
| 推动的门槛 | R64 的「用户读真实回复」那一条；bench 不退步 |
| 分支 | `claude/0164-sty-reply-style` |
| 迁移号 | 无 |

## 目标

用户的原话：不想让 Arslan 啰嗦，但希望它「有人情味，又能明确表达」，担心整体变成冷冰冰的机器。全部规矩和例子在 `docs/plans/0162/README.md` §8「回复风格」那条（以 10-27 更正后的版本为准）。本卡只说怎么落地。

- **任务结果、操作步骤、进度汇报、报错说明这几处**，用四条：一句一个动作，加编号；同一个东西始终用同一个名字；不用被动句，说清是谁做的；先说结论，再给理由。
- **闲聊、讨论想法、陪用户想事情**，不用这四条。保留现在的「跟着用户的语气走」那段（`server/orchestrator/arslan.py:45-48`），在它上面加，不替换。
- **人情味但不假：** 不用客套词；不替用户猜原因、不替用户的情绪下定义；记忆只在帮得上忙时用；用户没问就不给生活建议；长短跟着用户走。「我记着」「明天接着来」这类承诺，只在真有东西存着时才说。

## 改哪些文件

- `server/orchestrator/arslan.py`
  - `_ARSLAN_SYSTEM`（`:42-49`）：在「Match the user's register」那段后面加「人情味但不假」的几条。
  - 工作方法那段（`:124-140`，K5 加的）：加任务汇报的四条。它本来管的就是「做事」，放在这里，闲聊时自然用不到。
  - `BACKGROUND_SYSTEM`（`:708-713`）：结尾的「concise result」改成同样的四条加验收单三栏（三栏的格式跟 INB 卡对齐，不在这里另起一套）。
- 不改 `web/src/locales/`：卡片文案归 ACM，ACM 照这四条写，六种语言都按（`web/src/locales/process.ts` 有 en/zh/ja/es/de/fr）。
- **测试：** 只钉住「提示词里有这几条、闲聊那段还在」。回复写得好不好，pytest 证明不了（见验收）。

## 不许碰

- 「跟着用户的语气走」那段的意思不能变。
- 不加 STE 的词表，不要求把句子拆碎，不删「因为 / 所以」这类连接词。
- 不改工具说明（K5 那一套）。
- 提示词缓存的布局（K3）：新加的文字放在固定前缀里，不放在每轮变化的部分，否则会打断缓存。改完在 bench 上看缓存命中率不降。

## 怎么做（要点）

1. **先出测题（⓪Plan）：** 照 §8 的例子造一批，分两类：闲聊 10 条（「今天好累」这类），任务汇报 10 条（整理纪要、改文件、报错）。中英文各半。全是造出来的，不用用户的真实对话原文。
2. **改提示词前后各跑一次：**
   - 跑分全套（DeepSeek），完成率不降；
   - 上面那 20 条，两个版本的回复并排放在一页给用户看，用户逐条选「更好 / 一样 / 更差」。
3. **在 Claude 上也抽几条看**（Claude 和 DeepSeek 对风格指令的反应不一样）。
4. 用户看过、点头了再合。

## 验收

- bench：DeepSeek 全套不退步（通过、答对不降，「等你」不增，没有新的报错类型）；缓存命中率不降。
- 用户读完那 20 条并排的回复：闲聊没有变冷、没有假关心；任务汇报没有变啰嗦，也没有变成电报体。中英文都看。
- 「我记着」这类承诺：在没有保存任何东西的对话里，回复里不出现这类承诺（测题里专门放两条）。

## 量级

产品代码约 +20 行（全是提示词文字），测试约 +30 行。主要的工作量在测题和用户读回复。

## 风险与回退

- **风险：** 四条用到了闲聊里，回复变冷。用户读回复那一步就是为了抓这个。
- **风险：** 提示词变长，缓存的固定前缀变了，第一次请求贵一点；之后命中率应该照旧。
- **回退：** 只改了提示词文字，回退就是还原这几行。

## 开工前要用户定的

- ~~这张卡放「应该」还是「必须」~~：用户 10-28 定「必须」。
- 读回复用多少条：⓪Plan 建议 20 条（闲聊 10、任务 10，中英各半），用户嫌多可以减。

## STY2: how Arslan does work, "deeper, not bigger" (user, 2026-10-28; relayed by ④参谋)

⓪Plan, 2026-10-28. The user's clarification: this is about **how Arslan does work** (the user said "办事风格"), not how it talks, and it applies to tasks, not chit-chat. It edits the same prompt section as STY, so it is a second PR on this card, after STY's.

| Item | Content |
|---|---|
| Lane | Whoever writes STY (#452, ⑥Helper). ⓪Plan runs the bench before and after. |
| Tier | Must, in STY's tier (the user decided it goes with STY). |
| Depends on | STY's prompt PR merged first (same lines). The plan-mode part depends on S5a and a demo mock the user approves first. |
| Merge position | After STY. It is a system-prompt hot-file change, so it waits behind any open K-line prompt PR, as STY does. |
| Migration | None |

### What changes

The working method in `_ARSLAN_SYSTEM` (`server/orchestrator/arslan.py:124-140`, added by K5 in v0.1.63) gets four points. Three of them extend lines that are already there. Following `docs/sessions.md` §12 rule 3, they are merged into those lines rather than added as a second list.

1. **Go deeper, not bigger.** Before starting a task, consider what a top professional would do here. Do what fits the request well. List anything beyond the request as a suggestion at the end; don't widen the scope on your own. (New line.)
2. **Start from the raw material.** Read the real file, data or original page, not memory, a summary or someone's retelling. Citations point back to the source. This extends `:127` ("Read before you change") and `:135` ("cite only sources you actually read").
3. **Use the right tools.** Run what can be run (the tests, the command, opening the produced file) instead of reasoning that it should work. This extends `:128` ("Check after you change").
4. **External evidence before "done".** Saying it is done needs evidence beyond Arslan's own word: a passing test, command output, the file existing, the source matching. Say plainly what was not verified. This lines up with INB9's acceptance sheet (`docs/plans/0164/INB-inbox-progress.md:375`): ✅ needs evidence, and claims backed only by the model never go in ✅. It also extends `:128`.

**Background jobs:** `BACKGROUND_SYSTEM` gets the same four points in one line. STY already changes its ending.

**Plan mode (S5a):** the plan shows these four as its sections:
- references, plus "what a pro would add, for you to pick";
- materials;
- method;
- how it will be verified.

The acceptance sheet at the end is checked against these sections. This is UI, so a clickable demo mock goes to the user before any UI code (user, 2026-10-28). It belongs to S5a's PR, not to this card's prompt PR.

### The four card lines (`docs/sessions.md` §6, after #468)

1. **References:**
   - Claude Code's system prompt and its "verify before claiming done" practice;
   - Codex's AGENTS.md conventions and the OpenCode `AGENTS.md` style rules the user picked (https://github.com/sst/opencode/blob/dev/AGENTS.md);
   - Hermes' task loop.

   The PR links the exact passages it read. **Listed for the user, not built:** a per-task "professional checklist" (by task type) that Arslan fills in before starting. It is bigger than four lines in a prompt and would need its own card.
2. **Raw material:**
   - the current prompt text at `server/orchestrator/arslan.py:124-140` and `BACKGROUND_SYSTEM`;
   - the M64 bench transcripts of tasks where Arslan said "done" without checking, read on this Mac;
   - the card records only the counts and the task ids.
3. **Method:**
   - prompt text first;
   - a pytest that pins that the four points are in the working method and that the chit-chat part (`:45-48`) is unchanged;
   - the M64 bench before and after, on the same tasks (DeepSeek);
   - STY's 20-reply read for tone;
   - a mutation check: remove the new lines and the pin test goes red.
4. **External evidence:**
   - **Bench:** Pass rate does not drop, "waiting for you" does not rise, no new error types (K5's gate style), and the cache hit rate does not drop.
   - **Count from the bench transcripts:** "done" claims without a check or test run in the same turn, before vs after. Target: fewer, not zero.
   - **Tone:** the user's read of STY's 20 replies shows no colder chit-chat.
   - CI run ids on the PR.

### Acceptance

- The four points are in the working method; three are folded into K5's lines, with no duplicate list.
- BACKGROUND_SYSTEM gets the same one line.
- Bench gate as above.
- The "done without evidence" count does not rise, and the PR reports it.
- STY's read still passes.

### Size

About +10 product lines (prompt text) and about +20 test lines. The bench run is the main cost and stays inside the DeepSeek proxy cap.

### Risks

- Longer prompts change the cached prefix, so the first request costs more. Check the hit rate afterwards.
- "List extras at the end" can make replies longer. STY's read catches this. Extras go in one short list, only when there is something real to suggest.
