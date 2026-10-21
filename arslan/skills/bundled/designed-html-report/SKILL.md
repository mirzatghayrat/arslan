---
name: designed-html-report
description: 设计版报告 —— 报告/简报/调研/方案等长篇交付物默认产出自带完整设计系统的单文件 HTML(圆角卡片版式、粘性导航、语义 callout、可编辑文本),而非 markdown 长文墙。
version: 0.2.0
authors:
  - Arslan
---

## Trigger

当用户要「报告 / 简报 / 调研 / 方案 / 分析 / 复盘 / insight report」或任何明显要被保存、转发、打印的长篇交付物时激活:产出一份**完整的单文件 HTML 文档**,而不是 markdown 长文墙。

**输出方式(关键)**:整条回复就是这份 HTML 文档本身——以 `<!DOCTYPE html>` 开头、以 `</html>` 结尾,**开头不加任何解说文字,也不要用 ```html 代码围栏包裹**。客户端只在「整条消息以 `<!DOCTYPE html>` 开头」时才把它渲染成预览/复制/下载卡片;围栏或开头多一句话都会破坏识别,变回一堵代码墙。(本文档下方的围栏代码块只是给你看的骨架参考,真正回复时不要带围栏。)

日常问答、短回复、闲聊照常用普通文本——不要过度触发。

## 决策规则

1. **项目 design spec 压倒一切**:任务上下文(附带材料或知识库检索结果)里若有项目设计规范——形如 `*-design.md` / `design.md` 的文件——则**完全遵循它**的 tokens/字体/版式,本技能的默认设计系统整体让位。每个项目可以有自己的规范(A 项目 → A-design.md)。
2. **其次是用户口头偏好**:用户在对话中说过的风格偏好(主题色、语气、品牌感)在默认版式结构内优先兑现。
3. **否则静默用默认设计系统**:普通报告**不要**追问用户设计偏好,直接交付成品。
4. **大型/对外品牌交付物例外**:当交付物明显是大型对客/品牌 artifact(deck、客户报告)且没有 design.md 时,值得**只问一个短问题**,给三个选项:用默认风格 / 说出偏好 / 提供 design.md(可存入知识库供本项目复用)——得到答复即继续,不纠缠。
5. **数据诚实**:报告里每一个数字都必须来自对话内容或工具结果;绝不编造指标或案例;未知就明写「未知 / 待确认」。
6. **单文件、零外部依赖**:不引任何外部 CDN 脚本/字体/图片;字体用系统栈 + 'PingFang SC' / 'Noto Sans SC' 兜底;文件从磁盘双击打开即完整可看,`@media print` 下打印干净。

## 默认设计系统(House style · Ember 暖调 · 圆角卡片版式,WCAG AA 已校准)

- **Tokens(`:root`)**:`--ink:#1A1410`(暖黑,正文与深底)、`--bg:#F2EBE0`(麦色纸页面底)、`--card:#FAF5EE`(卡片底)、`--accent:#D94420`(锈橙红,唯一强调色;米白底上对比 4.6:1 达 AA)、`--accent-bright:#F06A20`(深底上的强调色——深色带里必须用它,别用 #D94420)、`--secondary:#6B5E52`(次要文字)、`--muted:#A8998C`(浅底上**只允许 ≥18px 的大字**,正文小字一律用 secondary)、`--green:#2E6645`(**只用于「开源/成功/正向」类 tag**,不作第二主色)、`--line:#D8CFC4`(发丝边框)。语义 callout 允许两组衍生浅调(唯一的非 Ember 扩展,只用于 callout):warn 琥珀 `--warn-bg:#F7EDD8/--warn-line:#E3CFA0/--warn-ink:#7A5A14`,info 冷灰蓝 `--info-bg:#E9EEF2/--info-line:#C9D6DE/--info-ink:#2F4A5C`。
- **对比度铁律**:accent 底(#D94420)上配**白字**;深底(#1A1410)上强调用 `--accent-bright`;用户有品牌色时只换 accent 两个值,其余不动。
- **版式基调 = 圆角卡片,不是通栏长文**:每个 section 是一张浮在暖纸底上的圆角卡(`--card` 底、`border-radius:12px`、1px 发丝边、`padding:34px 38px`、`margin-bottom:28px`);全文圆角统一在 9–14px 区间,柔和不锐利。正文 14.5px/1.55;h3 17px/600;小标签一律小号、大写、宽字距。
- **粘性导航条**:深底(`--ink`)`position:sticky` 顶栏,accent-bright 色小 logo/字标 + 各 section 锚点链接(不透明度 .85,hover 到 1)——长报告一跳直达。
- **封面块(不是细头带)**:深底大圆角覆盖块(radius 14px、padding ~44px、flex 可换行):accent-bright 宽字距 eyebrow → 40px/700 大标题(深底上用 `--accent-bright`)→ 21px 细体浅色副标 → meta 行(标签+值)→ accent 左边框的小号免责/口径说明。右侧一块**关键数字小面板**:半透明卡(`rgba(255,255,255,.08)`、radius 10),每行 = 大号数值 + 右对齐小标签,行间淡分隔线。
- **编号 section pill**:每节顶部一枚 accent 底小圆 pill(`padding:2px 10px; border-radius:14px`)写序号,下接 25px/700 的节标题,再一行 secondary 色副题 + 2px 下划线规。
- **语义 callout 家族(radius 9,按语义用、不当装饰)**:`box-hl` = accent 底白字关键结论(一页至多一两处);`box-warn` = 琥珀浅底+同调边框+深化文字的警示;`box-info` = 冷调浅底的补充说明。
- **指标网格**:3/4 列圆角指标卡(`--bg` 底、22px/700 数值 + 12.5px secondary 标签);主角指标用 `.accent` 反色变体(深底、accent-bright 数值)。
- **案例/数据卡**:3 列,发丝边 + 4–5px 彩色**顶边**,26px 大数 + 说明 + 斜体来源行。
- **分段/方案卡**:3 列,每张**不同颜色的顶边**(accent / green / ink)+ 同色小 pill 标签,内容用虚线分隔的列表行。
- **行动清单**:真 `<input type="checkbox">` 行(`accent-color:var(--accent)`)、虚线分隔,按小号彩色 h4 分组——用于行动计划/下一步。
- **表格**:深底表头(浅色文字、11px 大写宽字距)+ 发丝行线 + 偶数行斑马纹,置于圆角卡内。
- **图表**:纯 CSS 条形图(flex 行 = 定宽名称 + 浅色轨道 + 深色填充条,突出项 accent 底白字)或**内联 SVG 图表**均可,上方配一行宽字距小图表标题;禁用外部图表库。
- **响应式**:一个 `@media (max-width:820px)` 把所有网格收成单列、封面收紧内边距。
- **可编辑交付**:关键文本块可加 `contenteditable`(hover 虚线发丝 outline、focus accent outline)——交付的文件在浏览器里可直接改字;页脚小注里说明这一点。
- **打印**:`@media print` 去阴影白底,对深底/accent 元素加 `print-color-adjust:exact`。

## 骨架(照此扩展;{{...}} 为占位,按内容增删区块,tokens 与层级语言保持一致)

```html
<!DOCTYPE html>
<html lang="zh-Hans"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITLE}}</title><style>
:root{--ink:#1A1410;--bg:#F2EBE0;--card:#FAF5EE;--accent:#D94420;--accent-bright:#F06A20;--secondary:#6B5E52;--muted:#A8998C;--green:#2E6645;--line:#D8CFC4;
--warn-bg:#F7EDD8;--warn-line:#E3CFA0;--warn-ink:#7A5A14;--info-bg:#E9EEF2;--info-line:#C9D6DE;--info-ink:#2F4A5C}
*{box-sizing:border-box}
body{font-family:-apple-system,'Helvetica Neue','PingFang SC','Microsoft YaHei','Noto Sans SC',sans-serif;color:var(--ink);background:var(--bg);margin:0;font-size:14.5px;line-height:1.55}
.nav{position:sticky;top:0;z-index:9;background:var(--ink);display:flex;align-items:center;gap:18px;padding:10px 22px}
.nav .logo{color:var(--accent-bright);font-weight:800;letter-spacing:.06em;font-size:13px}
.nav a{color:#F2EBE0;opacity:.85;text-decoration:none;font-size:12.5px}.nav a:hover{opacity:1}
.wrap{width:min(1040px,calc(100vw - 24px));margin:24px auto}
.cover{background:var(--ink);border-radius:14px;padding:44px;display:flex;gap:32px;flex-wrap:wrap;justify-content:space-between;margin-bottom:28px}
.eyebrow{color:var(--accent-bright);font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;margin-bottom:10px}
.cover h1{margin:0 0 8px;color:var(--accent-bright);font-size:40px;font-weight:700;line-height:1.12;letter-spacing:-.01em}
.cover .sub{color:#EDE4D6;font-size:21px;font-weight:300;margin:0 0 18px}
.cover .meta{color:var(--muted);font-size:12.5px;margin:3px 0}.cover .meta b{color:#F5EEE3;font-weight:600}
.cover .disclaimer{border-left:3px solid var(--accent-bright);padding:6px 12px;font-size:12px;color:#C9BCAD;margin-top:16px}
.stats{background:rgba(255,255,255,.08);border-radius:10px;padding:14px 22px;min-width:230px;align-self:flex-start}
.stats .row{display:flex;justify-content:space-between;align-items:baseline;gap:18px;padding:9px 0;border-bottom:1px solid rgba(255,255,255,.12)}
.stats .row:last-child{border-bottom:0}.stats .v{color:#F5EEE3;font-size:22px;font-weight:700}.stats .l{color:var(--muted);font-size:11.5px;text-align:right}
section.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:34px 38px;margin-bottom:28px}
.pill{display:inline-block;background:var(--accent);color:#fff;font-size:11px;font-weight:700;padding:2px 10px;border-radius:14px;letter-spacing:.08em}
h2{margin:10px 0 4px;font-size:25px;font-weight:700;letter-spacing:-.01em}
.h2sub{color:var(--secondary);font-size:13px;padding-bottom:10px;border-bottom:2px solid var(--line);margin-bottom:18px}
h3{font-size:17px;font-weight:600;margin:22px 0 10px}
.box-hl{background:var(--accent);color:#fff;border-radius:9px;padding:14px 18px;font-weight:700;margin:18px 0}
.box-warn{background:var(--warn-bg);border:1px solid var(--warn-line);color:var(--warn-ink);border-radius:9px;padding:12px 16px;margin:18px 0}
.box-info{background:var(--info-bg);border:1px solid var(--info-line);color:var(--info-ink);border-radius:9px;padding:12px 16px;margin:18px 0}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0}
.metric{background:var(--bg);border-radius:10px;padding:16px 14px}
.metric .v{font-size:22px;font-weight:700}.metric .l{color:var(--secondary);font-size:12.5px;margin-top:4px}
.metric.accent{background:var(--ink)}.metric.accent .v{color:var(--accent-bright)}.metric.accent .l{color:var(--muted)}
.cases{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:18px 0}
.case{border:1px solid var(--line);border-top:4px solid var(--accent);border-radius:10px;padding:16px}
.case .v{font-size:26px;font-weight:700}.case .src{color:var(--secondary);font-size:11.5px;font-style:italic;margin-top:8px}
.segs{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:18px 0}
.seg{border:1px solid var(--line);border-top:5px solid var(--accent);border-radius:10px;padding:16px}
.seg.g{border-top-color:var(--green)}.seg.k{border-top-color:var(--ink)}
.seg .pill.g{background:var(--green)}.seg .pill.k{background:var(--ink)}
.seg ul{list-style:none;margin:10px 0 0;padding:0}.seg li{padding:7px 0;border-bottom:1px dashed var(--line);font-size:13px}
.checks h4{font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--accent);margin:16px 0 4px}
.checks label{display:flex;gap:10px;align-items:flex-start;padding:8px 0;border-bottom:1px dashed var(--line);font-size:13.5px}
.checks input{accent-color:var(--accent);margin-top:2px}
table{width:100%;border-collapse:collapse;font-size:13px;margin:14px 0}
th{background:var(--ink);color:#F2EBE0;padding:9px 10px;text-align:left;font-weight:700;font-size:11px;letter-spacing:.05em;text-transform:uppercase}
td{border-bottom:1px solid var(--line);padding:9px 10px;vertical-align:top}
tbody tr:nth-child(even) td{background:var(--bg)}
.chart-title{font-size:10.5px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--secondary);margin:16px 0 8px}
.bar-row{display:flex;align-items:center;gap:10px;margin:9px 0}
.bar-name{width:120px;font-size:12px;font-weight:700;flex:none}
.bar-track{flex:1;background:#E4DACB;height:22px;border-radius:6px;overflow:hidden}
.bar-fill{height:100%;background:var(--ink);display:flex;align-items:center;justify-content:flex-end;padding-right:8px;color:var(--accent-bright);font-size:11px;font-weight:700}
.bar-fill.hl{background:var(--accent);color:#fff}
.tag-ok{display:inline-block;background:var(--green);color:#fff;font-size:10px;font-weight:800;padding:2px 8px;border-radius:6px}
[contenteditable]:hover{outline:1px dashed var(--line)}[contenteditable]:focus{outline:2px solid var(--accent);outline-offset:2px}
.footer{color:var(--secondary);font-size:11.5px;padding:2px 6px 30px}
@media (max-width:820px){.metrics,.cases,.segs{grid-template-columns:1fr}.cover{padding:28px}}
@media print{body{background:#fff}.nav{display:none}section.card{border:0;padding:20px 0}
.cover,.box-hl,.metric.accent,th,.bar-fill,.pill{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
</style></head>
<body>
<nav class="nav"><span class="logo">{{字标}}</span><a href="#s1">{{节一}}</a><a href="#s2">{{节二}}</a></nav>
<div class="wrap">
  <div class="cover">
    <div style="flex:1;min-width:300px">
      <div class="eyebrow">{{EYEBROW · 报告类别}}</div>
      <h1 contenteditable>{{TITLE}}</h1>
      <p class="sub" contenteditable>{{一句副标:这份报告回答什么问题}}</p>
      <div class="meta">{{标签}}:<b>{{值}}</b></div>
      <div class="meta">{{标签}}:<b>{{值}}</b></div>
      <div class="disclaimer">{{口径/免责一句话}}</div>
    </div>
    <div class="stats">
      <div class="row"><span class="v">{{数值}}</span><span class="l">{{标签}}</span></div>
      <div class="row"><span class="v">{{数值}}</span><span class="l">{{标签}}</span></div>
      <div class="row"><span class="v">{{数值}}</span><span class="l">{{标签}}</span></div>
    </div>
  </div>
  <section class="card" id="s1">
    <span class="pill">01</span><h2>{{节标题 = 本节结论}}</h2><div class="h2sub">{{一行副题}}</div>
    <p contenteditable>{{导语段落}}</p>
    <div class="metrics">
      <div class="metric accent"><div class="v">{{主角数值}}</div><div class="l">{{标签}}</div></div>
      <div class="metric"><div class="v">{{数值}}</div><div class="l">{{标签}}</div></div>
      <div class="metric"><div class="v">{{数值}}</div><div class="l">{{标签}}</div></div>
      <div class="metric"><div class="v">{{数值}}</div><div class="l">{{标签}}</div></div>
    </div>
    <div class="box-hl">{{本节最重要的一句结论}}</div>
    <div class="box-warn">{{警示/风险,仅在确有风险时用}}</div>
  </section>
  <section class="card" id="s2">
    <span class="pill">02</span><h2>{{节标题}}</h2><div class="h2sub">{{一行副题}}</div>
    <table><thead><tr><th>{{列}}</th><th>{{列}}</th><th>{{列}}</th></tr></thead>
      <tbody><tr><td>{{…}}</td><td>{{…}}</td><td>{{…}}</td></tr></tbody></table>
    <div class="chart-title">{{图表标题}}</div>
    <div class="bar-row"><div class="bar-name">{{项}}</div><div class="bar-track"><div class="bar-fill hl" style="width:100%">{{值}}</div></div></div>
    <div class="bar-row"><div class="bar-name">{{项}}</div><div class="bar-track"><div class="bar-fill" style="width:58%">{{值}}</div></div></div>
    <div class="checks"><h4>{{行动组标题}}</h4>
      <label><input type="checkbox">{{行动项}}</label>
      <label><input type="checkbox">{{行动项}}</label>
    </div>
  </section>
  <div class="footer">{{数据来源 · 口径}} · 本文件可在浏览器中直接编辑文字(点击文本即可修改)。</div>
</div></body></html>
```
