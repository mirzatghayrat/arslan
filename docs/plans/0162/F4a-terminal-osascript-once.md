# F4a 终端里的 osascript 和 `shortcuts run` 只给「这一次」（R2）

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | 热修版 |
| 分级 | 必须 |
| 依赖 | F5a |
| 合并位置 | F 线，F5a 之后不分先后；S2a 依赖本卡 |
| 推动的门槛 | §5.4「R2 回归测试」；§5.3 第 9 条；§5.4「发布说明逐句对测试」 |
| 分支 | `claude/0162-f4a-terminal-osascript-once` |
| 迁移号 | 无 |

## 目标

经 `run_command` 跑的 `osascript` 和 `shortcuts run`：

- 卡片只给「这一次」，从不记住；
- 已经存下的规则或本对话授权，不再让它们免卡；
- 改正 v0.1.61 发布说明里那句与事实不符的话。

## 现状（亲核）

- **两条规则：** 终端规则 `apple-events` 匹配 `osascript`，`shortcuts` 匹配 `shortcuts run`（`server/services/terminal_policy.py:55-56`；计划写的 `:52` 是禁止层里的另一条）。
- **卡片给出「本对话」和「总是」：**
  - 命令卡的请求是 `kind="command"`（`server/services/approvals.py:560-575`）；
  - `"command"` 不在只给一次的 `_ONCE_ONLY` 里，也不在 `_NEVER_ALWAYS` 里（`server/services/permissions.py:54-65`）；
  - 所以 `options_for` 给出这两项（`:158-164`）。
- **存下的回答会免卡，有两条路：**
  - **规则：** 「总是」存成 `legacy_rule`。命中的规则全被记住时，`standing_allows` 直接放行（`terminal_policy.py:164-169`、`:220-237`）。窗口和后台任务两处都这样用：`server/ws/arslan.py:571-592`、`approvals.py:499-517`。
  - **授权：** 本对话授权存在库里。`_standing` 只要 kind 不在 `_ONCE_ONLY`，就会去查授权（`permissions.py:301-320`）。
- **发布说明写错了：** `docs/releases/v0.1.61.md:12` 写的「Every AppleScript still asks every time」，只对 Hands 的 AppleScript 工具成立。

## 改哪些文件

- **`server/services/terminal_policy.py`：**
  - 定义「只给一次」的规则集合 `{"apple-events", "shortcuts"}`；
  - `standing_allows` 对命中其中任何一条的命令一律返回 False。
- **`server/services/approvals.py` 的 `_command_request`：** 规则里有这两条之一时：
  - `once_only=True`（下一条新加的字段）；
  - `conversation_ok=False`；
  - `always_label=""`；
  - `remember_as=()`。
- **`server/services/permissions.py`：**
  - 给 `Request` 加一个 `once_only: bool = False`；
  - `options_for` 和 `_standing` 都认它：只给 `["once"]`，不查规则也不查授权；
  - `_dedupe`（`:434-446`）把它算进去。
  - 不改卡的 kind，因为 `perm_kind` 是 iPhone 和灵动岛已经在认的值。
- **测试**（计划说 2 个，实际核到的是下面 3 个）：
  - `tests/server/test_terminal_policy.py:140-146`：`:141`、`:143` 两条断言要反过来；
  - `tests/server/test_background_jobs.py:298-311`：`:309` 断言「记住 apple-events 后单独的 osascript 直接放行」，要改成仍然问；
  - `tests/server/test_run_command_confirm_flow.py:396-420`：断言照旧成立（仍出卡），只是 docstring 的前提不对了，改写 docstring。
- **v0.1.61 发布说明的更正（`docs/releases/v0.1.61.md:12`）：**
  - 按 `docs/sessions.md` §3，`docs/releases/*.md` 只由发版 PR 写，所以本卡不改这个文件。
  - 本卡在 PR 描述里写好更正的原文和对应的测试名，由 FR 写进热修版的发布说明，并在 `v0.1.61.md:12` 后面加一句更正，原句不改。
  - 已经发布的 GitHub Release 正文，要用户点头才能改。PR 里写明这一点，由用户决定。

## 不许碰

- Hands 的 `mac_applescript`、`mac_run_shortcut`（③Hands 的文件；它们已经每次都问）。
- 其他终端规则的选项（「更少的命令卡」是 S2a 的事）。
- 已经存下的 `legacy_rule` 行：不删，不写迁移，只是不再生效。设置页照旧能列出和删除它们（`server/api/settings.py:181-195`）。
- Bridge 帧格式、`web/src/locales/*`：卡片只少了选项，不加文案。
- 网页：它按帧里的 `options` 画选项，只对只给一次的那几种 kind 再收窄（`web/src/components/kit/askParts.tsx:85-90`，`RunCommandCard.tsx:61`）。服务端给 `["once"]`，网页就只画「这一次」，不用改。

## 怎么做（要点）

1. 先写「验收」里的新测试，看它们在 main 上失败。
2. `once_only` 要在三处都认：`options_for`、`_standing`、`_dedupe`。三处一起改，同一个提交。
3. 再改那 3 个旧测试。每改一条，在 PR 里写一句「为什么现在反过来」。
4. PR 描述里写好 v0.1.61 更正的原文和对应的测试名，交给 FR。

## 验收

- **新测试「osascript 卡只给这一次」：** `osascript -e …` 和 `shortcuts run "x"` 的卡，`options == ["once"]`。窗口一条，后台任务一条。
- **新测试：** 已存 `legacy_rule` `apple-events`，同时有一条 kind `command`、target `rules:apple-events` 的本对话授权。下一条 `osascript` 仍然出卡。
- **新测试：** 收件箱的「总是允许」不会为这类命令存任何东西（`remember_as` 为空）。
- 上面列的 3 个测试按新行为改好，并且通过。
- 别的命令（比如 `rm -rf build`）的「总是」照旧有效：`test_always_on_a_two_rule_command_silences_it_next_time`（`test_run_command_confirm_flow.py:425-440`）不改，照样通过。

## 量级

产品代码约 25–40 行，外加测试。发布说明的更正由 FR 写。

## 风险与回退

- **用户会多看到卡：** 原来已经「总是允许」osascript 的人，升级后每次都会看到卡。
  - 这正是要的行为，热修版的发布说明里要写清楚。
- **字段名就叫 `Request.once_only`，不要改名：** S1、S2a、S5 三张卡都按这个名字用它。
- **两件事要一起改：**
  - `options_for` 和 `_standing` 都要认它；
  - 不能只改界面选项。只改选项的话，库里的旧授权照样会免卡。
- **回退：** revert 合并提交。没有改数据。
