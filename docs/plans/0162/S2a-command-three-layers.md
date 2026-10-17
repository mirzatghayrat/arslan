# S2a 命令「沙箱优先」三层；受保护路径补全

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | 0.1.62 |
| 分级 | 必须（兑现 v0.1.61 发布说明「更少的命令卡」，D14） |
| 依赖 | F4a、C1；S3 先合更稳（见风险） |
| 合并位置 | F4a、C2c、C4 之后：三张都动 `server/services/approvals.py` 和 `server/ws/arslan.py` 的命令阶梯，先删后改。S2b、S4、S5 之前。改 `server/orchestrator/tool_loop.py:1042-1100`，有 K 线 PR 开着就排在它后面 |
| 推动的门槛 | D14 第一条承诺；§5.3 第 9 条（随 F4a 保持）；附录 A「危险命令识别」→ 追平；M2「卡片数（按种类）」中的命令卡下降 |
| 分支 | `claude/0162-s2a-command-layers` |
| 迁移号 | 无 |

## 目标

把 `terminal_policy` 的「问不问」换成三层（⓪Plan 提案 §5.1；总计划 S2）。

### ① 禁止层：永不跑，出不出沙箱都一样

- **现有 4 条** `_FORBID`（`server/services/terminal_policy.py:40-53`）。
- **Hermes 硬黑名单里适用于 macOS 的，改写成 Arslan 自己的规则。**
  - 今天经 `hermes.detect_hardline_command` 调用（`:117-119`），原文在 `arslan/vendor/hermes/approval_detection.py:92-125`。
  - 要搬的：
    - 递归删 `/`、`~` / `$HOME`、系统根目录（并进现有的 `macos-roots`）；
    - fork bomb；`kill -1`；`shutdown`、`reboot`、`halt`；
    - 写原始磁盘：`dd of=` 或重定向到 `/dev/disk*`、`/dev/rdisk*`；`diskutil erase*` / `zeroDisk` / `secureErase` / `partitionDisk`；`newfs_*`。
  - 只适用于 Linux 的不搬：`init 0/6`、`systemctl`、`telinit`、`/dev/sd*` 等。
- **新增：命令文本直接点名 Arslan 的数据目录就禁止**（`config.data_dir()`、`~/Library/Application Support/Arslan`）。
  - 沙箱里本来就挡（`server/services/command_sandbox.py:93-94`）。这一条补的是命令出了沙箱的情形（handover §7.4）。

### ② 对外 / 删除清单：只给「这一次」，从不记住，忽略已存的「总是」

做法沿用 F4a：卡的种类仍是 `command`（灵动岛和手机认的就是它），请求带 F4a 加的 `once_only=True`，不查规则也不查授权。F4a 只放了 `apple-events`、`shortcuts` 两条，本卡把集合扩成整张清单：

| 组 | 规则（名字沿用 `_ASK`，`terminal_policy.py:54-77`；新增的标 *） |
|---|---|
| 发出去 | `send-mail`、`send-message`、`upload`、`remote-shell`、`git-push`、`publish` |
| 删除 | `delete-outside`*：rm / rmdir / unlink / trash / srm 的目标不在工作文件夹里，或看不出目标；`force-kill`*：`kill -9`、`killall`、`pkill` |
| 改系统 | `login-items`、`keychain-write`*：`security add-*` / `delete-*` / `import`；`system-settings`*：`tccutil reset`、`networksetup -set*`、`systemsetup -set*`、`pmset`、`spctl`、`scutil --set` |
| F4a 已有 | `apple-events`、`shortcuts` |

- 这些动作绕得过文件沙箱：Apple Events、XPC、网络都不经文件规则。所以沙箱代替不了问。
- 把种类换成 `KINDS` 里给 3a 留的 `send`、`destructive`、`system`（`approvals.py:301-307` 的注释），手机和网页的风险显示会更准。但这属于卡片界面的大合并，记进 0.1.63 候选，本卡不换。
- **规则名不改。** M1 的驱动按名字回答卡（`scripts/kernel_bench/arslan_driver.py:37`、`:102-111`）；`task_service._OUTBOUND_RULES` 也按名字判断（`server/services/task_service.py:51-52`）。新增的名字告诉 ⓪Plan。

### ③ 其余：沙箱可用就在沙箱里直接跑，不出卡

- 被沙箱拦下时，照旧出一次「沙箱外重跑」卡（`tool_loop.py:1283-1290`）。
- **读不懂的命令问一次**（规则名 `unreadable`，同样 `once_only`）。以下几种算读不懂：
  - 解析不了：引号不配对、超过解析上限；
  - `eval`、`source <(…)`；
  - 把网络或解码的结果管道给 shell：`curl … | sh`、`base64 -d | sh` 等；
  - 内联脚本（`python -c`、heredoc、`node -e`……）里出现联网、起进程、驱动 App 的字样（沿用 `_SCRIPT_REACH`，`terminal_policy.py:178-189`）。
- **R4：今天免卡只看设置。**
  - `_sandbox_enabled`（`server/orchestrator/tool_loop.py:909-917`）只读设置，用在 `:1057` 和 `:1081`。
  - 设置开着、但 seatbelt 起不来时，`command_sandbox.wrapper` 返回 None，命令照样在沙箱外跑（`server/services/terminal_exec.py:101-102`）。
  - 改成：免卡前必须 `command_sandbox.available()`（`command_sandbox.py:155-168`）为真。
  - 沙箱关着或起不来时，第③层也出卡（种类 `command`）：「这一次」或「本对话」。「本对话」= 这段对话里不进沙箱的普通命令都不再问，目标 `unsandboxed:*`。
- 谨慎模式（`ask_all`）照旧：每条命令都出卡，目标是命令原文（`text:`）。S5 再把模式收成一个设置。

### 受保护路径：每个沙箱配置都带

- `default_protected()`（`command_sandbox.py:88-103`）加上：`~/.aws`、`~/.config/gcloud`、`~/.kube`、`~/.docker/config.json`、`~/.netrc`、`~/.npmrc`、`~/.pypirc`。
- 它已被工作区配置（`profile`，`:115-141`）和能力沙箱（`server/services/capability_sandbox.py:63-65`）共用。
- 离线兜底用的旧配置 `_SEATBELT_PROFILE`（`server/services/code_sandbox.py:45`，由 `terminal_exec.offline_wrapper` 使用）还没带，补上。
- **事实更正：** 计划里说「补上 Arslan 数据目录」，但它已经在列表里（`command_sandbox.py:93-94`）。真正的缺口是出了沙箱的命令（见①的新增规则）。

## 改哪些文件

- `server/services/terminal_policy.py`
  - 三层判断。`assess`、`ask_rules`、`risk_grade`、`describe` 这些对外的名字保留，调用方少改。
  - `runs_freely_in_sandbox`（`:192-210`）并进第③层。
  - `standing_allows`（`:164-169`）不再被判断路径读。
  - 本卡仍可以用 Hermes 的文本规整（`_detection_texts`，`:89-94`），由 S2b 换掉。
- `server/orchestrator/tool_loop.py:1042-1100`：`run_command` 分支按三层走；R4。**免卡只在这里判一次。**
- 两条命令阶梯：`server/ws/arslan.py:550-598`、`server/services/approvals.py:484-521`。
  - 阶梯被叫到就出卡，不再用 `may_skip_card`（`server/ws/arslan.py:66-80`）自己跳过普通命令。
  - 两处的 `standing` 分支删掉（`server/ws/arslan.py:590-592`、`approvals.py:514-517`）。
- `approvals._command_request`（`approvals.py:560-575`）：目标由判断结果给。第②层和 `unreadable` 走 F4a 的 `once_only` 那一支；第③层出卡时目标是 `unsandboxed:*`，谨慎模式下是 `text:<原文>`。
- `approvals.py:280-281` 的 `_ISLAND_RISKY_RULES`：改成从 `terminal_policy` 引用第②层全集加 `unreadable`，不再手抄一份。灵动岛对命令卡按规则判断（`:327-333`），所以这些卡在岛上仍然不能答。
- `server/services/task_service.py:51-52`：`_OUTBOUND_RULES` 改为引用 `terminal_policy` 的「发出去」组加 F4a 那两条，只留一份。
- `server/services/command_sandbox.py:88-103`；`server/services/code_sandbox.py:45`。
- **测试：**
  - `tests/server/test_terminal_policy.py`、`test_sandbox_script_cards.py`、`test_approvals_v2.py` 里断言旧行为的，改掉；
  - 新增回归用例：从 3a 分支（`claude/0161-terminal-categories`）的 `tests/server/test_terminal_categories.py`（2,492 行）里挑实测过的命令。

## 不许碰

- 不合并 3a 分支（4,930 行的解析器），只拿它的用例。
- `arslan/vendor/hermes/**` 不删，留给 S2b。
- Bridge 帧格式。已核过 `desktop/bridge/Sources/BridgeCore/FrameMapper.swift`：
  - 种类仍是 `command`，手机按命令文字给风险词（`:135-140`、`:218-228`），和今天一样；
  - 手机只答第一项。不用改 Swift。
- 「允许的文件夹」、出沙箱卡走 `decide()`（S4）；模式设置（S5）。

## 怎么做（要点）

1. 先把今天的行为钉成表格测试，再改：每条规则至少一条「问」、一条「不问」。
2. 一条命令同时命中几条规则时，目标里列出全部规则，同今天 `rules:<规则>|<规则>` 的写法（`approvals.py:565-571` 的说明）。
3. 已存的 `legacy_rule`「总是」不删数据，只是不再被读：第②层永远只给「这一次」，第③层不出卡。S6 的页面列出它们，可以删。
4. 用 3a 的实测命令回放，PR 里贴三层各占多少。

## 验收

- **测试：**
  - 每条禁止规则都拒，包括出了沙箱的；
  - 第②层每条都只给「这一次」，已存的「总是」不生效，灵动岛不能答；
  - 第③层：沙箱可用时不出卡；`available()` 为 False 时出卡（**R4 回归测试**）；
  - 读不懂的命令出卡，只给「这一次」；
  - 凭据目录在沙箱里读不到。
- **PR 里贴：** 3a 实测命令按三层的分布；M1 里受影响题目的前后对比（命令卡直接影响跑分，不是 K 线也要贴）。
- **M2（装上后 7 天）：** 命令卡按种类的数量明显下降。

## 量级

产品代码约 +350 / −250 行。

## 风险与回退

- **工作文件夹里的 `rm -rf`、`git reset --hard` 不再出卡**，只靠沙箱和 S3 的撤销。S3 先合更稳；如果 S2a 先合，发版前必须有 S3（§5.3 第 8 条）。
- **凭据目录挡了读。** 沙箱里的 `aws`、`kubectl`、`docker`，以及有 `~/.npmrc` 时的 `npm`，会读不到配置而失败，出「沙箱外重跑」卡。M2 若显示这类卡多，0.1.63 再细分（候选：只挡写，或按工具放行）。
- **沙箱关着的用户**，每段对话会多一张「不进沙箱」卡。想完全不问，用 S5 的「完全访问」。
- **回退：** S2b 还没合时，整个 PR revert。
