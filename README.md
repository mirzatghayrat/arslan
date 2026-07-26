# Arslan

**A local-first personal AI orchestrator.** You talk to one main agent — *Arslan* — which routes your request or delegates it to persona sub-agents ("spawns") that it can create, equip, and evolve. It runs on your own machine, against your own LLM keys, with a **safe-by-default kernel sandbox**, **honesty guardrails**, and a **visible second brain** you can browse and edit.

- **A persona team you grow.** Arslan is the front door; behind it you build a roster of specialised spawns, give them capabilities, and let a two-tier evolution loop refine them over time.
- **Safe by default.** Generated code runs inside a kernel-enforced sandbox (macOS seatbelt, network-denied). A credential-injecting proxy lets sandboxed git talk to the network without the raw tokens ever entering the sandbox. Localhost dev is zero-friction; prod / packaged builds auto-enforce a token.
- **Honest by design.** Guardrails intercept fabricated "I already did that" claims and keep the agent's self-reporting tied to what actually ran.
- **A brain you can see.** Materials, learnings, a profile, and wiki-link notes, retrieved with hybrid FTS5 + embeddings and browsable as an Obsidian-style graph.

Backend: FastAPI + async SQLAlchemy/SQLite (`server/`). Frontend: React 19 + TypeScript + Vite (`web/`).

## Features

- **Capability layer** — built-in tools + an MCP client + `SKILL.md` skill packs, tiered (safe vs. orchestrator) with human-confirm gating for privileged actions.
- **Kernel sandbox + credential proxy** — code runs network-denied under macOS seatbelt; a local MITM proxy injects git credentials so raw tokens never reach sandboxed processes. Fails closed where the kernel sandbox is unavailable.
- **Second brain** — materials / learnings / profile + `[[wiki-link]]` notes, hybrid FTS5 + embedding retrieval (FTS-only until an embedding provider is configured), Obsidian-style force-directed graph. Beliefs carry time: when each became true, what superseded it, and a start-time filter that shows the graph as it stood at a past instant. Deletes and overwrites the model proposes never apply directly — they land in an in-app inbox you accept or dismiss. Arslan (and equipped spawns) can also read/write it via agentic `recall`/`remember` tools — see the caveats in [Status](#status).
- **Tracing, eval & diagnosis** — per-run traces, an LLM-judge evaluator, and a Grafana-style diagnosis dashboard, feeding a two-tier evolution loop.
- **Multi-LLM BYOK** — bring your own keys across multiple providers with quality-first routing.
- **6-language i18n** and **6 theme palettes** (light + dark).

## Quickstart (dev)

**Prerequisites:** Python (managed with [`uv`](https://docs.astral.sh/uv/)) and Node.js.

> **New here?** For the full 5-minute first-run walkthrough — connect a model, get your first spawn to answer, and (optionally) watch it improve itself — see **[docs/QUICKSTART.md](docs/QUICKSTART.md)**. The commands below are the terse version.

```bash
# 1. Clone
git clone https://github.com/mirzatghayrat/arslan.git
cd arslan

# 2. Backend deps — include the server (runtime) + dev extras.
#    Plain `uv sync` installs only core deps; the backend imports SQLAlchemy/
#    aiosqlite/cryptography, which live in the `server` extra. Matches CI.
uv sync --extra dev --extra server

# 3. Secret key — nothing to do by default. On the FIRST dev boot the server
#    auto-generates ARSLAN_SECRET_KEY, persists it to ~/.arslan/secret_key
#    (outside the data dir on purpose — backup = data dir + that file), and
#    reuses it on every later boot.
#    OPTIONAL — pin it yourself in .env instead. It derives the key that
#    encrypts stored BYOK secrets at rest; a changed value makes previously-
#    stored keys undecryptable, so the pin SEEDS from the already-persisted
#    secret when one exists and only mints a fresh value on a true first run:
grep -q '^ARSLAN_SECRET_KEY=.' .env 2>/dev/null \
  || { key="$(cat "${ARSLAN_SECRET_KEY_FILE:-$HOME/.arslan/secret_key}" 2>/dev/null \
       || python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
       && [ -n "$key" ] && echo "ARSLAN_SECRET_KEY=$key" >> .env; } \
  && [ -f .env ] && chmod 600 .env

# 4. Run the backend (sources .env only if you created one in step 3 — the dev
#    server reads the process environment, not .env directly).
[ -f .env ] && set -a && source .env && set +a
PYTHONPATH=$PWD ARSLAN_DATA_DIR=data \
  .venv/bin/uvicorn server.main:app --host 127.0.0.1 --port 8741

# 5. In a second terminal, run the frontend dev server
cd web && npm install && npm run dev
```

Open **http://localhost:5173**. The Vite dev server proxies `/api` and `/ws` to the backend on `:8741`. On first run, a wizard walks you through adding a **BYOK** LLM key so Arslan has a model to think with. Configure additional keys, themes, and language later in Settings.

> Dev + localhost is **unauthenticated by design** for zero-friction local use. See [Security posture](#security-posture) before exposing it anywhere else.

### Run with Docker

```bash
cp .env.example .env   # set ARSLAN_SECRET_KEY (required in prod) and ARSLAN_API_TOKEN
docker compose up --build
```

Open http://localhost:8741. The image pins `ARSLAN_ENV=prod`, so it **refuses to boot without `ARSLAN_SECRET_KEY`** — supply a long random value via `.env` or the shell.

## Environment variables

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

## Security posture

Arslan is **safe by default**:

- **Localhost-only by default.** Dev + localhost runs unauthenticated on purpose (local convenience). Cross-site drive-by requests are blocked by TrustedHost + CORS + WebSocket-Origin checks; non-localhost / prod deploys must set the allowlists above.
- **Tokens where they matter.** `prod`, packaged builds, and non-loopback binds require a bearer token — auto-generated, persisted, and rotatable from Settings so you can't lock yourself out.
- **Secrets refuse the public key.** BYOK secrets are Fernet-encrypted with a PBKDF2-HMAC-SHA256 key derived from `ARSLAN_SECRET_KEY` over a per-install salt; the app refuses to write secrets under the built-in public dev key.
- **Sandbox fails closed.** Generated code runs network-denied under the macOS seatbelt; where the kernel sandbox is unavailable it fails closed rather than silently running unsandboxed.

**Do not expose the server to an untrusted network without a token and host/origin allowlists.** Full threat model and reporting policy: [SECURITY.md](SECURITY.md).

## Data & backup

Everything that matters lives in one directory — the DB, your notes, and your encrypted secrets — resolved from `ARSLAN_DATA_DIR` (or the platform app-data dir if unset). **That directory IS the backup unit:** copy it to back Arslan up, and restore by copying it back. Keep its `api_token` and `crypto_salt` files with it — new-scheme (PBKDF2) encrypted secrets are derived from `ARSLAN_SECRET_KEY` **and** the per-install `crypto_salt`, so losing (or mismatching) `crypto_salt` makes those stored secrets undecryptable even with the right `ARSLAN_SECRET_KEY`.

One deliberate exception: the secret itself lives **outside** that directory. If you never set `ARSLAN_SECRET_KEY` yourself, the dev auto-generated value sits at `~/.arslan/secret_key` — so a copied data dir alone can't decrypt your stored provider keys (lock and box travel separately). A complete backup is therefore **two pieces**: the data dir **and** the secret (your env value or that file).

## Status

**Pre-v1.** Honest about what's proven:

- **macOS-first.** The kernel sandbox is macOS seatbelt only; on other platforms it fails closed (Linux / Windows are targeted later via a Tauri desktop app).
- **The self-evolving agent team is being hardened.** The two-tier evolution loop works but is not yet claimed as fully proven — treat it as maturing, not finished.
- **No OCR, and no image understanding.** Arslan reads the *text layer* of PDFs (pypdf) plus docx, pptx, html, txt and md. **Scanned PDFs and standalone image attachments yield no text.** OCR is an opt-in extra — `uv sync --extra ocr` — and it additionally needs a `tesseract` binary on your PATH (`brew install tesseract tesseract-lang`), which is why it is **not** in the packaged desktop build: bundling and notarizing that binary plus its language packs is a cost we deliberately deferred. The real fix is sending images to your own vision-capable model, which is a separate, planned round — see `docs/specs/2026-07-26-s4.3a-packaging.md` §9.
- **The desktop build is macOS Apple Silicon only, and not yet a public release.** There is no Windows, Linux, or Intel-Mac build — do not read "desktop app" as cross-platform. The first `.dmg` (S4.3-a) is an internal build for dogfooding and for proving the signing/notarization pipeline; the public release is a separate round (S4.3-b). Auto-update polls GitHub Releases: an install that cannot reach `github.com` will never see an update **and shows no indication of that** — this is stock Tauri updater behaviour, disclosed rather than fixed here.
- **Agentic memory read/write needs a native-tool-calling provider.** The `recall`/`remember` tools only fire on providers that actually do tool-calling (e.g. DeepSeek). Over a direct Anthropic backend they never trigger — that path is intentionally text-in/text-out, so the tool schema is never sent to the model. Memory still forms automatically either way (router-extracted facts + end-of-session distillation), independent of this feature.
- **The two background loops that spend money ship disabled.** Auto-evolution and sleep-time curation each call the LLM on their own schedule, so both default to off — you turn them on in Settings. Evolution has a hard pre-run gate: set `evolution_max_dispatches` and any attempt whose derived dispatch ceiling exceeds it is refused before the first call (the ceiling is exact for the corpus at estimate time; a *token* projection is shown alongside but is a pooled average, not a bound). Sleep-time curation has **no** cap of its own. A hard limit in your provider's billing dashboard is still the only bound that covers everything.
- APIs, schemas, and defaults may change before v1.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Third-party dependency notices are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
