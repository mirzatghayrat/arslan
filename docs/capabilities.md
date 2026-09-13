# Arslan capabilities — the honest map

This document states exactly what spawns (Arslan's specialist agents) can and cannot do,
and where boundaries are enforced. An equippable capability has an implementation;
success still depends on permissions, setup, provider availability and the task.
See the [source-generated inventory](CAPABILITY_INVENTORY.md) for current catalog,
executor and provider-transport declarations, and [reliability contracts](RELIABILITY.md)
for tested boundaries and limitations.

## The tier model (one choke point)

All capability reads/writes flow through `server/registry/service.py`:

- **safe** — spawn-equippable. A skill is equippable only if it has a real method body;
  a toolset only if at least one of its tools actually executes ("catalog" entries stay
  visible but cannot be equipped — no decoration).
- **orchestrator** — Arslan-only (browser automation, full code execution, cron, …).
  Spawns can *escalate a need*; Arslan may grant a **temporary** safe capability (expires
  after a few turns) or answer with data. Needs go up; actions never come down.

## What spawns can actually DO (safe tier, wired)

| Toolset | Tools | Notes |
|---|---|---|
| Web Search & Scraping | `web_search`, `web_extract` | Live web via the configured search provider; the fetch resolves each hop once and connects to that pinned address, so a private/internal target is refused and cannot be swapped in afterwards by DNS. **Proxy caveat:** with `HTTPS_PROXY` (or `ALL_PROXY`) set, an **https** fetch cannot be pinned — the CONNECT tunnel would present the pinned IP to the TLS handshake and certificate validation would fail — so pinning is disabled for that combination and the protection is delegated to your proxy. It is logged at WARNING each time, so you can tell which mode an install is in. Plain **http** through a proxy is still pinned. Universal baseline for every spawn. |
| Charting | `render_chart` | 9 chart types → interactive ECharts, backend-built from validated data (the model never authors render config). |
| Deck / PPTX | `render_deck` | Native, editable PowerPoint from a validated slide spec — real shapes + speaker notes, not images. |
| Code Sandbox | `run_python` | Default-deny macOS Seatbelt: runtime read-only, per-call workspace writable, staged references read-only, network denied and no automatic unsandboxed retry. Scrubbed environment and bounded output. Packaged app includes a locked Python/NumPy/Pandas/Matplotlib runtime; source installs may prepare a first-use venv. Recorded outputs persist as authenticated downloads. Can run imported skill scripts (`{"skill_script": "<key>/<file>.py"}`). Unsupported platforms refuse this sandboxed path. |
| Skill Authoring | `create_skill` | Drafts a skill **candidate** only — going live always requires the human promote gate. |
| MCP (`mcp_*`) | user-connected | Any MCP server the user connects and wires; one-click connect list for credential-free official servers. |

## Skills: three sources, one lifecycle

1. **Shipped** — curated methodology skills (adapted from Apache-2.0/MIT sources, attributed
   in `THIRD_PARTY_NOTICES.md`). Injected into the spawn's prompt at dispatch.
2. **Imported** — standard Agent-Skills `SKILL.md` files imported **verbatim** from GitHub
   (Tool-Hub → Import skills). License-gated server-side: permissive licenses only
   (MIT/Apache-2.0/BSD/ISC/Unlicense/CC0); unlicensed or copyleft repos are refused.
   Bundled `scripts/*.py` are stored and runnable inside the sandbox.
3. **Self-authored** — the `create_skill` loop: forge → **observe on real runs** → replay
   evaluation → **human promote** → live → Curator review (unused/underperforming → retire).

**Cold-start note (by design):** the evaluation gate replays **real scored runs** of the
target spawn and needs **≥ 8 samples**. On a fresh install there is no real data yet, so
evaluation reports "insufficient samples" honestly — the human promote gate still works
(you are the gate). We deliberately do not fabricate synthetic evaluations.

## Task execution model

- Spawns run a bounded tool loop (up to 8 tool calls per turn, ~20 s per tool). Long jobs
  can be organized as explicitly started, immutable task recipes with dependencies,
  approvals and 1–4 parallel steps. Completed-step reuse requires explicit resume.
  Child tasks share whole-run request/tool/time/token/output/artifact budgets.
- If the budget runs out mid-task the loop makes a text-only salvage attempt and answers
  honestly with what it has — raw tool-protocol JSON is never shown to the user.
- Spawns do **not** receive arbitrary peer messaging or unrestricted shell access.
  Host command execution remains confirmation-gated and is not a filesystem jail.
  The optional browser panel is an explicit static public-HTTPS preview, not an
  autonomous interactive browser. User-connected MCP servers have their own trust
  boundaries and are not covered by the Python sandbox.

## Provenance discipline

Nothing third-party ships without a verified permissive license (`THIRD_PARTY_NOTICES.md`).
The same gate applies to runtime imports. Web content entering prompts is framed as
untrusted data (`wrap_external`). This is a prompt boundary, not a guarantee against
all prompt injection; tool authorization and execution policy remain necessary.
