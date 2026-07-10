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
- **Second brain** — materials / learnings / profile + `[[wiki-link]]` notes, hybrid FTS5 + embedding retrieval, Obsidian-style force-directed graph.
- **Tracing, eval & diagnosis** — per-run traces, an LLM-judge evaluator, and a Grafana-style diagnosis dashboard, feeding a two-tier evolution loop.
- **Multi-LLM BYOK** — bring your own keys across multiple providers with quality-first routing.
- **6-language i18n** and **6 theme palettes** (light + dark).

## Quickstart (dev)

**Prerequisites:** Python (managed with [`uv`](https://docs.astral.sh/uv/)) and Node.js.

```bash
# 1. Clone
git clone https://github.com/mirzatghayrat/arslan.git
cd arslan

# 2. Backend deps (creates .venv from uv.lock / pyproject.toml)
uv sync

# 3. Run the backend — set a real ARSLAN_SECRET_KEY to store LLM keys at rest
PYTHONPATH=$PWD \
ARSLAN_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(32))') \
ARSLAN_DATA_DIR=data \
  .venv/bin/uvicorn server.main:app --host 127.0.0.1 --port 8741

# 4. In a second terminal, run the frontend dev server
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
| `ARSLAN_SECRET_KEY` | *(dev fallback)* | Derives the Fernet key that encrypts stored BYOK secrets at rest. **Must be set to store API keys** — if unset the app refuses to write new encrypted secrets (the built-in dev key is public). In `prod` a missing value is boot-fatal. |
| `ARSLAN_API_TOKEN` | *(empty)* | API/WS bearer token. **Empty in dev + localhost = no auth** (zero-friction local). For prod / packaged / non-loopback binds a token is auto-generated on first run (see below). |
| `ARSLAN_DATA_DIR` | platform app-data dir | Where the DB, notes, and secrets live. Unset → macOS `~/Library/Application Support/Arslan`, Linux `~/.local/share/Arslan`, Windows `%APPDATA%/Arslan`. **This directory IS the backup unit.** |
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

Everything that matters lives in one directory — the DB, your notes, and your encrypted secrets — resolved from `ARSLAN_DATA_DIR` (or the platform app-data dir if unset). **That directory IS the backup unit:** copy it to back Arslan up, and restore by copying it back. Keep its `api_token` and `crypto_salt` files with it — without `crypto_salt` (and the matching `ARSLAN_SECRET_KEY`), stored secrets can't be decrypted.

## Status

**Pre-v1.** Honest about what's proven:

- **macOS-first.** The kernel sandbox is macOS seatbelt only; on other platforms it fails closed (Linux / Windows are targeted later via a Tauri desktop app).
- **The self-evolving agent team is being hardened.** The two-tier evolution loop works but is not yet claimed as fully proven — treat it as maturing, not finished.
- APIs, schemas, and defaults may change before v1.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Third-party dependency notices are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
