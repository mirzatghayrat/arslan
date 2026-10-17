# FR 发 v0.1.62

| 项 | 内容 |
|---|---|
| 道 | ②Main（冒烟由 ③Hands 跑） |
| 版本 | v0.1.62 |
| 分级 | 必须 |
| 依赖 | 开线：只改文档的那个规划 PR 合进 main 之后就开。发版：F5a、F1、F2、F3、F4a、F4b 都已合进 `release/0.1.62`；H2 赶上就一起发 |
| 合并位置 | 热修线的头和尾：第一步开出 `release/0.1.62`；最后合进它的是本卡的发版 PR；发布后把这个分支合回 main |
| 推动的门槛 | §5.4「CI 全绿」与「发布说明逐句对测试」 |
| 分支 | 发版分支 `release/0.1.62`；发版 PR 用 `claude/0162-fr-hotfix-release`（base 是 `release/0.1.62`） |
| 迁移号 | 无（热修线不带迁移） |

## 目标

从 v0.1.61 单独发一个正式版 v0.1.62，让 0.1.61 的用户能自动更新到。执行内核的改动一行都不带。发布后把发版分支合回 main，main 从此包含 v0.1.62 的全部内容。

## 版本号：v0.1.62（U1 已定）

- 唯一来源是 `desktop/src-tauri/tauri.conf.json:4`，必须是三段 semver。「0.1.61.1」在读配置时就会报错。
- 带 `-` 的 tag 会被发成预发布版，不标 latest（`.github/workflows/release.yml:227-228`）。更新器只读 `releases/latest/download/latest.json`（`tauri.conf.json:49-50`），老用户永远收不到。
- 所以能让 0.1.61 自动收到的最小版本号就是 v0.1.62。执行内核那一版顺延为 v0.1.63（更正 E1）。

## 热修线怎么走（审查 §3 FR）

为什么不先合进 main 再挑回：F1、F2、F3 都改 `tool_loop.py`，K1、K3、K4、K8 会大改这个文件。热修提交先进 main 再 cherry-pick 回 v0.1.61，会冲突，或者发出一个没人测过的组合。所以：

1. **开线：** `git switch -c release/0.1.62 v0.1.61`，推送。先例：`release/0.1.58`、`release/0.1.59`、`release/0.1.60`。
2. **F 线的 PR 都开进 `release/0.1.62`：** 从它拉分支，PR 的 base 是它。H2 赶上热修，也开进来。别的提交一律不进，C1 也不进。
3. **F5a 先合。** 合了马上开一个 PR：head 是 `release/0.1.62`，base 是 main，里面只有 F5a。用 merge commit 合（仓库一直这么合），不要 squash。main 的 CI 从此恢复，C1、C5b 可以开工（C1 改 `task_service.py`，合并要等「怎么做」第 6 步合回之后，见 C1 卡）。
4. **冻结：** v0.1.62 发布、分支合回 main 之前，开进 main 的 PR 不许碰 `server/orchestrator/tool_loop.py`、`server/services/task_service.py`。K 线反正要等 M1B（审查 A4），不损失时间。
5. **CI：** `ci.yml` 对任何分支的 push 都跑，PR 只在目标是 main 时另跑（`ci.yml:3-6`）。所以开进发版分支的 PR 靠推送分支拿到 CI；合并后，发版分支的新提交也靠推送跑。
6. **能力清单冲突：** `docs/CAPABILITY_INVENTORY.md` 冲突时随便取一边，最后统一重新生成一次：`.venv/bin/python -m scripts.capability_inventory > docs/CAPABILITY_INVENTORY.md`。

## 改哪些文件（发版 PR，开进 `release/0.1.62`）

- `desktop/src-tauri/tauri.conf.json:4`：改成 `0.1.62`。版本号只在发版分支上改，随合回进 main。
- 新建 `docs/releases/v0.1.62.md`。文件名必须和 tag 一样，因为 `release.yml:230` 用它当正文。
- `docs/releases/v0.1.61.md`：在 `:12` 和 `:26` 后面各加一句更正，原句不改（见下）。
- `docs/CAPABILITY_INVENTORY.md`：重新生成。版本号和 `server/registry/*.py` 的哈希都在里面。
- 先例：`1a25f8b2` 只动了 3 个文件。

## 发布说明怎么写

- **每一句对用户的承诺，都要能对上测试。** 在文末加「How this is tested」一节，逐句写出测试名。
- **要写进去的内容：**
  - 命令能跑满自己的时限，不超过回合剩下的时间；超时也带着输出（F1）；
  - 「需要你核对」只留给真的可能对外的动作；读命令、执行前就被拒的动作不再要你核对（F2）；
  - 一个 MCP 工具的参数表不合供应商的要求，不再让整轮失败（F3）；
  - 终端里的 osascript 和 `shortcuts run`，按 F4a PR 给的要点写：
    - 列出会问的写法：直接写、带路径、经 `command`、`exec`、`xargs` 调用，每次都问，只给「这一次」；以前存的「总是」不再生效；
    - 写明还不会问的：脚本自己调用 osascript（例如 `python3 x.py`），v0.1.63 挡住；
    - **不能**写「终端里的 AppleScript 现在都会问」（更正 E10）；
  - 写文件不跟随指向工作区外的链接，也不改硬链接那头的文件（F4b）；
  - H2 赶上的话：Hands 没执行的动作不再要你核对。
- **两句更正，同时写进 v0.1.62 的说明和 `v0.1.61.md`：**
  - `:12` 后面：v0.1.61 说的「每个 AppleScript 每次都问」，只对 Hands 的 AppleScript 工具成立；终端里哪些写法会问，见 v0.1.62。原文由 F4a 的 PR 描述给出。
  - `:26` 后面（U1）：v0.1.61 说「更少的命令卡」放在 0.1.62，现在挪到 v0.1.63。
- 已经发布的 v0.1.61 GitHub Release 正文要不要改，先问用户。

## 怎么做（发版那几步）

1. **发版 PR：** F 线各卡都合进 `release/0.1.62` 之后，从它拉 `claude/0162-fr-hotfix-release`，做上面的改动，开 PR，由用户合。
2. **等 CI：** 发版分支最新提交（就是要打 tag 的 sha）的 CI 必须是 success，记下 run id。`release.yml:45-64` 会再查一遍，查不到就拒绝出包。
3. **冒烟：** ③Hands 在这个 sha 上跑 `scripts/hands_smoke.py`，结果写进发版 PR 的评论，打 tag 前给用户看。
4. **打 tag：** 用户说 go 之后，在这个 sha 上打带注解的 tag `v0.1.62` 并推送。`release.yml` 会出一个 draft。
5. **核 draft：** DMG、`latest.json`、签名、正文都核过，然后交给用户。**由用户点 Publish。** 发布后核对它成了 Latest。
6. **合回 main：** 开 PR，head 是 `release/0.1.62`，base 是 main，用 merge commit。
   - 描述里写第 2–5 步的 run id、冒烟结果和完成证据四项（`docs/sessions.md` §8）。
   - 冲突：能力清单按「热修线怎么走」第 6 条；版本号取 `0.1.62`（C5b 若已在 main 上改了版本来源，就按 C5b 的方式写 `0.1.62`）；其余两边都留。
   - 合了以后冻结解除。main 的版本号从此是 0.1.62，这是对的：main 包含 v0.1.62 的全部内容。v0.1.63 发版时再改。

## 顺序提醒（不是硬门槛）

- ⓪Plan 的 M1、M2 最好在 FR 发版之前合进 main（审查 §5）：发布后马上要用 M1 跑基线（M1B），用 M2 出周报。

## 不许碰

- 已经发布的 v0.1.61 Release 正文（要改，先问用户）；
- 已有的 tag：不删、不移；
- 文档站和 6 份 README 的版本同步：发布之后另开 PR，按先例走 `docs/sync-<tag>`；
- 任何 C、K、S 线的提交进发版分支；
- Bridge 文件。

## 验收

- `git log v0.1.61..release/0.1.62` 只有热修各卡和发版 PR 的提交，列给用户看。
- 发版 sha 上 CI 是 success（写 run id）；`release.yml` 的 run 也是 success（写 run id）。
- ③Hands 的冒烟结果打 tag 前已经给用户看过，并汇总进合回 main 的 PR。
- 发布说明里每一句承诺，都对得上一个在 CI 里跑过的测试名；两句更正都在。
- draft 核过：资产齐全，`latest.json` 里是 0.1.62，不是预发布版。由用户发布；发布后它是 Latest。
- 合回 main 之后，main 最新提交的 CI 是 success（写 run id）。

## 量级

产品代码改 1 行（版本号），外加发布说明和生成的清单。

## 风险与回退

- **合回 main 时冲突：** 这段时间 main 上合了 C5b、M1、M2 等。按「怎么做」第 6 步处理，合回 PR 的 CI 必须全绿才合。
- **打 tag 之前发现问题：** 在发版分支上 revert 对应的合并提交，再跑一遍 CI。
- **发布后发现问题：** 不删 tag、不撤 Release。修好之后要再发，只能用下一个三段版本号，执行内核会再顺延一位。先问用户。
- **留着的东西：** 冻结规则在合回 main 时解除。`release/0.1.62` 合回后保留，作为 v0.1.62 的来源记录（同 `release/0.1.58` 等），不再往里合东西。
