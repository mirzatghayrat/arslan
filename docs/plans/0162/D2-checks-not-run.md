# D2 「检查跑不了」不该把做完的事挂成「等你」

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.63 |
| 分级 | 必须（M1B 基线发现：T1 上 Arslan 6 跑全部因此停在「等你」） |
| 依赖 | — |
| 合并位置 | 不进 K 线串行链。改 `server/services/artifact_validation.py` 和 `server/resources/artifact_inspector.py`；`server/services/task_service.py`（热点文件）只核对、预计不改。在 K 线 PR 之间的空档合 |
| 推动的门槛 | §5.2「等你」里「检查没跑」那一类接近 0；§5.1 T1 不再因此不过 |
| 分支 | `claude/0162-d2-checks-not-run` |
| 迁移号 | 无 |
| 来源 | 2026-10-19 M1B 基线，T1（提醒事项）；用户要求查清原因 |

## 目标

一道题自己的验收检查都通过了，就不因为「顺手存下的辅助文件没法解析」停在「等你」。

今天的情况（v0.1.62，`a4fca23b`，⓪Plan 在基线实例的任务记录里核过）：

- T1 里 Arslan 用 `write_file` 先写了一个辅助脚本（`arslan_reminders.swift` / `add_reminders.swift`），再用 `run_command` 跑它，提醒事项建好了，题目自己的检查「有回答」（`answer-delivered`，deterministic）通过。
- 但每次 `write_file` 都会留下快照，进到验收报告的 `artifacts`。快照的检查交给 `artifact_validation.inspect_bytes` → `server/resources/artifact_inspector.py`。它只认一张固定的类型表：office 文档，以及 `.txt` `.md` `.json` `.csv` `.tsv` `.html` `.css` `.js` `.ts` `.py` `.svg`（`artifact_inspector.py:73-87`）。表外的类型一律返回 `{"status": "not_run", "code": "artifact_parser_unavailable"}`。
- `task_service._run` 把 `not_run` 的产物当成「检查没跑」：`verified` 要求每个产物是 `passed` 或 `not_applicable`，`checks_missing` 也认这一条。于是任务以 `waiting_user`、`pause_reason = task_checks_not_run` 收场。
- **这和 F2 无关**：F2 改的是「需要你核对」（`task_reconciliation_required`）和存过交付物后的 `limit_reason`，没碰「检查没跑」这条路。
- 影响面：模型写 `.swift`、`.sh`、`.applescript`、`.rb`、`.go`、`.toml`、`.yaml` 这类辅助文件的任何回合和后台任务。

## 改哪些文件

- **`server/services/artifact_validation.py` 的 `inspect_bytes`：在主机上、启动沙箱之前先判断类型**（②Main 审查）。
  - 后缀不在检查器认识的名单里（office 文档、原有的文本类型，加上下面新加的文本类型），直接返回 `{"status": "not_applicable", "code": "artifact_type_not_checked"}`，不启动沙箱。
  - 为什么放在这里：`inspect_bytes` 只接受检查器返回 `passed` / `failed` / `not_run`（`artifact_validation.py:54`），别的值都会变回 `not_run / artifact_parser_unavailable`，所以只在检查器里返回 `not_applicable` 不起作用。在主机上先判断，还能让没有 seatbelt 的主机上的未知类型，不落进 `artifact_parser_isolation_unavailable`（`not_run`）。
  - 认识的类型名单写成一个常量，检查器和 `inspect_bytes` 共用，不能两边各抄一份。
- `server/resources/artifact_inspector.py`：把常见的代码和配置文本类型并进按 UTF-8 **解码**的那一组，例如 `.swift` `.sh` `.zsh` `.applescript` `.rb` `.go` `.rs` `.java` `.kt` `.c` `.h` `.cpp` `.m` `.yaml` `.yml` `.toml` `.xml` `.ini` `.cfg` `.sql` `.log`。
  - 能解码就是 `passed`（`text_parsed`），解码失败就是 `failed`。
  - 只解码，**不做结构解析**：`.xml`、`.yaml`、`.toml` 都一样。谁要用 ElementTree 解析 `.xml`，就得像 `.svg` 那样拒绝 DOCTYPE、ENTITY（防 billion laughs）。
  - 具体名单开工时定，写进 PR。
- `server/services/task_service.py`：预计不改，`not_applicable` 本来就不挡成功（`verified` 认 `passed` / `not_applicable`；`checks_missing` 只认 `not_run`）。开工时核对一遍。
- 测试，见「验收」。

## 不许碰

- 真正的失败照旧挡住，都仍是 `not_run` 或 `failed`：
  - 解析失败（`failed`）、解析超时（`artifact_parser_timeout`）；
  - **已知类型**上的隔离不可用（`artifact_parser_isolation_unavailable`）；
  - 加密的文件（`encrypted_artifact`，检查器 `:30`）。
- **`artifact_parser_unavailable` 今天有两层意思，只改第一层：**
  - 「这个类型没有解析器」：改成 `not_applicable`；
  - 「已知类型的库导入失败」（检查器里的 `except ImportError`），以及 `inspect_bytes` 在主机上的各种失败（找不到主机 Python、启动报 OSError、非零退出、输出不对）：**照旧 `not_run`**。
- 题目自己的验收检查（`file_saved` 等）和 F2 的规则（E15：写入快照本身不算查过的交付物）。
- 解析在沙箱里跑的方式（`code_sandbox`）。

## 验收

- **测试：**
  - 写一个 `.swift` 辅助文件、题目检查通过 → `succeeded`，不是 `waiting_user`；
  - 一个没有解析器的二进制类型：端到端调用 `inspect_bytes(b"...", ".bin")` 得到 `not_applicable`，不挡成功。CI 跑在 Linux 上，没有 seatbelt，这条测试同时证明判断是在主机上、启动沙箱之前做的；
  - 解析超时、隔离不可用 → 仍然 `not_run`，任务仍然挂起（守住原来的谨慎）；
  - 一个解码失败的 `.sh` → `failed`。
- **M1：** T1 上 Arslan 不再因为 `task_checks_not_run` 停下；贴前后对比（M1B 基线里 6 跑全部停在这里）。
- **M2（装上后 7 天）：** 「等你」里 `task_checks_not_run` 那一类接近 0。
- 完成证据四项（`docs/sessions.md` §8）。

## 量级

产品代码约 +20 / −3 行，测试另算。

## 风险与回退

- **风险：一个坏掉的交付物被当成「不适用」放过。** 只对「没有解析器的类型」放行，能解码的文本类型照样解析，解析失败照样挡；题目自己的验收检查照旧决定成败。
- **回退：** revert 这一个 PR。
