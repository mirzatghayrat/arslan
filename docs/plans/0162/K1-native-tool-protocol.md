# K1 Claude 和 Gemini 走原生工具协议

| 项 | 内容 |
|---|---|
| 道 | ②Main |
| 版本 | 0.1.62 |
| 分级 | 必须 |
| 依赖 | C1 |
| 合并位置 | K 线第 1 个（C1 → **K1** → K2 …） |
| 推动的门槛 | §5.1「Claude 上对 Claude Code：差距缩小一半以上」；§5.3 第 3 条 |
| 分支 | `claude/0162-k1-native-tools` |
| 迁移号 | 无 |

## 目标

用 Claude 或 Gemini 时，模型能看到自己上一步调了哪个工具、参数是什么、结果是什么（0.1.62 计划 K-1）。

今天的情况：

- 只有 OpenAI 兼容端点是原生的（`arslan/llm/providers/openai_provider.py:67-69`），基类默认关（`arslan/llm/providers/base.py:28`）。
- Claude 拿到的是 `to_legacy` 渲染的文字（`arslan/llm/trajectory.py:205-249`）：一句「Native tool invocation completed: X」加结果，不带参数。
- Gemini 的 `function_response` 里放的也是这段文字（`trajectory.py:233-245`）。

## 改哪些文件

- `arslan/llm/providers/anthropic_provider.py`
  - 实现原生轨迹：assistant 消息带 `tool_use`（id、name、input），思考块原样回传；紧接的 user 消息放这一批全部的 `tool_result`。
  - `supports_native_trajectory()` 返回 True。
- `arslan/llm/providers/gemini_provider.py`：`functionResponse` 里放真实结果，不放文本渲染（今天在 `:47-51`）。
- `arslan/llm/adapter.py:108-110`：选择原生 / 旧渲染的地方，加回退开关。
- `arslan/llm/trajectory.py`：`to_legacy` 保留一版，只在回退开关打开时用；下一版删。
- 测试：新增配对校验（每个 `tool_use` 在下一条 user 消息里有同 id 的 `tool_result`）、思考块回传、图片结果、回退开关。

## 不许碰

- 提示词与工具说明（K3、K5）；流式（K8）；工具分发（`tool_loop.py`）。
- Bridge 帧格式（`desktop/bridge/**`、`server/ws/bridge.py`、`spec/mobile-bridge/**`）。

## 怎么做（要点）

1. 先写配对校验测试，用录下来的 0.1.61 轨迹做输入，断言原生消息结构。
2. Anthropic 要求：有思考块时，连同签名原样回传，不能改写；`tool_result` 必须紧跟在对应的 `tool_use` 之后。按当时的官方文档核对一遍（本卡未核最新文档）。
3. Gemini：`functionResponse.response` 放结构化结果（截断规则沿用现有的落盘逻辑，`tool_loop.py:329-337`）。
4. 回退开关：一个设置或环境变量，默认走原生。

## 验收

- 测试全过；配对校验在 CI。
- **M1（贴在 PR 里）：** claude-sonnet-5 上逐题不差于热修版基线；三轮追问题看轨迹，确认模型引用了上一步的参数。
- 手动：用 Claude 跑一个「先写文件、再改其中一节」的任务，第二步不再整份重写。

## 量级

产品代码约 +150 行，不删；下一版删旧渲染约 −300 行。

## 风险与回退

- **风险：** 配对错位会让 Anthropic 回 400。配对测试覆盖每种组合：多调用一批、带图片、带思考。
- **回退：** 打开回退开关即回到旧渲染，不需要回滚代码。
