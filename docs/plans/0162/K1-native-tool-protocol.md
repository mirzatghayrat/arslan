# K1 Claude 和 Gemini 走原生工具协议

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | v0.1.63 |
| 分级 | 必须 |
| 依赖 | C1；**合并要等 M1B**（v0.1.62 发布后的基线跑完，A4）。可以先开发 |
| 合并位置 | K 线第 1 个（C1 → **K1** → K2 …）。v0.1.62 发布前不合：那之前 `tool_loop.py`、`task_service.py` 只给热修线 |
| 推动的门槛 | §5.1「不退步」；§5.1「Claude 上对 Claude Code：差距缩小一半以上」；§5.3 第 3 条 |
| 分支 | `claude/0162-k1-native-tools`；超过 800 行时拆成 `claude/0162-k1a-native-protocol`、`claude/0162-k1b-anthropic-context`（要点 12） |
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
  - `base.py:33-37` 的 `endpoint_fingerprint` 今天只算地址和型号。加上钥匙的哈希（只存哈希，不存钥匙）：换了钥匙或账号，思考块就不回放（要点 8）。
  - 新增 `build_trajectory_messages`：assistant 消息原样回放上面那条 content；紧接的 user 消息先放这一批全部 `tool_result`（同 id），再放状态块。
  - `chat()`（`:289-305`）接受 `tool_choice`：`"none"` 发 `{"type": "none"}`。今天它不接受这个参数，原生一打开，`adapter.chat_trajectory` 一传就 TypeError（`adapter.py:125-126`；调用在 `server/orchestrator/tool_loop.py:560-561`）。
  - `supports_native_trajectory()` 返回 True。
  - 文件头（`:16-20`）和 `_payload`（`:254-256`）的注释写着「不回传原生块」，一起改掉。
- `arslan/llm/providers/gemini_provider.py`
  - `functionResponse.response` 放结构化结果，不放文字渲染（`:47-51`）。
  - `chat()`（`:120-137`）接受 `tool_choice`：`"none"` 发 `toolConfig.functionCallingConfig.mode = "NONE"`。
  - 新增 `build_trajectory_messages`；`supports_native_trajectory()` 返回 True。
- `server/orchestrator/agent_status.py:126-141`，以及 `tool_loop.py` 里 `_model_call` 发状态块的几行（`:556-561`）：原生 Claude 下状态块改成「追加、不删」（要点 3）。`tool_loop.py` 只动这几行。
- **Anthropic 回合内的上下文（要点 12）：** `arslan/llm/trajectory.py`（`IMAGES_KEPT = 2`，`:35`；`keep_latest_images`，`:95`）；`tool_loop.py:378`（截图换占位）、`:2334-2336`（`bounded_history`）在 Anthropic 原生路径上不再调用；`anthropic_provider.py` 的 `_payload` 加服务端上下文管理。
- `server/orchestrator/model_call.py:41`：`_PROTOCOL` 今天只认 OpenAI 的报错用词。补上 Anthropic、Gemini 的（`tool_use`、`tool_result`、`thinking`、`functionResponse`），原生请求被拒时本回合退回旧渲染，而不是整轮失败。
- 测试：见验收。

## 不许碰

- 提示词与工具说明（K3、K5）；流式（K8）；`tool_loop.py` 里除状态块那几行、`:378` 和 `:2334-2336` 以外的地方。
- 其他服务商的本地裁剪：OpenAI 兼容和 Gemini 照旧用 `keep_latest_images`、`bounded_history`。
- OpenAI 兼容端点的轨迹（`openai_provider.py:71-122`）：它是 M1B 基线的一部分。
- Bridge 帧格式（`desktop/bridge/**`、`server/ws/bridge.py`、`spec/mobile-bridge/**`）。

## 怎么做（要点）

1. **先写测试。** 用录下来的 v0.1.61 轨迹做输入，断言原生消息结构：每个 `tool_use` 在下一条 user 消息里有同 id 的 `tool_result`。
2. **思考块原样带回。** 连同签名，一个字节都不改。**改了思考块会报 400；漏带不报错，这一步的思考会被悄悄关掉**（来源：Anthropic 官方文档 platform.claude.com 的 thinking 页，2026-10-17 读）。所以测试要断言「带了，而且逐字节相同」，不能只看有没有 400。补一条「有思考 + 有工具」的往返测试（用录下的响应，不连网）。
3. **状态块只追加，不删。**
   - 每步的 `<agent_status>` 作为单独的文本块，放在这一批所有 `tool_result` 之后，**不拼进工具结果**。拼进去就会被当成工具输出（不可信）。
   - 发出后留在轨迹里，下一步不删、不改。今天它每步只贴在最后一条消息上、不存（`agent_status.py:126-141`），下一步就从前文里消失了，这算「改了前文」（见第 4 条）。
4. **思考块和前文（已核，来源：Anthropic 官方文档 platform.claude.com 的 thinking 页，2026-10-17 读）。**
   - **前文检查：** 从 Fable 5.1 起，含 Opus 5.5、Sonnet 5.5、Haiku 5.5，服务端会检查回放的思考块之前，system、tools、消息有没有被改。2026-08-31 起创建的账号默认强制：改过就 400。
   - **让服务端丢掉失效的块：** 字段 `thinking.block_binding.prefix_mismatch_behavior: "drop_block"`，beta 头 `thinking-binding-controls-2026-08-01`。被丢掉的块列在响应的 `input_transformations` 里。
   - **限制：** `block_binding` 只能配 adaptive 思考，不能和 `between_tools` 一起发。Sonnet 5.5 的关思考路径今天发的就是 `between_tools`（`anthropic_provider.py:51-56`、`:270-278`），那条路不带 `block_binding`。
   - **代码事实：** Arslan 一个回合里有五处会改前文：
     - 状态块每步只贴在最后一条消息上、不存（第 3 条，`agent_status.py:126-141`）；
     - 截图换成占位（`trajectory.keep_latest_images`，`tool_loop.py:378`）；
     - 轮内按字符裁剪（`bounded_history`，`tool_loop.py:2334-2336`）；
     - 收尾时只给收尾工具，工具表变了（`tool_loop.py:2353-2354`）；
     - 上下文超长时的压缩（`model_call.py` 的 context 恢复）。
   - **处理：** `drop_block` 只是不报 400，被丢的块后面的思考全都没了。截图换占位（只留 2 张）和轮内裁剪，在屏幕任务和长任务里每一步都会改前文，所以不能靠它兜：
     - 第一处：第 3 条消掉；
     - 截图、轮内裁剪：要点 12，Anthropic 这条路发出后不再改；
     - 收尾换工具表：K3 让回合内工具表不变后消掉。K3 合并前，强制收尾那一步还会丢块，运行记录照样标出；
     - 上下文压缩：**唯一允许丢块的地方**，丢了在运行记录里标出来。
5. **强制收尾那一步：** Anthropic 发 `{"type": "none"}`，Gemini 用 NONE。工具表照旧带上，和 OpenAI 路径一样（`tool_loop.py:560`），前缀不变。
6. **Gemini：** `functionResponse.response` 放结构化结果。截断沿用现有的落盘逻辑（`tool_loop.py:329-337`）。
7. **回退：** 沿用 `ARSLAN_TOOL_PROTOCOL=legacy`。代码注释写明「Claude、Gemini 的旧文本渲染 v0.1.64 删」（见「风险与回退」）。
8. **跨轮不回放思考块。** 思考块只在一个回合内、工具调用之间带回去；下一轮的历史里不放上一轮的思考块。端点指纹加钥匙哈希，换了钥匙也不回放。
9. **对 Claude 5.5 一代和 Fable 5.1 默认带 `drop_block`**（字段和 beta 头见要点 4）。响应里的 `input_transformations` 记进运行记录（只记被丢了几个块、在哪一步，不记内容）。
10. **字段被拒时去掉重发。** 照 `arslan/llm/param_heal.py` 的做法：`block_binding` 或 beta 头被某个端点拒收，就去掉重发，并记住这个端点。它是嵌套字段，要补测试确认能去掉。
11. **（可以，归 K8）工具调用之间的进度说明：** Opus 5.5、Sonnet 5.5 在工具调用之间的进度说明以思考块返回，默认为空。拿文字、在窗口里显示，见 K8 卡「可以」一项。K1 不发相关参数，只保证这些思考块照要点 2 原样带回。
12. **Anthropic 回合内的上下文：发出后不再改**（来源：Anthropic 官方文档 platform.claude.com 的 context-editing 页和 preserved-thinking 页，2026-10-17 读）。
    - **第一次发出前就缩小：** 截图在附上时就缩到最终尺寸；工具结果在第一次发出时按现有的落盘规矩截断（`tool_loop.py:329-337`）。之后不换占位、不再裁剪。
    - **清理旧结果改用服务端：** 策略 `clear_tool_uses_20250919`，beta 头 `context-management-2025-06-27`，参数 `trigger`、`keep`、`clear_at_least`、`exclude_tools`。官方原文：Fable 5.1 和 5.5 一代上，服务端的上下文管理不会让思考块失效。
    - **`clear_at_least` 设大一些，一次多清：** 每清一次，缓存从那里往后作废；一次多清，作废的次数少。起始值（⓪Plan 定，更正 E22）：
      - `trigger`：`{"type": "input_tokens", "value": 60000}`。API 按输入 token 计，不是字符；原文写的「64k / 96k 字符」不对。API 默认是 100k。
      - `keep`：`{"type": "tool_uses", "value": 6}`。默认是 3，多步任务要看得到最近几步的结果。
      - `clear_at_least`：`{"type": "input_tokens", "value": 20000}`。是 trigger 的三分之一，保证每作废一次缓存都清掉足够多。
      - `exclude_tools`：`update_plan`、`task_progress`、`read_skill`。计划、进度和技能说明不能消失。只发这三个里本次请求工具表中确实有的（文档没说名单里能不能有工具表外的名字，所以不发）。
      - `clear_tool_inputs` 保持默认 `false`：清掉的只是结果，模型仍看得到自己调过什么。
      - **K3 之前先用过渡值（更正 E23）：** `trigger` 24k 输入 token、`clear_at_least` 8k；`keep`、`exclude_tools`、`clear_tool_inputs` 不变。原因：K3 加消息级缓存断点之前，只有系统前缀有 `cache_control`，清理不多作废任何缓存；而 60k 以下什么都不裁，每步都全价付这部分输入，128k 的聊天计费上限几步就会碰到。**K3 加消息级断点时改回上面的 60k / 20k**，`_CLEAR` 旁边的注释写这个条件。
      - **只对真正的 Claude 发：** `context_management` 和 `trims_context_server_side()` 都限定 `_is_claude()` 并且是官方 host。第三方 Anthropic 协议端点（例如经 `llm_base_url` 指到别家的 `/anthropic`）可能悄悄忽略这个字段，照旧本地裁剪（K1b 审查发现，更正 E23）。
      - 这些是起始值。M1 用 Claude 跑时贴三样：清理次数和清掉的 token 数（运行记录里的 `tool_uses_cleared`、`input_tokens_cleared`，来自 `context_management.applied_edits`），以及长任务前后的缓存命中。长任务上如果约每 10 次模型调用就清一次以上，或者缓存写入的花费超过省下的，R63 之前调整。
    - **被拒时：** 端点不接受这个 beta（例如经代理转发），照要点 10 去掉重发，退回本地裁剪 + `drop_block`。param_heal 会按端点记住这次拒绝，直到进程退出，所以之后在这个端点上的回合也都走本地裁剪，不只是这一回合；每个这样的运行，运行记录里标一次 `server_clearing_off`。
    - **其他服务商照旧在本地裁剪。**
    - 超过 800 行时拆成 K1a（要点 1–11）和 K1b（本条），连着合；K1b 合并前，Anthropic 默认仍走旧渲染，两个都合了才切到原生。

## 验收

- **测试（都在 CI）：**
  - 配对校验，覆盖每种组合：一批多个调用、带图片、带思考；
  - 「有思考 + 有工具」往返：第二次请求里的思考块和签名，与第一次响应逐字节相同；
  - `tool_choice="none"`：Anthropic 发 `{"type": "none"}`，Gemini 发 NONE，都不再 TypeError；
  - 状态块：是 `tool_result` 之后的单独文本块；下一步请求里，上一步的状态块还在原处；
  - 对 Claude 5.5 一代和 Fable 5.1 的请求都带 `drop_block`；带 `block_binding` 的请求，思考是 adaptive，没有 `between_tools`；
  - Anthropic 原生路径：截图第一次发出时已经缩小，之后的请求里逐字节不变（不换占位）；轮内不再本地裁剪，请求里带 `clear_tool_uses_20250919` 和设好的 `clear_at_least`；其他服务商照旧本地裁剪；
  - 上下文压缩丢块时，运行记录里有标记；服务端上下文管理被拒时，去掉重发、退回本地裁剪，也有标记；
  - `block_binding` 被拒时，去掉重发能过，下一次不再带；
  - 下一轮的请求里没有上一轮的思考块；端点指纹换了钥匙，思考块不回放；
  - Anthropic 的协议类 400 让本回合退回旧渲染；
  - 回退开关打开时，请求和今天逐字节相同。
- **M1（贴在 PR 里）：**
  - claude-sonnet-5 上，逐题不差于 M1B（v0.1.62 基线）；
  - 三轮追问题看轨迹，确认模型引用了上一步的参数；
  - 再用 Claude 5.5 一代（或 Fable 5.1）跑：两道多步题、**一道截图任务**（Hands，超过 2 张截图）、**一道长任务**（会触发清理旧结果）。都不出 400；运行记录里的 `input_transformations` 在正常路径上为 **0**。不为 0，说明还有地方改了前文，要找出来。只有上下文压缩（和 K3 合并前的强制收尾）允许不为 0，且要有标记。
- **手动：** 用 Claude 跑「先写文件、再改其中一节」，第二步不再整份重写。

## 量级

产品代码约 +450～600 行。审查估 +300，这里另加了状态块只追加、要点 4 的处理和要点 12（约 +150～200）。超过 800 行就按要点 12 拆成 K1a、K1b。不删代码；v0.1.64 删旧渲染时再量行数。

## 风险与回退

- **风险：配对错位，Anthropic 回 400。** 配对测试覆盖每种组合；被拒时本回合退回旧渲染（`model_call.py:41` 补词之后）。
- **风险：前文被改，思考块被丢（已核，见要点 4）。** `drop_block` 只保证不报 400；第 3 条和要点 12 让正常路径不改前文，M1 在截图任务和长任务上断言 `input_transformations` 为 0。
- **风险：服务端清理让缓存作废。** 用 `clear_at_least` 一次多清；M1 贴长任务的缓存命中前后对比（配合 K3）。
- **风险：状态块都留在轨迹里，长回合多占 token。** `clear_tool_uses` 不清状态块，它们是文字，不是工具结果（原文说「由服务端清理兜底」不对，更正 E23）。Anthropic 上靠清掉旧的工具结果腾出空间；其他服务商由轮内裁剪兜底，`_rendered_size` 要把状态块算进去。M1 里贴多步题的输入 token、计费 token 和停下的原因。
- **风险：`drop_block` 对老账号更严。** 2026-08-31 之前建的账号，只有设了 `block_binding` 才做前缀检查。设了以后，前缀一有改动，思考块就被丢掉；例如 K3 之前收尾那一步工具表变窄，或者压缩。M1 看 `input_transformations`。
- **风险：代理拒绝 beta 头却不点名字段。** 这时 param_heal 认不出该去掉什么，这个端点上的 Claude 回合会一直失败。已知，留作剩余风险。
- **回退：** 设 `ARSLAN_TOOL_PROTOCOL=legacy` 即回到旧渲染，不需要回滚代码。
- **留着的旧路径与删除条件**（代码注释里同样写）：
  - Claude、Gemini 的旧文本渲染，以及它们走回退开关的那条路：**v0.1.64 删**。条件：v0.1.63 装上后 7 天，M2 里 Claude、Gemini 没有协议类 400，且 M1 不退步。
  - `to_legacy` 本身还给「拒收原生历史的 OpenAI 兼容端点」兜底（`tool_loop.py:582`）。这条路不是 K1 留下的，K1 不动它。
