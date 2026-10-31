# SBX-M runbook: one sitting on the user's Mac

> ③Hands, 2026-10-31, at ⓪Plan's request. This is how to run the measurement in `docs/plans/0164/SBX-sandbox.md` §M once, in one sitting.
> - **Who runs it** (card, ownership table): the user, or ②Main after reading the corpus. Claude writes the report from the summary, with ids and results only, and a session other than the writer reviews it.
> - **What runs:** the SBX-2 corpus (Codex's, reviewed by Astra), the way `tests/server/sbx/corpus/README.md` says, plus a repeat loop of the listener-refusal gate.
> - **What it adds:** no probe. `scripts/dev/sbx_m.sh` only starts the existing tests and summarizes their JUnit files.

## Before you start (about 2 minutes)

1. **The Mac:** plugged in and on its usual network. The corpus fetches a few small public fixtures over https: a git clone, `pip download` and `npm view`.
2. **A checkout:**
   - main, at or after `dc926523`. That is #570: the builder refuses a port exclusion in the any-declared mode;
   - with its own `.venv`, from `uv sync --frozen --extra dev --extra server --extra ocr`;
   - and no uncommitted changes. The script counts changed files into the summary, so a dirty checkout shows.
3. **No other test suite running** on this Mac. A busy Mac can end slow rows as `timeout`. Tell ⓪Plan before you start so the sessions hold their full runs. The script also counts other pytest processes at the start.
4. **Optional, connect-only** (nothing is sent):
   - `SBX_SSH_AGENT_SOCKET`, `SBX_GPG_AGENT_SOCKET` and `SBX_DOCKER_SOCKET` name your real agent sockets (corpus README).
   - Leave them unset if you like. Unset rows report `not-supplied`.

## Run (one command, from the repository root, in Terminal)

```bash
scripts/dev/sbx_m.sh
```

- The Mac stays awake for the run (`caffeinate -i`), so you can walk away.
- **Options:**
  - `SBX_M_LOOPS=50` for more loop runs (the default is 30);
  - `SBX_M_LOOPS=0` for the corpus only;
  - `SBX_M_CORPUS=0` for the loop only;
  - `SBX_M_OUT=<folder>` to put the results somewhere else. The script refuses a folder inside the repository.
- **To stop:** Ctrl-C. The corpus kills each probe's process group, and its write probes clean up in `finally`. Afterwards, run the whole script again: each run gets a new folder.

## How long

| Part | What | Time |
|---|---|---|
| Preflight | versions, firewall state, other pytest processes | seconds |
| 1/2 corpus | `pytest tests/server/sbx -m sbx_mac`: 293 cases (71 kernel gates, 222 measurement rows) | about 10–20 minutes, not yet measured alone. CI's macOS step ran these plus 69 other cases in about 13 minutes on a VM (run 41171810403). |
| 2/2 loop | `test_sbx2_kernel.py -k listener_refusal`, 3 cases per run, 30 runs | about 3 seconds a run: 85 seconds for 30 runs on this Mac (2026-10-31, at `dc926523`, with other suites running) |

## macOS prompts to expect

**None are expected.** Here is why, and what to do if one appears anyway.

- **"Accept incoming network connections?"**
  - This can appear only while the Application Firewall is on. The preflight prints its state (off on this Mac on 2026-10-31).
  - If it appears, click **Deny** and note it.
- **"Install the command line developer tools?"**
  - The script stops before the run when there are no developer tools.
- **Screen Recording, pasteboard and keychain dialogs:**
  - The corpus never captures the screen or reads the general pasteboard.
  - Its git credential helper asks a nonexistent `.invalid` host, with prompts off (corpus README, "Safety and coverage").
- **A "Background Items Added" notification:**
  - Note the time. It would mean a launch-job write got through.
  - Only the default-deny candidate tries one, a job whose program is `true`. It is removed at once whether or not it was accepted.

The same corpus runs inside every local full-suite run on macOS. `pytest tests/` has no marker filter, so it includes `-m sbx_mac`. The sessions' full runs on this Mac have run it since #507 merged (2026-10-30), but nobody watched the screen during those runs.

## Where the results land

A new folder for each run: `~/Library/Logs/arslan-sbx-m/<UTC time>/`, outside the repository.

| File | What | Leaves this Mac? |
|---|---|---|
| `summary.md` | ids, pytest results, measurement outcomes, probe labels, errnos, return codes, versions, counts | Yes. The report quotes it. |
| `preflight.txt` | commit, macOS version and build, hardware, tool versions, firewall state, timings, exit code | Yes, inside `summary.md` |
| `results.xml` | the corpus's JUnit file, with each row's properties and its `executions` list | **No.** Failure text can hold local paths and service output. |
| `profiles/` | each exact profile text, under its SHA-256 | **No** (corpus README: local paths) |
| `pytest-corpus.txt` | the terminal output, with the "SBX measurements" lines | **No** |
| `loop/NNN.xml`, `loop/NNN.txt` | each loop run's JUnit file and output | **No** |

## What to paste back

At the end, the script prints three lines and the summary's path, for example:

```text
SBX-M at 0123456789ab · macos: 26.6.2 (25G83)
corpus: 293 cases, 293 passed, 0 failed, 0 error, 0 skipped, 0 xfailed; 12 rows need a look
loop (30 runs, passed/ran): any-declared-default-deny 30/30 · port-22-default-deny 30/30 · proxy-default-deny 30/30
summary: …/summary.md  (paste the three lines above; the folder stays on this Mac)
```

Paste those lines into ⓪Plan's session. The sessions run on this Mac, so they read `summary.md` and, for a failure, `results.xml` from the folder themselves.

## Reading the results

- **Corpus:**
  - A kernel gate that failed is a finding.
  - A measurement row can pass as a pytest row and still report `tool-failed`, `timeout`, `tool-unavailable`, `not-supplied` or `boundary-open`. That is not a compatibility or security result (corpus README, "Reading results"). The summary lists each such row under "Rows that need a look", with skips and xfails.
  - A hard-link `boundary-open` needs a follow-up before SBX-3 merges.
- **Loop:**
  - Since #570, the any-declared case asserts that the builder refuses the port exclusion. It is never a kernel run.
  - The proxy and port-22 cases must refuse a test-owned listener on the excluded port, over `127.0.0.1` and over `::ffff:127.0.0.1`, with a fresh ephemeral port each run.
  - Before #570, in any-declared, the compiler dropped that deny for about 7.8% of ports, and `::ffff:127.0.0.1` got past it at every port (⓪Plan's investigation on #507). ③Hands saw it as `assert 0 in (1, 13)`, a connect that went through.
  - A failed proxy or port-22 run is a finding for SBX-2, before SBX-3 wires the base. The summary quotes only that errno assertion. Anything else stays in `loop/NNN.txt`.

## Not measured here (the report keeps these)

- **From the corpus README:**
  - real Arslan listener discovery;
  - the run lifecycle, the boot sweep and post-run background cleanup (SBX-3);
  - the final closed Mail, Messages, Safari and Photos paths (SBX-3);
  - cross-preset cache isolation and link attacks (SBX-5);
  - real proxy forwarding and DNS routing (SBX-6);
  - Xcode GUI builds, QUIC, and an authenticated SSH git remote.
- **§M's listening checks with Codex's rules** (added by #549): a listener on `0.0.0.0` and on `::`, and a connection to the Mac's own LAN address.
  - No corpus probe does these yet. A new kind of probe is Codex's (card, "Harness").
  - The real version is a connection from another machine on the LAN, which needs a second device.
- **One hash per preset:** a profile text holds its test's scratch paths, so its exact hash changes from run to run. `results.xml` keeps each run's hash. Whether the report adds a hash with those paths replaced is the report's decision.
