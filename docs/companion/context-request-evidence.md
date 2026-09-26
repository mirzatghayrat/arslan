# Memory selection versus request evidence

Receipts previously proved only that context assembly selected an entry/version.
The host or worker could later fail before the model call, use another synthesis
prompt, or lose the selected block. Selection must not be displayed as delivery.

## Current implementation

The three native providers now offer an optional evidence hook at both ordinary
and streaming HTTP boundaries. It runs after the existing request-budget and
checkpoint admission. The hook sees final provider JSON, not request headers,
authentication keys or credential-bearing URLs. It changes neither payload nor
authorization.

The trusted personal-context binding keeps each selected block transiently within
its task/run lifetime. Attribution requires the same owner, task, run,
conversation and expert identity and the complete selected block in a native
system field. User quotations and partial/changed blocks are not attributed.
Identical repeated selections attribute to the latest receipt for that identity;
host and worker registrations remain separate even with identical text.

Two atomic counters are added to existing receipt JSON, without a schema or data
migration:

- `request_attempts`: a final payload containing that block reached the attempted
  HTTP-call boundary. Failure or cancellation may still prevent transmission.
- `provider_responses`: that attempt obtained a successful HTTP response. This is
  recorded before body parsing or stream completion, so it does not certify a
  valid answer, completed generation, billing, model attention or adoption.

Missing response evidence does not prove non-delivery. Responses cannot outnumber
attempts; concurrent increments do not replace one another. Acknowledgement is
once-only. Expired task leases and temporary tasks do not add evidence. Each
optional write has a 0.5-second time bound; failures produce a generic diagnostic,
not raw exception content, and do not prevent an otherwise admitted request.
User cancellation still propagates.

No new persistent prompt/body copy, endpoint, key or provider trace is stored.
The original receipt retains only its entry/version references and other existing
metadata. The six-language UI distinguishes selection-only, attempted request
with unconfirmed delivery, and successful service response counts. Legacy or
malformed counters never become a positive response claim. Deleted memory text
remains hidden by the existing explicit-review endpoint.

## Verification

The provider/context/multi-turn/API/contract regression initially passed 318 tests
in 67.48 seconds. After adding bounded-timeout behavior, all-provider real-host
entry checks and distinct worker attribution, the final focused provider-boundary
and contract run passed **52 tests in 2.81 seconds**. HTTP responses are synthetic
MockTransport fixtures, but payload serialization, request admission, host-task
binding and receipt persistence use production code. The tests cover all three
protocols in ordinary and streaming modes, actual host entry for all three,
HTTP/transport failures, budget refusal, quotations/partial context, task switches,
identical selections, worker separation, concurrency, expired leases, duplicate
acknowledgement, evidence failure, timeout and cancellation.

The complete frontend run passed **237 files / 1,833 tests in 18.47 seconds**,
TypeScript checking and production build (2.96 seconds) passed. Existing jsdom
canvas/navigation and large-bundle warnings remain. The updated isolated browser
fixture passed all six locales at 900×720 and 480×720, including horizontal
overflow, runtime errors, translation keys and reaching the end of long text.
All 12 screenshots in `/tmp/arslan-memory-layout.nbqQbk` were visually inspected.
These are synthetic headless checks, not live desktop acceptance.

The complete 4,718-test backend result recorded in W17 predates these hooks;
a new frozen full run is required for this source. This observability mechanism
is not revocation enforcement: revalidation of already-built prompts during an
in-flight task needs its own audit and tests. Historical scope snapshots and
real-model behavior are also not proven by these counters. No real model/account,
publication or installed-app replacement was used.

The frozen follow-up on clean `1d1be3c4` passed **4,739 tests, 14 skips and 18
warnings in 444.62 seconds**. Report:
`/tmp/arslan-request-evidence-regression.bdRjdP/backend.xml`. A separate isolated
diagnostic confirmed that deletion between two model requests still allows the
old block through the reused system prompt. The counters correctly observe it;
they do not prevent it. The follow-up mandatory admission and snapshot-writeback
fences are documented in `memory-inflight-revocation.md`; the counters remain
observability only, not the policy enforcement mechanism.
