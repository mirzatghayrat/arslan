# D4 osascript 报「未授权」，算已知失败

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.63 |
| 分级 | 必须（U10：用户 2026-10-19 定，R63 之前做完；K1 合并前后两次对照里都直接造成「等你」） |
| 依赖 | — |
| 合并位置 | **不进 K 线串行链。** 改 `server/services/task_service.py`（热点文件）的 `known_local_failure` 和它的测试。在 K 线 PR 之间的空档合；和 D3 改同一个文件，谁先合另一个 rebase |
| 推动的门槛 | §5.2「等你」里「需要你核对」那一类；§5.1 T1 |
| 分支 | `claude/0162-d4-osascript-not-authorized` |
| 迁移号 | 无 |
| 来源 | 2026-10-19 K1 合并前后对照（#213 的评论），claude-sonnet-5-5，T1，前后各一次 |

## 目标

osascript 发给某个 App 的 Apple Events 被系统或那个 App 以「没有权限」拒掉时，那个 App 里什么都没发生，结果是已知的。任务不再因此停在「需要你核对」。

## 今天的情况（main `df18ba0e`，⓪Plan 核过）

- 模型先用 osascript 建提醒事项：`osascript <<'EOF' … tell application "Reminders" … make new list … EOF`。退出码 1，stderr 是 `112:157: execution error: Reminders got an error: A privilege violation occurred. (-10004)`。出错的位置 112:157 正是第一条 `make new list`。
- 然后模型改用 EventKit 写 Swift 脚本，成功了，3 条提醒各建一次，题目自己的检查通过。
- 可任务停在 `task_reconciliation_required`。原因：
  - 这条命令命中外发规则 `apple-events`（`_OUTBOUND_RULES`，`task_service.py:54`）；
  - `known_local_failure`（`:85-128`）对命中外发的命令一律不算已知；
  - 于是 `uncertain`，`reconciliation_required` 变真（`:403`）。
- 系统拒 Apple Events 有两种写法：
  - `-1743`（`errAEEventNotPermitted`，「Not authorized to send Apple events to …」）是隐私设置里「自动化」没授权，事件没送到那个 App；
  - `-10004`（`errAEPrivilegeError`，「A privilege violation occurred」）是那个 App 自己报的「没有权限」。这次报它的是提醒事项；它是不是对这个发送方一律拒，开工时核实（见下）。

## 改哪些文件

- **`server/services/task_service.py` 的 `known_local_failure`：** 在外发判断之前，加一条窄的已知失败。四个条件同时满足才算：
  1. 整条命令只有一个 `osascript` 调用。脚本可以从 `-e`、here-doc 或一个文件来，前后不能接别的命令（`&&`、`;`、`|` 等）。
  2. 脚本只对**一个** App 说话：只有一个 `tell application "X"` 或 `application id "…"`，没有 `do shell script`。JavaScript（`-l JavaScript`）和看不出目标的脚本，照旧不算。
  3. 退出码不是 0，stderr 最后一行是 `… execution error: X got an error: … (-1743)` 或 `(-10004)`，`X` 就是第 2 条那个 App。
  4. 没有被信号杀掉，也没有被时间上限停下。
- **开工时先核实 `-10004` 是不是对这一对「发送方、App」一律拒：**
  - 用一个只读一句、再写一句的脚本，和一个连写两句的脚本，在没授权的状态下各跑一次；
  - 看会不会前一句成功、后一句才报 `-10004`；
  - 结果写进 PR。如果不是一律拒，这一版只认 `-1743`，`-10004` 写进「没覆盖」。
- 测试，见「验收」。

## 不许碰

- 其他外发规则（发信、发消息、上传、`git push`、快捷指令等）的失败照旧不算已知。
- 对两个以上 App 说话的脚本、带 `do shell script` 的脚本、`-1743` / `-10004` 以外的错误号，照旧不算已知。
- 命令卡和 Apple Events 的批准规则不改：这里只决定「失败了要不要核对」。
- F4a 的 osascript「只问一次」不改。

## 验收

- **测试：**
  - 上面那条原样的命令和 stderr → 已知失败，任务不进「需要你核对」。
  - `-1743` 的原文 → 已知失败。
  - 两个 App 的脚本、带 `do shell script` 的、`osascript … && echo ok`、错误号 `-1728`、被时间上限停下的 → 都不算已知。
  - stderr 里的 App 名和 `tell` 的 App 不一样 → 不算已知。
  - Mutation：去掉「只有一个 App」、去掉「App 名对得上」、去掉「只有一个 osascript」，各自有测试抓到。
- **M1：** T1 不再因为 osascript 被拒停在「需要你核对」。贴前后的「等你」次数。
- 完成证据四项（`docs/sessions.md` §8）。

## 量级

产品代码约 +30 行，测试另算。

## 风险与回退

- **风险：脚本自己抛出同一个错误号。** AppleScript 可以写 `error number -1743`，在前面几句已经改了东西之后再报错，就会被当成「什么都没做」。今天的模型不会这样写；条件 2、3 已经把范围收得很窄。这条风险写进代码注释。
- **风险：`-10004` 不是一律拒。** 开工先核实，核实不了只认 `-1743`。
- **回退：** revert 这一个 PR。
