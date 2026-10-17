# F4a 终端里的 osascript 和 `shortcuts run`：每种写法都出卡，只给「这一次」（R2）

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.62 |
| 分级 | 必须 |
| 依赖 | F5a |
| 合并位置 | 合进 `release/0.1.62`，F5a 之后不分先后。发版后随分支合回 main；S2a 要等它进了 main 才开工 |
| 推动的门槛 | §5.4「R2 回归测试」；§5.3 第 9 条；§5.4「发布说明逐句对测试」 |
| 分支 | `claude/0162-f4a-terminal-osascript-once`（从 `release/0.1.62` 拉，PR 的 base 是 `release/0.1.62`） |
| 迁移号 | 无 |

## 目标

经 `run_command` 跑的 `osascript` 和 `shortcuts run`：

- **换个写法也认得出**（审查 §3，更正 E10，高）：带路径、经 `command`、`exec`、`xargs` 调用，都出卡；
- 卡片只给「这一次」，从不记住；
- 已经存下的规则或本对话授权，不再让它们免卡；
- 改正 v0.1.61 发布说明里那句与事实不符的话，只写清哪些写法会问。

## 现状（亲核）

- **认命令名只认裸名字。** `apple-events` 匹配 `_POS + osascript`，`shortcuts` 匹配 `_POS + shortcuts run`（`server/services/terminal_policy.py:55-56`）。`_POS` 是 Hermes 的「命令位置」（`arslan/vendor/hermes/approval_detection.py:67-71`），只跳过 `sudo`、`env`、`exec`、`nohup`、`setsid`、`time`，不认路径。
- **下面这些写法今天判成 `run`，一张卡都不出**（本卡复核，v0.1.61 的 `terminal_policy.assess`）：
  - `/usr/bin/osascript -e …`
  - `command osascript …`
  - `… | xargs osascript`、`xargs -0 osascript`
  - `exec /usr/bin/osascript …`
  - `/usr/bin/shortcuts run …`
  - 默认策略 `ask_risky` 下，判成 `run` 的命令不出卡（`server/ws/arslan.py:571-580`）。
- **认得出的写法，卡片给出「本对话」和「总是」：** 命令卡是 `kind="command"`（`server/services/approvals.py:560-575`），不在 `_ONCE_ONLY` 和 `_NEVER_ALWAYS` 里（`server/services/permissions.py:54-65`），所以 `options_for` 给出这两项（`:158-164`）。
- **存下的回答会免卡，有两条路：**
  - **规则：** 「总是」存成 `legacy_rule`，`standing_allows` 直接放行（`terminal_policy.py:164-169`、`:220-237`）。窗口和后台任务两处都这样用：`server/ws/arslan.py:571-592`、`approvals.py:499-517`。
  - **授权：** `_standing` 只要 kind 不在 `_ONCE_ONLY`，就会去查本对话授权（`permissions.py:301-320`）。
- **发布说明写错了：** `docs/releases/v0.1.61.md:12` 写的「Every AppleScript still asks every time」，只对 Hands 的 AppleScript 工具成立。

## 改哪些文件

- **`server/services/terminal_policy.py`：**
  - `apple-events`、`shortcuts` 两条正则改成：命令名可以带路径（只看最后一段），前面可以有 `command`、`exec`、`xargs`（含它的选项，如 `-0`、`-I {}`、`-n 1`）。仍然只在命令位置匹配，所以 `echo "use osascript"`、`grep -r osascript .` 照旧不出卡。
  - 改在 `_ASK` 这两条里，`ask_rules`、`runs_freely_in_sandbox`、`task_service._OUTBOUND_RULES` 都会自动跟上。
  - 定义「只给一次」的规则集合 `{"apple-events", "shortcuts"}`；`standing_allows` 对命中其中任何一条的命令一律返回 False。
- **`server/services/approvals.py` 的 `_command_request`：** 规则里有这两条之一时：`once_only=True`、`conversation_ok=False`、`always_label=""`、`remember_as=()`。
- **`server/services/permissions.py`：**
  - 给 `Request` 加一个 `once_only: bool = False`；
  - `options_for` 和 `_standing` 都认它：只给 `["once"]`，不查规则也不查授权；
  - `_dedupe`（`:434-446`）把它算进去。
  - 不改卡的 kind，因为 `perm_kind` 是 iPhone 和灵动岛已经在认的值。
- **测试**（要改的旧测试 3 个）：
  - `tests/server/test_terminal_policy.py:140-146`：`:141`、`:143` 两条断言要反过来；
  - `tests/server/test_background_jobs.py:298-311`：`:309` 断言「记住 apple-events 后单独的 osascript 直接放行」，要改成仍然问；
  - `tests/server/test_run_command_confirm_flow.py:396-420`：断言照旧成立（仍出卡），只是 docstring 的前提不对了，改写 docstring。
- **v0.1.61 发布说明的更正：** `docs/releases/*.md` 只由发版 PR 写（`docs/sessions.md` §3），所以本卡不改这些文件。本卡在 PR 描述里写好更正的要点和对应的测试名，由 FR 写进去。要点：
  - 列出会问的写法：`osascript` 和 `shortcuts run`，直接写、带路径、经 `command`、`exec`、`xargs` 调用，每次都问，只给「这一次」；以前存的「总是」不再生效。
  - 写明还不会问的：脚本自己调用 osascript（例如 `python3 x.py`），v0.1.63 由 S2a 在沙箱里挡住。
  - **不能**写成「终端里的 AppleScript 现在都会问」（更正 E10）。
  - 已经发布的 GitHub Release 正文，要用户点头才能改。PR 里写明，由用户决定。

## 不许碰

- Hands 的 `mac_applescript`、`mac_run_shortcut`（③Hands 的文件；它们已经每次都问）。
- 其他终端规则的匹配和选项。它们带路径的写法同样认不出（本卡复核：`/usr/bin/curl -d …`、`/usr/bin/git push`、`command git push` 都判成 `run`），归 S2a；「更少的命令卡」也是 S2a 的事。
- 已经存下的 `legacy_rule` 行：不删，不写迁移，只是不再生效。设置页照旧能列出和删除它们（`server/api/settings.py:181-195`）。
- Bridge 帧格式、`web/src/locales/*`：卡片只少了选项，不加文案。
- 网页：它按帧里的 `options` 画选项（`web/src/components/kit/askParts.tsx:85-90`，`RunCommandCard.tsx:61`）。服务端给 `["once"]`，网页就只画「这一次」，不用改。

## 本卡认不出、发布说明不能说「会问」的写法

- 脚本里调用：`python3 x.py`、`node x.js` 里再调 osascript。内联脚本（`python3 -c "…osascript…"`）只按「运行脚本」那条 Hermes 规则出卡，那条能被「总是」记住。
- `$(which osascript) …`；`open "shortcuts://run-shortcut?name=…"`（本卡复核，都判成 `run`）。
- 这些归 S2a：沙箱配置加 `(deny appleevent-send)`。`open` 走的是 LaunchServices，能不能被挡住要 S2a 实测。

## 怎么做（要点）

1. 先写「验收」里的新测试，看它们在 v0.1.61 上失败。
2. `once_only` 要在三处都认：`options_for`、`_standing`、`_dedupe`。三处一起改，同一个提交。
3. 再改那 3 个旧测试。每改一条，在 PR 里写一句「为什么现在反过来」。
4. 代码注释写明：旧的 `apple-events`、`shortcuts` 两条 `legacy_rule` 行不再生效，v0.1.64 清掉（`docs/sessions.md` §9）。
5. PR 描述里写好 v0.1.61 更正的要点和对应的测试名，交给 FR。

## 验收

- **每种写法都认得出：** 下面每一条，`assess` 都是 `ask`，规则是 `apple-events` 或 `shortcuts`：
  - `/usr/bin/osascript -e …`、`command osascript -e …`、`echo x | xargs osascript`、`xargs -0 osascript`、`exec /usr/bin/osascript …`、`command /usr/bin/osascript …`；
  - `/usr/bin/shortcuts run "x"`、`command shortcuts run "x"`；
  - `zsh -c "/usr/bin/osascript -e …"` 的 `ask_rules` 里有 `apple-events`。
- **不误报：** `echo "use osascript"`、`grep -r osascript .`、`cat shortcuts.txt` 照旧是 `run`。
- **卡只给这一次：** 上面每种写法的卡，`options == ["once"]`。窗口一条，后台任务一条。
- **旧的回答不再生效：** 已存 `legacy_rule` `apple-events`，同时有一条 kind `command`、target `rules:apple-events` 的本对话授权。下一条 `osascript`、`/usr/bin/osascript` 仍然出卡。
- **收件箱的「总是允许」**不会为这类命令存任何东西（`remember_as` 为空）。
- 上面列的 3 个旧测试按新行为改好，并且通过。
- 别的命令（比如 `rm -rf build`）的「总是」照旧有效：`test_always_on_a_two_rule_command_silences_it_next_time`（`test_run_command_confirm_flow.py:425-440`）不改，照样通过。

## 量级

产品代码约 40–60 行，外加测试。发布说明的更正由 FR 写。

## 风险与回退

- **用户会多看到卡：** 原来已经「总是允许」osascript 的人，升级后每次都会看到卡；原来用带路径写法、从没见过卡的，现在也会看到。这正是要的行为，v0.1.62 的发布说明要写清楚。
- **字段名就叫 `Request.once_only`，不要改名：** S1、S2a、S5 三张卡都按这个名字用它。
- **两件事要一起改：** `options_for` 和 `_standing` 都要认它，不能只改界面选项。只改选项的话，库里的旧授权照样会免卡。
- **留着的东西和删除条件**（`docs/sessions.md` §9，代码注释同样写）：旧的 `apple-events`、`shortcuts` 两条 `legacy_rule` 行留在库里、不再生效，设置页照旧列出。**v0.1.64 清掉**（由 ⓪Plan 记进 README §8「v0.1.64 候选」）。
- **回退：** 在 `release/0.1.62` 上 revert 合并提交。没有改数据。
