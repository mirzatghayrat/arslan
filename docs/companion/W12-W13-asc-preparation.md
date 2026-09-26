# W12–W13 — offline ASC preparation checkpoint, not live acceptance

Baseline: `e9c81e21`. No credentials, Apple account requests, writes, submission,
publication, paid model calls or downloads of model weights occurred.

## Source and scope

Apple's [API overview](https://developer.apple.com/app-store-connect/api/) links
to the [official OpenAPI archive](https://developer.apple.com/sample-code/app-store-connect/app-store-connect-openapi-specification.zip).
Retrieved 2026-09-15: specification 4.4.1; archive SHA-256
`9386762084aa7156a9d5aab20526daf8d4ca423ddaebb0b3fffd2ef6fd836370`.
The typed subset covers Apps, versions, localizations, screenshot sets and
screenshot metadata. It uses `appVersionState`, not the deprecated
`appStoreState`. Unknown state/display-type strings are preserved. This is a
documented subset, not a generated full Apple SDK or a promise of future API compatibility.

## Implemented

- Project settings store explicit App ID, bundle ID, version resource ID and
  platform. Version is never guessed from an App name. All six languages explain
  that these are local target settings, not active account access.
- GET-only transport interface, fixed scoped paths, bounded requests/resources,
  strict same-origin/same-path pagination, duplicate/loop rejection and deadline.
  Authentication failure, missing target, permission denial and rate limiting
  are structured errors. Redirects are refused, remote error bodies are not echoed.
- Snapshots keep sparse fields distinct from explicit empty/null values and omit
  upload operations and asset tokens. Synthetic evidence is labelled fixture.
- Local material reports list missing locales/fields/screenshots and unknown
  compliance facts. They do not guess privacy, rights, export or review details;
  submission requirements and screenshot visual quality remain unverified.
- Local field diffs bind the complete snapshot. Changed remote state requires
  fresh approval. Per-field reconciliation distinguishes verified, not applied,
  conflicting and unknown states; none automatically retries a write.
- Grant admission now additionally requires the project's exact connection ID
  and complete typed App/version/platform/bundle binding.

## Deliberately unavailable

The production client factory refuses activation. There is no key-entry form,
credential-backed read, active draft PATCH, screenshot upload, submission or publication
executor. The capability endpoint distinguishes Apple's platform features from
locally enabled features and does not label a team-wide key as App-scoped.

The isolated broker, trusted confirmation UI, real draft mutation/readback and
independent security review are still required. Offline tests are not A07/A09
real-account evidence and do not satisfy W12/W13 release acceptance.

## Verification

69 synthetic connector/approval/project-API tests passed in 3.38 seconds.
The 13 companion UI tests passed in 1.36 seconds with Node's experimental
web-storage global disabled; the initial unadjusted run failed during collection
(`localStorage.getItem` unavailable), so that run supplied no test evidence.
TypeScript and changed Python lint checks passed. Six-language key parity is
included in the UI suite. No real account acceptance or release claim is made.

## Host-only single-field execution checkpoint

`server/services/asc_draft_execution.py` now joins a prepared field diff, one-use
approval, bounded transport call and independent readback to the action journal.
It has no route, model tool or production transport; real-account capability
flags remain false. The request shape was checked against Apple's
[localization update endpoint](https://developer.apple.com/documentation/appstoreconnectapi/patch-v1-appstoreversionlocalizations-_id_)
and [update request attributes](https://developer.apple.com/documentation/appstoreconnectapi/appstoreversionlocalizationupdaterequest/data-data.dictionary/attributes-data.dictionary)
on 2026-09-15. Only an exact single localization field is supported here; null
writes are explicitly unavailable rather than guessing the API's clearing behavior.

Before network preflight, the service validates the task/attempt, exact project
target, linked artifact-owning Run, prepared intent and current grant. It then
reads the full target snapshot and requires the approved baseline and field diff
to match. After that await, it rechecks target/cancellation and atomically admits
the action using the same serialized plan. Only one fixed-path PATCH is sent;
there are no caller-supplied URLs, authorization headers or automatic retries.

A separate GET snapshot determines verified / not applied / conflicting / unknown
state. Even a timeout may yield a verified desired value, but does not establish
request attribution. Readback reports include explicit fixture/broker evidence
kind, target, action/plan hashes, observed/expected field values and retrieval
time. They are credential-filtered, stored as Run-owned JSON artifacts, and
linked by digest in the action journal. Artifact persistence failure, cancellation
or inconclusive readback leaves the write uncertain. A second invocation cannot
replay the consumed action. Every following field needs fresh preparation and
approval; partially completed plans are not resent as a bundle.

The service does **not** claim an atomic remote compare-and-swap: a remote editor
can still race between preflight and PATCH. No conditional-write guarantee has
been established from these endpoint documents. The trusted broker, its own
policy/identity checks, confirmation UI, complete workflow integration, screenshot
upload handling, real draft acceptance and independent review remain release
gates. This checkpoint is not W11/W13 completion or permission to enable accounts.

The new 18-case execution suite plus connector, approval, binding, task runtime,
repository and validation tests passed 158 tests in 7.76 seconds. Coverage includes
timeout-after-application, no-application timeout, conflicting remote state,
readback failure, revoked/changed approvals, target/cancellation changes during
preflight, stale/expanded plans, unlinked artifact ownership and artifact-write
failure. Changed-file lint and whitespace checks passed; the existing
Starlette/httpx deprecation warning remains. All transports and data were synthetic.
