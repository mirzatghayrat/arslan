# F3 MCP 工具的参数表按供应商规整；一个坏工具不再拖垮整轮对话

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | 热修版 |
| 分级 | 必须 |
| 依赖 | F5a |
| 合并位置 | F 线，F5a 之后不分先后；K7 依赖本卡 |
| 推动的门槛 | §5.2「MCP 引起的整轮失败 = 0」；§5.3 第 4 条 |
| 分支 | `claude/0162-f3-mcp-schema` |
| 迁移号 | 无 |

## 目标

1. **发出去之前先规整。** MCP 工具的参数表在发给供应商之前，按这家供应商能接受的形状规整一遍。
2. **被拒时只降级那一个工具。** 供应商因为某一个工具回 400 时，只把这个工具降级，然后重试一次。整轮对话不能失败。

## 现状（亲核）

参数表从发现到发出，一路都是原样：

1. **发现时原样存下**（`server/mcp/discovery.py:212-227`）。
2. **每轮全发：** 每个就绪服务器的全部工具，每轮都带着 `input_schema` 发出（`server/orchestrator/arslan.py:1346-1369`）。
3. **原样透传：**
   - `_tool_params` 先用内置表，再用存下的 schema，最后退回宽松表（`server/orchestrator/tool_loop.py:1688-1710`）；
   - `_native_tool_schemas`（`:1713-1728`）；
   - 在 `:2168` 生成。
4. **各家供应商原样转发：**
   - Anthropic：`input_schema`（`arslan/llm/providers/anthropic_provider.py:211-236`）；
   - OpenAI 兼容：`payload["tools"] = tools`（`openai_provider.py:173-176`）；
   - Gemini：`parametersJsonSchema`（`gemini_provider.py:107-117`）。
5. **400 直接抛出：** 400 不匹配上下文和协议规则时，归为 `input`（`server/orchestrator/model_call.py:84-106`），不重试，直接抛出（`:129-166`）。
   - `_model_call` 现有三种恢复，都不管工具：图片读成文字、换旧协议、压缩上下文（`tool_loop.py:569-594`）。

## 改哪些文件

- **新增纯函数模块** `arslan/llm/tool_schema.py`：
  - 输入一份 JSON Schema 和供应商类别，输出规整后的 schema。不碰网络，不读库。
  - **Anthropic：** 顶层是 `anyOf` / `oneOf` / `allOf` 时，合并成一个 `type: object`：
    - 各分支的 `properties` 取并集，`required` 取交集；
    - 原来的约束写进 description 的一句话里。
  - **OpenAI 兼容（DeepSeek 等）：** 递归去掉对方不收的关键字，至少有 `pattern`。去掉的约束同样写进 description。
  - **Gemini：** 只做顶层合并。
  - 同样的输入永远给出同样的输出，键序固定。否则提示词缓存的前缀会变，见 `arslan.py:1357-1363` 的注释。
- **三个 provider 在翻译工具时调用它：**
  - 只处理 MCP 工具，也就是 key 以 `mcp_` 开头的；
  - 内置工具的参数表一字不改。
- **`server/orchestrator/tool_loop.py`**（热点文件，只改两处：`_model_call`（`:517-596`），和生成参数表的 `:2168`；`_model_call` 今天不带 `conversation_id`，要从调用方传进去）：
  - 新加一个恢复分支：`input` 类 400，错误原文里能认出某一个 MCP 工具（名字或序号）时：
    - 本轮去掉它，重试一次；
    - 记进进程内的 `_BAD_TOOLS[conversation_id]`，这个对话后面的轮次在 `:2168` 生成参数表时跳过它（仿 `:479` 的 `_REFUSES_IMAGES`）。
  - 认不出是哪个工具时：本轮去掉全部 MCP 工具，重试一次。
  - 以上两种都只试一次，不循环。
  - 降级时写一条 `conversation_events`，kind 为 `mcp_schema_relaxed`，ref 只带 `{tool_key, provider}`（仿 `:665-676` 的 `_log_degrade_hint`）。M2 用它计数。
  - 告诉模型的话只放进本步的状态说明。不加界面文案，不动 locale。
- **测试：**
  - 新文件 `tests/server/test_mcp_schema_normalise.py`；
  - `tests/server/test_native_tool_schemas.py` 里补「内置工具不变」的断言。

## 不许碰

- 发现和入库的逻辑（`discovery.py`），以及数据库里存的原始 schema。规整只在发出时做，原样保留便于以后对照。
- MCP 工具的按需取用归 K7，审批归 S1。
- `web/src/locales/*`、Bridge 文件。

## 怎么做（要点）

1. **夹具一律合成**，形状照 10-14 的事故，内容不用那个服务器的任何东西。至少三个：
   - 顶层 `anyOf`；
   - 嵌套 `pattern`；
   - 一个正常工具。
2. **错误原文不在仓库里。**
   - Anthropic 的报错一般按序号点名工具（`tools.<n>…`）。这是按常见报错形状推断的，未核。DeepSeek 的报错形状也未核。
   - 开工时向用户要一段去掉服务器名的错误原文。要不到就按两家的公开文档写，并在 PR 里标「未核」。
3. **认出工具的方式：**
   - 从错误原文里取序号，对回本次请求的 tools 列表；
   - 或者取名字，和 `mcp_` key 或外部名比对。
   - 两种都只认本次请求里确实存在的工具，参照 `arslan/llm/param_heal.py` 的做法：只改本次请求里真有的东西。

## 验收

- **规整函数的单元测试：** 三种形状 × 三类供应商。内置工具的参数表逐字相等。
- **两家各一个回放：**
  - 用存下的错误形状，在 Anthropic 和一个 OpenAI 兼容端点的替身上回放；
  - 第一次请求回 400、点名一个工具；
  - 第二次请求里没有这个工具，回合正常结束，记下一条 `mcp_schema_relaxed`。
- **认不出工具时：** 第二次请求不带任何 MCP 工具，回合照样结束。
- **同一对话的下一轮**：直接不带那个工具，不再先撞一次 400。
- **非 MCP 原因的 400**（比如 key 错、余额不足）照旧按原分类处理，不重试。

## 量级

产品代码约 120–180 行（新模块约 80 行），外加测试。

## 风险与回退

- **规整改变了参数的含义。** 比如合并 `anyOf` 时把两个互斥分支的字段放到了一起。
  - 模型可能传出服务器不接受的组合，服务器自己会报参数错误，至少整轮不会失败。
  - 在 description 里写明原来的约束，可以减少这种情况。
- **`_BAD_TOOLS` 只在进程内存里**，重启后第一次请求会再撞一次 400，再降级一次。热修版接受这个代价。
- **回退：** revert 合并提交。没有存下的状态。
