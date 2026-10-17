# F5a 让 CI 恢复绿色：去掉 Cua Driver 的 CI 检查

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.62 |
| 分级 | 必须 |
| 依赖 | FR「热修线怎么走」第 1 步：先从 tag v0.1.61 开出 `release/0.1.62` |
| 合并位置 | 合进 `release/0.1.62`，热修线第一个合。合了以后，马上把 `release/0.1.62` 合回 main 一次（这时分支里只有 F5a），main 的 CI 才恢复，C1、C5b 才能开工 |
| 推动的门槛 | §5.4 工程「CI 全绿」 |
| 分支 | `claude/0162-f5a-ci-unblock`（从 `release/0.1.62` 拉，PR 的 base 是 `release/0.1.62`） |
| 迁移号 | 无 |

## 目标

CI 的 backend 任务现在每次都红在同一步：「Hands — cargo-deny on Cua Driver」。Cua Driver 不进任何正式构建（打包默认不编它，见 F5b），却挡住所有 PR。

本 PR 只删 CI 里检查它的步骤和它专用的 cargo-deny 策略文件，让 CI 回到绿色。Rust 代码不动，留给 F5b（v0.1.63，不进热修，更正 E8）。

## 证据（2026-10-17 亲核）

- v0.1.61 的 run 38498094635（`fb6d7230`）是 success。
- run 38948519509 和今天的 run 39026566961 都只败在这一步（`gh run view` 查过，其余 job 和步骤都过）。
- 今天这一轮的失败日志里有 **7 条**公告，不是计划里写的 4 条：
  - RUSTSEC-2026-0346…0349，rustls 0.23.45；
  - RUSTSEC-2026-0367…0369，`zip`，经 `cursor-theme-cli` 引入。
  一条条加忽略跟不上，删掉这一步才是办法。

## 改哪些文件

- `.github/workflows/ci.yml:146-175`：删掉整段「Hands v2: Cua Driver at its pin」，也就是注释头加 5 个步骤：
  1. read the Cua Driver pin（`id: cua_pin`）；
  2. check out Cua Driver at the pin；
  3. the Cua Driver checkout is exactly the pin；
  4. every vendored Cua Driver file is in the pinned commit；
  5. cargo-deny on Cua Driver（`--config packaging/hands/cua-deny.toml`）。
- `packaging/hands/cua-deny.toml`：删文件。全仓库只有 `ci.yml:175` 用它，另有 `packaging/hands/cua-driver.pin:6` 的一句注释提到它。

## 不许碰（必须留着）

- `ci.yml:105-144` 的 agent-desktop 检查和 helper 检查：
  - `cargo test` on `desktop/hands`（`:110-111`）；
  - 读 pin、检出、核对 pin、核对 vendored 文件（`:113-134`）；
  - 对 agent-desktop 和 helper 各跑一次 cargo-deny（`:136-144`）。
  这些是真的随 DMG 发出去的东西，必须保留。
- `ci.yml:240-243` 的 macOS「Hands helper on macOS」。
- `desktop/hands/**` 的 Rust 代码、`packaging/hands/build_hands.sh`、`packaging/hands/cua-driver.pin`、`scripts/hands_cua_probe.py`、`scripts/hands_harness/`。这些都归 F5b。
- `release.yml`：没有 Cua 步骤（已 grep 核过）。

## 怎么做（要点）

1. 从 `release/0.1.62` 拉分支，只删上面两处，不加任何东西。
2. 核对没有别的地方读 `steps.cua_pin` 或 `third_party/cua`。删完后在 `ci.yml` 里 grep `cua`，应该一处都没有。
3. 有两个测试会读 workflow 文件：`tests/server/test_release_workflow.py`、`tests/server/test_macos_marker_covers_the_platform_set.py`。它们都不涉及 Cua 步骤，不用改。
4. CI 怎么跑：`ci.yml` 对任何分支的 push 都跑，PR 只在目标是 main 时另跑（`ci.yml:3-6`）。所以开进 `release/0.1.62` 的 PR，靠推送分支拿到 CI。
5. **合了以后合回 main 一次**（审查 §3 FR）：
   - 开一个 PR，head 是 `release/0.1.62`，base 是 main，里面只有 F5a；
   - 用 merge commit 合（仓库一直这么合），不要 squash，最后整体合回时 git 才认得共同祖先；
   - 合并由用户点。

## 验收

- 本 PR 推送后的 CI 全绿。PR 描述里写 run id 和 conclusion，不写「CI 绿」四个字了事。
- 合进 `release/0.1.62` 之后，分支最新提交的 CI 也是 success（写 run id）。
- 合回 main 之后，main 最新提交的 CI 是 success（写 run id）。之后开在 main 上的第一个 PR（比如 C1），CI 不再红在 Cua 那一步。
  - 注意：`web/src/__tests__/inbox-v2.test.tsx` 有一个疑似和时间有关的不稳定测试（见 reduce-proposal §6 第 5 条）。
  - 如果那个测试红了，在 PR 里写清是它，不能算成本 PR 的问题，也不能改那个测试来过关。

## 量级

约 −30 行 workflow，−49 行 toml。没有产品代码。

## 风险与回退

- **风险：** 从此 CI 不再检查 Cua Driver 的许可证和公告。可它本来就不进正式构建，F5b 会把代码一起删掉。
- **留着的东西和删除条件**（`docs/sessions.md` §9）：
  - `packaging/hands/cua-driver.pin` 先留着，因为 `build_hands.sh:90-95` 在 `HANDS_CUA_DRIVER=1` 时还会读它。**F5b 删（v0.1.63）。**
  - 它 `:6` 那句提到 `cua-deny.toml` 的注释会过时。本 PR 不改它，随 F5b 删文件一起消失。
- **回退：** 在 `release/0.1.62` 上 revert 本 PR 的合并提交即可，没有数据和迁移。已经合回 main 的那一份，在 main 上同样 revert。
