# Public-source preparation and citation-boundary repair — 2026-09-23

Base: `8d279131`, separate from the frozen beta.4 release candidate.
No package installation, third-party code adoption or paid model execution.

## Real inputs, not an Arslan execution result

The [public-source manifest](../../evals/companion/stage2-public-sources.json)
records five README revisions read through the public GitHub API, including
full-file SHA-256 hashes, commit dates, short exact excerpts and review criteria.
These are pinned retrieval references, **not a full offline archive**. A later
runner must fetch the pinned bytes and check their hash before claiming the
same input. The collector was Codex, not Arslan's web tool; no Arslan source
receipt or successful research run is manufactured from these reads.

- R1: three project sources selected; compare project purposes and integration
  limits. Benefits for Arslan remain hypotheses until measured.
- R3: legacy/current Agent Lightning branches selected; the input asks how a
  hypothetical legacy-based recommendation should be checked. It does not
  invent a prior user decision. Commit dates are not release dates.
- R4: same-commit English/Chinese OpenSquilla sources selected. Local routing
  classification must not be expanded into a promise of all-local inference.
- R2: **input selection still blocked**. No genuine same-scope contradiction
  was established in this batch. Version differences or translation choices
  are not fabricated into conflicts. This remains in the four-case denominator.

All twelve full pilot outcomes remain `not_run`. A source selection or manifest
schema check is not a passing end-user task. No model/cost budget was authorized.

## Important adoption constraint found

The pinned [Serena README](https://github.com/oraios/serena/blob/dc97aba74a5fa339d5b3b1a824ccf311b7db04a3/README.md#license)
distinguishes MIT SolidLSP from the GPL-3.0-or-later Serena application.
Do not carry forward a blanket MIT assumption or vendor the application based
on that assumption. This is a source observation, not a legal compatibility
determination; review authoritative license files before any incorporation.

The pinned [Agent Lightning current README](https://github.com/microsoft/agent-lightning/blob/ff9457587fb6ec900e16e93be9ad2d77409afa08/README.md)
describes a v1.0 refactor, while the [legacy README](https://github.com/microsoft/agent-lightning/blob/6db3c73dc0af2e50fe80e56873a57c1703f1b2a7/README.md)
describes the older store-centered arrangement. Old API integration advice
cannot simply be assumed current. Training is still outside this delivery.

The [OpenSquilla English README](https://github.com/TokenRhythm/opensquilla/blob/93c739c17998e9c5e8eb56b6399209946d67d483/README.md)
and [Chinese README](https://github.com/TokenRhythm/opensquilla/blob/93c739c17998e9c5e8eb56b6399209946d67d483/README.zh-Hans.md)
scope their local-processing claim to the routing decision. This does not
demonstrate lower cost or private inference for Arslan.

## Reproduced blocker 2: damaged source traces raise instead of failing closed

Eight new regressions initially raised `AttributeError`: non-object trace
entries, or valid-looking source results with null/list/string/integer tool
arguments. Both source counting and factual evidence validation call this
reader, so a damaged trace could abort validation rather than report missing
read evidence. This is a synthetic robustness reproducer, not a claim that
an actual user run or normal executor emitted these malformed records.

The reader now excludes non-object records/arguments, preserves independent
valid sources and retains URL/body-hash/receipt identity checks. A citation
backed only by a malformed record fails as unread. A correct read still does
not pass semantic review. Task-acceptance integration tests cover both checks.

Verification: **88 passed** in 2.79 seconds across research evidence, public
manifest integrity, frozen synthetic inputs, task validation and executor
regressions. Ruff and whitespace checks passed. The existing Starlette/httpx
deprecation warning remains. No signed build or installed-app test was run.
