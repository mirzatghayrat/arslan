# S2b 删掉整份引入的 Hermes 规则

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.63 |
| 分级 | 必须 |
| 依赖 | S2a（两个 PR 都合了） |
| 合并位置 | 两个 PR，按顺序：S2b-1 换掉文本处理，S2b-2 删文件。都在 S2a-2 之后，S5 前后都行。S2b-1 只碰 `server/services/approvals.py` 一行，和 C4、S4a 的冲突很小；两个都不碰 `tool_loop.py`、`task_service.py` |
| 推动的门槛 | 总计划 S2「删掉整份引入的 Hermes 规则（1,544 行）」；「先减后加」的净删行数；附录 A「危险命令识别」保持追平 |
| 分支 | `claude/0162-s2b1-shell-text`（S2b-1）、`claude/0162-s2b2-drop-hermes`（S2b-2） |
| 迁移号 | 无 |

## 目标

- **删掉 `arslan/vendor/` 整个目录和它的全部引用。** 里面是 `hermes/approval_detection.py`（1,544 行）、`hermes/ansi_strip.py`（83 行）、两个 `__init__.py` 和 `hermes/LICENSE`。
- **S2a 之后还剩的引用**，都在 `server/services/terminal_policy.py`：
  - `:33`：`from arslan.vendor.hermes import approval_detection as hermes`；
  - `:37`：`_POS = hermes._CMDPOS`，私有的「命令位置」正则；
  - `:89-94`：`_detection_texts`，用了私有的 `_normalize_command_for_detection` 和 `_command_detection_variants`。
  - S2a 若没删干净，还有 `:117-150`、`:200-210` 那几处私有函数（`detect_hardline_command`、`detect_dangerous_command`、`_execution_flag_findings`、`DANGEROUS_PATTERNS_COMPILED`……），一并换掉。
- **还要清的：** `server/services/approvals.py:333` 里 `verdict.rule.startswith("hermes:")` 的判断。S2a 之后不会再有 `hermes:` 开头的规则，这一行成了死代码。
- **为什么拆两个 PR：** 800 行规矩的例外（用户已批的 U2）只给「只删整份文件、别处只去引用且 ≤50 行」的 PR。新的文本处理模块约 +150 行，不是去引用，放进删文件的 PR 就不满足条件。分开还有一个好处：S2b-1 能单独证明「换实现，行为 0 处不同」。

## 改哪些文件

**S2b-1 换掉文本处理（普通 PR，受 800 行规矩）：**

- **新增一个小模块**（例如 `server/services/shell_text.py`，约 150 行），Arslan 自己的命令文本处理，接替 Hermes 那几个私有函数：
  - **规整**（对照 `approval_detection.py:493-513`）：去 ANSI 和 NUL；NFKC；接起反斜杠续行；绝对路径的家目录折回 `~`；去反斜杠转义（`r\m`）和空引号（`r''m`）；`$IFS` / `${IFS…}` 换成空格。
  - **找每个真正的命令起点**，要认引号：`;`、`&&`、`||`、`|`、`&`、换行、`$(`、反引号，并跳过 `sudo` / `env` / `exec` / `nohup` / `time` / `command` / `xargs` 这类前缀。
  - **取出要执行的载荷**：`sh -c` / `bash -c` / `zsh -c` 的参数、`eval`、`xargs`、`find -exec`，作为额外的检查文本。
  - **解析上限**：超过上限，交给 S2a 的「读不懂」。
- `server/services/terminal_policy.py`：换用新模块，删掉 `import` 和 `_POS`；模块说明（`:17-21`）改成「规则改写自 Hermes Agent（MIT）」。
- `server/services/approvals.py:333`：删掉 `hermes:` 那半句。
- **测试：**
  - `tests/server/test_terminal_policy.py:42-44`（`test_hermes_dangerous_patterns_ask`）改成测 Arslan 自己的规则；
  - 把 `"hermes:recursive delete"` 这类字符串当数据存进数据库的测试，**不用改**（例如 `tests/server/test_permissions.py:115-122`）；
  - 用 `assess` 现算出 `hermes:` 规则的测试（例如 `tests/server/test_approvals_v2.py:485`），S2a 已经改过，本卡只核对。

**S2b-2 删文件（按 U2 的例外）：**

- 删 `arslan/vendor/hermes/approval_detection.py`、`arslan/vendor/hermes/ansi_strip.py`（只有 `approval_detection.py:496` 用它，已核）、`arslan/vendor/hermes/__init__.py`、`arslan/vendor/__init__.py`（`arslan/vendor/` 下没有别的东西，已核）、`arslan/vendor/hermes/LICENSE`。
- `THIRD_PARTY_NOTICES.md:237-246`：这一节改写为「终端命令规则改写自 NousResearch/hermes-agent（MIT，commit `6b2fe92a`）」，附上 MIT 许可证全文。理由：S2a 的禁止层和 S2b-1 的文本处理都改写自 Hermes，MIT 要求保留版权和许可声明。
- 产品代码别的地方不改（S2b-1 之后已经没有引用）。

## 不许碰

- **规则本身。** 三层分到哪一层、问不问，都是 S2a 定的。本卡只换文本处理，行为一条不变。
- **文档站和发布说明。**
  - `docs-site/sections/*/02-development.html`（6 种语言）、生成的 `docs/docs/**`、`docs/index.html:836` 都提到 `arslan/vendor/hermes`；
  - 按 `docs-site/README.md`，这些在发版时随实际行为一起改。
  - 本卡只在 PR 描述里列出要改的句子，交给发版 PR。
- `packaging/**`：已核，没有引用 `arslan/vendor`。

## 怎么做（要点）

1. **先跑基线。** S2a 合进去之后，`tests/server/test_terminal_policy.py` 里所有防混淆的用例都是新模块的规格：引号、`$IFS`、`r''m`、反斜杠续行、`sh -c` 载荷、`ls && git push` 这类链式命令。先确认它们在旧实现上全过。
2. **再换实现**（S2b-1），同一组测试要全过。
3. **补测试：** 从 3a 分支的 `tests/server/test_terminal_categories.py` 再挑一批实测命令，覆盖新模块的每个分支。
4. **全仓确认：** `grep -rn "vendor.hermes\|approval_detection"` 在代码和测试里都是 0；文档里剩下的，列进 PR 描述。
5. S2b-1 合并后、S2b-2 合并前，Hermes 文件还在但没人引用。新模块的说明里写「`arslan/vendor/hermes` 由 S2b-2 删（v0.1.63）」。

## 验收

- **S2b-1：**
  - `tests/server/test_terminal_policy.py` 的防混淆用例全过；全量测试通过；
  - 用 3a 实测命令回放：每条命令的分层结果和 S2a 合并时一模一样，PR 里贴对比（应为 0 处不同）。
- **S2b-2（U2 的五个条件，PR 描述逐条写）：**
  - 只删不可达或第三方的整个文件：上面列的五个文件；
  - 别处的改动只是去掉引用，产品代码合计 ≤50 行（本 PR 预计 0 行；`THIRD_PARTY_NOTICES.md` 是文档）；
  - 不改任何行为：同一组 3a 回放 0 处不同；
  - PR 描述列出删了哪些文件，以及怎么确认不可达（上面的 `grep` 结果，加全量测试）；
  - CI 全绿，附 run id 和结论。
- `arslan/vendor/` 整个不在了；`THIRD_PARTY_NOTICES.md` 里有 MIT 全文和出处。

## 量级

- S2b-1：产品代码约 +150 / −30 行。
  - **更正（⓪Plan，2026-10-22）：** S2b-1 是一份删减过的移植，约 +450–500 行，不是 150 行的重写。原因是 `terminal_policy` 用到的八个 Hermes 私有函数，连同它们调用的部分共约 790 行，全都影响判断：认引号的扫描器、命令起点和命令词、`-c` 与读工具的程序参数、grep 模式遮挡（也给出「读不懂」）、命令词去混淆、规整。
  - **只删 Arslan 碰不到的两块：**
    - `HERMES_HOME` 折回：Hermes 自己的安装目录，这里取不到，本来就不起作用；
    - 解释器 `-c` / `-e` 和「载荷读不懂」的发现：它们不带载荷，Arslan 只读载荷，内联脚本由 `terminal_policy` 自己读。
  - **Windows 路径变体留着**（②Main 审 #320，A1）：先前说它碰不到判断，是错的。去掉它会让含 `X:\` 或三个反斜杠的命令判得更松（模糊测试 211 处不同，143 处放松）。这些旧判断在 zsh 下都是误报，所以不是漏洞；但本卡要求行为一条不变，所以留着。要删，另开一个带测试的改动。
  - **永久测试**（②Main 审 #320，A2）：`tests/server/test_shell_text_reading.py` 按判断结果钉住每种读法，30 个变异全被抓到，不靠对照测试。
  - **验收用逐条对比：** 新旧 `assess()`（层、规则、`ask_rules`）在 3a 语料、仓库测试里的全部命令字符串、生成的混淆写法上 0 处不同；再加一个按函数对比的测试（`tests/server/test_shell_text_parity.py`），随 S2b-2 一起删。
- S2b-2：约 −1,630 行（四个代码文件），产品代码别处 0 行。删的是整份第三方文件，按 U2 不用再拆。

## 风险与回退

- **新的文本处理比 Hermes 少几个防混淆分支，被绕过。**
  - 先用 S2a 时的全部用例做规格，再用 3a 的实测命令回放，要求 0 处不同。
  - 沙箱是第二道防线：第③层本来就在沙箱里跑，S2a-1 又挡了 Apple Events 和读过外部内容后的网络。
- **漏掉许可证义务。** 许可证全文搬进 `THIRD_PARTY_NOTICES.md`，审稿时核对。
- **留着的旧东西：** 只有 S2b-1 到 S2b-2 之间没人引用的 Hermes 文件，S2b-2 删（同一版 v0.1.63）。
- **回退：** 各自 revert。先退 S2b-2，Hermes 文件回来；再退 S2b-1，`terminal_policy` 重新用它们。S2a 的行为不受影响。
