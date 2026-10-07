"""Build aralem.dev/arslan/docs/ from docs-site/sections/*.html and docs-site/data/*.json.

    python3 docs-site/build.py            # writes docs/docs/index.html (+ diagrams/)

The chapters are HTML fragments. {{source:path|label}} becomes a GitHub link pinned to
the baseline commit in baseline.json, so every claim points at the code it was checked
against. When a release ships: update baseline.json, data/versions.json, the chapters
that changed, then rebuild. The build warns when the baseline lags the app version.

Origin: content drafted by Codex (2026-10-07), audited against v0.1.53 and restyled to
match the project site (2026-10-08).
"""
from pathlib import Path
import html
import json
import re

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
OUT_DIR = REPO / "docs" / "docs"
BASE = json.loads((ROOT / "baseline.json").read_text())
SHA = BASE["sha"]
GH = "https://github.com/mirzatghayrat/arslan"


def source(path: str, label: str) -> str:
    return (f'<a class="src" href="{GH}/blob/{SHA}/{html.escape(path)}" target="_blank" '
            f'rel="noopener">{html.escape(label)}</a>')


def version_table() -> str:
    rows = []
    for v in json.loads((ROOT / "data/versions.json").read_text()):
        if isinstance(v, str):
            continue
        ver = v.get("version", v.get("tag", ""))
        date = v.get("date_shanghai", v.get("published_date_shanghai", v.get("date", "")))
        summary = v.get("summary_zh", v.get("summary", ""))
        if isinstance(summary, list):
            summary = "；".join(summary)
        status = {"published_stable": "正式发布",
                  "tag_only_no_current_public_release": "仅标签；无公开 Release"}.get(v.get("status", ""), v.get("status", ""))
        if v.get("status_note"):
            status = v["status_note"]
        url = next((e["url"] for e in v.get("evidence", []) if e.get("type") == "github_release"), f"{GH}/tree/{ver}")
        rows.append(f'<tr data-version="{html.escape(ver)}"><th><a href="{html.escape(url)}" target="_blank" rel="noopener">'
                    f'{html.escape(ver)}</a></th><td>{html.escape(str(date))}</td><td>{html.escape(str(status))}</td>'
                    f'<td><strong>{html.escape(v.get("title", ""))}</strong><br>{html.escape(str(summary))}</td></tr>')
    return ('<div class="table-wrap"><table id="version-table"><thead><tr><th>版本</th><th>北京时间</th><th>状态</th>'
            '<th>这一版做了什么</th></tr></thead><tbody>' + "".join(reversed(rows)) + "</tbody></table></div>")


def beta_table() -> str:
    rows = []
    for v in json.loads((ROOT / "data/prereleases.json").read_text()):
        date = (v.get("published_at_shanghai") or "")[:10] or "未公开发布"
        status = "公开预发布" if v["status"] == "published_prerelease" else "未公开候选／文稿"
        url = v.get("evidence_url") or f"{GH}/blob/{SHA}/docs/releases/{v['version']}.md"
        rows.append(f'<tr><th><a href="{url}" target="_blank" rel="noopener">{v["version"]}</a></th>'
                    f'<td>{date}<br>{status}</td><td>{html.escape(v["summary"])}</td></tr>')
    return ('<div class="table-wrap"><table><thead><tr><th>测试版</th><th>日期与状态</th><th>主要变化和边界</th></tr>'
            '</thead><tbody>' + "".join(rows) + "</tbody></table></div>")


# The chapters' diagrams were drawn for a light page; these are their dark equivalents.
SVG_COLOURS = {"#e0e9df": "#0f1318", "#bacbbb": "#262b33", "#5c8071": "#7d8590",
               "#f4ebd7": "#1d1709", "#b6a177": "#8a6a1f"}

CSS = r"""
:root{--bg:#050506;--s1:#0b0c0f;--s2:#111318;--s3:#171a20;--line:rgba(255,255,255,.075);--line2:rgba(255,255,255,.14);
--tx:#f2f3f6;--tx2:#c9cdd5;--mu:#9aa0ab;--dim:#5f646d;--work:#3b9eff;--ask:#f5a524;--done:#34d399;--stop:#ff6b57;--search:#7c83ff;
--ui:-apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC","Hiragino Sans GB","Helvetica Neue",Arial,sans-serif;
--mono:"SF Mono",ui-monospace,"JetBrains Mono",Menlo,Consolas,monospace}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:84px;-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--tx2);font:16px/1.85 var(--ui);-webkit-font-smoothing:antialiased}
a{color:#8ab4ff;text-decoration:none}a:hover{text-decoration:underline;text-underline-offset:3px}
:focus-visible{outline:2px solid #8ab4ff;outline-offset:3px;border-radius:6px}
.nav{position:fixed;top:0;left:0;right:0;z-index:50;height:60px;display:flex;align-items:center;gap:24px;padding:0 24px;
background:rgba(5,5,6,.78);backdrop-filter:saturate(180%) blur(18px);-webkit-backdrop-filter:saturate(180%) blur(18px);border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:17px;color:var(--tx)}.brand:hover{text-decoration:none}.brand svg{width:26px;height:26px}
.brand small{font:500 12px var(--mono);color:var(--mu);border:1px solid var(--line2);border-radius:6px;padding:2px 7px;margin-left:4px}
.nav .links{display:flex;gap:22px;font-size:14px}.nav .links a{color:var(--mu)}.nav .links a:hover{color:var(--tx);text-decoration:none}
.nav .sp{flex:1}.nav .menu{display:none;white-space:nowrap;flex:none;background:transparent;border:1px solid var(--line2);color:var(--tx);border-radius:8px;padding:4px 10px;font:13px var(--ui)}
.btn{display:inline-flex;align-items:center;height:36px;padding:0 16px;border-radius:999px;font-weight:600;font-size:14px;background:#f5f6f8;color:#0b0c0e}.btn:hover{text-decoration:none}
.progress{position:fixed;left:0;top:60px;height:2px;width:100%;transform-origin:left;transform:scaleX(0);background:linear-gradient(90deg,var(--work),var(--search),var(--done));z-index:51}
.layout{display:grid;grid-template-columns:260px minmax(0,1fr) 220px;max-width:1440px;margin:0 auto;padding-top:60px}
.side{position:sticky;top:60px;height:calc(100vh - 60px);overflow-y:auto;padding:28px 14px 40px 24px;border-right:1px solid var(--line);scrollbar-width:thin}
.side .lbl,.toc .lbl{font:500 11px var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--dim);margin:0 0 10px 10px}
.side a{display:grid;grid-template-columns:28px 1fr;gap:4px;padding:7px 10px;border-radius:8px;color:var(--mu);font-size:13.5px;line-height:1.45}
.side a span{font:12px var(--mono);color:var(--dim);padding-top:1px}
.side a:hover{background:rgba(255,255,255,.04);color:var(--tx);text-decoration:none}
.side a.on{background:rgba(255,255,255,.07);color:var(--tx)}.side a.on span{color:var(--work)}
.side .base{margin:22px 10px 0;padding-top:16px;border-top:1px solid var(--line);font:12px/1.7 var(--mono);color:var(--dim)}
.side .base a{display:inline;padding:0;color:var(--mu)}
main{min-width:0;padding:0 56px 120px}
.toc{position:sticky;top:60px;height:calc(100vh - 60px);overflow-y:auto;padding:30px 20px 40px 8px;font-size:13px}
.toc a{display:block;padding:4px 0 4px 12px;border-left:1px solid var(--line);color:var(--dim);line-height:1.5}
.toc a:hover{color:var(--tx);text-decoration:none}.toc a.on{color:var(--tx);border-left-color:var(--work)}
.hero{padding:64px 0 40px;border-bottom:1px solid var(--line);margin-bottom:8px}
.eyebrow{font:500 12px var(--mono);letter-spacing:.16em;text-transform:uppercase;color:var(--mu);display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.badge{display:inline-flex;align-items:center;gap:6px;font:500 11px var(--mono);letter-spacing:.04em;padding:4px 8px;border-radius:6px;border:1px solid var(--line2);color:var(--mu);text-transform:none}
.badge.ok{color:var(--done);border-color:rgba(52,211,153,.4);background:rgba(52,211,153,.08)}
.badge.soon{color:var(--ask);border-color:rgba(245,165,36,.4);background:rgba(245,165,36,.08)}
.hero h1{margin:22px 0 0;color:var(--tx);font-size:clamp(38px,5.4vw,64px);line-height:1.08;letter-spacing:-.03em;font-weight:700}
.hero h1 span{display:block;margin-top:14px;font-size:.4em;letter-spacing:-.01em;line-height:1.5;font-weight:600;background:linear-gradient(180deg,#fff,#7d828c 130%);-webkit-background-clip:text;background-clip:text;color:transparent}
.hero .lead{margin:22px 0 0;font-size:18px;color:var(--mu);max-width:44em}
.stats{display:grid;grid-template-columns:repeat(3,1fr);margin-top:34px;border:1px solid var(--line);border-radius:16px;overflow:hidden;background:var(--s1)}
.stats div{padding:18px 20px;border-left:1px solid var(--line)}.stats div:first-child{border-left:0}
.stats b{display:block;color:var(--tx);font-size:22px;letter-spacing:-.02em}.stats p{margin:4px 0 0;font-size:12.5px;line-height:1.6;color:var(--mu)}
.chapter{padding:56px 0 28px;border-bottom:1px solid var(--line);scroll-margin-top:70px}
.chapter>h2{margin:0 0 26px;color:var(--tx);font-size:30px;line-height:1.3;letter-spacing:-.02em;font-weight:700}
.num{display:block;margin-bottom:10px;font:500 12px var(--mono);letter-spacing:.14em;color:var(--work)}
h3{color:var(--tx);font-size:20px;line-height:1.45;margin:38px 0 12px;letter-spacing:-.01em;scroll-margin-top:76px}
h4{color:var(--tx);font-size:16px;margin:20px 0 6px}
p{margin:12px 0}strong,b{color:var(--tx);font-weight:600}li{margin:6px 0}ul,ol{padding-left:22px}
code{font:.86em var(--mono);color:var(--tx);background:rgba(255,255,255,.06);border:1px solid var(--line);border-radius:5px;padding:1px 5px;overflow-wrap:anywhere}
pre{background:var(--s1);border:1px solid var(--line);border-radius:12px;padding:16px 18px;overflow:auto;font:13px/1.6 var(--mono)}pre code{background:none;border:0;padding:0}
blockquote{margin:22px 0;padding:16px 22px;border-left:3px solid var(--work);background:rgba(59,158,255,.06);border-radius:0 12px 12px 0;color:var(--tx2)}
.note{margin:20px 0;padding:12px 18px;border:1px solid var(--line);border-radius:12px;background:var(--s1);font-size:14.5px;color:var(--mu)}
.note.important{border-color:rgba(245,165,36,.35);background:rgba(245,165,36,.06);color:var(--tx2)}
.evidence{margin:16px 0 4px;font:12.5px/1.9 var(--mono);color:var(--dim)}
.evidence a.src,a.src{color:var(--mu);border-bottom:1px dashed var(--line2)}a.src:hover{color:var(--tx);text-decoration:none}
.pill{display:inline-block;font:500 11px var(--mono);padding:2px 8px;border-radius:5px;color:var(--done);background:rgba(52,211,153,.1);vertical-align:middle}
.pill.warn{color:var(--ask);background:rgba(245,165,36,.1)}.pill.future{color:var(--search);background:rgba(124,131,255,.12)}
.table-wrap{margin:20px 0;overflow:auto;border:1px solid var(--line);border-radius:14px;background:var(--s1)}
table{border-collapse:collapse;width:100%;min-width:620px;font-size:14px;line-height:1.75}
th,td{text-align:left;vertical-align:top;padding:12px 16px;border-bottom:1px solid var(--line)}
thead th{font:600 11.5px var(--mono);letter-spacing:.06em;color:var(--mu);background:var(--s2);white-space:nowrap}
tbody th{color:var(--tx);font-weight:600;min-width:96px}tbody tr:last-child>*{border-bottom:0}tbody tr:hover{background:rgba(255,255,255,.02)}
#version-table{font-size:13.5px}#version-table td:nth-child(2),#version-table td:nth-child(3){font:12px/1.7 var(--mono);color:var(--mu);white-space:nowrap}
.grid2,.grid3{display:grid;gap:16px;margin:20px 0}.grid2{grid-template-columns:repeat(2,minmax(0,1fr))}.grid3{grid-template-columns:repeat(3,minmax(0,1fr))}
.card{background:linear-gradient(180deg,var(--s2),var(--s1));border:1px solid var(--line);border-radius:16px;padding:20px 22px}
.card h3,.card h4{margin-top:0}.card p{font-size:14.5px}
.flow{display:flex;gap:26px;flex-wrap:wrap;margin:24px 0}
.flow-step{flex:1;min-width:150px;position:relative;background:var(--s1);border:1px solid var(--line2);border-radius:14px;padding:16px 18px;font-size:14px}
.flow-step:not(:last-child):after{content:"→";position:absolute;right:-20px;top:36%;color:var(--work)}
.flow-step b{display:block;font-size:15.5px;margin-bottom:4px}.flow-step span{color:var(--mu);font-size:12.5px}
.stage{position:relative;margin-left:8px;padding:6px 0 22px 30px;border-left:1px solid var(--line2)}
.stage:before{content:"";position:absolute;left:-5px;top:16px;width:9px;height:9px;border-radius:50%;background:var(--work);box-shadow:0 0 12px var(--work)}
.stage h3{margin:0 0 6px}.stage .date{font:12px var(--mono);color:var(--dim)}
.readroute{margin:24px 0;padding:18px 22px;border:1px solid var(--line);border-radius:14px;background:var(--s1)}
.diagram{margin:26px 0;padding:22px;overflow:auto;background:var(--s1);border:1px solid var(--line2);border-radius:16px}
.diagram svg{display:block;width:100%;height:auto;min-width:720px}
.diagram .box{fill:var(--s2);stroke:#3a404b;stroke-width:1.3}.diagram .dark{fill:#13325a;stroke:#3b9eff}
.diagram .planned{fill:#1d1709;stroke:#8a6a1f;stroke-dasharray:5 4}.diagram .boxtext{font-size:15px;font-weight:650;fill:#f2f3f6}
.diagram .small{font-size:12px;fill:#9aa0ab}.diagram .white{fill:#fff}.diagram .edge{fill:none;stroke:#7d8590;stroke-width:1.4}
.diagram .edge.dashed{stroke-dasharray:6 4}.diagram text{font-family:var(--ui)}
.diagram-caption{margin-top:12px;font-size:12.5px;line-height:1.8;color:var(--dim)}
.open-fig{display:inline-block;margin:0 0 10px;font:12px var(--mono);color:var(--mu)}
details{border-top:1px solid var(--line);padding:14px 0}details:last-of-type{border-bottom:1px solid var(--line)}
summary{cursor:pointer;color:var(--tx);font-weight:600;line-height:1.6;list-style:none;display:flex;gap:10px}
summary::-webkit-details-marker{display:none}summary:before{content:"+";font:600 15px var(--mono);color:var(--work);width:14px;flex:none}
details[open] summary:before{content:"–"}details>div{padding:8px 0 0 24px;font-size:15px}
.qa-label{font:12px var(--mono);color:var(--dim);margin-right:8px}
.search-row{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:18px 0}
.search-row input{width:340px;max-width:100%;height:40px;border-radius:10px;border:1px solid var(--line2);background:var(--s1);color:var(--tx);padding:0 12px;font:14px var(--mono);outline:0}
.search-row input:focus{border-color:rgba(59,158,255,.6);box-shadow:0 0 0 4px rgba(59,158,255,.12)}
.search-row span{font:12px var(--mono);color:var(--dim)}
.source-list{font-size:14px}.muted{color:var(--mu)}.tiny{font-size:12px}
.closing{margin-top:40px;font:12px/1.8 var(--mono);color:var(--dim)}
.screen-only{}[hidden]{display:none!important}
@media (max-width:1180px){.layout{grid-template-columns:240px minmax(0,1fr)}.toc{display:none}main{padding:0 36px 100px}}
@media (max-width:860px){.layout{grid-template-columns:1fr}.nav{gap:14px;padding:0 16px}.nav .links{display:none}.nav .menu{display:inline-block}
.side{position:fixed;top:60px;left:0;bottom:0;z-index:40;width:min(320px,86vw);height:auto;background:var(--bg);transform:translateX(-102%);transition:transform .25s ease;box-shadow:0 20px 60px rgba(0,0,0,.6)}
body.menu-open .side{transform:none}main{padding:0 18px 80px}.hero{padding:40px 0 28px}.stats{grid-template-columns:1fr}.stats div{border-left:0;border-top:1px solid var(--line)}.stats div:first-child{border-top:0}
.grid2,.grid3{grid-template-columns:1fr}.flow{flex-direction:column;gap:22px}.flow-step:not(:last-child):after{content:"↓";right:auto;left:50%;top:auto;bottom:-22px}
.chapter>h2{font-size:25px}.diagram{padding:12px}body{font-size:15.5px}}
@media (prefers-reduced-motion:reduce){*{transition:none!important;scroll-behavior:auto!important}}
@media print{.nav,.side,.toc,.progress,.screen-only,.search-row{display:none!important}.layout{display:block;padding:0}body{background:#fff;color:#111}main{padding:0}
.chapter>h2,h3,h4,strong,b,.hero h1{color:#111}.hero h1 span{color:#333;background:none}details>div{display:block!important}}
"""

MASK = ('<svg viewBox="250 190 750 840" aria-hidden="true"><path fill="#fff" d="M286 517L283 287C283 231 320 208 358 237L494 332Q626 280 758 332L894 237C932 208 969 231 969 287L966 517C966 562 982 603 963 651C944 694 909 731 880 777L811 890C758 974 698 1006 626 1006C554 1006 494 974 441 890L372 777C343 731 308 694 289 651C270 603 286 562 286 517Z"/>'
        '<path fill="#999" d="M310 496L307 286Q307 236 349 259L465 343Q376 404 310 496ZM942 496L945 286Q945 236 903 259L787 343Q876 404 942 496Z"/>'
        '<path d="M386 518C478 501 558 551 552 650C449 654 387 604 386 518ZM866 518C774 501 694 551 700 650C803 654 865 604 866 518Z"/>'
        '<g stroke="#000" stroke-width="14" stroke-linecap="round"><line x1="626" y1="696" x2="495" y2="813"/><line x1="626" y1="696" x2="757" y2="813"/><line x1="626" y1="696" x2="626" y2="893"/></g>'
        '<circle cx="626" cy="696" r="29"/><circle cx="495" cy="813" r="25"/><circle cx="757" cy="813" r="25"/><circle cx="626" cy="893" r="30"/></svg>')

JS = r"""
(function(){
var prog=document.getElementById('prog');
var chapters=[].slice.call(document.querySelectorAll('.chapter'));
var side=[].slice.call(document.querySelectorAll('.side a[data-ch]'));
var toc=document.getElementById('toc');var current=null;
function buildToc(ch){if(ch===current)return;current=ch;toc.innerHTML='<p class="lbl">本章</p>';
  [].slice.call(ch.querySelectorAll('h3[id]')).forEach(function(h){var a=document.createElement('a');a.href='#'+h.id;a.textContent=h.textContent;toc.appendChild(a)})}
function onScroll(){var h=document.documentElement.scrollHeight-innerHeight;prog.style.transform='scaleX('+(h>0?scrollY/h:0)+')';
  var cur=chapters[0];chapters.forEach(function(c){if(c.getBoundingClientRect().top<140)cur=c});
  side.forEach(function(a){a.classList.toggle('on',a.dataset.ch===cur.id)});buildToc(cur);
  var hs=[].slice.call(cur.querySelectorAll('h3[id]')),on=null;hs.forEach(function(h){if(h.getBoundingClientRect().top<160)on=h});
  [].slice.call(toc.querySelectorAll('a')).forEach(function(a){a.classList.toggle('on',on&&a.hash==='#'+on.id)})}
addEventListener('scroll',onScroll,{passive:true});addEventListener('resize',onScroll);onScroll();
var menu=document.getElementById('menu');menu.addEventListener('click',function(){document.body.classList.toggle('menu-open');menu.setAttribute('aria-expanded',document.body.classList.contains('menu-open'))});
side.forEach(function(a){a.addEventListener('click',function(){document.body.classList.remove('menu-open')})});
var q=document.getElementById('version-search');if(q){var rows=[].slice.call(document.querySelectorAll('#version-table tbody tr')),n=document.getElementById('version-count');
  function f(){var t=q.value.toLowerCase(),k=0;rows.forEach(function(r){r.hidden=t&&r.textContent.toLowerCase().indexOf(t)<0;if(!r.hidden)k++});n.textContent=t?k+' 条匹配':rows.length+' 条版本记录'}
  q.addEventListener('input',f);f()}
})();
"""


def build() -> None:
    files = sorted((ROOT / "sections").glob("*.html"))
    chapters, side = [], []
    for f in files:
        t = f.read_text()
        t = t.replace("<!-- VERSION_TABLE -->", version_table()).replace("<!-- BETA_TABLE -->", beta_table())
        t = re.sub(r"\{\{source:([^|}]+)\|([^}]+)\}\}", lambda m: source(m[1], m[2]), t)
        for old, new in SVG_COLOURS.items():
            t = t.replace(f'"{old}"', f'"{new}"').replace(f'"{old.upper()}"', f'"{new}"')
        sec = re.search(r'<section[^>]+id="([^"]+)"[^>]*>\s*<h2><span class="num">(\d+)\s*/\s*([^<]+)</span>', t)
        if sec:
            side.append(f'<a href="#{sec[1]}" data-ch="{sec[1]}"><span>{sec[2]}</span>{html.escape(sec[3].strip())}</a>')
        # give every h3 an id for the "on this page" list
        k = [0]

        def h3id(m, cid=sec[1] if sec else f.stem):
            k[0] += 1
            return f'<h3 id="{cid}-{k[0]}"' + m[1]
        t = re.sub(r"<h3(?! id=)(\s|>)", h3id, t)
        # newest release first: readers come for what changed lately
        def newest_first(m):
            rows = re.findall(r"<tr\b.*?</tr>", m[2], re.S)
            return m[1] + "".join(reversed(rows)) + m[3]
        t = re.sub(r'(<table id="version-table">.*?<tbody>)(.*?)(</tbody>)', newest_first, t, flags=re.S)
        chapters.append(t)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    version = BASE["version"]
    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Arslan 技术文档 · 基于 {version}</title>
<meta name="description" content="Arslan 的设计、实现与演进：系统架构、执行运行时、数据与记忆、安全边界、iPhone 桥接、交付与验证。每个结论都链接到 {version} 的源码。">
<meta name="theme-color" content="#050506">
<link rel="canonical" href="https://aralem.dev/arslan/docs/">
<link rel="icon" type="image/svg+xml" href="../assets/v2/favicon.svg">
<meta property="og:title" content="Arslan 技术文档">
<meta property="og:description" content="把 Arslan 讲清楚：从最早原型到 {version} 的设计、实现与演进。">
<meta property="og:image" content="https://aralem.dev/arslan/assets/v2/og.jpg">
<meta name="twitter:card" content="summary_large_image">
<style>{CSS}</style>
</head>
<body>
<div class="progress" id="prog" aria-hidden="true"></div>
<nav class="nav" aria-label="Main">
  <button class="menu" id="menu" type="button" aria-expanded="false" aria-controls="side">目录</button>
  <a class="brand" href="../">{MASK}Arslan<small>Docs</small></a>
  <div class="links"><a href="../#how">How it works</a><a href="../#gate">The gate</a><a href="../#hands">Hands</a><a href="../#devices">Mac + iPhone</a><a href="../#privacy">Privacy</a></div>
  <span class="sp"></span>
  <div class="links"><a href="{GH}">GitHub</a></div>
  <a class="btn" href="{GH}/releases/latest/download/Arslan-macos-arm64.dmg">Download</a>
</nav>
<div class="layout">
<aside class="side" id="side" aria-label="章节目录">
  <p class="lbl">目录</p>
  {''.join(side)}
  <div class="base">基于正式版 {version}<br>源码 <a href="{GH}/tree/{SHA}">{SHA[:8]}</a><br>核对 {BASE["checked"]}</div>
</aside>
<main>
<header class="hero">
  <p class="eyebrow">Arslan Docs <span class="badge ok">基于 {version}</span><span class="badge">中文</span><span class="badge soon">English coming</span></p>
  <h1>把 Arslan 讲清楚。<span>从最早原型到 {version} 的设计、实现与演进</span></h1>
  <p class="lead">一个本地优先、开源的 Mac 个人 AI 助手：它的产品选择、运行机制、数据与权限，以及五十多个版本积累下来的工程经验。正文区分已发布实现、历史设计和后续方向；每个结论都链接到 {version} 的源码。</p>
  <div class="stats">{BASE["stats_html"]}</div>
</header>
{''.join(chapters)}
<p class="closing">Arslan 技术文档 · 基于 {version}（源码 {SHA[:12]}），核对 {BASE["checked"]}。内容会随新版本更新；源文件在仓库的 docs-site/ 目录。</p>
</main>
<nav class="toc" id="toc" aria-label="本章"></nav>
</div>
<script>{JS}</script>
</body>
</html>
"""
    (OUT_DIR / "index.html").write_text(page)
    app_version = json.loads((REPO / "desktop/src-tauri/tauri.conf.json").read_text())["version"]
    if "v" + app_version != version:
        print(f"WARNING: docs baseline is {version}, the app is v{app_version}: update the chapters and baseline.json")
    print(json.dumps({"out": str(OUT_DIR / "index.html"), "bytes": len(page.encode()), "chapters": len(files)}, ensure_ascii=False))


if __name__ == "__main__":
    build()
