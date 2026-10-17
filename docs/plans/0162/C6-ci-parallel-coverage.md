# C6 CI：pytest 并行、出覆盖率，macOS 任务不再写死用例数

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.63 |
| 分级 | 应该 |
| 依赖 | F5a（CI 先恢复绿色，才分得清是并行带来的红还是原来就红） |
| 合并位置 | F5a 之后随时。<br>• 不碰产品代码和 K 线热点；<br>• `.github/workflows/ci.yml` 里，F5a 改 `:146-175`，本卡改 `:103` 和 `:312-353`，不重叠；<br>• C5b 也可能在 `ci.yml` 里加注释，后合的 rebase |
| 推动的门槛 | §5.4「CI 全绿」：反馈更快，覆盖率看得见。计划目标是 backend 任务约 31 分钟降到约 10 分钟 |
| 分支 | `claude/0162-c6-ci-parallel-coverage` |
| 迁移号 | 无 |

## 目标

1. **pytest 并行**：用 `pytest-xdist`，每个 worker 用自己的数据目录。
2. **出覆盖率报告**：`pytest-cov` 已经在 `dev` extra 里（`pyproject.toml:174`），只出报告，不设门槛。
3. **macOS 任务**改成断言「跳过数 = 0」，不再写死用例数。现在这个数要在两处同步：`ci.yml:337` 的 `EXPECTED = 54`，和 `tests/server/test_macos_marker_covers_the_platform_set.py:87` 的 `EXPECTED_TOTAL = 54`；`ci.yml:333` 的注释还写着已经过时的 48。

## 改哪些文件

- `pyproject.toml:171-178`：`dev` extra 加 `pytest-xdist`，然后重新生成 `uv.lock`（生成文件）。`pytest-xdist` 今天不在 lock 里，已核。
- `.github/workflows/ci.yml:103`：
  - 改成 `pytest tests/ -q -rfEs -n auto --dist loadfile`；
  - 加上 `--cov=server --cov=arslan --cov-report=term:skip-covered --cov-report=xml`；
  - `coverage.xml` 作为 artifact 上传。
  - `:75-102` 的注释保留，再加一句并行的说明。
- `ci.yml:312-353`，macOS 的「Assert they RAN」这一步：
  - 删 `EXPECTED`（`:337`）和 `total - skipped != EXPECTED` 这条（`:346-347`）；
  - 保留「skipped 必须为 0」「failures 必须为 0」，再加一条「total 必须大于 0」；
  - 改掉过时的注释（`:318-329`、`:333-336`）。
- `tests/server/test_macos_marker_covers_the_platform_set.py`：
  - 删 `EXPECTED_TOTAL`（`:87`）、`test_the_marked_population_matches_the_measurement`（`:195-219`）、`test_the_ci_workflow_expects_the_same_count`（`:222-229`）；
  - 保留两个结构性检查：`:147`「每个按平台跳过的文件都打了标记」和 `:166`「打了标记的文件确实有平台判断」。新增的 macOS 测试不会漏标，靠的是它们。
- 测试隔离：
  - 数据目录：`tests/real_data_dir_guard.py:52-61` 的 `pin_suite_data_dir()` 用 `tempfile.mkdtemp`，每个进程各建一个，xdist 的 worker 是独立进程，按理天然隔离（未实测）；
  - 真用户目录的快照检查（同文件的 `snapshot`、`created`）在每个 worker 里各跑一遍，要确认不会误报；
  - 只在发现冲突的地方改测试，不改产品代码。

## 不许碰

- 产品代码。
- `ci.yml:105-144` 的 Hands 检查，以及 F5a 删掉的 Cua 段。
- macOS 任务的选择方式（`-m macos`，`ci.yml:310`）和 macOS 绑定检查（`:289-305`）。
- 测试本身的断言，除非是为了消除并行下的相互干扰。

## 怎么做（要点）

1. **先测基线。** 在本卡分支上，不加 `-n` 跑一次，记下 pytest 这一步的耗时，再看整个 backend 任务各步骤的耗时。
   - 计划里的「约 31 分钟」取自 run 38489348597，本卡起草时没核；以本卡实测为准。
   - backend 任务里还有 Hands 的 `cargo test` 和 cargo-deny，pytest 并行只能缩短 pytest 那一步。
2. **找出相互干扰的测试。** 本地连跑 3 次 `-n auto --dist loadfile`，再在 CI 上跑 2 次。
   - 只在某一种顺序下才红的测试，逐个找出原因：共享文件、固定端口、模块级全局状态。可疑点可以先 `rg -n "\.bind\(|/tmp/" tests` 找；
   - 能修就修测试；修不了的标 `xdist_group`，让它们在同一个 worker 里跑。不能用重跑掩盖。
3. 覆盖率只出报告。在 PR 描述里贴一次总数，作为基线。

## 验收

- PR 里贴两次 CI run 的 id 和 conclusion：
  - backend 任务的总耗时，以及 pytest 这一步的耗时，前后对比；
  - 目标是 pytest 那一步至少快一半。达不到就写明卡在哪里。
- 连续 2 次 CI 绿，没有新的不稳定测试。
- CI 的 artifact 里有 `coverage.xml`，日志里有覆盖率汇总。
- macOS 任务：跳过数为 0；`ci.yml` 和测试文件里都不再有写死的用例数。

## 量级

- workflow 约 ±40 行；
- `pyproject.toml` +1 行；
- `uv.lock`：生成文件；
- 测试约 −40 行。

## 风险与回退

- **风险：** 并行暴露出原本就有的顺序依赖，比如 `tests/server/conftest.py:30-56` 那段「配置漂移」修复逻辑，在别的顺序下可能失效。修的时候以「每个测试自己干净」为准。
- **风险：** 去掉写死的数以后，如果有一个 macOS 测试被意外改成不再带标记，这个任务发现不了。这一点靠 `:147` 和 `:166` 两个结构性检查兜住。
- **回退：** revert 本 PR，`ci.yml` 回到串行。
