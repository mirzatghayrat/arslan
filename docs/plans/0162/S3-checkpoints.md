# S3 检查点：文件和命令的改动都能撤销

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | 0.1.62 |
| 分级 | 必须（D3；领先路线 L13「检查点与回滚」0.1.62 领先） |
| 依赖 | C1 |
| 合并位置 | S4 之前（问得少了，就得回得去：总计划 §3.2 第 3 条）。最好也在 S2a 之前：S2a 之后，工作文件夹里的删除不再出卡。和 F1（改 `RunCommandExecutor`）、F4b 与 K6（改写文件工具）碰同一处，谁后合谁 rebase |
| 推动的门槛 | §5.3 第 8 条；领先路线 L13 的证明（让它删掉一个文件夹再撤销，原样恢复）；附录 A「检查点与回滚」落后 → 领先 |
| 分支 | `claude/0162-s3-checkpoints` |
| 迁移号 | 无：用数据目录里的清单文件。若最后非要建表，写「需要 1 个迁移号（向 ②Main 申请）」 |

## 目标

- **今天没有撤销。** `_snapshot_write` 存的是**新**内容，当作交付物，不是旧内容（`server/registry/file_tools.py:310-322`）。
- **每一轮（一个 run）在动文件之前存一份：**
  - `write_file` / `edit_file` 之前：给要动的那个文件做 APFS 克隆（clonefile，几乎不占空间）；文件原来不存在，就记「本轮新建」。
  - 每条 `run_command` 之前：克隆整个工作文件夹。
- **恢复有三种：** 只恢复文件、只恢复对话、两者都恢复。
  - 用户后来自己改过的文件，不覆盖，列出来；
  - 本轮新建的文件，撤销时移到废纸篓；
  - 检查点 7 天后清理。
- **界面：** 每条回复下面有「撤销本轮文件改动」。

## 改哪些文件

- **新增 `server/services/checkpoints.py`**：克隆、清单、收尾、恢复、清理。
  - **位置：** `config.data_dir() / "checkpoints" / <run_id>/`，里面一个 `manifest.json`，加上克隆出来的文件和文件夹。
  - 数据目录本来就是受保护路径（`server/services/command_sandbox.py:93-94`），沙箱里的命令改不了检查点。
  - **克隆：** `clonefile(2)`，用 ctypes 调 libSystem，带 `CLONE_NOFOLLOW`（不跟随符号链接，和 F4b 一致）；或者 `/bin/cp -c -R`。二选一，测过再定。
  - **克隆不了时**（EXDEV：不在同一个卷；ENOTSUP：不是 APFS；Linux CI）：单个文件 ≤50 MB 时普通复制；文件夹不存，清单里记下原因。
- `server/registry/file_tools.py`：写入前存一份，写入后记下指纹（大小、mtime、sha256；内容是我们自己写的，直接算）。
  - `WriteFileExecutor`：`:243-266`，在 `:260-262` 之间；
  - `EditFileExecutor`：`:269-307`，在 `:302-304` 之间。
- `server/registry/executors.py:808`：`terminal_exec.run` 之前克隆工作文件夹（`cwd`，`:793`）。
- `server/services/host_run.py:60-80`：回合结束时（正常、取消、出错都算，放 `finally`）调 `checkpoints.finish(run_id)`，记下「本轮结束时」每个被动过的路径的指纹。
  - 命令动过哪些文件，靠克隆和现状比对得出。
  - 有了这份指纹，恢复时才分得清：哪些是这一轮改的，哪些是用户后来改的。
- `server/api/runs.py`：在现有 `/runs/{run_id}/…` 路由旁（例如 `:541`）加两个。不用动 `server/main.py`。
  - `GET /runs/{run_id}/checkpoint`：有没有、改了几个文件、新建几个、跳过了什么、对话能不能恢复、几时过期；
  - `POST /runs/{run_id}/checkpoint/restore`，body `{what: "files" | "conversation" | "both"}`：返回恢复了的、移到废纸篓的、因为用户改过而没动的、失败的。
- **对话恢复：**
  - 删掉这一轮的 user 消息及之后的全部 `arslan_messages`（K2 合了以后，工具摘要也在里面）。
  - **只在这一轮还没被摘要折叠时才能做：** user 消息的 id 要大于最新摘要的 `up_to_message_id`（`server/orchestrator/memory.py:80`，列在 `server/db/models.py:159`）。
  - 对话里有回合或后台任务在跑时拒绝：`run_registry.active_for`（`server/services/run_registry.py:65`），以及回合锁（`server/ws/arslan.py:44-51`）。
- **网页：**
  - `web/src/components/reply/ReplyFooter.tsx`：在已有的菜单里（`:111` 的回放项旁）加「撤销本轮文件改动」。点了才去取 `GET`，再弹确认框，三选一。
  - API 客户端类型；6 种语言的新文案按冲突协议加。C1c 没合时，同一个 PR 改 `web/src/__tests__/locale-parity.test.ts:300` 的计数。
- `docs/CAPABILITY_INVENTORY.md`：C5b 没合时，改了 `file_tools.py`、`executors.py` 就要重新生成。

## 不许碰

- Bridge 帧格式：可不可撤销走 REST，不往 `history` 或任何 WS 帧里加字段。
- 写文件的路径边界和符号链接规则（F4b）；`edit_file` 的新参数（K6）。
- Hands 在 App 里做的改动：不在本卡范围。

## 怎么做（要点）

1. **每条路径以本轮最早的那份为准。** 同一轮里先写文件、后跑命令，恢复时用写之前那份。
2. **工作文件夹太大就跳过。**
   - 上限：每次克隆前数一遍，最多 20,000 个文件或 5 GB（逻辑大小），超了就停止计数；
   - 磁盘剩余空间不足 5 GB 也跳过；
   - 超过上限时，这条命令前不存，清单里记 `too_large`。撤销确认框里写明「有 N 条命令前没存检查点（文件夹太大）」。
3. **恢复时逐个路径判断：**
   - 现状和「本轮结束时」的指纹一样：恢复成本轮之前的样子；
   - 不一样：说明用户后来动过，跳过并列出；
   - 本轮新建、现状没变的：移到废纸篓。废纸篓的做法复用 `capability_install.to_trash` 的思路（`server/services/capability_install.py:320-331`），不直接删。
4. **从较早的一轮撤销**，就把这一轮及之后各轮的改动按倒序撤销；确认框列出会动到的轮数。
5. **清理：** 新建检查点时顺手做，最多每小时一次。写法同 `permission_store._prune`（`server/services/permission_store.py:172-182`）。超过 7 天的整个目录删掉。

## 验收

- **测试（Linux CI 走复制回落）：**
  - 写 / 改一个文件后，撤销，内容和修改时间恢复；
  - 本轮新建的文件进废纸篓；
  - 用户后来改过的文件不被覆盖，并且被列出来；
  - `rm -rf` 掉工作文件夹里的一个子文件夹，再撤销，原样恢复（L13 的证明）；
  - 超过上限时跳过，并在清单里记下；
  - 只恢复对话：这一轮的消息不见了，文件不动；被摘要折叠过的轮，不让恢复对话；
  - 超过 7 天的检查点被清理。
- **macOS 测试**（`macos` 标记，`pyproject.toml:212`）：真的走 clonefile 克隆文件和文件夹。
- **手动：** §5.3 第 8 条：让它改一个文件，再点「撤销本轮文件改动」，文件恢复原样。

## 量级

- 产品代码约 +500 至 +650 行：服务端约 400，网页约 150。
- 超过 800 行就拆：S3a 服务端（存、恢复文件、清理、API），S3b 网页按钮和「恢复对话」。

## 风险与回退

- **对话恢复只在 Mac 上生效。** iPhone 上已经同步过去的消息不会被撤回：Bridge 没有「撤回消息」的帧，本版不加。确认框里写明。
- **撤销不了的东西：**
  - 沙箱外的命令改动了工作文件夹以外的文件；
  - 发出去的信、推上去的代码；
  - Hands 在 App 里做的事。
  - 确认框只承诺「工作文件夹和本轮写过的文件」。
- **克隆的代价随文件数增长。** 每次克隆要计时；一轮里累计超过约 2 秒，后面的命令就不再克隆，清单里记下。
- **回退：** 整个 PR revert。旧代码不读检查点目录，留着不影响运行，只占磁盘；清理代码也随 PR 回退了，所以要手动删数据目录里的 `checkpoints/`。
