# F4b 写文件不借链接写到工作区外（R1）

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.62 |
| 分级 | 必须 |
| 依赖 | F5a |
| 合并位置 | 合进 `release/0.1.62`，F5a 之后不分先后。发版后随分支合回 main；S3 恢复文件时用本卡的写法 |
| 推动的门槛 | §5.4「R1 回归测试」 |
| 分支 | `claude/0162-f4b-write-no-symlink`（从 `release/0.1.62` 拉，PR 的 base 是 `release/0.1.62`） |
| 迁移号 | 无 |

## 目标

`write_file` 和 `edit_file` 不能借工作区里的链接，把内容写到工作区外。三种情形都要挡：

- **符号链接：** 一个名叫 `notes.txt` 的链接指向 `~/.zshrc`；
- **硬链接**（审查 §3）：工作区里的 `notes.txt` 和 `~/.zshrc` 是同一个文件，`resolve()` 和 `O_NOFOLLOW` 都看不出来；
- **时间差**（审查 §3）：检查完路径之后才建上级目录、才打开文件，中间有人把某一段换成链接。

另外，新建的文件不带可执行位。

## 现状（亲核）

- **写入时只核对父目录。** `resolve_in_workspace(for_write=True)` 只解析父目录，再把最后一段原样接回去（`server/services/workspace_paths.py:70-82`）。最后一段如果是一个指向外面的链接，检查照样通过，接着 `path.write_text` 顺着链接写出去（`server/registry/file_tools.py:262`）。
- **密钥文件名检查看的也是链接自己的名字**（`workspace_paths.py:88-89`），不是目标的名字。
- **`edit_file` 挡得住符号链接**（按代码读，未跑）：它走 `for_write=False`，整条路径 `resolve()` 后再查（`workspace_paths.py:83-86`；`file_tools.py:285-304`）。**但挡不住硬链接**：硬链接的路径本身就在工作区里，`write_text`（`:304`）原地改的是同一个文件。
- **先查、后建目录、再写：** `WriteFileExecutor` 先解析路径（`file_tools.py:253`），再 `mkdir(parents=True)`（`:257`），最后写（`:262`）。
- **来历：** 这段「看父目录」的写法来自 `d187800c`（#45，2026-08-20）。
- **已有测试：** 读取经过链接被拒（`tests/server/test_workspace_paths.py:49-56`）；写入经过链接目录被拒（`:89-94`）。没有「最后一段是链接」和硬链接的写入测试。

## 改哪些文件

- **`server/services/workspace_paths.py`：** `for_write=True` 时，最后一段是符号链接就解析它的目标。
  - 用 `is_symlink()` 判断，不能用 `exists()`：悬空链接的 `exists()` 返回 False，可写入照样会在外面建出文件。
  - 目标在工作区外：拒绝（`PathEscape`）；在工作区内：返回解析后的真实路径。
  - 密钥文件名检查两样都查：链接的名字和目标的名字。
- **`server/registry/file_tools.py`：** `write_file` 和 `edit_file` 的写入（`:253-262`、`:304`）换成一个共用的安全写法：
  1. 建好上级目录之后，**再解析一次路径**，确认仍在工作区内（堵住建目录的时间差）；
  2. 在同一个目录里新建临时文件：`os.open(…, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0o666)`。macOS 上再加 `O_NOFOLLOW_ANY`（macOS 11+，路径里任何一段是链接都打不开）；没有这个常量的系统（Linux CI）只靠第 1 步；
  3. 写完、`fsync`，再 `os.replace` 到目标。`os.replace` 换掉的是目录项本身，不顺着链接写，硬链接那头的文件也就不会被改（审查 §3）。
  - 模式：新文件 `0o666`，交给 umask 处理，不带可执行位（审查 §3：`os.open` 默认是 0o777）。覆盖已有文件时，沿用原文件的权限位。
  - 写失败时删掉临时文件，原文件不动。
- **`docs/CAPABILITY_INVENTORY.md`：** rebase 到 `release/0.1.62` 后重新生成（`.venv/bin/python -m scripts.capability_inventory > docs/CAPABILITY_INVENTORY.md`）。`file_tools.py` 的哈希在里面（`:123`）。冲突时随便取一边，再重新生成，不手工合。
- **测试：** `tests/server/test_workspace_paths.py` 加单元测试；在 `file_tools` 一层加执行器测试（文件名由 PR 定）。

## 不许碰

- 读取路径的规则（`for_write=False` 那一支）；
- 「绿圈」默认可读文件夹的逻辑（`workspace_paths.py:99` 以下）；
- 其他写入入口：`run_command` 的沙箱归 S2a，检查点归 S3。

## 怎么做（要点）

1. 先写「验收」里的测试，看它们在 v0.1.61 上失败（`edit_file` 走符号链接那条除外）。
2. 先改 `resolve_in_workspace`，再把两处写入换成共用的安全写法。
3. 改完重新生成能力清单。
4. `O_NOFOLLOW_ANY` 和「再解析一次」两样都一直做，不是二选一，所以没有要删的旧路径。

## 验收

所有测试都在临时目录里做：用一个替身文件代表 `~/.zshrc`，放在临时目录里、工作区外。

- `write_file` 写 `link.txt`（符号链接，指向工作区外的替身）：被拒；替身内容不变。
- `edit_file` 改 `link.txt`：被拒，替身不变。这是回归守卫，在 v0.1.61 上应已通过。
- `write_file` 写一个悬空链接（目标在工作区外、还不存在）：被拒，外面没有多出文件。
- `write_file` 写一个指向工作区**内**另一个文件的链接：写进那个文件，不报错。
- 指向外面 `.env` 的链接，哪怕链接自己叫 `notes.txt`：被拒，报 `SecretFile` 或 `PathEscape`。
- **硬链接：** `os.link(替身, 工作区/notes.txt)`。`write_file` 和 `edit_file` 各写一次：替身内容不变；工作区里的 `notes.txt` 是新内容。
- **时间差：** 解析之后、写入之前，把文件或上级目录换成指向外面的链接（在测试里替换掉建目录或打开那一步来插入）：写入失败，替身不变，外面没有多出文件。
- **权限：** 新建的文件没有可执行位（`mode & 0o111 == 0`）；覆盖一个原本 `0o755` 的文件后仍是 `0o755`。
- 原有测试照旧通过：`test_write_to_new_file_judged_by_parent`、`test_make_parents_allows_missing_folders_inside`（`:78-108`）。
- `O_NOFOLLOW_ANY` 那条测试只在 macOS 上跑，打 macOS 标记；「再解析一次」那条在 Linux 上也跑。

## 量级

产品代码约 50–70 行，外加测试。

## 风险与回退

- **有人故意用链接组织工作区：** 链接指向工作区外的文件，以后往这类链接写会被拒。这是要的行为，v0.1.62 的发布说明写一句。
- **硬链接从此被「拆开」：** 写入后，工作区里的文件是新文件，工作区外那头保持原样。这也是要的行为，发布说明一并写。
- **`os.replace` 会换掉文件的 inode：** 文件的扩展属性、别的进程打开着的句柄看到的是旧文件。编辑器和同步工具普遍这么写，可以接受。
- **建目录时的时间差只能事后发现：** 如果有人在 `mkdir` 中途把一段换成链接，外面可能多出空目录，但写入会被第 1、2 步拦下，内容写不出去。
- **留着的东西：** 无。
- **回退：** 在 `release/0.1.62` 上 revert 合并提交。
