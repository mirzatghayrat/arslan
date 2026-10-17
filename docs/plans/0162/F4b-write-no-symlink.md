# F4b 写文件不跟随符号链接写到工作区外（R1）

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | 热修版 |
| 分级 | 必须 |
| 依赖 | F5a |
| 合并位置 | F 线，F5a 之后不分先后 |
| 推动的门槛 | §5.4「R1 回归测试」 |
| 分支 | `claude/0162-f4b-write-no-symlink` |
| 迁移号 | 无 |

## 目标

`write_file` 不能借工作区里的一个符号链接，把内容写到工作区外。比如一个名叫 `notes.txt` 的链接指向 `~/.zshrc`，写它就会写穿出去。

## 现状（亲核）

- **写入时只核对父目录。** `resolve_in_workspace(for_write=True)` 只解析父目录，再把最后一段原样接回去（`server/services/workspace_paths.py:70-82`）。
  - 最后一段如果是一个指向外面的链接，containment 检查照样通过。
  - 接着 `path.write_text` 会顺着链接写出去（`server/registry/file_tools.py:262`）。
- **密钥文件名检查看的也是链接自己的名字**（`workspace_paths.py:88-89`），不是目标的名字。
- **`edit_file` 不受影响**（按代码读，未跑）：它走 `for_write=False`，整条路径用 `resolve()` 解析后再查是否在工作区内（`workspace_paths.py:83-86`；`file_tools.py:285-304`）。下面给它也加一个测试，作为回归守卫。
- **来历：** 这段「看父目录」的写法来自 `d187800c`（#45，2026-08-20）。
- **已有测试：**
  - 读取经过链接被拒：`tests/server/test_workspace_paths.py:49-56`；
  - 写入经过链接目录被拒：`:89-94`。
  - 但没有「最后一段是链接」的写入测试。

## 改哪些文件

- **`server/services/workspace_paths.py`：** `for_write=True` 时，最后一段是符号链接就解析它的目标。
  - 要用 `is_symlink()` 判断，不能用 `exists()`：指向不存在目标的悬空链接，`exists()` 返回 False，可写入照样会在外面建出文件。
  - 解析出目标后：
    - 目标在工作区外，拒绝（`PathEscape`）；
    - 目标在工作区内，返回解析后的真实路径；
  - 密钥文件名检查改成两样都查：链接的名字和目标的名字。
- **`server/registry/file_tools.py`：** `WriteFileExecutor` 的写入（`:253-262`）改成用 `os.open(…, O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW)` 打开。
  - 这样检查完之后、写入之前，最后一段被人换成链接也写不出去，堵住这段时间差。
  - `EditFileExecutor` 的写入（`:304`）同样处理。
- **`docs/CAPABILITY_INVENTORY.md`：** rebase 后重新生成（`.venv/bin/python -m scripts.capability_inventory > docs/CAPABILITY_INVENTORY.md`）。`file_tools.py` 的哈希在里面。
- **测试：**
  - `tests/server/test_workspace_paths.py` 加单元测试；
  - 在 `file_tools` 一层加执行器测试（文件名由 PR 定）。

## 不许碰

- 读取路径的规则（`for_write=False` 那一支）；
- 「绿圈」默认可读文件夹的逻辑（`:99` 以下）；
- 其他写入入口：`run_command` 的沙箱归 S2a，检查点归 S3。

## 怎么做（要点）

1. 先写「验收」里的测试，看它们在 main 上失败（`edit_file` 那条除外）。
2. 先改 `resolve_in_workspace`，再改两处写入的打开方式。
3. 改完重新生成能力清单。

## 验收

所有测试都在临时目录里做：用一个替身文件代表 `~/.zshrc`，放在临时目录里、工作区外。

- `write_file` 写 `link.txt`（指向工作区外的替身）：
  - 被拒；
  - 替身内容不变。
- `edit_file` 改 `link.txt`：被拒，替身不变。这是回归守卫，在 main 上应已通过。
- `write_file` 写一个悬空链接（目标在工作区外、还不存在）：被拒，外面没有多出文件。
- `write_file` 写一个指向工作区**内**另一个文件的链接：写进那个文件，不报错。
- 指向外面 `.env` 的链接，哪怕链接自己叫 `notes.txt`：被拒，报 `SecretFile` 或 `PathEscape`。
- 用 `O_NOFOLLOW` 的单元测试：解析之后、写入之前，把文件换成指向外面的链接，写入失败，替身不变。
- 原有测试照旧通过：`test_write_to_new_file_judged_by_parent`、`test_make_parents_allows_missing_folders_inside`（`:78-108`）。

## 量级

产品代码约 20–30 行，外加测试。

## 风险与回退

- **有人故意用链接组织工作区：** 链接指向工作区外的文件夹，以后往这类链接写会被拒。
  - 这是要的行为。热修版的发布说明写一句。
- **`O_NOFOLLOW` 只管最后一段**，中间目录是链接的情况仍然靠父目录解析来挡（已有测试 `:89-94`）。
- **回退：** revert 合并提交。
