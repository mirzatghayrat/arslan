# Docs source (aralem.dev/arslan/docs/)

The technical docs are built from this folder into `docs/docs/index.html`. GitHub Pages then serves the result at https://aralem.dev/arslan/docs/.

```bash
python3 docs-site/build.py
```

| Path | What it is |
|---|---|
| `sections/NN-*.html` | One chapter each, as an HTML fragment (Chinese). `{{source:path\|label}}` becomes a GitHub link pinned to the baseline commit. |
| `baseline.json` | The release the text was checked against: version, commit, check date, and the hero stats. |
| `data/versions.json`, `data/prereleases.json` | Release data. Chapter 16 holds the rendered version table. |
| `build.py` | The page shell and styles, matching the project site. It also recolours the chapters' light diagrams for the dark page. |

## When a release ships

1. Add the new version to chapter 16 (`sections/16-versions.html`), as a row in `#version-table`. The build puts the newest row on top.
2. Update the chapters whose behaviour changed. Write what shipped, and mark anything after the release as later.
3. Every claim must be checked against the released code. Open the file you link; do not copy from release notes alone.
4. Set `baseline.json` to the new version, commit and date.
5. Run `python3 docs-site/build.py`. It warns when `baseline.json` lags `desktop/src-tauri/tauri.conf.json`.

## History

- Content was drafted by Codex on 2026-10-07 (17 chapters, baseline v0.1.53).
- It was audited claim by claim against `efc1c271` and restyled to match the site on 2026-10-08.
- The English edition is pending.
