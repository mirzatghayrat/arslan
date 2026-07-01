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
- Adapted/used from this source:
  - `skill-creator` — **adapted** (Anthropic's version depends on Claude-Code-specific eval
    tooling/scripts; only the methodology was ported to Arslan's SKILL.md format).

### obra/superpowers — MIT License (verified 2026-07-01)
- Copyright (c) 2025 Jesse Vincent. <https://github.com/obra/superpowers>
- MIT requires retaining the copyright + permission notice (reproduced below).
- Used/adapted from this source:
  - _(pending ingestion — will be listed as skills are copied)_

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
