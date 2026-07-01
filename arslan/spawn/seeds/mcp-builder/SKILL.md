---
name: mcp-builder
description: 构建 MCP 服务器 —— 设计高质量 MCP（Model Context Protocol）服务器，让 LLM 通过设计良好的工具调用外部服务；讲工具设计、命名、错误信息、评估。质量以"LLM 能否借它完成真实任务"衡量。
version: 0.1.0
authors:
  - Arslan
source: adapted from anthropics/skills · mcp-builder (Apache-2.0, © 2025 Anthropic PBC); bundled reference/ guides and scripts removed
---

## Trigger

当要构建 MCP 服务器、把某个外部 API/服务集成给 LLM 使用时激活（Python FastMCP 或 Node/TypeScript SDK 均可）。核心原则：MCP 服务器的质量，由"LLM 能借它多好地完成真实世界任务"来衡量，而非端点数量。

## 决策规则

- **四阶段工作法**：① 深度调研与规划（理解现代 MCP 设计 + 研究 API）② 实现（基础设施 + 逐个工具）③ 审查与测试 ④ 建评估。
- **API 覆盖 vs 工作流工具**：在"全面覆盖 API 端点"与"面向特定任务的工作流工具"间平衡；不确定时优先全面的 API 覆盖（给 agent 组合操作的灵活性）。
- **工具命名要好发现**：用一致前缀 + 动作导向命名（`github_create_issue`、`github_list_repos`），清晰描述性的名字让 agent 快速找到对的工具。
- **上下文管理**：工具描述简洁、支持过滤/分页，返回聚焦的相关数据，别把大块无关内容塞回上下文。
- **错误信息要可行动**：错误要给出具体建议和下一步，引导 agent 走向解法，而不是只报"失败了"。
- **每个工具定义 input/output schema**：用 Zod（TS）或 Pydantic（Python）加约束与清晰描述、字段里带示例；尽量定义 outputSchema 返回结构化数据。I/O 用 async/await，加恰当的可行动错误处理，支持分页。
- **加工具注解**：`readOnlyHint`、`destructiveHint`、`idempotentHint`、`openWorldHint` 帮客户端理解工具性质。
- **传输选择**：远程服务器用 streamable HTTP（无状态 JSON，易扩展维护），本地服务器用 stdio。
- **构建后必建评估**：写 ~10 个问题测 LLM 能否借该服务器答出真实复杂问题。每题要求：独立、只读（非破坏性）、复杂（需多次工具调用与深入探索）、真实、可核（单一明确答案，可字符串比对）、稳定（答案不随时间变）。做法：列工具→只读探索数据→生成问题→自己解一遍验证答案。
- **代码质量**：DRY 无重复、错误处理一致、类型全覆盖、工具描述清晰；构建通过（`npm run build` / `py_compile`）后再交付。
