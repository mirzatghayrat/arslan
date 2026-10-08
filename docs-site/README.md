# Docs source (aralem.dev/arslan/docs/)

The technical docs are built from this folder.

| Language | Built to | Served at |
|---|---|---|
| English (default) | `docs/docs/index.html` | https://aralem.dev/arslan/docs/ |
| Chinese | `docs/docs/zh/index.html` | https://aralem.dev/arslan/docs/zh/ |

```bash
python3 docs-site/build.py
```

| Path | What it is |
|---|---|
| `sections/<lang>/NN-*.html` | One chapter each, as an HTML fragment. Every language has the same files, section ids and links; the build refuses a mismatch. `{{source:path\|label}}` becomes a GitHub link pinned to the baseline commit. |
| `baseline.json` | The release the text was checked against: version, commit, check date, and the hero stats for each language. |
| `data/versions.json`, `data/prereleases.json` | Release data. Chapter 16 holds the rendered version table in each language. |
| `build.py` | The page shell, the styles that match the project site, the per-language page text (`LANGS`) and the language switch. It also recolours the chapters' light diagrams for the dark page. |

## When a release ships

1. Add the new version to chapter 16 in every language, as a row in `#version-table`. The build puts the newest row on top.
2. Update the chapters whose behaviour changed, in every language. Write what shipped, and mark anything after the release as later.
3. Every claim must be checked against the released code. Open the file you link; do not copy from release notes alone.
4. Set `baseline.json` to the new version, commit and date.
5. Run `python3 docs-site/build.py`. It warns when `baseline.json` lags `desktop/src-tauri/tauri.conf.json` (between a version bump on main and its release, that warning is expected).

## Adding a language

1. Copy `sections/en/` to `sections/<lang>/` and translate it. Keep every id, `{{source:}}` path and link.
2. Add an entry to `LANGS` in `build.py`, and the hero stats to `baseline.json`.
3. Rebuild. The language switch and the `hreflang` links pick it up.

## History

- Drafted in Chinese by Codex on 2026-10-07 (17 chapters, baseline v0.1.53).
- Audited claim by claim against `efc1c271` and restyled to match the site on 2026-10-08.
- Translated to English on 2026-10-08; English became the default.
- Updated to v0.1.54 (`ebf438dc`) on 2026-10-08: terminal gate, Bridge pairing/Touch ID, delivery evidence, version row.
- Six languages on 2026-10-08: German, Japanese, Spanish and Turkish from Codex's translations of the 2026-10-07 Chinese draft, with every block that the audit or 0.1.54 changed retranslated from the current English (structure checked against `sections/en/`). The language switch became a menu.
- Updated to v0.1.55 (`81c0028c`) on 2026-10-08 in all six languages: one queue / Inbox / Island answers, learning rules, capability switches, delivery evidence, version row.
- Updated to v0.1.56 (`e1313003`) on 2026-10-09 in all six languages: projects (board, levels, evidence), Hands at-most-once, delivery evidence, version row.
