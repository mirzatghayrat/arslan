# Reliability implementation — 2026-09-14

Baseline: `19f307720c9ffb00df04a591781a2be8a1f94dc1` / v0.1.37.
Branch: `codex/reliability-2026-09-14`.

The maintainer authorized implementation, push, and version updates. Paid model
evaluation has not been authorized. Use synthetic data and isolated test storage.
An 8/10 target is an acceptance goal, not a claim of achieved quality.

## Order and acceptance tracking

| ID | Work | State |
| --- | --- | --- |
| P0-01 | No automatic unsandboxed retry | Implemented; 19 targeted tests passed, full regression pending |
| P0-02 | Filesystem isolation | Implemented for Python; native kernel-denial tests passed, full regression pending |
| P1-01 | Startup/authentication boundary | Connection-level HTTP/WS guard implemented; 31 auth tests pass |
| P1-02 | Accurate safety documentation and release | README/SECURITY contracts corrected; release gates pending |
| P1-03 | Unified host/spawn Run, cancellation, events | Host Run lifecycle implemented; targeted storage/cancel/reconnect/accounting tests pass |
| P1-04 | Persistent downloadable artifacts | Python Run outputs persisted with safe export, metadata and authenticated downloads; targeted tests pass |
| P1-05 | Shared execution budget | Shared request/tool/time/token/output/artifact limits implemented; targeted tests pass |
| P1-06 | Provider contract verification | Gemini native tool/continuation gap implemented and mock-wire roundtrip verified; live calls pending budget |
| P1-07 | Recovery and backup acceptance | Periodic partial-output checkpoints and new-directory validated restore implemented; synthetic roundtrip tests pass |
| P1-08 | End-to-end task benchmark | Pending; paid calls need budget |
| P2-01 | Memory quality, context budgets, scale | Deterministic CJK-aware summary/history/facts caps tested; recall-quality/scale evaluation pending |
| P2-02 | Evolution evidence and judge calibration | Pending; live evidence required |
| P2-03 | Capability/version/provenance documentation | Pending |
| P2-04 | Dependency and test infrastructure | pypdf and frontend advisory fixes applied; npm audit zero; final regression pending |
| P2-05 | Behavior-oriented module boundaries | Pending |
| P2-06 | Loading, empty states, steps and artifacts UI | Pending |
| P2-07 | Voice and native desktop acceptance | Pending; physical checks explicit |
| P3-01 | Versioned recipes and bounded collaboration | Immutable versions, dependency execution, 1–4 parallel steps, approval/resume API and six-language editor implemented; behavior tests pass |
| P3-02 | Controlled browser workflow (selected first) | Static preview implemented and UI-verified; full interactive browser deferred, no kernel egress claim |

## Verification log

- Baseline audit: 3912 backend tests and 1669 frontend tests passed on the same
  commit, recorded separately on 2026-09-13. This is not post-change evidence.
- P0-01 adds behavior tests for attacker-controlled stderr and for a backend
  claiming availability but returning no execution wrapper.
- P0-01 targeted suite: 19 passed, 1 non-macOS-path skip on macOS; Ruff and
  whitespace checks passed. This does not resolve the separate filesystem issue.

Do not mark an item complete solely because code exists or a mocked test passes.
Release only the verified scope and clearly identify unverified features.

- P0-02: Python now uses default-deny Seatbelt rules (read-only interpreter libraries,
  read/write per-run workspace, read-only staged references, no network or host IPC).
  Command execution remains a distinct confirmation-gated, network-only policy.
- Real macOS tests deny external canary read/write/unlink/chmod, symlink access,
  child-interpreter access, network sockets, and writes to NumPy's runtime. Normal
  stdlib, SQLite, NumPy, staged input and generated-output paths pass. The Python
  suite has 29 passed / 1 platform-path skip; skill import/reference tests also pass.
- macOS 26 dyld requires read-data on the literal root vnode (not its descendants).
  The profile grants that narrow operation, not broad filesystem read access.
- New Node-based sandbox dependency deferred: native isolation is verified first;
  packaged interpreter availability and cross-platform support remain separate gates.
- P1-01: unauthenticated mode now rejects non-loopback or unknown ASGI peers before
  routing, independently of HOST/ARSLAN_BIND_HOST. Local Host/forwarding headers do
  not override the peer check. HTTP is 403 and WS is 1008. Reverse proxies still
  require configured authentication; a proxy must not hide remote peers behind an
  unauthenticated localhost backend. No public listener was opened for these tests.
- P1-03: host answers now have kind=host Runs, shared registry cancellation and
  reconnect journals, durable full/partial output, tool trace, prompt and single
  usage accounting. Completed/failed host runs are terminal and never auto-scored
  or admitted into spawn evolution. Host stop button and RunReplay linkage tested.
  Pre-routing conversational micro-turns and direct spawn chat are not yet unified.
- P1-04: recorded Python tools export regular files before temporary cleanup (32
  files, 50 MiB/file, 100 MiB/call). Symlinks and staged inputs are excluded; metadata
  carries Run owner, byte count and SHA-256. Chat download cards and persisted Run
  detail downloads use authenticated API calls. HTML downloads are attachment-only
  with nosniff/CSP sandbox. Standalone unrecorded calls explicitly report that their
  files are temporary, not downloadable. Generic export and real Python roundtrip
  tests passed; full regression is the next gate.
- Phase-one full regression at e4036d32: 3936 backend passes, 14 skips; four
  failures were old host-Run assumptions/marker counts and seven teardown errors
  came from a fixture relying on monkeypatch ordering. Corrected explicitly,
  targeted rerun 38 passed. Frontend 1671 passed / one locale-key-count guard
  failed; three new translations accounted for. Full rerun still required.
- macOS marked suite: **40 passed, zero skipped** (night-macos.xml). CI's exact
  native-test population guard updated alongside the measured test set.
- Gemini non-stream native tools now serialize functionDeclarations with
  parametersJsonSchema, normalize calls, preserve opaque thoughtSignature parts,
  return grouped functionResponses, and exclude thought text from visible output.
  Wire tests plus real tool-loop / mock HTTP two-tool roundtrip passed. This is
  transport evidence, NOT live provider acceptance. References checked 2026-09-14:
  https://ai.google.dev/api/generate-content#FunctionDeclaration and
  https://ai.google.dev/gemini-api/docs/generate-content/thought-signatures.
- P1-05: nested dispatches and concurrent child tasks share one budget. Provider
  HTTP requests (including retries), tool calls, wall time, output tokens and
  artifact bytes are admitted against limits; actual token usage gates the next
  request, not a guaranteed dollar ceiling. Snapshots persist on Run records.
  Defaults: 32 requests, 24 tools, 128k tokens, 600s, 8192 output tokens/request,
  100 MiB artifacts; configurable through ARSLAN_RUN_MAX_* environment settings.
  Background scoring receives a separate bounded context. Nine budget behavior
  tests pass, including parallel admission, multi-tool responses and timeout
  finalization. Python pipe capture and directory scanning are bounded too.
- Packaged builds never relaunch the frozen server as a Python CLI and never
  honor the development unsandboxed escape valve. A standalone Python runtime
  with lockfile-pinned NumPy/Pandas/Matplotlib is staged before signing, verified
  after relocation, and checked again inside the built app. No first-run pip or
  implicit Homebrew dependency. Missing/broken runtime fails closed.
- First remote CI: frontend, native macOS and secrets passed; Linux backend
  had one stale Gemini capability matrix failure (3902 passed). Updated the
  transport claim and preserved unknown/unsupported-state mechanism tests.
- Budget-stage full backend regression: 3953 passed, 14 skipped, two stale
  contract assertions failed (Gemini verdict and migration-tail list); corrected
  with focused reruns. Full frontend dependency rerun: 1670 passed, two stale
  Gemini-table assertions failed; synchronized frontend notices and tests.
- Backup tests cover committed WAL, salt/ciphertext roundtrip, real artifact
  bytes, refusal to overwrite, checksum corruption, traversal, symlink and
  duplicate-member rejection. No real user data or credentials used.
- Run checkpoint tests cover boot interruption and prevention of late partial
  writes overwriting final output. This is not automatic exactly-once tool replay.
- Recipe tests exercise actual Run storage with a deterministic dispatcher:
  concurrent roots followed by a dependent step, one shared budget, immutable
  versions, idempotent start, explicit approval, no repeated completed steps,
  failure cancellation, parent-stop propagation and authenticated HTTP validation.
  Frontend tests cover dependency editing, saved-version-only execution,
  idempotency after uncertain responses and explicit retry confirmation.
- Memory regression subset: 34 passed, including long CJK summary fallback,
  oversized-first-fact refusal, fail-closed sensitive filtering and active-only
  retrieval. These tests do not measure live semantic memory quality.
- Post-recipe frontend full run: 216 files / 1675 tests passed; production build
  passed (main JS 2735.53 kB, gzip 860.44 kB; chunk-size warning remains). Desktop
  npm audit also reports zero known vulnerabilities; default-branch GitHub alerts
  will remain until fixes reach main.
- MCP subprocess environments now pass only runtime essentials, resolved proxy
  configuration and explicit server credentials. Parent provider keys, Arslan's
  encryption secret, SSH agent sockets and runtime injection flags are not
  inherited wholesale. Fourteen targeted MCP environment/session tests pass.
  This is not a filesystem sandbox for arbitrary configured MCP executables.
- Post-recipe full backend: **3985 passed, 14 skipped**. Remote Linux backend,
  frontend, native macOS and secret-check jobs all passed on b17a146a.
- Bundled runtime canary: clean relocated interpreter, DataFrame CSV and real
  Matplotlib PNG generation passed inside Seatbelt; reading an unrelated
  synthetic outside file was denied. Runtime adds 231 MiB unpacked. This is
  pre-signing evidence; final signed-app checks remain a release gate.
- Static browser preview: 36 backend/policy tests and 8 frontend/locale tests
  passed. Real Chromium (sandbox on, page scripts off) fetched example.com,
  exported text/PNG and terminated on cancellation. UI verified completed
  snapshot/downloads and rejection of loopback navigation. Two-step recipe
  editing, dependency/approval toggles and immutable version save were also
  checked in the UI with synthetic data; no model calls were made.
- Full interactive browser remains deferred: macOS rejected nested renderer
  sandbox initialization under an outer Seatbelt profile. The static preview
  uses Chromium's renderer sandbox and a public-IP-pinning HTTPS proxy; do not
  describe that as a kernel network/filesystem jail for Node or the browser host.
