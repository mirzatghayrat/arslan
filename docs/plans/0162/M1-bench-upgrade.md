# M1 基准升级：「等你」算失败、5 道新题、Claude Code 参赛

| 项 | 内容 |
|---|---|
| 道 | ⓪Plan |
| 版本 | —（只改脚本，不随 App 发布） |
| 分级 | 必须 |
| 依赖 | — |
| 合并位置 | M 线随时；要在 FR 发布前合，M1B 才能在 v0.1.62 上跑基线 |
| 推动的门槛 | §5.1 全部（不退步、对 Hermes、对 Claude Code、新题 3/3） |
| 分支 | `claude/0162-m1-bench-upgrade`（拆成两个 PR 时：`claude/0162-m1a-bench-judging-entrants`、`claude/0162-m1b-bench-new-tasks`） |
| 迁移号 | 无 |

## 目标

总计划 §4.2 M1 的 ①–③。④ 跑基线归 M1B。

1. Arslan 停在「等你」的一次运行，算失败。
2. 加 5 道新题。
3. 加 Claude Code 参赛，用同一个 Claude 模型。Hermes 继续当 DeepSeek 上的对照。

## 现状（亲核，`scripts/kernel_bench/`）

- **驱动 `arslan_driver.py`：**
  - 把 `waiting_user` 当作结束（`:23`），在 `end` 里记 `task_waiting_user`（`:67-70`）。
  - 但判分只看检查器给的分数：`runner.py:213` 是 `passed = score == 3`。所以文件写出来了、任务却挂在「等你」的一次运行，照样算过。
  - `:23` 和 `:69` 写的是 `"completed"`，服务端的阶段名却叫 `succeeded`（`arslan/companion/contracts.py:167`），这个名字是死的。
- **驱动只会把 Arslan 配成 OpenAI 兼容端点**（`arslan_driver.py:147-157`），所以 Claude 模型上的 Arslan 跑不了。
- **runner 的参赛者在 `command()` 里列着**（`runner.py:77-111`）：hermes、goose、dsh、openclaw、arslan。没有 Claude Code。
- **现有题目：**
  - 检查器表在 `runner.py:42-51`，题面在 `prompts.json`；
  - 每题只发一条 prompt（`runner.py:192`），所以没有多轮的题；据总计划 §1.3，也没有超过 20 秒的命令（这一点没逐题核）。
- **计量代理 `meter.py`：**
  - 只转发到一个上游（`:20`，默认 DeepSeek）；
  - 价格表只有 DeepSeek（`:26-31`）；
  - 会把真 key 写进请求头（`:153-156`），参赛者拿到的只是假 key。
- **`report.py` 只按（题, 参赛者）分组。** 两个模型的结果会混在一起。
- **测试：** `tests/test_kernel_bench.py`（驱动、报告、检查器）、`tests/test_kernel_bench_tasks.py`（T1/T2/T4/T6 的检查器和夹具）。

## 改哪些文件

**M1a：判定、参赛者、双模型**

- `arslan_driver.py`：
  - 阶段名对齐成 `succeeded`；
  - 支持多轮：传一串 prompt，上一轮结束后再发下一条；
  - 拒绝时能带一句话：`cancel_*` 帧加 `note`，服务端按 `server/services/approvals.py:226` 读它；
  - `configure()` 支持 `anthropic`，`base_url` 指向第二个计量代理。
- `runner.py`：
  - Arslan 的 `end` 是 `task_waiting_user` 时，`passed = False`；
  - 新参赛者 `claude-code`；
  - 模型按参赛者分别指定；
  - 结果里记下 Claude Code 的版本。
- `meter.py`：
  - 加 Claude 模型的价格，按官方价目表填，注明日期；
  - 说明怎么开第二个实例：`BENCH_UPSTREAM` 指向 Anthropic，另一个端口。
- `report.py`：按（题, 参赛者, 模型）分组。
- `install_entrants.sh`：把 Claude Code 装进 bench 目录，版本固定。
- `README.md`：更新。
- `tests/test_kernel_bench.py`：补测试。

**M1b：五道新题**

题面加进 `prompts.json`；每道题一个检查器和夹具，都在 `scripts/kernel_bench/`；测试放 `tests/test_kernel_bench_tasks.py`。题目都在本地，不靠网页。

| 题 | 题面要点 | 怎么判 |
|---|---|---|
| T7 长命令 | 运行夹具里一个要 60–90 秒的脚本，把它最后打出的校验码存进 `answer.txt` | 校验码对；Arslan 没有停在「等你」 |
| T8 三轮追问 | 第 1 轮：按夹具笔记写一份三节的 `report.md`，先不要表格。第 2 轮：「把第二节改短」。第 3 轮：「加一个表格」 | runner 在轮与轮之间存快照：第二节变短到 ≤60%；第一、三节不变；第 3 轮多出一个 Markdown 表格 |
| T9 多文件精确修改 | 在 3 个指定文件里改一个配置名，另 1 个文件改版本号 | 被改的文件逐字节等于预期，其余文件逐字节不变，没有新文件 |
| T10 长日志 | 在一个 5,000 行的生成日志里，找出导致后面一串失败的第一个原因 | 回答里有正确的行号（±2）和原因关键词 |
| T11 被拒后换路 | 清理 `.bak` 文件；替身用户拒绝删除卡，附一句「改成移到 trash 文件夹」 | `.bak` 都在 `trash/` 里，一个没删，其余不变；Arslan 没有停在「等你」 |

## 怎么做（要点）

1. 先 M1a，后 M1b。M1a 合了，M1b 的新题才能用新的判分和两个模型。
2. 每道新题先写检查器和它的测试，再写题面。
3. Claude Code 按下面的方式参赛（标志以 `claude --help` 为准，未核）：
   - 和别的参赛者一样，跑在 `sandbox.sb.template` 的同一个沙箱里：只能写 bench 目录，读不到 `~/.ssh` 和钥匙串。
   - `HOME` 指向 bench 自己的目录，不读用户自己的 `~/.claude`。不挂任何 MCP。
   - `ANTHROPIC_BASE_URL` 指向计量代理，`ANTHROPIC_API_KEY` 用假值。
   - 用 `-p` 加 JSON 输出跑。权限放开，因为沙箱已经限制了写入。
   - 多轮用 `--resume`。
   - T11 的「拒绝」用它自己的禁用工具机制来模拟。模拟不了就记成不支持，不硬比。
4. Hermes 的多轮和拒绝机制都未核，做不到的同样记成不支持。

## 不许碰

- 产品代码（`server/**`、`arslan/**`、`web/**`）。`approvals.py:226` 只读，不改。
- 用户真实的数据目录、key 和配置。
- 现有 T1–T6 的判分标准。

## 验收

- **判分：** 新测试——一次检查器给了 3 分、但 `end` 是 `task_waiting_user` 的运行，记为不通过。
- **驱动：**
  - 新测试：`succeeded` 会让运行结束；
  - 新测试：多轮时，第 2 条消息在第 1 轮结束后才发；
  - 新测试：拒绝帧带着 `note`。
- **报告：** 两个模型分开成行（新测试）。
- **五个检查器：** 都有合成输出的测试，各至少一条「该过」、一条「该不过」，不调用任何模型。
- **试跑：** 用便宜模型、`--repeats 1` 把五道题在 Arslan 上各跑一次，确认流程能走通。只贴汇总数字，不贴回复内容和本机路径。真正的基线归 M1B。

## 量级

脚本约 400–600 行，外加测试。不是产品代码，但为了好审，默认拆成 M1a 和 M1b 两个 PR。

## 风险与回退

- **Claude Code 的标志会随版本变：** 版本固定在 `install_entrants.sh` 里，并写进结果。
- **把 Arslan 指到本地代理，可能改变它的行为：**
  - 按端点选的输出预算：`arslan/llm/output_budget.py` 的 `for_endpoint`；
  - 参数自愈：按端点指纹记的。
  - 都未核。试跑时要对照直连各跑一次。
- **花费：** 代理有单次上限和总上限（`meter.py:22-23`）。M1 只做小规模试跑。
- **回退：** revert。产品没有被改动。
