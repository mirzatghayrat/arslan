# 0.1.49 P1 设计：执行层「稳」——原生工具协议、截断、故障恢复

状态：**设计稿**（extra 档写成），实施按下文步骤在 medium 档进行；标 ⚠️extra 的两步建议切回 extra。日期 2026-10-01。
上位文档：`docs/plans/2026-10-01-kernel-upgrade-plan.md`（分支 `claude/kernel-bakeoff-plan`）第 2 节 P1。
外部依据：DeepSeek 官方 thinking mode 文档（2026-10-01 读取）、DeepSeek 模型/价格页、《深入理解 AI Agent》第 2、4、5、7 章。

## 0. 一句话

把 `run_native` 的内部历史换成**中立轨迹**（OpenAI 形状 + 不透明续接字段），在**请求时**按厂商渲染：OpenAI 兼容端点（DeepSeek 等）走原生 `tool_calls` / `role:"tool"` 并原样回传 `reasoning_content`；Gemini 渲染成现有的 provider_content 对；Anthropic、测试替身和回滚开关渲染成**今天逐字相同**的文本格式。再在模型调用外包一层「故障分类 + 截断状态机 + 熔断」，用流式和空闲看门狗替换 75 秒总超时。

## 1. 现状（亲核，带行号；分支 `claude/0149-kernel` = `441a1f29`）

| # | 事实 | 位置 |
| --- | --- | --- |
| F1 | 每次工具调用往 `convo` 追加一对：assistant `{"tool":…,"args":…}` JSON + **user** 消息 `TOOL RESULT for X:\n…\nUse this to continue…` | `server/orchestrator/tool_loop.py:300-331`（追加在 `:314`、`:328`） |
| F2 | 一批调用结束后，assistant 那半被改写成散文 `Native tool invocation completed: X`；Gemini 例外，改成 provider_content + function_response 对 | `tool_loop.py:1617-1644` |
| F3 | 模型调用把 `convo[-1]` 当成 `user` 参数传入，历史只能以 user 消息结尾 → 原生的 `role:"tool"` 结尾**进不了现有 adapter 接口** | `tool_loop.py:1538-1544`；`arslan/llm/adapter.py:73-90`；`providers/base.py` `build_messages` |
| F4 | `_parse_response` 不读 `reasoning_content`、不读 `finish_reason`；参数 JSON 解析失败就留原字符串 | `arslan/llm/providers/openai_provider.py:263-300`（`:281`） |
| F5 | **参数不是 dict 就换成 `{}` 然后照样执行**——被截断的调用会以空参数真的跑一次 | `tool_loop.py:1554-1555` |
| F6 | 输出上限有**两道** 8192：provider 默认值和执行预算的每请求上限 | `openai_provider.py:29`；`arslan/execution_budget.py:30`（另 `arslan/companion/contracts.py:60`） |
| F7 | 模型调用总超时 75 秒（非流式），httpx 60 秒；DeepSeek 非流式等待期间会持续发空行保活，所以真正起作用的只有 75 秒总超时——思考模型一放宽输出就会被它当成失败杀掉 | `tool_loop.py:1200`；`openai_provider.py:132` |
| F8 | 重试：`_chat_retry` 共 2 次、固定 0.2 秒间隔，不读 Retry-After，不区分 402/400 原因 | `tool_loop.py:1255-1272`；`arslan/runtime_policy.py:24-40` |
| F9 | 预算按**原始 token 总数**扣（含缓存命中的输入）；聊天轮上限 128k。原生协议回传思考后输入 token 变多但大部分是缓存命中，按原始数扣会**提前触发预算停止** | `arslan/llm/usage_sink.py:20`；`execution_budget.py:25-31` |
| F10 | 工具结果超过 8000 字符**直接截断 JSON 字符串**，模型看到的是断掉的 JSON、没有任何提示 | `tool_loop.py:307` |
| F11 | `read_file` 没有 offset/limit，落盘的长输出没法分段读 | `tool_loop.py:855-858` |
| F12 | 压缩 `bounded_history` 只认 Gemini 的 provider_content 对为不可拆分组 | `arslan/runtime_policy.py:112-150` |
| F13 | 轨迹不落库：checkpoint 只存预算与进度指纹，不存 convo → **改内部格式不需要迁移** | `server/services/task_service.py:182-197` |
| F14 | 79 个测试文件引用 tool_loop/run_native，56 个测试文件里的替身实现 `chat(system, user, history, tools)`；8 处断言 `TOOL RESULT` 文本 | `tests/` |

DeepSeek 协议事实（官方文档）：
- 请求带 `tools` 时，assistant 消息的 `reasoning_content` **必须原样回传**，否则 400；「即使那一轮没调工具」也要。
- 不带 `tools` 时回传的思考会被忽略。
- 思考默认开、默认强度 high；`{"thinking":{"type":"disabled"}}` 关，`reasoning_effort` 取 low/high/max。
- v4-flash / v4-pro：上下文 1M，**最大输出 384K**；支持 tool calls、chat prefix completion。

**S10 契约探针实测（2026-10-01，deepseek-v4-flash，经计量代理，合计 $0.0020 峰值价）**

脚本 `scripts/kernel_bench/contract_probe.py`，原始结果在本机 bench 目录。

| 情形 | 结果 |
| --- | --- |
| 本轮两步工具循环，回传 `reasoning_content` | 200 |
| 本轮 tool_calls 消息**去掉**思考（首步有 242 字符思考），带 tools | **200**（文档说会 400，实测不拦） |
| 同上，思考置为空串 | 200 |
| 同上，不带 tools | 200 |
| 旧用户轮：纯文本 assistant、无思考，带 tools | 200 |
| 旧用户轮：assistant tool_calls + tool 结果、无思考，带 tools | 200 |
| 强制步：同一份 tools + `tool_choice:"none"` | 200，无 tool_calls，正常作答 |
| 思考开、`max_tokens=64`、长文 | `finish_reason:"length"`，思考 184 字符 + 正文 71 字符（**上限同时覆盖思考与正文**） |
| 思考关、`max_tokens=64`、长文 | `length`，正文 311 字符被截 |
| 思考关、`max_tokens=64`、`write_file` 长内容 | `length`，tool_call 存在，`arguments` 是**半截 JSON**（149 字符，未闭合），id/name 完整 |
| 简单任务首步 | 思考 0 字符（flash 会对简单步骤跳过思考） |

结论：
1. **今天的 400 风险不存在**：DeepSeek 目前不强制回传思考。原生协议在兼容性上可以放心上。降级口（4.4）保留为防将来收紧的保险，但不再是主路径。
2. **D1 的收益必须靠测量证明**。上位计划写「Arslan 只是因为历史不原生才没撞 400」，这是错的：根本不会 400。回传思考与原生配对是否让模型少走弯路，是质量问题而不是兼容问题，以第 8 节配对对照为准。
3. 截断形状与 5.2 的假设一致：半截参数以「解析失败的字符串 + finish_reason=length」出现。今天的代码会把它换成 `{}` 执行（F5）。思考也计入上限，所以 5.1 的放宽是必要的。

## 2. 目标与不做的事

目标（P1 验收，见第 8 节）：T5 Pass^3；故障注入 429/500/超时/流式卡死/三处截断全部「恢复或带原因报错」；与 legacy 渲染配对比较时调用次数、输出 token、用时不升。

**本轮不做**（各自归属）：
- 状态栏 / 系统提示词字节冻结（P2.1）。
- 分层压缩与旧工具参数遮蔽（P2.4）。
- Anthropic 原生 tool_use/tool_result（需要真 key 验证，列为后续）。
- 跨轮持久化思考（成本未评估）。
- 命令沙盒（P3）。

## 3. 中立轨迹（内部表示）

`convo` 里只存四种消息，全部是普通 dict（便于 `json.dumps` 计算大小、便于 `{**m, "content": …}` 这类现有改写继续成立）：

```python
{"role": "user", "content": str | blocks}                       # 用户请求 / 宿主提示
{"role": "assistant", "content": str | None,
 "tool_calls": [{"id": str, "name": str, "arguments": dict | None,
                 "arguments_raw": str}],                         # 可为空列表
 "_continuation": {"protocol": "openai", "endpoint": fp,       # 不透明，只回给同一端点+模型
                   "fields": {"reasoning_content": "..."}}      # 或 {"protocol":"gemini","parts":[...]}
                  | None,
 "_finish": "stop" | "length" | "tool_calls" | ...}            # 只供本地判断，不上线
{"role": "tool", "tool_call_id": str, "name": str, "content": str,
 "_synthetic": bool}                                            # 宿主代跑（预搜索）为 True
```

规则：
1. **每个 assistant 的 tool_call id 后面恰好跟一条同 id 的 tool 消息**，中间不插别的；批内顺序与 tool_calls 顺序一致。所有提前结束分支（`policy.stopped`、wrap_up 拒绝、凭据拒绝、worker 越权、参数无效、截断不执行）都必须补一条错误 tool 消息——今天的 `_record_tool_result` 已经对每个调用都写一条，只是改写成 tool 消息。
   - 两个例外直接 `return`、不再请求模型，因此不违反不变量：`escalate` 与合法的 `ask_user_choice`。
2. `_continuation` 由 provider 解析时生成，`endpoint` 指纹 = `sha256(base_url + model)[:16]`。渲染时指纹不同就丢弃（同一 `run_native` 内 adapter 固定，正常不会发生；防将来中途换模型）。
3. id 缺失或本轮内重复时（部分兼容服务器给空 id 或总是 `call_0`），解析时改写为 `call_<step>_<i>`，渲染时一致使用改写后的 id。
4. `arguments_raw` 保留服务器给的原字符串，渲染时原样回传（不重新序列化）；`arguments` 是解析结果，解析失败为 `None`。
5. 宿主代跑的预搜索（`force_tools`，`tool_loop.py:1453-1471`）没有模型发起的调用，**不伪造** assistant tool_calls 消息（伪造的 assistant 没有思考，DeepSeek 可能 400）。改为 `_synthetic` tool 记录。原生渲染成一条 user 消息「Automatic pre-search (not requested by you) — RESULT for web_search: …」，legacy 渲染保持今天的形状。
6. 压缩按组驱逐：一组 = assistant + 它的全部 tool 消息（今天 legacy 对里的两半各自成组，可能只剩半截）。组大小按**实际渲染后要发出的形式**计算（`bounded_history` 增加 `size_of` 参数）——否则 legacy 模式会把不发送的思考和原始参数也算进窗口，压缩比今天更激进。
7. 不变量检查 `trajectory.validate(messages)` 在**每次原生请求前**运行：测试里抛错；生产里记一条事件并对本轮改用 legacy 渲染（4.4 同一个降级口）。

新模块 `arslan/llm/trajectory.py`（纯函数，无 I/O）：`assistant_from(resp, step)`、`tool_result(call, content, synthetic=False)`、`validate`、`groups`（压缩用）、`to_legacy`、`to_gemini`。

## 4. 渲染与传输

### 4.1 三种渲染，一个入口

`tool_loop._model_call(a, system, convo, current_request, *, tools, tool_choice)` 是 run_native 里唯一的模型调用点，替代 `_chat_retry(a, sys_now, convo[-1]["content"], history=…)`：

- `a` 有 `chat_trajectory` 且 `a.native_trajectory()` 为真（OpenAI 协议的 `LLMAdapter`，且开关未关）→ `a.chat_trajectory(system, messages, tools=…, tool_choice=…)`。
- 否则 → `legacy = trajectory.to_legacy(messages)`（Gemini 适配器则用 `to_gemini`），再调现有 `a.chat(system, legacy[-1]["content"], history=legacy[:-1], tools=…)`。56 个测试替身都没有 `native_trajectory`，**自动走 legacy 渲染，原测试不改**。

`to_legacy` 必须**逐字**复现今天的 payload：每个调用渲染成 assistant `Native tool invocation completed: X` + user `TOOL RESULT for X:\n{content}\nUse this to continue: call another tool, escalate, or give your final answer.`。`_synthetic` 记录保留今天预搜索那半 assistant 的原始 JSON（今天如此，见 F2 的替换只覆盖 `history_start:`）。

`to_gemini` 搬运 `tool_loop.py:1617-1634` 的现有逻辑。两者都用**黄金测试**锁定：对同一脚本，新旧代码产生的 provider 请求体逐字节相等（在改代码之前先录下旧 payload）。

### 4.2 OpenAI 兼容原生渲染（provider 内，翻译只在一处）

`OpenAIProvider.build_trajectory_messages(system, messages)`：
- assistant → `{"role":"assistant","content": content or "", "tool_calls":[{"id","type":"function","function":{"name","arguments": arguments_raw}}]}`；`tool_calls` 为空时不带该键；`_continuation.fields` 指纹匹配时合并进消息（`reasoning_content` 等）。
- tool → `{"role":"tool","tool_call_id": id, "content": content}`。
- 以 `_` 开头的私有键一律剥除（单测钉住：线上 payload 里不出现任何 `_` 键）。

回传哪些续接字段用**白名单**：`reasoning_content`（DeepSeek/Kimi/GLM/Qwen 兼容端）、`reasoning`、`reasoning_details`（OpenRouter 形状）。原则是「收到什么回什么」：响应里没有的字段绝不凭空添加，避免对严格端点发未知字段。

### 4.3 强制作答步保留工具前缀

今天强制步传 `tools=None`（`tool_loop.py:1543`）。原生模式改为**照传同一份 tools + `tool_choice:"none"`**，理由有二：
1. 历史里有 tool_calls/tool 消息时去掉 tools 定义，是否被各兼容端接受没有保证。
2. tools 是缓存前缀的一部分，删掉会让整段前缀缓存失效。

wrap_up 仍按今天传子集（是否改「遮蔽不删除」归 P2，需要测量）。legacy 路径行为不变。

### 4.4 开关与自动降级

- `ARSLAN_TOOL_PROTOCOL=native|legacy`，默认 native（仅对 OpenAI 协议生效）。用于对照测量和紧急回滚。
- **本轮降级熔断**：原生请求收到 400 且错误体提到 `reasoning_content` / `tool_call_id` / `tool_calls`，或 `validate` 失败时：
  - 同一条轨迹立即用 legacy 渲染重发一次，本轮余下都用 legacy；
  - 记 `protocol_degraded` 事件（conversation_events）；
  - 每轮最多一次。
- 中立轨迹的价值就在这里：降级是换渲染函数，不是改历史。

## 5. 输出预算与截断（P1.2）

### 5.1 输出预算表 `arslan/llm/output_budget.py`

| 端点 | 初始 max_tokens | 截断后上调到 | 依据 |
| --- | --- | --- | --- |
| DeepSeek 官方（v4-flash / v4-pro / flash） | 32 768 | 131 072 | 官方最大输出 384K；按实际生成计费，不预占额度 |
| OpenRouter | 8 192（保持） | 32 768 | v0.1.25 事故：OpenRouter 按 max_tokens 预占额度，额度不足直接拒（`openai_provider.py:21-28` 注释） |
| 其他 OpenAI 兼容 / 本地 | 8 192 | 16 384 | 未知端点保守 |

- `Limits.output_tokens_per_request` 默认改为 131 072，只作失控护栏。companion 合同同步。
- `model_request()` 裁小时（剩余预算不够），记 `clamped_by_budget=True`。这种截断**不走上调**，直接按「预算用尽」收尾，防止「截断→上调→被预算裁→再截断」空转。

### 5.2 截断状态机（每个模型步内）

`finish_reason == "length"` 时（Anthropic `max_tokens`、Gemini `MAX_TOKENS` 归一成 `length`）：

1. **含 tool_calls** → 本响应里的调用**一个都不执行**（最后一个的参数大概率不完整，前面的也无法证明完整）。
   - 用上调后的上限静默重发同一请求（不把截断的响应写进轨迹）。
   - 仍截断 → 写入轨迹：一条 assistant（带思考，DeepSeek 要求）+ 每个调用一条错误 tool 消息：「output limit reached while writing this call's arguments; nothing was executed. Split the work: write the file in parts (write_file then edit_file / append) or shorten the payload.」让模型改分批。
2. **纯正文** → 先静默上调重发；仍截断则**续写**：把半截正文作为 assistant 消息写入，再追加 user「Continue exactly where you stopped. Do not repeat.」，拼接结果。最多续写 2 次。
3. **只有思考没有正文/调用**（思考吃光上限）→ 上调重发；仍然如此则本步按「无可用输出」进入现有修复路径，不续写思考。

熔断（每轮）：上调 ≤ 2 次、续写 ≤ 2 次、截断导致的「不执行」≤ 3 次。超过就停，给出带原因的结果：「模型输出连续触顶 N 次，已尝试：上调到 X、续写 Y 次」。

### 5.3 预算按加权 token 计（F9）

`usage_sink` 在有缓存明细时按「未命中输入 + 0.1×命中输入 + 输出」扣预算。各家字段：
- DeepSeek：`prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`；
- OpenAI：`prompt_tokens_details.cached_tokens`；
- Anthropic：`cache_read_input_tokens`；
- Gemini：`cachedContentTokenCount`。

没有明细时退回原始总数（不变）。用量报表（花费显示）仍记原始数，不受影响。DeepSeek 价格里命中价约为未命中的 1/30，0.1 是偏保守的护栏权重。

## 6. 故障分类与恢复（P1.3）

新模块 `server/orchestrator/model_call.py` 取代 `_chat_retry`，承载 5.2 的状态机和以下分类：

| 类 | 判据 | 动作 |
| --- | --- | --- |
| 可重试·限流 | 429；503 带 Retry-After | 等待 `Retry-After`（上限 60 秒，且不超过剩余墙钟预算），否则指数退避 1/2/4/8 秒 + 0–50% 抖动；最多 4 次 |
| 可重试·服务端 | 500/502/503/504、连接断、读超时 | 同上退避，最多 4 次 |
| 可重试·卡死 | 流式在 90 秒内无任何**有效增量**（思考/正文/工具参数；`: keep-alive` 注释和空行不算） | 断开重发，计入上面的 4 次 |
| 不可重试·余额 | 402，或错误体含 insufficient balance / quota | 不重试；报「模型服务余额不足」+ 原文摘录 |
| 不可重试·认证 | 401/403 | 不重试；报「密钥无效或无权限」 |
| 上下文溢出 | 400 且错误体含 context length / maximum context / too many tokens | 用更小窗口（当前 ×0.5）压缩后重发一次 |
| 协议不兼容 | 400 且涉及 reasoning_content/tool_call_id/tool_calls | 4.4 降级 |
| 其他 400/422 | — | 不重试；原文摘录交给用户 |

- **死亡螺旋防护**：模型调用失败（上表任一类最终失败）后，run_native 的错误出口**不再调用任何会请求模型的修复**（`_synthesize_from_findings`、`_salvage_plain`、验收修复）。直接用确定性的 `_fallback_with_digest`（有工具结果时）或抛 `ModelCallError`。测试用计数替身钉住：失败后模型调用次数不再增加。
- **每轮总熔断**：模型错误恢复合计 ≤ 8 次。
- **报错带真实原因与已做的恢复**：`ModelCallError(kind, status, provider_excerpt, attempts, waited_s, recoveries)`；现有 `llm_errors.error_frame`（`server/orchestrator/arslan.py:667-690` 的出口）渲染成「DeepSeek 返回 503（服务繁忙），已退避重试 4 次共 23 秒」。永不出现空错误消息（小样里的空 `LLM_ERROR`）。
- **流式与看门狗**：原生路径下 `OpenAIProvider.chat()` 内部改用 SSE 收齐后返回完整 `LLMResponse`（tool_loop 仍是一问一答，不引入部分执行）。
  - tool_call 增量按 `index` 合并，`id`/`name` 取首次出现，`arguments` 字符串拼接；
  - `reasoning_content` 增量另行拼接；`finish_reason` 取最后一个非空值；
  - usage 取尾帧。
  - 总时长不再用 75 秒，而用 `min(剩余墙钟预算, 600 秒)`；卡死靠上面的 90 秒空闲判定。
  - 流式收齐只对已知支持流式工具调用的端点开启（DeepSeek 官方、OpenAI 官方、OpenRouter）。其他兼容端点（旧版本地服务器常见流式工具调用不完整）仍用非流式，总超时放宽到 300 秒。
  - 部分生成也计费，所以重发次数计入熔断。

## 7. 实施步骤（每步一个提交，先写测试）

| 步 | 内容 | 档位 |
| --- | --- | --- |
| S1 | `LLMResponse` 增加 `finish_reason`、`continuation`、每个 tool call 的 `arguments_raw`；三家 provider 解析（OpenAI 读 `reasoning_content`/`reasoning`/`reasoning_details` 与 `finish_reason`；Anthropic `stop_reason`；Gemini `finishReason`）；usage 缓存明细归一。**零行为变化** | medium |
| S2 | `arslan/llm/trajectory.py` + 黄金测试：在改 tool_loop 之前，先用现有代码录下 legacy 与 Gemini 场景的完整请求体，作为 `to_legacy`/`to_gemini` 的对照基准 | medium |
| S3 | run_native 改写为中立轨迹：`_record_tool_result` 写 tool 消息；每个模型响应写一条 assistant；删除 `:1617-1644` 的事后改写；`bounded_history` 按「assistant + 其 tool 消息」分组；预搜索改 `_synthetic`；`research_review.compact_saved_context` 在原生模式下不再追加 DRAFT（草稿已在 tool_calls 参数里，否则重复占窗口）；`_model_call` 入口 | ⚠️extra |
| S4 | `LLMAdapter.chat_trajectory` / `native_trajectory()`；`OpenAIProvider.build_trajectory_messages`；强制步 `tool_choice:"none"`；开关 `ARSLAN_TOOL_PROTOCOL` | medium |
| S5 | 输出预算表、`Limits` 与 companion 合同上限、预算裁小标记、加权 token 扣费 | medium |
| S6 | `model_call.py`：分类、退避/Retry-After、截断状态机、续写、降级、熔断、`ModelCallError` 与 `error_frame` 渲染；错误出口去掉模型修复调用 | ⚠️extra |
| S7 | OpenAI SSE 收齐（tool_call 增量合并、思考增量、保活忽略）+ 90 秒空闲看门狗 | medium |
| S8 | 工具错误变成模型输入：参数非合法 JSON 时只做 `json.loads(raw, strict=False)` 这一种安全修复（允许字符串里的裸换行），否则不执行并回报解析位置；按 schema 校验必填字段与顶层类型（错误里写期望类型）；未知工具回报最接近的 5 个可用名；`ProgressPolicy` 判为重复时，在 tool 消息的受信框架里写「此结果与之前第 N 次相同，再重复 M 次将停止」 | medium |
| S9 | 长输出落盘：`_record_tool_result` 超过 8000 字符时，完整结果写 `~/Arslan/.arslan/outputs/<turn>/<call_id>.txt`（0600 权限，7 天清理；该目录加入 `read_file` 的只读根，用户另选工作文件夹时也能读），上下文放头 6000 + 尾 1500 + 路径；`terminal_exec.clip` 同样落盘；`read_file` 增加 `offset`/`limit`（按行） | medium |
| S10 | ✅ **已做（用户批准，实付 $0.0020 峰值价）**，结果见第 1 节。原计划：deepseek-v4-flash 发 5 个极小请求：<br>(a) 两步工具循环带思考回传；<br>(b) 旧轮纯文本 assistant + tools，看是否 400（第 1 节未亲证项）；<br>(c) 去掉本轮思考，确认 400 的错误体（给 4.4 的判据取真样本）；<br>(d) 强制步 `tool_choice:"none"`；<br>(e) `max_tokens=64` 分别截在思考/正文/工具参数，取真实 `finish_reason` 与响应形状。<br>结果写进本文档 | medium |

S3 和 S6 标 extra 的原因：
- S3 改 1700 行的核心循环。不变量（配对、续接、压缩分组、所有提前结束分支）分散在十几个分支里，漏一个就是线上 400 或重复副作用。
- S6 的状态机与熔断组合多，「什么时候绝不能再调模型」判断错一次就是死亡螺旋或空报错。

### S3 实施记录（与设计的偏差在此写明）

- **结果绑定换了做法**：设计里写的是给 `_record_tool_result`/`_dispatch_tool` 传 call id。但仓库里有约 40 处测试直接调用这两个函数，研究审阅测试还会替换掉 `_dispatch_tool`。所以改成：记录一律先写成「宿主代跑」；`run_native` 在每个调用前记下位置，批末由 `_claim_results` 按位置绑定 id。批内只追加、不挪动，所以位置可靠。签名不变，所有直接调用照常工作。
- **超大新批次的处理变了（行为变化，非纯重构）**：旧格式下一批结果可以被拆开驱逐，模型只看到其中几条，外加一句系统提示。原生配对不允许拆组，所以现在的处理是：只有未受保护的最新组超限时，从最旧的结果起，把内容换成明确的「已省略，未被看到，请分小块重取」，配对保持完整，并计作压缩。受保护的新批次（≤96k）仍然整组送达。测试 `test_fresh_tool_batch_delivery[39000]` 在这个新行为下依然通过。
- 研究审阅的两处改写在 legacy 渲染里按旧格式还原：网页回执用 `_legacy_raw`（整轮替换、不带抬头），草稿用 `_legacy_suffix`（接在结束语之后）。原生渲染（S4）不带草稿，因为草稿已经在调用参数里。
- **黄金场景从 9 个增加到 10 个**：新增「两次读网页→存报告」的研究压缩场景，是在**改动前的代码**上录的（临时 worktree 检出 `20c16923`，import 自检确认跑的是旧代码）。原有 9 个场景只是工具列表多了两个工具，其余逐字节不变。
- 验收修复路径只在答案正是本次回复原文时才挂续接状态（合成或兜底的答案来自另一次请求）。正反两种情形都有测试，并做过变异验证。

### S6 实施记录（与设计的偏差在此写明）

- **范围**：恢复逻辑（`server/orchestrator/model_call.py`）只作用于每步那一次主模型调用。合成、兜底、审阅这些辅助调用保持原来的「快速重试一次」，失败就放弃，不挤占主链路。原有的 `_chat_retry` 测试因此不变。
- **只包装服务端/传输层错误**：其余照原样抛出，包括 `BudgetExceeded`、`TaskError` 和编程错误。
- **出错出口一律抛 `ModelCallError`，不返回「已完成步骤摘要」**（设计原写「摘要或抛错」）。理由是摘要会被当成答案显示。工具结果已经以事件帧实时展示过，错误帧给出原因和已做过的恢复。测试钉住：持续 503 时一共只请求 5 次，出错后再无任何模型请求。
- **超时**：S7 之前，非流式主调用的总超时从 75 秒放宽到 300 秒（S5 放宽输出上限后，75 秒会误杀正常的长生成），httpx 读超时同步改为 300 秒。我们自己的超时只重试 1 次，因为长生成很可能再次超时，而且每次都计费。
- **被拒的 `tool_choice` 也按协议问题处理**：本轮降级为 legacy 渲染，legacy 在强制步不带工具，避免兼容端点不认 `tool_choice` 时整轮失败。
- **熔断计数（每轮）**：上调输出上限 ≤2 次；续写 ≤2 次；截断导致不执行的批次累计 3 次就强制作答；所有恢复合计 ≤8 次。
- 被截断的调用会进 `ProgressPolicy` 计数。一批里有多个调用都被截断时，「重复无进展」的停止可能先于截断熔断触发，两者结果都是强制作答。
- **尚未修**：参数不是合法 JSON、但也并非被截断的调用，仍按旧行为以 `{}` 执行（F5 的另一半），归 S8。

### S7 实施记录

- **只有原生轨迹路径（`chat_trajectory`）会开流式**，而且只对 DeepSeek 官方、OpenAI 官方和 OpenRouter 开启。辅助调用、legacy 渲染和其他兼容端点照旧非流式。
- **服务器对流式请求仍回了普通 JSON 时**，按原来的方式解析。所以只回 JSON 的测试替身和端点都不受影响。
- **空闲看门狗**：90 秒内没有任何真实增量（思考、正文、工具参数）就判为卡死。`: keep-alive` 注释和空行不算进展。卡死按 `stall` 处理，只重试 1 次。
- **流在中途断开**（既没有 `[DONE]` 也没有 `finish_reason`）时报 `RemoteProtocolError`，按服务端错误退避重试，绝不把半截回复当成答案。
- 每次尝试的外层总上限改为 600 秒（仍受剩余时间预算约束）。卡死交给看门狗判断，非流式回复仍受 httpx 300 秒首字节超时约束。

## 8. 测试计划与验收

**旧测试原则上不改**：79 个经过 tool_loop 的测试文件走 legacy 渲染，必须全绿——这本身就是 legacy/回滚路径的回归证明。唯一预期的例外是断言「压缩后具体剩哪几条」的测试：驱逐粒度从半对变成整组（第 3 节规则 6）。这类改动逐条列在提交说明里并写明原因，不许为了变绿改断言。新测试单独成文件：

1. `tests/llm/test_trajectory.py`：
   - validate 的各类违规（孤立 tool、缺 tool、乱序、重复 id）；
   - `to_legacy`/`to_gemini` 黄金等价；
   - 私有键不上线；
   - 续接字段只回同指纹端点。
2. `tests/server/test_native_trajectory.py`（假 OpenAI 端点用 `httpx.MockTransport`，检查**真实请求体**而不是替身参数）。场景：
   - 单调用、并行 3 调用、批中 `policy.stopped`、wrap_up 拒绝、凭据拒绝、无效参数、未知工具；
   - `ask_user_choice` 参数错、答案被打回（unverified/deferral/protocol 三种）、验收修复；
   - 强制步、压缩驱逐、预搜索。

   每个场景断言：
   - 配对不变量成立；
   - 本轮每条 assistant 的 `reasoning_content` 与上游返回**逐字节相同**；
   - 请求体里没有 `TOOL RESULT for`；
   - 外部结果仍有 `wrap_external` 定界符；
   - 强制步 tools 与前一步逐字节相同且 `tool_choice=="none"`。
3. `tests/server/test_model_call_faults.py`（注入时钟与 sleep）：
   - 429 + Retry-After:2 → 等待 ≥2 秒后成功；
   - 500×2 后成功，恢复记录为 2；
   - 持续 503 → `ModelCallError` 含次数与原文，且失败后模型调用次数不再增加；
   - 402 / 401 不重试；
   - 读超时；
   - 流式只发 keep-alive → 90 秒判卡死；
   - 流式中途断开；
   - 截断在思考 / 正文（续写拼接结果与完整文本逐字相同）/ 工具参数（**写工具执行器调用次数为 0**）；
   - 恒截断 → 熔断后带原因停止；
   - 400 reasoning_content → 本轮降级、只降一次、事件已记；
   - 上下文溢出 → 压缩重发一次；
   - 预算裁小 → 不上调。
4. `tests/llm/test_openai_stream_assembly.py`：
   - tool_call 增量按 index 交错到达、id 只在首帧、arguments 分 7 段；
   - 思考与正文交错；
   - usage 尾帧；
   - 无 `[DONE]` 的提前结束算中断。
5. **变异验证（硬要求）**，每条都要先红后绿：
   - 去掉思考回传；
   - 压缩把一组拆开；
   - 截断时照样执行；
   - 错误出口调 `_synthesize_from_findings`；
   - 看门狗把 keep-alive 当增量；
   - 降级不设上限。

**付费验收（每轮开跑前单独报上限、等你批准）**：
- S10 探针（< $0.01）。
- P1 完成后跑一轮：Arslan-native、Arslan-legacy（只跑 T3、T5，用来把差异归因到协议）、Hermes，T1–T6 × 3。
- 前提：T1/T2/T4/T6 的夹具与检查器先补齐（T4 需你本人登录；T6 需你提供 `BAKEOFF_TELEGRAM_TOKEN`）。
- 预计 ≤ $5，按峰值价估。

**通过线**：
- T5 Pass^3；
- T1–T6 无空错误消息、无失实、无越界；
- native 对 legacy 在 T3/T5 上调用次数、输出 token、用时不升。

决策门沿用上位计划：P1 后仍有 ≥3 类 Hermes 没有的执行层问题，就认真考虑转 Hermes。

## 9. 风险

| 风险 | 缓解 |
| --- | --- |
| 跨轮纯文本旧消息触发 400（第 1 节未亲证项） | S10 探针先证；4.4 自动降级兜底，最坏退回今天的行为 |
| 回传思考使输入变长，压缩更早触发、证据被挤出 | 加权扣费只解决预算；窗口大小是 P2 的事。P1 在报告里给出每步输入 token 与缓存命中率，作为 P2 的依据 |
| 系统提示词在轮内仍会变（`sys_now += …`，`tool_loop.py:1486-1532`），前缀缓存在这些步失效 | 已知，归 P2.1 状态栏；P1 的成本对比要把这部分单列 |
| 写大文件时参数整段留在 assistant tool_calls 里占窗口 | 原生协议要求如此；P2.4 在压缩时把旧调用的大参数替换为回执 |
| Anthropic 仍走文本渲染，得不到原生收益 | 明确列为后续；需要真 key 验证配对约束后再开 |

## 10. 尚无证据、未声称已验

- 探针只覆盖 deepseek-v4-flash；v4-pro 未测。DeepSeek 将来是否开始强制回传思考未知（降级口兜底）。
- 「原生协议会显著降低输出 token 与用时」：书中实验与 DeepSeek 文档支持这个方向，**Arslan 上尚无测量**，以第 8 节付费对照为准。
- 0.1 的缓存命中权重：按 DeepSeek 价格推算，其他厂商未核价。
