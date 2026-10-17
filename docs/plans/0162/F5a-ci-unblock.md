# F5a 让 CI 恢复绿色：去掉 Cua Driver 的 CI 检查

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | 热修版 |
| 分级 | 必须 |
| 依赖 | — |
| 合并位置 | 所有 PR 里第一个合（其他 PR 的 CI 都要靠它） |
| 推动的门槛 | §5.4 工程「CI 全绿」 |
| 分支 | `claude/0162-f5a-ci-unblock` |
| 迁移号 | 无 |

## 目标

CI 的 backend 任务现在每次都红在同一步：「Hands — cargo-deny on Cua Driver」。Cua Driver 不进任何正式构建（打包默认不编它，见 F5b），却挡住所有 PR。本 PR 只删 CI 里检查它的步骤和它专用的 cargo-deny 策略文件，让 CI 回到绿色。Rust 代码不动，留给 F5b。

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
- `desktop/hands/**` 的 Rust 代码、`packaging/hands/build_hands.sh`、`packaging/hands/cua-driver.pin`、`scripts/hands_cua_probe.py`、`scripts/hands_harness/`。这些都归 F5b。pin 文件先留着，因为 `build_hands.sh:90-95` 在 `HANDS_CUA_DRIVER=1` 时还会读它。
- `release.yml`：没有 Cua 步骤（已 grep 核过）。

## 怎么做（要点）

1. 只删上面两处，不加任何东西。
2. 核对没有别的地方读 `steps.cua_pin` 或 `third_party/cua`。删完后在 `ci.yml` 里 grep `cua`，应该一处都没有。
3. 有两个测试会读 workflow 文件：`tests/server/test_release_workflow.py`、`tests/server/test_macos_marker_covers_the_platform_set.py`。它们都不涉及 Cua 步骤，不用改。

## 验收

- 本 PR 的 CI 全绿。PR 描述里写 run id 和 conclusion，不写「CI 绿」四个字了事。
- 再开一个只改文档的 PR，rebase 到本 PR 上，CI 也是绿的。
  - 注意：`web/src/__tests__/inbox-v2.test.tsx` 有一个疑似和时间有关的不稳定测试（见 reduce-proposal §6 第 5 条）。
  - 如果那个测试红了，在 PR 里写清是它，不能算成本 PR 的问题，也不能改那个测试来过关。

## 量级

约 −30 行 workflow，−49 行 toml。没有产品代码。

## 风险与回退

- **风险：** 从此 CI 不再检查 Cua Driver 的许可证和公告。可它本来就不进正式构建，F5b 会把代码一起删掉。
- **回退：** revert 本 PR 的合并提交即可，没有数据和迁移。
- **热修版：** FR 要把它 cherry-pick 到 `release/<版本>`，否则发版分支上的 CI 照样红，`release.yml:45-64` 会拒绝出包。
