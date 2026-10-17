# FR 发热修版

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | 热修版 |
| 分级 | 必须 |
| 依赖 | F5a、F1、F2、F3、F4a、F4b；H2 若已合也带上 |
| 合并位置 | 热修线最后 |
| 推动的门槛 | §5.4「CI 全绿」与「发布说明逐句对测试」 |
| 分支 | 发版分支 `release/<版本>`；记录发版并把说明写回 main 的文档 PR 用 `claude/0162-fr-hotfix-release` |
| 迁移号 | 无（热修线不带迁移） |

## 目标

把热修线的几个修复，从 v0.1.61 单独发成一个正式版，让 0.1.61 的用户能自动更新到。执行内核的改动一行都不带。

## 改哪些文件

**发版分支 `release/<版本>` 上：**

- cherry-pick 进来的热修各卡；
- `desktop/src-tauri/tauri.conf.json:4`（版本号）；
- 新建 `docs/releases/v<版本>.md`；
- 在 `docs/releases/v0.1.61.md:12` 后面加一句更正；
- `docs/CAPABILITY_INVENTORY.md`（重新生成）。

**记录用的文档 PR**（第 5 步，进 main）：只有上面两份发布说明。

## 版本号（用户定；更正 E1）

**规矩：**

- 唯一来源是 `desktop/src-tauri/tauri.conf.json:4`。
- 必须是三段 semver。「0.1.61.1」在读配置时就会报错。
- 带 `-` 的 tag 会被发成预发布版，不标 latest（`.github/workflows/release.yml:227-228`）。而更新器只读 `releases/latest/download/latest.json`（`tauri.conf.json:49-50`），所以老用户永远收不到。
- **结论：** 能让 0.1.61 自动收到的最小版本号是 **v0.1.62**。用了它，执行内核那一版顺延为 v0.1.63（见 E1）。

**用户定号之前，不建发版分支，也不改版本号。** 定号之后，计划和 README 里的叫法由 ⓪Plan 统一改，不在本 PR 里改。

## 怎么做（要点）

1. **从 tag 拉分支：** `git switch -c release/<版本> v0.1.61`。先例：0.1.58 就是从 `release/0.1.58` 发的。
2. **按合并的先后顺序，cherry-pick 热修各卡在 main 上的合并提交**（`git cherry-pick -m 1 <合并提交>`）。
   - 每一张都要带上：F5a、F1、F2、F3、F4a、F4b，以及已合的 H2。少了 F5a，发版分支上的 CI 照样红。
   - 别的提交一律不挑，C1 也不挑。
   - 热修各卡如果是在 C1 合进 main 之后写的，它们的测试可能依赖 C1 改过的 conftest，挑到 v0.1.61 上会冲突或失败。
   - 遇到这种情况，在发版分支上做最小的适配，并记进第 5 步的 PR。不能把 C1 一起带进来。
3. **发版提交**（先例：`1a25f8b2` 只动了 3 个文件）：
   - `tauri.conf.json:4` 改成新版本号；
   - 新建 `docs/releases/v<版本>.md`。文件名必须和 tag 一样，因为 `release.yml:230` 用它当正文；
   - 重新生成能力清单：`.venv/bin/python -m scripts.capability_inventory > docs/CAPABILITY_INVENTORY.md`。版本号和 `server/registry/*.py` 的哈希都在里面。
4. **发布说明怎么写：**
   - 每一句对用户的承诺，都要能对上测试。做法是在文末加「How this is tested」一节，逐句写出测试名。
   - 要写进去的内容：
     - 命令能跑满自己的时限（F1）；
     - 「需要你核对」只留给真的对外的动作（F2）；
     - 一个 MCP 工具的参数表不合供应商的要求，不再让整轮失败（F3）；
     - 终端里的 osascript 和 `shortcuts run` 只给「这一次」，已存的「总是」不再生效（F4a）；
     - 写文件不跟随指向工作区外的链接（F4b）。
   - 另外要写一句更正：v0.1.61 说的「每个 AppleScript 每次都问」，只对 Hands 的 AppleScript 工具成立。
   - 同一句更正也加在 `docs/releases/v0.1.61.md:12` 后面，原句不改。原文由 F4a 的 PR 描述给出。
5. **开记录用的 PR：** 从 main 拉 `claude/0162-fr-hotfix-release`，只放两样文档：`docs/releases/v<版本>.md`、`v0.1.61.md` 的那句更正（先例 `9051ee05`）。
   - 下面几步的 run id 和冒烟结果，都记在这个 PR 的描述里。
   - 这个 PR 发布之后再合。main 上的版本号留到执行内核那一版再改。
6. **推送发版分支，等 CI。** `ci.yml` 对任何分支的 push 都会跑。要求同一个 sha 上 CI 是 success，并记下 run id。`release.yml:45-64` 会再查一遍，查不到就拒绝出包。
7. **冒烟：** ③Hands 在这个 sha 上跑 `scripts/hands_smoke.py`，结果记进第 5 步的 PR。
8. **打 tag：** 用户说 go 之后，在这个 sha 上打带注解的 tag `v<版本>` 并推送。`release.yml` 会出一个 draft。
9. **核 draft：** DMG、`latest.json`、签名、正文都核过，然后交给用户。**由用户点 Publish。** 发布后核对它成了 Latest，再请用户合第 5 步的 PR。

## 不许碰

- main 上的 `tauri.conf.json`（见第 5 步）；
- 已经发布的 v0.1.61 Release 正文（要改，先问用户）；
- 已有的 tag：不删、不移；
- 文档站和 6 份 README 的版本同步：发布之后另开 PR，按先例走 `docs/sync-<tag>`；
- 任何 C、K、S 线的提交；
- Bridge 文件。

## 验收

- 发版分支的 diff 只有热修各卡的内容，外加版本号、发布说明和能力清单。用 `git log v0.1.61..release/<版本>` 列给用户看。
- 发版 sha 上 CI 是 success（写 run id）；`release.yml` 的 run 也是 success（写 run id）。
- ③Hands 的冒烟结果已经记进第 5 步的 PR。
- 发布说明里每一句承诺，都对得上一个在 CI 里跑过的测试名。
- draft 核过：资产齐全，`latest.json` 里是新版本号，不是预发布版。由用户发布；发布后它是 Latest。

## 量级

产品代码改 1 行（版本号），外加发布说明和生成的清单。cherry-pick 的提交量由热修各卡决定。

## 风险与回退

- **cherry-pick 冲突或测试不合：** 只在发版分支上做最小适配，记进第 5 步的 PR，并在 main 上核对同样的行为有测试。
- **发布后发现问题：** 不删 tag、不撤 Release。修好之后再发下一个三段版本号。
- **打 tag 之前发现问题：** 在发版分支上 revert 对应的 cherry-pick，再跑一遍 CI。
