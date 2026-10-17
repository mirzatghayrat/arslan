# S4b 「允许的文件夹」

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.63 |
| 分级 | 应该（审查 A2：原 S4 拆出的应该部分） |
| 依赖 | S3（问得少了，就得回得去：检查点要覆盖这些文件夹）；S4a（同一组阶梯和出沙箱授权） |
| 合并位置 | S3 → S4a → **S4b** → S6。S5 若同时开着，谁后合谁 rebase（S5 的「完全访问」也要认这些文件夹）。改 `server/orchestrator/tool_loop.py`：热修版 v0.1.62 发布前不接别的 PR；有 K 线 PR 开着就排在它后面 |
| 推动的门槛 | 减卡：⓪Plan 提案 §5.2，0.1.61 之后用户答的 21 张卡里，12 张是出沙箱卡；M2 出沙箱卡下降 |
| 分支 | `claude/0162-s4b-allowed-folders` |
| 迁移号 | 无：文件夹存设置键值 |

## 目标

- **用户选一次，之后在这些文件夹里写东西，就在沙箱里直接做，不出卡。** 这是减出沙箱卡的主力。
- 改动由 S3 的检查点兜底：S3 存不了的文件夹（另一个卷上），不能加进来。

## 改哪些文件

- **设置：** 新键 `allowed_folders`，存绝对路径的 JSON 列表。
  - 要登记的地方：`server/services/settings_service.py:19-35` 的 `_PLAIN_KEYS`、`server/schemas.py` 两个 schema、`web/src/api/adapters.ts`、`web/src/api/client.types.ts`。
  - 校验：必须存在、必须是文件夹；不能是 `/`、家目录本身、系统根目录或受保护路径（`default_protected`，`server/services/command_sandbox.py:88-103`）；必须和数据目录在同一个卷上（S3 的 `other_volume`），否则撤销做不到，拒绝并说明。
- **命令沙箱：**
  - `default_writable`（`command_sandbox.py:82-85`）加上允许的文件夹。
  - 「桌面、文稿、下载」关着时，允许的文件夹若在它们里面，要重新打开。`profile` 已经能处理这种情况（`command_sandbox.py:128-136`）。
  - 调用处：`server/registry/executors.py:792-812`。
- **S3 的检查点**：`ensure` 的范围加上允许的文件夹，各克隆一次，沿用 S3 的上限、排除和配额。
- **S2a 的 `delete-outside` 规则**：「工作文件夹以外」改成「工作文件夹和允许的文件夹以外」。
- **文件工具：** 在允许的文件夹里写也不出卡。
  - `server/registry/file_tools.py:80-92` 的 `_resolved` 认多个根；
  - `server/services/workspace_paths.py:52` 的 `resolve_in_workspace` 不改规则，只是多试几个根；
  - `_writing_in_own_folder`（`server/orchestrator/tool_loop.py:898-906`）改成看写入的路径。
- **网页：**
  - `web/src/components/settings/AdvancedSection.tsx`：在工作文件夹输入框旁（`:135-151`）加「允许的文件夹」列表，可加、可删；每个旁边一行字：「Arslan 在这里的改动不再问你，可以按回复撤销」；
  - 6 种语言。C1c 没合时，同一个 PR 改 `web/src/__tests__/locale-parity.test.ts:300` 的计数。

## 不许碰

- **Bridge 帧格式**：本卡不加卡，也不改卡的字段。
- 出沙箱卡、远程卡和阶梯本身（S4a 已合并）；安装能力卡（S7）。
- 宽 profile、「Run it anyway」、按命令前缀记住：⓪Plan 提案 §5.2 明确不做。
- ③Hands 的文件：Hands 在 App 里做的事不受这些文件夹影响。

## 怎么做（要点）

1. 先做设置键和校验，带测试（各种不能加的文件夹都被拒）。
2. 再接沙箱、检查点和文件工具，三处读同一个函数（例如 `settings_service.allowed_folders(db)`），读不出来算空列表（执行面宁关）。
3. 一个文件夹被删、被移走：读的时候跳过，设置页标「找不到」，不报错。

## 验收

- **测试：**
  - 允许的文件夹里，`cp`、`mv` 进去不出卡；文件夹外仍被沙箱拦下，出重跑卡；
  - `write_file` 写进允许的文件夹不出卡；写到别处照旧；
  - 允许的文件夹里的改动，S3 能撤销（一条命令删掉一个子文件夹，撤销后原样恢复）；
  - 另一个卷上的、受保护的、家目录本身，都加不进来；
  - `rm` 允许的文件夹里的文件，不再算 `delete-outside`。
- **M2（装上后 7 天）：** 出沙箱卡明显减少。

## 量级

产品代码约 +200 行：服务端约 100，网页约 100。

## 风险与回退

- **允许的文件夹里的改动只靠 S3 撤销。** 所以必须在 S3 之后合，并且检查点要覆盖这些文件夹；S3 跳过的（太大），确认框写明。
- **外置盘上的项目文件夹加不进来。** 用户只能把它设成工作文件夹（S3 会提示撤销不了），或者每次点出沙箱。「检查点放在同一个卷上」记进 v0.1.64 候选。
- **本卡不留旧路径。**
- **回退：** 整个 PR revert。设置键 `allowed_folders` 留着没有害处，旧代码不读它。
