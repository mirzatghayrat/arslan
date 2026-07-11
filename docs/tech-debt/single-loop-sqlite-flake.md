# Tech debt: cross-event-loop SQLite "database is locked" test flake

**Status:** ACCEPTED MITIGATION (2026-07-11) · **Owner:** maintainer · **Escalation:** see below

## Symptom

The backend test suite (`tests/server/`) intermittently fails with `sqlite3.OperationalError: database is locked`. It is non-deterministic — a given run may pass or fail, and it is not tied to any one test's product code.

## Root cause

~112 test files use multiple `anyio.run(...)` calls (each spins up a *fresh* event loop) against a shared async SQLAlchemy engine, plus a WS test portal on its own loop. A pooled `aiosqlite` connection created on one event loop gets reused across a different loop → the connection's single-writer lock is contended across loops → intermittent "database is locked". It is a **test-harness architecture** problem, not a product bug (production runs on one event loop).

## Current mitigation (accepted)

CI retries **only** this one failure signature, scoped as tightly as possible, in `.github/workflows/ci.yml`:

```
--reruns 2 --reruns-delay 1 --only-rerun "database is locked"
```

This has kept CI reliably green across S0/S1/S2 and the UX/PC rounds (6+ consecutive green runs). The flake is low-frequency and, by construction, cannot mask a real product failure (any *other* failure signature is never retried).

## Why we accepted the mitigation instead of the root fix

A root fix exists as a **117-file test refactor** (sync seed fixtures → `@pytest_asyncio.fixture async`, TestClient/WS routed through **one explicit blocking portal**, portal engine `poolclass=NullPool`, plus a `run_recorder` deterministic step-ordering fix). It was developed on branch `fix/single-loop-sqlite-tests`, but its merge-base predates S0/S1/S2 — which added and modified a large fraction of the test suite plus `conftest`. Rebasing the 117-file refactor onto current `main` is effectively a full redo (conflicts in nearly every test file it touches, and the async-fixture conversion would need re-applying to every new S0–S2 test). It was **not** superseded by later work — `main` still relies on the rerun bridge; the root fix is genuinely absent. Given the flake's low impact and the refactor's cost, the pragmatic, honest choice is: accept the bridge, preserve the work, and define hard escalation triggers.

## Preserved work

The full refactor is preserved at tag **`archive/single-loop-refactor`** (tip `68006e8`). A future root-fix ticket should start from that tag as reference, not from zero. **Root-fix approach summary** (to seed that ticket):
1. Convert synchronous seed fixtures to `@pytest_asyncio.fixture async` so all DB setup runs on the test's event loop.
2. Route TestClient / WebSocket tests through a **single explicit `anyio` blocking portal** (`client.portal = portal`) instead of per-call `anyio.run`, so there is one loop for the whole test.
3. Give the portal engine `poolclass=NullPool` (portal engine only) so no connection is pooled across loops; dispose + `portal.stop(True)` on teardown to avoid the load-hang gotcha.
4. Fold in the `run_recorder` deterministic step-ordering fix (tie-break by event arrival order).

## Escalation triggers (root-fix ticket auto-activates when ANY holds)

- The `database is locked` flake fires in CI at a **weekly frequency > 3 rerun-triggers** (visible in CI logs via `-rR`), i.e. it stops being rare.
- The **same error signature appears in a non-test environment** (dev server, packaged build, or any production-path run) — that would mean it's no longer test-harness-only and is a real product bug.
- A change requires widening the retry scope (see iron rule).

## Iron rule

**The `--only-rerun` match string is `"database is locked"` and never widens.** Any need to add a second match signature is, by definition, a declaration that a *different* flake exists and that a real root fix (not another retry band) is required — open the escalation ticket instead of broadening the retry.
