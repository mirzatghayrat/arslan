# Third-Party Notices

Arslan bundles skill/persona content that originates from third-party open-source
projects. Each retains its original license; this file provides the attribution those
licenses require. Where a file was adapted (not copied verbatim), the change is noted in
that file's `source:` frontmatter, and the significant-change requirement of Apache-2.0
is satisfied here + there.

Verified licenses are recorded below with the date verified. **Nothing from a source is
bundled until its license is verified and permits redistribution.**

### On the skills marked `authors: Arslan`

A `SKILL.md` without a `source:` line was written for this repository. That claim is about
**the text of the file**, nothing more: the methods and tools a skill names belong to their
owners. If you recognise your work in a skill that carries no `source:` line, open an issue,
and the attribution will be added.

---

## Skills — `arslan/skills/bundled/<skill>/SKILL.md`

Since v0.1.63 (C9) Arslan ships two skills; the others it used to bundle were retired, with
their sources' notices. A user's own and imported skills keep their own licences
(`skill_import` checks each at install).

- `designed-html-report`: `authors: Arslan`, written for this repository.
- `skill-creator`: **adapted** from anthropics/skills (below).

### anthropics/skills — Apache License 2.0 (re-verified 2026-10-21)
- Copyright 2026 Anthropic, PBC. <https://github.com/anthropics/skills>
- The repository has **no top-level LICENSE**; each skill carries its own `LICENSE.txt`, and
  the document skills `docx`, `pdf`, `pptx`, `xlsx` are source-available, not open source
  (the repository README). `skills/skill-creator/LICENSE.txt` is Apache-2.0, checked at commit
  `dbd4588f9e1033efb41dad4bef2f7947c8993d44` (2026-10-21).
- `skill-creator` is **adapted** (the user's decision, 2026-10-21: Arslan's adaptation stays):
  shortened and translated; Anthropic's version depends on Claude Code's eval tooling (`claude -p`,
  sub-agents, an eval viewer, scripts), which was removed, and only the methodology was ported to
  Arslan's SKILL.md format.
- Apache-2.0 §4, as met here:
  - the licence text ships beside the skill, as `arslan/skills/bundled/skill-creator/LICENSE.txt`
    (upstream's file, byte for byte, at the commit above);
  - the changed file says so at the top of its body, with source and commit;
  - this notice keeps upstream's copyright line.

---

## Persona seeds — the 249-persona library

### msitarzewski/agency-agents — MIT License (verified 2026-07-01)
- Copyright (c) msitarzewski. <https://github.com/msitarzewski/agency-agents>
- Source recorded in the DB as `agency-agents@<commit>`. MIT requires retaining the copyright +
  permission notice — the same MIT text reproduced above (obra/superpowers) applies.
- Used as the persona-seed library (identity references composed into spawns; curation-only —
  imported into the `persona_seeds` table, never redistributed as standalone files).

---

## Bundled computation runtime (desktop 0.1.38+)

The desktop build stages uv-managed standalone CPython and the lockfile-resolved
`sandbox` dependency group (NumPy, pandas, Matplotlib and their dependencies).
The runtime is copied without stripping its `lib/python3.11/LICENSE.txt`, wheel
`*.dist-info` license files, or bundled font notices. These notices travel inside
`Contents/Resources/sidecar/python_runtime` with the binaries they describe.
Exact distributions and hashes are recorded in `uv.lock`; the source staging
procedure is `packaging/stage_python_runtime.py`.

Optional webpage preview installs the separately integrity-locked Playwright MCP
and Chromium Headless Shell runtime only after the user requests setup. It is not
copied into the desktop bundle. The installation retains upstream package and
browser notices; see `server/resources/browser_runtime/package-lock.json`.

---

## Capability catalog — `server/registry/seed_catalog.py`

### NousResearch/hermes-agent — MIT License
- <https://github.com/NousResearch/hermes-agent>, Copyright (c) 2025 Nous Research; the license
  text is in the next section.
- The capability catalog (`server/registry/seed_catalog.py`) began as Hermes' toolset catalog.
  Checked against `toolsets.py` and `website/docs/reference/toolsets-reference.md` at commit
  `f1d62772923e06faa5fbbaf4fa0b0589dbd75577` (2026-10-21, C9): what remains is shared tool
  names (`read_file`, `write_file`, `patch`, `search_files`, `session_search`, `skills_list`,
  `skill_view`, `skill_manage`, `todo`, `web_search`, `web_extract`) and how some of them are
  grouped. The toolset names and every description are Arslan's own wording.
- 0.1.48–0.1.63 vendored Hermes' `tools/approval_detection.py` and `ansi_strip.py` under
  `arslan/vendor/hermes/`. 0.1.63 replaced them with Arslan's own `shell_text.py` (S2b-1) and
  removed the copy (S2b-2).

## Terminal command reading — `server/services/shell_text.py` (0.1.63+)

### NousResearch/hermes-agent — MIT License (verified at the source 2026-10-22)
- `server/services/shell_text.py` is adapted from Hermes Agent's `tools/approval_detection.py`
  and `tools/ansi_strip.py` at commit `6b2fe92af66a95ea6a5caa309e05c5643cdd79de`: the quote-aware
  shell scanner, command starts and command words, `-c` and program-option payloads, quote and
  grep-pattern masks, and command-word deobfuscation. The hard floor in
  `server/services/terminal_policy.py` (layer ①) is adapted from the same file's hardline rules.
- The vendored copy (`arslan/vendor/hermes/`) was removed in 0.1.63; this notice stays.

```
MIT License

Copyright (c) 2025 Nous Research

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

## Arslan Hands — `Arslan.app/Contents/Resources/hands/` (desktop 0.1.53+)

### lahfir/agent-desktop — Apache License 2.0 (verified 2026-10-03)
- <https://github.com/lahfir/agent-desktop>, Copyright its authors. The LICENSE file was
  read at the source (tag `v0.9.4`, commit `a4a695fdd1f673426579696c7e17074910e799fc`; read again
  unchanged at upstream main `9d7ba42a94bc4ec018e624f3033602188f64af63`, 2026-10-09):
  the Apache License, Version 2.0, unmodified. Upstream ships no NOTICE file.
- Built from our fork `mirzatghayrat/agent-desktop` at the commit pinned in
  `packaging/hands/agent-desktop.pin`: upstream main `9d7ba42a` (v0.9.4 plus four commits), plus
  commits that vendor its dependencies, plus **one change by Arslan** (2026-10-10: a complete app
  inventory leaves out an application whose process is gone). The fork's `ARSLAN-FORK.md` lists
  it, each changed file says so in its first lines (Apache-2.0 §4(b)), and the bundled `NOTICE`
  says the build carries Arslan's changes. The binary ships beside the helper, as `hands/agent-desktop` next
  to `hands/Arslan Hands.app` in Arslan.app's Resources; its LICENSE ships in the helper as
  `Arslan Hands.app/Contents/Resources/LICENSE-agent-desktop`, with a `NOTICE`.
- Its Rust dependencies (62 crates, vendored in the fork) are MIT, Apache-2.0, MIT OR
  Apache-2.0, Unlicense OR MIT, or include Unicode-3.0; `cargo deny check` (licenses,
  bans, sources, advisories) gates every CI run and therefore every release.
- Arslan's own helper `arslan-hands` (`desktop/hands/`) depends only on serde, serde_json
  and libc (MIT OR Apache-2.0).
