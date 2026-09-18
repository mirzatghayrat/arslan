# Open-source research adoption checkpoint

Research reviewed 2026-09-16; implementation direction accepted 2026-09-19.

Retain Arslan's runtime, existing routing, browser, permissions and user data.
No upstream package is installed by this decision. These are candidates, not
measured improvements or release acceptance evidence.

## Order and acceptance gates

1. Task-level evaluation: retain reproducible fixtures, expected outcomes,
   tool traces, failures, elapsed time and whole-task cost. Promptfoo is a
   development-only candidate, not a runtime requirement or security proof.
2. Tool-output projection: learn from OpenSquilla's separation of canonical
   raw evidence and bounded model-visible results. Preserve retrieval handles,
   errors and provenance. Compare task success and total cost before activation.
   Add difficulty routing only in observe-only mode initially; do not replace
   Arslan's existing provider/role routing without comparative evidence.
3. Code semantics: evaluate Serena as optional, initially read-only MCP support.
   Current Serena application is GPL-3.0-or-later; SolidLSP portions are MIT.
   Do not copy the application into the core based on older MIT descriptions.
   Separate processes do not by themselves settle distribution obligations.
4. Document parsing: evaluate Docling on difficult PDF/table fixtures as an
   optional capability. Check model licenses and packaged footprint separately.
5. Browser/sandbox: compare Playwright MCP and sandbox-runtime designs with
   existing boundaries; neither origin filters nor upstream defaults constitute
   Arslan's security acceptance. Do not broaden permissions by adoption.
6. Agent Lightning: defer training infrastructure until reproducible task
   outcomes, reliable rewards, suitable models/data and compute exist. It is
   not a plug-in that trains closed API models automatically.

## Primary research references

- https://github.com/TokenRhythm/opensquilla/blob/main/docs/features/tool-compression.md
- https://github.com/TokenRhythm/opensquilla/blob/main/docs/features/squilla-router.md
- https://github.com/oraios/serena/blob/main/LICENSE
- https://github.com/microsoft/agent-lightning
- https://github.com/promptfoo/promptfoo
- https://github.com/docling-project/docling
- https://github.com/microsoft/playwright-mcp
- https://github.com/anthropics/sandbox-runtime

## Immediate reliability prerequisite

Native onboarding had used origin-local storage only. A new loopback port on
restart could therefore show it again. Persist `first_run_seen` in the existing
backend settings table, restore before deciding visibility, and migrate an
existing local hint. Failed writes retain only a local/session fallback; durable
success is not guaranteed until the backend write succeeds. Native restart
acceptance remains required after rebuilding the candidate.
