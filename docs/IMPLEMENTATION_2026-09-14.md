# Reliability implementation — 2026-09-14

Baseline: `19f307720c9ffb00df04a591781a2be8a1f94dc1` / v0.1.37.
Branch: `codex/reliability-2026-09-14`.

The maintainer authorized implementation, push, and version updates. Paid model
evaluation has not been authorized. Use synthetic data and isolated test storage.
An 8/10 target is an acceptance goal, not a claim of achieved quality.

## Order and acceptance tracking

| ID | Work | State |
| --- | --- | --- |
| P0-01 | No automatic unsandboxed retry | Implemented; native denial tests and full 4027-test backend regression passed at db43ccaa |
| P0-02 | Filesystem isolation | Implemented for macOS Python; native kernel-denial tests and full backend regression passed |
| P1-01 | Startup/authentication boundary | Connection-level HTTP/WS guard implemented; 31 auth tests pass |
| P1-02 | Accurate safety documentation and release | README/SECURITY contracts corrected; release gates pending |
| P1-03 | Unified host/spawn Run, cancellation, events | Host Run lifecycle implemented; targeted storage/cancel/reconnect/accounting tests pass |
| P1-04 | Persistent downloadable artifacts | Python Run outputs persisted with safe export, metadata and authenticated downloads; targeted tests pass |
| P1-05 | Shared execution budget | Shared request/tool/time/token/output/artifact limits implemented; targeted tests pass |
| P1-06 | Provider contract verification | Gemini native tool/continuation gap implemented and mock-wire roundtrip verified; live calls pending budget |
| P1-07 | Recovery and backup acceptance | Periodic partial-output checkpoints and new-directory validated restore implemented; synthetic roundtrip tests pass |
| P1-08 | End-to-end task benchmark | 30 fixed deterministic engineering contracts and provenance runner added; real-model task benchmark pending approved budget |
| P2-01 | Memory quality, context budgets, scale | CJK-aware context caps and bounded exact-vector scan tested at 1k/10k/100k; live semantic recall evaluation pending |
| P2-02 | Evolution evidence and judge calibration | Judge schema/margin/disagreement handling hardened; invalid old probe retired; live calibration still pending |
| P2-03 | Capability/version/provenance documentation | Source-generated catalog/executor/transport inventory with drift test; pinned browser runtime and corrected capability boundaries |
| P2-04 | Dependency and test infrastructure | pypdf/npm advisories fixed; full regression passed at db43ccaa; Linux-only glib advisory remains explicit |
| P2-05 | Behavior-oriented module boundaries | Partial: host_run, execution budgets, artifact store, recipes, browser proxy/service and vector scan isolated with behavior tests; broad App/tool-loop rewrite deferred |
| P2-06 | Loading, empty states, steps and artifacts UI | Partial: recipe/artifact UI, graph loading/error/empty states and deferred chart loading implemented and UI-verified |
| P2-07 | Voice and native desktop acceptance | Explicit device acceptance matrix recorded in EVALUATION.md; physical checks pending |
| P3-01 | Versioned recipes and bounded collaboration | Immutable versions, dependency execution, 1–4 parallel steps, approval/resume API and six-language editor implemented; behavior tests pass |
| P3-02 | Controlled browser workflow (selected first) | Static preview implemented and UI-verified; full interactive browser deferred, no kernel egress claim |

## Verification log

- Release preparation at db43ccaa: **4027 backend tests passed, 14 skipped**
  (290.02s), **1680 frontend tests passed**, TypeScript/build and CI-scoped Ruff
  passed. An earlier full run caught a missing vector-filter diagnostic log;
  the log was restored and the full suite rerun, rather than weakening its test.
  Existing fixture teardown/async-mark warnings remain; this is not a zero-warning
  claim. The fixed acceptance runner reports **30/30** contracts on this commit.
- A separate post-signing frozen-service computation gate was then added:
  `--compute-selftest` uses only disposable storage, runs the production Python
  sandbox/export path, checks outside read/write and socket denial, and verifies
  persisted CSV contents plus PNG/hash bytes after workspace cleanup. Source
  interpreter use refuses; override runtime paths are ignored for this test.
  Packaging/entrypoint targeted tests: **32 passed**. Actual signed-app execution
  of this new gate remains pending the release workflow.

- Baseline audit: 3912 backend tests and 1669 frontend tests passed on the same
  commit, recorded separately on 2026-09-13. This is not post-change evidence.
- P0-01 adds behavior tests for attacker-controlled stderr and for a backend
  claiming availability but returning no execution wrapper.
- P0-01 targeted suite: 19 passed, 1 non-macOS-path skip on macOS; Ruff and
  whitespace checks passed. This does not resolve the separate filesystem issue.

Do not mark an item complete solely because code exists or a mocked test passes.
Release only the verified scope and clearly identify unverified features.

- P2-06: the graph always contains a synthetic self node, so checking for zero
  nodes hid the empty-state guidance. Real knowledge nodes now determine emptiness;
  failed graph loads expose an explicit retry instead of looking empty. Verified
  in the isolated browser. Coverage details are collapsible, with retention and
  empty-window warnings remaining visible. All six locales retain parity.
- Chart rendering is now deferred until needed, with asynchronous cleanup tests.
  Production main JS changed from 2735.53 kB / 860.44 kB gzip to 1612.81 kB /
  484.35 kB gzip; deferred chart chunk is 1136.82 kB / 381.24 kB gzip. These are
  bundle bytes, not measured cold-start timings; large-chunk warnings remain.
  Full frontend: 217 files / 1680 tests pass, TypeScript and production build pass.

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
