# G1 · 工具传输层 —— spec（门外第一批）

base main = `bebb87a`（v0.1.14）。上游：作战图 §G1（`docs/specs/2026-07-31-product-gap-assessment.md`），
用户 2026-08-01「开 G1」。**本 spec 只定形状，等审，不实现。**

**一句话**：Anthropic 和 Gemini 收下 `tools` 参数然后**原样丢弃**，
所以在这两家上，装备好的工具**一个都不会触发，而且没有任何东西告诉用户**。

---

## 0. 前置核实（亲核 `bebb87a`，逐条带 FILE:LINE）

| # | 主张 | 证据 |
|---|---|---|
| V1 | `tools` 是 provider 契约的一部分，不是可选扩展 | `arslan/llm/providers/base.py:39-46` — `chat(messages, tools=None, temperature)` 是 `@abstractmethod` |
| V2 | **OpenAI 系正常序列化** | `openai_provider.py:72-73` — `if tools: payload["tools"] = tools` |
| V3 | **Anthropic 丢弃，但有披露** | `anthropic_provider.py` 全文 `tools` 只出现 4 次：两个签名（`:160`/`:184`）+ 模块 docstring + `:144` 行内注释。**从不进 payload** |
| V4 | 🔴 **Gemini 丢弃，且零披露** | `gemini_provider.py` 全文 `tools` 只出现 **2** 次，**都是签名**（`:99`/`:125`）。没有 docstring 说明、没有注释。读代码的人会以为它工作 |
| V5 | 生产路径**确实传** tools | `tool_loop.py:1048` — `a.chat(system, user, history=history, tools=tools)` |
| V6 | 工具结果以 **provider 中性纯文本**喂回 | `tool_loop.py:279-281` — `{"role":"user","content": f"TOOL RESULT for {tool_key}:\n{framed}…"}`。wire 历史里**从不出现** `tool_use`/`functionCall` 块 |
| V7 | 🔴 **Anthropic 那句免责理由是过期的** | 它写「Arslan drives tools via its own prompt/JSON protocol」。而 `tool_loop.run()`（那个协议）**零生产调用方**：全仓只有 `run_native`（`spawn_loop.py:49`、`arslan.py:1055`）。**披露还在，理由已经不成立** |
| V8 | 工具描述**不在系统提示里**，`tools=` 是唯一通道 | `tool_loop.py:1142` — `system = system + _NATIVE_EFFICIENCY + "\n\n" + GUARD_NOTE`，无工具描述 |
| V9 | MCP 工具行来自**无 `order_by`** 的 select | `arslan.py:1749-1751` — `select(Tool).where(...)`，排序由 SQLite 决定 |

### ⇒ 由 V4+V5+V8 推出的硬结论（比"工具被丢弃"更严重）

**在 Anthropic 和 Gemini 上，`run_native` 根本不是一个工具循环，是一次单发 chat 调用。**

模型在**任何通道**都收不到工具 schema ⇒ `tool_calls` 恒空 ⇒
循环第 0 步就走「no tool_calls → content IS the final answer」直接返回。

唯一例外：`force_tools`（**仅 spawn 路径**）会**绕过模型**确定性地预跑至多一次 `web_search`
（`tool_loop.py:1164-1181`，靠 `tool_intent.classify` 判断，不问模型）。
除此之外——**每一个 MCP 工具、每一个技能、recall/remember、整个装备面——永不触发，且静默。**

### 📌 一件要说清楚的事：这不影响用户当前日常

用户主力是 **DeepSeek**，走 OpenAI 兼容路径（V2）⇒ **今天是好的**。
G1 修的是「换到 Anthropic/Gemini 就静默失能」，不是「现在坏了」。
**这决定了它的紧迫度，也决定了验收必须在那两家上做，不能在 DeepSeek 上做。**

---

## 1. 为什么便宜：V6 让最贵的那一半不必做

Anthropic 的严格约束是：**若 assistant 轮含 `tool_use`，紧随的 user 轮必须含配对的 `tool_result`**。
而 V6 说我们**从不把原生块回写进历史**——回写的是文本。
⇒ **配对约束根本不触发**，对齐只需两件事：

1. **请求翻译**：中性 schema → 各家原生形状
2. **响应解析**：各家原生工具调用形状 → `LLMResponse.tool_calls`

🔴 **这条便宜是有前提的，实现轮不许破坏它**：一旦开始把原生 `tool_use` 块回写进历史，
配对约束立刻生效，成本从「两件事」变成「全套往返 + 每个错误路径的配对维护」。
`_record_tool_result` 现在 append 的 `assistant_content` 是**文本**，必须保持是文本。

流式也不必动：`run_native` 只走 `adapter.chat`，不走 `chat_stream`（V5）。
但 `chat_stream` 的签名同样收 `tools` 同样丢弃——**拍板项 ④**。

---

## 2. 三家的 wire 形状（作战图已逐条对官方文档核过：23 条 → 22 CONFIRMED / 1 PARTIAL / 0 WRONG）

| | 请求 | 响应 | schema |
|---|---|---|---|
| OpenAI 系 | `tools[].function` | `tool_calls[]`，**arguments 是字符串** | 完整 JSON Schema |
| Anthropic | `tools[].input_schema` | `tool_use` 内容块 | 完整 JSON Schema |
| Gemini | `functionDeclarations` | `functionCall` part | **OpenAPI 子集**（白名单） |

从 litellm 沉淀里搬进来的知识（**不引 litellm 本体**——重依赖 + env 副作用，不适合冻结 sidecar）：
Gemini schema 白名单 + `$defs` 内联 · Anthropic 工具名清洗 · `required` 处理 · 缺失 id 合成。

---

## 3. 🔴 一个硬要求：tools 序列化必须**逐字稳定**

Anthropic 的缓存渲染序是 **tools → system → messages**，断点打在 system 前缀。
⇒ **`tools` 的任何重排都会击穿整个前缀缓存。**

而 V9：MCP 工具行来自无 `order_by` 的 select。今天无害（tools 根本没发出去），
**修好之后它立刻变成一个每次请求都可能击穿缓存的随机源。**

⇒ 实现轮**必须**同时做：`order_by` 定序 + 一条断言「同样输入两次序列化逐字相同」的测试。
参考先例：缓存效率轮把命中率从 80.5% 提到 98.5%，那份收益全在这条前缀上。

---

## 4. 九步（作战图判定：多数 small）

1. 中性工具 schema 类型 + `order_by` 定序（V9）
2. `openai_provider`：现状即正确，补一条「序列化逐字稳定」测试作基准
3. `anthropic_provider`：请求翻译（`input_schema`）
4. `anthropic_provider`：响应解析（`tool_use` 块 → `tool_calls`）
5. `gemini_provider`：请求翻译（`functionDeclarations` + schema 白名单/`$defs` 内联）
6. `gemini_provider`：响应解析（`functionCall` part）
7. **删掉 V7 那句过期理由**，换成对现状为真的说明；Gemini 补上它从来没有的披露
8. 适配性矩阵翻绿——**只对实测通过的那一格**（反向诚实徽标已有先例）
9. 回归：`run_native` 在三家上都真的进入多步循环

---

## 5. 不做（防蠕变）

引 litellm · 把原生 `tool_use` 块回写进历史（§1 的前提）· 动 `chat_stream`（除非 ④ 判 A）·
动 `tool_loop` 的循环结构 · 借机重构 adapter 层。

---

## 6. 拍板项

① **顺序**：A（推荐）Anthropic 先、Gemini 后（Anthropic 是 MCP 生态主场，且它已有披露=改动面清楚）。B：两家一起。
② **验收怎么做**：A（推荐）用**真 key 在两家上各跑一次真实多步工具循环**并留 wire 证据；B：只做单元级翻译/解析测试。
  🔴 我的立场：B 不够。这个 bug 的形状就是「单元测试全绿而真机静默失能」——
  只测翻译函数**证明不了模型真的调用了工具**。但 A 要花用户的钱，且需要用户提供两家的 key。
③ **`order_by` 定序**：A（推荐）本轮做（它是 §3 的硬前提，分开做等于留一个已知会击穿缓存的洞）；B：单独一轮。
④ **`chat_stream` 的 tools**：A：一并修（面对称，但 `run_native` 用不到，属未被验证的代码）；
  B（推荐）：**不修，改为显式拒绝**——收到 `tools` 就抛，而不是静默丢弃。理由：静默丢弃正是本轮在修的病，
  在同一轮里给它留一个新出口说不过去；而没有调用方的功能不该带着"看起来能用"的签名活着。

---

## 7. 验收（写死，实现轮照抄）

- **三家各一条「序列化逐字稳定」测试**：同输入两次 → 字节相同；mutation：去掉 `order_by` 必红。
- **Anthropic/Gemini 各一条「真的进入多步循环」测试**：断言 `tool_calls` 非空且循环步数 > 1。
  🔴 断言必须能区分「工具触发了」和「模型自己写了段像工具调用的文字」——
  只断言输出里出现工具名是无区分力的。
- **一条探针先证明自己能失败**：在**未修的** provider 上跑同一条断言必须红（照 v0.1.12 干净 runner 先例：
  探针先证明前提，再作能力声明）。
- **适配性矩阵的绿格必须有实测出处**，不许默认绿（反向诚实徽标先例）。
- **V7 的过期理由删除有测试钉住**：断言 docstring 不再声称一个零调用方的协议在驱动工具。

---

## 8. 尚无证据、未声称已验

- **本 spec 一行代码没写。** 九步的「多数 small」是作战图的判断，不是本轮实测。
- **Gemini 的 OpenAPI 子集具体白名单未在本仓复核**：来自 litellm 沉淀 + 官方文档，
  实现轮第一件事是拿真 schema 打一次真请求确认拒绝面。
- **「配对约束不触发」是从 V6 推出的，不是实测**：wire 历史里没有 `tool_use` 是代码事实，
  但 Anthropic 收到「带 tools 的请求 + 纯文本 assistant 历史」是否真的不抱怨，**要真请求才算数**。
  这是拍板项 ② 选 A 的第二个理由。
