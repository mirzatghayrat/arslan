<div align="center">

<a href="https://mirzatghayrat.github.io/arslan/">
  <img src="docs/assets/banner.jpg" alt="Arslan — ein Orchestrator, gezeichnet wie eine Maschine, nicht wie eine Chat-Box" width="100%">
</a>

<br/><br/>

**Du sprichst mit einem Host-Agent. Er leitet die Arbeit an Persona-Spawns weiter, die du selbst großgezogen hast.**<br/>
**Ihre Prompts verbessern sich von ganz allein — doch jede Änderung muss ein Examen auf zurückgehaltenen Aufgaben bestehen,**<br/>
**und nichts geht live, bevor *du* auf Promote drückst.**

<br/>

[![License](https://img.shields.io/badge/license-Apache--2.0-4c72e0?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS--first-8a63f4?style=flat-square)](#status--ehrlich-was-bewiesen-ist)
[![Python](https://img.shields.io/badge/python-3.11%2B-e6863c?style=flat-square)](pyproject.toml)
[![Frontend](https://img.shields.io/badge/react-19_%2B_TS_%2B_Vite-ff9ffc?style=flat-square)](web/)
[![Status](https://img.shields.io/badge/status-pre--v1-orange?style=flat-square)](#status--ehrlich-was-bewiesen-ist)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-2ea44f?style=flat-square)](CONTRIBUTING.md)

<br/>

<a href="https://github.com/mirzatghayrat/arslan/releases/latest/download/Arslan-macos-arm64.dmg"><img src="docs/assets/icons/badge-check.svg" width="14" height="14"> <b>Für macOS laden</b></a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="https://mirzatghayrat.github.io/arslan/"><img src="docs/assets/icons/globe.svg" width="14" height="14"> <b>Website</b></a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="docs/QUICKSTART.md"><img src="docs/assets/icons/zap.svg" width="14" height="14"> <b>Quickstart</b></a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="docs/ARCHITECTURE.md"><img src="docs/assets/icons/layers.svg" width="14" height="14"> <b>Architektur</b></a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="SECURITY.md"><img src="docs/assets/icons/shield.svg" width="14" height="14"> <b>Security</b></a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="CONTRIBUTING.md"><img src="docs/assets/icons/heart-handshake.svg" width="14" height="14"> <b>Mitmachen</b></a>

<sub><img src="docs/assets/icons/languages.svg" width="12" height="12">&nbsp;&nbsp;<a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a> · <b>Deutsch</b> · <a href="README.ja.md">日本語</a> · <a href="README.es.md">Español</a> · <a href="README.tr.md">Türkçe</a></sub>

</div>

---

## Eine Anfrage, von Anfang bis Ende

<div align="center">
  <img src="docs/assets/demo.gif" alt="Arslan-Demo — eine Anfrage geroutet, gesandboxt und beantwortet, alles in einem einzigen Thread" width="90%">
</div>

<p align="center"><em>Du fragst einmal. Der Host-Agent wählt den passenden Spawn, zerlegt den Job, führt generierten Code in einer Kernel-Sandbox aus und antwortet — alles in einem einzigen Thread.</em></p>

**Arslan ist ein local-first Personal-AI-Orchestrator.** Er läuft auf deinem eigenen Rechner, mit deinen eigenen LLM-Keys, mit einer **standardmäßig sicheren Kernel-Sandbox**, **Ehrlichkeits-Guardrails** und einem **sichtbaren Second Brain**, das du durchstöbern und bearbeiten kannst.

## Warum Arslan

| | |
|---|---|
| <img src="docs/assets/icons/users.svg" width="20"><br/>**Ein Persona-Team, das du aufbaust** | Arslan ist die Eingangstür; dahinter baust du dir einen Kader spezialisierter Spawns (eigenständige Persona-Agenten) auf — rüste sie mit Tools, `SKILL.md`-Skill-Packs und MCP-Servern aus und lass dann eine zweistufige Evolutionsschleife sie über die Zeit verfeinern. |
| <img src="docs/assets/icons/graduation-cap.svg" width="20"><br/>**Selbstevolution mit Prüfungs-Gate** | Der Prompt eines Spawns überarbeitet sich selbst — aus der eigenen Run-Historie — und muss dann den Amtsinhaber auf zurückgehaltenen früheren Aufgaben schlagen, und zwar in *jeder* Dimension. Bestanden → ein lesbarer Diff landet in deiner Inbox. **Nichts wird wirksam, bevor du auf Promote (die manuelle Freigabe) drückst.** |
| <img src="docs/assets/icons/shield-check.svg" width="20"><br/>**Sicher per Default, nicht per Disclaimer** | Generierter Code läuft ohne Netzwerkzugriff in einer kernel-erzwungenen Sandbox (macOS Seatbelt). Ein Credential-injizierender Proxy lässt gesandboxtes Git mit dem Netz sprechen, während rohe Tokens die Sandbox nie betreten. Wo die Kernel-Sandbox nicht verfügbar ist, **schlägt sie geschlossen fehl** (fail closed). |
| <img src="docs/assets/icons/brain.svg" width="20"><br/>**Ein Second Brain mit Zeitachse** | Materialien, Learnings, ein Profil und `[[wiki-link]]`-Notizen — hybrides Retrieval aus FTS5 + Embeddings, erkundbar als kraftbasierter Graph im Obsidian-Stil. Überzeugungen tragen Zeit: wann jede wahr wurde, was sie abgelöst hat, und ein Filter, der den Graphen so zeigt, wie er zu jedem beliebigen vergangenen Zeitpunkt aussah. |
| <img src="docs/assets/icons/badge-check.svg" width="20"><br/>**Ehrlich by Design** | Guardrails fangen erfundene „Hab ich schon erledigt“-Behauptungen ab und halten die Selbstauskunft des Agents an das gebunden, was tatsächlich lief. Vom Modell vorgeschlagene Lösch- oder Überschreib-Operationen im Gedächtnis greifen nie direkt — sie landen in einer Inbox, die du annimmst oder verwirfst. |
| <img src="docs/assets/icons/key-round.svg" width="20"><br/>**Local-first, Bring Your Own Key** | Dein Rechner, deine API-Keys, qualitätsorientiertes Routing über mehrere Provider — und **null Drittanbieter-Server** dazwischen. Kommt mit i18n in 6 Sprachen und 6 Theme-Paletten (hell + dunkel). |

<sub>Backend: FastAPI + async SQLAlchemy/SQLite (`server/`) · Frontend: React 19 + TypeScript + Vite (`web/`) · Tracing, LLM-Judge-Evals und ein Diagnose-Dashboard im Grafana-Stil füttern die Evolutionsschleife.</sub>

## Ein Blick in den echten Client

<div align="center">
  <img src="docs/assets/screens.jpg" alt="Arslan-Client-Screens — Spawns-Register, Capability-Bibliothek, MCP-Server, Spezialisten-Channel" width="100%">
</div>

## Der Weg einer Anfrage

<div align="center">
  <img src="docs/assets/fig01-request-path.png" alt="FIG. 01 — Anfragepfad: ein Thread rein, der Host-Agent routet zu spezialisierten Spawns; darunter Kernel-Sandbox und Second Brain" width="100%">
</div>

## Kontrollierte Selbstevolution

<div align="center">
  <img src="docs/assets/fig02-promotion-gate.png" alt="FIG. 02 — Promotion-Gate: Rewrite, Examen auf zurückgehaltenen Aufgaben, Vorschlagskarte, du promotest; Durchfallen wird verworfen, Ablehnen behält den Amtsinhaber" width="100%">
</div>

Der Prompt eines Spawns wird automatisch überarbeitet — und muss sich dann erst auf zurückgehaltenen früheren Aufgaben beweisen, bevor du ihn überhaupt zu Gesicht bekommst. Keine Dimension darf schlechter abschneiden als der Amtsinhaber. Durchgefallen → verworfen, taucht nie auf. Bestanden → eine Vorschlagskarte mit lesbarem Diff; die Änderung greift **erst, wenn du auf Promote klickst**.

## Ein Second Brain mit Zeitachse

<div align="center">
  <img src="docs/assets/fig03-second-brain.png" alt="FIG. 03 — Second Brain: Gedächtnis bildet sich automatisch, Spawns lesen es per hybridem Retrieval, Modell-Edits laufen durch deine Inbox, und jede Überzeugung trägt Zeit" width="100%">
</div>

Das Gedächtnis bildet sich von selbst — vom Router extrahierte Fakten und Destillation am Session-Ende — und Spawns lesen es per hybridem FTS5-+-Embedding-Retrieval zurück. Jede Überzeugung hält fest, wann sie wirksam wurde und was sie abgelöst hat, sodass du den Graphen im Obsidian-Stil zu jedem vergangenen Zeitpunkt zurückspulen kannst. Will das Modell eine Erinnerung bearbeiten oder löschen, landet der Vorschlag zuerst in deiner Inbox — **nichts wird stillschweigend überschrieben**.

## Installation

**Die Desktop-App ist der Weg, Arslan zu benutzen** — signiert, notariell beglaubigt und hält sich selbst aktuell:

<p><a href="https://github.com/mirzatghayrat/arslan/releases/latest/download/Arslan-macos-arm64.dmg"><b>⬇ Arslan für macOS herunterladen</b></a> (Apple Silicon) — DMG öffnen und Arslan in den Ordner <b>Programme</b> ziehen.</p>

Beim ersten Start in den Einstellungen den API-Key deines Modells hinterlegen — fertig.

Aus dem Quellcode oder mit Docker (Beitragende / Self-Hosting): siehe **[docs/QUICKSTART.md](docs/QUICKSTART.md)**.

## Sicherheitsmodell

<div align="center">
  <img src="docs/assets/safety.jpg" alt="Sicherheit ist eingebaut, nicht wegdisclaimert — Kernel-Sandbox, Credential-injizierender Proxy, local-first BYOK" width="100%">
</div>

Arslan ist **standardmäßig sicher**:

- **Standardmäßig nur localhost.** Dev + localhost läuft absichtlich unauthentifiziert (lokaler Komfort). Cross-Site-Drive-by-Requests werden durch TrustedHost- + CORS- + WebSocket-Origin-Checks blockiert; Nicht-localhost-/Prod-Deployments müssen die untenstehenden Allowlists setzen.
- **Tokens dort, wo es zählt.** `prod`, paketierte Builds und Nicht-Loopback-Binds verlangen ein Bearer-Token — automatisch generiert, persistiert und aus den Einstellungen rotierbar, damit du dich nicht aussperren kannst.
- **Secrets verweigern den öffentlichen Key.** BYOK-Secrets werden Fernet-verschlüsselt mit einem PBKDF2-HMAC-SHA256-Key, abgeleitet aus `ARSLAN_SECRET_KEY` über ein installationsspezifisches Salt; die App weigert sich, Secrets unter dem eingebauten öffentlichen Dev-Key zu schreiben.
- **Die Sandbox schlägt geschlossen fehl.** Generierter Code läuft ohne Netzwerkzugriff unter dem macOS Seatbelt; wo die Kernel-Sandbox nicht verfügbar ist, schlägt sie geschlossen fehl, statt stillschweigend unsandboxt zu laufen.

**Exponiere den Server nicht ohne Token und Host-/Origin-Allowlists in ein nicht vertrauenswürdiges Netzwerk.** Vollständiges Threat-Model und Meldeprozess: [SECURITY.md](SECURITY.md).

<details>
<summary><b>Umgebungsvariablen (vollständige Referenz)</b></summary>
<br/>

| Env var | Default | Zweck |
| --- | --- | --- |
| `ARSLAN_SECRET_KEY` | *(in dev auto-generiert)* | Leitet den Fernet-Key ab, der gespeicherte BYOK-Secrets at rest verschlüsselt. Dev: nicht gesetzt → beim ersten Boot auto-generiert, nach `~/.arslan/secret_key` persistiert und danach wiederverwendet; ein expliziter Wert gewinnt immer (ein Mismatch gegenüber der persistierten Datei loggt eine Warnung). In `prod` ist ein fehlender Wert boot-fatal und die persistierte Dev-Datei wird **niemals** gelesen. |
| `ARSLAN_SECRET_KEY_FILE` | `~/.arslan/secret_key` | Nur dev: wohin das auto-generierte Secret persistiert wird — absichtlich **außerhalb** des Datenverzeichnisses (Backup = Datenverzeichnis **+** diese Datei). **Leer** setzen, um die Auto-Generierung komplett zu deaktivieren. In `prod` ignoriert. Jeder Dev-Einstiegspunkt, der die Server-Konfiguration lädt (Server, Migrations-CLI, Diagnostik), darf sie beim ersten Gebrauch anlegen; die Generierung gibt immer eine Zeile aus, die sagt wo. |
| `ARSLAN_API_TOKEN` | *(leer)* | API-/WS-Bearer-Token. **Leer in dev + localhost = keine Auth** (reibungslos lokal). Für prod / paketierte / Nicht-Loopback-Binds wird beim ersten Start ein Token auto-generiert (siehe unten). |
| `ARSLAN_DATA_DIR` | plattformspezifisches App-Data-Verzeichnis | Wo DB, Notizen und Secrets leben. Nicht gesetzt → macOS `~/Library/Application Support/Arslan`, Linux `~/.local/share/Arslan`, Windows `%APPDATA%/Arslan`. **Dieses Verzeichnis plus dein Secret sind die Backup-Einheit** (siehe [Daten & Backup](#daten--backup)). |
| `ARSLAN_ENV` | `dev` | `dev` oder `prod`. `prod` verlangt ein Token und härtet die Defaults; ein fehlender `ARSLAN_SECRET_KEY` in `prod` ist boot-fatal. |
| `ARSLAN_ALLOWED_HOSTS` | nur localhost | Kommagetrennte TrustedHost-Allowlist für Nicht-localhost-/Prod-Deployments. |
| `ARSLAN_ALLOWED_ORIGINS` | nur localhost | Kommagetrennte CORS- + WebSocket-Origin-Allowlist für Nicht-localhost-/Prod-Deployments. |
| `ARSLAN_ALLOW_INSECURE_SECRETS` | *(aus)* | Nur-dev-Notausgang: erlaubt das Schreiben von Secrets unter dem öffentlichen Default-Key. **Niemals für echte Keys verwenden.** |
| `ARSLAN_ALLOW_UNSANDBOXED_PY` | *(aus)* | Nur-dev-Notausgang: lässt generiertes Python **ohne** Sandbox laufen, wo keine verfügbar ist. Beliebiger Code läuft dann mit den Rechten und dem Netzwerkzugriff des Servers; Runs werden fürs Audit als `sandboxed=false` markiert. Nur auf einer Maschine aktivieren, der du voll vertraust. |

Für prod / paketiert (`ARSLAN_PACKAGED=1`) / Nicht-Loopback-Binds gilt: Ist `ARSLAN_API_TOKEN` leer, **auto-generiert** die App beim ersten Start ein Token, persistiert es nach `<data_dir>/api_token` (nur für den Owner lesbar), gibt es einmalig beim Boot aus und lässt dich es in den Einstellungen ansehen/zurücksetzen.

</details>

<details>
<summary><b>Daten &amp; Backup</b></summary>
<br/>

Alles, was zählt, lebt in einem Verzeichnis — die DB, deine Notizen und deine verschlüsselten Secrets — aufgelöst aus `ARSLAN_DATA_DIR` (oder dem plattformspezifischen App-Data-Verzeichnis, wenn nicht gesetzt). **Dieses Verzeichnis IST die Backup-Einheit:** kopiere es, um Arslan zu sichern, und stelle wieder her, indem du es zurückkopierst. Lass seine Dateien `api_token` und `crypto_salt` dabei — Secrets im neuen Schema (PBKDF2) werden aus `ARSLAN_SECRET_KEY` **und** dem installationsspezifischen `crypto_salt` abgeleitet, sodass ein verlorenes (oder abweichendes) `crypto_salt` diese gespeicherten Secrets selbst mit dem richtigen `ARSLAN_SECRET_KEY` unentschlüsselbar macht.

Eine bewusste Ausnahme: Das Secret selbst lebt **außerhalb** dieses Verzeichnisses. Wenn du `ARSLAN_SECRET_KEY` nie selbst gesetzt hast, liegt der in dev auto-generierte Wert unter `~/.arslan/secret_key` — ein kopiertes Datenverzeichnis allein kann deine gespeicherten Provider-Keys also nicht entschlüsseln (Schloss und Kiste reisen getrennt). Ein vollständiges Backup besteht daher aus **zwei Teilen**: dem Datenverzeichnis **und** dem Secret (dein Env-Wert oder diese Datei).

</details>

## Status — ehrlich, was bewiesen ist

**Pre-v1.** Wir untertreiben lieber, als zu viel zu versprechen:

- **macOS-first.** Die Kernel-Sandbox gibt es nur als macOS Seatbelt; auf anderen Plattformen schlägt sie geschlossen fehl (Linux / Windows folgen später über eine Tauri-Desktop-App).
- **Das selbstevolvierende Agenten-Team wird gerade gehärtet.** Die zweistufige Evolutionsschleife funktioniert, gilt aber noch nicht als voll bewiesen — betrachte sie als reifend, nicht als fertig.
- **Agentisches Gedächtnis-Lesen/-Schreiben braucht einen Provider mit nativem Tool-Calling.** Die Tools `recall`/`remember` feuern nur bei Providern, die tatsächlich Tool-Calling können (z. B. DeepSeek). Über ein direktes Anthropic-Backend werden sie nie ausgelöst — dieser Pfad ist absichtlich Text-rein/Text-raus, das Tool-Schema wird dem Modell also nie gesendet. Das Gedächtnis bildet sich so oder so automatisch (vom Router extrahierte Fakten + Destillation am Session-Ende), unabhängig von diesem Feature.
- **Die beiden Hintergrundschleifen, die Geld ausgeben, sind ab Werk deaktiviert.** Auto-Evolution und Sleep-Time-Kuratierung rufen das LLM jeweils nach eigenem Zeitplan auf, deshalb sind beide per Default aus — du schaltest sie in den Einstellungen ein. Ein funktionierendes Ausgabenlimit gibt es noch nicht: Die Vorab-Schätzung ist eine bekannte Überschätzung, die mit deinem Korpus wächst, es wird also nichts dagegen durchgesetzt. Bis das behoben ist, begrenze deine Ausgaben mit einem harten Limit im Billing-Dashboard deines Providers.
- APIs, Schemas und Defaults können sich vor v1 noch ändern.

## Community

- <img src="docs/assets/icons/bug.svg" width="14" height="14"> Bug gefunden oder eine Idee? [Eröffne ein Issue](https://github.com/mirzatghayrat/arslan/issues).
- <img src="docs/assets/icons/heart-handshake.svg" width="14" height="14"> Lust mitzuhelfen? Starte mit [CONTRIBUTING.md](CONTRIBUTING.md).
- <img src="docs/assets/icons/globe.svg" width="14" height="14"> Die Projektseite lebt in [`docs/index.html`](docs/index.html) (ausgeliefert über GitHub Pages). Die Blueprint-Abbildungen in diesem README sind handgezeichnete SVGs — Quellen in [`docs/diagrams/`](docs/diagrams/).

## Lizenz

Apache-2.0. Siehe [LICENSE](LICENSE) und [NOTICE](NOTICE). Hinweise zu Drittanbieter-Abhängigkeiten stehen in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Icons: [Lucide](https://lucide.dev) (ISC).

---

<div align="center">
<sub>Wenn Arslan bei dir einen Nerv trifft, <a href="https://github.com/mirzatghayrat/arslan/stargazers">hilft ein <img src="docs/assets/icons/star.svg" width="12" height="12"> anderen, es zu finden</a>.</sub>
</div>
