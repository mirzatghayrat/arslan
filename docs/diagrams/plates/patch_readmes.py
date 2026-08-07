"""Rewrites the plate alt texts and adds the film line in all six READMEs.

One script rather than twelve hand edits because the translations have to stay
in step: a change that lands only in README.md leaves five READMEs describing
pictures that are no longer there. Run from the repository root.
"""

import re
import sys

TEXT = {
    "README.md": dict(
        banner="Arslan — one becomes many: a local-first personal AI orchestrator for macOS",
        gif="Four screens of the shipped Arslan client — orchestration thread, spawns ledger, second brain, diagnostics",
        screens="The shipped Arslan client in four screens — orchestration thread, spawns ledger, second brain, diagnostics",
        film='<p align="center"><a href="docs/assets/arslan-clay-60s.mp4"><b>▶ Watch the 60-second film</b></a> — the clay-animated film the <a href="https://mirzatghayrat.github.io/arslan/">project site</a> is cut from. <br><sub>The screens above are the shipped client, unretouched.</sub></p>',
    ),
    "README.zh-CN.md": dict(
        banner="Arslan——一生多：本地优先的个人 AI 编排器（macOS）",
        gif="Arslan 客户端的四个真实界面——编排线程、分身名册、第二大脑、诊断",
        screens="Arslan 客户端的四个界面——编排线程、分身名册、第二大脑、诊断",
        film='<p align="center"><a href="docs/assets/arslan-clay-60s.mp4"><b>▶ 观看 60 秒短片</b></a>——与<a href="https://mirzatghayrat.github.io/arslan/">官网</a>同源的黏土动画短片。<br><sub>上面的界面截图来自已发布的客户端，未经修饰。</sub></p>',
    ),
    "README.de.md": dict(
        banner="Arslan — aus einem werden viele: ein local-first KI-Orchestrator für macOS",
        gif="Vier Screens des ausgelieferten Arslan-Clients — Orchestrierungs-Thread, Spawn-Register, Second Brain, Diagnose",
        screens="Der ausgelieferte Arslan-Client in vier Screens — Orchestrierungs-Thread, Spawn-Register, Second Brain, Diagnose",
        film='<p align="center"><a href="docs/assets/arslan-clay-60s.mp4"><b>▶ Den 60-Sekunden-Film ansehen</b></a> — derselbe Knetanimations-Film, aus dem die <a href="https://mirzatghayrat.github.io/arslan/">Projektseite</a> geschnitten ist. <br><sub>Die Screens oben sind der ausgelieferte Client, unretuschiert.</sub></p>',
    ),
    "README.ja.md": dict(
        banner="Arslan — 一つが多になる：macOS 向けのローカルファースト AI オーケストレーター",
        gif="出荷版 Arslan クライアントの 4 画面 — オーケストレーションスレッド、スポーン台帳、セカンドブレイン、診断",
        screens="出荷版 Arslan クライアントの 4 画面 — オーケストレーションスレッド、スポーン台帳、セカンドブレイン、診断",
        film='<p align="center"><a href="docs/assets/arslan-clay-60s.mp4"><b>▶ 60 秒の映像を見る</b></a> — <a href="https://mirzatghayrat.github.io/arslan/">プロジェクトサイト</a>と同じクレイアニメーションの映像です。<br><sub>上の画面は出荷版クライアントそのもので、加工していません。</sub></p>',
    ),
    "README.es.md": dict(
        banner="Arslan — uno se vuelve muchos: un orquestador de IA local-first para macOS",
        gif="Cuatro pantallas del cliente publicado de Arslan — hilo de orquestación, registro de spawns, segundo cerebro, diagnóstico",
        screens="El cliente publicado de Arslan en cuatro pantallas — hilo de orquestación, registro de spawns, segundo cerebro, diagnóstico",
        film='<p align="center"><a href="docs/assets/arslan-clay-60s.mp4"><b>▶ Ver el film de 60 segundos</b></a> — el film en animación de plastilina del que sale el <a href="https://mirzatghayrat.github.io/arslan/">sitio del proyecto</a>. <br><sub>Las pantallas de arriba son el cliente publicado, sin retoques.</sub></p>',
    ),
    "README.tr.md": dict(
        banner="Arslan — birden çok olur: macOS için yerel öncelikli bir yapay zekâ orkestratörü",
        gif="Yayınlanan Arslan istemcisinden dört ekran — orkestrasyon dizisi, spawn defteri, ikinci beyin, tanılama",
        screens="Yayınlanan Arslan istemcisi dört ekranda — orkestrasyon dizisi, spawn defteri, ikinci beyin, tanılama",
        film='<p align="center"><a href="docs/assets/arslan-clay-60s.mp4"><b>▶ 60 saniyelik filmi izleyin</b></a> — <a href="https://mirzatghayrat.github.io/arslan/">proje sitesinin</a> kesildiği kil animasyon filminin ta kendisi. <br><sub>Yukarıdaki ekranlar yayınlanan istemcinin kendisi, rötuşsuz.</sub></p>',
    ),
}

ASSET_KEY = {"banner.jpg": "banner", "demo.gif": "gif", "screens.jpg": "screens"}

# The film line goes directly under the italic caption that follows the GIF.
CAPTION = re.compile(r'^(<p align="center"><em>.*</em></p>)$', re.M)

failed = False
for path, text in TEXT.items():
    src = open(path, encoding="utf-8").read()
    out = src

    for asset, key in ASSET_KEY.items():
        pattern = re.compile(
            r'(<img src="docs/assets/' + re.escape(asset) + r'" alt=")[^"]*(")'
        )
        out, n = pattern.subn(lambda m: m.group(1) + text[key] + m.group(2), out)
        if n != 1:
            print(f"{path}: expected 1 {asset} alt, replaced {n}", file=sys.stderr)
            failed = True

    if "arslan-clay-60s.mp4" not in out:
        out, n = CAPTION.subn(lambda m: m.group(1) + "\n\n" + text["film"], out, count=1)
        if n != 1:
            print(f"{path}: no caption to anchor the film line to", file=sys.stderr)
            failed = True

    if out != src:
        open(path, "w", encoding="utf-8").write(out)
        print(f"patched {path}")

sys.exit(1 if failed else 0)
