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

## Escalation log — second, distinct flake signature (`Event loop is closed` / portal-teardown)

A **different** flake now recurs and is **NOT covered by the `database is locked` bridge**, so the auto-rerun never retries it — it requires a **manual full-job rerun**.

- **Signature:** `Failed: Timeout (>120.0s) from pytest-timeout` inside `threading.py:_wait_for_tstate_lock` (a `BlockingPortal` thread's `join()` hanging on teardown), accompanied by `RuntimeError: Event loop is closed` and `NullPool` connection-termination tracebacks. It surfaces only on slow/loaded CI runners, never locally.
- **Occurrences (this week, 2026-07-07..07-12):** S3-M3 merge (2×, one earlier rerun pair) + Provider-round final-fix commit `0935593` (2× consecutive CI reds → green on the 3rd manual rerun, zero code change between attempts). This **crosses the ">3 weekly rerun-triggers" escalation trigger.**
- **Non-regression evidence for `0935593`:** the exact HEAD passed the full `tests/` suite and the portal/ws-heavy `tests/server` subset **4 times locally with zero hang**; the frontend CI job was green throughout; the two immediately-preceding commits on the same branch (`aa0baa1`, `aa0c0a0`) went green first-try. So the flake is CI-environment-timing, not `0935593`'s code.
- **Partial prior mitigation:** S3-M3 added `portal.stop(cancel_remaining=True)` to the two shared portal helpers, which fixed one teardown-hang class. The residual `Event loop is closed` hang is a separate layer (bridge does not capture it) and remains open.
- **Iron rule still intact:** the `--only-rerun` string was **not** widened to catch this signature (per the rule above, doing so would be the wrong move). Reruns for this signature are manual `gh run rerun --failed`.

**Escalation status: TRIGGERED.** A root-fix ticket for the portal-teardown hang should be opened (start from tag `archive/single-loop-refactor`, whose single-explicit-portal + `portal.stop(True)` + `NullPool` approach targets exactly this teardown-hang class). Deferred pending maintainer decision; recorded here so the on-repo ledger is honest.

### Maintainer decision (2026-07-12)

- **Do the root fix, but NOT now.** It is scheduled as a dedicated **"stabilization round" in S4, immediately before packaging, on a FROZEN `main`** — that feature-freeze window is the only time the refactor won't be churned by newly-landing tests.
- **Do NOT rebase `archive/single-loop-refactor`.** Its merge-base is too old; instead **re-derive the same approach on the frozen `main`** — the four moves are unchanged: (1) sync seed fixtures → `@pytest_asyncio.fixture async`; (2) all TestClient/WS through one explicit `anyio` blocking portal; (3) portal engine `poolclass=NullPool` + `dispose` + `portal.stop(True)` on teardown; (4) `run_recorder` deterministic step-ordering (tie-break by event-arrival order). Use the archive tag as a **reference**, not a base to merge.
- **Scope on current `main` (2026-07-12 measurement, for the freeze-timing estimate):** `tests/server/` = **298 files**; **133 files / 309 call-sites** use `anyio.run`; **33 files** use TestClient / blocking-portal / websocket. (The archived refactor was 117 files at its older merge-base; current scope is larger.) Rough effort: ~conftest rewrite (highest-risk, holds the teardown-hang gotcha) + ~133-file async-fixture conversion (mechanical but per-file verification) + 33-file portal routing + the recorder fix + a multi-run flake-soak to confirm the hang is gone. Estimate ≈ **2–3 focused days** subagent-driven, compressible toward ~1 day wall-clock with parallel worktree batches. Maintainer sets the freeze point from this.
- **Iron rule unchanged.** The `--only-rerun` string stays `"database is locked"` and is never widened. Until the root fix lands, the `Event loop is closed` / portal-teardown signature is handled by **manual `gh run rerun --failed`, and every occurrence is logged in this file.**

### Occurrence ledger (manual reruns during the transition)

| Date | Commit | Reds | Cleared on | Notes |
|---|---|---|---|---|
| 2026-07-12 | `0935593` (provider-round final fixes) | 2 consecutive | 3rd manual rerun | 4 clean local full/subset runs; frontend job green throughout; non-regression confirmed. |
| 2026-07-12 | `a6a79ec` (settings-round merge) | 1 | 1st manual rerun | Frontend-only round — backend byte-identical to green-at-`3296b07`, so a backend fail is definitionally the flake, not a regression. Frontend job green throughout. |
