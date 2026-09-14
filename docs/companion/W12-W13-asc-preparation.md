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
credential-backed read, draft PATCH, screenshot upload, submission or publication
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
