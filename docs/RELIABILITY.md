# Execution and recovery contracts

## What runs where

| Path | Filesystem | Network | Approval / recovery |
| --- | --- | --- | --- |
| Generated Python | Runtime read-only; per-call workspace read/write; staged references read-only | Denied by macOS Seatbelt | No unsandboxed retry; unsupported platforms refuse |
| Confirmed shell command | Host filesystem permissions, **not** a filesystem jail | Denied or restricted through the credential proxy | Existing per-command confirmation |
| Configured MCP server | Server's own process/environment, **not** covered by Python Seatbelt | Server-specific | Install/connect only trusted servers; existing capability grants |
| Task recipe | Same per-tool boundaries as an ordinary spawn | Same per-tool boundaries | Explicit start, optional step approvals, explicit unfinished-step retry |

Python's production/packaged path ignores `ARSLAN_ALLOW_UNSANDBOXED_PY`.
Source-development use of that escape valve is conspicuously unisolated. A
packaged frozen server is not a Python interpreter; when no usable Python 3.11+
runtime is available, computation refuses with setup guidance.

## Budgets

One live task and its nested/parallel dispatches share these defaults:

| Environment override | Default | Meaning |
| --- | --- | --- |
| `ARSLAN_RUN_MAX_MODEL_REQUESTS` | 32 | Actual provider HTTP attempts, retries included |
| `ARSLAN_RUN_MAX_TOOL_CALLS` | 24 | Tool admission attempts across all child work |
| `ARSLAN_RUN_MAX_WALL_SECONDS` | 600 | Whole-task deadline |
| `ARSLAN_RUN_MAX_TOKENS` | 128000 | Reported/estimated usage gates the **next** request |
| `ARSLAN_RUN_MAX_OUTPUT_TOKENS` | 8192 | Output ceiling sent to the provider per request |
| `ARSLAN_RUN_MAX_ARTIFACT_BYTES` | 104857600 | Cumulative exported artifact bytes |

These are not an exact dollar ceiling. A response already in flight can cross the
token threshold; providers differ in billing/thinking-token semantics. Keep a
provider-side spend limit. Run detail stores the budget snapshot and stop reason.
An explicit recipe resume starts a new budget, while completed steps are reused.

Working-memory and fact injection use deterministic CJK-aware **estimates**, not
vendor tokenizers. Raw source messages remain in storage when context is trimmed.
Oversized facts are skipped whole; they are not cut into potentially misleading
partial statements. Semantic recall quality still requires independent evaluation.

## Durable results and interruption

Recorded Python outputs are copied into the artifact store before workspace
cleanup. Downloads are authenticated attachments with MIME protection. Regular
files only: no symlink export, at most 32 files per call, 50 MiB each, 100 MiB total,
and at most 512 directory entries scanned. Results carry owner Run, size and hash.

Run text is checkpointed periodically (target interval 0.5s, up to 262144 chars).
A crash preserves the last successful checkpoint, not necessarily every last
streamed character. Boot marks orphaned Runs as interrupted. It does **not**
replay tools automatically. Completed host and recipe output remains on the Run;
normal completed spawn output remains in its linked conversation message.

Task recipes have immutable versions, 1–16 steps and 1–4 parallel steps. Each
child has its own Run and durable output. Dependencies receive bounded excerpts
of completed outputs as reference data. They do not receive unrelated spawn-chat
history. Failure stops dependent work and cancels unfinished siblings. Approval
is a workflow gate, not a way to bypass a tool's own permission requirements.

Resume is manual. A step may have changed an external system before interruption
was recorded; retry can repeat that effect. Inspect the step Run before agreeing.
There is no claim of exactly-once delivery to arbitrary external services.

## Backup and restore (source install)

Stop Arslan first. Keep the original encryption secret in a separate safe place.
Do not print it, put it in a shell command, or put it in the archive.

```sh
python -m scripts.backup_data create --data-dir /path/to/Arslan --output /safe/path/arslan-backup.zip
python -m scripts.backup_data restore --archive /safe/path/arslan-backup.zip --new-data-dir /path/to/restored-Arslan
```

If configured separately, supply `--db-path` and/or `--spawns-dir` when creating
the backup. The archive contains a SQLite backup snapshot (salt and ciphertext
together) plus `artifacts`, `spawns`, `skill_scripts`, and `uploads`. It excludes
access tokens, the external secret, rebuildable Python environments, shell
workspace and shell-proxy CA. Preserve any custom workspace separately if needed.

Restore verifies hashes, member paths, size limits and SQLite integrity before
installing a new directory. It does not overwrite or merge existing data. Only
restore trusted archives: checksums detect corruption, not a malicious author.

After restoring, keep the app stopped until the **same original secret** and the
new data location are configured. Source installs may set `ARSLAN_DATA_DIR`;
packaged apps deliberately use their fixed platform directory, so keep the old
directory as a rollback copy and move the verified restore into that location
only while the app is fully closed. Boot can then apply any pending migrations.
Verify notes, a known provider credential and an artifact before discarding the
old directory. No automatic in-place restore endpoint is exposed over HTTP.

## Optional static webpage preview

The browser button opens an explicitly initiated preview, not an autonomous
browser agent. Setup downloads Playwright MCP **0.0.80** with an npm integrity
lock and its matching Chromium Headless Shell revision. Node.js 18+ is an
external prerequisite. No model API calls or signed-in browser profiles are used.

Page scripts, service workers, website downloads, QUIC, and proxy bypasses are
disabled. Only navigation, accessibility snapshots and viewport screenshots are
exposed internally. Public HTTPS page resources pass through a per-visit CONNECT
proxy that validates every DNS answer and connects to a pinned public IP, on port
443 only. TLS remains end-to-end, with certificate validation enabled. Limits:
45 seconds overall, 32 connections and 50 MiB of tunnel traffic per visit.

Chromium's renderer sandbox stays enabled. **This is not kernel-enforced egress
or filesystem isolation for the trusted Node/Chromium parent processes.** macOS
rejected nested Chromium sandbox initialization under an outer Seatbelt profile;
we did not work around that by disabling the renderer sandbox. Full scripted
browser automation is deferred. Script-dependent websites may look incomplete.
Failed previews remain failed Runs, and saved output is accessible through the
existing authenticated artifact downloads. Stop uses the shared Run registry.

Source contracts checked against the pinned package and the official
[Playwright MCP documentation](https://github.com/microsoft/playwright-mcp).
Generic user-configured MCP servers are separate from this preview and do not
inherit its restrictions. The generic preset now pins the same MCP version;
`browser_tabs` requires approval because it can create and close tabs.

## Verification boundary

Transport mocks and synthetic task tests verify control flow, isolation,
artifacts, cancellation, versioning and recovery. They do not establish real
model task success, voice-device performance or judge accuracy. See the dated
implementation log for measured test runs; do not infer an 8/10 product score
from passing unit tests alone.
