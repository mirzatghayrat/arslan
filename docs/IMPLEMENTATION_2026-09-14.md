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
| P1-02 | Accurate safety documentation and release | Pending |
| P1-03 | Unified host/spawn Run, cancellation, events | Host Run lifecycle implemented; targeted storage/cancel/reconnect/accounting tests pass |
| P1-04 | Persistent downloadable artifacts | Python Run outputs persisted with safe export, metadata and authenticated downloads; targeted tests pass |
| P1-05 | Shared execution budget | Pending |
| P1-06 | Provider contract verification | Gemini native tool/continuation gap implemented and mock-wire roundtrip verified; live calls pending budget |
| P1-07 | Recovery and backup acceptance | Pending |
| P1-08 | End-to-end task benchmark | Pending; paid calls need budget |
| P2-01 | Memory quality, context budgets, scale | Pending |
| P2-02 | Evolution evidence and judge calibration | Pending; live evidence required |
| P2-03 | Capability/version/provenance documentation | Pending |
| P2-04 | Dependency and test infrastructure | Pending |
| P2-05 | Behavior-oriented module boundaries | Pending |
| P2-06 | Loading, empty states, steps and artifacts UI | Pending |
| P2-07 | Voice and native desktop acceptance | Pending; physical checks explicit |
| P3-01 | Versioned recipes and bounded collaboration | Pending; after Run/artifact/budget |
| P3-02 | Controlled browser workflow (selected first) | Pending; cross-platform later |

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
