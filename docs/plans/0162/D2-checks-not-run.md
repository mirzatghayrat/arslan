# D2 「检查跑不了」不该把做完的事挂成「等你」

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.63 |
| 分级 | 必须（M1B 基线发现：T1 上 Arslan 6 跑全部因此停在「等你」） |
| 依赖 | — |
| 合并位置 | 不进 K 线串行链。改 `server/resources/artifact_inspector.py` 和 `server/services/task_service.py`（热点文件）；在 K 线 PR 之间的空档合，同一时间改 `task_service.py` 的打开 PR 最多一个 |
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

- `server/resources/artifact_inspector.py`：
  - 把常见的代码和配置文本类型并进按 UTF-8 解析的那一组，例如 `.swift` `.sh` `.zsh` `.applescript` `.rb` `.go` `.rs` `.java` `.kt` `.c` `.h` `.cpp` `.m` `.yaml` `.yml` `.toml` `.xml` `.ini` `.cfg` `.sql` `.log`。能解码就是 `passed`（`text_parsed`），解码失败就是 `failed`。具体名单开工时定，写进 PR。
  - 仍然没有解析器的类型，返回 `{"status": "not_applicable", "code": "artifact_type_not_checked"}`。没法检查不等于检查没跑，不作任何断言。
- `server/services/task_service.py`：不改判断逻辑，`not_applicable` 本来就不挡成功。只核对 `checks_missing` 里没有别处把 `not_applicable` 当成没跑。
- 测试，见「验收」。

## 不许碰

- 真正的失败照旧挡住：解析失败（`failed`）、解析超时（`artifact_parser_timeout`）、隔离不可用（`artifact_parser_isolation_unavailable`）、解析器自己崩了，这些都仍是 `not_run` 或 `failed`。
- 题目自己的验收检查（`file_saved` 等）和 F2 的规则（E15：写入快照本身不算查过的交付物）。
- 解析在沙箱里跑的方式（`code_sandbox`）。

## 验收

- **测试：**
  - 写一个 `.swift` 辅助文件、题目检查通过 → `succeeded`，不是 `waiting_user`；
  - 一个没有解析器的二进制类型（例如 `.bin`）→ 产物 `not_applicable`，不挡成功；
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
