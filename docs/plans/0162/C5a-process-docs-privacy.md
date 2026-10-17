# C5a 过程文档移到存档分支；从文件里删隐私段落

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.63 |
| 分级 | 应该 |
| 依赖 | —。最好在 ⓪Plan 把本轮计划合进 main 之后再做（README §6 第 3 步），这样「保留」清单是全的 |
| 合并位置 | 随时。不碰代码和 K 线热点。<br>• 也改 `.gitignore` 的是 C2f；<br>• 也改 `docs/specs/2026-10-11-0161-smooth.md` 的是 C4（只加两行注记）。<br>后合的 rebase |
| 推动的门槛 | 无直接门槛；净减约 3.08 万行文档。兑现 D13：main 只留当轮计划和代码引用的 spec。按「仍待定」那条，先把隐私内容从文件里删掉 |
| 分支 | `claude/0162-c5a-process-docs`；存档分支 `archive/process-docs-2026-10`（推送，永不合并） |
| 迁移号 | 无 |

## 目标

1. 没有任何地方引用的过程文档，挪到一个只推送、不合并的存档分支，从 main 删掉。
2. 留在 main 的文件里，删掉私聊引用、数据库摘录、本机路径。
3. 要不要改写 git 历史，**本卡不做**：用户还没定（决定记录「仍待定」第 1 条）。
4. App Store Connect 相关文件不动（「仍待定」第 2 条）。

## 「没人引用」怎么算（可复现，不手列）

- **过程文档**：`docs/specs`、`docs/plans`、`docs/companion`、`docs/research`、`docs/design` 下的文件。
- **算作「引用」**：下列文件里出现这份文档的路径或文件名，就算它被引用。
  - 代码：`server`、`arslan`、`web/src`、`desktop`、`packaging`、`scripts`、`evals`；
  - 测试：`tests`；
  - CI：`.github`；
  - 文档站和发布说明：`docs-site`、`docs/releases`；
  - 公开的说明文档：`README*.md`、`CONTRIBUTING.md`、`SECURITY.md`、`CLAUDE.md`、`docs/sessions.md`；
  - `docs/` 根目录的 `*.md`、`*.html`，以及 `docs/docs`、`docs/privacy`、`docs/support`、`docs/marketing`。
- **一律保留**：
  - `docs/plans/2026-10-17-0162-*.md`、`docs/plans/0162/**`；
  - 任何被上面引用的文件。

在仓库根目录跑下面这段，输出就是要存档的清单。把输出原样贴进 PR：

```bash
CITERS=(server arslan web/src desktop packaging scripts tests evals .github docs-site docs/releases
        'README*.md' CONTRIBUTING.md SECURITY.md CLAUDE.md docs/sessions.md
        ':(glob)docs/*.md' ':(glob)docs/*.html' docs/docs docs/privacy docs/support docs/marketing)
for f in $(git ls-files docs/specs docs/plans docs/companion docs/research docs/design); do
  case "$f" in docs/plans/2026-10-17-0162-*|docs/plans/0162/*) continue;; esac
  b=$(basename "$f")
  git grep -q -F -e "$f" -e "$b" -- "${CITERS[@]}" || echo "$f"
done
```

- 起草这张卡时，在 `fb6d7230` 加本轮计划上跑了一次：101 个文件，30,822 行，和 reduce-proposal §4.5 的数字一致。
- 实施时以当天 main 上跑出来的为准。

`docs/assets` 用同一个思路：按文件名搜，排除 `docs/assets` 自己和上面五个过程文档目录。
- 起草时跑出来 39 个、约 3.2 MB：`site` 20 个，`icons` 10 个，`btn` 6 个，根目录 3 个。
- 只做了字面搜索。删之前，在 `docs/index.html` 和 `docs-site` 里看一眼有没有拼接出来的文件名（未核）。

## 改哪些文件

存档分支（先做）：
1. 从当天的 main 切出 `archive/process-docs-2026-10`。
2. 在存档分支上，对清单里的文件跑一次隐私扫描，并提交一次清理：

   ```bash
   git grep -n -E "/Users/|/home/|@gmail\.com|用户原话|The user's words" -- <清单里的文件>
   ```

   - 起草时有 5 个文件命中本机路径或邮箱，9 个命中「用户原话」类引用。
   - 命中的段落删掉。删不干净的文件不进存档，只在 main 上删。
3. 推送存档分支，把它的提交号写进 PR 描述。

main 上的 PR：
- `git rm` 清单里的过程文档，以及没人引用的 `docs/assets` 文件。
- `docs/specs/2026-10-11-0161-smooth.md`：它被 `web/src/__tests__/card-words.test.tsx` 引用，所以留在 main。删这些段落：
  - `:3-6` 的状态行，已经过时；
  - `:8-12` 的用户原话；
  - §0.1、§0.2 的数据库摘录（`:42-127`）。只留一句汇总，例如「0.1.61 之前的卡片统计见存档分支」；
  - `:14-18` 的截图描述，按同一条扫描命令判断。
- 对其余留在 main 的过程文档，跑同一条隐私扫描。命中的从文件里删，在 PR 描述里逐个列出。
- `.gitignore:44-50` 的注释：它说「设计 spec、计划……不随开源发布，所以忽略」，可 `docs/specs`、`docs/plans` 明明在提交。
  - 改成如实描述：这几行只忽略本地工具目录 `.superpowers`、`.omm`、`docs/superpowers`；
  - 当轮计划在 `docs/plans`，要提交。
- `CONTRIBUTING.md:159` 有同样的过时说法：「specs and plans … are not published with the open-source release」。一并改成如实描述。

## 不许碰

- git 历史：不 `filter-repo`，不 force-push main。
- 代码、测试、CI。
- `docs/releases/**`：只有发版 PR 写，见 `docs/sessions.md` §3。
- 本轮的计划文件和 `docs/plans/0162/**`。
- App Store Connect 相关的任何文件。

## 怎么做（要点）

1. 先跑上面的清单命令。再抽查 5 个被判「没人引用」的文件，确认确实没有入口；如果某个文件其实被代码按章节号引用，就留下。
2. 代码注释里只写了「spec §A4」、没写文件名的引用，命令找不到。这类注释在存档以后指向存档分支，所以 PR 描述里要写清存档分支名。
3. 按顺序：存档分支先推，main 的 PR 后合。
4. `docs/plans/**` 归 ⓪Plan（README §4）。清单里 `docs/plans` 下的文件和对 `docs/specs` 的段落删改，开 PR 时请 ⓪Plan 审。

## 验收

- 存档分支在远端可见；`git ls-tree -r --name-only archive/process-docs-2026-10` 列出清单里的全部文件，扫描排除的除外。
- 在 main 上重跑清单命令，输出为空。
- 隐私扫描命令在 main 的 `docs/` 下无命中，`docs/plans/0162/**` 里作为命令示例出现的模式除外。
- CI 绿，贴 run id。`card-words.test.tsx` 照旧通过：它引用的那份 spec 还在。

## 量级

产品代码 0 行。文档约 −3.08 万行，素材约 −3.2 MB。

## 风险与回退

- **风险：** 存档分支是公开仓库里的一个 ref，里面的内容等于再公开一次。所以清理要在存档分支上先做，而不是只在 main 上做。
  - git 历史里的旧版本仍在，要不要改写历史等用户决定。
- **风险：** 某份被删的 spec 其实是某段代码的设计依据。存档分支可以随时取回；需要时由 ⓪Plan 把它挪回 `docs/specs`。
- **回退：** revert main 上的 PR 即可。存档分支留着无害。
