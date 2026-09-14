# W02 — minimum contracts and runtime decision

2026-09-14. Implemented in `arslan/companion/contracts.py`; 31 offline tests pass.

TaskSpec, TaskState, WorkerBrief, ToolResult, ContextReceipt, AcceptanceCheck, ConnectionMetadata, Grant, and ActionJournal now have closed, versioned Pydantic/JSON schemas. Supporting scope, resource, acceptance-result, and budget contracts share the same boundary.

Covered invariants:

- Scope IDs must match their kind; a task-scoped specification must match its task ID.
- Native execution budgets retain every limit; worker briefs refer to a shared parent budget rather than specifying a fresh allowance.
- Success validation against a TaskSpec requires every named check to pass with the configured evaluator and evidence references. Critical checks cannot rely only on a model.
- Disabled/temporary memory modes reject memory references in receipts. Receipts record references and reason codes, not personal source bodies.
- Connection metadata contains an opaque credential reference, not a password field. Grant expiration is timezone-aware and revocation fails closed.
- Denied tools cannot claim executed effects. Writes require an action journal reference; confirmed actions require executor evidence. Uncertain outcomes remain distinct from failures.

## Boundaries not yet integrated

These types are not an authorization engine, evidence verifier, database migration, or completed Task Service. Reference ownership and evidence bytes must be checked by services; a syntactically valid reference is not proof. The task-aware acceptance gate must be called explicitly via `TaskState.validated_for(spec)`. Constructing a state alone cannot validate criteria stored in a separate specification.

The initial 31 tests exercise shared data contracts. The additional `tests/server/test_companion_runtime_conformance.py` now exercises real host, expert dispatcher and recipe entry points with synthetic models/tools and isolated persistence (11 tests). Persistent task-event ordering, recovery, grant revalidation and uncertain-write reconciliation remain W07/W11 work. No existing runtime is silently switched to these schemas before its service integration.

## Runtime direction

Keep the existing native Python runtime. The bounded comparison is closed in `ADR-001-native-runtime.md`: no Pi dependency or alternate production kernel was added, and no provider compatibility/quality advantage is claimed. W02's minimum contracts and decision are ready for the dependent storage/execution packages; they are not a release gate by themselves.
