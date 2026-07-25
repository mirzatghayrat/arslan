# Contributing to Arslan

Thanks for your interest in Arslan — a local-first, BYOK multi-agent orchestrator. This guide gets a new contributor from a fresh clone to a running dev instance in about **30 minutes**, then explains the checks, conventions, and workflow you need to land a qualifying PR.

- New to the project? Read the [README.md](README.md) first for what Arslan is and the user-facing quickstart.
- Want the mental model of the codebase? Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
- Reporting a security issue? Do **not** open a public issue — see [SECURITY.md](SECURITY.md).

## Prerequisites

| Tool | Version | Notes |
| --- | --- | --- |
| **Python** | **3.11+** (`requires-python = ">=3.11"`) | CI runs on **3.12**; develop on 3.11–3.12. |
| **[uv](https://docs.astral.sh/uv/)** | latest | Manages the virtualenv + resolves deps from `uv.lock`. |
| **Node.js** | **22** | CI uses Node 22 (`.github/workflows/ci.yml`); match it to avoid lockfile/toolchain drift. |
| **git** | any recent | `gh` is optional (only used by the shell command surface). |

macOS is the best-supported dev platform: the kernel sandbox is macOS-seatbelt-only, so the sandboxed-code paths only fully exercise there. Linux/Windows work for most of the codebase, but generated-code execution fails closed (see [Status](#status)).

## Dev setup (target: ≤30 minutes)

```bash
# 1. Clone
git clone https://github.com/mirzatghayrat/arslan.git
cd arslan

# 2. Create the venv and install deps — include the server + dev extras.
#    Plain `uv sync` installs only the core deps; the backend needs the
#    `server` extra (SQLAlchemy/aiosqlite/cryptography) and the checks need
#    the `dev` extra (pytest/ruff). This matches what CI installs.
uv sync --extra dev --extra server
#    (Optional) add local embeddings for the second brain's vector retrieval:
#    uv sync --extra dev --extra server --extra embeddings

# 3. Run the backend. Pinning ARSLAN_SECRET_KEY keeps every contributor boot on
#    ONE stable secret (it derives the key that encrypts stored BYOK secrets).
#    Left unset, dev auto-generates one into ~/.arslan/secret_key — also fine,
#    but switching between the two styles changes the effective secret and makes
#    previously-stored keys undecryptable: pick one style and stick to it.
PYTHONPATH=$PWD \
ARSLAN_SECRET_KEY=dev-secret-key \
ARSLAN_API_TOKEN= \
ARSLAN_DATA_DIR=data \
  .venv/bin/uvicorn server.main:app --host 127.0.0.1 --port 8741

# 4. In a second terminal, run the frontend dev server.
cd web && npm install && npm run dev
```

Open **http://localhost:5173**. The Vite dev server proxies `/api` and `/ws` to the backend on `:8741`. On **first run**, a wizard walks you through adding a **BYOK** LLM key so Arslan has a model to think with — you need at least one provider key (e.g. an OpenAI-compatible or DeepSeek key) for the agent to respond.

Notes for the dev flow:

- **Auth is off by design in dev + localhost.** With `ARSLAN_ENV=dev` (the default) and an empty `ARSLAN_API_TOKEN` on a loopback bind, no token is required — zero friction locally. This is *only* safe for a loopback bind on a machine you control; see [SECURITY.md](SECURITY.md) before exposing it.
- **`ARSLAN_DATA_DIR=data` keeps your brain in the repo's `data/` dir** while developing. If you leave it unset, Arslan uses the stable per-platform app-data dir instead (macOS `~/Library/Application Support/Arslan`, Linux `~/.local/share/Arslan`, Windows `%APPDATA%/Arslan`) — handy so a packaged app keeps *one* brain regardless of launch directory, but for dev an in-repo `data/` is easier to inspect and reset (`.gitignore`d).
- **No `--reload`.** The backend does not auto-reload; restart uvicorn after backend changes. The frontend (Vite) hot-reloads.

## Environment variables (dev-focused)

Mirrors [README.md](README.md#environment-variables); every var below is read in `server/config.py`. The three you'll actually set in dev are the first three.

| Env var | Dev value | Purpose |
| --- | --- | --- |
| `ARSLAN_SECRET_KEY` | `dev-secret-key` (any non-empty value) | Derives the Fernet key (PBKDF2-HMAC-SHA256 over a per-install salt) that encrypts stored BYOK secrets. Unset in dev → auto-generated once and persisted to `~/.arslan/secret_key` (see the README env table). An explicit value always wins — don't flip-flop between explicit and auto-generated, or previously-stored keys become undecryptable. In `prod` a missing value is boot-fatal. |
| `ARSLAN_API_TOKEN` | *(empty)* | API/WS bearer token. Empty + dev + localhost = no auth. For `prod` / packaged / non-loopback binds a token is auto-generated on first run. |
| `ARSLAN_DATA_DIR` | `data` | Where the SQLite DB, notes, spawns, and encrypted secrets live. **This directory plus your secret are the backup unit** (the secret lives outside it — your env value or `~/.arslan/secret_key`). Unset → platform app-data dir. |
| `ARSLAN_ENV` | `dev` (default) | `dev` or `prod`. `prod` hardens defaults and makes a missing secret boot-fatal. |
| `ARSLAN_ALLOWED_HOSTS` | *(unset)* | Comma-separated TrustedHost allowlist for non-localhost / prod. Dev defaults to localhost + test hosts. |
| `ARSLAN_ALLOWED_ORIGINS` | *(unset)* | Comma-separated CORS + WS-Origin allowlist for non-localhost / prod. Dev defaults to the Vite origin `http://localhost:5173`. |
| `ARSLAN_ALLOW_INSECURE_SECRETS` | *(off)* | Dev-only escape hatch: permits writing secrets under the public default key. Never use for real keys. |
| `ARSLAN_ALLOW_UNSANDBOXED_PY` | *(off)* | Dev-only escape hatch: lets generated Python run **without** a sandbox where none is available (non-macOS). Runs then have the server's full privileges + network; marked `sandboxed=false`. Only enable on a machine you fully trust. |

Other read-but-rarely-set vars (see `server/config.py` + `server/secret_bootstrap.py`): `ARSLAN_DB_PATH`, `ARSLAN_SPAWNS_DIR`, `ARSLAN_STATIC_DIR`, `ARSLAN_BIND_HOST`, `ARSLAN_ATTACH_CHAR_LIMIT`, `ARSLAN_PACKAGED`, `ARSLAN_MCP_HEALTH_ON_BOOT`, `ARSLAN_SECRET_KEY_FILE` (dev secret persistence path; empty = disable auto-generation — the test suites pin it empty).

## Where things live

```
server/                FastAPI backend
  api/                 REST endpoints, /api/v1 (spawns, settings, runs, evolution, …)
  ws/                  WebSocket layer — the conversation stream
  orchestrator/        Arslan host loop: router, tool_loop (native tool-calling), spawn_loop, dispatcher
  registry/            Capability layer: 3-library registry, executors, the single write gate
  services/            ~45 services: BYOK routing, spawns, evolution/eval, distill, shell-net proxy
  db/                  SQLAlchemy models, session, hand-wired migrations (versions/_00NN_*.py)
  main.py              App factory + lifespan (boots migration chain, seeds registry)
  config.py            All ARSLAN_* env vars resolve here
arslan/                CLI + core package (llm routing profiles, spawn seeds/scaffold, templates)
web/src/               React 19 + TS + Vite SPA (components/, stores/, api/, hooks/, locales/)
tests/                 Pytest suite (tests/server/ is the bulk; also core/, services/, spawn/, …)
scripts/               smoke_main_link.py (main-link smoke gate) + helper scripts
docs/                  ARCHITECTURE.md, superpowers/ (specs, plans, evidence), tech-debt/
```

## Checks you must pass before opening a PR

These are exactly what CI (`.github/workflows/ci.yml`) enforces. Run them locally and make them green **before** you push.

### Backend

```bash
# Ruff lint — same paths CI checks
.venv/bin/ruff check server/ arslan/ tests/ scripts/

# Tests — CI runs the whole tests/ tree
PYTHONPATH=$PWD ARSLAN_SECRET_KEY=dev-secret-key ARSLAN_API_TOKEN= ARSLAN_DATA_DIR=data \
  .venv/bin/pytest tests/ -q

# Main-link smoke gate — boots the REAL server against a throwaway data dir
# (mocked LLM adapter, no network) and asserts routing + reply + persistence.
.venv/bin/python scripts/smoke_main_link.py
```

> **CI's exact pytest invocation** adds a scoped flake retry:
> `.venv/bin/pytest tests/ -q -rR --reruns 2 --reruns-delay 1 --only-rerun "database is locked"`.
> That `database is locked` retry is a **deliberate, tightly-scoped bridge** for a known cross-event-loop SQLite test-harness flake — it is *expected* to occasionally trigger in CI and does **not** indicate a product bug. See [docs/tech-debt/single-loop-sqlite-flake.md](docs/tech-debt/single-loop-sqlite-flake.md). **Iron rule: the `--only-rerun` match string is `"database is locked"` and never widens.** If you hit a *different* flaky signature, that means a real root fix is needed — open the escalation ticket, do not broaden the retry.

### Frontend (run from `web/`)

```bash
cd web
npm run lint     # tsc --noEmit  → the Typecheck gate
npm run test     # vitest run    → the Vitest gate
npm run build    # the Build gate
```

> **Typecheck is a SEPARATE gate from Build — a known trap.** In CI, `Typecheck` (`tsc --noEmit`, aliased as `npm run lint`) runs as its own step, distinct from `Build` (`npm run build`). **`npm run build` can pass while `tsc --noEmit` fails** (e.g. a test file with an undeclared `expect`/`test`, or an unused import that Vite happily bundles but `tsc` rejects). Always run `npm run lint` explicitly — a green build is not a green typecheck.

For reproducible installs matching CI, use `npm ci` instead of `npm install` (it installs from `web/package-lock.json`).

## Project conventions

### Test-driven development

This repo is written test-first. **Write the failing test before the implementation**, then make it pass. New behavior lands with tests under `tests/` (most backend tests live in `tests/server/`). A change to product code without corresponding test coverage is unlikely to be accepted.

### Versioned migrations

Schema changes are **not** run via `alembic upgrade` (alembic is gone). They are idempotent `upgrade_sync` functions registered in an explicit, ordered runner — `server/db/migrations/runner.py` — which boot applies via its `schema_version` ledger (`server/main.py`'s `lifespan()` calls `apply_pending` after `Base.metadata.create_all`, in one transaction). To add a migration, update **three places in lockstep**:

1. Create `server/db/migrations/versions/_00NN_<name>.py` (bump `NN` past the latest — currently `_0031_*`). Expose an **idempotent** `upgrade_sync(connection)`: guard every change so re-running is a net no-op — the pattern is to read `PRAGMA table_info(<table>)` and only `connection.exec_driver_sql("ALTER TABLE … ADD COLUMN …")` for columns that don't exist yet. (See `_0027_mcp_health.py` for a minimal example.)
2. **Register it** in `server/db/migrations/runner.py`: add `from .versions._00NN_<name> import upgrade_sync as _m00NN` and append `("00NN", _m00NN)` to `MIGRATIONS` — **at the end, in order; never reorder existing entries** (the order is the zero-behavior-change guarantee).
3. **Update the hardcoded id list** in `tests/server/test_migration_runner.py::test_registry_matches_boot_chain_verbatim`.

> **Gotcha:** a version file that is *not* registered in `MIGRATIONS` never runs. The completeness test (`test_every_upgrade_sync_file_is_registered_or_documented_subsumed`) turns that into a **CI failure** rather than a silent runtime skip — so a forgotten registration is caught before merge. (`_0001`–`_0005` predate `create_all` and are allow-listed as `SUBSUMED`.)

### Commit & branch style

- **Branches:** `type/short-description`, e.g. `fix/router-hallucinated-spawn-id`, `feat/mcp-health-badge`, `docs/contributing-architecture`.
- **Commits:** imperative, present tense, focused. Explain *why* in the body when it isn't obvious. Keep unrelated changes out.
- Co-author trailer when pairing with an AI assistant, e.g. `Co-Authored-By: …`.

### Where specs and plans live

Larger changes are designed before they're coded: a written **spec** (what/why, constraints, invariants touched, acceptance criteria), then an ordered implementation **plan**, then the code. The specs and plans behind the existing subsystems are internal research records and are **not published with the open-source release**; `docs/ARCHITECTURE.md` is the public account of how the system fits together, and the invariants it lists are the ones to preserve.

## The workflow this repo uses

Non-trivial work follows a **brainstorm → spec → plan → implement** arc:

1. **Brainstorm / propose** — open an issue or discussion describing the problem and the intended direction. For anything design-heavy, align on approach first.
2. **Spec** — capture the design as a written spec (what/why, constraints, invariants touched, acceptance criteria).
3. **Plan** — break the spec into an ordered implementation plan; tasks are often executed by focused sub-agents.
4. **Implement** — TDD each task, keeping the checks above green.

For a small, self-contained fix you can skip straight to a PR — but still open an issue first if it changes behavior, touches a security/honesty guard, or alters schema.

## Submitting a PR

- **Branch** off `main` with a descriptive `type/desc` name and push to the repo (or your fork).
- **Green checks.** All the [checks above](#checks-you-must-pass-before-opening-a-pr) must pass — backend ruff + pytest + smoke, and frontend lint + test + build. Note in the PR that they're green locally.
- **Keep it focused.** One logical change per PR. Split refactors from behavior changes.
- **Include tests** for new behavior or bug fixes (TDD).
- **Don't weaken the guards without discussion.** The sandbox (fails-closed), the auth posture (safe-by-default), the capability write gate (single-throat `assert_assignable`, tier isolation), and the honesty guardrails (`promise_guard`, `wrap_external` on tool output) are load-bearing invariants. If your change touches one, call it out explicitly and get sign-off first. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#cross-cutting-invariants) and [SECURITY.md](SECURITY.md).
- **Link the spec/issue** the PR implements.

## Reporting security issues

Please report vulnerabilities **privately**, not in a public issue — use GitHub's private "Report a vulnerability" flow or the security contact in [SECURITY.md](SECURITY.md).

## License

Arslan is licensed under **Apache-2.0** (see [LICENSE](LICENSE) and [NOTICE](NOTICE)). By contributing, you agree that your contributions are licensed under Apache-2.0. Third-party dependency notices are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Status

**Pre-v1.** Be aware of what's proven and what isn't:

- **macOS-first.** The kernel sandbox is macOS seatbelt only; on other platforms it fails closed. Linux/Windows are targeted later via a Tauri desktop app.
- **The self-evolving agent team is being hardened.** The two-tier evolution loop works but is not yet claimed as fully proven — treat it as maturing.
- **APIs, schemas, and defaults may change before v1.** See the [README status section](README.md#status) for the current roadmap positioning.
