# 0.1.40 stable — finite acceptance and release plan

Latest result: [two-case semantic review](stable-0.1.40-two-retest-20260924.md).
Source 60e779ba, independently approved 12/$1.20, used 8 requests. Both deliver
files and final answers; R1/R4 still contain unsupported saved-report claims.
Prompt-only strengthening was insufficient. R is not closed, no tag or stable
release authorized by these results. Stop repetitive paid reruns; next repair
must address claim-to-evidence review without hidden calls or a silent model swap.

Latest R-gate update: [four-case retest](stable-0.1.40-four-retest-20260924.md)
on source `83f29f4ecc2da668ace50e6bbf989ae7d296d00f`, 15/22 new requests.
D3/M2 core criteria passed (D3 wording caveat retained). R1/R4 now deliver
saved/reopened reports and final answers, but both still fail specific semantic
claims. R remains open with two cases, not four execution failures. Later prompt
repairs are not live-certified. No stable candidate or release yet.

Previous R-gate update: [eight-case additive retest](stable-0.1.40-retest-20260924.md)
on source `470c713735f1661c54941da55975eb0bf881c605`, 30 new requests. D1/R2/R3/M4
core criteria passed with recorded caveats; D3/M2/R1/R4 remain unaccepted.
Later offline fixes are not live-certified. Scheduled `arslan-2` is paused;
no stable candidate, tag or Publish yet. Historical checkpoints below are retained.

Latest native update: wrong-key restore refusal with an actual synthetic encrypted
credential now has development-bundle evidence; original project/memory remained
usable after restart. This closes that specific native negative case, not the
final-package or broader N/U gates. See the v8 receipt below.

Native layout v9 (same fcb5f2ac development bundle, not the current source):
isolated `native-home-layout-v9` switched zh/en/ja/es/de/fr through the actual
native window. AX observations show localized preview/manual-install/stable-update/
backup notices and native menu labels in all six. Window resized to 1800x1200
retina pixels (approximately 900x600 logical); Chinese and French workspace
screenshots and German appearance screenshot retained usable key controls with
wrapped long text. Lower settings scroll normally; this is not a full six-locale
error-dialog or full-conversation acceptance. Local receipt `native-layout-v9.json`
records executable hash and boundaries; screenshots were inspected in task tools,
not separately archived. Clean native Quit, stopped PID absent, zero provider/
message/run/usage rows. No model calls or real installation changes.

User direction, 2026-09-23: stop treating successive beta releases as the
destination. Deliver a functionally complete, tested stage, then a stable
release. This stage is **the daily research assistant**, not all of v1.2.

User clarification, 2026-09-24: 0.1.40 is the first delivery checkpoint, not
the overall destination or a reason to stop progressing toward v1.2. Remaining
v1.2 capabilities should be mapped by functional dependency to independently
usable, tested releases after this one. Do not bundle them back into 0.1.40 or
interpret more version numbers/betas as delivered functionality. Exact later
version assignments require that roadmap mapping, not invented completion dates.

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
broker, general account automation, full video understanding or wholesale redesign enters
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
| R — useful task outcomes | All original R1–R4/D1–D4/M1–M4 IDs have frozen inputs, actual outputs, reviewed conclusions, sources/artifacts and recovery evidence against their original acceptance. Keep failures and corrections; no best-of-N substitution or dropped cases. | Open: eight-case additive sweep executed, not eight passes. D1/R2/R3/M4 core criteria passed with recorded caveats; D2/D4/M1/M3 prior core results retained. D3/M2/R1/R4 remain unaccepted. Offline repairs are not live-certified. |
| N — actual native core flows | On the candidate: identity/channel; conversation and restart; mixed attachment retention; source opening; artifact opening; project memory correction/deletion; cancellation and explicit resume; backup/restore UI. Verify narrow-window usability and localized safety/errors in supported locales; recheck changed surfaces rather than all historical screens. | Partial: isolated native development bundle from fcb5f2ac verifies identity, Chinese onboarding/menu, project create/edit/restart, mixed attachment rejection/retention, memory correction/history/pause, restore-picker cancellation, positive restore/activation/relaunch with quarantined memory, and checksum-mismatched archive refusal with original profile retained after explicit restart. Backup was created through the source maintenance API, not a native export UI. Full conversations, deletion, source/artifact opening, task recovery, wrong-key/interrupted native restore, narrow-window/six-locale completion and final signed candidate remain unverified. |
| U — upgrade and recoverability | Isolated fixtures representing stable 0.1.38, beta.3 and beta.6; backup before upgrade, supported upgrade with record/content checks, restart, restore with matching key, wrong/missing key and interrupted restore fail-closed. Exercise installer replacement and updater manifest/signature handling without changing production Latest or real data. | Partial: all three historical-source profile rehearsals passed on 2026-09-24; packaged/UI upgrade and recovery evidence still must be bound to the candidate. |
| S — safety and regression | No unresolved data-loss, unauthorized action, privacy/key exposure, startup failure or broken advertised core path. Full CI and scoped safety regressions pass; dependency findings receive platform/reachability disposition rather than 'all clear' by count. | Open until final source; reuse prior results only where changes cannot invalidate them. |
| P — release provenance | Release source integrated through review with current remote main; documented source/version identity, full same-SHA CI, signed/notarized/stapled package, Gatekeeper/fresh-install and asset/update-signature checks. Stable-channel update path explicitly reviewed before Latest/Publish. | Open; remote main observed at `d3e8081d0fc7a72072731edfaa0ea33acf095724`, not the beta.6 source. Do not silently merge or promote the existing beta artifact. |

Native recovery clarification (2026-09-24): post-trial **Keep paused**, refusal of
rollback on the next launch, and explicit rollback on a subsequent launch now
have real native development-bundle evidence below. This is not an injected
crash during directory movement, wrong-key coverage, or final-package acceptance.

Native memory clarification (2026-09-24): deletion cancellation, confirmed
deletion and restart persistence now have real isolated development-bundle
evidence below; remove that item from the outstanding development-UI checklist.
Final-candidate revalidation and real-model non-reuse remain separate boundaries.

### Native wrong-key recovery — v7 qualification and v8 result

Same unchanged development bundle, source
`fcb5f2acacd1f188f631fc384e99dfa7803f3a55`; fixture helper checkout `c612db65`.
No paid calls, real providers, private chats, installed-app replacement or Publish.

- v7 used the earlier backup with no stored credentials. A different well-formed
  key reached trial success because there was no ciphertext to validate. Kept
  paused, never activated. Retain this experiment; it is not a wrong-key pass or
  evidence of credential decryption bypass.
- v8 added exactly one encrypted, unusable synthetic search credential to a
  separate backup fixture. Offline preflight before native execution was
  `compatible/checked=1/unreadable=0` with its fixture key and
  `unreadable_credentials/checked=1/unreadable=1` with the wrong key.
- Actual native ZIP/key pickers and stop/prepare confirmation led to a localized
  paused warning, with **no activation confirmation**. Controlled-HOME restart
  reopened the original Cedar project and paused blue local memory.
- Read-only stopped checks confirm original fixture DB hash unchanged, active
  project/memory/revision facts identical, no synthetic credential imported,
  zero provider/message/run/usage rows, no activation or previous-profile record.
  The retained candidate still requires the correct key; wrong-key unreadability
  remains 1/1. Backup hash unchanged.
- UX caveat: the warning is generic "restore paused", not a specific key-mismatch
  explanation. Final signed-package repetition remains required.
- Tooling caveat: an AX observation immediately after final Quit exposed a new
  default-HOME acceptance process blocked by the existing profile lock. No
  workspace loaded; this acceptance process and own launchers were terminated.
  Future cleanup must inspect process exit through the launcher, not call AX on
  a stopped app. This is not counted as a second successful restart.

Private receipt `../stable-0140-native-evidence-20260924/native-wrong-key-v8.json`,
SHA-256 `b6aed3e60662deaf41d4cd4d8c3914d6ee546482a6b37d1fed0ec9dcd30fac0a`.
All test processes stopped; raw fixture logs remain private.

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
new batch has used 31/36 calls, $3.10 reserved as of the M4 process batch below. Preserve a distinct durable ledger and
never reset either ledger to obtain extra attempts.

The old beta.5 publishing instructions are obsolete. The user authorized ongoing
stable-stage work and notification when a releasable draft is ready on 2026-09-24;
the existing heartbeat may be repurposed with this plan and current branch, never
resumed with the old candidate. Main merge and Publish remain user-controlled.

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

## Cross-version source rehearsal and refusal UX — 2026-09-24

User confirmed stable-first; the future optional Jev mode stays outside this
release. No additional model calls, real profile access or installed app changes.

New opt-in harness: `tests/server/test_stable_cross_version_profiles.py`.
Historical code is extracted from local Git objects and run in fresh processes
with disposable HOME, explicit synthetic credentials and a network-blocking
audit hook. It creates fixtures with the historical models/migrations, not
current-model fixtures relabelled as old profiles. Runtime dependencies are the
current locked environment, not the historical signed bundles.

| Source | Resolved source commit | Schema head | Observed |
| --- | --- | --- | --- |
| v0.1.38 | `1724d2afa95fd4dfff28d1151135e00ec15926d4` | 0046 | Upgrade to 0053, second boot, pre-upgrade backup recovery passed |
| v0.1.40-beta.3 | `fe0624943534e63b38a9a440c6631000c0798eec` | 0053 | Same checks passed |
| v0.1.40-beta.6 | `0beb89bd638d5846745b7546adeb128452a5a0c2` | 0053 | Same checks passed |

Each checks synthetic chat, legacy fact content, decryptable provider credential,
reopenable CSV and database integrity. Wrong/missing-key preflight refuses
without changing the upgraded DB. Recovery uses the pre-upgrade archive plus
matching secret and original source; it never boots the old app on the upgraded
DB. Original fixture and archive hashes remain unchanged.

Evidence directory beside the worktrees:
`stable-0140-compat-evidence-20260924/source-identity-corrected/`.
Three JSON records retain source/archive/harness hashes and boot results.
The initial three-pass report used the v0.1.38 annotated tag object ID in its
`source_commit` field. Archive contents were the released source, but that field
was imprecise. Original reports remain intact; the corrected harness checks
`tag^{commit}` against the pinned commit and reran all three. With the seven
future-schema tests, **10 passed** in 6.81 s. No product failure was hidden.

The rehearsal exposed a related UX gap by inspection: the storage guard could
refuse after the sidecar had announced its port, leaving a generic desktop
startup failure. Two new entry-point tests failed before repair. The packaged
entry now checks the schema read-only while holding profile ownership and
before announcing a port; a closed error code maps to six-language recovery
guidance. It never triggers automatic restore/retry or echoes private details.
The transactional storage guard remains in place as defense in depth.

Verification on the changed source:

- Packaging, future-schema, native-locale and release-workflow selection:
  **87 passed**; Ruff and whitespace checks passed. Includes a fresh-process
  run of the real entry script: unsupported schema emits only the known code,
  leaves the DB unchanged and creates no secret or access token.
- Rust library: **78 passed, 1 existing opt-in packaged-control test ignored**.
  Initial local build lacked the CI resource placeholder directories; after
  creating the same empty sidecar/listen directories as CI, tests passed.
  These placeholders are not a built sidecar or releasable package.
- Locked/offline Rust Clippy with warnings denied and rustfmt check passed.
- Native error-code mapping and all six catalogs are tested; actual displayed
  layout and user interaction remain native acceptance, not inferred from tests.

Reproduce the cross-version group with `ARSLAN_STABLE_COMPAT=1`, an explicit
synthetic `ARSLAN_SECRET_KEY`, and the existing development Python environment.
An optional `ARSLAN_STABLE_COMPAT_EVIDENCE` directory uses exclusive output
creation, so do not overwrite earlier evidence when rerunning.

Remaining gate U work is packaged installer/updater and native recovery flow,
including interrupted recovery on the candidate. R/N/P are not closed by this
source-level batch. No new beta, stable tag, push or Publish was performed.

## Bounded usability batch — 2026-09-24

The user explicitly brought the crowded conversation UI into this stable stage.
This is not a new feature milestone or a wholesale visual redesign: prioritize
reading, task follow-up and discoverable controls while retaining safety status.
The overall v1.2 direction remains; this release still ends at the five gates.

- Diagnostics starts closed and is an overlay at narrower widths; its button
  exposes expanded state and the rail has an accessible name/close action.
- Project/memory and task status share one wrapping context row. Actual project
  and task dialogs, review/cancel/resume behavior are retained.
- Empty expert strips disappear; real invited experts remain available.
- Attachment and microphone actions are grouped; stop/send remain in place.
- Execution settings are collapsed by default, but the confirmation posture is
  always readable. The header tooltip uses the actual policy instead of claiming
  every command needs confirmation while read-only auto-run is enabled.
- Sidebar spacing is reduced and waiting tasks retain their status and count.
  No actual tasks, memories, permissions or navigation destinations are removed.

Evidence: seven focused frontend suites **47 passed**, TypeScript and production
build passed (existing large-chunk warning retained). The isolated real-App
fixture in `web/acceptance` was inspected at 1280x720 and 900x600: reading area,
pending task, combined toolbar, mic/attachment grouping and default-closed rail;
execution options and diagnostics were opened. Fixture data is synthetic and
cannot call a model or execute commands. This is browser-rendered layout evidence,
not completion of native gate N or the twelve real task cases. The fixture is not
a production build entry. No installed app, real profile or paid model was used.

Final frontend regression after the policy-tooltip correction: **260 files,
2039 tests passed**, TypeScript and production build passed. jsdom emitted its
known canvas/navigation-not-implemented notices, not test failures. English
900x600 was also visually checked; project/memory and task dialogs opened and
closed correctly using only fixture data. This does not upgrade the evidence
to native-app or model acceptance.

Next bounded work: freeze remaining R inputs/checkers and the independent cost
ledger; complete the outstanding task-outcome and native core-flow evidence,
then freeze/integrate the release candidate for exact-source CI and packaging.
Do not cut a beta just for this layout batch or add Jev before stable acceptance.

## Stable live-input contract and budget checkpoint — 2026-09-24

Starting source `7edc50e2`. New `evals/companion/stable-0140-acceptance.json`
retains all twelve original IDs, pins prior input/generator/runner file hashes,
and fixes per-case criteria and request ceilings summing to 36. This is a new
authorization, not replacement of the old live pilot. R2 public inputs remain
blocked; R1/R3/R4 require complete pinned-body acquisition/read evidence, not
the prior excerpts. No case has been promoted to passed by this checkpoint.

The separate canonical ledger is beside this worktree at
`stable-0140-live-evidence-20260924/budget.jsonl`. Initialization is exclusive;
reservations are locked, append-only, flushed and never refunded. The offline
helper rejects missing/damaged ledgers, changed contracts or input hashes,
unknown/stale/unbounded pricing, missing opt-in and per-case/global overruns.
Same-day pricing and semantic preflight are explicit caller-reviewed evidence,
not inferred from their presence in JSON. See `evals/companion/STABLE0140.md`.

The stable live runner still needs wiring to this ledger and post-response
usage/HALT checks before any paid execution. Historical live tests must not be
pointed at a new output folder as a workaround. No model, profile/key access,
native app or release operation was performed; new grant usage remains 0/36.

Verification: new stable-ledger plus historical guard selection **25 passed**
(0.18 s), including concurrent reservations and retained original pilot limits;
Ruff and whitespace checks passed. The canonical stable ledger was initialized
once and read back as **0 requests / US$0.00 reserved**. Next batch must reuse
it, not initialize another, and finish complete-source preflights/runner wiring.

## Public-input and guarded-adapter checkpoint — 2026-09-24

Starting source `cffdaa8f`. Seven complete public source bodies archived with
retrieval provenance; the five original README hashes all match. R2 now has an
additive frozen preflight for the genuine Planck/SH0ES H0 discrepancy, explicitly
preserving different methods/model assumptions, dates and uncertainties. It is
not a full-paper/current-consensus claim or a passed task. Details and source
links: `stable-public-input-review.md`. The original contract and ledger are
unchanged; no synthetic case was relabelled as public evidence.

The stable adapter now reserves before a single non-streaming request, records
usage, and halts on ambiguous accounting/failure/interruption. All tests use
doubles; no primary credential loaded or paid call made. Actual host-runner
integration and current pricing verification remain required. Public extraction
preflight exposed the existing 12,000-character cap truncating OpenSquilla and
Serena; R1/R4 must get a supported bounded complete-read path before they can
meet the frozen criteria. Do not change only the harness to hide this limitation.

Next: close that narrow reader gap with security/source regressions, finish
preflight/host wiring, then execute/review the fixed cases under the same ledger.
Native/packaged gates remain separate; no beta, stable tag or Publish here.

Verification: collector/adapter/stable-budget/original-budget selection **42
passed** (0.23 s); Ruff and whitespace checks passed. Initial Ruff fixture-import
diagnostics were fixed without altering the frozen historical runner. The source
collection used seven fixed public GETs and the actual ledger still reads 0/36.

## Bounded long-read repair — 2026-09-24

Starting source `37ec8a8e`. A failing executor reproducer showed that requesting
a larger read still returned only the initial 12,000 characters. The real
`web_extract` now accepts optional integer `max_chars` in 1–40,000, with the
unchanged 12,000 default. Invalid values fail before any fetch. The existing
single-resolution/per-hop pinned network path, timeouts and fetch budgets are
unchanged. Tool schema and host guidance expose the same bound and require
honest partial-read disclosure; pages longer than the bound are not 'fully read'.

A second reproducer found a distinct transport cut: `_record_tool_result`
serialized all tools then sliced at 8,000 characters, losing the page's tail
and source metadata even after a successful longer fetch. After correcting a
test-double omission of required `usage`, that test failed on the missing tail.
Validated built-in web reads now use a structured, bounded envelope preserving
text plus receipt. Escape-heavy serialization is capped at 60,000 characters by
shortening the text **before** hashing/logging; its effective receipt is partial,
so the trace cannot claim delivery of discarded bytes. Unrelated/malformed tool
results keep their old transport cap. External-data framing and marker-defanging
remain in place; this is not a security-permission expansion.

Verification (overlapping groups, not unique task counts):

- Executor/schema/host loop/source and SSRF redirect/rebinding/pinned-fetch group:
  **163 passed**. Default reads remain bounded; larger reads still reject private
  destinations and bad limits. A scripted host adapter sees the source tail and
  intact metadata, not just a direct-executor return value.
- Framing/source-output/runtime-policy/task validation/frozen inputs/generated
  capability inventory: **71 passed**. Inventory fingerprint refreshed for the
  changed executor; no frozen live input or historical runner altered.
- Final targeted long-read suite including forged closing-marker defense:
  **18 passed**. Ruff and whitespace checks passed; existing Starlette warning
  retained. No broad unrelated suite rerun or full same-SHA CI claim.
- Actual archived bodies through the production parser, executor and prompt
  envelope: **7 passed**; no source remains truncated at 40,000 for this frozen
  set. Network transport was explicitly replaced with archived public bytes.
  This is an offline preflight, **not live source fetching or real-model quality**.
  Evidence plus implementation hashes: canonical evidence directory's
  `public-reader-preflight-v1/`.

The selected long-source delivery gap is closed at source level. Current grant
still reads **0/36 / US$0.00 reserved**. Next bounded batch: wire isolated host
execution to the stable adapter, freeze remaining case preflights, verify actual
primary identity/current prices, then run and review cases without automatic
paid retries. Keep R/N/U/S/P open until their actual evidence is complete.

## Document live-run preparation — 2026-09-24

Starting source `076dc7ba`. The independent stable runner now connects the
real answer/memory host path to the durable stable-budget adapter, using only a
fresh fixture database. D1/D2/D4 preflights freeze actual generated PDF/Word/CSV
bytes, production-reader output, prompt and the existing acceptance criteria.
They do not supply the model with expected answers. Unsupported content is
really rejected, and OCR is disabled so no secondary vision call can occur.
Network egress is limited to the configured DeepSeek completion endpoint.
The sole real-profile access is read-only primary configuration and required
crypto material; no conversation/file inspection, startup or migration.

Official pricing was fetched directly on 2026-09-23 UTC and reviewed: legacy
`deepseek-v4-flash` is an alias served by V4.1-Flash, with peak cache-miss input
$0.30/M and output $1.20/M. The runner preserves that alias disclosure and uses
peak rates conservatively; usage estimates are not a provider invoice. Pricing
snapshot is stored in the canonical evidence directory and expires by UTC day.

Offline loader/preflight/accounting checks: **42 passed, 3 opt-in live skipped**;
Ruff passed. No model call in preparation. The following live batch must append
actual results and semantic review separately; native attachment/layout flows
remain unverified. Existing historical runner and contract hashes are unchanged.

The first opt-in invocation stopped before any request: the harness's decorated
turn omitted the required conversation/message parameters. Ledger verified still
0/36. Corrected the harness signature and added exact-runner offline smoke cases
for all three documents: **3 passed**, including persisted answer, guarded
reservation and refusal to repeat. This was a harness failure, not a model
outcome; no paid retry or refund occurred. Actual results follow separately.

## Actual document batch and review — 2026-09-24

Executed source `3ed71fde8fdfb38374189a13f76dfa43e2ef5361`, exact runner hash
`219bdbeac6a37b148ab16657a42560b4d1e0bdda382a8a65ea3359f22a0dae5f`.
The opt-in host test produced three persisted answers (**3 execution checks
passed**, 10.99 s). This is not three quality passes or native UI acceptance.
All requests and usage were durably recorded, with no retries or unknown usage.

Source-grounded semantic review, kept separately from unmodified raw outputs:

| Case | Actual result | Disposition |
| --- | --- | --- |
| D1 PDF | Required facts and page 1/3 references correct, but calls the blank page 2 missing and the document structurally incomplete. | **Failed**. Extracted-text absence does not prove physical-page absence. Repair source-completeness communication before acceptance. |
| D2 Word | Correct paragraph 3 deadline change, paragraph 5 added action, unchanged owner/action, no invented calendar direction/duration. | Core criteria pass; unnecessary speculative zero-based-locator advice noted. Native file opening still open. |
| D4 mixed inputs | Keeps Cedar/Mira and CSV provenance; unsupported input honestly rejected without invented content. | Core criteria pass; overbroad side remark about single-row statistics noted. Native mixed-attachment retention still open. |

Canonical evidence directory now contains `S2-D1/D2/D4-preflight.json`, the
actual document bytes under `document-inputs/`, their `*-result.json`, three
request input/response/accounted triplets and `document-semantic-review-v1.json`
with result hashes. This review is by the primary coding agent, not independent
human/security acceptance. All 12 IDs remain in the denominator: two core passes
with caveats, one failure, nine not yet run; R/N/U/S/P remain open.

Current independent grant: **3/36 calls, $0.30 reserved**, conservative peak-rate
usage estimate **$0.0035988** (not invoice); previous 32-call pilot unchanged.
D1's frozen per-case 1-call cap is consumed. **Do not silently reset/reallocate
it or rewrite its preflight to retry.** First repair/reproduce offline; any paid
retest requires an additive reviewed input revision and explicit budget decision.

Next bounded batch: reproduce PDF completeness loss through the real attachment
entry point and add honest page-inventory metadata without claiming visual
inspection. Keep original frozen baseline evidence. Then continue remaining
registered cases within their unused case caps, followed by isolated native and
packaged acceptance. No tag, new beta, Publish, real-data or installed-app change.

## PDF attachment completeness repair — 2026-09-24

Starting source `b4bd9fff`, clean worktree. An actual multipart upload to
`POST /api/v1/extract` reproduced the absent page inventory; new offline
regressions initially gave **4 failures, 1 pass**. The all-empty PDF already
remained empty and was not promoted to readable content.

The attachment service now prepends a bounded parser inventory: physical page
count, one-based page numbers without native text, and explicit limits on what
this means. No native text is **not** proof of a missing page, visual blankness,
or document incompleteness. Scan/OCR partial-read notices are retained separately;
this metadata never certifies that all content was read. Empty extraction stays
empty, lists stop at 64 with count/omission metadata, the existing attachment
character cap and partial flag remain in force, and compression cannot rewrite
the PDF source. Page 1/3 source text and locators are byte-preserved after the
inventory. No OCR/model/network permission was added.

This repair is in the real ephemeral attachment path, not the frozen low-level
`_extract_file` baseline helper. Historical helpers, input hashes, preflight,
failed answer and checker are deliberately unchanged. A later D1 repair attempt
must use the real attachment extraction result in an **additive** preflight;
rerunning the old harness would still feed the old text-only baseline. Library
ingestion is a distinct path and is not claimed repaired by this batch.

Verification: real attachment/API, page locators, extraction and frozen-input
selection **69 passed** (4.93 s); Ruff passed. These are source-level offline
checks, not proof that the model now answers correctly or that native UI works.
An optional single-test evidence run archives the actual repaired API response
as `pdf-attachment-repair-v1.json` with input/source/test hashes; it never changes
the baseline files. No paid calls in this batch; budget remains **3/36, $0.30
reserved**. The original D1 failure and all five release gates remain open.

Next: continue the unused fixed-case allocations (D3 and research/memory), and
prepare the additive D1 retest/budget decision without resetting any ledger.
Do not label the offline repair as a passed live case or cut another beta.

Evidence run completed on committed source `16576258`: **1 passed** (0.94 s),
`pdf-attachment-repair-v1.json` SHA-256
`7d22912ae508bed306307c6847afd61ddbfeafbb1d382f39f950b1d41f9bd2a4`.
Original failed D1 result still hashes to
`047a8d919c9cc0c769c4ff88f605a7ad787976eaaa7cd2c0dfc3f91ecd2fa55f`.
Ledger reread confirms 3 requests / $0.30 reserved; working tree clean before
this documentation-only evidence annotation.

## CSV deliverable preflight — 2026-09-24

Starting source `cb404551`, clean worktree. Added D3 to the stable document
runner, without altering the frozen historical contract or earlier preflights.
The input CSV passes through the production structured reader; the model gets
the original task and permission to write/read only `totals.csv`, not expected
totals or review notes. Real workspace executors run behind an additional exact
path allowlist in a disposable directory. No arbitrary file read or shell tool
is offered. The runner archives the actual output, parses it independently,
checks successful tool readback and reopens its real artifact/manifest pair.
Missing-value/refund explanations still require separate semantic review.

Offline exact-runner and preflight checks: **13 passed** (4.00 s), using scripted
provider replies only; Ruff passed. D3 uses three requests in the scripted happy
path, within its already frozen four-request cap. Actual model behavior may
differ and is not retried automatically. Canonical ledger verified 3/36 before
execution. Official DeepSeek pricing fetched again on the same UTC day; reviewed
peak rates still match the existing same-day pricing snapshot. Live results must
be appended after execution; no claim of D3 acceptance from these unit checks.

## Actual CSV result and bounded repair — 2026-09-24

Executed source `4e0c06c9df87e80388aec3475fc069353fe62748`. D3 used requests
4–6 and **failed**: no `totals.csv` was created. The actual write call omitted
`path`; the exact-path confirmation callback refused it, and a subsequent read
also lacked its path. Final response honestly disclosed the failure, but a code
block is not the required reopenable artifact. The answer computed known USD
12.00/CNY 23.50 totals and retained the -1.00 refund, yet incorrectly inferred
the actual USD total must be >=12.00 despite an unknown amount/sign. It called
Pending row 3 without clarifying data-row versus physical-row numbering (CSV
line 4 with header). D3 is not accepted on either delivery or factual review.

Important causal qualification: the harness replaced production descriptions
with abbreviated descriptions that omitted `args` hints. The actual submitted
schemas had empty properties. Production descriptions did include `{path}` /
`{path, content}`, so this is **not an unbiased full-production-description
measurement**, nor proof the native app necessarily behaves identically. A
separate reproducer using actual `_arslan_tools()` confirmed that production
structured schemas were also missing these required fields. Keep the paid
failure and qualification; do not relabel a revised harness as the original run.

Seven offline reproducer failures preceded the repair. Changes now:

- Read/write file schemas declare required typed path/content parameters.
- Malformed read/write arguments fail with `invalid_file_arguments` before
  confirmation or file I/O; never report missing parameters as a user decline.
  Existing scope, secret/symlink checks and valid-write permission remain.
- The stable runner filters actual production descriptions rather than
  inventing shortened substitutes. Its fingerprint now differs from the frozen
  D3 preflight, intentionally preventing an unreviewed repeat.
- Source-grounding guidance explicitly forbids inferring numeric signs/bounds
  from missing values and asks for clear header-inclusive row conventions.
  This is general guidance, not a verified model-quality fix or a hard oracle.

Post-repair exact runner/tool-loop/contract selection: **49 passed** (29.33 s).
File executors, permission grants, workspace boundaries, native schemas, artifact
storage and source-output selection: **107 passed** (5.11 s). Ruff/whitespace
passed. Existing Starlette warning and one reported aiosqlite closed-loop
delivery suppression retained; no test outcome affected. No broad CI claim.

Raw preflight and result are unchanged; separate review:
`S2-D3-semantic-review-v1.json`. Result SHA-256
`1514bcf65269d803cb0f6cc601d9510ea61dfb444dc8ad06e1088f136495c204`.
No artifact file/manifest is invented to fill the missing deliverable.

Budget now **6/36 requests, $0.60 reserved**, conservative peak-rate usage
estimate **$0.0078594**, not an invoice. D3 has 1/4 unused case calls, not enough
for the tested three-step flow; D1 has none. Do not silently repurpose unused
case caps, reset ledgers or automatically rerun failures. Future repair retests
need an additive preflight and reviewed accounting decision preserving all six
reservations. Eight untouched research/memory cases retain their allocations.
Next batch should progress those cases; R/N/U/S/P remain open. No tag, push,
Publish, installed application or real user-data change in this batch.

## Project and confirmation memory preflight — 2026-09-24

Starting source `e62e2799`, clean worktree. Added stable M1/M2 inputs and a real
host runner reusing the historical case semantics, actual migration/activation,
memory repository and scoped task context in fresh synthetic databases. Two
same-name projects have distinct IDs; only A gets its confirmed orange rule.
The blue global preference begins as extractor-proposed, then a user revision
confirms green. Each before/after turn is persisted separately; review criteria
are not supplied to the model. No external tools, secondary provider or real
conversation input is offered. All calls route through the same durable ledger.

Initial offline run caught a harness callback-shape error before any paid call;
fixed by passing the task service's required event emitter, not the event list.
Exact-runner/context-boundary checks then **3 passed, 2 paid tests skipped**
(3.83 s). They inspect actual request payloads, not just scripted answer text:
project rule absent from B, proposed blue absent, confirmed green present.
These assertions do not grade live answer quality or native interaction.

Ledger checked at 6/36, $0.60 reserved. Official pricing re-fetched on the same
UTC date; conservative rates still match the stored same-day snapshot. M1/M2
each retain their original two-call allowance. Freeze their additive preflights
and runner fingerprints before live execution; no retries or budget reallocation.

## Actual M1/M2 memory outcomes — 2026-09-24

Executed source `b1c52182023a97804e753f7a11564101eee80f18`; two execution checks
passed in 10.53 s, using exactly requests 7–10 (no retries). This is not two
quality passes. All four answers and original memory revisions were persisted.

- **M1 core criteria passed.** Project A uses the confirmed orange rule; distinct
  same-name project B explicitly reports unknown without inheriting it. Actual
  request 7 includes the rule and request 8 excludes it. No invented project
  status or remembered fact was observed.
- **M2 memory boundary passed, overall case not accepted.** Proposed blue stays
  out of requests 9/10; confirmed green appears only after user revision, and
  the before/after answers reflect this. However the requested one-line style
  brief becomes multiple paragraphs with a made-up auth-refactor/certificate
  example. The model labels it an example, so it is **not evidence of memory
  leakage or fabricated remembered history**, but it does not meet the frozen
  concise useful brief/no decorative project facts criterion. Its HTML green
  span also does not prove actual native colored rendering.

Separate semantic review with raw result hashes:
`memory-M1-M2-review-v1.json` in the canonical evidence directory. This is the
primary coding agent's review, not independent human/security acceptance.
No prompt tweak or paid rerun was performed after seeing the outputs. M2's
two-call allocation is consumed, and the original result remains immutable.

Current grant: **10/36 requests, $1.00 reserved**, conservative peak-rate usage
estimate **$0.0117474** (not invoice), old 32-call pilot separate. Three cases
have core passes (D2/D4 with caveats, M1), three remain unaccepted (D1/D3/M2),
and six have not run (R1–R4/M3/M4). Native flows and R/N/U/S/P remain open.

Next bounded batch: deletion/summary regeneration and interrupted-task evidence
(M3/M4), then remaining public-research cases. Consolidate repair retests under
an explicit accounting/preflight revision after baseline gaps are known; never
silently reset a case counter, alter old evidence or increase the authorized
36-call/$5 global ceiling. No beta, tag, push, Publish or installed-app change.

## Deletion and summary regeneration preflight — 2026-09-24

Starting source `6c38dbd0`, clean worktree. Added M3's original synthetic violet
preference, source message, old summary, deletion, real summary regeneration and
follow-up heading request to the stable guarded runner. Original displayed
chat must remain; eligible model context must not reuse the deleted preference.
Summary calls also use the same case/global ledger. The existing summary cap
may trigger one additional compression call, so the frozen M3 three-call ceiling
covers at most two summary calls plus one answer, never automatic retries.

Exact-runner/context tests: **4 passed, 3 paid opt-in skipped** (4.82 s), Ruff
passed. Offline tests inspect both summarizer and answer payloads, retain the
visible source message, and verify old-summary removal. This proves harness and
context boundaries only, not real-model semantic quality or native deletion UI.
Canonical budget remains 10/36, $1.00 reserved before execution. Official pricing
fetched again on the same UTC day, matching the existing reviewed snapshot.
Freeze M3's additive inputs/runner before spending; M1/M2 are not rerun.

## Actual M3 deletion outcome — 2026-09-24

Executed source `87ac31e2d09c89f10adb318739a46067cb9ecb74`; one execution
check passed (5.11 s), requests 11–12 only. No extra compression or retry was
needed. Actual request 11 contains only the retained inventory-report messages;
both that summary and request 12 exclude the deleted preference and old summary.
Original displayed-chat row remains in the isolated DB. The final answer says
no color preference is available and supplies a neutral Inventory Report heading.
Separate semantic review found no direct or paraphrased reuse of violet.
**M3 core criteria passed**; native deletion UI remains untested. Extra summary/
status/date text is a terseness caveat, not a deleted-memory reuse finding.

Evidence: `S2-M3-regeneration.json`, per-turn/raw request records and
`S2-M3-semantic-review-v1.json`. Raw result SHA-256
`e22951e9f7712c0d702fa8fe8dcca7a3d20ccd2f7a5aeb9708203d466c701580`.
The coding agent reviewed the outputs; this is not independent human/security
acceptance or a claim of native visual presentation.

Ledger now **12/36 requests, $1.20 reserved**, conservative peak-rate usage
estimate **$0.0132183** (not invoice), with the old pilot untouched. Current
task outcomes: four core passes (D2/D4 with caveats, M1/M3), three unaccepted
(D1/D3/M2), five unrun (R1–R4/M4). Preserve M3's unused call; it does not silently
increase any other case's allowance. Next: bounded interrupted-task M4 or public
research cases, then explicitly reviewed repair retests. R/N/U/S/P stay open;
no tag, beta, push, Publish, installed-app or real user-data changes.

## Abrupt process recovery rehearsal — 2026-09-24

Executed source `8731023ef46960f2fdbe09bd45916e441c09ddb2` with the new
`tests/server/test_stable_process_recovery.py` opt-in harness. Each scenario
uses a fresh synthetic HOME/profile and two independent Python interpreters.
The first commits a task/checkpoint and fsyncs a synthetic report, then exits
via `os._exit(73)` without normal cleanup. The second opens that profile using
production storage initialization and task repository code. Network connection,
binding and DNS operations are denied by a child-process audit hook.

Both actual subprocess scenarios passed (**2 passed, 1.55 s**):

- **Completed write receipt:** saved artifact reference/checkpoint survive;
  recovery changes the task to `waiting_user/process_interrupted`, creates no
  extra attempt and requires explicit resume. Identical write intent is refused.
- **Write persisted, receipt absent:** action becomes uncertain. Explicit resume
  alone is refused until trusted read-back supplies matching file evidence;
  empty evidence is refused. After reconciliation, identical write is refused.

In both cases the file's bytes, inode and modification timestamp remain unchanged.
Task budget identity persists, with synthetic request counters going 1→2 only
after explicit resume; tool/token/artifact accounting also remains charged.
The final state still requires acceptance review, not automatic success. The
19 adjacent repository regressions passed (0.73 s), and Ruff passed. A pre-freeze
run also passed both scenarios (1.49 s); it is not counted as additional coverage.

Evidence under the canonical directory: `process-recovery-v1/completed.json`
SHA-256 `aa7ad7e5cbfdfae739f50a52237e45320ed40116c2ac10bb5e08cc189ab859df`,
and `process-recovery-v1/uncertain.json`
SHA-256 `14c6c86066db9af773b0993b2da73f83c9e7a4441d36c60005d49b19ca67b12d`.
Each records source and harness hashes, child exit codes and verification scope.

**Boundary:** this exercises real process termination and repository durability,
but the task, report, budget increments and trusted reconciliation are synthetic.
It does not exercise a live model, the full task-service/host dispatch, native
app lifecycle, user-facing recovery controls or signed package. Calling the
repository recovery function directly does not certify the application's whole
boot path. It is also not a power-loss durability test. **M4 remains unrun**;
these checks supplement rather than replace its frozen task acceptance.

Ledger independently rechecked: still **12/36, $1.20 reserved**, zero paid calls
this batch; original case caps and failed outputs unchanged. No product-code
change was necessary for these repository boundaries. Next bounded batch:
freeze the actual M4 host/resume inputs and guarded runner, preserving this
separate process evidence, or execute the already prepared public-source cases.
Do not repeat these offline tests as a substitute for the five remaining real
cases. R/N/U/S/P remain open; no release/tag/push or installed-app change.

## Actual public-conflict task R2 — 2026-09-24

Executed source `575861dbf84bc367c6ca0a883ed9d7577e4dc02a`. Added an exclusive
`S2-R2-runner-plan-v1.json`, preserving the original public-input preflight,
contract and four-request allocation. The additive prompt makes the existing
save/reopen criterion explicit (`comparison.md`), supplies the frozen URLs and
does not supply scientific expected answers. Only actual production web/read/write
tools are offered, restricted to those URLs and that synthetic relative path.
All source bytes must match their archived hashes. Model and tool results retain
their actual raw records; no excerpts or scripted responses enter the live run.

Exact-runner smoke check **1 passed, 1 paid opt-in skipped** (1.22 s), Ruff passed.
Two no-model production fetches matched the archives before spending. Official
[DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/) was reviewed
again at 20:41 UTC, 2026-09-23; same-day stored peak rates and alias disclosure
remain valid. The environment uses its existing HTTPS proxy: source-address
pinning is delegated to it and recorded, not claimed independently verified.

Actual run: **1 execution check passed** (14.37 s), requests 13–16, no retries.
Both complete extracted abstract pages and receipt hashes are present in the
next actual model request, with no extractor truncation. The actual Markdown
file was written, read back and reopened via its owned artifact/manifest; direct
source links remain present. This is neither native file opening nor a full-paper
read. Raw source bytes exactly match both preflight hashes.

**R2 is not quality-accepted yet.** The values, units, baseline/variant distinction,
version dates and retrieval dates are correct; the answer preserves the two
methods, attributes the 5-sigma discrepancy and does not choose a winner or claim
current consensus. However, it labels SH0ES's uncertainty “1-sigma-like” although
that interval convention is not explicit in the inspected abstract. It also
infers different actual systematic-error treatment from differences in reporting
detail. These are unsupported source attributions, not a claim that the full
paper's statistical convention is necessarily wrong. Preserve the uncertainty
as stated and leave undisclosed comparisons unknown. Excess length is a separate
usability caveat. Execution success must not hide these factual-scope findings.

Separate review: `S2-R2-semantic-review-v1.json`; original outputs unchanged.
Result SHA-256 `35aff0e3e44d7952501d02f0039ab65ca52203230a74b19096907fa35582c088`;
saved Markdown `9c107d0292b7f7e95446a153b853ce1d738aea083bb19bb83296068774a6dcbc`.
The coding agent reviewed source support; no independent specialist sign-off is
implied. No product prompt was tuned or paid attempt repeated after this output.

Ledger now **16/36 requests, $1.60 reserved**, conservative peak-rate usage
estimate **$0.0228231** (not invoice). R2 has consumed 4/4; old pilot remains
separate. Four cases have core passes (D2/D4 with caveats, M1/M3), four remain
unaccepted (D1/D3/M2/R2), four are unrun (R1/R3/R4/M4). Next: remaining original
cases, then additive repair reviews and a cumulative accounting decision within
the authorized ceiling—no silent case-cap reset or output replacement. R/N/U/S/P
remain open. No beta, tag, push, Publish, native installation or real-data change.

## Actual bilingual research task R4 — 2026-09-24

Executed source `7780a7311612bbcddc3bb9a7eb14764aa9e5af0a`. R4's original prompt
and both same-commit OpenSquilla READMEs were frozen in a new exclusive preflight
and additive runner plan. The supported 40,000-character read is requested for
each long source; no scientific/project expected answer is supplied. R2's original
records remain untouched and its consumed allocation is not reused. Changing the
shared runner invalidates its old fingerprint for future execution, not history.

Exact-runner offline checks **2 passed, 2 paid opt-in skipped** (2.25 s), Ruff
passed. Both production preflight GETs matched pinned raw-body hashes. The official
pricing page's browser fetch timed out; direct HTTPS retrieval succeeded and
confirmed the same UTC-day reviewed rates/legacy alias. Existing system proxy
delegation is disclosed. No credentials are printed or source writes authorized.

Actual result: **1 execution check failed** (22.87 s), requests 17–20. Both pages
were fetched successfully with no extractor truncation (33,376/18,871 characters),
and their complete extracted text plus receipt hashes reached actual requests 18
and 19. The model wrote a 7,918-byte comparison and read it back successfully.
Afterward the 64,000-character loop-history bound removed the English source from
request 20. The model requested it again; the harness refused the duplicate and
the next model call was blocked before reservation/HTTP by R4's four-call ceiling.
No final answer was persisted. No fifth call was charged and no retry was run.

**Important qualification:** the harness banned *all* duplicate fetches, whereas
the prompt only forbids retrying failed URLs. Reopening a successful source after
context eviction can be legitimate. The restrictive guard and short fixed cap
therefore affect this outcome; do not label it proof that production cannot finish
the task. Correct that harness rule before any additive repair attempt, retaining
the original trace and accounting. Investigate bounded source retention separately,
without simply widening budgets or claiming a source is still in model context.

The live test's final-answer assertion preceded artifact archival. The actual
temporary workspace file and original manifest were therefore copied unchanged
into the canonical evidence directory after failure. A separate production
`artifact_store.read_owned` check reopened the real artifact and verified identical
bytes and hash. This salvages evidence, **not the task's acceptance status**.

**R4 remains not accepted.** Its locality distinction and bilingual classifier
quotations are correct; the same-commit sandbox descriptions genuinely differ,
so that discrepancy is not invented. However the report falsely claims that the
Chinese README omits V1/V2 parallel reporting and the device/install-ID distinction:
both are explicitly present in that source's lines 338–339 and 362–369. Both full
texts were available when the report was written; later compaction does not excuse
this factual failure. Different translated text lengths do not prove omissions.
The conclusion also mandates the more conservative sandbox account without
runtime/code evidence; keep the discrepancy unresolved instead. Excess length and
overclaiming completeness from parser output are additional caveats.

Evidence: `S2-R4-result.json`, `S2-R4-comparison.md`, `S2-R4-original.manifest.json`
and separate `S2-R4-semantic-review-v1.json`. Result SHA-256
`66d4521669066f83ba0fe83ac68af3e4035683d3dd6295c44eddbdf8c058da79`;
artifact `02e3a850463558586f6d359358b42cbeb9713f7f5a04035e7457ac4f11bbff3f`.
No model claim is substituted for these readback checks; native opening and
independent acceptance remain untested.

Ledger **20/36 requests, $2.00 reserved**, conservative peak-rate usage estimate
**$0.0475377** (not invoice). Four core passes, five unaccepted (D1/D3/M2/R2/R4),
three unrun (R1/R3/M4). No silent cap reset or paid repeat. Next bounded batch:
correct the documented harness limitations for untouched cases, finish their
baselines, then review additive repairs and cumulative accounting within the
authorized ceiling. No beta/tag/push/Publish, installed-app or real-data change.

## Research harness correction and actual R3 — 2026-09-24

Executed source `532fd2aa2288e0ee4dea4a245dff3e5894177870`. Corrected the two
documented harness limitations before starting untouched R3: successful pinned
sources can be genuinely refetched within unchanged model/task budgets; failed
URLs and changed bodies still cannot retry. Every refetch verifies actual bytes,
not a fabricated cached-read receipt. Partial files/manifests are now archived
before execution assertions, even when the final response fails. These changes
do not reclassify or rerun the earlier R2/R4 baselines.

Offline correction checks **11 passed, 3 paid opt-in skipped** (3.38 s): successful
refetch, no retry after transport/HTTP/hash failures, no unlisted URL access,
and partial-artifact retention on final-model failure. R3 received the original
hypothetical old-advice prompt and two full pinned README URLs, plus commit/date
metadata already in the frozen manifest (no expected migration answer). The
additional prompt-metadata check **2 passed** (1.28 s); Ruff passed. Both actual
preflight GETs matched archived hashes. Direct official pricing retrieval again
confirmed the same-day peak rates after browser fetching timed out.

Actual run **1 execution check passed** (22.19 s), requests 21–24 only. Both real
source reads reached request 22 with their complete extractor outputs and receipts;
the report was written, read back and reopened as an owned artifact. Final answer
persisted. This is not a semantic pass: **R3 remains not accepted**.

- It correctly contrasts LightningStore/span/tracer with Trainer, API Gateway and
  Rollout Controller, keeps the advice hypothetical, and separates supplied commit
  dates, retrieval time, article dates and unknown release date.
- It nevertheless asserts that v0.x and v1.0 are not interoperable. Two READMEs
  and a refactor notice do not prove compatibility **or** incompatibility. The
  frozen criterion requires this to remain unknown pending targeted checks.
- It accurately notices damaged installation text. Investigation confirmed a
  production reader defect: raw `text/plain` README was parsed as HTML, so the
  literal `<this-repo>` placeholder swallowed following installation commands.
  `truncated=false` described the later character cap, not a lossless parser.

## Plaintext README repair, without paid retry — 2026-09-24

Four offline reproducer failures (three existing HTML cases passed) preceded the
fix. `_fetch_text` now preserves bodies declared `text/plain` or `text/markdown`,
including literal placeholders and code; HTML/unspecified content retains article
extraction. No URL-extension trust shortcut, fetch-permission change or limit
increase was introduced. Executor character caps, untrusted framing and matching
source receipts remain in place.

Post-repair reader/bounds/framing/pinning/SSRF/executor/inventory selection:
**84 passed** (1.02 s), Ruff and whitespace checks passed. Committed repair source
`4112a294fe23bf5d53c9018b32d1d01a22bfcdf2`; **8 plaintext checks passed** (0.05 s),
including the actual archived current README. Its original raw text and installation
commands now reach the real tool-feedback envelope unchanged. That evidence uses
archived bytes, not another live fetch/model or native UI acceptance.
`plaintext-readme-repair-v1.json` SHA-256
`f7cecfcfabf565291b2f2cd6b10f4c34839fd944e3790b6f87c44f9b22380dd8`.

Separate R3 review: `S2-R3-semantic-review-v1.json`. Original result SHA-256
`d7d564098fc7c3a255569e999846d8a1ff916ac03c7b6be7b8d7c994a1b6a0bc`;
saved report `788b688608f31bc127aaf6a38af1c67ea936b3033b70aefd115863c834a55ce1`.
No baseline output was rewritten and no paid repair attempt was made. A future
attempt must distinguish this repaired raw-text delivery from the older parser
evidence; earlier untruncated-extraction checks do not certify losslessness.

Ledger **24/36 requests, $2.40 reserved**, conservative peak-rate usage estimate
**$0.0629238** (not invoice). Four core passes; six unaccepted (D1/D3/M2/R2/R3/R4);
two unrun (R1/M4), still allocated 5 calls each. Remaining global slots are not
permission to reset exhausted case caps. Next: complete those untouched baselines,
then explicitly review repair inputs/accounting and remaining native/packaged gates.
No beta, tag, push, Publish, installed-app or real-data changes.

## R1 first-delivery repair and actual comparison attempt — 2026-09-24

Before spending, archived R1 bodies replayed through the real extractor/feedback
envelope totalled 67,131 conversation characters with a minimal user message.
The 64k rolling-history window discarded the first new source before any model
had seen it. This is distinct from older-source eviction after a previous read.

Repair source `cc5ec1f3e10acb1e9cd2a24528ef42e3de82ef6f` temporarily groups a fresh
tool-feedback batch for its first delivery, only when the batch is at most 96k
characters. The existing 64k rolling target resumes on subsequent requests; larger
batches keep existing eviction and explicitly warn about potentially unseen
content. Opaque native provider pairs retain their existing indivisibility.
The exact current user request is restored at user priority if evidence eviction
removed it, without promoting its text to a system instruction. Thus 96k is not
a global request-size promise: the original user request, system/schema overhead
and existing opaque-provider retention are separate. Task/request/cost limits do
not change. The paid harness still enforces its 100,000-byte payload ceiling.

Scoped fresh-batch/runtime/native/extractor checks initially **49 passed**;
runner/live-opt-in/native/read checks **14 passed, 4 skipped** (5.16 s). After
adding current-request retention, **26 passed** (14.77 s), including fresh batch,
Gemini roundtrip, native loop and scripted research runners. Ruff passed. Three
actual preflight GETs matched pinned hashes. Same-day official pricing again
confirmed the peak input/output rates; configured proxy pinning delegation remains
disclosed. Untouched R1 alone received an additive input/runner freeze, preserving
all previous baseline evidence and caps.

Actual R1 execution: **1 failed** (24.33 s), requests **25–26**. Request 26 was
**79,810 bytes** and contained all three full raw READMEs, matching receipts, and
the original task. This live evidence supports the first-delivery repair. It does
not make R1 pass: no `comparison.md` was written, read back or registered as an
owned artifact. The provider returned no native tool calls and instead emitted a
textual `write_file` object. Unescaped quotes around `auth mode = "none"` made the
object invalid JSON (offset 4436), so the old parse-dependent output guard missed
it and it became the final answer. No write was secretly executed.

The proposed content distinguished training, routing and semantic coding; marked
benchmarks as self-reported; correctly separated Serena GPL application from MIT
SolidLSP; and retained direct fixed-commit sources. However, it claimed Serena
shell execution remains enabled while basic tools are disabled in Codex/Claude
Code. The source's Basic Features section includes `execute_shell_command` in
that typically disabled set: the exception is unsupported. Its offline-fit
recommendation also fails to explicitly preserve the classifier-versus-provider
inference boundary. It is much longer than the requested brief comparison. These
are not exhaustive independent claim checks; R1 already fails delivery and scope.

## Malformed protocol output guard — same batch, no paid retry

Offline reproduction: **4 failed, 2 passed** (0.84 s). Correction source
`3d53fe07` rejects a recognizable tool-protocol object prefix even if subsequent
JSON is malformed or truncated. This is an output rejection only: it does not
repair/execute textual calls, change dispatch parsing, or grant write permission.
The existing bounded safe-synthesis path remains responsible for an honest final
answer. Ordinary JSON and prose still pass the targeted regression.

After correction, **24 passed** (11.25 s): malformed protocol, native loop,
fresh-batch delivery and Gemini roundtrip; Ruff and whitespace checks passed.
The exact archived request-26 response is now detected offline. This proves
guard coverage, not successful file delivery or semantic correctness on a paid
retest. Original R1 evidence is unchanged; no automatic model repeat occurred.

Review: `S2-R1-semantic-review-v1.json` in the canonical evidence directory.
Original result SHA-256
`161caabd3a2856686cc6df1315d9a70497c60d721c56fdb6f2120a2f43c12167`;
request-26 input
`d39309d6fbe9678719b61b3b25a574295b7dc84ab80891bd1f7d76f10f15ded0`;
response
`7629d3104b0bf42c38a83c9f72a7d195ac643df2109b4f83215751b0fb48d26c`.

Ledger **26/36 requests, $2.60 reserved**, conservative peak-rate usage estimate
**$0.0748554** (not invoice), no HALT. Four core passes; seven unaccepted
(D1/D3/M2/R1/R2/R3/R4); only M4 remains unrun. R1 consumed 2 of its original 5
slots; this does not authorize a silent baseline overwrite or best-of-N rerun.
Next bounded batch: M4's isolated real-model interruption/resume baseline, retaining
the separate deterministic uncertain-write evidence. Then review additive repair
attempts, remaining allowance, and native/packaged acceptance. R/N/U/S/P remain
open. No release candidate, tag, push, beta, Publish, installed-app or real-data
change was made.

## Actual M4 host, process interruption and explicit resume — 2026-09-24

Runner/source `ce63da570feacfc1e9bf929de7745fecc189c970`; unchanged five-call M4
allocation and original 36/$5 ledger. An additive preflight freezes the original
synthetic Cedar/Mira/Monday facts, an explicit three-line `brief.md` write/read
deliverable, source/revision citation and no-rewrite-on-resume requirement. No
expected answer is supplied beyond the source itself. Only read/write of this
isolated path and owned `task_progress` are exposed. Resume grants no new writes;
the production completed-action journal also remains active.

The exact runner was first checked with two real child interpreters and a
network-denying audit hook. Initial smoke failed because the fake adapter bypassed
production request accounting; this was a harness omission, not lost accounting
in production. Moving the double to HTTP transport retained the real provider,
adapter and task checkpoint chain: **1 passed** (4.02 s). Scripted usage moved
3→5 across processes, implicit and repeated resume were refused, and file/owned
artifact remained unchanged. Ruff and whitespace checks passed. This smoke is
not another live/model-quality result.

The authorized actual run used requests **27–31** only, official same-day peak
pricing rechecked before execution. The initial process (PID 27044) used four
requests: inspect progress/missing file, write, read back, final answer. It saved
a 174-byte, three-line brief with correct facts and source, preserved an owned
artifact, checkpointed the actual host state, and exited **73** via `os._exit`.
This is actual interpreter loss, not merely a caught exception or native-app test.

The second process (PID 27130) initialized isolated storage and recovered exactly
one task into `waiting_user/process_interrupted`. It made no model calls before
explicit resume; attempt count stayed one and the saved budget was identical.
Implicit `repo.start` was refused. Explicit `task_service.resume_turn` created
attempt two with the same budget ID. Request 31 inspected `task_progress` and
reopened `brief.md`; both succeeded, with no new write or changed bytes/inode/mtime.
The original artifact independently reopened with an identical hash. Product
request accounting moved **4→5**, with prior tokens/tools/artifact usage retained.

**M4 is not fully accepted:** there was no resumed final answer. A sixth model
request was refused **before reservation/HTTP** by the frozen five-call harness
ceiling, producing `LLM_ERROR/stable_budget_exhausted` and final
`failed/execution_failed`. No request 32 was made and no automatic retry occurred.
The subprocess ended 1 at the final-state assertion, after preserving its result.
This is a bounded-evaluation completion failure, not evidence of data loss,
duplicate writes, reset accounting, or inability of production to resume under
its different task budget. Do not silently widen the case after observing it.

Evidence: canonical `M4-process-v1/` contains before-crash, recovered-no-resume
and after-resume records, with source/runner hashes and distinct process IDs.
`S2-M4-semantic-review-v1.json` preserves this qualification. Artifact hash:
`7c62a9e35891d7cf50e08717837e956c22498b6a25f96681d1428bdfa4c8ba76`.
After-resume record:
`133f21892e13758368b8f24e8aeb69ec252bf3eb63212b8c2f38ed7165d748da`.
The synthetic profile and files remain isolated beside the evidence; no real chat,
installed application, user profile migration or external account was touched.
Existing deterministic uncertain-write evidence is complementary, not live M4.

All twelve baselines have now been attempted: **four core passes, eight not fully
accepted**, with original failures retained. Ledger **31/36, $3.10 reserved**;
conservative peak-rate usage estimate **$0.0805866**, not invoice. All calls are
accounted; HALT absent. Original pilot's 32 calls remain separate. The five global
slots remaining are not a reset of exhausted per-case caps or authorization for
unregistered retries. Next finite batch: consolidate demonstrated product blockers
versus harness limits, repair source-grounding/protocol-delivery gaps offline, and
freeze an additive retest/accounting plan before any further paid call. Native,
upgrade/package and integration gates remain open; none can be inferred from this
process check. No beta, tag, push, main merge or Publish.

## Bounded native-call correction — 2026-09-24, no paid calls

Starting source `457abd40`. The malformed-output detector stopped protocol
leakage, but an offline reproducer showed a remaining delivery problem: even
with native tools and request budget available, any textual tool request went
straight to tool-free salvage. It could explain a failure but could not perform
the requested save. Four new tests failed before correction (six existing
protocol/ordinary-text checks passed), including both valid and malformed text
and granted/declined write confirmation.

Correction source `0615c644967f3a9c3962aea1eae6d645f3dd9208` retains the native loop
for a bounded retry of *model output format*,
not an automatic execution of textual JSON. The rejected object is omitted from
the prompt instead of being echoed as an invocation example. A subsequent actual
native call must still resolve the tool, pass argument checks and receive the
existing permission confirmation. The same progress/no-progress and task budgets
apply; no model/provider or authority is changed. Forced/no-tool paths retain the
existing honest tool-free fallback.

Verification: initial focused group **25 passed** (12.71 s); expanded final group
**38 passed** (19.27 s), Ruff/whitespace checks passed. The groups overlap. Includes
an exact research-host runner with scripted provider replies that corrects a
malformed call and then really writes, reads back and reopens an owned artifact
in an isolated fixture; denial prevents execution; a two-request budget cannot
be extended by repeated malformed output. Existing native, fresh-batch and Gemini
roundtrip checks remain green. No paid model was called; fixture ledgers do not
alter the canonical 31/36 ledger.

Repair planning is consolidated in `stable-0.1.40-repair-plan.md`, separating
product defects from harness limits and preserving all original acceptance IDs.
The next bounded batch is generic source-grounding/brevity repair and runner
readiness; a new paid repair sweep requires an explicit accounting/authorization
decision before execution. No baseline has been relabelled passed, no native or
packaged acceptance is inferred, and no beta/tag/push/Publish occurred.

## Shared evidence-scope guidance — 2026-09-24, no paid calls

Implementation source `2ed10c995fb2c443dbf6329e618a9718ffc884f4` adds a shared
answer contract to both the normal host prompt and tool-free synthesis. It
distinguishes inspected source claims, inference and unknowns; requires matching
version/component/condition scope; rejects unsupported absence, compatibility,
statistical-convention and whole-workflow locality claims; and preserves requested
brevity without unsolicited invented project details. No case-specific expected
answer or evaluation oracle was inserted.

The synthesis path previously urged a decisive conclusion even with incomplete
evidence. That conflicting guidance is removed: it must answer the supported
portion and state specific gaps. Its reference digest is now framed as untrusted
external material. This is prompt guidance, not a new factual verifier or broader
tool authority, and does not prove that a live model will obey it.

Red/green wiring checks: **7 failed** before the change, covering six locale
configurations of the actual host and the synthesis fallback. After repair,
**51 passed** (16.32 s) across prompt wiring/cache, source links, file contracts,
native loop and malformed protocol handling. An additional disjoint group of
capability-inventory and exact synthetic memory-runner checks had **6 passed**
(4.71 s). Ruff and whitespace checks passed. Scripted providers are not real-model
quality evidence; none of the eight unaccepted baselines is promoted to passed.

Canonical paid ledger remains **31/36**, **$3.10 reserved**, with conservative
peak usage estimate **$0.0805866** (not invoice). No paid call, key/profile access,
native UI or package acceptance was performed in this batch. Next: freeze additive
repair inputs/checkers and accounting; obtain explicit additional paid authority
before the proposed repair sweep. Native and packaged gates remain open. No tag,
push, main merge or Publish.

## Native/package acceptance isolation prerequisite — 2026-09-24

Starting source `949edb22`; repair source `4168bf89`. The preceding user-facing
turn requested an additional independent repair budget; no answer has arrived.
The recurring heartbeat's old "0 calls" checkpoint is historical, not fresh
authorization. Canonical ledger was rechecked: **31/36, $3.10 reserved**. No new
paid calls or credential/profile reads in this batch.

Code inspection before native launch found that `fresh_install_check.boot`
copied the entire parent environment and only cleared three overrides. Replacing
HOME did not clear `ARSLAN_SECRET_KEY_FILE`: a nonempty inherited path could reach
a key outside the fixture, while the test suite's empty override could disable
the first-run key generation being checked. Other inherited runtime/profile
overrides and provider credentials also remained in the launched environment.
This was reproduced using synthetic sentinel values, not real credentials.

The acceptance launcher now constructs a minimal environment with isolated HOME
and TMPDIR, fixed system PATH and locale. It retains the deliberately poisoned
relative `ARSLAN_DATA_DIR=data` to keep testing the packaged sanitizer. It does
not change production key precedence or add an end-user startup restriction.
This is environment hygiene, **not an OS filesystem/network sandbox**; native
WebKit state and actual GUI behavior still need their own isolated verification.

Red checks: **3 failed** (two real launcher-environment captures, one missing
helper). Final scoped selection: **67 passed** (1.85 s), Ruff/whitespace passed.
The real source-bootstrap child generates a new key inside disposable HOME,
with network and synthetic foreign-key reads rejected by an audit hook. The
native executable was replaced only in the launcher unit tests; no app bundle,
native interaction, installation, Gatekeeper or complete fresh-install run is
claimed. Corrected an outdated script comment that called its existing native
executable launch a sidecar-only run; backend probes still do not prove drag/drop
or window movement.

Next unpaid batch: prepare a source-identified isolated native candidate and
exercise the finite gate-N core flows, without an installed-app replacement or
configured paid provider. Additive live repair inputs/accounting can be prepared,
but do not execute them pending the user's budget answer. All five gates remain
open; no beta/tag/push/main merge/Publish.

## First current-source native interaction batch — 2026-09-24

Built source `fcb5f2acacd1f188f631fc384e99dfa7803f3a55`, before any changes in
this batch. Existing locked dependencies, offline desktop npm install, production
web build (existing chunk warning), PyInstaller 6.21.0/Python 3.11.15 sidecar,
two Swift voice helpers, and locked/offline Tauri **debug** build. Sidecar selftest
passed all 15 imports/web assets plus the no-AGPL/no-database/no-secret scans.
The analysis TOC confirms 375 first-party Python modules came from this checkout,
not the sibling checkout supplying the shared dependency environment.

The local bundle is deliberately `Arslan-Acceptance.app`, identifier
`com.arslan.acceptance.stable0140`, in
`../stable-0140-native-evidence-20260924/`. It retains the source's
`0.1.40-beta.6` version; it is **not another released beta**, a final RC, or a
0.1.40 stable artifact. No Developer ID/notarization, no DMG and no standalone
compute runtime staged. Native checks on this development variant must not be
promoted to signed final-candidate/package acceptance.

Launched the real native executable with the minimal environment and isolated
`native-home-v1`; no provider was configured. CUA drove the actual macOS window,
not the browser fixture. Observed:

- Clean English onboarding, Chinese selection reflected in UI and native menu;
  desktop version/channel summary and preview/manual-install/backup warning.
- Created and edited synthetic project `Native acceptance Cedar`, entered its
  associated conversation; the complete Chinese summary survived process restart.
  Initial automation `typeText` omitted Chinese characters; replacing via paste
  saved the intended text. This input-tool issue is not recorded as a product bug.
- Selected frozen synthetic `notes.csv` through the native file picker. Selecting
  `notes.unsupported` subsequently showed the unsupported-type error while the
  CSV remained ready. This checks pre-send retention, not a completed mixed-file
  model task, persistence of unsent attachments, or HTML drag/drop.
- Added a project-only, local-only confirmed synthetic preference, corrected
  green to blue, inspected both revisions, then paused it and observed the paused
  state/enable action. No cloud permission was enabled. Deletion/model use is not
  established by these UI actions.
- Native File > Restore opened its localized ZIP picker and cancellation returned
  to the usable settings screen. No backup archive was restored. Normal native
  Quit returned exit code 0 after the second launch.

The initial acceptance helper failed despite a working app: its loose loopback
URL regex selected system proxy **7899**, not sidecar **64066**, then killed its
test child on health timeout. Repair `d3f3f623f03ce06af8a9f167057588d5ebf32e9b`
matches the exact Uvicorn listening line (including optional sidecar prefix).
Five regression failures before repair; final scoped packaging/isolation group
**72 passed** (1.81 s), Ruff/whitespace passed. Restart with the same fixture and
unchanged bundle selected actual port **64517**, PID **36608**. The repair changes
the probe only; it is not falsely claimed embedded in the earlier bundle.

After normal quit, read-only checks confirm one active synthetic project, one
paused project memory with revision history, database `quick_check=ok`, and zero
provider configs/messages/runs/usage rows. Bundle binary hashes, source identities,
fixture state and explicit unverified items are in `native-core-v1.json`, SHA-256
`31bbec57e44b185f9a515782406502ba524b6bf844c01ae7893f223f3a7f9327`.
The first source-path checker accidentally matched third-party `mcp/server`
paths; corrected to first-party TOC module names before emitting the receipt.
Raw local app logs contain disposable fixture credentials and remain private;
do not attach or publish them. No real profile/key/chat was read or migrated.

Gate N remains partial. Next unpaid batch can reuse this exact isolated bundle
and profile for the remaining native core flows; do not let default launch/open
discard its controlled HOME. Before new paid repair cases, still await the user's
additional budget decision and freeze additive inputs/checkers/accounting.
Canonical ledger remains **31/36, $3.10 reserved**, unchanged. No CI/tag/push,
installed-app replacement, main merge, Publish or new paid call in this batch.

## Native restore and relaunch evidence — 2026-09-24

Starting checkout `b070ee05`; reused unchanged development bundle source
`fcb5f2acacd1f188f631fc384e99dfa7803f3a55`, helper `d3f3f623`. No rebuild,
paid call, provider setup, CI, tag or installed-app replacement. XcodeBuildMCP
session defaults have no Xcode project/scheme; this is the existing Tauri bundle,
with CUA driving actual macOS dialogs. The original `native-home-v1` remained
stopped and its database hash remained unchanged.

Created a checksummed backup using `server.services.backup.create` on a stopped
synthetic clone: 19 members / 1,059,002 uncompressed bytes, no external key or
access token. **This is maintenance-API backup creation, not native export UI.**
The original key is a disposable fixture key, not a configured provider key.
Kept the backup and both rehearsal profiles under the existing private native
evidence directory. Edited the cloned project through the native UI to introduce
a distinct `RESTORE-V3-DELTA` marker before restoring the earlier backup.

Actual native steps: File > Restore, ZIP selection, extensionless original-key
selection, first stop/prepare confirmation, visible maintenance workspace,
restricted trial, second activate/restart confirmation, automatic native relaunch.
The new Chinese workspace served on port 49376 (previously 49234). Project list
initially excluded the restored archived project; selecting its archived filter
showed the original full Mira/Monday text without the temporary marker. Memory
showed the corrected blue preference as **需复核 / 一个项目 / 仅本地**. Normal Quit
removed both acceptance processes, leaving the separately installed running app
alone. No cloud approval or background task was enabled.

Stopped-fixture inspection confirms restored project archived, memory quarantined
and local-only, zero provider/message/run/usage rows, database quick checks okay,
all 18 non-database archive assets matching their hashes, activation completed
record present, and the pre-restore profile retained with its delta. Receipt
`../stable-0140-native-evidence-20260924/native-restore-v3.json`, SHA-256
`038db89fc2d1cba76cd1f4f3477a8faa89acfa7442e959a6d763ea3f4a2542b7`.

Retained the first v2 rehearsal and its automation failure rather than silently
replacing it. Its restore and backend relaunch completed (two startup ports, no
startup error, completed activation, intact previous profile). But the launcher
returned when the old desktop exited; the terminal session then cleaned up the
restarted descendants. A subsequent CUA `getApp` launched an acceptance instance
with default HOME, whose startup was refused by the already-running real
profile's cooperative lock. That refused window was quit; no personal database
was opened or migrated. The initially suspected product lock failure is therefore
**not established**. V3 keeps the launcher process group alive through native
relaunch and observes the existing app handle, without a default-home relaunch.
Future native recovery tests must keep this lifetime constraint as well as HOME
isolation. Do not post raw logs; they contain disposable fixture tokens.

This closes one positive native development-bundle restore path, not gates N/U.
No encrypted provider records existed, so credential rewrap is not established;
negative/interrupted native recovery, native backup export, installer/updater
upgrade and signed final-candidate checks remain separate. Next unpaid batch:
bounded negative/paused native recovery or remaining native interaction checks.
Paid retests still require the unanswered additional authorization; the previous
31/36 calls and $3.10 reservation are unchanged. No repeated budget reminder.

## Native checksum-mismatch refusal — 2026-09-24

Starting checkout `0a6b033b`, unchanged native bundle source `fcb5f2ac`, no build
or paid call. New disposable `native-home-negative-v4` cloned the stopped v1
fixture; no existing evidence/profile was overwritten. Registered the input and
expected outcome before launch in `native-negative-v4-inputs.json`. Corrupted
one non-database member of a copy of the known backup while leaving its manifest
unchanged: ZIP CRC/integrity remains valid, but the recorded content checksum
does not match. The original archive and disposable original key are retained.

CUA drove the real native ZIP and key pickers and stop/prepare confirmation.
The normal workspace was replaced by maintenance, then a Chinese **恢复已暂停**
warning explaining uncertain completion, no automatic retry, preservation and
explicit exit/reopen. No activation/success confirmation appeared. The recovery
menu was disabled and the normal backend child was gone. No candidate directory,
profile-switch journal, previous-profile directory or completed activation was
created. This is the expected fail-closed outcome for this negative input, not
an unexpected build/release failure.

After normal Quit, explicitly relaunched with the same controlled HOME and a
new log file (old log retained); the launcher stayed alive through the test.
The workspace was usable on port 50099, versus 49958 before refusal. The original
active Cedar project and full summary were visibly intact; the corrected blue
memory still showed **已停用 / 仅本地**, not restored/quarantined or enabled.
Normal Quit ended the acceptance processes; only then was its launcher stopped.
No default-HOME launch or interaction with the installed app occurred.

Stopped-fixture assertions compare project rows, memory rows and all revisions
to v1 exactly, check both database integrity and zero provider/message/run/usage
rows, verify 18 asset hashes, unchanged original-v1 DB hash, and absence of
activation/staging records. Receipt `native-negative-v4.json` in the private
native evidence directory has SHA-256
`7cc1c1832368cb448bbb662c41dcf215e63a66106abb4cdc80b7e8d4631aa1bc`.
Raw logs remain private. No unit test count is substituted for these observations.

This verifies one actual corrupt-archive refusal/reopen path on the development
bundle. It does not cover a wrong key, missing key, credential rewrap, choosing
pause after a successful trial, rollback after an interrupted switch, all locales
or the signed final package. Next unpaid batch can exercise that distinct
post-trial pause/rollback path on another clone; do not repeat this negative case
as new progress. N/U remain partial; all release gates remain open. Canonical
paid consumption is unchanged at 31/36, $3.10 reserved; the previously asked
additional-budget question remains unanswered. No tag, push, Publish or merge.

## Native post-trial pause and explicit rollback — 2026-09-24

Starting checkout `aa413ee8`; unchanged isolated development bundle source
`fcb5f2acacd1f188f631fc384e99dfa7803f3a55`. Created only the new synthetic
`native-home-pause-v5` clone, registered known archive hash and expected outcome
before launch. No provider/key from the real installation, model request,
rebuild or installed-app mutation. The native launcher permits recovery dialogs
before normal health, keeps its process group alive, and writes distinct logs
for prepare/reopen-paused/reopen-rollback instead of overwriting prior attempts.

Actual CUA-driven sequence:

1. Native ZIP/key selectors and first stop/prepare confirmation; restricted
   trial reported success, followed by the second activation consent dialog.
2. Selected **保持暂停**, acknowledged the pause warning and normally quit.
   The active path contained the quarantined restored candidate, the original
   profile remained at its previous path, and the pending operation record
   blocked normal startup. No completed activation was present.
3. Explicit controlled-HOME restart showed **资料恢复尚未完成**, offering
   **回退到原资料** or **保持暂停** before a normal workspace. Selected pause
   again: the localized startup-refused page remained, with no workspace or
   normal backend. Normally quit. The same operation, active directory identity
   and candidate database digest were unchanged — no implicit rollback/activate.
4. Another explicit controlled restart offered the same decision. Selected
   **回退到原资料**; startup then reached the Chinese workspace on port 51145.
   The active Cedar project/full original summary and blue **已停用 / 仅本地**
   memory were visible. Normally quit, then stopped only the owned launcher.

Stopped-profile checks establish original directory identity restored, original
project/memory/revision facts exactly retained, both DB integrity checks okay,
zero provider/message/run/usage rows, pending journal removed, and the quarantined
candidate retained separately with the exact pre-rollback database hash. The
original v1 fixture database is unchanged. Private evidence receipts:

- `native-pause-v5-paused.json`:
  `9e9bf62621f2f390015f2333f7fcd0ff9b990d92152c94c45ee4c6f0497ccfed`
- `native-pause-v5-declined.json`:
  `5889add9b59e5ad3761be77c170668f10635ecbef466979684ff23533ec6777f`
- `native-pause-v5-rolled-back.json`:
  `990310dec7c6b8df65304e3ad6530cab9572dd6e669302730ff04f3b43a608b9`

This is a real declined-finalization/reopen/consented-rollback path, **not** a
crash injected midway through directory movement or proof for every recovery
failure. No encrypted provider records existed. Wrong/missing-key native paths,
other native task flows, six-locale/narrow-window checks and final signed-package
upgrade/recovery remain distinct work. All acceptance processes have exited;
raw logs remain private. Paid consumption remains 31/36 and $3.10 reserved,
with no new authorization inferred. No large suite rerun, CI/tag/push/merge or
Publish. Next finite unpaid batch should address another remaining native path
or prepare frozen additive retests, rather than repeat these recovery paths.

## Offline additive-retest preparation — 2026-09-24

Starting checkout `4416312f`; preparation implementation committed as
`b2b37ee0ea4a1a4de479337ade9d5ed8b3f0b4c8` before generating the receipt.
Validated eight failed-case preflights and thirteen retained input entries;
captured unchanged criteria, original call usage, current runner hashes and
explicit remaining adapter/review dependencies. See the repair plan's read-only
inventory section. Private `stable-0140-repair-preparation-20260924/inventory-v1.json`
has SHA-256 `5da133748651aa5de5353b020051322909afb7146226b6507004b6626d07ef9c`.

This is preparation only: no new executable contract, authorization, model call,
credential access, source fetch, native run or semantic acceptance. Five small
offline integrity checks and Ruff passed; original evidence and budget remain
unchanged at 31/36 and $3.10 reserved. All eight runners are explicitly not ready.
D1 still needs an additive actual-attachment-API adapter rather than reuse of
the legacy low-level input; research/recovery need independently linked
accounting rather than reused old caps. Do not treat new directory names as a
budget reset. The additional-budget question remains pending without a repeat
prompt. N/U retain the previous partial native evidence, R/S/P remain open.
Next bounded unpaid batch may close a remaining native core path or implement
the additive offline runner/checker preparation, with no paid execution until
explicit additional authority and per-call accounting are in place.

## D1 real attachment context prepared offline — 2026-09-24

Starting checkout `ea6889f4`; new preparation/checker source
`feb8922dfd98fd4b846d3af0417b078e6018ace5`. The unchanged retained 1,173-byte PDF
was posted through the real isolated attachment REST API, not the historical
low-level helper. Its 698-character untruncated response now preserves the
physical-page inventory alongside exactly the old body text. Original user
request wording remains unchanged; expected answer facts were not added to the
prompt. Nine focused offline adapter checks plus one canonical retained-input
receipt check passed, with Ruff clean. No large suite was repeated.

Private receipt `stable-0140-repair-preparation-20260924/d1-attachment-v1.json`:
`f20b571931eab0aa540c10259bd2e80d3a6cbd3ed1803e59c0f6b0058162a2a0`.
Old ledger still hashes to
`20c988dcbcaf9977d268e6b1d880bbc8ba57d94aa1b41fa9593ef47b3049751a`;
31 calls and $3.10 reserved are unchanged. No real credentials, external source
fetch, paid call, native launch or release action occurred. This is only an
input-adapter preparation receipt; D1 remains unaccepted until authorized actual
output is reviewed. All gates retain their previous status. Next finite unpaid
batch should prioritize a distinct remaining native interaction (for example
synthetic memory deletion and restart) rather than repeat the completed
extraction or recovery paths. Keep controlled HOME and launcher lifetime rules.

## Native memory deletion and restart — 2026-09-24

Starting checkout `74d539c1`; same development bundle source
`fcb5f2acacd1f188f631fc384e99dfa7803f3a55`. Desktop and sidecar hashes still match
`native-core-v1.json`; no rebuild or installed-app replacement. Xcode session
defaults were unset; this is the existing Tauri bundle, not an Xcode project or
simulator run. Used controlled minimal HOME and CUA for all native interactions.
Created only a new disposable `native-home-memory-delete-v6` clone of the stopped
v1 synthetic fixture, registered expected outcomes before launch, and preserved
the original fixture. No real provider/secret/chat data was accessed.

Observed in the native Chinese UI on port 56312:

1. The paused project-local blue-heading memory was visible. Delete opened a
   confirmation identifying the content and explaining revision/index/derived
   removal while original chat history and old backups may retain original text.
2. Cancel retained the same paused memory. Opening the confirmation again and
   explicitly deleting it produced the empty-memory state.
3. Normal Quit exited successfully. Read-only stopped-DB checks found status
   `deleted`, version 4, cleared normalized/dedup hashes, one remaining revision
   with null body, no source/index rows, and two content-digest tombstones.
4. Controlled restart on port 56510 still showed the empty list. The original
   active Cedar project and full summary remained. Starting a project-bound
   empty conversation retained Cedar in the project/memory dialog and did not
   enable cloud-memory consent. No message was sent. Cancelled the dialog and
   normally quit; stopped only the owned launchers after child exit.

Before/after restart checks match project rows, deletion state/revision and
tombstones exactly; database integrity is okay, provider/message/run/usage counts
are all zero, and the original v1 database hash is unchanged. Private receipts:

- `native-memory-delete-v6-deleted.json`:
  `970399f107eaf1cd5d7079123a92afd3482ac2c8450837220d376c9129865fb1`
- `native-memory-delete-v6-restarted.json`:
  `90f23171645850560e8cb7aa881e103ca882a6c12664c76d97666ca1ae4b7a4f`

All acceptance processes/launchers exited. Raw logs stay private. This closes
the isolated native development-UI deletion/restart path, not final-package
acceptance, actual model non-reuse, old-backup reimport, or removal of derived
summaries that were not present in this fixture. R/N/U/S/P retain their other
outstanding criteria. Paid ledger remains 31/36 with $3.10 reserved, no new
authorization inferred or requested again. Next unpaid batch can address native
source/artifact opening or narrow-window/localized core-flow checks; do not
repeat the already covered deletion/recovery scenarios as new progress.
