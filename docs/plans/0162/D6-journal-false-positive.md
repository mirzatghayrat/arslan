# D6 一步记不进任务记录时，只拒这一步；去掉在 JSON 编码文本上查密钥的误判

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.63 |
| 分级 | 应该（用户 2026-10-20 定） |
| 依赖 | K3（`tool_loop.py` 是 K3 的文件，K3 合并后再动） |
| 合并位置 | 不进 K 线严格链；K3 合并后马上做，排在「回合中途缓存作废」那项 K 线工作之前 |
| 推动的门槛 | §5.1 T2（后台任务不该因为一步记不下就整个停掉）；中文用户写笔记时的误判 |
| 迁移号 | 无 |
| 来源 | 2026-10-20 K3 的 Claude 对照（`k3-c5`）T2 第 2 次：后台任务正有进展，一步 `edit_file` 被判「记不进任务记录」，整个任务以 `job_blocked` 停掉 |

## 发生了什么（⓪Plan 和 ②Main 只读核过）

1. **整个任务停掉。**
   - `task_repository.encoded_action`（main 上 `task_repository.py:47-57`）在三种情况下抛 `TaskError("task_action_arguments_not_journalable")`：
     - 编码后超过 256 KB；
     - `contains_credential_data(arguments)` 命中；
     - `contains_credential(encoded)` 命中。
   - `tool_loop._dispatch_tool` 的 `except TaskError` 只把 `task_reconciliation_required` 和 `task_action_already_completed` 变成工具结果，其余的照抛。
   - 所以这一步让整个后台任务停了，模型也收不到一句原因。
2. **这次其实是误判。**
   - 那一步的 `new` 是一段笔记，开头是「重大进展……curl 直接可取，无需登录/无验证码：」，换行后接一个网址。
   - ⓪Plan 在 K3 的 head 上用真函数只读跑过：

     | 检查 | 结果 |
     |---|---|
     | `contains_credential_data(arguments)` | 不命中 |
     | `contains_credential(原文)` | 不命中 |
     | `contains_credential(编码后的整段)` | 命中 |
     | 编码后、把「验证码」换掉 | 不命中 |
   - **原因：** `content_policy._SECRET_PATTERNS` 的第 5 条是「`验证码` + `：` + 4 个以上非空白字符」。`json.dumps` 把换行写成字面的 `\n`，它不是空白，于是「：**\nhttps://…」连成了 4 个以上非空白字符。原文里换行会把它截断。
3. **同一个毛病还在别处：** 在 JSON 编码后的字符串上查密钥。
   - `server/api/companion.py:67`（`self.model_dump_json()`）；
   - `server/services/task_repository.py:123` 和 `:221`（任务规格的 `spec.model_dump_json()`）；
   - `arslan/companion/memory.py:102`（`style_reference.model_dump_json()`）。

   这些地方，用户或模型写的文字里只要有「验证码：」「密码：」这类词后面接换行，就可能被误判。开工时逐个确认误判的后果：拒绝建任务、不存记忆，还是别的。

## 改什么

1. **一步记不下，只拒这一步，任务继续。** `tool_loop` 把 `task_action_arguments_not_journalable` 变成这一次调用的工具结果，不再往上抛。给模型的话照 ②Main 拟的：
   > 这一步没有执行：它的参数不能记进任务记录——超过 256 KB，或者里面有像密钥的内容（密码、key、token 或 cookie 的值）。别把密钥写进文件或命令：从环境变量或用户指定的文件读。太长的写入拆成几次。
2. **不在 JSON 编码后的整段文字上查密钥。**
   - `encoded_action` 去掉 `contains_credential(encoded)`。大小检查照旧查编码后的长度。
   - **但先补上编码后那次检查顺带做到的事**（②Main 在 Opus 5.5 上审卡时发现，⓪Plan 在 Opus 5.5 上用真函数核过）：
     - 编码后，`"键":"值"` 连在一起，规则会跨过键名去匹配。所以键名叫 `db_password`、`x-api-key`、`GITHUB_ACCESS_TOKEN`、值是一串 8 位以上字符的参数，今天是被编码后那次挡住的（测试里用假值，卡里不写出来，免得被 gitleaks 当成密钥）。
     - 按原文查的 `contains_credential_data` 只把键名和固定的几个词逐字比较，不拿规则去匹配键名，所以这三个都放过了。只去掉编码后那次，真的密钥就会进任务记录。
     - 所以 `contains_credential_data` 同一个 PR 里加两条：
       - 字符串键名本身也过一遍规则；
       - 值是字符串或数字的键，把「键: 值」按原文拼起来再查一遍。这正是编码后那次查到的，只是没有 `\n` 转义。
     - 核对结果：

       | 例子 | 按原文 | 编码后 | 补上以后 |
       |---|---|---|---|
       | 上面三个键名带密钥词的 | 放过 | 挡住 | 挡住 |
       | T2 那段笔记 | 放过 | 挡住（误判） | 放过 |
       | `验证码：` 换行后接一个值 | 挡住 | 挡住 | 挡住 |
     - 顺带：research_review、`tool_loop` 和 task_workers 里同样用到 `contains_credential_data` 的地方，也会开始挡这类键名。它们是真的密钥，不是新的误判。
     - 第 3 条那几处用到的模型，②Main 用 `model_fields` 查过：没有带密钥词的字段名，也没有任意的字典，不会多出误判。
   - 第 3 条列的几处也改成按原文查，比如 `contains_credential_data(model.model_dump())`，不查 `model_dump_json()`。`contains_credential_data` 还会查键名（password、authorization 等），开工时核对这几个模型有没有这样的字段名，会不会带来新的误判；有就只查值。
3. **规则本身不动：** Cookie、密码、key、token 的模式都保留。真的密钥照样拒。

## 不做

- 不放宽 `_SECRET_PATTERNS`，不删 Cookie 那条。真的 `Cookie: session=…` 被记进任务记录，比拒掉一次写入更糟（②Main 的判断，⓪Plan 同意）。
- 不改任务记录的格式。

## 验收

- **测试：**
  - T2 第 2 次那段**原文**（「无验证码：**」后面换行再接网址）能正常记进任务记录，`edit_file` 照常执行。
  - **规则本身不变：**「验证码：」后面直接换行、下一行是一个值，照样被挡。原文里规则的 `\s*` 会跨过换行。卡里写明这一点，不改成「值必须在同一行」：那样会漏掉「密码：」换行再写密码的情况。
  - 键名是 `db_password`、`x-api-key`、`GITHUB_ACCESS_TOKEN` 的参数（假值），在去掉编码后那次检查以后照样被挡。
  - 参数里有真的 `Cookie: session=…` 值：这一步被拒；模型收到上面那段原因；任务继续，不是 `job_blocked`。
  - 超过 256 KB 的写入：同样只拒这一步。
  - 第 3 条的每一处：带「无验证码：」加换行的文字不再被误判；真的密钥照样被挡。
  - **Mutation：** 下面每一条改回去，都要有测试抓到：
    - 恢复对编码后整段的检查；
    - 去掉对键名的检查，或者去掉「键: 值」那次检查；
    - 恢复「记不下就停掉整个任务」；
    - 第 3 条任何一处改回查 `model_dump_json()`。
- 完成证据四项（`docs/sessions.md` §8）。

## 量级

产品代码约 +36 / −10 行，测试另算。

## 风险与回退

- **风险：** 去掉编码后的检查，会不会漏掉只在编码后才看得出的密钥？
  - 已知的一类（键名里带密钥词）由上面补的两条接住，有测试。
  - 别的形状 ⓪Plan 和 ②Main 都没想到。PR 里写明这一点；有人想到反例，就加一个测试。
- **回退：** revert 这一个 PR。
