---
name: deck-authoring
description: 把内容做成一份会讲故事的演示 deck —— 一页一个观点、标题即结论(assertion-evidence)、有叙事弧线、话术进演讲者备注,再映射到 render_deck 的版式生成原生可编辑 .pptx。用户要做 PPT/演示/汇报/pitch 时用。
version: 0.1.0
authors:
  - Arslan
source: Arslan original methodology (presentation storytelling); 配合 render_deck 工具生成 .pptx
---

## Trigger

用户要**做一份演示/PPT/汇报/路演 deck** 时激活 —— 把材料或结论组织成能"讲"出来的幻灯片,而不是把文档整段塞进页面。产出:先想清结构 → 用 `render_deck` 工具生成**原生可编辑的 .pptx**(不是图片),用户可下载再改。

## 决策规则

1. **先定叙事弧线,再排页**。用 SCQA / 金字塔:情境(Situation)→ 冲突(Complication)→ 问题(Question)→ 答案(Answer/主张)。整份 deck 有一条主线,不是零散要点堆叠。
2. **一页一个观点**。每页只讲一件事;讲不完就拆两页。观点多≠信息量大。
3. **标题即结论(assertion-evidence)**。页面标题写**这一页的结论/主张**("规模领先者正在甩开利基玩家"),正文只放支撑它的证据;标题**不要**写话题标签("竞争分析")。
4. **少字、大想法**。每条 bullet ≤ 一行;一页 ≤ 6 条;关键数字用 `big-number` 版式放大;金句用 `quote`。细节与话术**进演讲者备注(notes)**,不进页面。
5. **映射到版式**(`render_deck` 的 layout):封面/结论 → `title`;章节切换 → `section`;要点 → `bullets`;对比/取舍 → `two-column`;金句 → `quote`;关键指标 → `big-number`。
6. **结构骨架**:封面(title)→ 可选议程(bullets)→ 分章(section + 内容页)→ 收尾(title/big-number 给一个记得住的结论)。10–20 页足矣,别灌水。
7. **每页写 notes**:把你想讲的话、数据来源、过渡句放进 notes —— 页面是提词板不是讲稿。
8. **数字带来源**(若涉数据):正文/notes 里标来源,无法核实标 `[未核实]`(与研究类技能一致)。
9. **调 `render_deck` 生成**:把结构组织成 `slides=[{layout, title/subtitle/bullets/left/right/text/value/label, notes}]`,可选 `theme={accent:'#hex'}`,一次生成完整 .pptx 交付用户下载。

**核心原则**:deck 是**讲故事的载体**不是文档转储 —— 先有主线与每页的主张,再有版式;页面放结论、备注放话术;宁可页少而清,不要页多而糊。
