# F5b 删除 Cua Driver 引擎（保留 agent-desktop）

| 项 | 内容 |
|---|---|
| 道 | ②Main 实现；③Hands 审（改的是 Hands 的 Rust 代码） |
| 版本 | v0.1.63（不进 v0.1.62：U7，更正 E8） |
| 分级 | 必须 |
| 依赖 | F5a 已经随第一次合回进了 main |
| 合并位置 | 开进 main，v0.1.63 线，F5a 进 main 之后任何时候。不碰热修冻结的两个文件 |
| 推动的门槛 | §5.4 工程「CI 全绿」（删掉运行时用不到的代码，CI 不再为它变红） |
| 分支 | 默认两个 PR：`claude/0162-f5b1-unwire-cua`、`claude/0162-f5b2-remove-cua-files`；用户放宽 U2 时合成一个 `claude/0162-f5b-delete-cua-engine` |
| 迁移号 | 无 |

## 目标

删掉 Hands 里 Cua Driver 这条引擎路径：Rust 代码、打包开关、探针脚本、测试台里的 Cua 引擎。agent-desktop 一行不动。热修只需要 F5a 去掉 CI 那一步；删代码要 ③Hands 审，不挤进热修。

## 现状（亲核）

- **运行时没人用它：**
  - 打包默认不编 Cua（`packaging/hands/build_hands.sh:88-127`，要设 `HANDS_CUA_DRIVER=1` 才编）；
  - 没有 Cua Driver 时，`cua` 这个 op 只回 `engine_missing`（`desktop/hands/src/server.rs:1778-1785`）。
- **服务端、网页、Tauri 都不引用它：** 在 `server/`、`arslan/`、`web/src`、`desktop/src-tauri` 里 grep 不到 `cua`。
- **整文件：**
  - `src/cua.rs`（608 行）、`src/cua_policy.rs`（597 行）；
  - `tests/cua.rs`（570 行）；
  - `scripts/hands_cua_probe.py`（178 行）；`packaging/hands/cua-driver.pin`。
- **文件内的触点：**
  - `src/lib.rs:9-10`；
  - `src/server.rs`：导入 `:9-10`；Config 字段 `:45-49`（含只给 Cua 用的 `host_bundle_id`）；State 字段 `:68-75`；初始化 `:294-308`；关停 `:342-343`；分派 `:876`；Stop 时停 Cua `:1548-1553`；status 里的两个字段 `:1567-1568`；整段 Cua 代码 `:1627-1981`（到文件末尾，355 行）；
  - `src/main.rs:49-76`；
  - `src/paths.rs:17-20`，以及只给 `host_bundle_id` 用的 `own_bundle_id`（`:73` 起）；
  - `src/outcome.rs:25-26` 的 `from_cua`，以及它在 `:56-64` 的单元测试；
  - `tests/server.rs:107-109`、`:195-197`（Config 字段）。
  - `src/macos.rs` 的 `app_of_pid`、`secure_at`（和只给它用的 `AXUIElementCopyElementAtPosition` 声明）：只有 `server.rs` 的 Cua 段在调。它们是 `pub`，编译器不报未使用，F5b-1 一起删（更正：原卡漏列）。同样只有 Cua 段在调的 `focused_secure` 和 `secure` 留着：③Hands 要用它们给 agent-desktop 的 `press` 加密码框检查（③Hands 的卡，v0.1.63/64），那张卡不做了就一起删。
- **打包和脚本里的触点：**
  - `build_hands.sh:27-32`、`:88-127`、`:161-166`、`:176-185`、`:232-237`、`:241-242`；
  - `scripts/hands_harness/engines.py:140` 起的 `Cua` 类；
  - `scripts/hands_harness/run.py:6`、`:8`、`:30`、`:77`、`:84`、`:204`、`:234-238`；
  - `scripts/hands_harness/cases.py:75` 的注释。
- **文档：** `docs-site/sections/{en,de,es,ja,tr,zh}/09-security.html` 各有一句「Cua Driver 那条路径留在代码里，不进正式版」。这句描述的是已发布的版本，等 v0.1.63 发布后的文档同步再改，本卡不改。同一句也在 `docs/docs/{,de,es,ja,tr}/index.html:476` 和 `docs/docs/zh/index.html:475`（更正：原卡漏列），删除条件相同。

## 改哪些文件

**一个 PR**（U2：整文件删除的 PR 可以超过 800 行）：

- 删整文件：`src/cua.rs`、`src/cua_policy.rs`、`tests/cua.rs`、`scripts/hands_cua_probe.py`、`packaging/hands/cua-driver.pin`。
  - `tests/cua.rs` 要拿含 Cua 字段的 `arslan_hands::server::Config` 起服务（`:166-178`），字段一删就编不过，必须同一步删。
- 去掉上面列的文件内触点：`lib.rs`、`server.rs`、`main.rs`、`paths.rs`、`outcome.rs`、`tests/server.rs`。
- `build_hands.sh` 的 Cua 部分。
- 测试台去掉 `Cua` 引擎，`--engines` 默认只剩 `agent-desktop`，`run.py:77` 不再要求 `cua_driver`。

**和 U2 的条件对不上的地方（更正 E14；默认拆两个，用户放宽 U2 才合成一个）：**

- U2 要求整文件以外的改动「只去掉引用，合计 ≤50 行」。F5b 做不到：文件内要删的代码约 600 行。其中 Rust 约 450 行（光 `server.rs` 末尾的 Cua 段就有 355 行），`build_hands.sh` 约 70 行，测试台的 `Cua` 类约 74 行。
- 这 600 行全是删不可达的代码，本身也在 800 行以内。
- **用户同意把 U2 放宽到「文件内删除不可达代码也算」**，就按上面一个 PR 做。
- **不同意**，就拆成两个 PR，状态列写两个 PR 号：
  - F5b-1 断开接线（`claude/0162-f5b1-unwire-cua`）：文件内触点、`tests/cua.rs`、打包、脚本，走普通的 800 行规矩；
  - F5b-2 删整文件（`claude/0162-f5b2-remove-cua-files`）：`cua.rs`、`cua_policy.rs` 和 `lib.rs:9-10`，走 U2。这两个文件只依赖还要留下的 `argv`、`integrity`、`paths`、`policy`（`cua.rs:22-23`、`:239`；`cua_policy.rs:20-21`），所以 F5b-1 之后照样能编译。

## 不许碰

- agent-desktop 的一切：`packaging/hands/agent-desktop.pin`；`build_hands.sh` 的 agent-desktop 部分；`ci.yml:105-144`；`src/runner.rs` 等。
- `scripts/hands_smoke.py`（③Hands 的冒烟，本卡不改它）；
- `scripts/hands_l3/`（只用 `hands_harness.run` 的 build 和 launch，`runner.py:101`）；
- 服务端 Python；
- `docs/specs/2026-10-08-0157-hands-v2.md`（历史 spec，存档的事归 C5a）；
- Bridge 文件。

## 怎么做（要点）

1. 每一步都要过 `cargo fmt --check`、`cargo clippy --all-targets -D warnings` 和 `cargo test`，在 Linux 和 macOS 两个 job 里都要过（`ci.yml:110-111`、`:236-243`）。去掉字段后留下的未用导入会被 `-D warnings` 判红。
2. **`refused_after` 和 `Completion` 只在 Cua 段里用，随 Cua 段一起删。** H2 不要复用它们：H2 的「没执行」写在 Python 端。
3. **status 去掉 `cua_driver` 和 `cua_driver_pinned` 两个字段之前，再 grep 一遍。** 服务端 Python 没有读它们，只有测试台和探针脚本读（`run.py:77`、`hands_cua_probe.py:121`）。
4. 测试台的 `Arc` 引擎（`engines.py:214` 起）：③Hands 审 F5b-1（#249）时定为删，在 F5b-1 里一起删。它只是对照用的候选，不在 Hands 后面，用的是测试台进程自己的授权。

## 验收

- **U2 的条件**（按用户最后的决定核）：
  - 删掉的整文件都不可达或是第三方的。PR 描述逐个列出，并写怎么确认的：grep 结果、`cargo build` 不再引用、打包默认不编。
  - 不改任何行为：打包默认的 DMG 里 Hands 的文件清单和改动前一样（列出对比）。
  - 整文件以外的改动行数写进 PR 描述。一个 PR 时，要能对上用户放宽后的条件；拆两个时，F5b-2 的这部分 ≤50 行。
  - CI 全绿。PR 描述里写 run id，其中 macOS job 的「Hands helper on macOS」要过。
- 在整个仓库里 grep `cua` 和 `Cua`，只剩下这些：历史 spec、`docs/specs/hands-v2-bakeoff/`、docs-site 那 6 句、测试台里作为结果标签的字符串（`tests/test_hands_harness.py:59-62`）。
- ③Hands 用合并前的 sha 编一个开发版 Hands，跑 `scripts/hands_smoke.py`。通过的项和改动前同一种构建方式的结果一致。结果写进 PR，由 ③Hands 签字。

## 量级

- Rust 产品代码：约 −1,650 行（整文件 1,205 行，文件内约 450 行）。
- 测试：约 −575 行。脚本：约 −250 行。打包：约 −75 行。

## 风险与回退

- **风险：** 以后想重新评估 Cua 时，要从 git 历史里取回来。fork、pin 和评估记录都留在历史和 `docs/specs/` 里。
- **风险：** 测试台少了两个引擎（Cua 和 Arc），对照实验只剩 agent-desktop。
- **留着的东西和删除条件**（`docs/sessions.md` §9）：
  - docs-site 那 6 句和 `docs/docs` 里同样的 6 句：v0.1.63 发布后的文档同步里改掉。
  - `src/macos.rs` 的 `focused_secure`、`secure`：③Hands 那张 `press` 密码框检查的卡不做了，就和它一起删。
  - `server/registry/hands_tools.py:68` 的四个拒绝码和 `:1137` 那条 `refused` 分支：F5b 之后没有引擎再发它们。本卡不碰服务端 Python，交 ③Hands 在 F5b-2 合并后清掉。
- **回退：** revert 合并提交（拆成两个时，按顺序 revert F5b-2、F5b-1）。
