---
name: deck-authoring
description: 演示文稿/PPT/deck/slides 请求 → 默认产出一份自带完整设计系统的单文件 HTML 演示(全屏分页、键盘翻页、打印即 PDF);用户明确要可编辑的 .pptx/PowerPoint 时才改用 render_deck 生成原生 pptx。叙事方法不变:一页一个观点、标题即结论、SCQA 弧线。
version: 0.2.0
authors:
  - Arslan
source: Arslan original methodology (presentation storytelling); HTML deck 为默认交付,render_deck 工具按需生成 .pptx
---

## Trigger

用户要**做演示文稿 / PPT / deck / slides / 汇报 / 路演**时激活。默认交付 = **一份完整的单文件 HTML 演示文稿**(HTML 能承载远多于 pptx 的设计:精确 tokens、纯 CSS 图表、过渡动效),不是 markdown 大纲,也不是先问一轮再做。

**输出方式(关键·渲染契约)**:整条回复就是这份 HTML 文档本身——以 `<!DOCTYPE html` 开头、以 `</html>` 结尾,**开头不加任何解说文字,也不要用 ```html 围栏包裹**。客户端只在「整条消息以 `<!DOCTYPE html` 开头」时才渲染成预览/下载卡片;多一句开场白或一层围栏,用户看到的就是一堵代码墙。

**唯一例外**:用户**明确**要「可编辑的 pptx / PowerPoint 文件 / 能自己再改的 PPT」→ 不写 HTML,改走规则 9 的 `render_deck` 工具生成原生 .pptx。没点名要 pptx 就默认 HTML。

## 决策规则

1. **先定叙事弧线,再排页**。SCQA / 金字塔:情境 → 冲突 → 问题 → 答案(主张)。整份 deck 一条主线,不是要点堆叠。
2. **一页一个观点**,绝不超过一个。讲不完就拆页;观点多≠信息量大。
3. **标题即结论(assertion-evidence)**。每页标题写这一页的**主张**(「规模领先者正在甩开利基玩家」),正文只放支撑证据;不写话题标签(「竞争分析」)。
4. **HTML 结构契约**:每页 = 一个满视口 `<section class="slide">`(`height:100vh; display:none`,`.active` 显示);内联一段**极小的原生 JS 翻页器**——方向键/空格/PageUp·Down + 点击左右半屏翻页,右下角页码计数器「n / N」;**零外部依赖**(不引 reveal.js、不引 CDN 字体/脚本,系统字体栈 + 'PingFang SC'/'Noto Sans SC' 兜底);`@media print` 下每页 `display:block; page-break-after:always; height:100vh` → 浏览器打印即得一页一屏的 PDF。允许克制的 CSS 过渡(淡入/上移几像素),禁止花哨动画。
5. **默认设计系统(Ember,逐字用这些值)**:页底 `#F2EBE0`、正文墨色 `#1A1410`、强调 `#D94420`(**accent 底上一律配白字**)、深底上的强调必须用 `#F06A20`(深色带里别用 #D94420)、卡片底 `#FAF5EE`、次要文字 `#6B5E52`、分隔线 `#D8CFC4`;`#A8998C` **只允许 ≥18px 的大字**;`#2E6645` 只用于「成功/正向」类小 tag,不作第二主色。整体是**圆角卡片**视觉:圆角统一 9–14px、1px 发丝边、柔和留白,不是直角编辑部风;小标签一律小号大写宽字距。
6. **页型语言**:满视口的 slide 是画布,页内内容用圆角卡片块组织。**封面页** = 深底(#1A1410)大圆角覆盖块(radius ~14px、大内边距):#F06A20 色宽字距 eyebrow → 40px/700 特大标题 → 21px 细体浅色副标 → meta 行(标签+值);右侧配一块半透明**关键数字小面板**(`rgba(255,255,255,.08)`、radius 10,行 = 大数值 + 右对齐小标签、淡分隔线)。**章节页** = accent 底小圆 pill 编号(`padding:2px 10px; border-radius:14px`)或超大编号 + 一句 25px/700 章节主张。**数据页** = 圆角指标卡网格(`--bg` 底、22px/700 数值 + 小号次要标签;主角指标用反色变体 = 深底 + #F06A20 数值)/ 案例卡(发丝边 + 4–5px 彩色顶边、26px 大数、斜体来源行)/ 深底表头斑马纹表格 / 纯 CSS 条形图或内联 SVG 图表(上方配宽字距小图表标题)——**数字绝不排成 bullet 墙**。**要点/警示/说明**用语义 callout 家族(radius 9,按语义用不当装饰):`box-hl` = accent 底白字关键结论、`box-warn` = 琥珀浅调警示、`box-info` = 冷调补充说明。**金句页** = 大引号 + 出处。每页字少想法大:bullet ≤ 一行、一页 ≤ 6 条。
7. **项目规范压倒默认**:任务上下文/知识库里若有 `*-design.md` / `design.md`,其 tokens/字体/版式**完全覆盖**规则 5;其次兑现用户在对话里说过的风格偏好;都没有就静默用 Ember,不追问。
8. **数据诚实**:每个数字来自对话内容或工具结果;无法核实标 `[UNSOURCED]`/「未核实」,绝不编造。
9. **用户明确要可编辑 .pptx 时 → 调 `render_deck`**:把同一套叙事结构映射到版式——封面/收尾 → `title`;章节 → `section`;要点 → `bullets`;对比 → `two-column`;金句 → `quote`;单个大数 → `big-number`;2–4 个指标 → `kpi`;行列数据 → `table`;数值对比/趋势 → `chart`(原生可编辑图表)。话术与来源进每页 `notes`(speaker notes)。theme 用名字:`ember`(默认)/ `ember-dark` / `ink` / `midnight` / `azure` / `terra`。一次调用生成完整 .pptx 供下载。
10. **HTML 版也要「可讲」**:讲稿式细节别堆上页面——放进每页底部一行小字备注区或直接省略;页面是提词板不是讲稿。

**核心原则**:deck 是讲故事的载体不是文档转储——先有主线与每页的主张,再选载体:默认交付**设计完整的单文件 HTML**(以 `<!DOCTYPE html` 裸文档开头回复),用户点名要 PowerPoint 才用 `render_deck` 出原生 .pptx。宁可页少而清,不要页多而糊。
