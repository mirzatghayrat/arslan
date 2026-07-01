---
name: finishing-a-development-branch
description: 收尾开发分支 —— 实现完成、测试全绿后，先验证测试再给出 4 个明确选项（本地合并/推送建 PR/保留/丢弃），执行所选、按需清理 worktree。
version: 0.1.0
authors:
  - Arslan
source: adapted from obra/superpowers · finishing-a-development-branch (MIT, © 2025 Jesse Vincent)
---

## Trigger

当实现完成、测试应当全绿、需要决定如何整合这份工作时激活。核心原则：验证测试 → 给出选项 → 执行所选 → 清理。

## 决策规则

- **先验证测试再给选项**：跑项目测试套件。测试挂了就停在这里、如实展示失败、不进入下一步 —— 不能带着失败的测试去合并/建 PR。
- **确定基线分支**：用 `git merge-base HEAD main`（或 master）判断从哪分出来的，拿不准就问用户确认。
- **给出恰好 4 个选项，不加解释**：1) 本地合并回基线分支；2) 推送并建 PR；3) 保留分支原样（用户稍后处理）；4) 丢弃这份工作。问"选哪个？"，保持简洁。
- **选项 1 本地合并**：切到基线分支 → pull 最新 → 合并功能分支 → 在合并结果上再跑一遍测试 → 测试过才删功能分支 → 清理 worktree。
- **选项 2 推送建 PR**：推分支 → `gh pr create`（Summary 2-3 条 + Test Plan）→ 保留 worktree（PR 还在走）。
- **选项 3 保留原样**：报告"保留分支 <名>，worktree 在 <路径>"，不清理 worktree。
- **选项 4 丢弃：必须先确认**：列出将永久删除的分支/commits/worktree，要求用户输入 `discard` 精确确认后，才切回基线并 `git branch -D`。
- **worktree 清理只对选项 1 和 4**：选项 2、3 保留 worktree（可能还需要）；别自动清理。
- **红线**：绝不带失败测试推进、绝不未验证就合并、绝不未确认就删工作、绝不未经明确要求就 force-push。
