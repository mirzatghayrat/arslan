# 工程债:拿源码文本当测试的存量(2026-08-08 清点,不修)

用户 2026-08-08 要求:「列个数进工程债,别让它们一个个等着被撞见。」
起因是 `tests/server/test_startup_backfill.py` 里那条
`test_main_lifespan_calls_backfill` —— 它 grep `main.py` 的源码来断言启动链的接线,
本轮把同族的另一条(salt resolver 的启动次序)改成了**真驱动 `lifespan`**,
并用 mutation 证明了两者的差别:调换 main.py 里的两行,复制次序的测试全绿、
真驱动那条红。

## 数字

**21 个文件 / 33 个调用点**(判据:`read_text()` 或 `inspect.getsource` 的结果
在其后 12 行内被 `assert … in / not in / count( / re.search / startswith` 消费)。

| 条数 | 文件 |
|---:|---|
| 4 | `tests/test_websocket_runtime_dependency.py` |
| 2 | `tests/server/test_capability_supply_chain.py` |
| 2 | `tests/server/test_hermetic_budget_refund.py` |
| 2 | `tests/server/test_live_evals_have_not_rotted.py` |
| 2 | `tests/server/test_llm_error_surfacing.py` |
| 2 | `tests/server/test_packaging_entry.py` |
| 2 | `tests/server/test_release_workflow.py` |
| 2 | `tests/server/test_sandbox_main_context.py` |
| 2 | `tests/server/test_update_manifest.py` |
| 2 | `tests/test_shell_window_config.py` |
| 1 | `test_accepted_file_types_agree` · `test_capability_self` · `test_live_fetch_budget` · `test_mcp_token_store` · `test_skill_script_failclosed` · `test_spawn_vision` · `test_startup_backfill` · `test_token_bootstrap` · `test_vision_error_copy` · `tests/spawn/test_manager` · `tests/spawn/test_quality` |

## 🔴 这 33 条不是 33 个缺陷 —— 分三类,只有第三类是债

1. **文件本身就是交付物**(`test_release_workflow` / `test_packaging_entry` /
   `test_update_manifest` / `test_shell_window_config`):断言一个 YAML/TOML/JSON 的内容
   **就是**断言行为,因为那份文件是被 GitHub Actions / Tauri 消费的东西,不是它的描述。
   **不算债。**
2. **刻意的漂移哨**(`test_macos_marker_covers_the_platform_set`、
   `test_live_evals_have_not_rotted` 的语料计数、`test_capability_supply_chain`):
   它们要断言的**就是源码的形状**(某个 marker 打没打、某条注册表有没有漏),
   行为断言表达不了。**不算债**,但它们各自的 docstring 应写清「我保障不了什么」。
3. **真债**:用 grep 代替一次可以真跑的观察 —— `test_startup_backfill` 那条是样本。
   **本轮没有逐条分类到这一层**,所以「真债有几条」这个数**现在给不出**。

## 为什么值得清,以及清的判据

本会话内 grep-被散文满足**发生了四次**(`color-scheme` 注释、模块 docstring 里的
`"allowed":`、我自己刚写进去的 `"pytest.mark.macos"`、`media_type.py` 的反例 docstring),
每一次那条 grep 都是绿的。

判据(与 [[arslan-assert-behaviour-not-source]] 的分界一致):
- **断言「缺席」** 可以查源码(缺席没有行为可观察);
- **断言「存在 / 会发生」** 必须观察行为。
  一条永不执行的代码和一条正确执行的代码,在源码里长得一模一样。

## 不做

本轮**只清点**。逐条分类和改写单独立项 —— 混进 ⓪ 会让一个加密改动的
diff 里混进二十个不相干的测试重写。

关联:[[arslan-assert-behaviour-not-source]]、[[arslan-verify-rules-dont-recite]]、
[[arslan-probe-must-match-consumer]]。
