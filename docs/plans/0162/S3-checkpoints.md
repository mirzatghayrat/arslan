# S3 检查点：文件和命令的改动都能撤销

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.63 |
| 分级 | 必须（D3；领先路线 L13「检查点与回滚」v0.1.63 领先） |
| 依赖 | C1；F4b（恢复时用它的安全写法，热修版已带） |
| 合并位置 | S4b、S5 之前（问得少了，就得回得去：总计划 §3.2 第 3 条；U4「能撤销的不问」靠它）。最好也在 S2a-2 之前：之后工作文件夹里的删除不再出卡。和 F1（`RunCommandExecutor`）、K6（写文件工具）碰同一处，谁后合谁 rebase。不改 `server/orchestrator/tool_loop.py`、`server/services/task_service.py` |
| 推动的门槛 | §5.3 第 8 条；领先路线 L13 的证明（让它删掉一个文件夹再撤销，原样恢复）；附录 A「检查点与回滚」落后 → 领先 |
| 分支 | `claude/0162-s3a-checkpoints`（S3a）、`claude/0162-s3b-undo-ui`（S3b） |
| 迁移号 | 无（已复核）：索引就是数据目录里的清单文件；按对话列出、配额、重叠都靠扫清单（只留 7 天）；撤对话和事实用现有的表 |

## 目标

- **今天没有撤销。** `_snapshot_write` 存的是**新**内容，当作交付物，不是旧内容（`server/registry/file_tools.py:310-322`）。
- **每个回合（一个 run）第一次动手前，存一份，只存一次。**
  - 「动手」= 本轮第一次 `write_file`、`edit_file` 或 `run_command`。
  - 存工作文件夹的 APFS 克隆（几乎不占空间）。S4b 之后，允许的文件夹各存一份。
  - 排除能重新生成的目录：`node_modules`、`.venv` / `venv`、`__pycache__`、`build`、`dist`、`.next`、`target`、`DerivedData`、`.build`。撤销确认框写明这些没存。
  - 同一轮再动手，不再存：最早的那份为准。写到被排除目录里的文件，写前单独克隆这一个文件。
- **恢复有三种：** 只恢复文件、只恢复对话、两者都恢复。
  - 用户后来自己改过的文件，不覆盖，列出来；
  - 本轮新建的文件，撤销时移到废纸篓；
  - 检查点 7 天后清理。
- **界面：** 每条回复下面有「撤销本轮文件改动」。

## 改哪些文件

- **新增 `server/services/checkpoints.py`**：克隆、清单、收尾、恢复、配额、清理。
  - **位置：** `config.data_dir() / "checkpoints" / <run_id>/`，一个 `manifest.json` 加克隆。数据目录是受保护路径（`server/services/command_sandbox.py:93-94`），沙箱里的命令改不了。
  - **Time Machine：** 第一次建 `checkpoints/` 时把它排除出备份（`tmutil addexclusion` 的效果，即写 `com.apple.metadata:com_apple_backup_excludeItem` 扩展属性）。
  - **`ensure(run_id, roots)`：** 本轮第一次调用时克隆，之后什么都不做。run id 取 `execution_context.current_run_id()`，同 `file_tools.py:317`；取不到（`:318-319` 那种）就不存。
  - **克隆：** `clonefile(2)`，用 ctypes 调 libSystem，带 `CLONE_NOFOLLOW`；或者 `/bin/cp -c -R`。测过再定。
  - **跨卷（EXDEV）提前查：** 比较文件夹和数据目录的 `st_dev`。不在同一个卷上就不克隆，清单记 `other_volume`。
  - **非 APFS（ENOTSUP）和 Linux CI：** 单个文件 ≤50 MB 时普通复制；文件夹不存，清单记原因。
- `server/registry/file_tools.py`：写入前 `ensure`，写入后记指纹（大小、mtime、sha256；内容是我们自己写的，直接算）。
  - `WriteFileExecutor`：`:243-266`，在 `:260-262` 之间；`EditFileExecutor`：`:269-307`，在 `:302-304` 之间。
- `server/registry/executors.py:808`：`terminal_exec.run` 之前 `ensure`（`cwd` 在 `:793`）。
- `server/services/host_run.py:60-80`：回合结束时（正常、取消、出错都算，放 `finally`）调 `checkpoints.finish(run_id)`，记下「本轮结束时」每个被动过的路径的指纹。命令动过哪些文件，靠克隆和现状比对得出。
- `server/api/runs.py`：在现有 `/runs/{run_id}/…` 路由旁（例如 `:541`）加两个，不动 `server/main.py`：
  - `GET /runs/{run_id}/checkpoint`：有没有、改了几个、新建几个、跳过了什么（含 `too_large`、`other_volume`、排除的目录）、和哪些轮重叠、对话能不能恢复、几时过期；
  - `POST /runs/{run_id}/checkpoint/restore`，body `{what: "files" | "conversation" | "both"}`：返回恢复了的、移到废纸篓的、因用户改过没动的、失败的。
- **对话恢复：**
  - 删掉这一轮的 user 消息及之后的全部 `arslan_messages`（K2 合了以后，工具摘要也在里面）。
  - 只在这一轮还没被摘要折叠时能做：user 消息的 id 要大于最新摘要的 `up_to_message_id`（`server/orchestrator/memory.py:80`，列在 `server/db/models.py:159`）。
  - 对话里有回合或后台任务在跑时拒绝：`run_registry.active_for`（`server/services/run_registry.py:65`）和回合锁（`server/ws/arslan.py:44-51`）。
  - **这一轮抽到的事实一起撤：** 事实的来源里记着 run id（`server/services/memory_repository.py:144`；run id 在 `host_run.py:64-65` 绑定）。找出这些条目，以用户身份按 `MemoryRepository.delete_entry`（`:437`）的步骤删，只写 `source_kind="run_id"` 的 `MemorySuppression`，这一轮的消息就不会再把它们抽回来（`server/services/memory_history.py:11-26`）。
  - **不要照搬 `delete_entry` 的屏蔽范围：** 它按来源里的每个键写屏蔽，含 `conversation_id`（`:460-464`），而 `_not_suppressed` 一见到就拒（`:168-173`），整段对话以后再也抽不出事实。给它加一个参数，只屏蔽 run id。
- **网页：**
  - `web/src/components/reply/ReplyFooter.tsx`：在已有的菜单里（`:111` 的回放项旁）加「撤销本轮文件改动」。点了才取 `GET`，再弹确认框，三选一。
  - `web/src/components/settings/AdvancedSection.tsx` 工作文件夹输入框下（`:135-151`）：在另一个卷上时提示「这里的改动撤销不了」。
  - API 客户端类型；6 种语言的新文案按冲突协议加。C1c 没合时，同一个 PR 改 `web/src/__tests__/locale-parity.test.ts:300` 的计数。
- `docs/CAPABILITY_INVENTORY.md`：C5b 没合时，改了 `file_tools.py`、`executors.py` 就要重新生成。

## 不许碰

- Bridge 帧格式：可不可撤销走 REST，不往 `history` 或任何 WS 帧里加字段。
- 写文件的路径边界和符号链接规则（F4b）；`edit_file` 的新参数（K6）。
- Hands 在 App 里做的改动；这一轮学到的做法（lessons）。都不在本卡。

## 怎么做（要点）

1. **太大就跳过。** 克隆前数一遍（被排除的目录不数），最多 20,000 个文件或 5 GB（逻辑大小），超了停止计数，清单记 `too_large`；磁盘剩余不足 5 GB 也跳过。确认框写明哪几个文件夹没存。
2. **总配额：** 全部检查点「已经和原文件分开的部分」合计 ≤10 GB。克隆和原文件共用数据块，只有原文件后来被改、被删，克隆才真的占地方，按这些文件的大小估。超了从最旧的删起。
3. **恢复时逐个路径判断：**
   - 现状和「本轮结束时」的指纹一样：恢复成本轮之前的样子；
   - 不一样：用户后来动过，跳过并列出；
   - 本轮新建、现状没变的：移到废纸篓，复用 `capability_install.to_trash` 的思路（`server/services/capability_install.py:320-331`），不直接删。
   - 写回文件用 F4b 的安全写法：不跟随符号链接、拒绝硬链接、先写临时文件再 `os.replace` 换上。
4. **`.git` 整个恢复，或者不动。** 比对 `HEAD`、`index`、`refs/`、`packed-refs` 的指纹：和「本轮结束时」一样，就把现在的 `.git` 移进废纸篓、把克隆整个换上；不一样（用户后来又提交过）或有 `index.lock`，就不动，列出来。从不逐个文件恢复 `.git`。
5. **同一个文件夹里两个 run 同时动：** 模块在进程里记「哪些 run 正在动哪个文件夹」。`ensure` 时发现别的 run 也在动，两边清单都记 `overlap`。恢复时：还有 run 在动这个文件夹，拒绝恢复文件，等它结束；清单有 `overlap`，确认框列出那些轮，写明它们的改动会一起撤掉。
6. **从较早的一轮撤销**，就把这一轮及之后各轮的改动按倒序撤销；确认框列出会动到的轮数。
7. **清理：** 新建检查点时顺手做，最多每小时一次，写法同 `permission_store._prune`（`server/services/permission_store.py:172-182`）。超过 7 天的整个目录删掉。
8. **复制兜底的代码注释写删除条件：** 「CI 不再在 Linux 上跑这些测试、且不再支持非 APFS 卷时删」。

## 验收

- **测试（Linux CI 走复制兜底）：**
  - 写 / 改一个文件后撤销，内容和修改时间恢复；本轮新建的文件进废纸篓；
  - 一轮里先写文件、再跑三条命令：只克隆一次；`node_modules` 不进克隆；
  - 用户后来改过的文件不被覆盖，并且被列出来；
  - `rm -rf` 掉工作文件夹里的一个子文件夹，再撤销，原样恢复（L13 的证明）；
  - 本轮做了 `git commit`：撤销后 `git log`、`git status` 回到之前，`git fsck` 通过；用户后来又提交过：`.git` 不动，并被列出；
  - 两个 run 同时动一个文件夹：一个还在跑时恢复被拒；都结束后，确认框数据列出重叠的轮；
  - 跨卷：清单记 `other_volume`，`GET` 返回它；超过上限、超过总配额时的行为如上；
  - 恢复写回时目标被换成指向外面的符号链接：写入失败，外面的文件不变；
  - 只恢复对话：这一轮的消息不见了，文件不动；这一轮抽到的事实被删，重新抽取也不会回来；同一对话下一轮的新事实照常保存；被摘要折叠过的轮，不让恢复对话；
  - 超过 7 天的检查点被清理。
- **macOS 测试**（`macos` 标记，`pyproject.toml:212`）：真的走 clonefile 克隆文件和文件夹；`checkpoints/` 带 Time Machine 排除属性。
- **手动：** §5.3 第 8 条：让它改一个文件，再点「撤销本轮文件改动」，文件恢复原样。

## 量级

- 默认拆两个 PR：
  - S3a 服务端：存、恢复文件、`.git`、配额、重叠、清理、API，约 +550 行；
  - S3b：网页按钮、设置页提示、「恢复对话」（含撤事实），约 +250 行。
- 比原来的 +500 至 +650 多，多在 `.git`、跨卷、重叠、配额和撤事实。

## 风险与回退

- **对话恢复只在 Mac 上生效。** iPhone 上已经同步过去的消息不会被撤回：Bridge 没有「撤回消息」的帧，本版不加。确认框里写明。
- **撤销不了的东西：** 沙箱外的命令改动了文件夹以外的文件；发出去的信、推上去的代码；Hands 在 App 里做的事；被排除的目录；另一个卷上的文件夹。确认框只承诺「存过的文件夹和本轮写过的文件」。
- **克隆的代价随文件数增长。** 每次克隆要计时，超过约 2 秒就在清单里记下，PR 里贴大文件夹的实测。
- **K2 会把回合后的工作挪出回合锁。** 抽事实若因此丢了 run id，撤事实就失效。本卡的测试守住它，K2 改动时要跑。
- **留着的兜底：** 文件复制兜底长期保留，删除条件：CI 不再在 Linux 上跑这些测试、且 Arslan 不再支持非 APFS 卷。
- **回退：** 按 PR revert，S3b 先退。旧代码不读检查点目录，留着不影响运行，只占磁盘；清理代码也随 PR 回退了，所以要手动删数据目录里的 `checkpoints/`。
