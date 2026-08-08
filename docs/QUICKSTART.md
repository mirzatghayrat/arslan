# Quickstart — your first 15 minutes with Arslan

This walks you from a fresh clone to **a specialist spawn answering you in the conversation** — and, optionally, to **watching your agent team improve itself**. It's the end-to-end narrative; the terse boot commands also live in the [README](../README.md#install).

**What you'll have at the end:** the app running locally, one BYOK model connected, and a named spawn (not just the host agent) streaming an answer to a real task. The optional final step shows the self-improving half of the product.

**Roughly:** ~15–20 minutes to your first spawn answer (dependency downloads dominate). The optional "watch it improve itself" step adds 15–60 minutes of mostly-unattended background compute.

---

## Before you start

- **Toolchain:** Python 3.11+ (CI uses 3.12), [`uv`](https://docs.astral.sh/uv/), Node.js 22, and `git`.
- **macOS is best-supported.** The kernel sandbox for generated-code execution is macOS-seatbelt-only. On Linux the app installs and the whole chat flow works; only *generated-code execution* fails closed. (Windows/Linux desktop builds come later via Tauri.)
- **You need one BYOK LLM key.** Arslan runs against *your* provider key — nothing answers until you add one. This guide features **DeepSeek** (the first-run wizard's default), but any OpenAI-compatible / native Anthropic / Gemini key works.
- **Dev + localhost is unauthenticated by design** — zero-friction local use. No bearer token here; tokens only apply to the Docker/prod path at the end. Don't expose this bind to an untrusted network (see [SECURITY.md](../SECURITY.md)).

---

## 1. Clone and install

```bash
git clone https://github.com/mirzatghayrat/arslan.git
cd arslan

# Backend deps — include the server (runtime) + dev extras.
uv sync --extra dev --extra server
```

> **Don't run a bare `uv sync`.** It installs only the core deps. The backend imports SQLAlchemy / aiosqlite / cryptography, which live in the optional **`server`** extra — without it, `uvicorn server.main:app` fails to import at boot. `--extra dev --extra server` matches what CI and the Dockerfile install.

---

## 2. Start both servers

You'll run the backend and the frontend as two long-lived processes, so open **two terminals**.

**Terminal 1 — backend.** Just start it — on the first boot the server auto-generates `ARSLAN_SECRET_KEY`, persists it to `~/.arslan/secret_key` (it prints where), and reuses it on every later boot:

```bash
# Sources .env only if you created one (see the optional pin below).
[ -f .env ] && set -a && source .env && set +a
PYTHONPATH=$PWD ARSLAN_DATA_DIR=data \
  .venv/bin/uvicorn server.main:app --host 127.0.0.1 --port 8741
```

**Optional — manage the secret yourself.** Pin it in `.env` instead (generated ONCE; `.env` is gitignored, and the same value also serves the Docker path below):

```bash
# Seeds from the already-persisted secret when one exists (never re-mint over a
# secret that already encrypted stored keys); only a true first run generates.
grep -q '^ARSLAN_SECRET_KEY=.' .env 2>/dev/null \
  || { key="$(cat "${ARSLAN_SECRET_KEY_FILE:-$HOME/.arslan/secret_key}" 2>/dev/null \
       || python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
       && [ -n "$key" ] && echo "ARSLAN_SECRET_KEY=$key" >> .env; } \
  && [ -f .env ] && chmod 600 .env
```

> **Why one stable secret?** `ARSLAN_SECRET_KEY` derives the key that encrypts your stored BYOK secrets at rest. If it changes between runs, previously-stored keys become **undecryptable** — the auto-generated file (and the optional `.env` pin) exists precisely so the value stays stable. A complete backup is **two pieces**: your data dir **plus** the secret (`~/.arslan/secret_key`, or your own value). The dev server reads the *process* environment (not `.env` directly), which is why an explicit pin must be `source`d first.

**Terminal 2 — frontend:**

```bash
cd web && npm install && npm run dev
```

Open **http://localhost:5173**. The Vite dev server proxies `/api` and `/ws` to the backend on `:8741`.

> **Notes.** The backend has **no `--reload`** — after backend code changes, Ctrl-C and restart uvicorn (the frontend hot-reloads). `npm run dev` runs a small staging script (a transparent Tailwind-v4 workaround) — use it rather than calling `vite` directly, or you may get an unstyled page. If `/api` or `/ws` gives connection-refused, use `127.0.0.1:5173` rather than `localhost:5173` (localhost can resolve to IPv6-only).

---

## 3. Add your model (first-run wizard)

On first load, a **first-run wizard** appears automatically (because no model is configured yet). It's a 3-step modal:

1. Welcome
2. Pick your language
3. **Connect a model** — the provider defaults to **DeepSeek**, and the model is set automatically to `deepseek-v4-flash` (the wizard has no model field). Just **paste your API key** into the password field and click **Finish**.

Your key is encrypted at rest (Fernet / PBKDF2-HMAC-SHA256), and the first model you save becomes your primary.

> **If the wizard's model id doesn't match your provider,** fix it later in **Settings → Providers** (that screen also has a **Test** button the wizard doesn't). The wizard saves without a connectivity test, so a wrong/expired key or an unknown model id only surfaces as an error later, in chat.

**Alternatives:**

- **Settings → Providers → Add config** — paste the key (it commits when the field loses focus), with a **Test** button.
- **CLI** (dev/localhost, no auth header needed). Replace the placeholder with your own key — never paste a real key into a shared shell/history you don't control:

  ```bash
  curl -X POST http://127.0.0.1:8741/api/v1/settings/provider-configs \
    -H 'Content-Type: application/json' \
    -d '{"label":"DeepSeek","provider":"deepseek","model":"deepseek-v4-flash","base_url":"https://api.deepseek.com","api_key":"<YOUR_DEEPSEEK_KEY>"}'
  ```

> **Key saves just work by default** — the server auto-generates `ARSLAN_SECRET_KEY` on first boot (step 2). If you disabled that (`ARSLAN_SECRET_KEY_FILE=` set empty) or the boot log warned that persisting failed, set `ARSLAN_SECRET_KEY` yourself before saving a key — without any secret the save fails closed and the wizard quietly closes without storing anything.

---

## 4. Get your first spawn to answer

Arslan is a **team**, not a single chatbot. Six specialist spawns are seeded on first boot (Research Analyst, Data & Chart Analyst, Financial Research Analyst, Content & Copywriter, Coding Assistant, Deck Master). But each conversation's **roster starts empty**, so you pull one in first.

**The one-step way to see a spawn answer:**

1. In the roster / Ledger rail, click **+ Pull Into Chat** on **Research Analyst** — you'll see *"Research Analyst joined the conversation."*
2. In the composer, type a task in its domain and press Enter, e.g.:
   > Research the current state of AI agent frameworks and give me a sourced briefing.
3. Research Analyst streams its answer **under its own name** — a distinct specialist, not the host. That's the "my agent team works" moment.

> **The doer-first trap — read this or you'll think it's just one chatbot.** If you type a task with an *empty* roster, **Arslan answers it itself** and offers a small "let Research Analyst take this?" card. Accepting that card only *enrolls* the spawn into this session's roster — it does **not** re-run the task. So either **pull the spawn into the chat / @-mention it first** (recommended, one step), or accept the card and **send the task again**.

**Alternatives:**

- **One-shot:** type `@Research Analyst <task>`. Arslan gives a brief and shows an invite card — click **Accept** and it dispatches.
- **Create your own:** describe a *recurring* need in a domain your current spawns don't cover (e.g. "every week, audit my repo's dependencies for new CVEs"). When nothing on the roster fits, the router offers a **Create** card; click it and the new spawn joins and runs the task immediately. (A bare "make me a spawn" with no specifics won't create anything — it'll ask you to be concrete.)

> Each turn makes two or three LLM calls (a routing decision, sometimes a roster-scoring step when a member fits, then the answer/spawn run), so the *first* response has a little latency. That's expected.

> **Second brain — recall/remember, honest caveats.** Arslan (and any spawn equipped with the "Second Brain" toolset) can search and write your second brain directly by calling `recall`/`remember` tools mid-conversation. Two things to know:
> - **Needs a native-tool-calling provider** (e.g. DeepSeek). Over a direct Anthropic connection those tools never fire — that backend is intentionally text-in/text-out, so no tool schema is ever sent. Your memory still forms automatically regardless (facts extracted from what you say, plus end-of-session distillation) — this only affects the model's ability to actively search/write it mid-turn.
> - **High-confidence proposals (delete / overwrite / edit) are REST-only.** When the model wants to delete or overwrite something instead of just appending, it proposes the change rather than applying it — today that proposal is only visible/actionable via `GET`/`POST /brain/proposals`, not an in-app inbox yet.

---

## 5. (Optional) Watch it improve itself

This is the self-improving half of the product. It's **optional and slow** — one attempt takes **15–60 minutes** of mostly-unattended background compute and spends **real BYOK tokens** — so skip it if you just wanted a first answer.

**Prep — use a plain Q&A spawn.** Only runs with no side-effecting tools are hermetically replayable and eligible for evolution. Keep the spawn to plain answering (or the replay-safe built-ins: web search / extract, chart, deck, `run_python`, `read_skill`).

1. **Build a corpus.** Chat with that spawn ~8–10 times with real questions. Each answer records a run, and an LLM judge auto-scores it in the background.
2. **Trigger it.** Go to **Diagnostics → evolution**, pick the spawn under **运行进化 (Run evolution)**, click **Estimate** (shows projected judge calls + dispatches; see the caveat below on what the token number is worth), then **ENQUEUE**.
3. **Wait 15–60 minutes.** A bounded-edit optimizer runs several epochs, then a final paired holdout gate decides whether a candidate actually beats the current prompt.
4. **Review & promote.** When a proposal appears, open it: the promotion card shows real vs. synthetic win-rates (kept separate), a per-dimension win table, the prompt diff, and per-pair replay links. Click **Confirm** to adopt the generation-2 prompt — or **Reject**, or **Rollback** later.

> **Honest caveats.**
> - A dead or undecryptable BYOK key makes every attempt bail in seconds — verify your key in **Settings** first (this is the most common reason an attempt "does nothing").
> - The inbox currently shows only a static *"Enqueued"* line while an attempt runs — no live progress bar yet. **Refresh the tab** to find the finished proposal.
> - **The cost estimate is not a bound in either direction.** The `est_tokens` field is labelled `lower_bound` and that label is wrong: it multiplies the whole corpus by the epoch budget, but the optimizer only replays a capped validation slice, so it reads close to a floor on a small corpus and increasingly over-states as the corpus grows (`server/services/evolution_estimate.py`). It also prices neither the optimizer's own per-epoch calls nor synthetic minting. What you *can* set is `evolution_max_dispatches` — a cap on projected replay dispatches, in **Settings → Automation**, unset by default. The retired `evolution_max_est_tokens` key no longer gates anything; if an install still has it set, diagnostics says so rather than silently ignoring it.
> - **Auto-evolution ships off.** Nothing runs in the background — and spends tokens — until you turn it on in **Settings → Automation**. Once on, it fires by itself as new scored runs accrue, so attempts happen without you clicking ENQUEUE. Sleep-time curation is off by default for the same reason.
> - With very few real comparison pairs, the card flags the result as "synthetic-driven" and suggests waiting for more evidence before promoting.

---

## Alternatives & troubleshooting

**Run with Docker** (single terminal, but **not** the fastest path to usable):

```bash
cp .env.example .env    # set ARSLAN_SECRET_KEY
docker compose up --build
```

Open http://localhost:8741. The image pins `ARSLAN_ENV=prod`, so it **enforces a bearer token** and **refuses to boot without `ARSLAN_SECRET_KEY`**. With `ARSLAN_API_TOKEN` empty, it auto-mints a token on first boot and prints it **once** — grab it from `docker compose logs`. That token step is why the dev/localhost path above is the quicker way to "usable."

**Common first-run issues:**

| Symptom | Fix |
| --- | --- |
| Backend `ImportError` at boot | You ran a bare `uv sync` — re-run `uv sync --extra dev --extra server`. |
| Nothing answers | No model saved — reopen the wizard or add a key in **Settings → Providers**. |
| Only the host answers, never a spawn | Roster is empty — **+ Pull Into Chat** or `@`-mention a spawn first (see step 4). |
| Unstyled page | You bypassed `npm run dev` — use it, not a direct `vite` call. |
| `/api` or `/ws` refused | Use `127.0.0.1:5173`, not `localhost:5173`. |
| Stored keys suddenly "undecryptable" | `ARSLAN_SECRET_KEY` changed between runs — keep it stable. Common cause: switching between an explicit env value and the auto-generated `~/.arslan/secret_key`. |

**Back up your data — two pieces.** The DB, notes, and encrypted secrets live under `ARSLAN_DATA_DIR` (here, `data/`); back it up and restore it **as a whole**, keeping its `crypto_salt` with it (or PBKDF2-encrypted secrets become undecryptable). The **second piece is the secret itself**, which deliberately lives outside the data dir: your `ARSLAN_SECRET_KEY` value, or the auto-generated `~/.arslan/secret_key`. A data-dir-only backup restored on a fresh machine gets a NEW auto-generated secret and cannot decrypt the stored provider keys. See the [README](../README.md#data--backup) for details.

---

Next steps: browse the [architecture overview](ARCHITECTURE.md), the [capability layer](capabilities.md), and — if you want to contribute — [CONTRIBUTING.md](../CONTRIBUTING.md).
