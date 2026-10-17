# K1 Claude 和 Gemini 走原生工具协议

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.63 |
| 分级 | 必须 |
| 依赖 | C1；**合并要等 M1B**（v0.1.62 发布后的基线跑完，A4）。可以先开发 |
| 合并位置 | K 线第 1 个（C1 → **K1** → K2 …）。v0.1.62 发布前不合：那之前 `tool_loop.py`、`task_service.py` 只给热修线 |
| 推动的门槛 | §5.1「不退步」；§5.1「Claude 上对 Claude Code：差距缩小一半以上」；§5.3 第 3 条 |
| 分支 | `claude/0162-k1-native-tools` |
| 迁移号 | 无 |

## 目标

用 Claude 或 Gemini 时，模型能看到自己上一步调了哪个工具、参数是什么、结果是什么；Claude 的思考块原样带回去（v0.1.63 计划 K-1）。

今天的情况（`fb6d7230`）：

- 只有 OpenAI 兼容端点走原生（`arslan/llm/providers/openai_provider.py:67-69`），基类默认关（`arslan/llm/providers/base.py:28-31`）。
- Claude 拿到的是 `to_legacy` 渲染的文字（`arslan/llm/trajectory.py:205-251`）：一句「Native tool invocation completed: X」加结果，不带参数。
- 解析 Claude 的回复时，只留文字和 `tool_use`（`arslan/llm/providers/anthropic_provider.py:410-423`），思考块和签名都丢了。Claude 5 一代默认会思考，Opus 5.5 和 Fable 关不掉（`:45-56`）。
- Gemini 已经回传自己的 `functionCall` 和思考签名（`trajectory.py:240-241`），但 `functionResponse` 里放的仍是「TOOL RESULT for X」那段文字（`trajectory.py:233-239`；发送在 `gemini_provider.py:47-51`）。
- 回退开关**已经有**：`ARSLAN_TOOL_PROTOCOL=legacy`（`arslan/llm/adapter.py:102-108`），不用新加。

## 改哪些文件

- `arslan/llm/providers/anthropic_provider.py`
  - `_parse_response`（`:410-431`）：保留整条 assistant content（thinking、redacted_thinking、text、tool_use，顺序不变），放进 `LLMResponse.continuation`（`arslan/models.py:98-102`）。带上端点指纹（`base.py:33-37`），只回放给同一端点和模型，照 OpenAI 的做法（`openai_provider.py:107-110`）。
  - 新增 `build_trajectory_messages`：assistant 消息原样回放上面那条 content；紧接的 user 消息先放这一批全部 `tool_result`（同 id），再放状态块。
  - `chat()`（`:289-305`）接受 `tool_choice`：`"none"` 发 `{"type": "none"}`。今天它不接受这个参数，原生一打开，`adapter.chat_trajectory` 一传就 TypeError（`adapter.py:125-126`；调用在 `server/orchestrator/tool_loop.py:560-561`）。
  - `supports_native_trajectory()` 返回 True。
  - 文件头（`:16-20`）和 `_payload`（`:254-256`）的注释写着「不回传原生块」，一起改掉。
- `arslan/llm/providers/gemini_provider.py`
  - `functionResponse.response` 放结构化结果，不放文字渲染（`:47-51`）。
  - `chat()`（`:120-137`）接受 `tool_choice`：`"none"` 发 `toolConfig.functionCallingConfig.mode = "NONE"`。
  - 新增 `build_trajectory_messages`；`supports_native_trajectory()` 返回 True。
- `server/orchestrator/agent_status.py:126-141`，以及 `tool_loop.py` 里 `_model_call` 发状态块的几行（`:556-561`）：原生 Claude 下状态块改成「追加、不删」（要点 3）。`tool_loop.py` 只动这几行。
- `server/orchestrator/model_call.py:41`：`_PROTOCOL` 今天只认 OpenAI 的报错用词。补上 Anthropic、Gemini 的（`tool_use`、`tool_result`、`thinking`、`functionResponse`），原生请求被拒时本回合退回旧渲染，而不是整轮失败。
- 测试：见验收。

## 不许碰

- 提示词与工具说明（K3、K5）；流式（K8）；`tool_loop.py` 里除状态块那几行以外的地方。
- OpenAI 兼容端点的轨迹（`openai_provider.py:71-122`）：它是 M1B 基线的一部分。
- Bridge 帧格式（`desktop/bridge/**`、`server/ws/bridge.py`、`spec/mobile-bridge/**`）。

## 怎么做（要点）

1. **先写测试。** 用录下来的 v0.1.61 轨迹做输入，断言原生消息结构：每个 `tool_use` 在下一条 user 消息里有同 id 的 `tool_result`。
2. **思考块原样带回。** 连同签名，一个字节都不改。不带就是 400。补一条「有思考 + 有工具」的往返测试（用录下的响应，不连网）。
3. **状态块只追加，不删。**
   - 每步的 `<agent_status>` 作为单独的文本块，放在这一批所有 `tool_result` 之后，**不拼进工具结果**。拼进去就会被当成工具输出（不可信）。
   - 发出后留在轨迹里，下一步不删、不改。今天它每步只贴在最后一条消息上、不存（`agent_status.py:126-141`），下一步就从前文里消失了，这算「改了前文」（见第 4 条）。
4. **思考块和前文（未核，开工时先对官方文档确认）。**
   - **未核的风险：** 较新的 Claude 型号可能会检查「回放的思考块之前，system、tools、消息有没有被改」，改过就报错或丢掉思考块。哪些型号、从哪天起、用什么字段让服务端丢掉失效的块，本卡都没有核，所以不写字段名和日期。开工前对照 Anthropic 当时的官方文档确认，PR 里写明看的是哪份文档、哪天看的。
   - **代码事实：** Arslan 一个回合里有五处会改前文：
     - 状态块每步只贴在最后一条消息上、不存（第 3 条，`agent_status.py:126-141`）；
     - 截图换成占位（`trajectory.keep_latest_images`，`tool_loop.py:378`）；
     - 轮内按字符裁剪（`bounded_history`，`tool_loop.py:2334-2336`）；
     - 收尾时只给收尾工具，工具表变了（`tool_loop.py:2353-2354`）；
     - 上下文超长时的压缩（`model_call.py` 的 context 恢复）。
   - **确认有这项检查时：** 第 3 条消掉第一处；其余四处按文档给的办法处理（例如让服务端丢掉失效的思考块，或不再回放改动点之前的思考块），每处补一条测试。新加的请求字段被拒时，去掉它重发，照 `arslan/llm/param_heal.py` 的做法；嵌套字段要补测试确认能去掉。
   - 彻底的修法（回合内工具表不变、前缀只追加）在 K3。
5. **强制收尾那一步：** Anthropic 发 `{"type": "none"}`，Gemini 用 NONE。工具表照旧带上，和 OpenAI 路径一样（`tool_loop.py:560`），前缀不变。
6. **Gemini：** `functionResponse.response` 放结构化结果。截断沿用现有的落盘逻辑（`tool_loop.py:329-337`）。
7. **回退：** 沿用 `ARSLAN_TOOL_PROTOCOL=legacy`。代码注释写明「Claude、Gemini 的旧文本渲染 v0.1.64 删」（见「风险与回退」）。

## 验收

- **测试（都在 CI）：**
  - 配对校验，覆盖每种组合：一批多个调用、带图片、带思考；
  - 「有思考 + 有工具」往返：第二次请求里的思考块和签名，与第一次响应逐字节相同；
  - `tool_choice="none"`：Anthropic 发 `{"type": "none"}`，Gemini 发 NONE，都不再 TypeError；
  - 状态块：是 `tool_result` 之后的单独文本块；下一步请求里，上一步的状态块还在原处；
  - 截图换占位之后的下一步请求，按要点 4 确认的办法处理（确认有这项检查时）；
  - Anthropic 的协议类 400 让本回合退回旧渲染；
  - 回退开关打开时，请求和今天逐字节相同。
- **M1（贴在 PR 里）：**
  - claude-sonnet-5 上，逐题不差于 M1B（v0.1.62 基线）；
  - 三轮追问题看轨迹，确认模型引用了上一步的参数；
  - 再用一个最新一代的 Claude 型号跑两道多步题，不出 400。PR 写明要点 4 对照的官方文档，以及测试账号会不会真的做这项检查。
- **手动：** 用 Claude 跑「先写文件、再改其中一节」，第二步不再整份重写。

## 量级

产品代码约 +300～400 行。审查估 +300，这里另加了状态块只追加和要点 4 的处理两处。不删代码；v0.1.64 删旧渲染时再量行数。

## 风险与回退

- **风险：配对错位，Anthropic 回 400。** 配对测试覆盖每种组合；被拒时本回合退回旧渲染（`model_call.py:41` 补词之后）。
- **风险：前文被改，思考块失效（未核，见要点 4）。** 靠要点第 3、4 条兜住；M1 里用最新一代的 Claude 型号核。
- **风险：状态块都留在轨迹里，长回合多占 token。** 由轮内裁剪兜底；M1 里贴多步题的输入 token 前后对比。
- **回退：** 设 `ARSLAN_TOOL_PROTOCOL=legacy` 即回到旧渲染，不需要回滚代码。
- **留着的旧路径与删除条件**（代码注释里同样写）：
  - Claude、Gemini 的旧文本渲染，以及它们走回退开关的那条路：**v0.1.64 删**。条件：v0.1.63 装上后 7 天，M2 里 Claude、Gemini 没有协议类 400，且 M1 不退步。
  - `to_legacy` 本身还给「拒收原生历史的 OpenAI 兼容端点」兜底（`tool_loop.py:582`）。这条路不是 K1 留下的，K1 不动它。
