# Arslan

An open-source Meta-Agent that helps non-technical users build domain-specific AI agents through conversation.

## Run with Docker

```bash
cp .env.example .env   # set ARSLAN_SECRET_KEY (required in prod) and ARSLAN_API_TOKEN
docker compose up --build
```

Open http://localhost:8741. The API is under `/api/v1`, WebSocket endpoints under `/ws`.

The Docker image pins `ARSLAN_ENV=prod`, so it **refuses to boot without `ARSLAN_SECRET_KEY`**. Supply a long random value via `.env` or the shell environment.

## Run locally (dev)

```bash
ARSLAN_SECRET_KEY=dev-secret-key \
  .venv/bin/uvicorn server.main:app --host 127.0.0.1 --port 8741
```

Zero-config local runs default to `ARSLAN_ENV=dev`: a missing secret falls back to a fixed insecure dev key (with a one-time warning) instead of refusing to boot.

### Configuration

| Env var | Default | Purpose |
| --- | --- | --- |
| `ARSLAN_ENV` | `dev` | `dev` or `prod`. In `prod`, a missing `ARSLAN_SECRET_KEY` is boot-fatal. |
| `ARSLAN_SECRET_KEY` | *(dev fallback)* | Derives the encryption key for stored BYOK LLM keys. **Required in prod.** |
| `ARSLAN_API_TOKEN` | *(empty)* | Bearer token protecting all API/WS endpoints. **Empty = no auth.** |
| `ARSLAN_BIND_HOST` | `127.0.0.1` | Advisory default bind host for launch scripts. The real bind is the launcher's `uvicorn --host`. |

## Security notes / risks

- **No API token = no auth.** With `ARSLAN_API_TOKEN` empty, every API and WebSocket endpoint is unauthenticated. This is intended for localhost only; a startup banner warns loudly. Never expose such an instance to a network.
- **Bind host is launcher-controlled.** The app defaults advisory guidance to `127.0.0.1`, but the effective bind is whatever `uvicorn --host` is passed. Binding `0.0.0.0` with no API token exposes the API to the network with no auth (a loud advisory is logged). Set `ARSLAN_API_TOKEN` or bind `127.0.0.1`.
- **Weak secret in dev.** A missing `ARSLAN_SECRET_KEY` in dev uses a fixed insecure key, so stored LLM keys are only weakly protected. Set a real secret before any non-local use.
- **Unsandboxed Python escape valve.** `run_python` fails closed when no sandbox backend is available (macOS seatbelt required). Setting `ARSLAN_ALLOW_UNSANDBOXED_PY=1` lets generated Python execute *without* a sandbox — arbitrary code runs with the server's privileges and network access. It is off by default; when on, runs are marked `sandboxed=false` for audit, the capability page shows a warning badge, and each unsandboxed run logs a banner. Only enable it on a machine you fully trust.
