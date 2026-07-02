---
name: designed-html-report
description: 设计版报告 —— 报告/简报/调研/方案等长篇交付物默认产出自带完整设计系统的单文件 HTML,而非 markdown 长文墙。
version: 0.1.0
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

## 默认设计系统(House style)

- **Tokens(`:root`)**:`--ink:#1e1e1e`(正文与深底)、`--bg:#f6f4f2`(暖纸页面底)、`--accent:#eeff53`(唯一强调色,默认柠檬黄绿;用户有品牌色时只换这一个)、`--green:#54665a`(次级文字/图形)、`--line:#e4e4e4`(发丝分隔线);内容载体是白色页卡。
- **页面骨架**:居中白卡 `width:min(1040px, calc(100vw - 24px))` + 柔和阴影,浮在暖纸底上。
- **深色页头带**:eyebrow 小标(accent 色、11px、大写、宽字距)→ 大标题(白、800、紧行高、微负字距)→ 灰副标;右上角一枚 accent 徽章点题。
- **Section 标签**:10px、700、大写、`.14em` 字距、green 色——每个区块用它定调,再接 19px/800 的小节标题。
- **KPI 网格**:深底 `gap:2px` 露缝的白格子,每格 accent 色 3px 底边;小号大写标签 + 大号 800 数字 + 一行小注。
- **表格**:表头深底 + accent 文字(11px 大写宽字距);单元格发丝边框;偶数行暖纸色斑马纹。
- **Keybox 要点框**:暖纸底 + 4px accent 左边框,装结论性要点列表。
- **纯 CSS 条形图**:flex 行 = 名称(定宽)+ 浅色轨道 + 深色填充条(数值右对齐、accent 字);要突出的那根用 accent 底 + ink 字。禁用外部图表库。
- **强调 callout**:accent 底、ink 字、加粗——一页至多一两处,放最重要的结论。
- **页脚带**:深底、灰字、11px,写数据来源与口径/免责说明。
- **打印**:`@media print` 去阴影白底,对深底/accent 元素加 `print-color-adjust:exact`。

## 骨架(照此扩展;{{...}} 为占位,按内容增删区块,tokens 与层级语言保持一致)

```html
<!DOCTYPE html>
<html lang="zh-Hans"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITLE}}</title><style>
:root{--ink:#1e1e1e;--bg:#f6f4f2;--accent:#eeff53;--green:#54665a;--line:#e4e4e4}
*{box-sizing:border-box}
body{font-family:-apple-system,'Helvetica Neue','PingFang SC','Microsoft YaHei','Noto Sans SC',sans-serif;color:var(--ink);background:var(--bg);margin:0;font-size:14px;line-height:1.5}
.page{width:min(1040px,calc(100vw - 24px));margin:24px auto;background:#fff;box-shadow:0 4px 32px rgba(30,30,30,.10)}
.header{background:var(--ink);padding:26px 40px 22px;display:flex;align-items:flex-end;justify-content:space-between;gap:20px}
.eyebrow{color:var(--accent);font-size:11px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;margin-bottom:9px}
.header h1{margin:0 0 6px;color:#fff;font-size:29px;font-weight:800;line-height:1.15;letter-spacing:-.01em}
.header .sub{color:#bfbda7;font-size:13px}
.badge{background:var(--accent);color:var(--ink);font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;padding:6px 14px;white-space:nowrap;align-self:flex-start}
.body{padding:30px 40px 36px}
.section-label{font-size:10px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--green);margin:30px 0 8px}
h2{margin:0 0 12px;font-size:19px;font-weight:800;letter-spacing:-.01em}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:2px;margin-bottom:28px;background:var(--ink)}
.kpi{background:#fff;padding:16px 12px;text-align:center;border-bottom:3px solid var(--accent)}
.kpi .l{color:#666;font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;margin-bottom:7px}
.kpi .v{font-size:23px;font-weight:800;letter-spacing:-.02em}.kpi .d{color:#888;font-size:11px;margin-top:3px}
table{width:100%;border-collapse:collapse;font-size:13px;background:#fff;margin-bottom:18px}
th{background:var(--ink);color:var(--accent);border:1px solid var(--ink);padding:9px 10px;text-align:left;font-weight:700;font-size:11px;letter-spacing:.05em;text-transform:uppercase}
td{border:1px solid var(--line);padding:9px 10px;vertical-align:top}
tbody tr:nth-child(even) td{background:var(--bg)}
.keybox{background:var(--bg);border-left:4px solid var(--accent);padding:16px 18px;margin:0 0 26px}
.bars{background:var(--bg);padding:16px}.bar-row{display:flex;align-items:center;gap:10px;margin:9px 0}
.bar-name{width:120px;font-size:12px;font-weight:700;flex:none}
.bar-track{flex:1;background:#e8e6e1;height:22px;border-radius:4px;overflow:hidden}
.bar-fill{height:100%;background:var(--ink);display:flex;align-items:center;justify-content:flex-end;padding-right:8px;color:var(--accent);font-size:11px;font-weight:700}
.bar-fill.hl{background:var(--accent);color:var(--ink)}
.hl-callout{background:var(--accent);color:var(--ink);padding:14px 18px;font-weight:700;margin:20px 0 0}
.footer{background:var(--ink);color:#bfbda7;padding:18px 40px;font-size:11px;margin-top:30px}
@media print{body{background:#fff}.page{box-shadow:none;margin:0;width:100%}
.header,.footer,.kpi,th,.hl-callout,.bar-fill{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
</style></head>
<body><div class="page">
  <div class="header"><div>
    <div class="eyebrow">{{EYEBROW · 报告类别}}</div>
    <h1>{{TITLE}}</h1>
    <div class="sub">{{副标 · 范围 · 日期}}</div>
  </div><div class="badge">{{BADGE}}</div></div>
  <div class="body">
    <p>{{一段导语:这份报告回答什么问题、依据什么材料。}}</p>
    <div class="kpis">
      <div class="kpi"><div class="l">{{指标名}}</div><div class="v">{{数值}}</div><div class="d">{{口径}}</div></div>
      <div class="kpi"><div class="l">{{指标名}}</div><div class="v">{{数值}}</div><div class="d">{{口径}}</div></div>
      <div class="kpi"><div class="l">{{指标名}}</div><div class="v">{{数值}}</div><div class="d">{{口径}}</div></div>
      <div class="kpi"><div class="l">{{指标名}}</div><div class="v">{{数值}}</div><div class="d">{{口径}}</div></div>
    </div>
    <div class="section-label">{{SECTION LABEL}}</div>
    <h2>{{小节标题}}</h2>
    <table><thead><tr><th>{{列}}</th><th>{{列}}</th><th>{{列}}</th></tr></thead>
      <tbody><tr><td>{{…}}</td><td>{{…}}</td><td>{{…}}</td></tr></tbody></table>
    <div class="keybox"><ul><li>{{关键要点}}</li><li>{{关键要点}}</li></ul></div>
    <div class="bars">
      <div class="bar-row"><div class="bar-name">{{项}}</div><div class="bar-track"><div class="bar-fill hl" style="width:100%">{{值}}</div></div></div>
      <div class="bar-row"><div class="bar-name">{{项}}</div><div class="bar-track"><div class="bar-fill" style="width:58%">{{值}}</div></div></div>
    </div>
    <div class="hl-callout">{{一句最重要的结论}}</div>
  </div>
  <div class="footer">{{数据来源 · 口径与免责说明}}</div>
</div></body></html>
```
