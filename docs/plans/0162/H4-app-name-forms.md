# H4 AppleScript 里 App 的「.app」和完整路径写法，也要按同一个 App 认

| 项 | 内容 |
|---|---|
| 道 | ③Hands（`hands_service.py` 是它的文件）；②Main 审 |
| 版本 | v0.1.63 |
| 分级 | 必须：恢复一条已有的承诺（never-list 和高权限 App），和 #251 一样算安全修复 |
| 模型 | 代码和审查都在 Opus 5.5 上做（用户 2026-10-20 的规矩）；结论写明模型 |
| 依赖 | #267（同一个文件，先合） |
| 合并位置 | 不进 K 线；#267 之后 |
| 迁移号 | 无 |
| 来源 | ②Main 2026-10-20 在 Opus 5.5 上复审 #267 时发现。main 上就有，不是 #267 引起的 |

## 问题

AppleScript 认 `tell application "System Events.app"`，也认完整路径（`tell application "/Applications/1Password.app"`）。今天 Hands 的几个判断只认不带后缀的名字：

- `_high_reach`：`"System Events.app"`、`"Finder.app"`、`"Terminal.app"`、`"Shortcuts Events.app"` 都被判成普通 App（`app`），不是高权限。
- `never_touched`：`"/Applications/1Password.app"` 这种路径写法不被拒。
- **后果（`mac_applescript`）：**
  - 一段 System Events 脚本变成「每个 App 问一次」的卡，灵动岛也能批。之后它还能用 `tell process "1Password"` 碰到 never-list 里的 App。
  - 按路径写 1Password，直接绕过 never-list。
- S2a-1 的「不包沙箱跑」不受影响：D4 不放行 `.app"`，允许清单只认确切的名字。
- **③Hands 做 H4 时又找到两处**（Opus 5.5，#271 已修）：
  - `_SCRIPT_APP` 把 App 名字限在 120 个字符以内。故意拉长的 1Password 路径，在检查看来就是「没写 App」，也绕过 never-list。
  - 同样的写法问题也在 `desktop_open` 和 `_resolve_app`（模型写的 App 名字）里，不只 `mac_applescript`。
  - System Events.app 被误判成普通 App 这一处，今天在 `mac_applescript` 里被 0.1.61 的改写盖住了；那道门以后放开时会变成真问题，所以一起修。

## 改什么

- 在 `hands_service.py` 里加一个把 App 名字规范化的函数：去掉目录、去掉 `.app` 后缀、转小写。`script_apps`、`_high_reach`、`never_touched` 都用它，不各写一份。
- 路径写法：按路径找到那个 App，读它的 bundle id，和名字一起对 never-list，就像 `app_identity` 今天对名字做的那样。找不到 App 的路径就按名字部分认，不放宽。
- 顺手核对：别处还有没有按 App 名字判断的地方（审批规则、允许的 App 清单），也走同一个函数。
- App 名字不限长度（去掉 120 个字符的上限）。
- **App 名字不是写死的字符串，一律拒**（⓪Plan 2026-10-20 在 Opus 5.5 上定，③Hands 建议）：比如 `tell application ("1Pass" & "word")`、`tell application someVariable`。这种名字静态查不出来，今天按「看不出是哪个 App」每次问、把脚本给用户看，但不硬拒。never-list 承诺的是硬拒，所以改成直接拒，告诉模型「App 名字要写成字面的字符串」。这一条只会挡住很少见的写法。

## 验收

- **测试：**
  - `"System Events.app"`、`"Finder.app"`、`"Terminal.app"`、`"Shortcuts Events.app"` 都判成高权限；
  - `"/Applications/1Password.app"` 和 `"1Password.app"` 都被 never-list 拒；
  - 大小写不同（`"system events.APP"`）也一样；
  - 普通的 `"Reminders.app"` 仍判成 `app`；
  - 超过 120 个字符的 1Password 路径照样被 never-list 拒；
  - `desktop_open` 和 `_resolve_app` 收到 `.app` 和路径写法时一样认；
  - `tell application ("1Pass" & "word")`、`tell application x`（变量）被拒，并告诉模型原因。
- **Mutation：** 每个函数去掉规范化，都要有测试抓到。
- ②Main 在 Opus 5.5 上审，结论写明模型。
- 完成证据四项（`docs/sessions.md` §8）。

## 量级

产品代码约 +40 行，测试另算。
