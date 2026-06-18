---
name: github-eval
description: 评估某 GitHub 仓库并把它匹配到具体需求 —— 它做什么、质量如何、值不值得挂载或借鉴。
version: 0.1.0
authors:
  - Arslan
credentials:
  - name: GITHUB_TOKEN
    required: false
    description: 提升 GitHub API 速率上限；匿名亦可用（低速率）。
    storage: ".env / 环境变量 / --token"
---

## Trigger

当用户需要判断「某个 GitHub 仓库是否值得用」时激活：评估一个 repo 的质量、活跃度、可信度，并匹配到用户的具体需求（如"能不能挂进我的 agent""值不值得借鉴它的设计"）。只做评估与匹配，不修改任何仓库。

## 决策规则

- 第一步永远先取客观数据：`eval <owner/repo>` 获取 stars、forks、license、最近更新时间、open issues。
- 信任分级（决定"建议挂载 / 人工确认 / 警告"）：
  - stars ≥ 1000 且 180 天内有更新 → 高信任，可建议挂载或借鉴。
  - stars ≥ 100 → 中等，展示详情，建议使用前人工审查。
  - stars < 100 或长期未更新 → 低信任，警告风险，建议安全审查。
- **碰钱 / 有真实副作用的工具（下单、转账、发布、改数据）即使信任分高，也必须用户明确批准，绝不自动安装。**
- license 必须核对：MIT / Apache-2.0 商用友好；GPL 类有传染性需提示；无 license 默认不可商用。
- 匹配需求时说清三种用法的取舍：① 挂载为 MCP/工具（最干净）② 借鉴设计理念（不抄码）③ 抠源码（耦合重，慎用）。
- 只读：绝不 star、fork、提 issue 或以任何方式修改目标仓库。
- 不臆造：拿不到的指标如实说"未获取"，不编造数据。
