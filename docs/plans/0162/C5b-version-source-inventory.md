# C5b 唯一的版本来源；能力清单只在发版时生成

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.63 |
| 分级 | 应该 |
| 依赖 | —。C2d 合了以后，`arslan/__init__.py` 的 `__version__` 就没人读了，本卡直接删它 |
| 合并位置 | 随时，**越早越好**：合了以后，C2a、C3、S1、S3、S5 都不用再为 `docs/CAPABILITY_INVENTORY.md` 重新生成、解冲突。`server/main.py` 只改 `:445` 一行 |
| 推动的门槛 | 无直接门槛。间接：§5.4 工程门槛里的「发版流程」更稳；并行 PR 不再在一个生成文件上反复冲突（`docs/sessions.md` §3 已经写了「C5b 合并后，只在发版 PR 里生成」） |
| 分支 | `claude/0162-c5b-version-inventory` |
| 迁移号 | 无 |

## 目标

1. **版本号只有一个来源**：`desktop/src-tauri/tauri.conf.json:4`。
   - 服务端已经从它读：`server/config.py:44-62` 的 `_app_version()`，结果存在 `settings.app_version`（`:90`、`:174`）；
   - 发版流程也已经核对 tag 和它是否一致：`.github/workflows/release.yml:206-208`。
   - 本卡把剩下几处写死的「0.1.0」理顺。
2. **能力清单只在发版时生成**。现在 `tests/test_capability_inventory.py:4-5` 每次跑测试都要求 `docs/CAPABILITY_INVENTORY.md` 和代码一致。清单里有 11 个源文件的 SHA-256（`docs/CAPABILITY_INVENTORY.md:118-132`，由 `scripts/capability_inventory.py:76-80` 生成），所以任何改了 `executors.py`、`seed_catalog.py` 等文件的 PR 都要重新生成，并行时反复冲突。

## 改哪些文件

版本：
- `server/main.py:445`：`FastAPI(..., version="0.1.0")` 改成 `version=settings.app_version`。
- `pyproject.toml:7`：Python 打包必须有 `version`，值不动，旁边加注释：「不是 App 版本，App 版本只在 `desktop/src-tauri/tauri.conf.json`」。
- `arslan/__init__.py:2`：
  - C2d 已合，就删掉 `__version__`；
  - 没合，就加同样的注释。
- `web/package.json:4`（`0.0.0`）、`desktop/package.json:4`、`desktop/src-tauri/Cargo.toml:3`（都是 `0.1.0`）：JSON 写不了注释，值不动。
- 新测试 `tests/test_version_source.py`：
  - FastAPI 的 `app.version`（OpenAPI 里的版本）等于 `settings.app_version`；
  - `settings.app_version` 来自 `tauri.conf.json`，源码环境下带 `-dev`，见 `config.py:60`。
- `CONTRIBUTING.md` 加一小节「版本号」：唯一来源是 `tauri.conf.json`；上面这些文件里的 `0.1.0` / `0.0.0` 不代表 App 版本；发版时只改 `tauri.conf.json`。

能力清单：
- `tests/test_capability_inventory.py:4-5`：普通 CI 里不再比对。环境变量 `ARSLAN_RELEASE_CHECK=1` 时才跑；同文件的另一个测试（`:8-13`）照常跑。
- `.github/workflows/release.yml`：在 `uv sync`（`:109`）之后、构建之前加一步：`.venv/bin/python scripts/capability_inventory.py | diff -u docs/CAPABILITY_INVENTORY.md -`。
  - release 只装 `server`、`build` 两个 extra，没有 pytest，所以这里用生成脚本加 diff，不跑测试；
  - 脚本要能 import `server`。没在 release 的 runner 上试过；不行就在命令前加 `PYTHONPATH=.`；
  - 清单过期就在出包前失败，并提示「在发版 PR 里重新生成」。
- 清单文件头加一句：「生成于发版 PR；两次发版之间，可能和代码不一致」。

## 不许碰

- `desktop/hands/Cargo.toml:3`：③Hands 的文件。如果要加注释，请 ③Hands 来改。
- `tauri.conf.json` 的版本值本身：由各版的发版卡改（FR 改成 0.1.62，R63 改成 0.1.63）。
- `scripts/capability_inventory.py` 的输出格式：本卡只改什么时候检查，不改内容。
- `docs/sessions.md`、README：⓪Plan 的文件。
  - `docs/sessions.md` §3 已经写了新规矩；
  - FR 卡和以后的发版 PR 清单要加「重新生成能力清单」这一步，请 ⓪Plan 补进卡里。

## 怎么做（要点）

1. 先确认没有别处读 FastAPI 的 `app.version`：`rg -n "app\.version|openapi.*version" server tests web/src`。
2. 跳过条件用 `pytest.mark.skipif(os.environ.get("ARSLAN_RELEASE_CHECK") != "1", reason=...)`。跳过的原因要在 `-rs` 的输出里看得见；CI 用的是 `-rfEs`（`ci.yml:103`），本来就会列出跳过原因。
3. 在本 PR 里重新生成一次清单，作为起点。

## 验收

- 本地全量绿、CI 绿，贴 run id。普通 CI 的 skip 列表里出现 `test_generated_inventory_is_current`，原因写明「只在发版时检查」。
- 本地验证两种检查：
  - 设上 `ARSLAN_RELEASE_CHECK=1`，故意改一行 `seed_catalog.py`，测试失败；重新生成清单后通过；
  - 同样改一行，release 那条 `diff` 命令返回非 0。
- `GET /openapi.json` 里的 `info.version`，和 `GET /api/v1/health` 的 `version` 一致。

## 量级

产品代码约 +20 / −5 行。workflow 约 +10 行，测试约 +30 行。

## 风险与回退

- **风险：** 两次发版之间，`CAPABILITY_INVENTORY.md` 可能和代码不一致。文件头写明了，读者不会把它当成实时清单。
- **风险：** 有人把 `ARSLAN_RELEASE_CHECK` 加进普通 CI，又回到天天冲突的老样子。在 `ci.yml` 旁边写一行注释说明。
- **回退：** revert 本 PR。
