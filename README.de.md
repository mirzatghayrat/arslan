<div align="center">

<a href="https://aralem.dev/arslan/">
  <img src="docs/assets/readme/banner.jpg" alt="Arslan — erledigt die Arbeit, fragt vor dem Handeln. Die Arslan Island in der Notch des Mac wartet auf die Freigabe, Dateien zu verschieben." width="100%">
</a>

<br/><br/>

**Ein Open-Source-KI-Agent, der auf deinem Mac lebt — und auf dein iPhone hört.**<br/>
**Er nutzt dein Terminal und deine Apps und arbeitet weiter, während du redest.**<br/>
**Alles, was in deinem Namen handelt, wartet auf *deinen* Klick.**

<br/>

[![Release](https://img.shields.io/github/v/release/mirzatghayrat/arslan?style=flat-square&color=34d399&label=release)](https://github.com/mirzatghayrat/arslan/releases/latest)
[![License](https://img.shields.io/badge/license-Apache--2.0-4c72e0?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/macOS_11+-Apple_Silicon-111?style=flat-square)](README.md#status--honest-about-whats-proven)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-2ea44f?style=flat-square)](CONTRIBUTING.md)

<br/>

<a href="https://github.com/mirzatghayrat/arslan/releases/latest/download/Arslan-macos-arm64.dmg"><img src="docs/assets/btn/de-download.png" alt="Für macOS laden" height="28"></a>&nbsp;&nbsp;<a href="https://aralem.dev/arslan/"><img src="docs/assets/btn/de-website.png" alt="Website" height="28"></a>&nbsp;&nbsp;<a href="docs/QUICKSTART.md"><img src="docs/assets/btn/de-quickstart.png" alt="Schnellstart" height="28"></a>&nbsp;&nbsp;<a href="SECURITY.md"><img src="docs/assets/btn/de-security.png" alt="Sicherheit" height="28"></a>&nbsp;&nbsp;<a href="CONTRIBUTING.md"><img src="docs/assets/btn/de-contributing.png" alt="Mitmachen" height="28"></a>

<a href="README.md"><a href="https://aralem.dev/arslan/docs/"><b>📖 Technische Dokumentation</b></a> <sub>(Englisch · Chinesisch)</sub>

<img src="docs/assets/btn/lang-en.png" alt="English" height="22"></a>&nbsp;<a href="README.zh-CN.md"><img src="docs/assets/btn/lang-zh.png" alt="简体中文" height="22"></a>&nbsp;<img src="docs/assets/btn/lang-de-on.png" alt="Deutsch" height="22">&nbsp;<a href="README.ja.md"><img src="docs/assets/btn/lang-ja.png" alt="日本語" height="22"></a>&nbsp;<a href="README.es.md"><img src="docs/assets/btn/lang-es.png" alt="Español" height="22"></a>&nbsp;<a href="README.tr.md"><img src="docs/assets/btn/lang-tr.png" alt="Türkçe" height="22"></a>

</div>

---

<div align="center">
  <img src="docs/assets/readme/island.gif" alt="Arslan — erledigt die Arbeit, fragt vor dem Handeln. Die Arslan Island in der Notch des Mac wartet auf die Freigabe, Dateien zu verschieben." width="760">
  <br/>
  <sub>Ein Hintergrundauftrag, live in der Notch: er arbeitet, <b>hält an und fragt</b>, bevor er deine Dateien verschiebt, und sagt dir dann, was er gefunden hat.</sub>
</div>

## Frag ihn zum Beispiel

> *“Sammle die Rechnungen dieses Jahres aus Downloads in einem Ordner und sag mir, welche Monate fehlen.”*<br/>
> *“Wie viele doppelte Dateien liegen in Downloads? Schieb die Kopien in den Papierkorb, behalte die neueste.”*<br/>
> *“Mach aus sales_q3.csv einen einseitigen Bericht mit Diagramm.”*<br/>
> *“Leg in Notizen eine Notiz mit den drei Punkten aus diesem Meeting an.”*<br/>
> *“Schau jeden Morgen um 9 auf diese Seite und sag mir, ob sich der Preis geändert hat.”*

Du redest weiter, während er arbeitet. Alles, was löscht, sendet, installiert oder eine andere App bedient, **fragt dich zuerst** — auf dem Mac oder dem iPhone.

## In einer Minute startklar

1. **[Arslan für macOS laden](https://github.com/mirzatghayrat/arslan/releases/latest/download/Arslan-macos-arm64.dmg)** (Apple Silicon, macOS 11+) — signiert, notarisiert, aktualisiert sich selbst.
2. In **Programme** ziehen und öffnen.
3. In den Einstellungen einen Modell-API-Schlüssel einfügen — OpenAI, Anthropic, Gemini, DeepSeek, Qwen, Kimi, OpenRouter und mehr — oder ein lokales Modell über **Ollama** anbinden.

Das war's. Kein Konto, keine Anmeldung, kein Arslan-Server.

## Neu in 0.1.63 — mitten in der Antwort umlenken, Antworten beim Schreiben, einen Zug rückgängig machen

Tippe eine Nachricht, während Arslan arbeitet, und sie erreicht die Antwort bei ihrem nächsten Schritt; Antworten erscheinen, während das Modell sie schreibt; bis zu vier Lesevorgänge laufen gleichzeitig; und bevor ein Zug deinen Arbeitsordner erstmals ändert, sichert Arslan einen Checkpoint, sodass „Diesen Zug rückgängig machen“ die Dateien zurückspielt. Dateien, um die du bittest, kommen als Anhänge zurück, auch auf dem iPhone. Zwei Sicherheitsänderungen vorweg: **Jeder neue Terminalbefehl fragt jetzt, bevor er läuft** (zurückstellen unter Einstellungen › Was Arslan darf › Terminal), und **geplante Aufgaben führen in dieser Version keine Befehle aus** — ein Schritt, der einen braucht, wird übersprungen und in deinem Posteingang aufgeführt. Jede Antwort und jede Hintergrundaufgabe hält außerdem standardmäßig bei 2 $ Modellausgaben an, und der Code aus der Expertenzeit ist weg (12.514 Produktzeilen weniger als in 0.1.62). Die Notes nennen auch, was auf 0.1.64 verschoben wurde, und zwei Hürden vor dem Release, die wir verfehlt haben. [Alle Release Notes →](https://github.com/mirzatghayrat/arslan/releases/tag/v0.1.63)

Zuletzt:
- **[0.1.62](https://github.com/mirzatghayrat/arslan/releases/tag/v0.1.62)** — lange Befehle werden fertig: Ein Befehl läuft bis zu seinem eigenen Limit (standardmäßig 2 Minuten, höchstens 10), „braucht deine Prüfung“ nur, wenn wirklich etwas passiert sein könnte, MCP-Werkzeugbeschreibungen können keinen Chat mehr brechen, und das Schreiben einer Datei folgt nie einem Link aus deinem Arbeitsordner hinaus.
- **[0.1.61](https://github.com/mirzatghayrat/arslan/releases/tag/v0.1.61)** — eine Freigabekarte überall (Chat, Posteingang, Island, iPhone), MCP-Server, die sich selbst starten, und Claude funktioniert wieder nach einer abgelehnten `temperature`-Einstellung.

<div align="center">
  <img src="docs/assets/readme/devices.jpg" alt="Arslan auf dem Mac — ein Hintergrundauftrag sammelt Rechnungen — und Arslan für iPhone mit einer wartenden Freigabe" width="100%">
</div>

<p align="center"><sub>Mac: aus dem Launch-Film zu 0.1.52, Oberfläche aus dem Quellcode nachgebaut, Szene inszeniert. iPhone: eine echte Bildschirmaufnahme. <a href="https://aralem.dev/arslan/#film">▶ Das ganze System in 60 Sekunden</a></sub></p>

## Warum Arslan

| | |
|---|---|
| **Eine Schleife, jede Aktion hinter einem Tor** | Eine Nachricht betritt eine native Tool-Calling-Schleife. Das Modell schlägt vor; eine feste Policy-Funktion — kein weiteres Modell — antwortet vor jedem Shell-Befehl mit **run**, **ask** oder **forbid**. Ergebnisse kommen als nicht vertrauenswürdige Daten zurück: Anweisungen, die in einer Webseite stecken, werden gelesen, nicht befolgt. |
| **Er arbeitet weiter, während du redest** | Lange Arbeit wird zum Hintergrundauftrag, und der Zug endet. Ein Auftrag endet **done**, **partial**, **blocked** oder **stopped** — nie stillschweigend. Zeitpläne laufen höchstens alle 15 Minuten (bis zu 10), und was dein Mac verschlafen hat, wird nicht nachgeholt. |
| **Status in der Notch** | Die **Arslan Island** zeigt, was gerade passiert, fragt, wenn sie dich braucht, und meldet, wenn es fertig ist. Menüleiste, Push-to-talk und ein Stopp-Knopf für alles, was läuft. |
| **Hände — gefragt, nicht angenommen** | Mac-Apps über Arslan Hands, Arslans eigener Browser, deine Kurzbefehle, AppleScript. Er tippt nie in ein Passwortfeld und rührt Schlüsselbundverwaltung, Passwortmanager, Systemeinstellungen, Sicherheitsabfragen von macOS, die Mitteilungszentrale und sich selbst nie an. |
| **Dein Mac in der Hosentasche** | Arslan für iPhone (bald im App Store) spricht mit deinem Mac über **deine eigene private iCloud**, Ende-zu-Ende-verschlüsselt. Dieselbe Freigabekarte erscheint auf beiden; die erste Antwort gilt. Eine unbeantwortete Karte wartet 30 Minuten, und dass die Zeit abläuft, ist kein Nein (seit 0.1.61; frühere Versionen lehnten sie nach 300 s ab). |
| **Local-first, eigener Schlüssel** | Das Gedächtnis liegt in SQLite auf deinem Mac; dein Modellanbieter sieht nur die Züge, die du sendest, mit deinem Schlüssel. **Arslan betreibt keine Server.** Korrigiere ihn einmal, und er merkt sich die Vorgehensweise — mit Rückgängig. |
| <img src="docs/assets/icons/shield-check.svg" width="16"> **Zugangsdaten bleiben deine** | Arslan holt oder injiziert nie deine Kontodaten. Authentifizierte Connectoren (etwa App Store Connect) bleiben deaktiviert, bis ein isolierter Credential-Broker die Sicherheitsprüfung besteht — siehe [W11](docs/companion/W11-security-boundary.md). Ein Befehl, den du außerhalb der Sandbox freigibst, läuft mit deinen eigenen Rechten. |

## Ein Zug, von Anfang bis Ende

<div align="center">
  <img src="docs/assets/readme/loop.jpg" alt="Die Schleife: Nachricht, Schleife, Policy, Sandbox, Ergebnis — jeder Schritt nennt die Datei, die ihn durchsetzt" width="100%">
</div>

| Schritt | Was passiert | Durchgesetzt in |
|---|---|---|
| **Nachricht** | Aus dem Fenster, vom iPhone oder per Stimme — eine Unterhaltung, eine Schleife | `server/orchestrator/arslan.py`, `server/services/phone_bridge.py` |
| **Schleife** | Native Tool-Calls; der Plan liegt beim Host; eine abgeschnittene Antwort wird fortgesetzt statt erraten; 75 s pro Modellaufruf | `server/orchestrator/tool_loop.py` |
| **Policy** | `run` · `ask` · `forbid`, eine reine Funktion des Befehlstexts | `server/services/terminal_policy.py` (Befehlserkennung und harte Untergrenze angepasst aus Hermes Agent, MIT) |
| **Sandbox** | macOS-Seatbelt: Befehle schreiben nur in den Arbeitsordner, Temp und Caches; SSH-Schlüssel, Schlüsselbund und Arslans Daten bleiben zu; Modellschlüssel erreichen nie einen Befehl; ein Befehl läuft bis zu seinem eigenen Limit, standardmäßig 2 Min., höchstens 10 | `server/services/command_sandbox.py`, `terminal_exec.py` |
| **Ergebnis** | Als nicht vertrauenswürdig verpackt und geprüft, bevor es dich erreicht; Behauptungen über nie erledigte Arbeit fängt ein deterministischer Wächter ab | `server/orchestrator/untrusted.py`, `promise_guard.py` |

## Das Tor

<div align="center">
  <img src="docs/assets/readme/gate.jpg" alt="Das Tor auf der Projektseite: einen Befehl eingeben und Arslans echte Antwort sehen — forbid für das Auslesen von Schlüsselbund-Passwörtern" width="100%">
</div>

| Antwort | Wann | Beispiele (jeweils die echte Antwort von `terminal_policy.assess()`) |
|---|---|---|
| **run** | Lesen, Auflisten, Konvertieren, Bauen, eine Seite abrufen | `ls -la ~/Downloads` · `ffmpeg -i talk.mov talk.mp4` · `npm run build` · `curl -s https://example.com` |
| **ask** | Destruktiv oder nach außen in deinem Namen | `rm -rf build/` · `git push --force` · `curl … \| sh` · `osascript …` · `brew install jq` · `mail -s …` · `scp … mac-mini:` |
| **forbid** | Nie, auch nicht mit „nicht mehr fragen“ | `security find-generic-password … -w` · `cat ~/.arslan/secret_key` · `rm -rf ~` · `sudo …` · `shutdown` |

„Nicht mehr fragen“ wird pro Befehlsart gemerkt und unter Einstellungen › Erweitert aufgelistet; forbid-Regeln lassen sich nie merken. Das Tor schützt vor Fehlern und eingeschmuggelten Anweisungen — es ist kein Käfig: ein freigegebener Befehl läuft mit deinen Rechten. Seit 0.1.63 fragt ein neuer Befehl standardmäßig zuerst, was auch immer seine Zeile oben sagt. Probiere 64 Befehle auf der [Projektseite](https://aralem.dev/arslan/#gate).

## Hände, Hintergrundarbeit und das iPhone

<div align="center">
  <img src="docs/assets/readme/hands.jpg" alt="Hände: Mac-Apps über Arslan Hands, Browser, Kurzbefehle und AppleScript; sichtbar und stoppbar; Apps, die nie berührt werden" width="100%">
</div>

<div align="center">
  <img src="docs/assets/readme/iphone.jpg" alt="Mac und iPhone: Ende-zu-Ende-Verschlüsselung über deine private iCloud (X25519, HKDF-SHA256, ChaCha20-Poly1305, Ed25519), die erste Antwort gilt, das Gesicht der Island" width="100%">
</div>

Die iPhone-Verbindung hat keinen Arslan-Server und kein Relay: Nachrichten laufen durch eine CloudKit-Zone in deiner privaten iCloud-Datenbank — X25519-Schlüsselvereinbarung, HKDF-SHA256, ChaCha20-Poly1305, Ed25519-Signaturen. Zugestellte Nachrichten werden gelöscht; was liegen bleibt, löscht Arslan für Mac, sobald es älter als 7 Tage ist — der Mac prüft etwa einmal täglich, solange er läuft und online ist, sonst später.

## Datenschutz

<div align="center">
  <img src="docs/assets/readme/privacy.jpg" alt="Wer sieht was: dieser Mac alles, dein Modellanbieter die gesendeten Züge, iCloud Chiffretext und Routing, Arslans Server nichts — weil es keine gibt" width="100%">
</div>

## Installation

Aus dem Quellcode (Mitwirkende): siehe **[docs/QUICKSTART.md](docs/QUICKSTART.md)**.

Texterkennung in Bildern und gescannten PDFs, die vollständige Sicherheitslage, Umgebungsvariablen und Datensicherung: siehe [englisches README](README.md#install) (maßgeblich ist die englische Fassung).

## Status — ehrlich über das Bewiesene

- **Pre-v1.** Vorerst nur macOS 11+ auf Apple Silicon. Die Sandboxen sind macOS-Seatbelt; anderswo wird generiertes Python verweigert, Shell-Befehle laufen ohne Sandbox und sind entsprechend markiert.
- **Eigener Modellschlüssel.** Arslan läuft über dein Konto; dein Anbieter rechnet ab. Nativer Tool-Transport ist für OpenAI-kompatible, Anthropic- und Gemini-Pfade implementiert und protokollgetestet — das ist keine Live-Zertifizierung jedes Modells oder Endpunkts.
- **Hands kann noch nicht an eine Bildschirmposition klicken oder ziehen.** Ein Fenster auf einem anderen Schreibtisch erreicht es, indem es kurz dorthin geht (solange das Ausleihen des Vordergrunds an ist). Eine Taste, die in den ~50 ms gedrückt wird, in denen eine App nach vorn springt, landet in dieser App, und ein großes Fenster (Notizen mit vielen Notizen) braucht zum Lesen 10–20 Sekunden.
- **Arslan für iPhone kommt bald in den App Store.** Die Mac-Seite ist in 0.1.53 enthalten.
- **Ausgaben haben ein Standardlimit, keine Garantie.** Jede Antwort und jede Hintergrundaufgabe hält bei 2 $ Modellausgaben an (Einstellungen › Hintergrund); es zählen nur Modelle mit bekanntem Preis. Setze trotzdem ein hartes Limit im Abrechnungsbereich deines Anbieters.
- **Standardmäßig fragt jeder neue Befehl zuerst, und geplante Aufgaben führen keine Befehle aus** (0.1.63).
- APIs, Schemata und Voreinstellungen können sich vor v1 ändern.

## Community

- Einen Fehler gefunden oder eine Idee? [Issue eröffnen](https://github.com/mirzatghayrat/arslan/issues).
- Helfen? Fang mit [CONTRIBUTING.md](CONTRIBUTING.md) an.
- Die Projektseite liegt in [`docs/index.html`](docs/index.html) (GitHub Pages). Die Bilder in diesem README sind Aufnahmen dieser Seite.

## Lizenz

Apache-2.0. Siehe [LICENSE](LICENSE) und [NOTICE](NOTICE). Hinweise zu Drittanbietern — darunter Hermes Agent (MIT) und agent-desktop (Apache-2.0, in Arslan Hands aus einem Fork gebaut, der eine Änderung von Arslan enthält) — stehen in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Symbole: [Lucide](https://lucide.dev) (ISC).

---

<div align="center">
<sub>Wenn Arslan dich anspricht, <a href="https://github.com/mirzatghayrat/arslan/stargazers">hilft ein <img src="docs/assets/icons/star.svg" width="12" height="12"> anderen, es zu finden</a>.</sub>
</div>
