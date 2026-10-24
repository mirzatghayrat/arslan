# Incident 2026-10-24: a review probe read the dev secret key

**Summary.** During ②Main's first independent review of #394 (C11b), one probe script read the real secret key file (`~/.arslan/secret_key`) into its own process memory. The key was compared, never printed. It is in no transcript, log or file, and nothing that uploads carried it. Rotating it is not required; that stays the user's call.

## What happened

- **When:** 2026-10-23 17:19 UTC (01:19 on 10-24 Beijing time), the first probe of the effort=max review of #394 at `b3c9cc46`.
- **What ran:** a probe script started with `.venv/bin/python`, outside pytest. It set an explicit fake `ARSLAN_SECRET_KEY` and imported `server.main`. It did not set `ARSLAN_SECRET_KEY_FILE=""` and it ran with the real `HOME`.
- **Why that read the file:** when an explicit key is set, the secret bootstrap (`server/secret_bootstrap.py`) compares it with the persisted secret file, which defaults to `~/.arslan/secret_key` under `HOME`. It warns when they differ. The warning names only the path: "ARSLAN_SECRET_KEY is set explicitly and differs from the persisted secret at …; the explicit value wins." So the file's contents were read into that one process to be compared, and nothing else was done with them.
- **The key:** the secret that encrypts stored provider API keys in Arslan's data folder and backups.
- **A second slip, which read nothing real:** in the re-check (round 2), a zsh quoting mistake left `ARSLAN_SECRET_KEY_FILE` unset for two probes. `HOME` still pointed at a scratch folder, so the real `~/.arslan` was never resolved. The config generated a throwaway secret inside the scratch folder, which was deleted.
- **The test suite was never exposed.** Its conftest pins `ARSLAN_SECRET_KEY_FILE=""` and a HOME of its own before any product module is imported. No suite log of this round contains the warning.

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

- **Inside the suite** (`tests/real_data_dir_guard.py: forbid_real_secret_folder`, installed at the top of `tests/conftest.py`): an audit hook makes any open under the real `~/.arslan` fail for the whole test run, whatever the code under test does. This is on top of the existing `ARSLAN_SECRET_KEY_FILE=""` and HOME pins.
- **For probes outside the suite:** run them through `scripts/dev/probe.sh`. It gives them:
  - a scratch HOME and data folder;
  - `ARSLAN_SECRET_KEY_FILE=""` and a fake key;
  - no inherited `ARSLAN_*` variables;
  - and it refuses a scratch folder inside the real `~/.arslan`.
- **Tests:** `tests/test_real_secret_guard.py`.
  - The suite reads no secret file and has its own HOME.
  - An open under the real secret folder is refused, while a look-alike path is not.
  - The probe runner gives a script a scratch HOME, no secret file and a fake key; it refuses a scratch folder inside `~/.arslan`; and it defaults to a fresh temporary scratch folder.
  - Removing the guard, or the runner's empty secret-file setting, fails a test.
- **Process (⓪Plan):** review briefs say to run every probe through `scripts/dev/probe.sh`, or as a pytest test. `docs/sessions.md` can carry that rule.
