# Third-Party Notices

Arslan bundles skill/persona content that originates from third-party open-source
projects. Each retains its original license; this file provides the attribution those
licenses require. Where a file was adapted (not copied verbatim), the change is noted in
that file's `source:` frontmatter, and the significant-change requirement of Apache-2.0
is satisfied here + there.

Verified licenses are recorded below with the date verified. **Nothing from a source is
bundled until its license is verified and permits redistribution.**

---

## Skills — `arslan/spawn/seeds/<skill>/SKILL.md`

### anthropics/skills — Apache License 2.0 (verified 2026-07-01)
- Copyright 2025 Anthropic, PBC. <https://github.com/anthropics/skills>
- The repository has **no top-level LICENSE**; each skill carries its own `LICENSE.txt`.
  The **document skills `docx`, `pdf`, `pptx`, `xlsx` are source-available (proprietary),
  NOT open source, and are NOT bundled here.** Only skills whose own `LICENSE.txt` is
  Apache-2.0 are used.
- Apache-2.0 requires: retain this notice; state significant changes (done per-file via
  `source:` frontmatter).
- **`doc-coauthoring` was NOT ingested**: its directory in `anthropics/skills` carries no
  `LICENSE.txt`, so its per-skill license could not be confirmed (the repo has no top-level
  LICENSE). Skipped pending license verification.
- Adapted/used from this source (each verified Apache-2.0 via its own `skills/<name>/LICENSE.txt`
  on 2026-07-01):
  - `skill-creator` — **adapted** (Anthropic's version depends on Claude-Code-specific eval
    tooling/scripts; only the methodology was ported to Arslan's SKILL.md format).
  - `brand-guidelines` — **adapted** (pptx font/color post-processing tooling removed; brand
    palette + typography methodology kept).
  - `internal-comms` — **adapted** (bundled `examples/` guideline files removed; comms-type
    methodology kept).
  - `frontend-design` — **adapted** (methodology copied faithfully into Arslan's SKILL.md
    structure; no bundled tooling in the source).
  - `theme-factory` — **adapted** (bundled `theme-showcase.pdf` and `themes/` preset files
    removed; theming + on-the-fly-theme methodology kept).
  - `canvas-design` — **adapted** (bundled `.pdf`/`.png` rendering pipeline and `canvas-fonts`
    assets removed; design-philosophy methodology kept).
  - `algorithmic-art` — **adapted** (bundled `templates/viewer.html` + generator scaffolding
    removed; algorithmic-philosophy + seeded-randomness methodology kept).
  - `mcp-builder` — **adapted** (bundled `reference/` guides and `scripts/` removed; the
    four-phase MCP design + evaluation methodology kept).
  - `webapp-testing` — **adapted** (bundled `scripts/with_server.py` and example scripts
    removed; the reconnaissance-then-action Playwright methodology kept — methodology only,
    since Arslan spawns do not execute scripts).

### obra/superpowers — MIT License (verified 2026-07-01)
- Copyright (c) 2025 Jesse Vincent. <https://github.com/obra/superpowers>
- MIT requires retaining the copyright + permission notice (reproduced below).
- Used/adapted from this source (methodology ported to Arslan's SKILL.md format; the source
  SKILL.md prose was rewritten/condensed into Arslan's `## Trigger` + `## 决策规则` structure,
  so all are marked **adapted**):
  - `brainstorming` — **adapted** (idea→design exploration; approval-gated implementation).
  - `test-driven-development` — **adapted** (RED-GREEN-REFACTOR; iron law + rationalization
    counters). Backfills the existing `test-driven-development` catalog entry's body.
  - `requesting-code-review` — **adapted** (request review with clean work-product context;
    severity-based action). Backfills the existing `requesting-code-review` catalog entry's body.
  - `receiving-code-review` — **adapted** (verify-before-implement; no performative agreement).
  - `verification-before-completion` — **adapted** (evidence-before-claims verification gate).
  - `writing-skills` — **adapted** (TDD-for-skills authoring/verification method).
  - `finishing-a-development-branch` — **adapted** (verify tests → 4 options → execute + cleanup).

```
MIT License

Copyright (c) 2025 Jesse Vincent

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## Persona seeds — `arslan/spawn/seeds/<persona>` (the 249-persona library)

- Source recorded in the DB as `agency-agents@<commit>`.
- **⚠️ LICENSE VERIFICATION PENDING** — the persona-seed library must have its source
  repo's license verified (permits redistribution + attribution terms) before public
  release, exactly as was done for the skills above. Tracked as an open pre-open-source item.
