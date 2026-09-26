# W14 — source-provenance checkpoint

Baseline: `685bfb99`. No model/account charges or live acceptance runs.

Successful web extraction now returns a bounded-text hash, stable source ID,
retrieval timestamp, truncation flag, untrusted-web classification and unknown
reference-only license status. The receipt and text travel in the task-owned
tool trace; no global or personal-memory source cache is created. A resumed/new
task without that read evidence must reopen the source. Retrieval time is not
publication time and does not establish that a license, price or fact is current.

The existing source-count validator now needs a hash-consistent successful
extraction with nonempty body, not just `ok: true`. A structured research-evidence
validator rejects unread sources, altered source bodies, wrong URLs and absent
quotes. Time-sensitive evidence older than one day requires reopening. Exact
quoted text still produces `not_run` for claim support and temporal relevance:
a passage can exist while failing to support the claim. A model cannot override
this deterministic gate or make it pass by voting.

Host research guidance separates discovery, reading, direct support, inference,
comparison scope, conflicting evidence and unknowns. Source text cannot grant
permissions or become a user preference. Existing saved method revisions are not
silently overwritten.

This is not R01–R08 quality acceptance. Semantic entailment, correct interpretation
of conflicts and real-model research quality still require human/real-task review.
The implementation explicitly leaves those checks unperformed rather than using
link count or quote matching as a proxy for factual truth.

Verification: 99 research, extraction, task-validation and contract tests passed
in 3.09 seconds; changed Python lint passed. One existing Starlette/httpx
deprecation warning remains. Tests include an exact but irrelevant quote that
must not pass semantic validation and page-injected instructions that stay data.
