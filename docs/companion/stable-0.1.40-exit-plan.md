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
| R — useful task outcomes | All original R1–R4/D1–D4/M1–M4 IDs have frozen inputs, actual outputs, reviewed conclusions, sources/artifacts and recovery evidence against their original acceptance. Keep failures and corrections; no best-of-N substitution or dropped cases. | Open: stable D2/D4 core criteria passed with caveats; D1 failed on a blank-page completeness claim. Nine stable cases remain unrun. R2 public inputs and long-read path are prepared, not yet model-accepted. |
| N — actual native core flows | On the candidate: identity/channel; conversation and restart; mixed attachment retention; source opening; artifact opening; project memory correction/deletion; cancellation and explicit resume; backup/restore UI. Verify narrow-window usability and localized safety/errors in supported locales; recheck changed surfaces rather than all historical screens. | Partial prior evidence: beta.6 icon switching, rounded corners and five pages at two sizes were tested. That is not the complete core-flow acceptance. |
| U — upgrade and recoverability | Isolated fixtures representing stable 0.1.38, beta.3 and beta.6; backup before upgrade, supported upgrade with record/content checks, restart, restore with matching key, wrong/missing key and interrupted restore fail-closed. Exercise installer replacement and updater manifest/signature handling without changing production Latest or real data. | Partial: all three historical-source profile rehearsals passed on 2026-09-24; packaged/UI upgrade and recovery evidence still must be bound to the candidate. |
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
new batch has used 3/36 calls, $0.30 reserved as of the document batch below. Preserve a distinct durable ledger and
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
