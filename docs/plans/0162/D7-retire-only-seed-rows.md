# D7 退役名单只删自带的技能，不删你导入的同名技能

| 项 | 内容 |
|---|---|
| 道 | ③Hands（⓪Plan 2026-10-21 分；`server/registry/` 不是 Hands 的文件，由 ②Main 审） |
| 版本 | v0.1.63 |
| 分级 | 必须（会悄悄删掉用户导入的技能；C9 退役更多技能之前一定要先修） |
| 依赖 | — |
| 合并位置 | 不进 K 线严格链，什么时候合都行；**C9 之前合** |
| 推动的门槛 | 用户数据不丢 |
| 迁移号 | 无 |
| 来源 | ④参谋的清理清单 §3（2026-10-21，读代码确认）；⓪Plan 在 main `5a97ff7f` 上核过；用户定先修（U13 第 3 条） |

## 发生了什么

- 开机时 `server/registry/seeder.py` 的 `_retire_removed_seeds`（`:63-69`）按名字删：`delete(SkillPack).where(SkillPack.key.in_(RETIRED_SKILL_KEYS))`，不看这一行是不是自带的。
- 导入技能时，`server/services/skill_import.py:71` 把 SKILL.md 里的 `name` 转成 key；导入的行 `category="imported"`。
- 退役名单（`seeder.py:27-38`）里有 notion、obsidian、google-workspace、powerpoint 这类常见名字。你导入一个叫这些名字的技能，下次重启它就没了；`data_dir/skill_scripts/<key>/` 里它带的脚本留成孤儿。
- 导入时「同名就拒」（`skill_import.py:274-275`）挡不住：退役的种子行开机时已经删了，同名的导入能进来，下次开机再被删掉。

## 改哪些文件

- `server/registry/seeder.py`：退役只删 seeder 自己种下的行。判断用行上已有的字段（`category` 不是 `imported`，以及其他用户来源的类别；`source_id` 为空）。用哪几个字段，③Hands 开工时核 `SkillPack` 的各种来源后定，写进 PR。
- 测试：新加一个测试文件。

## 不许碰

- 退役名单本身（C9 再加）；`skill_import` 的流程；工具集的退役（`RETIRED_TOOLSET_KEYS` 管的是 `Tool` / `Toolset`，另一回事）。

## 验收

- **测试：**
  - 导入一个 key 在退役名单里的技能，跑一次 `seed_registry_with`：这一行还在，它的脚本目录也还在；
  - 同一份数据库里，名单上的自带行照删；
  - mutation：去掉新加的条件，第一条测试要红。
- 完成证据四项写在 PR 里（`docs/sessions.md` §8）。

## 量级

产品代码约 10 行，加测试。

## 风险与回退

- **风险：** 漏判一种用户来源，那种行仍会被删。所以要列出 `SkillPack` 的全部写入点，各给一条测试。
- **回退：** revert 这个 PR。
