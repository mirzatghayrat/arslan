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
  1. 整条命令只有一个 `osascript` 调用，脚本写在命令里：`-e` 或 here-doc。前后不能接别的命令（`&&`、`;`、`|` 等）。`osascript 某个文件.scpt` 不算：脚本不在命令里，第 2 条没法核，读那个文件时它也可能已经变了。
  2. 脚本只对**一个** App 说话：数脚本里**每一个** `tell application "名字"`，嵌套的也算（比如里面再 `tell application "System Events"`），去重后正好一个名字。
     - 只认 `tell application "名字"` 这一种写法。`tell app "…"` 的简写、`application id "…"`（stderr 里是 App 名，不是 bundle id，第 3 条对不上）、JavaScript（`-l JavaScript`）、看不出目标的，都不算。
     - 脚本里有 `do shell script`、`run script`、`load script` 的不算：它们会跑别的命令或脚本。
  3. 退出码不是 0，stderr 最后一行是下面两种之一，`X` 就是第 2 条那个 App：
     - `-1743`：`… execution error: Not authorized to send Apple events to X. (-1743)`
     - `-10004`：`… execution error: X got an error: A privilege violation occurred. (-10004)`
  4. 没有被信号杀掉，也没有被时间上限停下。
- **开工时先核实 `-10004` 是不是对这一对「发送方、App」一律拒：**
  - 用一个只读一句、再写一句的脚本，和一个连写两句的脚本，在没授权的状态下各跑一次；
  - 看会不会前一句成功、后一句才报 `-10004`；
  - 结果写进 PR。如果不是一律拒，这一版只认 `-1743`，`-10004` 写进「没覆盖」。
- 测试，见「验收」。

## 不许碰

- 其他外发规则（发信、发消息、上传、`git push`、快捷指令等）的失败照旧不算已知。
- 对两个以上 App 说话的脚本、带 `do shell script` / `run script` / `load script` 的脚本、`-1743` / `-10004` 以外的错误号，照旧不算已知。
- 命令卡和 Apple Events 的批准规则不改：这里只决定「失败了要不要核对」。
- F4a 的 osascript「只问一次」不改。

## 验收

- **测试：**
  - 上面那条原样的命令和 stderr → 已知失败，任务不进「需要你核对」。
  - `-1743` 的原文 → 已知失败。
  - 两个 App 的脚本（包括嵌套的 `tell application "System Events"`）、`tell app` 简写、`application id`、`osascript 文件.scpt`、带 `do shell script` / `run script` / `load script` 的、`osascript … && echo ok`、错误号 `-1728`、被时间上限停下的 → 都不算已知。
  - stderr 里的 App 名和 `tell` 的 App 不一样 → 不算已知。
  - Mutation：去掉「只有一个 App」、去掉「App 名对得上」、去掉「只有一个 osascript」，各自有测试抓到。
- **M1：** T1 不再因为 osascript 被拒停在「需要你核对」。贴前后的「等你」次数。
- 完成证据四项（`docs/sessions.md` §8）。

## 量级

产品代码约 +30 行，测试另算。

## 风险与回退

- **风险：脚本自己抛出同一个错误号。** AppleScript 可以写 `error number -1743`，在前面几句已经改了东西之后再报错，就会被当成「什么都没做」。今天的模型不会这样写；条件 2、3 已经把范围收得很窄。这条风险写进代码注释。
- **风险：here-doc 里的脚本再去跑别的脚本。** `run script`、`load script` 会执行另一个脚本，`do shell script` 会跑命令，它们做的事第 2 条看不到，所以这三种一律不算（条件 2）。
- **风险：`-10004` 不是一律拒。** 开工先核实，核实不了只认 `-1743`。
- **回退：** revert 这一个 PR。

## 后续 PR（D4 第二个，2026-10-21）

起因：⓪Plan 的 k2a3-ds 跑分里 T1 从 2/3 掉到 0/3，三种写法都被记成「结果不明」（不是 K2a 的问题）。

- **tell 之外的无副作用 `set` 也算安全**，按语法白名单判（`_safe_statement`）：
  - 字面量、`current date`、`date "…"`；
  - 先前 set 过的变量，和它们的日期属性（weekday、hours、minutes、seconds、time、year、month、day），也可以 `set <日期属性> of <变量> to …`；
  - `+ - * / div mod`，日、时、分、周单位，`as integer` 这类转换；
  - 单行的 `if … then set …`。
  - 不许调用、handler、`of` 一个 App 或别的对象。
- **编译期 `syntax error:` 算已知失败**：osascript 先编译整段，所以脚本里什么都没跑。
  - 只认编译期的格式（`N:M: syntax error: …`）。
  - stderr 是脚本自己能控制的（③Hands 审：先 `log` 一行假的，再杀掉父进程；或者 error 的消息结尾带这一行）。所以三条都满足才算：
    - 脚本过得了和「被拒绝」同一份白名单；
    - 只对一个 App，按名字点名，不是路径；
    - `osacompile -o /dev/null` 确认它编译不过（`_fails_to_compile`）。osacompile 只编译不运行，可能会读 App 的字典；它不可用、超时或出错时，结果仍算不明。
  - 确认步骤有一个 macOS 专用测试（`macos` 标记总数 55 → 56，测试和 ci.yml 两处一起改）。
- **`mac_applescript` 工具套同一套规则**：脚本取自参数，stderr 取自结果的 `error`。超时和其他错误码照旧算不明。实例：T1 r1 的 -1708 发生在 `make new list` 之后，不算已知。
- **顺带补上第一版的口子**：命令里有在单引号之外的 `$` 或反引号时，一律不判。理由：shell 会先替换、先跑，osascript 看到的已经不是写出来的脚本。第一版里，`-e "…$(curl …)…"` 碰上 -1743，会被当成「什么都没发生」。

## 以后再看（⓪Plan 2026-10-21 实测，不开新 PR）

#245 合并后 T1 ×3（main `5e33c5e5` 之后，DeepSeek，A 方案）：2/3 通过，K2a 时是 0/3；r2 被拒的 osascript 已算已知失败。r1 还是「需要你核对」，因为脚本里有两种写法不在白名单里：

- `end tell` 之后顶层的 `return "done"`。这段脚本还有一个别的错误号的编译错误：`syntax error: Invalid date and time date …（-30720）`，日期字符串是中文格式。
- `set time of t1 to 9 * 60 * 60`：日期属性设成纯数字算式，前后带 `--` 注释，之后报 -10004。

脚本原文在 ⓪Plan 那次跑分（fresh-arslan-T1-r1-d4b-ds）的 run_steps 里。要放宽时，两条都按同一份白名单的思路加：只认没有副作用的写法，编译错误照旧要 osacompile 确认。
