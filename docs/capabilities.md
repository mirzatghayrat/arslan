# Arslan capabilities — the honest map

This document states exactly what spawns (Arslan's specialist agents) can and cannot do,
and where every boundary is enforced. It is kept deliberately honest: **everything listed
as equippable works; everything gated says so.**

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
| Web Search & Scraping | `web_search`, `web_extract` | Live web via the configured search provider; the fetch resolves each hop once and connects to that pinned address, so a private/internal target is refused and cannot be swapped in afterwards by DNS. **If you configure an HTTP proxy, the connection is made by the proxy and this guarantee is delegated to it.** Universal baseline for every spawn. |
| Charting | `render_chart` | 9 chart types → interactive ECharts, backend-built from validated data (the model never authors render config). |
| Deck / PPTX | `render_deck` | Native, editable PowerPoint from a validated slide spec — real shapes + speaker notes, not images. |
| Code Sandbox | `run_python` | Local sandboxed Python: ephemeral tmpdir, fully scrubbed env (no keys), CPU/memory/output caps, **network denied** (macOS seatbelt; the result reports `network_isolated` honestly). numpy/pandas/matplotlib preinstalled (lazy first-use venv, ~200 MB disk). Can also run scripts bundled with imported skills (`{"skill_script": "<key>/<file>.py"}`). |
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
  are decomposed by Arslan (the orchestrator), not by unbounded spawn autonomy.
- If the budget runs out mid-task the loop makes a text-only salvage attempt and answers
  honestly with what it has — raw tool-protocol JSON is never shown to the user.
- Spawns do **not** browse the web interactively, execute shell commands, or message each
  other. Full `code_execution` remains orchestrator-tier and un-wired for now (roadmap).

## Provenance discipline

Nothing third-party ships without a verified permissive license (`THIRD_PARTY_NOTICES.md`).
The same gate applies to runtime imports. Web content entering prompts is framed as
untrusted data (`wrap_external`) — instructions found inside it are never followed.
