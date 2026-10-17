# F5b 删除 Cua Driver 引擎（保留 agent-desktop）

| 项 | 内容 |
|---|---|
| 道 | ②Main 实现；③Hands 审（改的是 Hands 的 Rust 代码） |
| 版本 | 0.1.62（不进热修版） |
| 分级 | 必须 |
| 依赖 | F5a |
| 合并位置 | 0.1.62 线；F5a 之后任何时候 |
| 推动的门槛 | §5.4 工程「CI 全绿」（删掉运行时用不到的代码，CI 不再为它变红） |
| 分支 | `claude/0162-f5b-delete-cua-engine`（拆成两个 PR 时：`claude/0162-f5b1-unwire-cua`、`claude/0162-f5b2-remove-cua-files`） |
| 迁移号 | 无 |

## 目标

删掉 Hands 里 Cua Driver 这条引擎路径：Rust 代码、打包开关、探针脚本、测试台里的 Cua 引擎。agent-desktop 一行不动。

## 现状（亲核）

- **运行时没人用它：**
  - 打包默认不编 Cua（`packaging/hands/build_hands.sh:88-127`，要设 `HANDS_CUA_DRIVER=1` 才编）；
  - 没有 Cua Driver 时，`cua` 这个 op 只回 `engine_missing`（`desktop/hands/src/server.rs:1778-1785`）。
- **服务端、网页、Tauri 都不引用它：** 在 `server/`、`arslan/`、`web/src`、`desktop/src-tauri` 里 grep 不到 `cua`。
- **Rust 里的触点：**
  - `src/cua.rs`（608 行）、`src/cua_policy.rs`（597 行）；
  - `src/lib.rs:9-10`；
  - `src/server.rs` 里有这些：
    - 导入 `:9-10`；
    - Config 字段 `:45-49`（含只给 Cua 用的 `host_bundle_id`）；
    - State 字段 `:68-75`；
    - 初始化 `:294-308`；
    - 关停 `:342-343`；
    - 分派 `:876`；
    - Stop 时停 Cua `:1548-1553`；
    - status 里的两个字段 `:1567-1568`；
    - 整段 Cua 代码 `:1627-1981`（到文件末尾）。
  - `src/main.rs:49-76`；
  - `src/paths.rs:17-20`，以及只给 `host_bundle_id` 用的 `own_bundle_id`（`:73` 起）；
  - `src/outcome.rs:25-26` 的 `from_cua`，以及它在 `:56-64` 的单元测试；
  - `tests/cua.rs`（570 行）；
  - `tests/server.rs:107-109`、`:195-197`（Config 字段）。
- **打包和脚本里的触点：**
  - `build_hands.sh:27-32`、`:88-127`、`:161-166`、`:176-185`、`:232-237`、`:241-242`；
  - `packaging/hands/cua-driver.pin`；
  - `scripts/hands_cua_probe.py`（178 行）；
  - `scripts/hands_harness/engines.py:140` 起的 `Cua` 类；
  - `scripts/hands_harness/run.py:6`、`:8`、`:30`、`:77`、`:84`、`:204`、`:234-238`；
  - `scripts/hands_harness/cases.py:75` 的注释。
- **文档：**
  - `docs-site/sections/{en,de,es,ja,tr,zh}/09-security.html` 各有一句「Cua Driver 那条路径留在代码里，不进正式版」。
  - 这句描述的是已发布的版本，所以等 0.1.62 发布后的文档同步再改，本卡不改。

## 改哪些文件

按 §8「产品代码 ≤ 约 800 行」，纯删除也会超线：Rust 产品代码约 −1,640 行。所以默认拆成两个 PR，都挂在本卡下。

- **F5b-1 断开接线**（约 −430 行 Rust，−570 行测试，外加打包和脚本）：
  - `server.rs`、`main.rs`、`paths.rs`、`outcome.rs`、`tests/server.rs` 里上面列的触点；
  - 删 `tests/cua.rs`：它要拿含 Cua 字段的 `arslan_hands::server::Config` 起服务（`tests/cua.rs:166-178`），字段一删就编不过，所以必须和断开接线放在同一步；
  - `build_hands.sh` 的 Cua 部分；
  - 删 `cua-driver.pin`、`scripts/hands_cua_probe.py`；
  - 测试台去掉 `Cua` 引擎，`--engines` 默认只剩 `agent-desktop`，`run.py:77` 不再要求 `cua_driver`。
  - 这一步 `cua.rs`、`cua_policy.rs` 还在，但没人调用了。
- **F5b-2 删整文件**（约 −1,205 行 Rust，含两文件里自带的单元测试）：
  - 删 `src/cua.rs`、`src/cua_policy.rs`；
  - 删 `lib.rs:9-10`。
  - 这两个文件只依赖还要留下的 `argv`、`integrity`、`paths`、`policy`（`cua.rs:22-23`、`:239`；`cua_policy.rs:20-21`），所以 F5b-1 之后它们照样能编译。
  - 只有 `git rm` 和这两行，没有别的改动，审的人一眼能核。
- 如果用户同意「整文件删除不受 800 行限制」，两步可以合成一个 PR。
- 拆成两个时，②Main 在 README 状态列里写两个 PR 号。

## 不许碰

- agent-desktop 的一切：
  - `packaging/hands/agent-desktop.pin`；
  - `build_hands.sh` 的 agent-desktop 部分；
  - `ci.yml:105-144`；
  - `src/runner.rs` 等。
- `scripts/hands_smoke.py`（③Hands 的冒烟，本卡不改它）；
- `scripts/hands_l3/`（只用 `hands_harness.run` 的 build 和 launch，`runner.py:101`）；
- 服务端 Python；
- `docs/specs/2026-10-08-0157-hands-v2.md`（历史 spec，存档的事归 C5a）；
- Bridge 文件。

## 怎么做（要点）

1. **先 F5b-1，后 F5b-2。** 每一步都要过 `cargo fmt --check`、`cargo clippy --all-targets -D warnings` 和 `cargo test`，在 Linux 和 macOS 两个 job 里都要过（`ci.yml:110-111`、`:236-243`）。去掉字段后留下的未用导入会被 `-D warnings` 判红。
2. **`refused_after` 和 `Completion` 只在 Cua 段里用，随 Cua 段一起删。** H2 不要复用它们：H2 的「没执行」写在 Python 端。
3. **status 去掉 `cua_driver` 和 `cua_driver_pinned` 两个字段之前，再 grep 一遍。** 服务端 Python 没有读它们，只有测试台和探针脚本读（`run.py:77`、`hands_cua_probe.py:121`）。

## 验收

- 两个 PR 的 CI 全绿。PR 描述里写 run id，其中 macOS job 的「Hands helper on macOS」要过。
- 在整个仓库里 grep `cua` 和 `Cua`，只剩下这些：历史 spec、`docs/specs/hands-v2-bakeoff/`、docs-site 那 6 句、测试台里作为结果标签的字符串（`tests/test_hands_harness.py:59-62`）。
- ③Hands 用 F5b-2 的 sha 编一个开发版 Hands，跑 `scripts/hands_smoke.py`。
  - 通过的项和改动前同一种构建方式的结果一致。
  - 结果写进 PR，由 ③Hands 签字。

## 量级

- Rust 产品代码：约 −1,640 行。
- 测试：约 −575 行。
- 脚本：约 −250 行。
- 打包：约 −75 行。

## 风险与回退

- **风险：** 以后想重新评估 Cua 时，要从 git 历史里取回来。不过 fork、pin 和评估记录都留在历史和 `docs/specs/` 里。
- **风险：** 测试台少了一个引擎，对照实验只剩 agent-desktop（和 Arc，要不要留由 ③Hands 定）。
- **回退：** 按顺序 revert F5b-2、F5b-1。
