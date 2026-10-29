# 多会话协作规矩

**所有在本仓库工作的会话，开工前必读。** 当轮的分道、任务卡和合并顺序，见 `docs/plans/0162/README.md`。

**唯一的共享内存是这个仓库。** 交接、计划和决定都要以提交物的形式存在。下面这些都不算交接：会话自己的记忆、草稿区、本机文件、聊天记录。

---

## 1. 编号与职责

| 编号 | 职责 |
|---|---|
| ⓪Plan | 维护当轮计划和任务卡；M 线（跑分、本机周报、体感验收）；发版前判定是否达到门槛 |
| ①iOS | iPhone App（另一个仓库）。本仓库里只读它依赖的 Mac 端契约 |
| ②Main | 实现 F、C、K、S 各线；管合并队列、共享文件仲裁、迁移号登记、CI 健康、版本号与发版准备 |
| ③Hands | 负责 Hands：`desktop/hands/**`、`server/registry/hands_tools.py`、`server/services/hands_service.py`、`server/api/hands.py`、`scripts/hands_smoke.py` |

- 新开的会话往后编号（④、⑤……），开工前先在当轮 README 的分道表里登记。
- 版本号、打 tag、发布、合并，都由用户拍板、用户点。例外：决定 U9（2026-10-18），⓪Plan 可以合并同时满足四条的 PR（CI 绿、完成证据四项齐、另一个会话审过、按当轮 README §3 的顺序）；打 tag 和发布仍只归用户。 **Replaced for merging (user, 2026-10-28, confirmed in ⓪Plan's chat):** sessions merge PRs that are not on the security surface themselves, through GitHub auto-merge; see §5 "Who merges". Tags and releases stay the user's.

## 2. 文件归属

- **默认规则：** 谁的任务卡，谁改卡上「改哪些文件」列的文件。卡上「不许碰」的文件不改。
- **Hands 的文件归 ③Hands。** 其他道的卡要动它们，必须由 ③Hands 审。
- **Bridge 契约文件不改帧格式。** 这些文件是：`desktop/bridge/**`、`server/ws/bridge.py`、`spec/mobile-bridge/**`、`server/api/phone.py`、`server/services/phone_*.py`。确实要改，先问 ①iOS 和 ②Main。
- **发现要动别人的文件时：**
  1. 停下，不要改；
  2. 在 PR 描述或给对方的消息里，写清楚要改什么、为什么；
  3. 由文件的主人来改，或者由 ②Main 仲裁后指定一个人改。

## 3. 共享热点文件

| 文件 | 规矩 |
|---|---|
| `server/orchestrator/arslan.py`、`server/orchestrator/tool_loop.py`、`server/orchestrator/memory.py` | 当轮 K 线主改。其他 PR 只做小改动，合并时排在当前打开的 K 线 PR 之后；rebase 时两边都保留 |
| `web/src/locales/*.json`（6 种语言） | 新加的 key，6 种语言同一个 PR 一起加；不改别人的 key；冲突在文件末尾，rebase 时两边都留；`web/src/__tests__/locale-parity.test.ts` 通过才算完 |
| `docs/CAPABILITY_INVENTORY.md` | 生成物，不手改、不手工解冲突。rebase 后重新生成：`.venv/bin/python -m scripts.capability_inventory > docs/CAPABILITY_INVENTORY.md`（在仓库根目录、用项目的虚拟环境运行）。C5b 合并后，只在发版 PR 里生成 |
| `server/db/migrations/**`、`tests/server/test_migration_runner.py`、`server/db/models.py` | 迁移号按 §4 处理 |
| `server/main.py`、`web/src/App.tsx` | 只做小改动。路由和启动步骤加在末尾，不重排；rebase 时两边都留 |
| `docs/releases/*.md` | 只有发版 PR 写。每一句对用户的承诺旁边，写出对应的测试名 |
| `docs/plans/**`、`docs/specs/**` | 计划只由 ⓪Plan 改；任务卡的状态由 ②Main 更新；spec 只在决定变化时改，并注明日期 |

## 4. 迁移号

- **谁分配：** ②Main，在当轮 README 的登记表里分配。一个 PR 最多带一个迁移。
- **同步改的地方：** 加一个迁移要同时改这几处，缺一处 CI 就红：
  - 版本文件 `server/db/migrations/versions/_00NN_*.py`；
  - `server/db/migrations/runner.py` 里的导入和 `MIGRATIONS`；
  - `tests/server/test_migration_runner.py` 里的 id 列表；
  - `server/db/models.py`。
- **顺序：** `MIGRATIONS` 按数字升序排列。合并前，如果别的迁移已经先合了，该 PR 先把自己的号改成下一个空号，再合。
- **冻结：** 一个号只要进过正式版本，就永远不能改。`runner.assert_supported_schema` 会拒绝启动带未知 id 的数据库。
- **别碰真实数据：** 没合并的迁移，不许在用户的真实数据目录上跑；开发构建用临时数据目录。

## 5. 分支、PR、合并

- **分支名：** `claude/<版本><编号>-<主题>`，例如 `claude/0162-k1-native-tools`。
- **一个 PR 只做一件事。** 产品代码改动不超过约 800 行，测试、翻译和生成的文件不算在内；超过就拆。
- **PR 的写法：**
  - 标题写它推动的是哪个门槛；
  - 描述里链接对应的任务卡；
  - 描述里写「完成证据」四项（§8）；
  - K 线 PR 要贴跑分的前后对比，没有对比不合。
- **合并顺序**由依赖图决定，不是先到先得。顺序表在当轮 README。
- **Who merges (user, 2026-10-28; relayed by ④参谋 and confirmed by the user in ⓪Plan's chat; replaces U9 for merging):**
  - **The session merges** (GitHub auto-merge): docs, plan cards, bench scripts, tests, and deletion-only PRs, all outside the security surface. Condition: another session's OK **at the current head**, and **every** check on that head green (not only the required ones; the `language` job, for example, is not required yet). The authoring session enables auto-merge with `ccd_pr` `set_auto_merge`; GitHub merges when the required checks pass. **Timing (found 2026-10-29):** GitHub refuses to enable auto-merge on a PR that is already mergeable ("clean status"), so enable it once the OK is in and every check that is *not* required has passed (today `language`; the ruleset requires `backend`, `frontend`, `macos`, `secrets`), while a required one is still running. If all checks are already green, a session cannot merge it (a plain `gh pr merge` is blocked); name it to the user, who merges.
  - **The user merges** everything else: anything on the security surface, and ordinary product code (for example BR2's file grouping) unless the user says otherwise. The security surface here means:
    - the outside-content mark;
    - the sandbox;
    - the classifier;
    - command policy;
    - permissions and confirm cards;
    - the five modes;
    - the Bridge (pairing, keys, frames, what it offers the phone);
    - secrets and credential storage;
    - network egress checks (`net_pin`, the SSRF allowlist);
    - capability and MCP install checks;
    - memory and learned-practice writes;
    - Hands' policy;
    - CI and repository settings (`.github/workflows/`, branch protection, required checks);
    - dependency and lock changes (`pyproject.toml`, `uv.lock`, `package.json` and lockfiles);
    - migrations that drop data.

    Deleting a guard, a hard rule or a test of the security surface counts as security surface, not deletion-only.
  - **A push after auto-merge is on:** GitHub keeps auto-merge enabled across new commits. Disable it before pushing, and re-enable only after a new OK and green checks at the new head.
  - **Old base:** if a PR's CI ran on an old base and main has since changed files it touches, or code its tests call, merge main in (or rebase) and re-run CI before enabling auto-merge.
  - **The authoring session watches main's CI** for that merge commit, whoever clicked merge. If it goes red, open a pure `git revert` of that merge. The revert needs no new OK, only green checks; the author may enable auto-merge on it unless the reverted PR was user-merged, in which case the user merges the revert. Say so in STATUS and to the author.
  - **Blocked:** a plain `gh pr merge` is blocked by the auto-mode classifier. If the classifier also blocks binding the PR or enabling auto-merge (it did for ⓪Plan on 2026-10-28), stop, say so in STATUS, and leave the merge to the user. Don't work around it or ask another session to do it.
  - The merge order (§3 of the round's README) still applies. Tags and releases stay the user's.
- **rebase 纪律：**
  - 开 PR 前和合并前，各 rebase 一次到最新的目标分支（一般是 main；热修线是 `release/0.1.62`，见 §7）；
  - 冲突按 §3 处理；
  - 不 force-push 别人的分支；
  - 破坏性的 git 操作单独执行，不放进 `&&` 链里。
- **说 CI 绿时**，附上 run id 和结论。
- **Reviewing (user, 2026-10-28):** every review also points out over-defence: unnecessary defensive code, the same validation repeated in several layers, and single-use helpers or abstractions (§12).

## 6. 文档卫生

- **不写进仓库的东西：**
  - 本机绝对路径；
  - 私聊内容；
  - 用户数据库的摘录（只有汇总数字可以）。
- **草稿区**（系统临时目录）会被清理，不要放交付物。
- **范围冻结：** 新想法写进当轮 README 的「下一版候选」，不进本版。删死代码不在此列，条件见 §11 第 4 条。
- **Language (user, 2026-10-28):** everything written to GitHub is in English: code, comments, commit messages, PR titles, bodies and comments, plan docs and task cards, bundled skills, READMEs. Chinese written before 2026-10-28 is not rewritten; new lines added to an older Chinese file are English. Chat with the user stays in Chinese, and sessions give the user a Chinese summary in chat. Messages between sessions may be in either language. Exceptions: quoting exact Chinese inside an English sentence (UI labels, the user's or the model's words, session names such as ④参谋); data that has to match Chinese input (for example the secret keywords in `arslan/companion/content_policy.py` or app names in `desktop/hands/policy.json`); translation files and tables (for example `web/src/locales`, `desktop/src-tauri/native_menu_messages.json`, and the iOS `*.xcstrings` / `*.lproj`); tests, evals and fixtures whose input is Chinese; the multilingual `docs-site`; and, until the user decides, the iOS app's UI copy (its string catalog's source language is zh-Hans; comments, docs and commits in the iOS repo are English from now on). v0.1.64 adds a CI check (card LANG1 in `docs/plans/0164/README.md`) that looks only at lines a PR adds, never at whole files (about 250 files on main already contain Chinese). Commit messages, PR titles, bodies and comments are not files: they stay each session's job. The check is `scripts/check_added_chinese.py` (CI job `language`); run `python3 scripts/check_added_chinese.py --base origin/main` before pushing. It also passes a line whose Chinese is old text removed from the same file, or from the file it was renamed from (an edit around old Chinese). For a case no exception names, put the marker `lang-check: allow` on the line, or add a narrow path glob with a reason to `.github/lang-check-allow.txt`. CI runs the base commit's copy of the checker and the allowlist too, so a new exception or allowlist entry lands in its own PR before the Chinese it allows.
- **A new card has four lines (user, 2026-10-28, relayed by ④参谋).** This applies to every new task card and every card that opens a new area, from now on (for example SIDE, ACM, HR, CLS, S5a and S5b, and later ones). Existing cards are not rewritten. Small PRs, fixes and cleanups don't need it.
  1. **References:** how mainstream tools do it, with links. Anything a top professional would add beyond what the user asked for is **listed for the user to decide, not built** (no silent scope growth).
  2. **Raw material:** the real data the card is built from, not a session's summary: the user's own database opened read-only (`mode=ro`, only where the session is allowed to read it; never the secret files), real logs, recordings, code at `file:line`. The session reads it; the card records only what the first bullet of this section allows: aggregate numbers, row shapes without content, and `file:line`. Never excerpts of the user's data, private chats or local paths.
  3. **Method:** the tools, and how it will be tested: a failing test first, a mutation check, a bench task, probes through `scripts/dev/probe.sh`.
  4. **External evidence:** what shows it is right without relying on a session's word. For example a CI run id, a test that goes red when the fix is removed, bench numbers against the baseline, the user's real-Mac smoke test, or an iPhone on a real device. "A reviewer said OK" alone does not count for this line.

## 7. 发版

- **版本号的唯一来源**是 `desktop/src-tauri/tauri.conf.json`，必须是三段 semver：
  - 四段的版本号（比如 0.1.61.1）读配置时就会报错；
  - 带 `-` 的 tag 会被发成预发布版，更新器看不到。
- **发布说明：** 每一句对用户的承诺，都要对得上一个测试。
- **热修走发版分支：** 从上一个正式版的 tag 拉出 `release/<版本>`（这一轮是 `release/0.1.62`），热修 PR 都合进这个分支；发版后把这个分支合回 main。热修发布前，热修改到的热点文件不接别的 PR。细节见 FR 卡。
- **打 tag** 要用户点头；**发布**由用户点。

## 8. 完成证据

每个 PR 的描述、每次汇报「做完了」，都写这四项。**没有这四项，不算完成。**

1. **做了什么验证：** 哪条命令或哪个测试，结果是什么（说 CI 绿要附 run id 和结论）；
2. **覆盖到哪；**
3. **没覆盖到哪；**
4. **还剩什么风险。**

## 9. 旧路径要写删除条件

- 任何「先留着」的旧代码、兜底或兼容路径（包括回退开关），都要在**代码注释**和**任务卡**里写明：哪个版本删，或者满足什么条件删。
- 例子：K1 保留的旧文本渲染，写「v0.1.64 删」。
- **代码注释里用固定的写法：** `DELETE-BY: v0.1.64`，删除条件写在后面（例如 `DELETE-BY: v0.1.64 if M2 shows …`）。这样发版前一条 `git grep -n 'DELETE-BY:'` 就能列全（§11 第 2 条）。已有的自由写法（「Deleted in v0.1.64 if…」「stay until v0.1.64」），下次改到那个文件时换成这种写法。
- 只写「先留着」的，审查时不过。
- 写着本版或更早版本删、到发版时还在的，发版前要查出来，见 §11 第 2 条。

## 10. 方法包（superpowers 与 Aegis 试点）

- v0.1.62 发布前，所有会话照旧用 superpowers。
- v0.1.62 发布后，只在 ②Main 的 C 线试用 Aegis 方法包，做法见 `docs/plans/0162/README.md` §9。
- 一个会话里不要两套同时装。试点结论出来前，其他会话都不换。

## 11. 换掉就删掉

用户 2026-10-21 批（总计划 U12）。目标：到 v0.1.65 是一个干净、简单、好用的 Arslan，不再出现「事情没做完就换主题，旧的东西变成死代码」。

1. **同一版里替换。** 引入新做法的卡，在「改哪些文件」里写明删掉它取代的哪些旧东西，新旧在同一版里做完。验收写「旧的已经没有了」，用 `git grep` 查不到为证。从 v0.1.64 的卡开始。
2. **删除期限到了还没删，就不发版。** §9 要求每个「先留着」的旧路径写明哪一版删。每版发版前（从 R63 开始），⓪Plan 查代码注释里的 `DELETE-BY:`（§9）和任务卡，列出写着本版或更早版本删、但还在的旧路径，写进门槛判定。还没换成固定写法的旧注释，也按自由写法再查一遍；只写了卡名、没写版本的（例如「F5b deletes them」），按那张卡所在的版本算。没删的不发版，除非用户逐条同意顺延，并写明原因和新的期限。
3. **上一版的删除没合完，不开新的子系统。** 从 v0.1.64 开始：上一版计划里排了的删除（C 线的卡、各卡写明本版删的旧路径）没有全部合并之前，不开新子系统的卡。v0.1.63 已经排好的卡（例如 S3 检查点）照当轮 README §3 的顺序做，不受这条限制。同一时间只做一个新子系统。修 bug、修安全问题不受这条限制。
4. **删死代码不受范围冻结限制**（§6），条件全部满足才行：
   - 确认没人引用：逐个名字 `git grep -w` 查过，结果贴在 PR 里；名字还可能以字符串出现（注册表的键、`getattr`、服务端发出的翻译键、模板里的键），所以也按字符串查一遍，PR 里写明注册表和翻译键查过了；
   - 不改任何行为；
   - 产品代码每个 PR 不超过约 800 行（只做整份删除的，照总计划 U2 的例外）；
   - 不插队：按当轮 README §3 的顺序排，不挡 K 线、S 线；K 线的卡正在改的热点文件（§3），等那张卡合了再删；
   - 发版前最后一轮跑分（R63 第 3 步）开始以后，不再合这类 PR，让最后一轮测的就是要发的东西。
     这个截止只管计划外的删死代码 PR。计划里的删除卡（C 线、F5b 这类）是本版的卡：「必须」的照 R63 的依赖，要在候选版之前合完；没合完的「应该」「可以」照 R63 第 1 步顺延，它们写下的删除期限一并由用户逐条顺延（第 2 条）。

   还在跑、只是用得少的功能，不算死代码：删它是改行为，要用户定。
5. **缠住了先剪线，不整块推迟。** 一大块旧代码只靠一两处调用连着的，先单独剪掉那几处调用，再按第 4 条整块删。剪线要是改了行为，先由用户定。例：专家时代的那一块约 6.7k 行，只靠技能锻造「评估要选分身」这一根线连着；剪不剪由用户在 v0.1.64 定。
6. **每版发布说明写产品代码的净行数。** 产品代码指 `server/`、`arslan/`、`web/src/`，不含测试和翻译，和上一个正式版的 tag 比（这一轮是 v0.1.62）：

   ```bash
   git diff --shortstat v0.1.62 HEAD -- server arslan web/src ':(exclude)**/tests/**' ':(exclude)**/__tests__/**' ':(exclude)**/*.test.ts' ':(exclude)**/*.test.tsx' ':(exclude)web/src/locales/**'
   ```

   v0.1.63 到 v0.1.65 的目标是负数。这是目标，不是门槛：必要的修复不因为它不做。

## 12. Code: no over-defence

User, 2026-10-28 (relayed by ④参谋). Adapted for Python from OpenCode's `AGENTS.md` (Style Guide, General Principles). Measured on main `96bdf096` (`server/` and `arslan/`, tests excluded, about 65k lines): 808 `try` blocks, 294 broad handlers (`except Exception`, `BaseException` or bare), 59 of them silent swallows (the body is only `pass` (32), a constant `return` (25) or `continue` (2)). Cleanup card: EXC1 in `docs/plans/0164/README.md` §3.7.

**Security boundaries (all four rules):** the security model's decided boundaries are not speculative edge cases, and checks on them are not "repeated validation". They are:
- outside content and its mark;
- the sandbox (Seatbelt profiles and their builder);
- command policy;
- permissions, the five modes and confirm cards;
- memory, learned-practice and other persisting writes;
- Hands' own policy (the helper's never-list);
- secrets, tokens and local auth (the API token, the WebSocket origin check, `crypto_boot`);
- network egress checks (the SSRF allowlist, the LAN scan);
- capability and MCP install checks;
- the Bridge;
- the approval ledger.

Defence there follows the security process (the user decides, a review at effort=max), not rules 1–3; rule 4's comment and fail-closed requirements apply there too, so the EXC1 check covers security code. A check repeated across a process or privilege boundary is defence in depth, not repetition: for example the Hands helper's own never-list (`server/services/hands_service.py`, `desktop/hands/src/policy.rs`) or Seatbelt on top of `terminal_policy` (`server/services/command_sandbox.py`). Anywhere else, the rules apply.

1. **No speculative defence.** Before adding code for a race or edge case that is speculative or very unlikely, write down the concrete failure (what input or timing gives what wrong result), how likely it is, and what the extra code costs. Put it in the PR description. A reviewer may ask for the code to come out. Don't grow scope quietly for theoretical robustness.
2. **Validate once, at the boundary that owns the value**, then pass typed values inward (a pydantic model, a dataclass, an enum, a `NewType`). Don't re-check the same thing at every layer. When a value is checked in more than one place, keep the check at the owning boundary and delete the rest. This is also the direction for the security model: the S64-0 and S64-0b holes came from the outside-content mark being carried by hand along many paths; the fix is to set it once at entry and honour it at every sink.
3. **No premature abstraction.** Inline logic that is used once. Extract a helper only when it is reused, hides a genuinely complex boundary, or names a real concept. No base class, protocol, registry or factory with a single implementation.
4. **Keep complexity down.** Avoid `try`/`except` where the error can't happen or the caller already handles it. Catch the narrowest exception you expect. Don't split one clear function into several small ones.
   - **A broad catch that swallows** (`except Exception` or `BaseException` or a bare `except`, whose body only passes, continues or returns a constant) needs a comment on the `except` line saying why swallowing is right, for example `# noqa: BLE001 — a ledger write failure does not change the decision`. A bare `# noqa: BLE001` is not a reason. Otherwise narrow it or log it.
   - **On an execution or permission path, a swallow fails closed** (the returned constant asks, sandboxes or refuses), and its comment says so, for example `# noqa: BLE001 — unreadable means the default: sandboxed`. A swallow that fails open there is a security bug, not a style issue.
   - Catching `asyncio.CancelledError` and not re-raising needs the same comment (for example, awaiting a task you just cancelled during shutdown).

**Reviewing (every review, by sessions and by Codex):** besides correctness and the evidence (§8), point out unnecessary defensive code, the same validation repeated in several layers, and helpers or abstractions with a single use. Name the file and line and say what to remove; the author answers each one (remove it, or state the failure mode it guards against).
