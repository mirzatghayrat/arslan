# C2d 删旧的 `arslan` 命令行

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | 0.1.62 |
| 分级 | 必须 |
| 依赖 | C1 |
| 合并位置 | C1 之后随时。不碰 K 线热点 |
| 推动的门槛 | 无直接门槛；净减代码。间接：打包自检少查一个数据目录 |
| 分支 | `claude/0162-c2d-legacy-cli` |
| 迁移号 | 无 |

## 目标

`arslan` 命令行（`arslan/cli.py`）是早期「对话生成专家」的入口：App 不提供这个命令，没有文档，CI 和打包脚本也不调用它。PyInstaller 的 `collect_submodules("arslan")`（`packaging/arslan-server.spec:47-48`）会把模块文件收进包里，但没有任何入口调用它。删掉它、只被它用的对话引擎和需求树，以及 `pyproject.toml` 的入口。服务端的附件导入在用 `arslan.core.chunking`（`server/services/ingest.py:12`），保留。

## 改哪些文件

以下内容都在 `fb6d7230` 上核过。

删除（共 688 行）：
- `arslan/cli.py`（289 行）；
- `arslan/core/dialogue.py`（280 行）：唯一的产品引用是 `arslan/core/__init__.py:2` 的预先导入；
- `arslan/config/requirement_tree.yaml`（119 行）：唯一的读取方是 `dialogue.py:23`。

跟着改：
- `arslan/core/__init__.py:2-4`：删掉对 `dialogue` 的预先导入和 `__all__`，只留包的说明。否则 `import arslan.core.chunking` 会顺带加载已删的模块。
- `pyproject.toml:183-184`：删 `[project.scripts] arslan = "arslan.cli:main"`；`:192` 注释里的「requirement tree」一行也删。
- `packaging/server_entry.py:435`：打包自检的数据目录清单里，删 `("arslan/config", "the requirement tree is unavailable")` 这一项。
  - C2e 还会删 `arslan/config/settings.py`、`__init__.py`，那之后整个目录都没了。
- `packaging/arslan-server.spec:84`：注释里「the requirement tree」的说法删掉。PyInstaller 用 `collect_data_files("arslan")` 收数据，不用改代码。

测试：
- 删 `tests/core/test_dialogue.py`、`tests/test_cli.py`、`tests/test_cli_evolve.py`、`tests/test_cli_runtime.py`。
- `tests/test_integration.py` 的两个测试都从 `DialogueEngine` 起步（`:27`、`:144`）。
  - 改成直接构造 `SpawnRequirements`，保留它对 `SpawnManager`、`QualityGate`、`TemplateLibrary` 那一段的覆盖；
  - 改不动就整份删，在 PR 里说明。

## 不许碰

- `arslan/core/chunking.py`：`server/services/ingest.py:12` 在用。
- `arslan/core/evolution.py`、`arslan/spawn/*`、`arslan/templates/*`、`arslan/models.py`：`cli.py` 用到它们，但它们在服务端各有调用者，已用 `rg` 核过。
- `click`、`rich` 两个依赖：全仓库只有 `cli.py` 用它们（已核）。删依赖要重生成 `uv.lock`、改 `THIRD_PARTY_NOTICES.md`，不在本卡，记进 README §8「0.1.63 候选」。
- `arslan/__init__.py` 的 `__version__`：`cli.py` 删掉后就没人读了，由 C5b 处理。
- `arslan/config/settings.py`、`__init__.py`：归 C2e。

## 怎么做（要点）

1. 删前跑一遍引用：

   ```bash
   rg -n "arslan\.cli|arslan\.core\.dialogue|DialogueEngine|requirement_tree|from arslan\.core import" --glob '!docs/**'
   ```

   结果应该只有本卡列出的文件。
2. 在干净环境里重装：`uv sync --frozen --extra dev --extra server --extra ocr`。确认安装不再生成 `arslan` 可执行文件，也不报错。
3. 打包自检（`packaging/server_entry.py` 的 `selftest`）只少一项。本卡不跑打包；有 DMG 构建条件时，在 PR 里写明跑没跑。

## 验收

- 本地全量绿、CI 绿，贴 run id。
- `python -c "import arslan.core.chunking"` 成功，而且不加载 `arslan.core.dialogue`：检查 `sys.modules`。写成一个小测试。
- 上面那条 `rg` 命令不再有命中，排除 docs 和 git 历史。

## 量级

产品代码约 −690 行，在 800 以内。测试约 −520 行（4 个文件共 518 行），另有 `test_integration.py` 的改写。

## 风险与回退

- **风险：** 有人在源码环境里用过 `arslan` 命令。App 不提供它，也没有文档。发布说明里一句话说明即可。
- **风险：** `uv.lock` 会不会因为删了 `[project.scripts]` 而变。按理不会；如果 `uv sync --frozen` 报 lock 过期，就重生成 lock，并在 PR 里说明。
- **回退：** revert 本 PR。没有数据变化。
