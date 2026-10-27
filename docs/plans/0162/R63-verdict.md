# R63 第 6 步：v0.1.63 门槛判定（2026-10-27）

R63 第 6 步：每条门槛写「达到 / 未达到」，附证据；附删除期限清单（`docs/sessions.md` §11 第 2 条）。⓪Plan 写。打 tag 由用户点。

## 要打 tag 的提交

- main `78b2400b`，push CI `40476160824` success。
- 和用户试用的第三候选（`8fd7f343`，Release run `40223018402`）比，`server/`、`web/`、`desktop/`、`arslan/`、`packaging/` 里只差 #421：`server/api/usage.py` 改为引用新文件 `server/run_kinds.py` 里的同一组运行种类，行为不变。其余是文档和只读脚本（#419–#423）。
- 第三候选的 Release run 里 verified-source、build（签名、公证、`fresh_install_check`）都 success。打 tag 时 Release 工作流会在 tag 的提交上重新出包。

## §5.1 跑分（M1）

见 [R63-gate-report.md](R63-gate-report.md)（#407）。

| 门槛 | 结果 | 判定 |
|---|---|---|
| 不退步（DeepSeek） | 9 题都不低于 M1B；通过 22/27 | 达到 |
| 不退步（Claude） | T11 从 3/3 掉到 0/3（报告第三节第 1 条） | 未达到；用户 10-24 定带着发（#408），已写进发布说明 |
| DeepSeek 上对 Hermes | 全套 Pass^3：Arslan 6 题、Hermes 6 题（同题比少 1 题） | 按门槛原文达到（持平） |
| Claude 上对 Claude Code | 差距 12 → 0（各 17/24） | 达到 |
| 新题 3/3 | T7 两个模型都 3/3；T8 DeepSeek 1/3、Claude 0/3；T11 Claude 0/3 | 未达到；同上带着发 |

## §5.2 本机数据（M2）

脚本：`scripts/usage_report.py`（#421 修好只数 `live` 的问题后），④参谋 在用户本机库上只读跑，`--since 2026-10-25`。试用天数按用户 10-24 的决定（1 天），不是 7 天。10-26 那一周 = 第三候选加 M3 操作。

| 指标 | 0.1.61 | 门槛 | 10-26 那周 | 判定 |
|---|---:|---:|---:|---|
| 任务停在「等你」 | 32% | ≤15% | 1/23 = 4% | 达到 |
| 其中「需要你核对」 | 30 / 222 | ≤5% | 1/23 = 4% | 达到 |
| 工具调用失败率 | 26% | ≤12% | 5/59 = 8%（上一周 46/631 = 7%） | 达到 |
| `run_command` 时限类失败 | 31–35 次 / 30 天 | 0 | 20 秒截断 0、F1 外层时限 0、命令自己的时限 0 | 达到 |
| MCP 引起的整轮失败 | 6 次 | 0 | ≈0 | 没有证据：见 M3 第 4 条的保留 |
| 回合后的额外调用 | 都在回合锁里 | U5：不在锁里，不排队 | 测试断言 + M3 第 11 条（有保留：回复收尾时插话那种情形没有可靠地打到） | 达到 |

读数时要知道：
- 只有一个用户、大约一天半，大多是 M3 里故意拒卡、故意让命令失败的操作。
- 0.1.61 的基线当时按哪些运行种类数的，没有记下；`worker` 运行不算在内。
- 上一周（10-19–10-25）大半在装第二候选之前，「等你」12/77 = 16%。其中「命令自己的时限」4 次、一次失败的命令跑了约 20 秒，和那条过期的「20 秒」经验记忆对得上（README §8，用户已删）。

## §5.3 体感验收（M3）

第二候选（`04354865`）上 ④参谋 代测；第 4、8 条在第三候选上复测；第 7、10b、12 条用户在 iPhone 上测（TestFlight build 21）。

| 条 | 判定 | 一句现象 |
|---|---|---|
| 1 | 通过 | `sleep 75` 跑完，没有「需要你核对」，没有 `timed out` |
| 2 | 通过（用户测） | 一次做完 |
| 2b | 本版不验 | 可选 |
| 3 | 不通过，用户 10-27 定带着发 | 第三轮「再加一个表格」把第二节的段落改写进表格（DeepSeek，测一次） |
| 4 | 通过，有保留 | 接着 116 个工具的服务器，Claude、DeepSeek 都正常回答；但 K7 之后普通对话不发它的工具说明，所以只证明到普通对话 |
| 5 | 不通过，用户 10-27 定带着发 | 两个模型都用终端整份改写，不用 `edit_file`；内容对 |
| 6 | 通过 | 被拒后改成移到废纸篓 |
| 7 | iPhone 通过；Mac 那半没有记录 | 手机上逐段出字 |
| 8 | 通过（第三候选） | 改过的文件放回后 sha256 一致；Python 环境没动 |
| 9 | 通过 | 两种写法都出卡，只有「仅这一次」 |
| 10a | 无法判定 | 没有 0.1.61 同一天的秒数；本版 9 秒 |
| 10b | 通过（用户测） | 从 iPhone 插话，下一步照做 |
| 11 | 通过，有保留 | 回复收尾时插话那种情形没有可靠地打到 |
| 12 | 通过（用户测；测的是送文件，截屏那半没有记录） | 文件到了手机和 Mac；每次两张卡；`write_file` 不展开 `~`，文件先放错了地方（README §8） |

## §5.4 工程门槛

- **CI：** 要打 tag 的提交 `78b2400b`，push CI `40476160824` success。
- **安全回归测试：**
  - R1（写入不跟随符号链接）：`tests/server/test_write_no_links.py::test_write_file_through_a_link_to_outside_is_refused`；
  - R2（终端 osascript 只给「这一次」）：`tests/server/test_osascript_once.py::test_the_windows_card_offers_only_this_time_despite_a_rule_and_a_grant`；
  - R6（定时任务只跑只读的 MCP 工具）：`tests/server/test_s1_mcp_approval.py::test_with_nobody_to_ask_only_read_only_runs_even_with_a_grant`；
  - R7（定时任务没有 `start_background_work`）：`tests/server/test_hands_h3_chat.py::test_a_scheduled_runs_refusals_never_send_it_to_background_work`；
  - 所有卡片都写账本：`tests/server/test_s7_capability_ledger.py::test_every_answer_writes_exactly_one_row_and_a_job_that_skips_the_card_writes_none`（S7 补上的最后一种卡）。
- **发布说明每一句对上测试：** `docs/releases/v0.1.63.md` 的「How this is tested」一节。

## 删除期限清单（`docs/sessions.md` §11 第 2 条）

在 `78b2400b` 上查：代码注释里固定写法的 `DELETE-BY:` 全是 v0.1.64（49 处）和 v0.1.65（1 处），没有写本版或更早的；再按自由写法和任务卡名查一遍（⓪Plan 派的只读审查，结果逐条核过）。写着本版删、还在、没有用户同意顺延的有两处：

| # | 还在的 | 哪张卡说本版删 | 现在有没有人用 |
|---|---|---|---|
| 1 | `arslan/__init__.py` 的 `__version__ = "0.1.0"` | C2d（#238）、C5b（#201），都是 v0.1.63。注释写「C2d deletes both」，C5b 卡写 C2d 合了就删；C5b 先合，删除落在两张卡中间 | 没有（`arslan/cli.py` 已删） |
| 2 | 专家时代的 REST 接口：`server/api/spawns.py` 的 `GET /spawns/{id}`、`PUT /spawns/{id}/config`、`DELETE /spawns/{id}`、`GET`/`DELETE /spawns/{id}/preferences`；`server/api/knowledge.py` 的 `GET`/`DELETE /spawns/{id}/knowledge`；`server/api/collections.py` 的 `PUT`/`DELETE /spawns/{id}/collections/{cid}` | C7 第二步（C7b，v0.1.63）：「专家相关的 REST 接口（`spawns`、`recipes`、`expert_conversion` 等）」。C7 卡记下的顺延只有 `GET /spawns`、`PUT /spawns/{id}/equipment`、`/experts/legacy` | 大多没有网页调用方；`GET /spawns/{id}/knowledge` 只有一个网页单元测试在调（`getKnowledge`，`web/src/__tests__/knowledge-client.test.ts`），跟它一起删；`POST /spawns/{id}/knowledge` 仓库卡在用（`ingestKnowledgeText`，`RepoDossier.tsx`），先换调用方 |

两处现在都不能删：最后一轮跑分开始以后不再合删死代码的 PR（§11 第 4 条），而且第 2 处有一部分还在用，删了会改行为。所以按 §11 第 2 条，要用户逐条同意顺延，写明原因和新期限。⓪Plan 建议：都顺延到 v0.1.64，第 1 处跟 C5b 的同类清理一起，第 2 处并进 C7c（和 `GET /spawns` 同一个迁移）。

**用户 10-27 逐条同意顺延到 v0.1.64**：第 1 处跟 C5b 的同类清理一起；第 2 处并进 C7c。用户写明的原因：最后一轮跑分后不再合删代码的 PR，而且第 2 处有一部分还在用。v0.1.64 删到这两处时，同一个 PR 里给留下的部分补上 `DELETE-BY:`。

另外几处不算过期、但不合 §9 的写法（代码注释没写版本，靠任务卡记着 v0.1.64）：`server/services/task_service.py:947-951` 还收 `"expert"` 这个 driver（注释说等「专家时代 REST」那一条和一次迁移，实际落在 C7c）；`replay_safety.py` 和 `tool_loop.py:989` 的 `HERMETIC_FETCH_BUDGET`（C7c）；`web/src/types.ts:92` 的 `spawnIntro`（README §8 说跟专家表一起删）；`pyproject.toml` 里没人 import 的 `click`、`rich`（README §8 的 v0.1.64 候选）；C7 卡说先留着、要写 `DELETE-BY: v0.1.64` 的几样也没写：`web/src/components/companion/LegacyExperts.tsx`（还用着 `POST /experts/{id}/to-skill`，和 `/experts/legacy` 是同一页）、`server/api/expert_conversion.py`、`server/db/models.py` 的 `Spawn`、`web/src/stores/arslanStore.ts` 的 `spawn_summary` 显示。v0.1.64 改到这些文件时补上 `DELETE-BY:`。

已经顺延、有用户同意记录的：F5b-2（R63-release.md「必须」卡另一半的顺延）；「until S2a-3」的定时任务不跑命令（R63-release.md，用户 10-24）；「until S6」的 `always_allowed`（S6 顺延，用户 10-24）；各卡写明 v0.1.64 / v0.1.65 的开关和旧表（C7c、C8、C2a、C4、K1、K2、K4、K7、K8、K9）。

## 判定

- §5.1：两条没达到：不退步（Claude，T11）和新题 3/3（T8 两个模型、T11 Claude）；用户 10-24 同意带着发，发布说明已写。
- §5.2：五条达到；MCP 整轮失败没有证据（M3 第 4 条的保留）。
- §5.3：第 3、5 条没过，用户 10-27 同意带着发，发布说明已写；第 7 条 Mac 那半、第 12 条截屏那半没有记录；第 10a 条无法判定；第 4、11 条通过有保留；其余通过。
- §5.4：达到。
- 删除期限：两处过期，用户 10-27 逐条同意顺延到 v0.1.64（上一节）。

⓪Plan 认为可以打 tag `v0.1.63`（在 `78b2400b` 或之后只改了文档的提交上）。打 tag 和发布由用户点。

## 打 tag 时要知道的

- 新的运行镜像 `macos-26-arm64 20261021.0445.8` 上没有 `~/.cargo/bin/rustc`（第三候选第一次出包 `40220041558` 因此失败）。#418 让 `build_dmg.sh` 退回到 PATH 上的 rustc，但这只有单元测试；成功的第三候选 `40223018402` 是在旧镜像 `20261013.0424.1` 上出的包。tag 那次出包如果挂在 Rust 上，看这里。
- 用户本机的终端设置是「只问有风险的」：迁移 0070 切过一次，用户自己切回（用户 2026-10-27 确认，保持不动）。这个设置下有已知的 `cd` 后相对路径删除的缺口（发布说明 Known limits 第一条，v0.1.64 修）。

## 尚无证据、未声称已验

- M3 第 7 条 Mac 窗口那半没有记录。
- M3 第 12 条截屏那半（真实屏幕而不只是桌面背景、第一次是否弹「屏幕录制」授权）没有记录；记录里只有两次送文件。
- MCP 整轮失败：没有测过模型真用到大服务器工具的那条路（README §8）。
- 本判定没有逐项重核 R63「验收」里的文档类条目（docs-site 文案、SECURITY.md 等）。它们由各自的 PR 合并时核过；打包里的 `THIRD_PARTY_NOTICES.md`、`LICENSE` 和 WebSocket 探针由第三候选的 `fresh_install_check` 证明。
