# DEP1: no open critical or high runtime dependency alert at the v0.1.64 tag

| | |
|---|---|
| Grade | **Release gate** for v0.1.64 (proposed by ④参谋 on 2026-11-02, carded by ⓪Plan). |
| Lane | ②Main, in parallel and off the SBX path. One PR per ecosystem. |
| Review | Product code: another session's review at high, then the author self-merges under #644. |
| Gate | At the v0.1.64 tag, no open Dependabot alert of severity critical or high on a **runtime** dependency. Development-only alerts are listed in the release notes' internal checklist, not fixed by force. |

## Why

A push printed "116 vulnerabilities". GitHub's Dependabot alerts on main (read 2026-11-02 through the API) show 8 critical, 52 high, 48 medium and 8 low. Arslan opens images and PDFs from outside (attachments, web pages, the reader), so Pillow and pypdf sit on the attack surface, not behind it.

## Raw material (main 260b90a7)

Critical and high alerts, grouped by package. "Locked" is the version in the lock file; "fixed" is the highest first-patched version among that package's alerts.

| Ecosystem | Package | Scope | Alerts | Locked | Fixed | Major bump? |
|---|---|---|---|---|---|---|
| pip (`uv.lock`) | Pillow | runtime | 5 critical, 23 high | 12.3.0 | 13.0.0 | yes |
| pip | pypdf | runtime | 13 high | 6.18.1 | 6.21.4 | no |
| pip | PyJWT | runtime | 1 critical, 6 high | 2.13.0 | 2.14.0 | no |
| pip | certifi | runtime | 1 critical | 2026.6.17 | 2026.10.18 | no |
| pip | urllib3 | runtime | 2 high | 2.7.0 | 2.8.0 | no |
| pip | filelock | runtime | 1 high | 3.29.7 | 4.2.1 | yes |
| cargo (`desktop/src-tauri/Cargo.lock`) | zip | runtime | 1 critical, 1 high | 4.6.1 | 9.0.5 | yes; likely transitive |
| npm (`web/package-lock.json`) | vite | runtime | 1 high | (lock) | 6.4.4 | check |
| npm | source-map-js | runtime | 1 high | (lock) | 1.2.2 | check |
| npm | undici | development | 4 high | (lock) | 7.30.1 | dev only: record |

Alerts named `pillow` and `Pillow` (and `pyjwt` and `PyJWT`) are the same package; Dependabot files them under both spellings.

## Reference

- **Mainstream practice:** Dependabot or Renovate grouped updates per ecosystem, with full CI on each; a release gate on open critical and high runtime alerts is common in projects that ship desktop apps (an installed app can't be patched server-side).
- **Arslan's own rules:** a dependency's license is checked at the source, as for any new dependency; CI syncs with `uv sync --frozen`, so the lock file is what ships.

## Method

1. **One PR per ecosystem:** Python (`uv lock --upgrade-package` for each named package), Rust (`cargo update -p zip`, or bump the direct dependency that pulls it in), npm (`npm update` for the named packages, then `npm audit` for what's left).
2. **Major bumps** (Pillow 13, filelock 4, zip 9): read the changelog for removed APIs Arslan uses, and grep the call sites. Re-check the license at the source and note it in the PR.
3. **Tests:** full CI. Plus a real-Mac smoke test of OCR, PDF reading and attachments (images and PDFs in chat), since those paths use Pillow and pypdf, and the updater and file paths for the Rust side.
4. **If a fixed version doesn't exist yet,** or the bump breaks something that can't be fixed in this release, list the alert with the reason and ask the user. The gate doesn't pass silently.

## External evidence

- CI ids for each PR.
- The Dependabot alert list read again after the merges, showing no open critical or high runtime alert (the same API query as above).
- The real-Mac smoke test result (OCR, PDF, attachments).

## Size

Three PRs, mostly lock-file changes, plus any call-site fixes the major bumps need.
