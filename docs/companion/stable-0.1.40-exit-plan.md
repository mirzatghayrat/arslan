# 0.1.40 stable — finite acceptance and release plan

User direction, 2026-09-23: stop treating successive beta releases as the
destination. Deliver a functionally complete, tested stage, then a stable
release. This stage is **the daily research assistant**, not all of v1.2.

Baseline: published `v0.1.40-beta.6`, source
`0beb89bd638d5846745b7546adeb128452a5a0c2`. Work branch:
`codex/stable-0140-acceptance-2026-09-23`. Existing worktrees, release-note edits
and installed applications are preserved. No version bump or tag yet.

## Fixed product promise

Compare public materials, summarize/compare supported user documents, produce
an openable result with inspectable sources, and continue work using only
eligible confirmed project context. Errors, partial input, cancellation and
recovery must be visible and must not silently lose data or expand authority.
Existing conversation, expert, settings, voice and library paths remain protected
by relevant regressions; they are not removed to make this stage appear smaller.

No new training, default model routing, authenticated browser writes, credential
broker, general account automation, full video understanding or redesign enters
this release. Unsupported capabilities must be unavailable or accurately labelled,
not merely hidden in release notes while advertised in the application.

## Three batches, one release destination

1. **Freeze acceptance and measure gaps.** Carry forward the twelve existing
   IDs and original failed outputs; freeze new inputs/checkers before new model
   calls. Inventory native and compatibility evidence, reusing valid evidence
   rather than treating every historical 'pending' paragraph as a new task.
2. **Close blockers.** Reproduce and repair failures in the fixed scope, in
   small batches. Verify each repair and affected regressions. No beta release
   is required after every development batch. New feature requests go to the
   next milestone unless explicitly brought into scope by the user.
3. **Freeze candidate and release stable.** Complete integration review, exact
   source CI and signed-package acceptance. Use an RC only if a distributable
   acceptance candidate is needed. Never move a released tag or use another
   SHA's green CI. Prepare the stable release for the user's final Publish.

## Release gates — all required, no blended percentage

| Gate | Finite acceptance | Current status |
| --- | --- | --- |
| R — useful task outcomes | All original R1–R4/D1–D4/M1–M4 IDs have frozen inputs, actual outputs, reviewed conclusions, sources/artifacts and recovery evidence against their original acceptance. Keep failures and corrections; no best-of-N substitution or dropped cases. | Open: beta.5 live pilot is partial, not 12/12; R2 public conflict unresolved, R3/R4 excerpt limitations and M4 live read-only boundary retained. |
| N — actual native core flows | On the candidate: identity/channel; conversation and restart; mixed attachment retention; source opening; artifact opening; project memory correction/deletion; cancellation and explicit resume; backup/restore UI. Verify narrow-window usability and localized safety/errors in supported locales; recheck changed surfaces rather than all historical screens. | Partial prior evidence: beta.6 icon switching, rounded corners and five pages at two sizes were tested. That is not the complete core-flow acceptance. |
| U — upgrade and recoverability | Isolated fixtures representing stable 0.1.38, beta.3 and beta.6; backup before upgrade, supported upgrade with record/content checks, restart, restore with matching key, wrong/missing key and interrupted restore fail-closed. Exercise installer replacement and updater manifest/signature handling without changing production Latest or real data. | Open: substantial component tests exist; cross-version packaged evidence still must be bound to the candidate. |
| S — safety and regression | No unresolved data-loss, unauthorized action, privacy/key exposure, startup failure or broken advertised core path. Full CI and scoped safety regressions pass; dependency findings receive platform/reachability disposition rather than 'all clear' by count. | Open until final source; reuse prior results only where changes cannot invalidate them. |
| P — release provenance | Release source integrated through review with current remote main; documented source/version identity, full same-SHA CI, signed/notarized/stapled package, Gatekeeper/fresh-install and asset/update-signature checks. Stable-channel update path explicitly reviewed before Latest/Publish. | Open; remote main observed at `d3e8081d0fc7a72072731edfaa0ea33acf095724`, not the beta.6 source. Do not silently merge or promote the existing beta artifact. |

Supported rollback means restoring the **pre-upgrade profile plus matching
key and compatible app**. It does not mean an old binary may safely open a new
database. Test and document that supported recovery path. Already shipped old
binaries cannot acquire a downgrade guard retroactively; do not promise one.
Inspect current boot/migration rejection of unsupported future schemas as a
separate safety boundary before deciding whether code changes are required.

The endpoint is all five gates satisfied for this bounded scope, not completion
of every W00–W21 item, all sixty memory scenarios, every model/provider or every
possible UI state. Cosmetic or deferred non-core items may be recorded for a
later release with rationale; a failed core case cannot be waived by relabelling
it as deferred after seeing its result.

## Evidence and decision rules

Each gate records source SHA, environment, fixture/input hashes, command or UI
steps, observed result and evidence location. Unit tests, scripted integration,
real-model runs, native interaction and installer checks stay distinct.
Review factual support and usefulness; parseability and passing harness asserts
are not model-quality acceptance. Source availability and model uncertainty are
handled honestly; no fabricated successful reads or forced conflict resolution.

No automatic retries of costly failing scenarios. Diagnose first, then register
a repair attempt and retain the baseline. Freeze scope once the candidate is
prepared. A new serious safety finding still blocks release; unrelated feature
ideas do not extend the finish line.

## Authority and costs

No user profile, real chats, personal files or account mutations are used for
acceptance. No installed application is replaced without explicit authorization.
Synthetic keys/data and isolated profiles are the default.

The earlier real-model pilot used 32/36 requests and is a separate historical
authorization. 'More Codex quota' is not assumed to authorize a new API bill.
A new independent 36-request / US$5 configured-primary-model budget was explicitly
approved in this task on 2026-09-23. It covers only isolated synthetic inputs and
public materials; stop paid calls if pricing cannot be reliably bounded. This
new batch has not made a model call yet. Preserve a distinct durable ledger and
never reset either ledger to obtain extra attempts.

The old beta.5 publishing automation remains paused. No new publishing monitor,
main merge, release creation or stable promotion is started by this planning
checkpoint. Normal scoped implementation and offline verification continue.

## First compatibility batch — 2026-09-23/24

No paid model request, native app launch, installation or user-data access.

- Existing migration/backup/deletion-ledger/recovery/profile tests: initial
  command omitted the synthetic secret, producing 25 encryption refusals and
  204 passes. This was a test-environment omission; no insecure-secret bypass
  was enabled. With explicit synthetic `ARSLAN_SECRET_KEY`, **229 passed**.
- Reproducer for an unsupported future `schema_version`: **three failures**
  before repair. Direct migration silently accepted the ledger; normal storage
  boot and migration CLI reached schema creation before any compatibility check.
- Repair: a read-only compatibility fence before schema creation and crypto
  boot, plus a fence for direct migration callers. Unknown IDs and ambiguous
  ledger forms fail with `database_schema_unsupported`, without echoing profile
  paths/ledger contents. Fresh and supported legacy profiles remain allowed.
- Post-fix future-schema/migration/profile regression: **114 passed**. Tests
  check byte-identical fixture databases after refusal; they do not prove that
  already released old binaries refuse new databases.
- The startup-order test initially failed because it enumerated the old
  callback order. Its assertion is updated to require the new guard first,
  retaining all schema/crypto/memory callbacks in their original relative order.
- Final startup/legacy-crypto/preflight/future-schema selection: **43 passed**;
  Ruff and whitespace checks passed. These groups overlap and are not a sum
  of distinct pilot successes. Full candidate CI is still a later gate.

This is a source-level compatibility repair, not completion of gate U. Actual
cross-version packaged upgrade/restore and localized native error experience
remain required. No claim of stable readiness is made by these test counts.

## Next-release inclusion — branded installer, 2026-09-24

User-approved installer handoff received from the design task. Source commit
`e1e51b229298e3301b19ba4cda621a4eb932d144` was cherry-picked as `cd41a75f`
without resetting the compatibility work. Include it in the next planned
release; **do not create a separate release for this change**.

- Preserve the 720×440 Finder layout, native App/Applications items, orange
  arrow and committed 1x/2x backgrounds. Default artwork is English only:
  **Drag Arslan into Applications to install**. Do not add Chinese/bilingual
  copy. macOS may localize its own Applications label.
- `dmgbuild==1.6.7` is locked and macOS/build-only. The packaging workflow must
  install the build extra; no new end-user runtime dependency is implied.
- Gate P now explicitly includes running `packaging/verify_dmg_layout.py` on
  the newly built real DMG before signing, plus opening that candidate DMG in
  Finder to inspect the English text, Retina background and icon positions.
- Preserve existing signing, notarization, stapling, Gatekeeper, fresh-install
  and updater-signature checks. Run full same-source CI with this dependency
  and packaging change included. Recheck two published DMG aliases for matching
  digests if both names remain in the release.
- Design-task evidence: a real preview made with the signed beta.6 App passed
  layout verification and Finder inspection. This is handoff evidence, not
  evidence that the next candidate has been built or notarized. Never upload
  that temporary preview DMG as the next release artifact.

Integration checkpoint: cherry-pick clean; local Ruff, shell syntax and
whitespace checks passed. No full CI, native rebuild, tag or release was run
for this handoff. Packaging reference: `packaging/dmg/README.md`.

Follow-up offline selection, 2026-09-24, source `8e795bdd`: explicit synthetic
secret, existing locked Python environment; release-workflow, packaging-entry
and fresh-install salt-probe tests **71 passed** (2.26 s), with the existing
Starlette/httpx deprecation warning. This is not a newly built DMG, a native
install run or completion of gates N/U/P.

The user additionally requested Jev/Laya efficiency research. Findings and a
bounded, not-yet-started later experiment are recorded in
`jev-laya-research-2026-09-24.md`. No new inference dependency, model download,
cloud provider or release gate is introduced; stable acceptance stays first.
