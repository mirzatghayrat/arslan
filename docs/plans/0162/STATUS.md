# v0.1.63 状态（一页纸）

⓪Plan 维护，每次合并后更新。卡的详情看 [README](README.md) §2 的状态列。

**更新于：** 2026-10-28 北京时间上午（Codex 已只读接上 GitHub）

## v0.1.63 已发布

- 2026-10-27 14:26Z 由你点 Publish，是 Latest。tag `v0.1.63` 在 `9bbb6ad6`（#425 之后的 main）。
- Release run 40505601007：核源码、编译、建 draft 三步都绿。这次在新镜像 `macos-26-arm64 20261021.0445.8` 上编成：第三候选上次就挂在这个镜像的这一步，这次过了。#418 的 rustc 兜底不打日志，看不出走了哪条路；日志里 rustup 是系统包管理器装的，正是 #418 说的那种情况。公证通过；新装检查 92 项全过；`latest.json` 是 0.1.63。
- 放行的依据和没达到的项：[R63 判定](R63-verdict.md)（#424）。
- 下一版：v0.1.64，候选和已定的排序见 [README](README.md) §8。

## Codex 待审

**怎么跑（你 10-28 定的方式）：** ChatGPT 桌面版 → Code Review → 选下表里「能审」的 PR → **Review with Codex**，把下面那段提示整段粘进去，再把 `<PR 号>` 和 `<额外要看的>` 换成表里那一行。只在聊天里审：**不点 Submit review，不开自动审查，不在 Summary 或 Changes 页里写评论**（那里的评论会马上发到 GitHub）。你 10-28 装 GitHub 连接器时只勾了一个无关的公开仓库，没勾 arslan，所以 Codex 对 arslan 只有只读权限；以后也别勾 arslan（README §8）。审完把 Codex 的回复原样（带第一行的模型）贴成那个 PR 的一条评论；各会话逐条回应，回应完才合。

**Which model (user, 2026-10-28):** PRs that touch the security surface (mark fixes, sandbox, classifier, command policy, the five modes, confirm cards, Bridge frames) use **GPT-6 Astra** at the highest reasoning level. PRs over about 400 product lines that do not touch the security surface use **GPT-6.1 Terra** (or Sol) at Extra High. **After clicking Review with Codex, paste the whole prompt below as well;** the auto-generated prompt alone does not count as a review against this list. Codex cannot see its own version, so you fill in the model line from the model drop-down. Your Code Review "Review instructions" (set 2026-10-28, apply to every repository) already say: read-only, no comments, no pushes, no merges, no file changes, no commands, reply in English, first line is the model and reasoning level.

| PR | 是什么 | 能审了吗 | `<额外要看的>` |
|---|---|---|---|
| [#438](https://github.com/mirzatghayrat/arslan/pull/438)（S64-0） | 「读过外部内容」标记的四个漏洞，加 F1 | **Done.** Merged by you on 2026-10-28 (squash `3ee16b6c`); main CI run 40648762514 success. Codex, pasted by you: GPT-6.1 Terra, Extra High, with this prompt: no findings, "merge within the stated scope"; GPT-6 Astra, Extra High, with Code Review's own prompt and your instructions only: no actionable defects. Nothing to answer. What Terra listed as not reviewed (attachments and OCR, commands reading files, job results) is S64-0b and the known limit. | — |
| [#443](https://github.com/mirzatghayrat/arslan/pull/443) (S64-0b) | Two more mark leaks: attachment and OCR text inlined without the mark; background job results posted as Arslan's own words | **Ready once CI is green** (③Hands adds the run id on the PR); alongside ②Main's max review. GPT-6 Astra, highest level | `server/orchestrator/arslan.py` (`_handle_answer_body`'s `_dispatch` wrapped in `untrusted.carried(...)`, including the OCR retry); `server/orchestrator/tool_loop.py` (`run_native`, the two lines after `track_turn()`); `server/orchestrator/untrusted.py` (`carried()` yields the run's mark, `end_turn`, `JOB_RESULT_FROM_OUTSIDE`, `job_result()`, `history_from_outside()`); `server/services/background_jobs.py` (`_run` writes the mark back to `job.outside_seen`; `_report` stores the framed copy in `content` and the original in `display_content`); `tests/server/test_s64_0b_attachments_and_job_results.py`. Also every reader of `display_content or content`: `server/ws/arslan.py:80`, `server/api/phone.py:127`, `server/services/conversation_search.py:75`, `server/services/task_service.py:1144`; `memory.assemble_working_context` (history uses `content`; `clip_context` keeps the frame's header); temporary conversations are deliberately unchanged. Judge whether "a framed job result in history marks the turn" is right. |
| [#375](https://github.com/mirzatghayrat/arslan/pull/375) | S2a-3 a+c：命令按完整的 shell 语法读懂才放行 | 还不能：等默认拒绝沙箱（SBX）合并、③Hands rebase 之后审新头，不审旧头 | `docs/plans/0162/S2a-command-three-layers.md` 的 S2a-3 节；`docs/incidents/2026-10-24-dev-secret-read.md` |
| [#376](https://github.com/mirzatghayrat/arslan/pull/376) | S2a-3 c 的后半：经别的命令间接跑的，算没读懂 | 同 #375：等 SBX 合并、rebase 之后 | `docs/plans/0162/S2a-command-three-layers.md` 的 S2a-3 节；`docs/incidents/2026-10-24-dev-secret-read.md` |
| [#378](https://github.com/mirzatghayrat/arslan/pull/378) | S2a-3 b：请 macOS 在沙箱外办事的程序分两档 | 同 #375：等 SBX 合并、rebase 之后 | `docs/plans/0162/S2a-command-three-layers.md` 的 S2a-3 节；`docs/incidents/2026-10-24-dev-secret-read.md` |
| [#396](https://github.com/mirzatghayrat/arslan/pull/396) | S2a-3 d：拿真 shell 对照命令判定 | 同 #375：等 SBX 合并、由写它的会话 rebase 之后 | `docs/plans/0162/S2a-command-three-layers.md` 的 S2a-3 节；`docs/incidents/2026-10-24-dev-secret-read.md`。**不要运行这个 PR 的真 shell 对照测试，只读代码；它只在一次性 CI 虚拟机里跑。** |

只改文档的 PR（如 #432、#434）不送 Codex；#432 的安全模型由云端审计审。

**提示（整段粘贴）：**

```
你是 Arslan（公开仓库 mirzatghayrat/arslan）的外部安全审查员。只审 PR #<PR 号>。只读：不提交 GitHub review，不评论，不推送，不开 PR，不改任何文件。

先读：
1. PR 描述（里面有「完成证据四项」：做了什么验证、覆盖到哪、没覆盖到哪、还剩什么风险）和 diff 全文。
2. docs/sessions.md 的 §5、§8、§9（PR 大小、完成证据、留着的旧路径要写删除条件）。
3. SECURITY.md：Arslan 对用户承诺了哪些保护。
4. 这个 PR 额外要看的：<额外要看的>

要找的：
- 外部内容（网页、文件、MCP 工具、子任务或后台任务交回的文字）能不能不经用户确认就让 Arslan 做事：联网、写记忆或学到的做法、改文件、跑命令。
- 沙箱、确认卡、命令判定、令牌、密钥有没有绕过的路；出错、超时、限流时是放行还是拒绝（应该是拒绝或出卡）。
- 测试有没有测后果，而不只是看代码写了；把修复删掉，测试会不会变红。
- PR 描述说修了、代码里其实没修的；没写删除条件的旧路径或兜底。

不要：运行任何命令或测试，只读代码（你在用户的个人电脑上，不在隔离环境里）；不访问家目录、~/.arslan、Arslan 的数据文件夹或任何密钥；攻击写法只写到能证明问题为止。

回复格式：
Write the whole reply in English (it is pasted onto GitHub), with these labels: "First line: Model: …", "Severity (high / medium / low)", "Not reviewed", "Verdict: merge / merge after fixes / do not merge".
第一行：模型：<Codex 版本、模型名、推理档位>（中途换了模型也写明，标出哪部分是换了之后审的）。
然后每条发现一段：严重度（高 / 中 / 低）；文件:行；问题是什么；会出什么事（什么输入 → 什么错误结果）；建议怎么修。
然后「没看的部分」：哪些文件或路径没细看。
最后一句结论：可以合 / 改完再合 / 不能合。
```

## 已合并（#367 之后，新的在前）

| PR | 内容 | 合并提交 |
|---|---|---|
| #425、#426 | 文档：v0.1.64 候选「快问」替换 iPhone 上的 Remote，以及你定的五条（用默认模型；记录一直保留、能逐条删；Mac 快捷键小窗放 v0.1.65 候选；不进 Mac 侧栏；`conversation_search` 能搜到） | `9bbb6ad6`、`6f29cec9` |
| #424 | **R63 判定**（第 6 步）：跑分、M2、M3 逐条对门槛；两处到期的删除你同意顺延到 v0.1.64 | `0f93e550` |
| #423 | 文档：M3 第 3、5 条按「已说明的缺口」发出（你 10-27 定） | `78b2400b` |
| #421、#422 | M2 报告只数用量页数的那几类运行（聊天回合记作 `host`）；跟进的注释和卡 | `0abf825d`、`f719fffc` |
| #418 | `build_dmg.sh` 在 `~/.cargo/bin` 没有 rustc 时用 PATH 上的（第三候选在新镜像上编挂的根因） | `1338e3b6` |
| #416、#414 | 撤销不再把 Python 环境放进检查点（不管它叫什么名字，M3 第 8 条）；R63 在打 tag 前修撤销（你 10-26 定） | `73c8190e`、`195220f8` |
| #410、#411 | **R63 A / B：**「只问有风险的」改回时出确认框（写明已知问题）、撤销的指引、一次性的说明；发布说明写明两个缺口、默认设置的代价和撤销的已知问题 | `acf4427c`、`04354865` |
| #409 | 10-24 事故：一个审查探针读到了开发用的密钥（记录、测试套件守卫、`scripts/dev/probe.sh`） | `9e9f589c` |
| #404、#403、#405、#407、#408 | 0.1.63 版本号、发布说明和它们的测试、能力清单；冻结清单；最后一轮 M1 的安排、门槛报告、发版决定（你 10-24 定） | `adf35143`、`6eb8a6fa`、`1690a6ec`、`ac31f2af`、`500ef59a` |
| #398、#399 | **v0.1.63 的兜底：**默认「每条命令都先问」，所有人切一次（迁移 0070）；定时任务一条命令都不跑（到 S2a-3 为止） | `6169ceb5`、`e497ef7c` |
| #394、#402 | **C11b：**访问令牌不进服务端日志；非 ASCII 令牌回 401；不认 `*` 允许清单；打包版没有 API 浏览页；种子路由要令牌；跟进 | `adaac481`、`409913d7` |
| #339 | SECURITY.md：写桌面版而不是 prod 模式；默认每条命令都先问 | `3b74e63e` |
| #393、#401 | **K9b：**回合进行中发的消息，在下一个工具边界被读到；关连接时最多等 30 秒 | `d3ac7b28`、`f3b6619c` |
| #384、#389、#390、#391、#392 | 产品代码不再用 `asyncio.wait_for`，改用不会丢停止的 `arslan.aio.within`；被停下的 Mac 自动化命令会被结束 | 见各 PR |
| #385、#386、#387、#388 | **C7：**删掉建专家那一串、`arslan/spawn`、`evolution.py` 和 jinja2 依赖、人设浏览接口 | 见各 PR |
| #302、#319、#300 | D9：附件被截断时说出来，上限 40,000 字；Bridge 测试：定时卡的新键不改变手机收到的内容；docs-site：聊天回复不再停在同一个 App 五步 | `72081e7c`、`5e021a8f`、`8f7d21dd` |
| #395、#397、#400、#412、#413、#415、#417、#419、#420 | 文档：云端 Claude 接 S2a-3 / C11b；S2a-3 顺延；R63 记录；§8 补的候选和跟进；iPhone 1.0 要的 Mac 字段和 ①iOS 的方案 | 见各 PR |
| #359 | **C9b：**删掉 MCP 推荐目录和 `suggest_connector` 工具 | `79197ef5` |
| #358、#373、#382 | **C8-2、C8-4：**删掉研究复核（存报告后的复核）和它的所有出口；删掉回合结束提炼和整条提炼链；跟进删 `supports_bounded_critique` | `a35a972c`、`7d56d7e9`、`f0121191` |
| #368 | **K9a：**同一条回复里连着的只读调用同时跑（三处记步骤的地方成对发，不改 Bridge 协议） | `4b8e1556` |
| #377、#379 | 流的空闲上限和单次调用上限改用 `asyncio.timeout`，不再丢取消；桌面版不认继承来的配置（C11 跟进，#364 之后） | `cb1e1e07`、`383de3f1` |
| #380、#383、#381、#374 | 测试有自己的 HOME，写了你的 `~/Arslan` 会报出来（#383 起不再让整轮失败）；文档：C11b 已定、S2a-3 审查和 PR3 的去向；10-22 合并后的状态 | `1dfb393c`、`06b7847b`、`75645348`、`8acb06d3` |

## 已合并（#367 及以前，新的在前）

| PR | 内容 | 合并提交 |
|---|---|---|
| #367 | **S7：**每张「装能力」卡的回答都记进权限账本（同意 / 拒绝 / 没人答各一行；后台任务不写；来源链接只留协议、主机、路径；记账失败不改变决定）。Opus 5.5 effort=max 独立审 | `2a1d252f` |
| #352 | **S4a：**出沙箱和远程的卡都走同一个 `decide()`；「本对话可以出沙箱」的授权存下来（重启不丢、后台任务认、定时任务永远不认），只有发起询问的窗口能给，设置 › 高级能收回；收回后在等卡的命令改在沙箱里跑。Opus 5.5 effort=max 独立审两轮 | `8866f1e3` |
| #364、#371、#369 | C11 跟进（云端审计）：打包版忽略继承的 `ARSLAN_ALLOWED_ORIGINS` / `ARSLAN_ALLOWED_HOSTS`；**发版检查的 WebSocket 探针带上同源 Origin**（#338 以后不带会 403，发版那一步会挂），三次握手各证一道防护；R63 清单 | `f60708c7`、`f617b208`、`bbbf023d` |
| #338、#343 | **C11：**桌面版服务端加固（没有 prod 模式；总要访问令牌；拒绝别的来源和没有 Origin 的 WebSocket；关沙箱逃生阀）；令牌只交给自己的页面，主窗口不能导航离开 | `be03c246`、`dc63e5dc` |
| #350、#336、#326 | **K8：**DeepSeek（OpenAI 兼容）、Claude、Gemini 都边写边显示；守卫改成事后追加更正；流到一半出错不重发。K8a 的 DeepSeek 门槛过：通过 18/27、答对 20/27、「等你」2（基线 18、19、4） | `bcba7000`、`28e76f42`、`0807d692` |
| #329、#318 | **S3：**检查点（一轮第一次改文件前克隆工作文件夹）和「撤销这一轮」（连对话一起，迁移 0069） | `6e8f7202`、`256ada17` |
| #325、#328 | **S1b：**定时任务只在 `~/Arslan` 里写；每次拒绝都进收件箱（含 Hands 的）；定时卡显示任务内容 | `a419f895`、`7d13c907` |
| #320、#322 | **S2b：**Arslan 用自己的 `shell_text` 读命令；删掉整份引入的 Hermes | `543b5dad`、`fa806885` |
| #365、#363、#355 | **C8：**删掉每 15 分钟的整理层循环（用量表的清理原样搬到单独模块保留）、对话菜单里的「提炼」；研究复核要删之前先把「存了报告把读过的网页换成收据」原样搬出来（逐字一致的测试） | `24aa4a91`、`8c68410a`、`a19833d2` |
| #331、#335、#337、#341、#342、#345、#346、#351、#354、#361、#366 | **C7 第一、二步和 C2b：**技能锻造不再要分身；删掉进化（REST、诊断、自动和手动路径、语料和回放）、配方、dispatcher 和只有它用的代码、promise_guard 零工具那一档、`evolution.*` 翻译；新加护栏测试：后台任务的工具永远拿不到跑命令和写文件 | 见各 PR |
| #347 | A5：App 里带上 LICENSE 和第三方许可说明，发版检查核对逐字节一致 | `2e318e38` |
| #330、#333、#334、#372、#370 | **C6 和 CI：**同一提交只跑一次；发版分支保留 CI；pytest 并行；测试库按 App 的设置建（K8c 第一次红的根因）；停下的任务被再取消时照样写检查点 | 见各 PR |
| #323、#340、#344、#349、#353、#356、#360 | bench 记首字时间；几条会抖的测试修好；三条验收约定改指新测试名并加护栏 | 见各 PR |
| #321、#324、#327、#332、#348、#357、#362 | 文档：K7/S2a-2/S1a 后的状态；对外文档等界面版；SECURITY 不再说有凭据代理；分道表加 ⑤C6、⑥C7；R63 清单；C8 卡的偏离；**你定的 S2a-3 做法和 v0.1.64 排序** | 见各 PR |
| #317 | S1a：MCP 按服务器的标注审批（只读的直接跑、会删东西的每次问、其余默认「这个对话都行」）；没人能问的运行（定时任务）不采信任何「总是允许」或对话授权；定时任务不开后台任务；要出卡的 MCP 调用参数超过 4,000 字就拒，不再悄悄截掉。⓪Plan 在 Opus 5.5 上安全审查（另派 effort=max 独立审查），改后复审过 | `97082c99` |
| #308 | S2a-2：命令三层，Arslan 自己的规则（直接拒的 / 每次都问的 / 沙箱里不问就跑的）；JXA 在出卡前就拒；写 rc、ssh、凭据文件的命令每次都问。②Main 在 Opus 5.5 上安全审查（一个 🔴 修后复审过）；⓪Plan 的 M1：命令多的五题 15/15、「等你」0（K5 14/15、1） | `36b8506c` |
| #315 | K7：工具按需取。默认配置加 3 个 MCP 服务器，每次请求的工具从 56,094 字降到 11,966 字。DeepSeek 门槛过：**通过 23/27、答对 23/27、「等你」0**（基线 18、19、4；K5 20、20、1），到现在最好的一轮 | `046d184b` |
| #316 | 文档：本页、README 状态列、§8 候选 | `c15b470d` |
| #313 | C3b：30 天里一次没用过的 7 个工具不再每轮都发；一台机器都没登记时不提供 `ssh_run`（⓪Plan 替你按卡定的，可以改） | `6f962f98` |
| #306 | D5：搜索先用这个对话这一轮模型自带的搜索；Tavily / SearXNG 可设成「只用它」或「备选」；被拦就说被拦。Claude 上 T3 2/3 → 3/3，搜索全走 Anthropic、没有被拦 | `d9cec85f` |
| #309、#307、#305 | C2a-2（拆三个）：记忆 v1 那条走不到的路全部删掉，产品代码里不再调用 `is_active` | `f484f1e1`、`e6320f54`、`fa1d5329` |
| #312 | C1c-2：网页删掉 14 种服务端早就不发的专家帧和 21 组没人用的翻译 | `f9c686d5` |
| #304 | C3a：删掉模型拿到却用不了的工具（`render_deck` 等） | `0a1c1092` |
| #310、#311、#303 | 会抖的计时测试修好；bench 的 A/B 设置项；文档 | `53904927`、`70bec9fa`、`b9a5bbb6` |
| #301 | S1-0：`schedule_task` 的说明不再说「定时任务是只读的」（不是真的）。⓪Plan 在 Opus 5.5 上审 | `eaaf84f4` |
| #294 | K5：工作方法要把事做完；工具说明和工具对上（14 个参数表、`edit_file` 改名、网页规则搬进工具说明）；多步骤任务最后给你四行收尾。DeepSeek 门槛过：通过 20/27、答对 20/27、「等你」1（基线 18、19、4），没有新的报错类型，花 $2.56。那 1 次「等你」是 JXA 脚本在沙箱里报 -600，交给 S2a-2 | `528a05a1` |
| #299 | 文档：U14（云端审计的四条落卡：S1 加四项和 S1-0、新卡 C11、v0.1.64 安全底线）；D9 卡 | `fb599dca` |
| #290 | H3：聊天里的 Hands 不再有自己的 5 次和「一轮一个 App」上限，Stop 对聊天回合也停住；定时任务照旧保留上限。你在 Mac 前的冒烟 32/33（只有 G8′） | `565338ab` |
| #249 | F5b-1：拆掉 Cua Driver 引擎。你在 Mac 前跑的冒烟 29/30，只有已知的截图延迟 G8′ 没过 | `4f50f9f2` |
| #288 | 另外三处同类竞态（工作区的 tab、模型设置的选中项），晚到的更新不再撤回你刚做的选择 | `da49a794` |
| #296、#295 | C9a：自带技能只剩 `designed-html-report` 和带出处说明的 `skill-creator`；D8：标题只用你的第一句话、发给这段对话自己的模型 | `d41d6793`、`863e28f6` |
| #293 | D7：开机时的退役只删 Arslan 自带的技能行，你导入的同名技能不再被删（②Main 审时又补了一处：锻造出来的技能用 `promoted_at` 保护） | `2f149dbd` |
| #291 | C10：删掉 Docker 这条部署路径（3 个文件和 7 份文档里的段落）；`web/`、静态文件服务、prod 模式都没动 | `c741d3df` |
| #285 | 权限卡队列的竞态：翻到下一张卡后，一个晚到的更新会把第一张卡放回来（翻页被撤回），「允许」答的是屏幕上显示的那张。没有被藏起来的卡被批准。②Main 找到根子、修了，⓪Plan 审过 | `c135518f` |
| #287 | bench：每次跑的上限从 15 分钟调到 50 分钟，高过 Arslan 自己的 45 分钟硬上限（K4b 的 T2 第 3 次就是被旧上限掐断的）；有测试钉住 | `54b95952` |
| #286、#289、#292 | 文档：K4b 和 U13 之后的状态；K5 卡写进计划的发现和 10 个决定（工作文件夹只给数量不给名字；参数表不用 `pattern`、顶层 `anyOf`、类型数组） | `b4348a5f`、`5a5c3be3`、`dcd458f5` |
| #284 | U13：你定的清理清单落成 6 张卡（C7 专家那一大块、C8 整理层与研究复核、C9 自带技能与 MCP 推荐、C10 Docker、D7 退役删掉导入技能的 bug、D8 标题），K5 卡补引用要求和 `promise_guard` | `5c8646e9` |
| #282 | K4b：后台就是同样的工作换个地方做，不再逼模型转后台、只回一句话；去掉每轮 25 次网页读取的上限；只留一个 token 估算器；聊天回合满 10 分钟给模型一条提示、给你一行说明；上下文环能点开看各部分。DeepSeek 门槛过：通过 21/27、答对 21/27、**「等你」0**（基线 18、19、4），没有报错类型，花 $2.14 | `93921bf5`（你点的合并） |
| #281 | 规矩「换掉就删掉」（你 10-21 批，④参谋提、⓪Plan 改）：写进 `docs/sessions.md` §11、总计划 U12；R63 加删除期限清单和产品代码净行数 | `094e37fe` |
| #277 | K4a：聊天和后台任务用同一个停止策略；按缓存档位算美元；每个任务默认 $2 上限（到 $1.33 开始收尾）；回合里的历史一次裁到上限的一半，缓存每一大段才断一次。DeepSeek 门槛过：通过 20/27、答对 21/27、「等你」3（基线 18、19、4），没有报错类型 | `5a97ff7f` |
| #269、#273、#278、#279、#280 | 文档：H4 卡（标成已合并、实际量级、剩下的三种情况）；E26（Claude 清理 100k / 40k）；本页和 README 状态列；K4a 之后的状态和两条 v0.1.64 候选；K4 卡记下 K4b 的 10 个决定、改正长回合的理由，§8 补 5 条 | `96bf41ea`、`9ebe2a37`、`894e0ea7`、`56a8bb40`、`13a2a125` |
| #271 | H4：同一个 App 的各种写法（`.app`、路径、不加空格、`¬`）都认得；System Events 进程名、访达按 id 打开 never-list 里的 App 一律拒 | `a50bcdab` |
| #276 | Hands 判断：保存、导出、加参会人每次给你看整段脚本 | `893fdd55` |
| #272 | S2a-1b：iPhone 发起的回合里，只能在 Mac 上批的卡不再发到手机 | `0d17ee13` |
| #265 | S2a-1：命令沙箱收紧（沙箱里不发 Apple Events；读过外部内容后命令断网，沙箱内外都是；Arslan 自己的数据在沙箱外也读写不了，不包沙箱跑的那一条除外，它靠四个 App 的允许清单）；批准过的 AppleScript 只对提醒事项、日历、备忘录、通讯录不包沙箱跑，批准过的 `shortcuts run` 也不包沙箱跑（卡上写明以你的身份运行） | `0183ff88` |
| #275 | K3b：Claude 上不改已发出的历史；清理改 100k / 40k | `7e8c57aa` |
| #274 | D6：一步记不进任务记录时只拒这一步，后台任务不再整个停掉 | `ceb4d976` |
| #267 | Hands 判断：`read`、`open location`、`URL`、剪贴板算越出 App | `5ddc8e4a` |
| #259 | K3：提示词布局和缓存 | `f3bda58d` |
| #257、#258 | C1c-1：删专家时代的残留 | `2993ff93`、`6e17afc3` |
| 文档 | D5 搜索卡 #261、W1 搜索四层 #264、D6 卡 #270、U11 三次收窄 #260 / #263 / #268、§8 候选 #266、更正 #262 | — |

已关掉（不合并）：#185、#207，对外文档同步到 v0.1.61、v0.1.62 的两个 PR。你定对外文档等界面版之后一次更新（U13 第 6 条；10-22 从 v0.1.65 挪到界面版之后，截图只拍一次），关的时候留了说明，以后可以重开。


## 在路上

- **S64-0 = [#438](https://github.com/mirzatghayrat/arslan/pull/438): merged 2026-10-28** (`3ee16b6c`, main CI 40648762514 success; ②Main xhigh + an independent max reviewer, two Codex reviews with no findings). Next: S64-0b (③Hands), INB1 → INB2 (②Main), M64 baseline running (⓪Plan, DeepSeek).
- **M64（⓪Plan）：** 跑分加代码审查题、拆分派汇总题和同题统计，你 10-28 说现在就能开。
- 没有 v0.1.63 的卡了。顺延到 v0.1.64 的见 README §8 开头「冻结时顺延的」，还有 R63 判定里的两处删除（`__version__`、专家时代的 REST 接口）。
- **S2a-3（③Hands）：** #375、#376、#378、#396 留着，v0.1.64 和默认拒绝沙箱一起审（你 10-24 定）。#298 也开着（和 main 冲突）：SECURITY.md 那半已被 #339 顶替，剩下的 #298b 跟 S2a-3 一起写（README §8）。

## 等你拍板的

- **#434（v0.1.64 计划）：** 已按你 10-28 早上的决定改好，等你点合并。合并后能同时开的一起开（先合 C7c、C5b、F5b-2，再开 CAP1–CAP3、Q1、STY、INB1 起）。
- **#432（安全模型）：** 等云端审计（5.5，A–F 题）回来再定；你倾向推翻 D8，条件是复核里的两处更正都做到。S64-0 要不要并进另外三处标记漏洞，等它的 E 题。
- **「推送只推要你做的」（收件箱第 5 条）：** 会改变所有手机（含旧版）收到的推送，单独问你。Bridge 帧的其余几条已按 ①iOS 的建议定了（10-28）。
- **S2a-3 PR1 #375 约 1,060 行，超过 `docs/sessions.md` §5 的约 800 行，要不要拆：** 938 行是一份完整的 shell 语法，拆开会在 main 上留下半个读取器。我倾向不拆，但这是 §5 的规矩，由你定。S2a-3 只是顺延，这个问题没定；v0.1.64 送外部审查前要答。
- **R63 判定里没有记录的两半**（M3 第 7 条 Mac 那半，第 12 条截屏那半）：v0.1.64 冒烟时补测，还是就此放下。
- **K8c 的 Gemini M1：** 要 Gemini 代理和额度（只有你能放 key）。
- **Security model "hard rules + sandbox + classifier" with permission modes — decided by the user on 2026-10-28** (README §8): sandbox and classifier both "must" in v0.1.64 (SBX first, classifier after); all five modes (S5a after SBX, S5b after the classifier); D8 reversed with the audit's conditions, any one unmet means no classifier; S64-0b for two more mark leaks; if the classifier's review is blocked, v0.1.64 waits. Pass lines: you chose option 2 on 2026-10-28 (README §8).

## 已定、不用再问

- **跑分在 v0.1.64 加「代码审查」题**（你 10-27 定）：先出 3 题，Arslan 和 Claude Code 都跑在 DeepSeek 上并排比（R63 里 Claude Code 的数字是在 Claude 上跑的，不能直接比）；Codex 用你的 Plus 加进来当参考线（它用自己的模型）。
- **Codex 进审查流程**（你 10-27 定）：做 v0.1.64 安全审查的外部审查工具，结论再给云端审计看一遍；日常只审碰安全面的 PR 和大 PR（⓪Plan 另定：按 U2 整份删除、不碰安全面的不审，比你选的范围窄一点，你可以改），跟「他会话审」对照，不顶替；只读，不推送，不合并，只看公开仓库，不碰你的家目录和数据。**你 10-28 在 ChatGPT 桌面版的 Code Review 里连 GitHub**，只用「Review with Codex」（在聊天里审，不发到 GitHub），不开自动审查；连接器只勾了一个无关的公开仓库、没勾 arslan，Codex 对 arslan 只读，试过能打开 PR（README §8）。待审的 PR 和提示见上面「Codex 待审」；它的结论由你原样贴到 PR 上。
- **v0.1.64「对 Hermes」门槛**（你 10-27 定）：同样的题，三次全过的题数不少于 Hermes。v0.1.63 只比同题时少 1 题。
- **回复风格、项目里的「总指挥 + 子会话」**（你 10-27 定，④参谋 转）：风格放 v0.1.64，跟 D1 一起做，四条只管任务汇报这类回复，闲聊保持温度；子会话分两步，v0.1.64 先做底子，v0.1.65 做项目页。详情见 README §8。
- **能力页和插件的八条**（你 10-28 逐条同意，④参谋 转）：并进 v0.1.64「按需加能力」那张卡，详情见 README §8。带钩子的插件先不装；钩子支持我排在 v0.1.65 之后、和预装推荐那一轮一起做，你可以改。#62 那个只筛已装能力的过滤框留着（你 10-28 定）。
- **收件箱的八条和「进展」页**（你 10-28 逐条同意，④参谋 转）：详情见 README §8。版本是我排的，你可以改：v0.1.64 先做学到的做法和记忆不再排队（安全 PR），再做去掉列表、状态点、只推要你做的、确认卡只在对话里、验收单（只在你不在场的运行）、四行简报；进展页的时间线和地图放界面版。

## 跑分花费（停在 10-22；最后一轮 M1 的花费见 [门槛报告](R63-gate-report.md)（#407））

| 计量 | 本次重启后（上限） |
|---|---|
| DeepSeek | $1.85（$20） |
| Claude | $4.65（$30，每次 $1） |

- 10-22 中午你调高上限、重启了两个代理；重启前 DeepSeek 累计 $15.93。
