SBX-2 stages a default-deny Seatbelt preset and a base-name-parameterized evidence harness. Product callers still use SBX-1's existing presets. The candidate grants only explicit process, file, device, IPC and TCP operations, with closed/protected paths last. Its Mach-service and Unix-socket allowlists remain empty until SBX-M supplies evidence for individual additions.

Author: Codex
Reviewer: GPT-6 Astra, highest reasoning level, in a new independent Codex session (**pending**). Claude reviews only non-probe harness/marker plumbing. The user pushes, opens the PR with label `codex`, and merges.

Task: [SBX plan — Who writes what, sections 1, 2 and M, SBX-2 row](https://github.com/mirzatghayrat/arslan/blob/main/docs/plans/0164/SBX-sandbox.md).
Procedure and coverage: `tests/server/sbx/corpus/README.md`.

## Evidence 1: verification and results

- Portable regression command: `.venv/bin/pytest tests/server/sbx/test_sbx2_profile.py tests/server/sbx/test_sbx1_profile_texts.py tests/server/test_command_sandbox.py tests/server/test_code_sandbox.py tests/server/test_capability_sandbox.py tests/server/test_ssh_exec.py -m 'not macos' -q`: **94 passed, 1 existing Linux-only test skipped on macOS, 34 macOS cases deselected**. Local checks used a scratch HOME.
- Candidate/profile goldens and platform-marker guard: **31 passed, 1 failed**. The sole failure is `test_the_ci_workflow_expects_the_same_count`: the unchanged workflow expects 69, while this branch selects 359. This is an outstanding CI dependency, not a green suite.
- macOS collection: `pytest tests/ -m macos --collect-only -q` selects **359 cases**: 69 existing plus SBX-2's 71 kernel gates and 219 compatibility measurement rows. All new cases carry `macos`; `sbx_mac` selects all 290 new cases. A platform lacking Seatbelt fails on macOS instead of skipping.
- The installed macOS policy compiler accepted all four candidate network modes with a run-scoped IPC prefix. This checks syntax without applying the sandbox; it is **not** enforcement evidence.
- Three portable mutation checks went red: default-allow in place of default-deny, wholesale Mach lookup, and a read grant after protection. The source was restored after each. Real-kernel mutation evidence is still pending CI/review.
- Ruff on every changed Python file, `git diff --check`, and `python3 scripts/check_added_chinese.py --base origin/main` passed (1,061 added lines checked). No `.github/` changes; the candidate's only reference under `server/` is its definition.
- **macOS CI run id: pending — add the id, conclusion, assertion counts, skips and xfails after the user pushes and CI runs.** No real-Seatbelt corpus was run locally; the card requires CI first, then SBX-M on the user's Mac.

## Evidence 2: coverage

- Stable golden text, parameter rejection, resolved protection ordering, explicit TCP modes, same-sandbox signals, private IPC name prefixes, narrowed device writes, and a base-name table with strict expected failures for future unbuilt surfaces.
- Real-kernel test code for each section 2 service class, all four network modes, preference and launch submission denial, Apple Events, Unix sockets, controlled filesystem boundaries, signals, IPC, ptys, devices and loopback/Arslan-port exclusions. Service tests require a policy denial as well as failed reachability, with historical controls; a missing daemon alone cannot pass.
- Measurements under current commands, candidate and outside floor: git, Python, node, Swift, brew, DNS/certificates, two cache runs, hard links, temp behavior and child access. Optional operator-supplied real agent sockets are connect-only. Exact profile hashes and safe outcomes are printed in CI logs and JUnit; local profile artifacts can be saved explicitly.
- No entry point, parser, classifier, Settings default, outside-floor policy, secret, dependency version, lockfile, or workflow is changed.

## Evidence 3: not covered / remaining work

- No CI run or independent Astra review yet. The new test code is not proof of runtime confinement until that run succeeds. No SBX-M result or compatibility claim is supplied here.
- **Required companion CI change, by a Claude session in its own PR:** update the macOS job's exact expected population from 69 to 359 (recount after any intervening changes). This branch updates the test-side mirror and deliberately does not weaken or skip the mismatch assertion. Codex may not edit `.github/` under the task's delivery rules. Coordinate that dependency before judging this PR mergeable.
- No product wiring or SBX-3 Run lifecycle/boot sweep, final private-app-data paths, SBX-5 cross-preset cache/link protections, or SBX-6 live proxy. No authenticated SSH remote, Xcode GUI, QUIC, or exhaustive syscall/device trace. A missing optional socket is reported as `not-supplied`.
- Compatibility measurement rows intentionally do not fail pytest on a tool/network failure. Review their explicit outcomes; a green measurement row is not a successful tool run. Public network availability and installed tool versions affect those outcomes.

## Evidence 4: residual risks

- The empty service allowlists intentionally expose compatibility costs, particularly cfprefsd, DNS, trust services and SwiftPM. Additions require named corpus evidence and review; do not widen them wholesale. Proxy rows do not have a running proxy yet.
- Mach service aliases vary by OS. The tests cover named classes and actual launch submission, but SBX-M must verify the user's build and catch alternate channels. A headless CI VM cannot substitute for the user's Mac.
- IPC isolation is a fresh random per-run name prefix, not ownership tracking; callers must allocate unique prefixes. Unmodified multiprocessing may use other names and fail. Hard-link results may require a kernel follow-up before SBX-3.
- The current branch is **not merge-ready** until the companion CI change, successful macOS run, and independent review. This unused preset does not alter current user behavior.

Security-boundary validation is centralized in the preset: unknown modes, invalid ports and malformed IPC prefixes fail before emitting a policy. No speculative fallback or new service-framework abstraction is added. `DELETE-BY: v0.1.64 after SBX-M records the historical baseline, before SBX-3 replaces the commands preset` applies to the harness's historical adapter; the code and task card both state it.
