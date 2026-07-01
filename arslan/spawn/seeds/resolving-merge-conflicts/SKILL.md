---
name: resolving-merge-conflicts
description: 解决进行中的 git merge/rebase 冲突 —— 看清状态、追溯每处冲突的一手来源与原始意图、逐块解决(保留双方意图/按合并目标取舍)、跑自动检查、收尾提交。用户遇到合并/变基冲突时用。
version: 0.1.0
authors:
  - Arslan
source: adapted from mattpocock/skills · engineering/resolving-merge-conflicts (MIT, © Matt Pocock); 个人品牌与专有 setup 引用剥离,方法论保留
---

## Trigger

当有一个**进行中的 git merge 或 rebase 冲突**需要解决时激活 —— 文件里出现 `<<<<<<<` / `=======` / `>>>>>>>` 冲突标记,或 rebase 停在冲突处。目标是**正确收编两边的意图并干净收尾**,而不是简单 `--abort` 逃避。

## 决策规则

1. **先看清当前状态**:查 git 历史(`git log` / `git status`),分清是 merge 还是 rebase,列出哪些文件冲突。
2. **追溯每处冲突的一手来源**:深入理解每个改动**为什么**这么改、原始意图是什么 —— 读 commit message、翻对应 PR、查原始 issue/ticket。**不理解意图,就别动手解那一处。**
3. **逐 hunk 解决**:尽量**保留双方意图**;真冲突不可兼得时,选**符合本次合并既定目标**的那个,并记下取舍(trade-off)。**绝不臆造新行为**。始终解决,**绝不 `--abort`** 逃避。
4. **跑项目的自动检查**:找出并按序运行(通常)typecheck → tests → format,修好合并过程弄坏的一切。
5. **收尾**:全部 stage 后 commit;若是 rebase,`git rebase --continue` 直到所有 commit 变基完成。

**核心原则**:解冲突是"理解两个意图再取舍",不是"挑一边删一边"。不懂意图先追溯;取舍要留痕;收尾必过检查。
