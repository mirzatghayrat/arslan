# Incident 2026-10-24: a review probe read the dev secret key

**Summary.** During ②Main's first independent review of #394 (C11b), one probe script read the real secret key file (`~/.arslan/secret_key`) into its own process memory. The key was compared, never printed. It is in no transcript, log or file, and nothing that uploads carried it. Rotating it is not required; that stays the user's call.

## What happened

- **When:** 2026-10-23 17:19 UTC (01:19 on 10-24 Beijing time), the first probe of the effort=max review of #394 at `b3c9cc46`.
- **What ran:** a probe script started with `.venv/bin/python`, outside pytest. It set an explicit fake `ARSLAN_SECRET_KEY` and imported `server.main`. It did not set `ARSLAN_SECRET_KEY_FILE=""` and it ran with the real `HOME`.
- **Why that read the file:** when an explicit key is set, the secret bootstrap (`server/secret_bootstrap.py`) compares it with the persisted secret file, which defaults to `~/.arslan/secret_key` under `HOME`. It warns when they differ. The warning names only the path: "ARSLAN_SECRET_KEY is set explicitly and differs from the persisted secret at …; the explicit value wins." So the file's contents were read into that one process to be compared, and nothing else was done with them.
- **The key:** the secret that encrypts stored provider API keys in Arslan's data folder and backups.
- **A second slip, which read nothing real:** in the re-check (round 2), a zsh quoting mistake left `ARSLAN_SECRET_KEY_FILE` unset for two probes. `HOME` still pointed at a scratch folder, so the real `~/.arslan` was never resolved. The config generated a throwaway secret inside the scratch folder, which was deleted.
- **The test suite was never exposed.** Its conftest pins `ARSLAN_SECRET_KEY_FILE=""` and a HOME of its own before the server's config, which runs the secret bootstrap, is first imported. (One product module, `server.profile_paths`, is imported just before the HOME pin; it reads no secret.) No suite log of this round contains the warning.

## How we confirmed the value went nowhere

- A separate process read the key file and searched 244,210 files for the key's text and for its raw bytes. It printed only counts. **0 files contained either.** The files searched:
  - every Claude Code session and subagent transcript of this project, which is what the model receives;
  - the session's scratch folder: probe scripts, their logs and outputs, and the bench copies;
  - the coordination worktrees, without `.venv`, `node_modules` and `.git`.
- The probe's output, which went into the reviewer's transcript, held only the warning text with the path.
- The comparison is local. The probe made no provider or network call that could carry the key.
- The review comments posted to GitHub (#394) contain no key material.

**Could it have reached anything that uploads?** No. The model's context is the transcripts, which don't contain it. The probe made no network call with it. Nothing else read it.

## Cause

Probes that run product code outside pytest get none of conftest's protections. The review brief told the reviewer to use fake tokens and a scratch HOME, but the first probe was written before that environment was set up. After the disclosure, ⓪Plan made it a rule that every probe sets `ARSLAN_SECRET_KEY_FILE=""` and a scratch HOME from the first run.

## Fixes (this PR)

- **Inside the suite** (`tests/real_data_dir_guard.py: forbid_real_secret_folder`, installed at the top of `tests/conftest.py`), on top of the existing `ARSLAN_SECRET_KEY_FILE=""` and HOME pins:
  - an audit hook refuses any open of the real `~/.arslan`, or of anything under it, in every test process. Paths are compared after resolving links (the folder's own and the opened path's) and `..`, and, on macOS, in any letter case;
  - the refusal is a `PermissionError`, which the code under test may catch (the secret bootstrap catches `OSError`), so every refusal is recorded and fails the test it happened in;
  - **not covered:** child processes (a `cat` of the file runs outside the hook), a relative path opened against a directory descriptor, and a descriptor opened before the hook was installed. The guard's docstring lists these. It is a net under the pins, not a sandbox.
- **For probes outside the suite:** run them through `scripts/dev/probe.sh`. It gives them:
  - an empty environment plus `PATH`, `TMPDIR`, `LANG`, `TERM`, `USER` and `LOGNAME`, so no token, key, `ARSLAN_*` or `PYTHON*` variable of the calling shell reaches them;
  - a scratch HOME and data folder;
  - `ARSLAN_SECRET_KEY_FILE=""` and a fake key;
  - and it refuses a scratch folder that is the real home or inside the real `~/.arslan`. The check runs after resolving links, `..`, missing folders and a trailing slash, in any letter case, and before anything is created.
  - It does not limit what the probe itself reads by an absolute path or starts.
- **Tests:** `tests/test_real_secret_guard.py`. None of them touches the real `~/.arslan`: the hook's cases run in a child pytest session whose home is a temp folder, and the runner's against a fake home.
  - The suite reads no secret file and has its own HOME.
  - An open under the real secret folder is refused and recorded, while a look-alike path is not.
  - Links (the folder itself a link, another link into it), `..` through a missing folder, a trailing slash, and on macOS another letter case are all refused.
  - A refusal the code swallows (the secret bootstrap's own read) still fails the test.
  - The probe runner refuses the home and the secret folder however they are spelt, whether or not `~/.arslan` exists or is a link, and creates nothing when it refuses.
  - The probe runner passes on no variable of the calling shell beyond its allowlist (fake `ARSLAN_*`, `GH_TOKEN`, `OPENAI_API_KEY` and `PYTHON*` values are passed in to check). It gives a script a scratch HOME, no secret file and a fake key, and lets it import `server`. It defaults to a fresh temporary scratch folder.
  - Mutations: removing any of the runner's checks (physical resolution, `env -i`, `PYTHONPATH`, case fold, the resolved secret folder) or the hook's (resolving the opened path, resolving the folder, case fold, recording), or the conftest's install or teardown check, fails a test.
- **Process (⓪Plan):** review briefs say to run every probe through `scripts/dev/probe.sh`, or as a pytest test. `docs/sessions.md` can carry that rule.
