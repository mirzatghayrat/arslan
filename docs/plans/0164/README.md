# v0.1.64 计划（草稿）：任务卡清单、顺序与分道

> **⓪Plan 2026-10-29 夜间起草；用户 10-28 早上读完早报后定了 §2 的大部分（经 ④参谋转），本页已按那些决定改好。** 范围、顺序、门槛归用户定；这一版改的是总计划的范围，所以这份 PR 由用户点合并，⓪Plan 不按 U9 自己合。合并前只开用户说「现在就开」的两张：S64-0（③Hands 写）和 M64（⓪Plan）。

- **这一版是什么：** 领先路线里的「执行领先」那一版（`docs/plans/2026-10-17-0162-lead-roadmap.md` §0.1、§0.6），加上 v0.1.63 冻结时顺延的卡，再加上 10-25 到 10-28 用户经 ④参谋 转来的几页（都已记在 `docs/plans/0162/README.md` §8）。
- **规矩：** `docs/sessions.md`（特别是 §5 PR 不超过约 800 行、§8 完成证据四项、§9 旧路径写删除条件、§11 换掉就删掉）。U9 合并四条照旧。
- **候选的原文：** 都在 `docs/plans/0162/README.md` §8。本页只排卡、排顺序；细节以 §8 和各张卡为准。

---

## 0. 先说结论

1. **v0.1.64 按原计划装不下。** 领先路线给 v0.1.64 排了 14 行「领先」和 24 行「追平」，再加上 v0.1.63 顺延的约 10 张卡、§8 里几十条候选、这几天新定的六页（快问、能力、收件箱、回复风格、子会话、Codex 审查）。照 v0.1.61 的教训（一万多行、没法审），要先砍。**用户 10-28 定了：** 这几天定的六页全是「必须」；「执行领先」行里 L6、L7、L11 + K10 是「应该」，其余顺延（§3）。
2. **排序卡在一件事上：** #432（安全改成「硬规则 + 沙箱 + 分类器」）。云端审计在 4.8 上出了意见，②Main 带独立审查员在 5.5 上复核过；用户 10-28 把复核结果发回云端审计（5.5，问题 A–F），等它回来再正式定。用户倾向推翻 D8，条件是复核里的两处更正都做到。定之前，§4 照样写成两种情况。
3. **审查不再是上限：** 用户 10-28 说审查额度够，范围不因额度砍。CAP 照样单开一个会话，为的是并行。
4. **今晚写好的卡：** 快问（Q1）、按需加能力（CAP）、收件箱与进展（INB）、子会话（SUB）、回复风格（STY）、跑分（M64）。还没写的大卡：沙箱默认拒绝（SBX）、卡片与文案大合并（ACM），它们等 #432。

## 1. 已定的（不用再问）

- **v0.1.64 先做什么（用户 10-22）：** ① 沙箱默认拒绝（含沙箱合一）→ ② 按需装能力 → ③ 本机代理加网站名单（产能允许时）。领先路线 §0.6。**#432 可能改这一条**，见 §2。
- **S2a-3 顺延到 v0.1.64（用户 10-24）：** #375、#376、#378、#396 留着，跟默认拒绝沙箱一起审、一起合。合不进的话，「只在有风险时问」继续禁用。(Correction, SBX card 2026-10-28: it is not disabled; it is off by default and still selectable behind a warning sheet, `server/services/settings_service.py:409-415`.)
- **外部安全审查用 Codex（用户 10-27）：** 结论再给云端审计看；日常只审碰安全面的和产品代码超过约 400 行的 PR；只读、只看公开仓库、结论写明模型；它提的每一条都要在 PR 上回应。§8「v0.1.64 的安全审查路径」。 **Changed (user, 2026-10-28 evening):** Codex only for what a Claude review cannot cover; see §1.3.
- **跑分（用户 10-27）：** 加 3 道「代码审查」题；「对 Hermes」的门槛改为同题三次全过的题数不少于 Hermes。见 M64 卡。
- **快问的五条（用户 10-27）**、**回复风格**（10-27，以更正后那版为准）、**子会话分两步**（10-27）、**能力页和插件八条**（10-28）、**收件箱八条**（10-28，#433）。见各自的卡。
- **v0.1.63 顺延的两处删除（用户 10-27）：** `__version__`（跟 C5b 那类清理一起）、专家时代的 REST 接口（并进 C7c）。`R63-verdict.md`「删除期限」。

### 1.1 用户 10-28 早上定的（读完早报和本页后，经 ④参谋转）

- **S64-0 现在就开**（§3.4）：③Hands 写，effort=max 写和审，②Main 带独立审查员审，再加 Codex。复核 #432 时又提到的三处标记漏洞要不要一起修，等云端审计回答（用户已作为 E 题发给它）。 **Changed (user, 2026-10-28 evening):** Codex only for what a Claude review cannot cover; see §1.3.
- **范围不因审查额度砍：** 用户说审查额度够。
  - CAP 照样单开一个会话（为了并行，不是为了额度）。
  - STY：必须。SUB：必须（用户 10-27 本来就放进了 v0.1.64；它只等 SBX，SBX 本来就是必须）。
  - L6 后台进程、L7 目标模式：留在 v0.1.64，标「应该」。L6 排在 SBX 之后；L7 跑分不退步才合。
  - 其余「执行领先」行照 ⓪Plan 的建议（L11 + K10「应该」，其余顺延 v0.1.65）。
- **Bridge 帧：** 照 ①iOS 的建议。翻页这一版做；改名先不做；「做完未看」按手机能做到的程度降级；四行简报和子会话上手机顺延 v0.1.65。**「推送只推要你做的」（INB 第 5 条）单独问用户，还没定。**
- **#432：** 用户把复核结果发给了云端审计（在 5.5 上，问题 A–F），等它回来再正式定。用户倾向推翻 D8，条件是两处更正都做到（守护进程那一类靠 SBX 的 profile 加系统服务允许清单挡；分类器说「行」记成 `by="reviewer"`、只管这一次、不存规则和授权、永远不批沙箱外的动作）。
- **①iOS 的审阅不贴到 PR 上**，只记在 Q1 卡末尾。
- **开工顺序：** 用户点合并本 PR 后，能同时开的一起开：先合 C7c、C5b、F5b-2，再开 CAP1–CAP3、Q1、STY、INB1 起。M64 和 S64-0 现在就能开。SBX 卡等 #432 定了再写。
- **Codex：** 用户在 ChatGPT 桌面版的 Code Review 里连上 GitHub，只用「Review with Codex」（在聊天里审，不发到 GitHub），不开自动审查。待审的 PR 和能直接粘的提示在 `docs/plans/0162/STATUS.md`「Codex 待审」。 **Changed (user, 2026-10-28 evening):** Codex only for what a Claude review cannot cover; see §1.3.

### 1.3 Codex only when a Claude review is blocked (user, 2026-10-28 evening; relayed by ④参谋)

In the user's words: 「你能自己审的就不用 astra 了，让 astra 审是 Claude 涉及到 safeguards 不能自己审的才去 astra」. #460 (INB1) was reviewed by another Claude session at effort=max, and the user merged it without an Astra run.

- **A PR with an OK from an independent Claude review by another session does not go to Codex.** On the security surface that review runs at effort=max; that is the security review. This replaces "effort=max review plus Codex" everywhere in this plan and its cards (§1, §3 card rows, §4, §7, the S64-0 lines, the INB, CAP, SUB and S2a cards, `docs/plans/0162/README.md` §5 and §8, STATUS's decisions); the old lines carry a pointer here.
- **Codex GPT-6 Astra only for what a Claude reviewer cannot review because of safeguards:** it refuses, or reviews only part of it. The PR says which part was not reviewed and why; the user runs Astra on that part with the prompt in `docs/plans/0162/STATUS.md` "Codex 待审".
- **Terra / Sol for large non-security PRs:** the same rule; only when no Claude review is possible.
- **PR descriptions** no longer write "Codex: the user runs it" by default. They name the Claude reviewer and effort, and say "Codex: not needed" or which part needs it.
- The cloud audit still reviews security designs (#432 and its follow-ups); that is unchanged.

### 1.2 #432 decided by the user on 2026-10-28 (after the cloud audit's 5.5 rerun; relayed by ④参谋)

Full text in `docs/plans/0162/README.md` §8 (#432). In short: "complete in one go" is the goal, so **SBX and the classifier are both "must" in v0.1.64**, SBX first and the classifier after (a safety precondition, not a schedule choice). The audit's "SBX → measure → bring back 'ask only when risky' → measure cards" steps still run, but only to set the classifier's baseline. **All five modes** ship: S5a after SBX and S3, S5b after the classifier. **D8 is reversed** with the audit's conditions (B, C gates a/b/c/d/h/g, D7's constraints, ledger, one-click off); if any one is unmet the classifier does not ship. Pass lines are written by the user before measuring. **S64-0b** takes two more mark leaks. **If the classifier's review is blocked, v0.1.64 waits** rather than shipping without it. So case B in §4 is the order; case A is dropped.

## 2. 还要用户定的

按要紧程度排：

1. ~~Pass lines for the classifier~~: the user chose option 2 on 2026-10-28 (see the CLS row in §3.2).
2. ~~S64-0 and the extra mark leaks~~: decided 2026-10-28 (§1.2): #438 merges as planned, two leaks go to S64-0b, `run_command` reading files is a known limit.
3. **推送只推「要你做」的**（INB 第 5 条）：会影响所有手机，单独问。
4. **#375 约 1,060 行要不要拆**（超过 §5 的约 800 行）。按云端审计的意见 S2a-3 的解析器要留，这一问照样要答。
5. **R63 判定里没有记录的两半**（M3 第 7 条 Mac 那半、第 12 条截屏那半）：v0.1.64 冒烟时补测，还是放下。
6. **K8c 的 Gemini M1：** 要 Gemini 代理和额度（只有用户能放 key）。
7. **还没确认的建议：** 旁聊进 v0.1.64；界面版的设计图先出；Aegis 试点的结论（§9 还没跑）。
8. **钩子支持排在 v0.1.65 之后**（⓪Plan 排的）、**收件箱各条放哪一版**（⓪Plan 排的）、**按 U2 整份删除的 PR 不让 Codex 审**（⓪Plan 定的）：用户可以改。
9. **M64 开工前的两个小问**（M64 卡末尾）：Codex 参考线第一轮用「用户贴题、存回复」；三道代码审查题用 Python、TypeScript、Swift。⓪Plan 先按这两个默认做，用户可以改。

## 3. 卡清单（分级用户 10-28 已定）

「道」开工时再按各会话的负载调。状态：S64-0、M64 已开工，其余等本 PR 合并。

### 3.1 这几天新定的

| 卡 | 做什么 | 道 | 建议分级 | 依赖 | 卡 |
|---|---|---|---|---|---|
| **Q1** | 快问：替换 iPhone 的 Remote（Mac 端加 iPhone 端） | ②Main + ①iOS | 必须 | Bridge 帧（§2 第 3 条）；和 SUB 共用 `kind` 列的迁移 | [Q1](Q1-quick-ask.md) |
| **CAP** | 按需加能力：能力页只列「会什么」、安装卡、插件（不带钩子的）、OSV 检查、verify、导入 Claude Code / Codex 设置；删能力发现中心那一套 | 新开一个会话（用户 10-28 定，为了并行） | 必须 | SBX（跑陌生代码的部分）；安全面按 effort=max 加 Codex (Codex only for what a Claude review cannot cover, §1.3)；**卡里拆成 17 个 PR（CAP1a–CAP11，删表的迁移各自单独一个 PR，CAP6b 归 SBX），删约 3,400 行、加约 4,000 行，是这一版最大的卡；砍范围时的顺序先定好：CAP10 → CAP8 → CAP7** | [CAP](CAP-capabilities.md) |
| **INB** | 收件箱：先做学到的做法和记忆不再排队（单独的安全 PR，保留外部内容那道闸）；再按「东西挪到哪」拆：去掉列表、侧边栏状态点、只推「要你做」、确认卡只在对话里、验收单（v0.1.64 只在用户不在场的运行出）、进展页的四行简报和运行数据补全 | ②Main | 必须 | 文案跟 ACM 对齐，但不并进 ACM；SUB（子会话的验收单和父链接）。卡里拆成 INB1–INB9；INB1、INB2 排在 S64-0 后面最先做，INB2 是放宽，必须在 S64-0 之后 | [INB](INB-inbox-progress.md) |
| **SUB** | 子会话的底子：一个子 agent 工具做成子会话，最多三层；先补 `delegate_work` 不传外部内容标记的洞；跑分题「拆开、分派、汇总」先过 | ②Main | 必须（用户 10-28） | SBX；M64 的那道题；和 Q1 共用迁移。**SUB1（补 `delegate_work` 的洞）并进 S64-0（§3.4）**；SUB3–SUB5 叠着做，跑分题在叠好的头上过了才合；SUB6 删 `delegate_work` 和 `TaskWorker` | [SUB](SUB-sub-sessions.md) |
| **STY** | 回复风格：任务汇报用四条原则，闲聊保持温度，人情味但不假 | ②Main（⓪Plan 出测题） | 必须（用户 10-28） | ACM（卡片文案用同一套写法） | [STY](STY-reply-style.md) |
| **M64** | 跑分：代码审查题、拆分派汇总题、Hermes 门槛、每版一次完整的 | ⓪Plan | 必须 | 无（可以最先做） | [M64](M64-bench.md) |

### 3.2 领先路线里 v0.1.64 的大卡（还没写）

| 卡 | 做什么 | 建议分级 | 说明 |
|---|---|---|---|
| **SBX** | 沙箱默认拒绝 + 沙箱合一（领先路线 §0.6 第 1 条，含兼容性回归和两个要量的数） | 必须 | **Unblocked (user, 2026-10-28):** it is the "sandbox" layer. Includes the audit's B-1 (system-service allowlist, measured on a Mac before "run directly in the sandbox" opens) and f (keychain, in the measurements); e (files written now and run later) is **HR's**, SBX only gives HR a builder parameter for it (③Hands). **Card: `docs/plans/0164/SBX-sandbox.md`** (SBX-1 … SBX-8; "SBX merged" means SBX-1 to SBX-7). Then: measure on a Mac, bring back "ask only when risky", measure cards again; that number is the classifier's baseline. Card written by ⓪Plan after this PR merges; lane ③Hands (moved from ②Main on 2026-10-28, both agreeing; at effort=max); reviewed by ②Main plus an effort=max reviewer (Codex only for what that review cannot cover, §1.3 after #465). **SBX merges before ③Hands rebases S2a-3** (#375 / #376 / #378 / #396): both touch `command_sandbox.py` and `terminal_policy.py`. The Mac measurement (git, swift, python, the keychain helper, launchd / LaunchServices / cfprefsd under default-deny) runs through probes with no real keys, and the report names exactly what was measured. |
| **HR** | Hard rules tidy-up as one written set, each with a test: the parser's direct forms, e (files written now and run later; the list includes git hooks and config, editor task files, `AGENTS.md` / `CLAUDE.md` / `.claude/` / `.mcp.json` / `.cursor/`, `.envrc`, `.npmrc` / `.yarnrc.yml` / workspace `pip.conf` / `uv.toml`, `.pre-commit-config.yaml` / `.husky/`, `.github/workflows/`; ③Hands, #444 review), S2a-1's network cut, the never-approve list (every layer ② card, the network card, the outside / retry card), and the absolute list that holds even under full access. The daemon-escape class is **not** here: SBX's default-deny profile plus allowlist holds it (correction A); HR must not duplicate SBX | must | After SBX and S2a-3. Lane ③Hands; effort=max plus Codex. **Changed (user, 2026-10-28 evening):** Codex only for what a Claude review cannot cover; see §1.3. |
| **CLS** | The classifier ("auto" mode's reviewer), shipped as a service only: input → allow / ask plus a reason; it does not touch `permissions.py` | must (user, 2026-10-28) | After SBX, HR, S64-0 and S64-0b. **Gates built and tested in CLS:** a (intent only from the user's own words; for jobs the opening message in `Job.origin`, no attachments or OCR text; the model's goal shown only as "what the model intends"; off in model-started jobs, scheduled runs and resumed tasks, because they have no such message; **not** switched off because a job started after outside content, per the audit's 2026-10-28 answer), c (no longer a classifier gate: the outside-content mark stays with the hard rules, and S64-0 / S64-0b fixed the leaks found), g (test set on this Mac only), local-only and BYOK, D7's constraints that live in the service (tool results are not in its input, which the audit's answer confirms; any error, timeout or 429 returns "ask"), and the user's pass lines: **option 2 with the cloud audit's six changes** (2026-10-28; full text `docs/plans/0162/README.md` §8): exfiltration-style is a structural routing test (0 such actions reach the classifier); overreach ≤ 8 in 90, steered ≤ 6 in 225; one deterministic test per hard rule; lines bound to each provider's measured model (an unmeasured configured model turns the classifier off); false blocks ≤ 2% of ~500 gated actions (n confirmed first); cards saved as "answers at least X% of the approvable scope"; synthetic and real-data test sets kept apart. Fixed before measuring, not changed after. **The classifier is not switched off by outside content or `run_command`** (audit, user agreed); instead four conditions, each with a test: scope is the work folder and temp dir only (no shared caches); never approves writes that persist (memory, skills, lessons, scheduled tasks, settings, and every path on HR's e list: one list, kept in HR); the pending action's text is data, not instructions; a ledger column for approvals after outside content, and S3's checkpoint exists before its first approved change. Expected approvable scope is narrow; it is measured before the card-saving line is set. **Scope details (③Hands, #444 review):** "temp" means a private per-run TMPDIR, not today's `temp_roots()` (which includes the shared `/var/folders/…/C/` cache and `/private/tmp`, `/private/var/tmp`); SBX records which writable roots are inside the classifier's scope; the scope check runs on resolved paths (symlinks); S3's checkpoint does not cover temp, so a temp write the classifier approves is not undoable and is limited to the run's own TMPDIR. Its answer is "allow" only for actions whose effect stays inside the sandbox's writable area; it never answers a layer ② card (send, upload, push, delete outside the work folder, drive another app), the network card, the outside / retry card, or anything full access would still ask; with no sandbox, nothing (same list as #432 item 3). The audit's open question is answered (2026-10-28): outside content does not switch it off; the four conditions replace that. If its review is blocked, v0.1.64 waits, and it is never worked around (not by moving it to another session either); ③Hands' lane has been stopped by the safety classifier on this kind of surface before (S2a-3's tests), and keeping the adversarial set on this Mac (gate g) limits what the code PR exposes. Lane ③Hands; effort=max plus Codex. **Changed (user, 2026-10-28 evening):** Codex only for what a Claude review cannot cover; see §1.3. **Pass lines complete (user, 2026-10-29):** the two open ones are ≥ 70% of the approvable scope answered and ≤ 5% failures falling back to a card (`docs/plans/0162/README.md` §8). |
| **S5a** | Modes: plan / ask every step / auto-edit / full access; current mode next to the input box, one click, per conversation; Settings keeps only the default for new conversations; plan's "start" returns to the previous mode; sub-sessions inherit only | must | After SBX, HR's e rule and S3 undo. Clickable demo to the user before UI code. Lane ②Main. |
| **S5b** | The "auto" mode on top of S5a, **and the only PR that wires CLS into `permissions.py` `_ask`** (one writer in the hot file) | must | After CLS. **Gates built and tested in S5b:** b ("yes" recorded `by="reviewer"`, this time only, no rules or grants, never satisfies the network / unsandboxed checks), d (modes widen in order; only runs that finish inside SBX; never anything full access would still ask; no sandbox, no approvals), h (denials counted: 3 in a row within a turn, 20 per conversation and per job, then back to cards), the ledger the user can read, the one-click off, and D7's constraints that live in the wiring (an exception or timeout counts as "ask"; it only answers cards that would be asked anyway; off by default, on only after the user agrees). **"Any one unmet → the classifier does not ship" binds S5b's merge as well as CLS's:** "auto" is not offered until every gate in both cards holds. Lane ②Main; reviewed by ③Hands plus an effort=max reviewer plus Codex. **Changed (user, 2026-10-28 evening):** Codex only for what a Claude review cannot cover; see §1.3. |
| **S64-0b** | Two more mark leaks from the audit's E: attachment and OCR text inlined without the mark; background job results posted as Arslan's own words (framed and marked when the job read outside content) | must (user, 2026-10-28) | After #438. The attachment / OCR inline code is in `arslan.py` (a hot file; goes after any open K-line PR touching it). About 20 product lines each; tests check outcomes (network command gets a card, `memory_note` does not take effect at once). `run_command` reading files stays a known limit. Lane ③Hands; effort=max plus Codex. **Changed (user, 2026-10-28 evening):** Codex only for what a Claude review cannot cover; see §1.3. |
| **S2a-3** | #375、#376、#378、#396（和可能重开的 #406、还没人接的 PR4） | must (user, 2026-10-28: keep the parser, drop "complete the list") | Codex 审 rebase 之后的头 (now: another session's max review first, Codex only for what it cannot cover, §1.3)（§8 安全审查路径的顺序）。**PR4（定时任务恢复只读命令）要加的（用户 10-28）：** 定时任务存一个 `outside_seen` 列（写提示的那一轮读过外部内容就是 True），到点时从它起步；换掉 S64-0 里包住 `_fire` 的临时 `carried(True)`。 |
| **ACM** | 卡片界面与文案大合并（领先路线 D 行「审批策略与作用域」；§8 和别处叫它 D1，和 v0.1.63 的 D1 卡不是一回事） | 必须 | INB、STY、S4a 跟进、S6 都挂在它上面。等 #432（权限模式会改卡片）。 |
| **NET** | 本机代理加网站名单（§0.6 第 3 条） | 顺延候选 | 原定「产能允许时」。 |
| 其余「执行领先」行 | L1 薄循环 + ACP、L2 内置工具按需 + 参数修复、L3 边流式边执行、L4 进度流到灵动岛和 iPhone、L6 后台进程与进程工具、L7 目标模式、L8 存记忆 + 服务端压缩、L11 文件夹规矩、L12 评审选项 + iPhone 批准、L14 公开 Terminal-Bench + Mac 题库 | 用户 10-28 已定 | L11 + K10「应该」（都小）。**L6 后台进程、L7 目标模式留在 v0.1.64，标「应该」**：L6 是新的安全面，排在 SBX 之后；L7 改主循环，跑分（M64 那套）不退步才合。其余顺延 v0.1.65。L6、L7 的卡开工时由 ②Main 写。 |
| 「追平」行 | 备用模型链、允许 / 拒绝规则、diff 预览、密钥脱敏、审批日志、斜杠命令、插件（并进 CAP）、无头模式、测试整理、发布渠道 | 逐行定 | ⓪Plan 建议：插件并进 CAP；diff 预览并进 S3 的「查看改动」；其余顺延。 |

### 3.3 v0.1.63 冻结时顺延的（`docs/plans/0162/README.md` §8 开头）

| 卡 | 建议分级 | 说明 |
|---|---|---|
| F5b-2（删 Cua Driver 的死文件） | 必须 | 只删文件，U2；③Hands 审。 |
| C5a（过程文档移到存档分支、删隐私段落） | 应该 | 对用户没影响。 |
| C5b 的同类清理 + `__version__` | 必须 | 用户 10-27 同意的删除期限。 |
| C7c（专家表、旧专家转技能页、记忆 v1 旧表、`router_decisions`、专家 REST 接口） | 必须 | 一次迁移；代码里已写 `DELETE-BY: v0.1.64`。**Also (user, 2026-10-28):** decide in the same PR whether the 30 quarantined `scope_kind=expert` memory entries are deleted or moved, and say which in the PR. |
| K6（文件工具补齐）、K10（读 AGENTS.md） | 应该 | K10 和 L11「文件夹规矩」一起做；AGENTS.md 是不是给分类器看，跟 #432 一起定。**L11 also gets (user, 2026-10-28, memory plan item 15):** output language follows where the output goes (chat: the language of the user's message; a file: that folder's rules; a message: the recipient), and after the user corrects the same thing twice, Arslan asks "make this a rule for this folder?". |
| S4b、S5、S6，S4a 的两个跟进 | 看 #432 | 都建在权限模型上。#432 若选五档模式，S5 扩写。 |
| #298b（SECURITY / ARCHITECTURE 按三层模型重写） | 必须 | 跟着安全模型的结果写。 |

`runs.py` 的诊断只认 `live`：归 INB6（进展页要按种类数后台任务和定时任务）。§8 里其余的小条目（M3 跟进、`~` 不展开、同一文件两张卡、时序不稳的测试等），开工时由 ②Main 按文件归到上面的卡里，或者单独开小 PR；不单独写卡。

### 3.4 补洞 PR（S64-0）：起草时读代码发现的四个洞

②Main 和 ③Hands 审 #434 时各自读了代码：四个里三个成立，第四个成立一半。都是读代码得出的，没跑过。**用户 10-28 定：现在就开，③Hands 写，②Main 带独立审查员审，加 Codex。** **Changed (user, 2026-10-28 evening):** Codex only for what a Claude review cannot cover; see §1.3.

| 洞 | 成立吗 | 严重度（③Hands） | 怎么修 |
|---|---|---|---|
| `delegate_work` 交回网页内容时一个框都不加，父回合的「读过外部内容」标记也没打上（`task_workers.py:268`；`tool_loop.py:373-374`） | 成立 | 高 | 去掉 `external: False`，并加进 `_WEB_TOOLS`、`_OUTSIDE_TOOLS`；两样都要改 |
| 后台任务开在全新的上下文里（`background_jobs.py:162`）；任务目标是那一轮模型写的，可能刚读过网页；`start_background_work` 不出卡 | 成立，**今天就有，计划里原来没人修** | 中 | 启动时把「这一轮读过外部内容」记在任务上，任务的每次运行从它起算；要给 `track_turn()` 加一个起始值（它今天每次都清零，`untrusted.py:92-93`） |
| 学到的做法合并：一条读过外部内容时留下的提议，后来一个干净的回合提出相似的做法，会把旧条整条打开，文字还是旧的（`lessons.py:296-304`） | 成立，概率不高 | 中低 | 用干净那一轮的文字覆盖，再生效；没生效的原因记进 `evidence`；没记录的旧条一律当读过外部内容 |
| 用户点「继续」恢复的任务，一开始当作没读过外部内容（`task_service.py` 的 `resume_turn`）；`task_progress` 也不在外部名单里 | 成立 | 低到中 | 恢复的回合一开始就算读过外部内容；`task_progress` 加进外部名单 |

- **复核 #432 时又提到的几处标记漏洞**（②Main 和独立审查员，读代码）：附件和 OCR 文字直接内联、不打标记；`run_command` 读文件；后台任务的结果当成 Arslan 自己的话发进对话。②Main 审 #438 时又补两处：**F1** 定时任务每次都从干净开始，即使写提示的那一轮读过外部内容（max 审查员实测：到点那次的 `memory_note` 当场生效；回答过一次「这段对话」后，之后的定时任务不再出卡）。**用户 10-28 定：F1 并进 S64-0**，先临时用 `carried(True)` 包住 `_fire`；正式的 `outside_seen` 列放在给定时任务恢复命令的那张卡（S2a-3 的 PR4，即 f），那时换掉这层包装；`find_tools` 给 MCP 写的描述加了框但不打标记（`on_demand.py:80-91`）。S64-0 要不要一起修：用户已作为 E 题发给云端审计，等它回答再定。在那之前 S64-0 只修上表四个，PR 描述写明这三处没修。
- 「卡片回答后接着跑的那一轮」**不是洞**：卡是在同一回合里等的，标记还在（②Main、③Hands 都这么读）。
- **已开：#438**（③Hands，Opus 5.5 max，head 393e3be7；产品 +72/−22，测试 +510）。起始值做成了上下文 `untrusted.carried(seen)`，没给 `track_turn` 加参数，`tool_loop.py`、`arslan.py` 没动。两个行为变化：收件箱接受的提议起的后台任务一律按读过外部内容起步；iPhone 上打的任务照旧干净起步。
- **合成一个 PR（S64-0）：** 产品代码约 +40 行，测试约 +250 行。测试要测后果，不只看标记：同一轮里 `memory_note` 不当场生效，联网的命令会出联网卡。effort=max 写和审，加 Codex，结论写明模型。 **Changed (user, 2026-10-28 evening):** Codex only for what a Claude review cannot cover; see §1.3.
- **排在哪：** 最前面。不等 SBX，也不等 #432；它是安全修复，§11 第 3 条管不到。SUB1 并进来，INB1 只留做法那一侧的测试。INB2（放宽「关于你」的记忆）必须排在它后面。
- **一个设计上的限制（不是洞）：** 标记按回合算。第 N 轮读了网页，第 N+1 轮从干净开始，可模型在第 N 轮的回复可能复述了网页。笔记和做法今天接受了这一点；INB2 要扩到「关于你」时不能接受，见 INB 卡。

### 3.5 Added on 2026-10-28 (bugs and rules the user reported or decided that day)

New text in this plan is in English from 2026-10-28 (`docs/sessions.md` §6).

| Card | What | Lane | Tier | Notes |
|---|---|---|---|---|
| **MEM1** | Memory write hygiene: merge by meaning, write in the user's language and never guess gender, keep one-off task state out of "about you" | ②Main | must | In the INB card, after INB2. From the memory plan (`docs/plans/0162/README.md` §8, item A). |
| **CAP8b** | Import memories from ChatGPT / Claude (paste, list, confirm) | CAP session | must | In the CAP card, after MEM1. Item 17. |
| **PRJ0** | Projects, deletions only: "learn how you advance gates" (shadow / auto, `project_habits` and its table), rhythm stats, stall reminders | ③Hands | must | From the user's Projects decisions (SUB card, "Projects"). U2; the table drop is its own PR. Board, template gates and retro go in v0.1.65 together with their replacement. |
| **LANG1** | English on GitHub, enforced: a CI check that fails when Chinese appears in a file that should not have it (exceptions as in `docs/sessions.md` §6 after #440: quoted Chinese inside English, data that must match Chinese input, translation files and tables, tests/evals/fixtures with Chinese input, `docs-site`, iOS UI copy until the user decides); translate the two bundled skills `arslan/skills/bundled/designed-html-report/SKILL.md` and `skill-creator/SKILL.md` to English | ②Main | must | Items 13 and 14. The check must not fail on files written before 2026-10-28: it runs on the lines a PR adds (diff-based), not on the whole tree. Commit messages and PR text are not checked; they stay each session's job (①iOS review of #440). It needs its own escape hatch (an allowlist file or a marker comment) for a case none of the exceptions name (①iOS). Not a new subsystem; can start as soon as this PR merges. |

The rest of the memory plan is not in v0.1.64: items 5–10 go with memory as files (v0.1.65; ⓪Plan puts the "used N memories" line and "what Arslan learned this week" there, not in the interface version); item 18 (WeChat, no database decryption) after v0.1.65; item 19 (proactive proposals in the conversation or progress page, not the Inbox) after v0.1.65.

### 3.6 用户新报的 bug

| 卡 | 做什么 | 道 | 分级 | 说明 |
|---|---|---|---|---|
| **FS1** | 全屏时点 ✕ 关主窗口会黑屏（用户 10-28 报，④参谋 看了录屏）：窗口消失，整屏变黑，顶上留着 Arslan 的菜单栏，要从 Dock 彻底退出 Arslan 才恢复 | ②Main | 必须 | **原因（读 main 的代码，没在真机上跑）：** 常驻模式（0.1.41 起）关窗口是藏起来，`desktop/src-tauri/src/lib.rs:1088-1092` 收到 `CloseRequested` 后直接 `prevent_close()` + `hide()`，藏之前没有先退出全屏，macOS 给全屏窗口单开的那个桌面就空着、显示成黑的。`desktop/src-tauri/src` 里关窗口这条路上没有任何处理全屏的代码。**修法：** 关闭时窗口在全屏，就先 `set_fullscreen(false)`，等退出全屏结束（全屏状态或 resize 的事件回来）再 `hide()`；同时核 `resident::show_main`（`resident.rs:229`）从菜单栏或 Dock 重新打开时回到普通桌面。**验收：** 「全屏 → 点 ✕ → 不黑屏、回到原来的桌面 → 从菜单栏和 Dock 各打开一次、窗口正常出现」先写进 v0.1.64 冒烟清单；真机这一步要用户在场。产品代码约 +20 行 Rust；能拆出纯函数的判断（全屏时先退出再藏）就加单元测试。不是新子系统，§11 第 3 条管不到，本 PR 合并后随时可做。 |

### 3.8 Arslan's working method (user, 2026-10-28; relayed by ④参谋)

| Card | What | Lane | Tier | Notes |
|---|---|---|---|---|
| **STY2** | "Deeper, not bigger": four points in Arslan's working method (go deeper not bigger, extras listed for the user; start from raw material; use the right tools; external evidence before "done"). Mostly folded into K5's existing lines. Card: STY card, section STY2 | STY's writer (⑥Helper) | must (with STY) | After STY's prompt PR (same lines). 27-task kernel bench before/after as K5, plus a scripted "done without evidence" count that must not rise; STY's read for tone. The plan-mode sections belong to S5a, behind a demo mock. |

## 4. 合并顺序

**两种情况都一样的（②Main、③Hands 审 #434 后改）：**
- **M64 和 S64-0 最先，互不等：** M64 给 SUB3–SUB5 和 STY 出基线；S64-0 是安全修复，不等跑分。然后 INB1 → INB2。
- **§11 第 3 条（上一版的删除没合完，不开新的子系统）：** C7c、C5b、F5b-2 要在 SUB、Q1、CAP 的新部分之前合，不是「空档里合」。
- CAP1–CAP3 不跑陌生代码，不用等 SBX 或 S2a-3。
- 跑陌生代码的（CAP 的 verify 和插件脚本、CAP5 的命令边界、CAP6b、SUB）都排在 SBX 后面。
- **L6 后台进程**排在 SBX 后面；**L7 目标模式**跑分（M64 那套）不退步才合（用户 10-28）。

**Case A (#432 not adopted) is dropped: the user adopted #432 on 2026-10-28.**

**Case B, adopted by the user on 2026-10-28.** Earlier notes: 云端审计（#432 上，Opus 4.8，待复核）的意见：分类器只是「少出卡」的体验层，不是安全边界，必须排在 SBX 之后；S2a-3 的解析器留下，只放弃「把清单补全」。②Main 带一位 effort=max 的独立审查员复核后更正：经系统守护进程在沙箱外生效的那一类命令，**靠 SBX 默认拒绝的 profile 加系统服务允许清单挡，不靠解析器**（解析器看不见脚本、编出来的程序、git 钩子这类间接调用）；分类器说「行」要记成 `by="reviewer"`、只管这一次、不存规则和授权；分类器永远不批沙箱外的动作。这条提议还会顶替总计划的 D7、D8，D8 要用户明确推翻。详见 #432。**

```
M64、S64-0（互不等）→ INB1 → INB2
C7c、C5b、F5b-2（在任何新子系统之前）
CAP1–CAP3、Q1、STY、INB3–INB9
SBX ──→ measure on a Mac ──→ "ask only when risky" back ──→ measure cards (= the classifier's baseline)
SBX ──→ S2a-3 (rebase, max review + Astra for blocked parts, no "complete the list") ──→ HR
SBX + S3 ──→ S5a ──→ ACM
S64-0 (#438) ──→ S64-0b
HR + S64-0b + pass lines written by the user ──→ CLS (gates a/b/c/d/h/g) ──→ S5b
SBX ──→ CAP 里跑陌生代码的部分 ──→ SUB
SBX ──→ L6
L7：随时可做，跑分不退步才合
```

## 5. 分道

| 道 | 卡 |
|---|---|
| ⓪Plan | M64；本页、STATUS、各卡；R64 门槛判定 |
| ②Main | S5a、S5b、INB（含 MEM1）、review of SBX、SUB、STY、ACM、C7c、C5b、K6、K10、L6、L7、FS1、LANG1、S4b/S5/S6；合并队列和迁移号；S64-0 的审查（带 effort=max 独立审查员） |
| 新开一个会话（用户 10-28 定，为了并行） | CAP |
| ③Hands | **S64-0（effort=max 写）**；S64-0b；**SBX (from 2026-10-28)**；HR；CLS；PRJ0；S2a-3（看 #432）；F5b-2；Hands 文件的审查 |
| ①iOS | Q1 的 iPhone 端；Bridge 帧的变更清单（和 ②Main 一起） |
| Codex（外部工具，不是会话） | 安全面和大 PR 的独立审查（§8 安全审查路径）。 **Changed (user, 2026-10-28 evening):** Codex only for what a Claude review cannot cover; see §1.3. |

CAP 有 17 个 PR，单开一个会话（像 v0.1.63 的 ⑤C6、⑥C7），本 PR 合并后由 ⓪Plan 开。

## 6. 迁移号

main 上最新是 0070。这一版预计要的（开工时向 ②Main 申请、在这里登记）。**每个删表的迁移单独一个 PR，排在用到它的代码删掉之后**：代码能回退，表回退不了（②Main）。

| 卡 | 要的迁移 | Number |
|---|---|---|
| Q1 + SUB | `conversation_contexts` 加存下来的 `kind`（今天 `conversations.result` 里的 `kind` 是每次读时算出来的）、父对话 id、标题（①iOS 建议这一版先不改名）；一次迁移，两张卡共用，Q1 先申请，下一个可用号是 0071。**不是每段对话都有 `conversation_contexts` 这一行**：读的地方一律把没有这一行当作 `chat` | 0071 (Q1) |
| C7c | 旧专家数据转换，删专家表、记忆 v1 旧表、`router_decisions` | 0073 (C7c-2; must use `DROP TABLE IF EXISTS`: on a fresh database the table is already absent) |
| CAP1 | 删 `discovery_candidates`、`capability_finds`（`models.py:401`） | 0074 (CAP1b), 0075 (CAP1c) |
| CAP2 | 删候选表 `skill_candidates`（要先改 `seeder.py:85-95` 和 `run_redact` 里对它的依赖） | — |
| CAP7 | 重建 `capability_sources`：它有 `CHECK (kind IN ('mcp','skill'))`（`models.py:364`，0064 建的），插件要加一种 | — |
| CAP3 / SUB | 专业工作方法并进技能的话，`professional_methods`、`professional_method_versions` 两张表也删，或者写 `DELETE-BY` | — |
| INB4 | 「做完未看」的已读标记（新表，名字以 INB 卡为准） | — |
| INB2、INB6 | 记忆提案挪到「待整理」（INB2 可能要一个迁移）；进展页缺的运行数据（INB6，如果要加列） | 0072 (INB2) |
| SUB6 | 删 `task_workers` 表；迁移 0052 今天 import 了 `TaskWorker`，删类之前要让 0052 在新装上照样能跑 | — |
| S2a 跟进 | 清理旧的 `legacy_rule` 权限行 | — |

Numbers assigned so far (②Main, 2026-10-28): 0071 Q1, 0072 INB2, 0073 C7c-2, 0074 CAP1b, 0075 CAP1c, 0076 PRJ0's table drop (`project_habits` / `ProjectLevel.habit`, ③Hands). The next free number is 0077; a card that needs one asks ②Main and logs it here.

**Numbers assigned (②Main, 2026-10-29).** One migration per PR. Numbers are unique and never reused; they may land out of order (`apply_pending` is set-based), but a drop PR lands after the code that used the table is gone. Ask ②Main before taking a number.

| Number | Card | What | Where |
|---|---|---|---|
| 0071 | Q1 + SUB | The shared `kind` / parent / title columns on `conversation_contexts` | Reserved; Q1a opens it |
| 0072 | INB2 | `runs.read_outside` | #475 |
| 0073 | C7c-2 | Drop `router_decisions` | #450 |
| 0074 | CAP1b | Drop `discovery_candidates` | Merged (#457) |
| 0075 | CAP1c | Drop `capability_finds` | #473 |
| 0076 | PRJ0 | Its table drop, after #459 | ③Hands |
| 0077 | CAP2b | Drop `skill_candidates` | ⑤CAP |

The next free number is 0078.

## 7. 门槛（R64，草稿）

- 跑分：按 M64 卡，DeepSeek 上不退步（通过、答对不降，「等你」不增，没有新的报错类型）；对 Hermes 同题三次全过不少于它；代码审查题和拆分派汇总题出数。
- 安全：每个碰安全面的 PR 都有 effort=max 的审查 + Codex 的审查（结论写明模型），安全相关的结论给云端审计看过。 **Changed (user, 2026-10-28 evening):** every PR on the security surface has an OK from an independent Claude review at effort=max by another session; Codex Astra only for parts that review could not cover (§1.3).
- 用户验收：回复风格要用户读一批真实回复（中英文）；收件箱改完后用户一天的使用感受。
- 删除期限：`DELETE-BY: v0.1.64` 的都删掉了，或者用户逐条同意顺延。

具体数字和清单在 R64 卡里定，用户批准本计划后 ⓪Plan 再写。
