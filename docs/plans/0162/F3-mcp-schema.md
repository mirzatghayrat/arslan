# F3 MCP 工具的参数表按供应商规整；坏工具不再拖垮整轮对话

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.62 |
| 分级 | 必须 |
| 依赖 | F5a |
| 合并位置 | 合进 `release/0.1.62`，F5a 之后不分先后。发版后随分支合回 main；K7 要等它进了 main 才开工 |
| 推动的门槛 | §5.2「MCP 引起的整轮失败 = 0」；§5.3 第 4 条 |
| 分支 | `claude/0162-f3-mcp-schema`（从 `release/0.1.62` 拉，PR 的 base 是 `release/0.1.62`） |
| 迁移号 | 无 |

## 目标

1. **发出去之前先规整。** MCP 工具的参数表在发给供应商之前，规整成三家都收的形状。
2. **被拒时降级，最多两次。** 供应商因为参数表回 400 时：先去掉点名的那个工具重试；再失败，本轮去掉全部 MCP 工具再试一次。整轮对话不能因此失败。
3. **记住坏工具。** 按「模型、工具、参数表哈希」记在进程里，同一个模型下次不再先撞一次 400。

## 现状（亲核）

参数表从发现到发出，一路都是原样：

1. **发现时原样存下**（`server/mcp/discovery.py:212-227`）。
2. **每轮全发：** 每个就绪服务器的全部工具，每轮都带着 `input_schema` 发出（`server/orchestrator/arslan.py:1346-1369`）。
3. **原样透传：** `_tool_params`（`server/orchestrator/tool_loop.py:1691-1710`）→ `_native_tool_schemas`（`:1713-1728`，末尾可能追加 `escalate`，`:1726-1727`）→ 在 `:2168` 生成；装上新能力后在 `:2450-2453` 重新生成一次。
4. **各家供应商最终发出的形状不同：**
   - Anthropic：`input_schema`，**没有名字的工具直接跳过**（`arslan/llm/providers/anthropic_provider.py:226-236`）；
   - OpenAI 兼容：`payload["tools"] = tools`，原样（`openai_provider.py:173-176`）；
   - Gemini：全部放进一个 `functionDeclarations` 列表（`gemini_provider.py:107-117`）。
5. **400 直接抛出：** 不匹配上下文和协议规则时归为 `input`（`server/orchestrator/model_call.py:84-106`），不重试（`:129-166`）。`_model_call` 现有三种恢复都不管工具（`tool_loop.py:569-594`），而且恢复只做一次（`:595`）。
6. **执行时另取一次工具表**（`tool_loop.py:1239`），不看本轮发给模型的那份。

## 改哪些文件

- **新增纯函数模块** `arslan/llm/tool_schema.py`：输入一份 JSON Schema 和供应商类别，输出规整后的 schema。不碰网络，不读库。**三家都做**（审查 §3：OpenAI 也拒绝顶层 `anyOf`）：
  - 顶层是 `anyOf` / `oneOf` / `allOf` 时，合并成一个 `type: object`：`properties` 取并集，`required` 取交集，原来的约束写进 description 的一句话里；
  - 展开本地的 `$ref` / `$defs`；循环引用的地方换成宽松的 `{"type": "object"}`，并在 description 里说明；
  - `type: [..., "null"]` 改成单一类型，description 加「可以为空」；有两个以上非空类型时去掉 `type`，同样写进 description；
  - 去掉 `$schema`。
  - **OpenAI 兼容（DeepSeek 等）另外：** 递归去掉对方不收的关键字，至少有 `pattern`，去掉的约束写进 description。
  - 同样的输入永远给出同样的输出，键序固定。否则提示词缓存的前缀会变，见 `arslan.py:1357-1363` 的注释。
- **三个 provider 在翻译工具时调用它：** 只处理 key 以 `mcp_` 开头的工具，内置工具的参数表一字不改。
- **三个 provider 各加一个小函数：** 把报错里的工具序号，按**自己最终 payload 的顺序**换成工具名（审查 §3）。Anthropic 按跳过无名工具之后的列表算；Gemini 按 `functionDeclarations` 计；OpenAI 兼容按 `payload["tools"]` 计。
- **`server/orchestrator/tool_loop.py`**（热点文件）：
  - `_model_call`（`:517-596`）新加一个恢复分支，排在「换旧协议」之前判断。条件：`input` 类 400，本次请求带着 MCP 工具。
    - 报错里能认出某一个 MCP 工具（序号或名字）：本轮去掉它，重试；
    - 认不出，但报错提到 tool / function / schema / parameters 之类的字样：本轮去掉全部 MCP 工具，重试；
    - **再失败**（审查 §3）：本轮去掉全部 MCP 工具，再试最后一次；还失败就照旧抛出。
    - 认不出、也不像参数表的问题：照旧抛出，不重试。
  - **本轮排除对后面每一步都生效：** 维护一个本轮的排除集合，`:2168` 生成参数表、`:2450-2453` 重新生成、`wired_keys`（`:2145`、`:2451`）、执行时取的工具表（`:1239`）都扣掉它。模型再叫被去掉的工具，得到 `tool_unavailable`。
  - **进程内记住坏工具：** 新集合 `_BAD_TOOLS`，元素是（`_model_key(a)`（`:482-484`）、工具 key、参数表规整前 JSON 的 sha256），仿 `:479` 的 `_REFUSES_IMAGES`。生成参数表时跳过命中的工具。服务器改了参数表，哈希就变，会再试一次。
  - `_model_call` 今天不带 `conversation_id`，从调用方传进去，用来记事件。
  - 降级时写 `conversation_events`，kind 为 `mcp_schema_relaxed`，ref 只带 `{tool_key, provider}`；一次去掉全部时 `tool_key` 写 `"all"`（仿 `:665-676` 的 `_log_degrade_hint`）。M2 用它计数。
  - 告诉模型的话只放进本步的状态说明。不加界面文案，不动 locale。
- **测试：** 新文件 `tests/server/test_mcp_schema_normalise.py`；`tests/server/test_native_tool_schemas.py` 里补「内置工具不变」的断言。

## 不许碰

- 发现和入库的逻辑（`discovery.py`），以及数据库里存的原始 schema。规整只在发出时做，原样保留便于以后对照。
- MCP 工具的按需取用归 K7，审批归 S1。
- `web/src/locales/*`、Bridge 文件。

## 怎么做（要点）

1. **夹具一律合成**，形状照 10-14 的事故，内容不用那个服务器的任何东西。至少这几个：顶层 `anyOf`；嵌套 `pattern`；`$ref` 到 `$defs`；循环 `$ref`；`type: ["string", "null"]`；带 `$schema`；一个正常工具；一个没有名字的工具（测 Anthropic 的序号）。
2. **错误原文不在仓库里。**
   - Anthropic 的报错一般按序号点名工具（`tools.<n>…`），这是按常见报错形状推断的，未核。DeepSeek、Gemini 的报错形状也未核。
   - 开工时向用户要一段去掉服务器名的错误原文。要不到就按各家的公开文档写，并在 PR 里标「未核」。
3. **认出工具的方式：** 序号经 provider 换成名字，或者直接取名字，和 `mcp_` key 或外部名比对。都只认本次请求里确实存在的工具，参照 `arslan/llm/param_heal.py`：只改本次请求里真有的东西。
4. 降级重试和 `_BAD_TOOLS` 的代码注释写明删除条件（见「风险与回退」，`docs/sessions.md` §9）。

## 验收

- **规整函数的单元测试：** 上面每种形状 × 三类供应商。内置工具的参数表逐字相等。同一输入跑两次，输出逐字节相同。
- **序号：** Anthropic 的 payload 里前面有一个无名工具时，报错的序号仍然对回正确的工具；Gemini 按 `functionDeclarations` 的位置对回。
- **回放**（Anthropic 和一个 OpenAI 兼容端点的替身各一个）：
  - 第一次请求回 400、点名一个工具；第二次请求里没有它，回合正常结束，记下一条 `mcp_schema_relaxed`。
  - **两个坏工具：** 第一次点名 A，第二次点名 B；第三次请求不带任何 MCP 工具，回合照样结束。
  - **认不出工具时：** 第二次请求不带任何 MCP 工具，回合照样结束。
- **本轮后面的步骤：** 去掉的工具不在之后每一步的参数表里，也不在 `wired_keys` 里；装上新能力、重新生成参数表之后也不回来；模型硬叫它，得到 `tool_unavailable`。
- **同一模型的下一轮、另一个对话：** 直接不带那个工具，不再先撞一次 400。换一个模型，照常带上。
- **非 MCP 原因的 400**（比如 key 错、余额不足、和工具无关的参数错）照旧按原分类处理，不重试。

## 量级

产品代码约 180–250 行（新模块约 120 行），外加测试。

## 风险与回退

- **规整改变了参数的含义。** 比如合并 `anyOf` 时把两个互斥分支的字段放到了一起。模型可能传出服务器不接受的组合，服务器自己会报参数错误，至少整轮不会失败。在 description 里写明原来的约束，可以减少这种情况。
- **一次去掉全部 MCP 工具，本轮就用不了 MCP。** 模型从状态说明里知道这件事，会改用内置工具或告诉用户。
- **`_BAD_TOOLS` 只在进程内存里**，重启后第一次请求会再撞一次 400，再降级一次。v0.1.62 接受这个代价。
- **留着的东西和删除条件**（`docs/sessions.md` §9，代码注释同样写）：降级重试和 `_BAD_TOOLS` 是规整没覆盖到时的兜底。M2 周报连续 4 周 `mcp_schema_relaxed` 为 0，就在下一版删掉这两样，最早 v0.1.65。
- **回退：** 在 `release/0.1.62` 上 revert 合并提交。没有存下的状态。
