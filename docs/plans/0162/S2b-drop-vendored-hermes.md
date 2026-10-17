# S2b 删掉整份引入的 Hermes 规则

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | 0.1.62 |
| 分级 | 必须 |
| 依赖 | S2a |
| 合并位置 | S2a 之后，S5 前后都行。只碰 `server/services/approvals.py` 一行，和 C2c、C4、S4 的冲突很小 |
| 推动的门槛 | 总计划 S2「删掉整份引入的 Hermes 规则（1,544 行）」；「先减后加」的净删行数；附录 A「危险命令识别」保持追平 |
| 分支 | `claude/0162-s2b-drop-hermes` |
| 迁移号 | 无 |

## 目标

- **删掉 `arslan/vendor/hermes/approval_detection.py`（1,544 行）和它的全部引用。**
- **S2a 之后还剩的引用**，都在 `server/services/terminal_policy.py`：
  - `:33`：`from arslan.vendor.hermes import approval_detection as hermes`；
  - `:37`：`_POS = hermes._CMDPOS`，私有的「命令位置」正则；
  - `:89-94`：`_detection_texts`，用了私有的 `_normalize_command_for_detection` 和 `_command_detection_variants`。
  - S2a 若没删干净，还有 `:117-150`、`:200-210` 那几处私有函数（`detect_hardline_command`、`detect_dangerous_command`、`_execution_flag_findings`、`DANGEROUS_PATTERNS_COMPILED`……），一并换掉。
- **还要清的：** `server/services/approvals.py:333` 里 `verdict.rule.startswith("hermes:")` 的判断。S2a 之后不会再有 `hermes:` 开头的规则，这一行成了死代码。

## 改哪些文件

- **新增一个小模块**（例如 `server/services/shell_text.py`，约 150 行），Arslan 自己的命令文本处理，接替 Hermes 那几个私有函数：
  - **规整**（对照 `approval_detection.py:493-513`）：去 ANSI 和 NUL；NFKC；接起反斜杠续行；绝对路径的家目录折回 `~`；去反斜杠转义（`r\m`）和空引号（`r''m`）；`$IFS` / `${IFS…}` 换成空格。
  - **找每个真正的命令起点**，要认引号：`;`、`&&`、`||`、`|`、`&`、换行、`$(`、反引号，并跳过 `sudo` / `env` / `exec` / `nohup` / `time` 这类前缀。
  - **取出要执行的载荷**：`sh -c` / `bash -c` / `zsh -c` 的参数、`eval`、`xargs`、`find -exec`，作为额外的检查文本。
  - **解析上限**：超过上限，交给 S2a 的「读不懂」。
- `server/services/terminal_policy.py`：换用新模块，删掉 `import` 和 `_POS`；模块说明（`:17-21`）改成「规则改写自 Hermes Agent（MIT）」。
- `server/services/approvals.py:333`：删掉 `hermes:` 那半句。
- **删除：**
  - `arslan/vendor/hermes/approval_detection.py`；
  - `arslan/vendor/hermes/ansi_strip.py`：只有 `approval_detection.py:496` 用它，已核；
  - `arslan/vendor/hermes/__init__.py`、`arslan/vendor/__init__.py`：`arslan/vendor/` 下没有别的东西，已核；
  - `arslan/vendor/hermes/LICENSE`，但许可证全文要先搬走，见下一条。
- `THIRD_PARTY_NOTICES.md:237-246`：这一节改写为「终端命令规则改写自 NousResearch/hermes-agent（MIT，commit `6b2fe92a`）」，并附上 MIT 许可证全文。
  - 理由：S2a 的禁止层是从 Hermes 的规则改写来的，MIT 要求保留版权和许可声明。
- **测试：**
  - `tests/server/test_terminal_policy.py:42-44`（`test_hermes_dangerous_patterns_ask`）改成测 Arslan 自己的规则；
  - 把 `"hermes:recursive delete"` 这类字符串当数据存进数据库的测试，**不用改**（例如 `tests/server/test_permissions.py:115-122`）；
  - 用 `assess` 现算出 `hermes:` 规则的测试（例如 `tests/server/test_approvals_v2.py:485`），S2a 已经改过，本卡只核对。

## 不许碰

- **规则本身。** 三层分到哪一层、问不问，都是 S2a 定的。本卡只换文本处理，行为一条不变。
- **文档站和发布说明。**
  - `docs-site/sections/*/02-development.html`（6 种语言）、生成的 `docs/docs/**`、`docs/index.html:836` 都提到 `arslan/vendor/hermes`；
  - 按 `docs-site/README.md`，这些在发版时随实际行为一起改。
  - 本卡只在 PR 描述里列出要改的句子，交给发版 PR。
- `packaging/**`：已核，没有引用 `arslan/vendor`。

## 怎么做（要点）

1. **先跑基线。** S2a 合进去之后，`tests/server/test_terminal_policy.py` 里所有防混淆的用例都是新模块的规格：引号、`$IFS`、`r''m`、反斜杠续行、`sh -c` 载荷、`ls && git push` 这类链式命令。先确认它们在旧实现上全过。
2. **再换实现**，同一组测试要全过。
3. **补测试：** 从 3a 分支的 `tests/server/test_terminal_categories.py` 再挑一批实测命令，覆盖新模块的每个分支。
4. **全仓确认：** `grep -rn "vendor.hermes\|approval_detection"` 在代码和测试里都是 0；文档里剩下的，列进 PR 描述。

## 验收

- `arslan/vendor/` 整个不在了；全量测试通过。
- `tests/server/test_terminal_policy.py` 的防混淆用例全过。
- 用 3a 实测命令回放：每条命令的分层结果和 S2a 合并时一模一样，PR 里贴对比（应为 0 处不同）。
- `THIRD_PARTY_NOTICES.md` 里有 MIT 全文和出处。

## 量级

- 产品代码约 −1,560 行（Hermes 两个文件），约 +150 行（新模块）。
- 删的是整份第三方文件，不用逐行审，同 C1（−1,600 行）一样算一件事；是否要拆，由 ②Main 判。新增部分远低于 800 行。

## 风险与回退

- **新的文本处理比 Hermes 少几个防混淆分支，被绕过。**
  - 先用 S2a 时的全部用例做规格，再用 3a 的实测命令回放，要求 0 处不同。
  - 沙箱是第二道防线：第③层本来就在沙箱里跑。
- **漏掉许可证义务。** 许可证全文搬进 `THIRD_PARTY_NOTICES.md`，审稿时核对。
- **回退：** 整个 PR revert。Hermes 文件随之回来，S2a 的行为不受影响。
