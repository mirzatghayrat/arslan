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

## 改什么

- 在 `hands_service.py` 里加一个把 App 名字规范化的函数：去掉目录、去掉 `.app` 后缀、转小写。`script_apps`、`_high_reach`、`never_touched` 都用它，不各写一份。
- 路径写法：按路径找到那个 App，读它的 bundle id，和名字一起对 never-list，就像 `app_identity` 今天对名字做的那样。找不到 App 的路径就按名字部分认，不放宽。
- 顺手核对：别处还有没有按 App 名字判断的地方（审批规则、允许的 App 清单），也走同一个函数。

## 验收

- **测试：**
  - `"System Events.app"`、`"Finder.app"`、`"Terminal.app"`、`"Shortcuts Events.app"` 都判成高权限；
  - `"/Applications/1Password.app"` 和 `"1Password.app"` 都被 never-list 拒；
  - 大小写不同（`"system events.APP"`）也一样；
  - 普通的 `"Reminders.app"` 仍判成 `app`。
- **Mutation：** 每个函数去掉规范化，都要有测试抓到。
- ②Main 在 Opus 5.5 上审，结论写明模型。
- 完成证据四项（`docs/sessions.md` §8）。

## 量级

产品代码约 +25 行，测试另算。
