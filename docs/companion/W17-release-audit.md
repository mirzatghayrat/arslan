# W17 — release audit in progress

This is an engineering checkpoint, not an 8-point score, a release candidate,
permission to publish, or permission to replace the installed application.

## Frozen engineering run

Source `4bb3aa00` was clean when the complete Python suite started. The run used
a new temporary HOME/data directory, a scrubbed environment, a synthetic secret,
disabled secret-file bootstrap, and `ARSLAN_LIVE_LLM=0`. No production application
database or account configuration was loaded. Result: **4,514 passed, 3 failed,
14 skipped, 18 warnings in 389.69 seconds**. The report is
`/tmp/arslan-companion-regression.peETb1/companion-backend.xml`.

All three failures came from `test_accepted_file_types_agree.py`: its source
reader still required literal picker strings after W20 moved both pickers to the
shared registry. Updating the gate also exposed a real mismatch: the image branch
still recognized only six extensions, while the registry declared TIFF/HEIC
families too. The fix recognizes the complete shared image list and verifies
actual dispatch for every declared extension, rather than just comparing two
copies of the same list. Unknown extensions are still rejected. Parser/codec
fidelity remains separate from dispatch recognition.

The updated format/vision/OCR regression passed 93 tests. The complete frozen
rerun on clean source `59d5ba62` passed **4,577 tests, with 14 skips and 19
warnings in 411.38 seconds**. Its report is
`/tmp/arslan-companion-regression.u3Jhgc/companion-backend.xml`. The same skip
categories remain; the teardown guard recorded 64 closed-loop deliveries.
The complete frontend suite passed **236 files / 1,820 tests** in 19.20 seconds,
and the production build passed in 3.66 seconds. The first frontend attempt used
Node's experimental web storage and failed (53 files); rerunning with the already
established `NODE_OPTIONS=--no-experimental-webstorage` setting passed without
product changes. Existing jsdom canvas/navigation and bundle-size warnings remain.
These results apply to that frozen source, not automatically to subsequent edits.

Warnings were not hidden: the first full run included existing async-marker,
SQLAlchemy cleanup/cycle and deliberate teardown warnings. The aiosqlite guard
recorded 77 deliveries into closed loops without changing test outcomes. Twelve
live-model cases, one non-macOS case and one operator-copy allowlist case were
skipped. These are not successful real-model evaluations.

## Desktop source checks

The XcodeBuildMCP skill's session tools were unavailable. The repository's existing
Tauri/Rust CI path was used as the appropriate fallback, not raw Xcode commands.
With the installed stable toolchain, offline/locked dependencies and a temporary
HOME: Rust formatting passed, all 26 Rust tests passed, and Clippy passed for all
targets with warnings denied. Both Swift voice helper files passed typechecking.
The existing empty CI resource directories were reused. No application was
installed/launched, no microphone permission was requested, and no signing or
notarization was performed. These source checks do not verify a distributable app.

## Requirement evidence still needed

| Requirement | Current authoritative state | Remaining evidence |
| --- | --- | --- |
| Complete engineering regression | Clean `59d5ba62` full backend/frontend runs pass as recorded above | Repeat for subsequent release source; skips/warnings remain disclosed |
| 30 real task families × 3 attempts | All 30 catalog entries are `real_inputs_pending`; fixed denominator is 90 | Authorized real inputs, immutable initial-state/configuration hashes, actual attempts and independent checker evidence |
| 60 multi-turn memory scenarios | All 60 remain `specification_pending_runtime_binding` | Runtime-bound cross-turn checks, with output-behavior limitations distinguished from repository/context tests |
| W11 credential boundary | Credential-backed activation remains disabled | Trusted broker identity/OS isolation, confirmation UI, independent security review |
| W12/W13 ASC | Offline read/diff/reconciliation contracts only | Authorized exact App/version integration and real draft-write/readback evidence; no submission/publication authorization inferred |
| W15 design/media | Project style references and gated media library; precise editing unsupported | Runnable design workflow evidence, reference/output review, approved available backend for D07; unsupported stays in denominator |
| W19 browser/dock | Isolated public-page navigation and earlier real-browser fixtures | Independent broker review, full locale/window checks and packaged runtime validation; authenticated actions remain disabled |
| W20 input coverage | Shared declaration, structured readers, sampled video frames and bounded payloads | Remaining codec/visual-quality/source-locator checks and real selected-model evidence; samples are not full-motion or audio analysis |
| W21 language consistency | UI/catalog/connector resources and component tests implemented | Remaining runtime messages/errors and all-six-language live layout/navigation checks |
| Installation and migration | Source-level synthetic migration/restore checks exist | Source/package identity, signature/notarization, isolated fresh install, old-library upgrade/restore and retained model configuration |
| Human trial and safety review | Not supplied by unit tests | Actual authorized trial, UX judgment and external review |

The Mac remains locked for live UI inspection. Unverified rows are not treated as
passed, unsupported tasks are not removed, and development checks are not used as
a substitute for the reserved real-input evaluation set.
