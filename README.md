<div align="center">

<a href="https://mirzatghayrat.github.io/arslan/">
  <img src="docs/assets/banner.jpg" alt="Arslan — one becomes many: a local-first personal AI orchestrator for macOS" width="100%">
</a>

<br/><br/>

**You talk to one host agent. It routes work to persona spawns you raised yourself.**<br/>
**Their prompts improve on their own — but every change passes a held-out exam,**<br/>
**and nothing ships until *you* press Promote.**

<br/>

[![License](https://img.shields.io/badge/license-Apache--2.0-4c72e0?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS--first-8a63f4?style=flat-square)](#status--honest-about-whats-proven)
[![Python](https://img.shields.io/badge/python-3.11%2B-e6863c?style=flat-square)](pyproject.toml)
[![Frontend](https://img.shields.io/badge/react-19_%2B_TS_%2B_Vite-ff9ffc?style=flat-square)](web/)
[![Status](https://img.shields.io/badge/status-pre--v1-orange?style=flat-square)](#status--honest-about-whats-proven)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-2ea44f?style=flat-square)](CONTRIBUTING.md)

<br/>

<a href="https://github.com/mirzatghayrat/arslan/releases/latest/download/Arslan-macos-arm64.dmg"><img src="docs/assets/icons/badge-check.svg" width="14" height="14"> <b>Download for macOS</b></a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="https://mirzatghayrat.github.io/arslan/"><img src="docs/assets/icons/globe.svg" width="14" height="14"> <b>Website</b></a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="docs/QUICKSTART.md"><img src="docs/assets/icons/zap.svg" width="14" height="14"> <b>Quickstart</b></a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="docs/ARCHITECTURE.md"><img src="docs/assets/icons/layers.svg" width="14" height="14"> <b>Architecture</b></a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="SECURITY.md"><img src="docs/assets/icons/shield.svg" width="14" height="14"> <b>Security</b></a>&nbsp;&nbsp;·&nbsp;&nbsp;<a href="CONTRIBUTING.md"><img src="docs/assets/icons/heart-handshake.svg" width="14" height="14"> <b>Contributing</b></a>

<sub><img src="docs/assets/icons/languages.svg" width="12" height="12">&nbsp;&nbsp;<b>English</b> · <a href="README.zh-CN.md">简体中文</a> · <a href="README.de.md">Deutsch</a> · <a href="README.ja.md">日本語</a> · <a href="README.es.md">Español</a> · <a href="README.tr.md">Türkçe</a></sub>

</div>

---

## One request, end to end

<div align="center">
  <img src="docs/assets/demo.gif" alt="Four screens of the shipped Arslan client — orchestration thread, spawns ledger, second brain, diagnostics" width="90%">
</div>

<p align="center"><em>You ask once. The host agent picks the spawn, splits the job, runs generated code in a kernel sandbox, and answers — all in one thread.</em></p>

<p align="center"><a href="docs/assets/arslan-clay-60s.mp4"><b>▶ Watch the 60-second film</b></a> — the clay-animated film the <a href="https://mirzatghayrat.github.io/arslan/">project site</a> is cut from. <br><sub>The screens above are the shipped client, unretouched.</sub></p>

**Arslan is a local-first personal AI orchestrator.** It runs on your own machine, against your own LLM keys, with a **safe-by-default kernel sandbox**, **honesty guardrails**, and a **visible second brain** you can browse and edit.

## Why Arslan

| | |
|---|---|
| <img src="docs/assets/icons/users.svg" width="20"><br/>**A persona team you grow** | Arslan is the front door; behind it you build a roster of specialist spawns — equip them with tools, `SKILL.md` skill packs, and MCP servers, then let a two-tier evolution loop refine them over time. |
| <img src="docs/assets/icons/graduation-cap.svg" width="20"><br/>**Self-evolution with an exam gate** | A spawn's prompt revises itself from its own run history — then must beat the incumbent on held-out past tasks, on *every* dimension. Pass → a readable diff lands in your inbox. **Nothing takes effect until you press Promote.** |
| <img src="docs/assets/icons/shield-check.svg" width="20"><br/>**Safe by default, not disclaimed** | Generated code runs network-denied under a kernel-enforced sandbox (macOS seatbelt). A credential-injecting proxy lets sandboxed git talk to the network while raw tokens never enter the sandbox. Where the kernel sandbox is unavailable, it **fails closed**. |
| <img src="docs/assets/icons/brain.svg" width="20"><br/>**A second brain with a time axis** | Materials, learnings, a profile, and `[[wiki-link]]` notes — hybrid FTS5 + embedding retrieval, browsable as an Obsidian-style force-directed graph. Beliefs carry time: when each became true, what superseded it, and a filter that shows the graph as it stood at any past instant. |
| <img src="docs/assets/icons/badge-check.svg" width="20"><br/>**Honest by design** | Guardrails intercept fabricated "I already did that" claims and keep the agent's self-reporting tied to what actually ran. Memory deletes/overwrites the model proposes never apply directly — they land in an inbox you accept or dismiss. |
| <img src="docs/assets/icons/key-round.svg" width="20"><br/>**Local-first, bring your own key** | Your machine, your API keys, quality-first routing across multiple providers — and **zero third-party servers** in the middle. Ships with 6-language i18n and 6 theme palettes (light + dark). |

<sub>Backend: FastAPI + async SQLAlchemy/SQLite (`server/`) · Frontend: React 19 + TypeScript + Vite (`web/`) · Tracing, LLM-judge evals, and a Grafana-style diagnosis dashboard feed the evolution loop.</sub>

## Inside the actual client

<div align="center">
  <img src="docs/assets/screens.jpg" alt="The shipped Arslan client in four screens — orchestration thread, spawns ledger, second brain, diagnostics" width="100%">
</div>

## How a request flows

<div align="center">
  <img src="docs/assets/fig01-request-path.png" alt="FIG. 01 — Request path: one thread in, the host agent routes to specialist spawns; kernel sandbox and second brain underneath" width="100%">
</div>

## Governed self-evolution

<div align="center">
  <img src="docs/assets/fig02-promotion-gate.png" alt="FIG. 02 — Promotion gate: rewrite, held-out exam, proposal card, you promote; fail is discarded, reject keeps the incumbent" width="100%">
</div>

A spawn's prompt gets revised automatically — then it has to prove itself on held-out past tasks before you ever see it. No dimension is allowed to score worse than the incumbent. Fail → discarded, never surfaces. Pass → a proposal card with a readable diff; the change lands **only when you click Promote**.

## A second brain with a time axis

<div align="center">
  <img src="docs/assets/fig03-second-brain.png" alt="FIG. 03 — Second brain: memory forms automatically, spawns read it via hybrid retrieval, model edits pass through your inbox, and every belief carries time" width="100%">
</div>

Memory forms on its own — router-extracted facts and end-of-session distillation — and spawns read it back with hybrid FTS5 + embedding retrieval. Every belief records when it took effect and what superseded it, so you can scrub the Obsidian-style graph to any past instant. When the model wants to edit or delete a memory, the proposal lands in your inbox first — **nothing is overwritten silently**.

## Install

**The desktop app is the way to use Arslan** — signed, notarized, and it keeps itself up to date:

<p><a href="https://github.com/mirzatghayrat/arslan/releases/latest/download/Arslan-macos-arm64.dmg"><b>⬇ Download Arslan for macOS</b></a> (Apple Silicon) — open the DMG and drag Arslan into <b>Applications</b>.</p>

On first run, add your model API key in Settings and you're set.

Running from source or with Docker (contributors & self-hosters): see **[docs/QUICKSTART.md](docs/QUICKSTART.md)**.

### Reading text in images and scanned PDFs

A model with vision reads your pictures directly. When the model you configured
cannot — many cheaper models cannot — Arslan falls back to the operating
system's own text recognition. What that gives you depends on the platform, so
here it is per platform rather than as a blanket "supports OCR":

| Platform | Text in images / scanned PDFs | What it needs |
|---|---|---|
| **macOS** (the `.dmg`) | ✅ Works out of the box | **Nothing.** It uses macOS's built-in Vision framework — no download, no Homebrew, nothing borrowed from your machine |
| **Windows** | Planned — the intent is the same capability through the OS | — |
| **Linux** (from source) | ❌ Not available by default | Install `tesseract` yourself and the optional `ocr` extra |

Two honest caveats:

- **Text is read in your interface language (plus English).** This is a real
  limitation, not a default: system text recognition only finds what it is
  asked to look for, and asking for more makes it *worse* — measured, widening
  the request from Chinese+English to all thirty supported languages loses the
  Chinese text entirely. So if your interface is in English and you feed a
  Chinese screenshot, the writing is not read, and Arslan tells you which
  language it looked for rather than claiming the image was blank. Switch the
  interface language to read that image.
- **The available languages are whatever your macOS recognises**, and that set
  grows with the OS version — Arslan asks the system at runtime instead of
  promising a list. If your language is not among them, Arslan says so and
  reads nothing, rather than returning plausible-looking nonsense. **Uyghur is
  not supported by macOS text recognition**; we verified that asking anyway
  produces convincing gibberish, which is why Arslan refuses instead.
- Verified on macOS 26. **On macOS 11 and 12 the recognised-language set is
  smaller and has not been tested by us**; the runtime check means you will be
  told, not silently given wrong text.

## Security posture

<div align="center">
  <img src="docs/assets/safety.jpg" alt="Safety is built in, not disclaimed — kernel sandbox, credential-injecting proxy, local-first BYOK" width="100%">
</div>

Arslan is **safe by default**:

- **Localhost-only by default.** Dev + localhost runs unauthenticated on purpose (local convenience). Cross-site drive-by requests are blocked by TrustedHost + CORS + WebSocket-Origin checks; non-localhost / prod deploys must set the allowlists below.
- **Tokens where they matter.** `prod`, packaged builds, and non-loopback binds require a bearer token — auto-generated, persisted, and rotatable from Settings so you can't lock yourself out.
- **Secrets refuse the public key.** BYOK secrets are Fernet-encrypted with a PBKDF2-HMAC-SHA256 key derived from `ARSLAN_SECRET_KEY` over a per-install salt; the app refuses to write secrets under the built-in public dev key.
- **Sandbox fails closed.** Generated code runs network-denied under the macOS seatbelt; where the kernel sandbox is unavailable it fails closed rather than silently running unsandboxed.

**Do not expose the server to an untrusted network without a token and host/origin allowlists.** Full threat model and reporting policy: [SECURITY.md](SECURITY.md).

<details>
<summary><b>Environment variables (full reference)</b></summary>
<br/>

| Env var | Default | Purpose |
| --- | --- | --- |
| `ARSLAN_SECRET_KEY` | *(auto-generated in dev)* | Derives the Fernet key that encrypts stored BYOK secrets at rest. Dev: unset → auto-generated on the first boot, persisted to `~/.arslan/secret_key`, and reused thereafter; an explicit value always wins (a mismatch vs the persisted file logs a warning). In `prod` a missing value is boot-fatal and the persisted dev file is **never** read. |
| `ARSLAN_SECRET_KEY_FILE` | `~/.arslan/secret_key` | Dev-only: where the auto-generated secret persists — kept **outside** the data dir on purpose (backup = data dir **+** this file). Set **empty** to disable auto-generation entirely. Ignored in `prod`. Any dev entry point that loads server config (server, migration CLI, diagnostics) may mint it on first use; generation always prints one line saying where. |
| `ARSLAN_API_TOKEN` | *(empty)* | API/WS bearer token. **Empty in dev + localhost = no auth** (zero-friction local). For prod / packaged / non-loopback binds a token is auto-generated on first run (see below). |
| `ARSLAN_DATA_DIR` | platform app-data dir | Where the DB, notes, and secrets live. Unset → macOS `~/Library/Application Support/Arslan`, Linux `~/.local/share/Arslan`, Windows `%APPDATA%/Arslan`. **This directory plus your secret are the backup unit** (see [Data & backup](#data--backup)). |
| `ARSLAN_ENV` | `dev` | `dev` or `prod`. `prod` requires a token and hardens defaults; a missing `ARSLAN_SECRET_KEY` in `prod` is boot-fatal. |
| `ARSLAN_ALLOWED_HOSTS` | localhost only | Comma-separated TrustedHost allowlist for non-localhost / prod deploys. |
| `ARSLAN_ALLOWED_ORIGINS` | localhost only | Comma-separated CORS + WebSocket-Origin allowlist for non-localhost / prod deploys. |
| `ARSLAN_ALLOW_INSECURE_SECRETS` | *(off)* | Dev-only escape hatch: permits writing secrets under the public default key. **Never use for real keys.** |
| `ARSLAN_ALLOW_UNSANDBOXED_PY` | *(off)* | Dev-only escape hatch: lets generated Python run **without** a sandbox where none is available. Arbitrary code then runs with the server's privileges and network access; runs are marked `sandboxed=false` for audit. Only enable on a machine you fully trust. |

For prod / packaged (`ARSLAN_PACKAGED=1`) / non-loopback binds, if `ARSLAN_API_TOKEN` is empty the app **auto-generates** a token on first run, persists it to `<data_dir>/api_token` (owner-only), prints it once at boot, and lets you view/reset it in Settings.

</details>

<details>
<summary><b>Data &amp; backup</b></summary>
<br/>

Everything that matters lives in one directory — the DB, your notes, and your encrypted secrets — resolved from `ARSLAN_DATA_DIR` (or the platform app-data dir if unset). **That directory IS the backup unit:** copy it to back Arslan up, and restore by copying it back. Keep its `api_token` and `crypto_salt` files with it — new-scheme (PBKDF2) encrypted secrets are derived from `ARSLAN_SECRET_KEY` **and** the per-install `crypto_salt`, so losing (or mismatching) `crypto_salt` makes those stored secrets undecryptable even with the right `ARSLAN_SECRET_KEY`.

One deliberate exception: the secret itself lives **outside** that directory. If you never set `ARSLAN_SECRET_KEY` yourself, the dev auto-generated value sits at `~/.arslan/secret_key` — so a copied data dir alone can't decrypt your stored provider keys (lock and box travel separately). A complete backup is therefore **two pieces**: the data dir **and** the secret (your env value or that file).

</details>

## Status — honest about what's proven

**Pre-v1.** We'd rather under-claim than over-sell:

- **macOS-first.** The kernel sandbox is macOS seatbelt only; on other platforms it fails closed (Linux / Windows are targeted later via a Tauri desktop app).
- **The self-evolving agent team is being hardened.** The two-tier evolution loop works but is not yet claimed as fully proven — treat it as maturing, not finished.
- **Agentic memory read/write needs a native-tool-calling provider.** The `recall`/`remember` tools only fire on providers that actually do tool-calling (e.g. DeepSeek). Over a direct Anthropic backend they never trigger — that path is intentionally text-in/text-out, so the tool schema is never sent to the model. Memory still forms automatically either way (router-extracted facts + end-of-session distillation), independent of this feature.
- **The two background loops that spend money ship disabled.** Auto-evolution and sleep-time curation each call the LLM on their own schedule, so both default to off — you turn them on in Settings. **What is enforced:** a cap on the number of replay DISPATCHES an evolution attempt may project (you set it in Settings; an attempt over the cap is refused before it runs), and a fetch budget on web search/extract — per run for a live turn, and per attempt for the evaluation loop, which is the surface that multiplies. **What is not:** there is no exact token ceiling. Dispatches are counted rather than tokens because the per-dispatch cost varies too much for a token number to mean anything, and the pre-run token estimate over-states by 3.7–5.2x — a cap set from real spend would refuse every attempt. So treat the caps as bounding the ORDER of magnitude, and still keep a hard limit in your provider's billing dashboard.
- APIs, schemas, and defaults may change before v1.

## Community

- <img src="docs/assets/icons/bug.svg" width="14" height="14"> Found a bug or have an idea? [Open an issue](https://github.com/mirzatghayrat/arslan/issues).
- <img src="docs/assets/icons/heart-handshake.svg" width="14" height="14"> Want to help? Start with [CONTRIBUTING.md](CONTRIBUTING.md).
- <img src="docs/assets/icons/globe.svg" width="14" height="14"> The project site lives in [`docs/index.html`](docs/index.html) (served via GitHub Pages). The blueprint figures in this README are hand-drawn SVGs — sources in [`docs/diagrams/`](docs/diagrams/).

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Third-party dependency notices are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Icons: [Lucide](https://lucide.dev) (ISC).

---

<div align="center">
<sub>If Arslan resonates with you, <a href="https://github.com/mirzatghayrat/arslan/stargazers">a <img src="docs/assets/icons/star.svg" width="12" height="12"> helps other people find it</a>.</sub>
</div>
