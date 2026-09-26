# W03 — storage and legacy snapshot

2026-09-14. Migration 0047 adds projects, memory entries/revisions/sources, stable legacy mappings, deletion metadata and a migration report. The existing schema registry remains the single boot chain.

The migration runs transactionally, preserves original rows, uses deterministic IDs within a store instance, and checks input checksums on repeated application. Two experts' identical preferences remain separate records. Unknown provenance/confirmation is not fabricated; old inferred facts remain proposed and untraceable preferences are quarantined. Old cloud consent is not inferred. Recognizable credential values remain only in the existing recovery input and are not copied to ordinary v2 content.

Current revision ownership has a deferred composite foreign key. Cross-scope/dangling supersession and cyclic chains are quarantined. Missing source references are flagged. Structured reports distinguish counts, restricted data and intentional filtering from successful copies.

Verification: 8 new migration tests plus 48 migration-runner tests passed, including injected interruption/rollback, idempotency, unchanged legacy content, same-text cross-expert isolation, unknown confirmation, credential screening, dangling/cyclic references and revision ownership.

This snapshot phase is `prepared`, not an active second prompt source. W04/W05 must finish service routing and then activate the unified repository with legacy-write guards; until that switch there is no claim that the memory migration is production-complete. No real user database was opened or migrated during development.
