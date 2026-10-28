---
name: designed-html-report
description: Designed report — for reports, briefs, research, proposals and other long deliverables, produce by default a single-file HTML document with a complete design system (rounded-card layout, sticky navigation, semantic callouts, editable text) instead of a wall of Markdown.
version: 0.3.0
authors:
  - Arslan
---

## Trigger

Activate when the user asks for a report, brief, research write-up, proposal, analysis, retrospective or insight report, or any long deliverable that will clearly be saved, forwarded or printed: produce a **complete single-file HTML document**, not a wall of Markdown.

**How to output it (this matters):** the whole reply is the HTML document itself — it starts with `<!DOCTYPE html>` and ends with `</html>`, with **no explanatory text before it and no ```html code fence around it**. The client renders a preview / copy / download card only when the whole message starts with `<!DOCTYPE html>`; a fence or one extra sentence at the start breaks that and turns the reply back into a wall of code. (The fenced skeleton below is a reference for you; do not fence the real reply.)

Everyday questions, short replies and chat stay plain text — do not over-trigger.

## Decision Rules

1. **A project design spec overrides everything:** if the task context (attached material or knowledge-base results) contains a project design spec — a file like `*-design.md` or `design.md` — **follow it completely** for tokens, fonts and layout, and set this skill's default design system aside. Each project can have its own spec (project A → A-design.md).
2. **Next, what the user has said:** style preferences the user stated in the conversation (accent colour, tone, brand feel) come first within the default layout structure.
3. **Otherwise use the default design system without asking:** for an ordinary report, **do not** ask the user about design preferences; deliver the finished document.
4. **Exception for large or external branded deliverables:** when the deliverable is clearly a large client-facing or branded artifact (a deck, a client report) and there is no design.md, it is worth asking **one short question** with three options: use the default style / describe a preference / provide a design.md (which can be saved to the knowledge base and reused for this project). Continue as soon as there is an answer; do not press.
5. **Honest data:** every number in the report comes from the conversation or a tool result; never invent metrics or cases; when something is unknown, write "unknown / to be confirmed" in the report's language.
6. **Single file, no external dependencies:** no external CDN scripts, fonts or images; use the system font stack with 'PingFang SC' / 'Noto Sans SC' as fallbacks; the file opens complete when double-clicked from disk, and prints cleanly under `@media print`.
7. **The report's language is the user's language:** write the content in the language the user is using, and set `<html lang>` to match.

## Default design system (house style · warm Ember palette · rounded-card layout, calibrated for WCAG AA)

- **Tokens (`:root`):** `--ink:#1A1410` (warm black, body text and dark surfaces), `--bg:#F2EBE0` (wheat paper page background), `--card:#FAF5EE` (card background), `--accent:#D94420` (rust orange-red, the only accent; 4.6:1 on the off-white background, meets AA), `--accent-bright:#F06A20` (the accent on dark surfaces — inside a dark band always use it, never #D94420), `--secondary:#6B5E52` (secondary text), `--muted:#A8998C` (on light backgrounds **only for large text ≥18px**; small body text always uses secondary), `--green:#2E6645` (**only for "open source / success / positive" tags**, never a second main colour), `--line:#D8CFC4` (hairline borders). Semantic callouts may use two derived light tints (the only extension beyond Ember, and only for callouts): warn amber `--warn-bg:#F7EDD8/--warn-line:#E3CFA0/--warn-ink:#7A5A14`, info cool grey-blue `--info-bg:#E9EEF2/--info-line:#C9D6DE/--info-ink:#2F4A5C`.
- **Contrast rules:** on the accent background (#D94420) use **white text**; on the dark background (#1A1410) use `--accent-bright` for emphasis; if the user has a brand colour, change only the two accent values and leave the rest.
- **The base layout is rounded cards, not a full-width wall of text:** each section is a rounded card floating on the warm paper background (`--card` background, `border-radius:12px`, 1px hairline border, `padding:34px 38px`, `margin-bottom:28px`); all corner radii stay within 9–14px, soft rather than sharp. Body text 14.5px/1.55; h3 17px/600; small labels are always small, uppercase and widely letter-spaced.
- **Sticky navigation bar:** a dark (`--ink`) `position:sticky` top bar with a small logo or wordmark in accent-bright plus anchor links to each section (opacity .85, 1 on hover) — one click to any part of a long report.
- **A cover block (not a thin header strip):** a large dark block with rounded corners (radius 14px, padding ~44px, wrapping flex): a widely spaced accent-bright eyebrow → a 40px/700 title (in `--accent-bright` on the dark surface) → a 21px light subtitle in a pale colour → meta rows (label + value) → a small disclaimer or scope note with an accent left border. On the right, a **small key-numbers panel**: a translucent card (`rgba(255,255,255,.08)`, radius 10), each row a large value plus a small right-aligned label, with faint dividers between rows.
- **Numbered section pill:** at the top of each section, a small rounded accent pill (`padding:2px 10px; border-radius:14px`) with the number, then a 25px/700 section title, then one line of subtitle in secondary with a 2px rule underneath.
- **Semantic callout family (radius 9, used for meaning, not decoration):** `box-hl` = white text on accent for the key conclusion (at most one or two per page); `box-warn` = a warning on an amber tint with a matching border and deeper text; `box-info` = a supplementary note on a cool tint.
- **Metrics grid:** 3 or 4 columns of rounded metric cards (`--bg` background, 22px/700 value + 12.5px secondary label); the headline metric uses the inverted `.accent` variant (dark background, accent-bright value).
- **Case / data cards:** 3 columns, hairline border plus a 4–5px coloured **top border**, a 26px large number, a description and an italic source line.
- **Segment / option cards:** 3 columns, each with a **different coloured top border** (accent / green / ink) and a small pill label in the same colour; the content is list rows separated by dashed lines.
- **Action checklist:** real `<input type="checkbox">` rows (`accent-color:var(--accent)`), separated by dashed lines and grouped under small coloured h4 headings — for action plans and next steps.
- **Tables:** a dark header row (light text, 11px uppercase, wide letter-spacing), hairline row lines and zebra-striped even rows, inside a rounded card.
- **Charts:** either pure-CSS bar charts (a flex row = fixed-width name + light track + dark fill bar; the highlighted item is white on accent) or **inline SVG charts**, with a small widely spaced chart title above; external chart libraries are not allowed.
- **Responsive:** one `@media (max-width:820px)` collapses every grid to a single column and tightens the cover padding.
- **Editable deliverable:** key text blocks can carry `contenteditable` (dashed hairline outline on hover, accent outline on focus) — the delivered file can be edited directly in the browser; say so in a small footer note.
- **Print:** `@media print` removes shadows and uses a white background, and adds `print-color-adjust:exact` to dark and accent elements.

## Skeleton (extend from this; {{...}} are placeholders; add or remove blocks to fit the content, and keep the tokens and the visual hierarchy consistent)

```html
<!DOCTYPE html>
<html lang="{{LANG}}"><head><meta charset="utf-8">
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
<nav class="nav"><span class="logo">{{WORDMARK}}</span><a href="#s1">{{SECTION 1}}</a><a href="#s2">{{SECTION 2}}</a></nav>
<div class="wrap">
  <div class="cover">
    <div style="flex:1;min-width:300px">
      <div class="eyebrow">{{EYEBROW · REPORT TYPE}}</div>
      <h1 contenteditable>{{TITLE}}</h1>
      <p class="sub" contenteditable>{{One-line subtitle: the question this report answers}}</p>
      <div class="meta">{{Label}}: <b>{{Value}}</b></div>
      <div class="meta">{{Label}}: <b>{{Value}}</b></div>
      <div class="disclaimer">{{One sentence on scope / disclaimer}}</div>
    </div>
    <div class="stats">
      <div class="row"><span class="v">{{Value}}</span><span class="l">{{Label}}</span></div>
      <div class="row"><span class="v">{{Value}}</span><span class="l">{{Label}}</span></div>
      <div class="row"><span class="v">{{Value}}</span><span class="l">{{Label}}</span></div>
    </div>
  </div>
  <section class="card" id="s1">
    <span class="pill">01</span><h2>{{Section title = this section's conclusion}}</h2><div class="h2sub">{{One-line subtitle}}</div>
    <p contenteditable>{{Lead paragraph}}</p>
    <div class="metrics">
      <div class="metric accent"><div class="v">{{Headline value}}</div><div class="l">{{Label}}</div></div>
      <div class="metric"><div class="v">{{Value}}</div><div class="l">{{Label}}</div></div>
      <div class="metric"><div class="v">{{Value}}</div><div class="l">{{Label}}</div></div>
      <div class="metric"><div class="v">{{Value}}</div><div class="l">{{Label}}</div></div>
    </div>
    <div class="box-hl">{{The single most important conclusion of this section}}</div>
    <div class="box-warn">{{Warning / risk — only when there really is one}}</div>
  </section>
  <section class="card" id="s2">
    <span class="pill">02</span><h2>{{Section title}}</h2><div class="h2sub">{{One-line subtitle}}</div>
    <table><thead><tr><th>{{Column}}</th><th>{{Column}}</th><th>{{Column}}</th></tr></thead>
      <tbody><tr><td>{{…}}</td><td>{{…}}</td><td>{{…}}</td></tr></tbody></table>
    <div class="chart-title">{{Chart title}}</div>
    <div class="bar-row"><div class="bar-name">{{Item}}</div><div class="bar-track"><div class="bar-fill hl" style="width:100%">{{Value}}</div></div></div>
    <div class="bar-row"><div class="bar-name">{{Item}}</div><div class="bar-track"><div class="bar-fill" style="width:58%">{{Value}}</div></div></div>
    <div class="checks"><h4>{{Action group title}}</h4>
      <label><input type="checkbox">{{Action item}}</label>
      <label><input type="checkbox">{{Action item}}</label>
    </div>
  </section>
  <div class="footer">{{Data sources · scope}} · {{In the user's language: the text in this file can be edited in the browser (click any text to change it).}}</div>
</div></body></html>
```
