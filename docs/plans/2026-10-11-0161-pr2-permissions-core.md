# 0.1.61 PR 2 — the permission core: one decide(), a store, a ledger, cards that wait

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Arslan one permission layer, `server/services/permissions.py`, with these parts:
- a persistent store: "Always" rules, task and conversation grants, and a ledger;
- a v2 card answer (scope + note) that background jobs share with the chat window;
- 30-minute cards whose expiry is never reported as a refusal;
- scheduled runs that never wait.

What asks stays exactly as today. PR 3 changes what asks; this PR changes how asking works.

**Architecture:**
- **The ladder.** `permissions.decide(Request, Context) -> Decision` decides in this order:
  1. money: always a card;
  2. an "Always" rule;
  3. a grant for this task or conversation; a job sees its conversation's grants;
  4. the card surface bound to the turn by the `asking_with(asker)` contextvar.

  With no surface, the answer is an immediate no (`by="policy"`). Every decision writes one
  `approval_events` row.
- **The card surfaces.**
  - The chat window binds an asker over its existing `_ask_everywhere`. The card stays private to
    the window, and the Inbox and island can still answer it.
  - A background job binds `approvals.BroadcastAsker`.
  - A scheduled run binds nothing.
- **The callbacks move onto `decide`.** `confirm_workspace_write`, `confirm_schedule` and the
  rule cards of `confirm_command`, in both the window and the job, are reimplemented on
  `decide`. The outside/retry sandbox cards are left as they are; PR 3 replaces them.
- **No UI change.** The web UI is PR 2b. It works against both shapes: until 2b lands, the UI
  keeps sending `remember`, which maps to a scope.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async + SQLite (aiosqlite), pytest
(`asyncio_mode = "auto"`), the existing `tests/server/conftest.py` harness (`build_ws_client`).

**Spec:** `docs/specs/2026-10-11-0161-smooth.md`. This PR covers §3, §A4 (except the UI), §A5
(store and migration), §A8 (the ledger), §A9 ("expired is not declined", "a rule tick stores all
rules") and §A11 (the interface). The user approved the spec on 2026-10-11.

## Global Constraints

- **`decide()` keeps the §A11 contract** that ③Hands builds against. Three additions are
  recorded as rulings below:
  - `Request.frame`, `Request.remember_as` and `Request.grant_as`;
  - `Context.task_id`;
  - `would_ask` is `async`.

  Hands' files (`server/registry/hands_tools.py`, `server/services/hands_service.py`) are not
  touched here; ③Hands moves them.
- **The scope options** follow §A4 exactly:
  - The first choice is "task" for the kinds `app` and `shortcut`, and "once" for everything else.
  - "conversation" is never offered for `money`, `capability`, `other_agent`, `system`, `opaque`,
    `remote`, `takeover` or `app_risky`.
  - "always" is never offered for those kinds, nor for `destructive`, `screen`,
    `workspace_write` or `schedule`. It is offered only when the request carries an
    `always_label`.
- **Money is never remembered**, and asks in every mode.
- **Cards wait `approvals.TIMEOUT_S = 1800` s.** An expired card is `by="expired"`, and the model
  text says "NOT a refusal". The ledger says `expired`, never `deny`.
- **The phone and the island answer only the first option.** Phones never grant more than once
  (today's rule "a phone never grants always").
- **The shadow judge still runs on rule cards**, exactly as today (`judgment.shadow` +
  `record_outcome_later`).
- **Migrations:** `_0067` must be updated in the three lockstep places: the version file,
  `runner.MIGRATIONS`, and `tests/server/test_migration_runner.py`'s id list. It is idempotent.
  The old settings row `terminal_always_allow` stays, for a downgrade.
- **Before every commit:** run `.venv/bin/ruff check server tests` (line length 100) and the
  focused tests. Before the push (Task 6), run the full suite with `ARSLAN_SECRET_KEY=ci-secret`
  as CI does.
- **Git:** never use `git checkout --` or `git stash`. Commits end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Rulings carried in this plan (spec §A11 additions)

1. `Request` gains `frame: dict | None` (the card frame the caller built: its own type and
   fields; `None` means a generic `propose_action`), `remember_as` (the `(kind, target)` pairs an
   "Always" stores) and `grant_as` (the pairs a task or conversation grant stores).
   - This is needed because a command's "Always" must store **every** rule it matched as
     `legacy_rule` rows (§A9), not one combined key.
   - `decide_many` needs one grant per app.
2. `Context` gains `task_id`. "For this task" needs the turn or job id; `decide()` fills it from
   `personal_context` when it is empty.
3. `would_ask` is `async`, because the store is the database.
4. `workspace_write` is kept as a kind for now. Its card disappears in PR 3, when picking a folder
   becomes consent (§A3).

## Review Focus

The five inputs most likely to bite, each pinned by a test in the owning task:

1. **Two identical requests while one card is open.** For example, a job and its window, or two
   parallel calls. Expected: one card; both callers get the same answer. → Task 3,
   `test_identical_requests_share_one_card`.
2. **A card that expires for one waiter while another still waits on it.** Expected: the card
   stays open for the second waiter, and `card_resolved` is sent only once. → Task 3,
   `test_one_waiter_expiring_does_not_close_a_shared_card`.
3. **A message typed while this window's card waits.** Expected: the card is answered "No" with
   the message as the note, and the message runs next instead of waiting 30 minutes. → Task 4,
   `test_a_message_typed_while_a_card_waits_answers_it`.
4. **A phone or island answer carrying `scope: "always"`.** Expected: downgraded to the card's
   first option. → Task 3, `test_phone_and_island_answers_are_once_only`.
5. **A scheduled run (no surface) reaching a boundary.** Expected: refused at once, with a ledger
   row `decided_by=policy` that the Inbox can list. → Task 2,
   `test_no_surface_means_no_at_once_and_is_recorded`.

---

### Task 1: The store — migration 0067, models, `permission_store`, legacy rules backed by it

**Files:**
- Create: `server/db/migrations/versions/_0067_permissions.py`
- Modify: `server/db/migrations/runner.py`: import `_m0067` and append `("0067", _m0067)` to
  `MIGRATIONS`.
- Modify: `tests/server/test_migration_runner.py`: append `"0067"` to the id list in
  `test_registry_matches_boot_chain_verbatim`.
- Modify: `server/db/models.py`: add `PermissionRule`, `PermissionGrant`, `ApprovalEvent` after
  `ConversationModel` (around line 442).
- Create: `server/services/permission_store.py`
- Modify: `server/services/terminal_policy.py`: `always_allowed`, `allow_always`, `forget`
  (lines 222–246) now read and write `legacy_rule` rows.
- Test: create `tests/server/test_permission_store.py`. Update any test that seeds the settings
  row `terminal_always_allow` directly. Find them with
  `grep -rln terminal_always_allow tests/`, and seed with
  `terminal_policy.allow_always(db, rule)` instead.

**Interfaces:**
- Produces (Tasks 2–5 use these):
  - `permission_store.find_rule(db, kind, target) -> PermissionRule | None`
  - `add_rule(db, kind, target, *, label="", created_from="") -> PermissionRule`
  - `touch_rule(db, row)`
  - `list_rules(db, kind=None) -> list[PermissionRule]`
  - `delete_rule(db, rule_id) -> bool`
  - `delete_rule_by(db, kind, target) -> bool`
  - `find_grant(db, conversation_id, task_id, kind, target) -> PermissionGrant | None`
  - `add_grant(db, conversation_id, task_id, kind, target, *, call_id="") -> PermissionGrant`
  - `record(db, **fields) -> ApprovalEvent`
  - `recent(db, *, limit=200)`
  - `refused_since(db, since: datetime)`
  - `_reset_for_tests()`

  None of these functions commit; callers commit.
- The `terminal_policy` signatures are unchanged.

- [ ] **Step 1: Write the failing tests**

Create `tests/server/test_permission_store.py`:

```python
"""0.1.61 §A5/§A8: the permission store — rules, grants, the ledger, and the legacy
"don't ask again" list now living in it."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa

from server.db import session as db_session
from server.services import permission_store, terminal_policy


@pytest.fixture(autouse=True)
def _fresh(portal_db):
    permission_store._reset_for_tests()
    yield


async def test_a_rule_is_found_by_kind_and_target_and_added_once():
    async with db_session.AsyncSessionLocal() as db:
        a = await permission_store.add_rule(db, "app", "com.tencent.xinWeChat", label="WeChat",
                                            created_from="c1")
        b = await permission_store.add_rule(db, "app", "com.tencent.xinWeChat", label="WeChat")
        await db.commit()
        assert a.id == b.id
        assert (await permission_store.find_rule(db, "app", "com.tencent.xinWeChat")).label == "WeChat"
        assert await permission_store.find_rule(db, "app", "com.apple.Notes") is None
        assert await permission_store.find_rule(db, "shortcut", "com.tencent.xinWeChat") is None


async def test_a_conversation_grant_covers_every_task_and_a_task_grant_only_its_task():
    async with db_session.AsyncSessionLocal() as db:
        await permission_store.add_grant(db, "conv-1", "", "schedule", "*")
        await permission_store.add_grant(db, "conv-1", "turn-a", "app", "com.apple.Notes")
        await db.commit()
        assert await permission_store.find_grant(db, "conv-1", "turn-z", "schedule", "*")
        assert await permission_store.find_grant(db, "conv-1", "turn-a", "app", "com.apple.Notes")
        assert await permission_store.find_grant(db, "conv-1", "turn-b", "app", "com.apple.Notes") is None
        assert await permission_store.find_grant(db, "conv-2", "turn-a", "app", "com.apple.Notes") is None
        assert await permission_store.find_grant(db, None, "turn-a", "app", "com.apple.Notes") is None


async def test_the_ledger_keeps_90_days_and_lists_policy_refusals():
    async with db_session.AsyncSessionLocal() as db:
        old = await permission_store.record(db, kind="app", target="x", mode="standard",
                                            decided_by="user", decision="allow")
        old.created_at = datetime.utcnow() - timedelta(days=91)
        await permission_store.record(db, kind="schedule", target="*", mode="standard",
                                      decided_by="policy", decision="deny", conversation_id="c")
        await db.commit()
        permission_store._reset_for_tests()          # let the next write prune
        await permission_store.record(db, kind="app", target="y", mode="standard",
                                      decided_by="rule", decision="allow")
        await db.commit()
        targets = [e.target for e in await permission_store.recent(db)]
        assert "x" not in targets and {"y", "*"} <= set(targets)
        refused = await permission_store.refused_since(db, datetime.utcnow() - timedelta(hours=24))
        assert [(e.kind, e.decided_by) for e in refused] == [("schedule", "policy")]


async def test_legacy_dont_ask_again_rules_live_in_the_store():
    async with db_session.AsyncSessionLocal() as db:
        await terminal_policy.allow_always(db, "delete")
        await terminal_policy.allow_always(db, "hermes:recursive delete")
        await terminal_policy.allow_always(db, "sudo")           # forbidden: never stored
        assert await terminal_policy.always_allowed(db) == {"delete", "hermes:recursive delete"}
        rows = await permission_store.list_rules(db, "legacy_rule")
        assert {r.target for r in rows} == {"delete", "hermes:recursive delete"}
        await terminal_policy.forget(db, "delete")
        assert await terminal_policy.always_allowed(db) == {"hermes:recursive delete"}


def test_migration_0067_copies_the_old_list_once(tmp_path):
    from server.db.migrations.versions import _0067_permissions as m
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE settings (key VARCHAR(100) PRIMARY KEY, value TEXT NOT NULL)")
        conn.exec_driver_sql("INSERT INTO settings VALUES ('terminal_always_allow', "
                             "'[\"hermes:script execution via heredoc\", \"delete\"]')")
        m.upgrade_sync(conn)
        m.upgrade_sync(conn)                                     # idempotent
        rows = conn.exec_driver_sql(
            "SELECT kind, target, created_from FROM permission_rules ORDER BY target").fetchall()
    assert rows == [("legacy_rule", "delete", "migration"),
                    ("legacy_rule", "hermes:script execution via heredoc", "migration")]
```

Check how existing DB tests get a fresh database: look at `tests/server/conftest.py` for a
fixture that points `db_session` at a temp SQLite file with `create_all`. Use it as `portal_db`
above, or replace `portal_db` with whatever that fixture is called. If none exists, add a small
fixture in this test file. It should:
- create a temp engine with `Base.metadata.create_all`;
- monkeypatch `db_session.AsyncSessionLocal` to an `async_sessionmaker` bound to it;
- dispose of the engine at teardown.

Take the pattern from the file that `tests/server/test_inbox_approvals.py`'s
`build_ws_client(... db_name=...)` comes from. Do not invent a new one if one exists.

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/.claude/worktrees/wonderful-chandrasekhar-022909/arslan-0161-core && .venv/bin/python -m pytest tests/server/test_permission_store.py tests/server/test_migration_runner.py -q
```
Expected: FAIL. `permission_store` and the `_0067` module do not exist, and the registry list
check fails once `"0067"` is added to the test.

- [ ] **Step 3: Implement**

`server/db/migrations/versions/_0067_permissions.py`:

```python
"""0067: the permission store (0.1.61 §A5, §A8).

Three tables: standing answers ("Always", `permission_rules`), answers for one task or one
conversation (`permission_grants`), and a ledger of every decision that crossed a boundary
(`approval_events`). The old "don't ask again" list — settings `terminal_always_allow`, a
JSON list of rule names — becomes `legacy_rule` rows; the settings row stays, for a
downgrade. Idempotent; fresh databases get the tables from Base.metadata.create_all.
"""
from __future__ import annotations

import json
from datetime import datetime


def upgrade_sync(connection) -> None:
    connection.exec_driver_sql("""
    CREATE TABLE IF NOT EXISTS permission_rules (
        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
        kind VARCHAR(30) NOT NULL,
        target TEXT NOT NULL,
        label TEXT NOT NULL DEFAULT '',
        created_from VARCHAR(80) NOT NULL DEFAULT '',
        created_at DATETIME NOT NULL,
        last_used_at DATETIME,
        use_count INTEGER NOT NULL DEFAULT 0,
        UNIQUE (kind, target)
    )""")
    connection.exec_driver_sql("""
    CREATE TABLE IF NOT EXISTS permission_grants (
        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
        conversation_id VARCHAR(100) NOT NULL,
        task_id VARCHAR(100) NOT NULL DEFAULT '',
        kind VARCHAR(30) NOT NULL,
        target TEXT NOT NULL,
        call_id VARCHAR(64) NOT NULL DEFAULT '',
        created_at DATETIME NOT NULL,
        UNIQUE (conversation_id, task_id, kind, target)
    )""")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_permission_grants_conversation "
                               "ON permission_grants (conversation_id)")
    connection.exec_driver_sql("""
    CREATE TABLE IF NOT EXISTS approval_events (
        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
        created_at DATETIME NOT NULL,
        conversation_id VARCHAR(100),
        job_id VARCHAR(100),
        run_id VARCHAR(100),
        kind VARCHAR(30) NOT NULL,
        target TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '',
        extra JSON,
        mode VARCHAR(20) NOT NULL,
        decided_by VARCHAR(20) NOT NULL,
        decision VARCHAR(10) NOT NULL,
        scope VARCHAR(20),
        rule_id INTEGER,
        grant_id INTEGER,
        reviewer JSON,
        wait_ms INTEGER
    )""")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_approval_events_created "
                               "ON approval_events (created_at)")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_approval_events_conversation "
                               "ON approval_events (conversation_id)")
    _copy_legacy_rules(connection)


def _copy_legacy_rules(connection) -> None:
    """The old list, as `legacy_rule` rows. An unreadable list copies nothing: a standing
    permission is never inferred from an error (terminal_policy's rule)."""
    try:
        row = connection.exec_driver_sql(
            "SELECT value FROM settings WHERE key = 'terminal_always_allow'").fetchone()
    except Exception:  # noqa: BLE001 — no settings table on a bare database
        return
    if not row:
        return
    try:
        rules = [str(r) for r in json.loads(row[0]) if str(r).strip()]
    except (ValueError, TypeError):
        return
    now = datetime.utcnow().isoformat(sep=" ")
    for rule in rules:
        connection.exec_driver_sql(
            "INSERT OR IGNORE INTO permission_rules (kind, target, label, created_from, created_at, "
            "use_count) VALUES ('legacy_rule', ?, '', 'migration', ?, 0)", (rule, now))


def downgrade_sync(connection) -> None:
    for table in ("approval_events", "permission_grants", "permission_rules"):
        connection.exec_driver_sql(f"DROP TABLE IF EXISTS {table}")
```

`server/db/models.py`: add after `ConversationModel`, importing `UniqueConstraint` and `Text` if
they are not already imported:

```python
class PermissionRule(Base):
    """0.1.61 §A5: a standing answer ("Always"): this kind of boundary, this target, no card."""

    __tablename__ = "permission_rules"
    __table_args__ = (UniqueConstraint("kind", "target"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(30), nullable=False)
    target = Column(Text, nullable=False)
    label = Column(Text, nullable=False, default="")
    created_from = Column(String(80), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)
    use_count = Column(Integer, nullable=False, default=0)


class PermissionGrant(Base):
    """0.1.61 §A5: an answer for one task (task_id = the turn or job) or one conversation
    (task_id = ""). A job started from the conversation reads its conversation grants."""

    __tablename__ = "permission_grants"
    __table_args__ = (UniqueConstraint("conversation_id", "task_id", "kind", "target"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(100), nullable=False, index=True)
    task_id = Column(String(100), nullable=False, default="")
    kind = Column(String(30), nullable=False)
    target = Column(Text, nullable=False)
    call_id = Column(String(64), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ApprovalEvent(Base):
    """0.1.61 §A8: one decision that crossed a boundary — who decided, how, how long the card
    waited. The number this round is judged by (cards per task) comes from here."""

    __tablename__ = "approval_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    conversation_id = Column(String(100), nullable=True, index=True)
    job_id = Column(String(100), nullable=True)
    run_id = Column(String(100), nullable=True)
    kind = Column(String(30), nullable=False)
    target = Column(Text, nullable=False)
    detail = Column(Text, nullable=False, default="")
    extra = Column(JSON, nullable=True)
    mode = Column(String(20), nullable=False)
    decided_by = Column(String(20), nullable=False)
    decision = Column(String(10), nullable=False)
    scope = Column(String(20), nullable=True)
    rule_id = Column(Integer, nullable=True)
    grant_id = Column(Integer, nullable=True)
    reviewer = Column(JSON, nullable=True)
    wait_ms = Column(Integer, nullable=True)
```

`server/services/permission_store.py`:

```python
"""Where Arslan's permissions are kept (0.1.61 §A5, §A8).

Standing answers ("Always", `PermissionRule`), answers for one task or one conversation
(`PermissionGrant`), and the ledger of every decision that crossed a boundary
(`ApprovalEvent`). Plain storage: what a request means and when to ask is `permissions`'
business. Nothing here commits — the caller owns the transaction.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from sqlalchemy import delete, select

from server.db.models import ApprovalEvent, PermissionGrant, PermissionRule

#: Ledger rows are kept this long (spec §A8).
LEDGER_DAYS = 90
#: A task grant's turn or job never comes back; its row is pruned after this.
TASK_GRANT_HOURS = 24
#: Pruning runs at most once an hour, on a write.
_PRUNE_EVERY_S = 3600
_last_prune = {"at": 0.0}


async def find_rule(db, kind: str, target: str) -> PermissionRule | None:
    return (await db.execute(select(PermissionRule).where(
        PermissionRule.kind == kind, PermissionRule.target == target))).scalar_one_or_none()


async def add_rule(db, kind: str, target: str, *, label: str = "",
                   created_from: str = "") -> PermissionRule:
    row = await find_rule(db, kind, target)
    if row is None:
        row = PermissionRule(kind=kind, target=target, label=label[:500],
                             created_from=created_from[:80], created_at=datetime.utcnow(),
                             use_count=0)
        db.add(row)
        await db.flush()
    return row


async def touch_rule(db, row: PermissionRule) -> None:
    row.last_used_at = datetime.utcnow()
    row.use_count = (row.use_count or 0) + 1


async def list_rules(db, kind: str | None = None) -> list[PermissionRule]:
    query = select(PermissionRule).order_by(PermissionRule.created_at.desc(), PermissionRule.id.desc())
    if kind is not None:
        query = query.where(PermissionRule.kind == kind)
    return list((await db.execute(query)).scalars().all())


async def delete_rule(db, rule_id: int) -> bool:
    row = await db.get(PermissionRule, rule_id)
    if row is None:
        return False
    await db.delete(row)
    return True


async def delete_rule_by(db, kind: str, target: str) -> bool:
    row = await find_rule(db, kind, target)
    if row is None:
        return False
    await db.delete(row)
    return True


async def find_grant(db, conversation_id: str | None, task_id: str | None, kind: str,
                     target: str) -> PermissionGrant | None:
    """A conversation grant (task_id "") or a grant for exactly this task."""
    if not conversation_id:
        return None
    tasks = [""] + ([task_id] if task_id else [])
    return (await db.execute(select(PermissionGrant).where(
        PermissionGrant.conversation_id == conversation_id,
        PermissionGrant.task_id.in_(tasks),
        PermissionGrant.kind == kind,
        PermissionGrant.target == target).limit(1))).scalar_one_or_none()


async def add_grant(db, conversation_id: str, task_id: str, kind: str, target: str, *,
                    call_id: str = "") -> PermissionGrant:
    await _prune(db)
    task_id = task_id or ""
    row = (await db.execute(select(PermissionGrant).where(
        PermissionGrant.conversation_id == conversation_id, PermissionGrant.task_id == task_id,
        PermissionGrant.kind == kind, PermissionGrant.target == target))).scalar_one_or_none()
    if row is None:
        row = PermissionGrant(conversation_id=conversation_id, task_id=task_id, kind=kind,
                              target=target, call_id=call_id[:64], created_at=datetime.utcnow())
        db.add(row)
        await db.flush()
    return row


async def record(db, **fields) -> ApprovalEvent:
    await _prune(db)
    row = ApprovalEvent(created_at=datetime.utcnow(), **fields)
    db.add(row)
    await db.flush()
    return row


async def recent(db, *, limit: int = 200) -> list[ApprovalEvent]:
    return list((await db.execute(select(ApprovalEvent).order_by(
        ApprovalEvent.created_at.desc(), ApprovalEvent.id.desc()).limit(limit))).scalars().all())


async def refused_since(db, since: datetime) -> list[ApprovalEvent]:
    """Boundaries refused because nobody could be asked (a scheduled run): the Inbox offers
    "Always allow" for next time (spec §A4)."""
    return list((await db.execute(select(ApprovalEvent).where(
        ApprovalEvent.decided_by == "policy", ApprovalEvent.decision == "deny",
        ApprovalEvent.created_at >= since).order_by(ApprovalEvent.created_at.desc()))).scalars().all())


async def _prune(db) -> None:
    now = time.monotonic()
    if _last_prune["at"] and now - _last_prune["at"] < _PRUNE_EVERY_S:
        return
    _last_prune["at"] = now
    cutoff = datetime.utcnow()
    await db.execute(delete(ApprovalEvent).where(
        ApprovalEvent.created_at < cutoff - timedelta(days=LEDGER_DAYS)))
    await db.execute(delete(PermissionGrant).where(
        PermissionGrant.task_id != "",
        PermissionGrant.created_at < cutoff - timedelta(hours=TASK_GRANT_HOURS)))


def _reset_for_tests() -> None:
    _last_prune["at"] = 0.0
```

`server/services/terminal_policy.py`. Replace the bodies of `always_allowed`, `allow_always` and
`forget`, and keep their docstrings' meaning:

```python
async def always_allowed(db) -> set[str]:
    """Rules the user said not to ask about again (0.1.61: `legacy_rule` rows in the permission
    store). Unreadable means none: ask."""
    from server.services import permission_store
    try:
        return {r.target for r in await permission_store.list_rules(db, "legacy_rule")}
    except Exception:  # noqa: BLE001 — a standing permission is never inferred from an error
        return set()


async def allow_always(db, rule: str) -> None:
    """Remember a rule. Forbidden rules and the empty rule can never be remembered."""
    from server.services import permission_store
    if not rule or rule in {k for k, _, _ in _FORBID} | {"hardline", "empty", "too-long"}:
        return
    await permission_store.add_rule(db, "legacy_rule", rule, label=describe(rule),
                                    created_from="card")
    await db.commit()


async def forget(db, rule: str) -> None:
    from server.services import permission_store
    await permission_store.delete_rule_by(db, "legacy_rule", rule)
    await db.commit()
```

Remove `ALWAYS_ALLOW_KEY` only if nothing else imports it (check with
`grep -rn ALWAYS_ALLOW_KEY server tests`); otherwise leave the constant in place.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/.claude/worktrees/wonderful-chandrasekhar-022909/arslan-0161-core && .venv/bin/python -m pytest tests/server/test_permission_store.py tests/server/test_migration_runner.py tests/server/test_terminal_policy.py tests/server/test_run_command_confirm_flow.py -q
```
Expected: PASS. If other tests seeded `terminal_always_allow` directly and now fail, switch them
to `terminal_policy.allow_always`. Find them with `grep -rln "terminal_always_allow" tests`.

- [ ] **Step 5: Mutation check**

On a `cp` backup (scratchpad), make each change one at a time and confirm a test fails:
1. In `find_grant`, drop the `task_id` filter (match any task). Expected failure:
   `test_a_conversation_grant_covers_every_task_and_a_task_grant_only_its_task`.
2. Change `LEDGER_DAYS` to 365. Expected failure: the ledger test.
3. In `allow_always`, drop the forbidden-rule guard. Expected failure: the legacy test.

- [ ] **Step 6: Commit**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/.claude/worktrees/wonderful-chandrasekhar-022909/arslan-0161-core && .venv/bin/ruff check server tests && git add -A server/db server/services/permission_store.py server/services/terminal_policy.py tests/server && git commit -m "permissions: the store — rules, grants, ledger (migration 0067); legacy don't-ask-again rules live there (0.1.61 §A5, §A8)"
```

---

### Task 2: `permissions` — the ladder, the scopes, the asker, the ledger

**Files:**
- Create: `server/services/permissions.py`
- Test: create `tests/server/test_permissions.py`

**Interfaces:**
- Consumes: Task 1's `permission_store`; `approvals.TIMEOUT_S` and `approvals.LAST_OUTCOME`
  (they exist today); `protocol.propose_action(call_id, kind, target, detail)` (it exists);
  `settings_service.shell_confirm_policy(db)`; `personal_context.current()` (`.task_id`,
  `.run_id`, `.query`).
- Produces (Tasks 3–5, ③Hands and PR 3 use these):
  - `Request`, `Context`, `Decision` (dataclasses, fields below);
  - `async decide(req, ctx) -> Decision`;
  - `async decide_many(reqs, ctx, *, title) -> list[Decision]`;
  - `async would_ask(req, ctx) -> bool`;
  - `async record_standing(req, ctx)`;
  - `asking_with(asker)`, a context manager;
  - `LAST_DECISION`, a `ContextVar[Decision | None]`;
  - `options_for(req) -> list[str]`.

  An asker is `async (frame: dict) -> dict` and returns
  `{"approved": bool, "scope": str | None, "note": str, "by": str | None}`. `by` is `None`
  exactly when the card expired.

- [ ] **Step 1: Write the failing tests**

Create `tests/server/test_permissions.py`. It reuses Task 1's fresh-database fixture; name it
the same way.

```python
"""0.1.61 §3/§A11: one decide() — money, rule, grant, card; nobody to ask means no."""
from __future__ import annotations

import pytest

from server.db import session as db_session
from server.services import approvals, permission_store, permissions
from server.services.permissions import Context, Request


class Asker:
    """A card surface that answers as told and records the frames it was shown."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.frames: list[dict] = []

    async def __call__(self, frame):
        self.frames.append(frame)
        return self.answers.pop(0)


def yes(scope=None, note=""):
    return {"approved": True, "scope": scope, "note": note, "by": "mac"}


def no(note=""):
    return {"approved": False, "scope": None, "note": note, "by": "mac"}


EXPIRED = {"approved": False, "scope": None, "note": "", "by": None}
CTX = Context(conversation_id="conv-1", task_id="turn-1")


def app(bundle="com.apple.Notes"):
    return Request(kind="app", target=bundle, title="Use Notes?", always_label="Notes")


@pytest.fixture(autouse=True)
def _fresh(portal_db):                      # Task 1's fixture
    permission_store._reset_for_tests()
    yield


async def test_options_follow_the_spec_table():
    assert permissions.options_for(app()) == ["task", "conversation", "always"]
    assert permissions.options_for(Request(kind="schedule", target="*", title="t")) == ["once", "conversation"]
    assert permissions.options_for(Request(kind="money", target="x", title="t", always_label="x")) == ["once"]
    assert permissions.options_for(Request(kind="destructive", target="x", title="t", always_label="x")) \
        == ["once", "conversation"]
    assert permissions.options_for(Request(kind="command", target="delete", title="t")) == ["once", "conversation"]
    assert permissions.options_for(Request(kind="command", target="delete", title="t",
                                           always_label="deletes files")) == ["once", "conversation", "always"]


async def test_a_card_answer_for_the_task_covers_the_next_step_of_that_task_only():
    asker = Asker(yes("task"))
    with permissions.asking_with(asker):
        first = await permissions.decide(app(), CTX)
        again = await permissions.decide(app(), CTX)
    assert (first.allowed, first.by, first.scope) == (True, "user", "task")
    assert (again.allowed, again.by, again.scope) == (True, "grant", "task")
    assert len(asker.frames) == 1
    frame = asker.frames[0]
    assert frame["options"] == ["task", "conversation", "always"]
    assert frame["always_label"] == "Notes" and frame["title"] == "Use Notes?"
    assert frame["expires_at"] > 0 and frame["call_id"]
    other_task = Asker(no())
    with permissions.asking_with(other_task):
        later = await permissions.decide(app(), Context(conversation_id="conv-1", task_id="turn-2"))
    assert later.allowed is False and len(other_task.frames) == 1


async def test_always_stores_a_rule_every_conversation_then_reads():
    with permissions.asking_with(Asker(yes("always"))):
        await permissions.decide(app(), CTX)
    with permissions.asking_with(Asker()):                     # no answers left: must not ask
        d = await permissions.decide(app(), Context(conversation_id="conv-9", task_id="t"))
    assert (d.allowed, d.by, d.scope) == (True, "rule", "always")


async def test_a_scope_the_card_did_not_offer_is_the_first_option():
    with permissions.asking_with(Asker(yes("always"))):
        d = await permissions.decide(Request(kind="schedule", target="*", title="t"), CTX)
    assert d.scope == "once"
    async with db_session.AsyncSessionLocal() as db:
        assert await permission_store.find_rule(db, "schedule", "*") is None


async def test_money_always_asks_even_after_yes():
    asker = Asker(yes("once"), yes("once"))
    pay = Request(kind="money", target="com.apple.AppStore", title="Buy this app?")
    with permissions.asking_with(asker):
        await permissions.decide(pay, CTX)
        await permissions.decide(pay, CTX)
    assert len(asker.frames) == 2
    assert asker.frames[0]["options"] == ["once"]


async def test_remember_as_stores_every_rule_a_command_matched():
    req = Request(kind="command", target="delete|hermes:recursive delete", title="Run rm -rf build?",
                  always_label="deletes files, recursive delete",
                  remember_as=(("legacy_rule", "delete"), ("legacy_rule", "hermes:recursive delete")))
    with permissions.asking_with(Asker(yes("always"))):
        await permissions.decide(req, CTX)
    async with db_session.AsyncSessionLocal() as db:
        rules = {r.target for r in await permission_store.list_rules(db, "legacy_rule")}
    assert rules == {"delete", "hermes:recursive delete"}


async def test_an_expired_card_is_not_a_refusal():
    with permissions.asking_with(Asker(EXPIRED)):
        d = await permissions.decide(app(), CTX)
    assert (d.allowed, d.by) == (False, "expired")
    assert "NOT a refusal" in d.model_text
    assert permissions.LAST_DECISION.get() is d
    assert approvals.LAST_OUTCOME.get() == "expired"
    async with db_session.AsyncSessionLocal() as db:
        [event] = await permission_store.recent(db)
    assert (event.decided_by, event.decision) == ("expired", "expired")


async def test_no_carries_the_users_words_to_the_model():
    with permissions.asking_with(Asker(no("use the Downloads copy instead"))):
        d = await permissions.decide(app(), CTX)
    assert (d.allowed, d.by, d.note) == (False, "user", "use the Downloads copy instead")
    assert "use the Downloads copy instead" in d.model_text


async def test_no_surface_means_no_at_once_and_is_recorded():
    d = await permissions.decide(Request(kind="schedule", target="*", title="Schedule “digest”?"),
                                 Context(conversation_id="conv-1"))
    assert (d.allowed, d.by) == (False, "policy")
    async with db_session.AsyncSessionLocal() as db:
        [event] = await permission_store.recent(db)
    assert (event.kind, event.decided_by, event.decision) == ("schedule", "policy", "deny")


async def test_every_decision_is_one_ledger_row_with_its_scope_and_wait():
    with permissions.asking_with(Asker(yes("conversation"))):
        await permissions.decide(app(), CTX)
        await permissions.decide(app(), CTX)
    async with db_session.AsyncSessionLocal() as db:
        events = list(reversed(await permission_store.recent(db)))
    assert [(e.decided_by, e.decision, e.scope) for e in events] == [
        ("user", "allow", "conversation"), ("grant", "allow", "conversation")]
    assert events[0].wait_ms is not None and events[1].wait_ms is None
    assert events[0].conversation_id == "conv-1" and events[0].mode == "standard"


async def test_decide_many_asks_once_for_the_apps_not_yet_allowed():
    with permissions.asking_with(Asker(yes("always"))):
        await permissions.decide(app("com.apple.Notes"), CTX)
    asker = Asker(yes("conversation"))
    reqs = [app("com.apple.Notes"), app("com.apple.reminders"), app("com.apple.mail")]
    with permissions.asking_with(asker):
        out = await permissions.decide_many(reqs, CTX, title="Use Reminders and Mail?")
    assert [d.by for d in out] == ["rule", "user", "user"]
    assert len(asker.frames) == 1 and "com.apple.Notes" not in asker.frames[0]["detail"]
    with permissions.asking_with(Asker()):
        assert not await permissions.would_ask(app("com.apple.mail"), CTX)
        assert await permissions.would_ask(app("com.apple.Safari"), CTX)


async def test_decide_many_hides_always_when_any_app_cannot_be_remembered():
    asker = Asker(yes("conversation"))
    reqs = [app("com.apple.Notes"),
            Request(kind="app", target="com.apple.systemevents", title="t", always_label="")]
    with permissions.asking_with(asker):
        await permissions.decide_many(reqs, CTX, title="Use Notes and System Events?")
    assert "always" not in asker.frames[0]["options"]


async def test_the_context_is_filled_from_the_running_turn(monkeypatch):
    from types import SimpleNamespace
    from server.services import personal_context
    monkeypatch.setattr(personal_context, "current",
                        lambda: SimpleNamespace(task_id="turn-x", run_id="turn-turn-x", query="tidy my notes"))
    asker = Asker(yes("task"))
    with permissions.asking_with(asker):
        await permissions.decide(app(), Context(conversation_id="conv-1"))
    async with db_session.AsyncSessionLocal() as db:
        assert await permission_store.find_grant(db, "conv-1", "turn-x", "app", "com.apple.Notes")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/server/test_permissions.py -q` (from the worktree).
Expected: FAIL with `ModuleNotFoundError: server.services.permissions`.

- [ ] **Step 3: Implement**

Create `server/services/permissions.py`:

```python
"""One place that decides whether Arslan may cross a boundary (0.1.61 §3, §A11).

`decide(request, context)` answers, in order:
  1. money — always a card, in every mode, never remembered;
  2. an "Always" rule for exactly this kind and target;
  3. a grant for this task or this conversation (a background job reads the grants of the
     conversation that started it);
  4. a card on the surface bound to this turn (`asking_with`): the chat window, a job's
     broadcast — or none, for a scheduled run, which has nobody to ask: the answer is no, at
     once (silence is not consent; Hermes resolves unattended runs from policy the same way).
Every decision is one ledger row (`approval_events`).

What a request IS, and whether it is forbidden outright, is the caller's business —
terminal_policy for commands, Hands for apps. This module remembers and asks. Approve for
me and Full access (PR 7) slot in between 1 and 2.
"""
from __future__ import annotations

import contextlib
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field, replace

from server.db import session as db_session
from server.services import approvals, permission_store

logger = logging.getLogger(__name__)

#: Kinds a card answers for this one time only: never a grant, never a rule.
_ONCE_ONLY = frozenset({"money", "app_risky", "capability", "other_agent", "system", "opaque",
                        "remote", "takeover"})
#: Kinds whose first choice is "for this task": work in an app is many steps.
_TASK_FIRST = frozenset({"app", "shortcut"})
#: Kinds that never offer "Always".
_NEVER_ALWAYS = _ONCE_ONLY | frozenset({"destructive", "screen", "workspace_write", "schedule"})
_EXTRA_MAX = 1024

_EXPIRED = ("Nobody answered the card for {title} in 30 minutes. This is NOT a refusal. Don't "
            "retry it in this turn. Finish what you can and tell the user what is waiting.")
_NO_SURFACE = ("{title} needs the user's OK, and this run has nobody to ask (it runs on its "
               "own). It was not done. Tell the user, so they can allow it for next time.")


@dataclass(frozen=True)
class Request:
    kind: str
    target: str                 # the scope a grant or rule is stored under
    title: str                  # the card's question, one line
    detail: str = ""            # what exactly: command, element label, arguments
    why: str = ""               # the model's one-line reason, if any
    always_label: str = ""      # the literal scope "Always" stores; "" hides "Always"
    conversation_ok: bool = True
    extra: dict = field(default_factory=dict)
    frame: dict | None = None   # the caller's card frame (its type and fields); None → propose_action
    remember_as: tuple[tuple[str, str], ...] = ()   # what "Always" stores; () → ((kind, target),)
    grant_as: tuple[tuple[str, str], ...] = ()      # what a task/conversation grant stores


@dataclass(frozen=True)
class Context:
    conversation_id: str | None
    job_id: str | None = None
    run_id: str | None = None
    task_id: str | None = None  # the turn or job "for this task" covers; filled when empty
    surface: str = "chat"
    user_request: str = ""      # the user's latest words (trusted), for the reviewer (PR 7)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    by: str                     # floor | mode | rule | grant | reviewer | user | expired | policy
    scope: str | None = None    # once | task | conversation | always
    note: str = ""              # the user's "tell Arslan instead"
    model_text: str = ""        # what the tool result tells the model when not allowed


Asker = Callable[[dict], Awaitable[dict]]
_ASKER: ContextVar[Asker | None] = ContextVar("permissions_asker", default=None)
#: The last decision in this context: tool results read it to tell "expired" from "no".
LAST_DECISION: ContextVar[Decision | None] = ContextVar("permissions_last_decision", default=None)


@contextlib.contextmanager
def asking_with(asker: Asker | None) -> Iterator[None]:
    """Bind the card surface for everything awaited inside (a turn, a job)."""
    token = _ASKER.set(asker)
    try:
        yield
    finally:
        _ASKER.reset(token)


def options_for(req: Request) -> list[str]:
    opts = ["task" if req.kind in _TASK_FIRST else "once"]
    if req.conversation_ok and req.kind not in _ONCE_ONLY:
        opts.append("conversation")
    if req.always_label and req.kind not in _NEVER_ALWAYS:
        opts.append("always")
    return opts


async def decide(req: Request, ctx: Context) -> Decision:
    ctx = _filled(ctx)
    mode = await _mode()
    standing = await _standing(req, ctx, mode)
    if standing is not None:
        return _done(standing)
    return _done(await _ask(req, ctx, mode))


async def decide_many(reqs: list[Request], ctx: Context, *, title: str) -> list[Decision]:
    """One card for several requests of one kind (Hands' DesktopAccess). Those already allowed
    are left off the card; one answer covers every one shown; decisions in input order."""
    ctx = _filled(ctx)
    mode = await _mode()
    out: list[Decision | None] = [await _standing(r, ctx, mode) for r in reqs]
    shown = [r for r, d in zip(reqs, out) if d is None]
    if shown:
        combined = Request(
            kind=shown[0].kind, target="\x1e".join(r.target for r in shown), title=title,
            detail="\n".join(r.detail or r.target for r in shown),
            always_label=(", ".join(r.always_label for r in shown)
                          if all(r.always_label for r in shown) else ""),
            conversation_ok=all(r.conversation_ok for r in shown),
            extra={"items": [r.extra for r in shown]},
            remember_as=tuple((r.kind, r.target) for r in shown),
            grant_as=tuple((r.kind, r.target) for r in shown),
            frame=shown[0].frame)
        decided = await _ask(combined, ctx, mode)
        out = [d if d is not None else decided for d in out]
    return [_done(d) for d in out]          # type: ignore[arg-type]


async def would_ask(req: Request, ctx: Context) -> bool:
    """Would `decide` show a card? No side effects: nothing asked, nothing recorded."""
    return await _standing(req, _filled(ctx), await _mode(), record=False) is None


async def record_standing(req: Request, ctx: Context) -> None:
    """A caller that found a standing answer itself (terminal_policy's legacy rules) still
    writes the ledger row, so the count of decisions stays whole."""
    await _record(req, _filled(ctx), await _mode(), Decision(True, "rule", "always"))


# ── the ladder ────────────────────────────────────────────────────────────────

async def _standing(req: Request, ctx: Context, mode: str, *, record: bool = True) -> Decision | None:
    if req.kind in _ONCE_ONLY:
        return None
    async with db_session.AsyncSessionLocal() as db:
        rule = await permission_store.find_rule(db, req.kind, req.target)
        if rule is not None:
            decision = Decision(True, "rule", "always")
            if record:
                await permission_store.touch_rule(db, rule)
                await _record_in(db, req, ctx, mode, decision, rule_id=rule.id)
                await db.commit()
            return decision
        grant = await permission_store.find_grant(db, ctx.conversation_id, ctx.task_id,
                                                  req.kind, req.target)
        if grant is not None:
            decision = Decision(True, "grant", "task" if grant.task_id else "conversation")
            if record:
                await _record_in(db, req, ctx, mode, decision, grant_id=grant.id)
                await db.commit()
            return decision
    return None


async def _ask(req: Request, ctx: Context, mode: str) -> Decision:
    asker = _ASKER.get()
    if asker is None:
        decision = Decision(False, "policy", model_text=_NO_SURFACE.format(title=req.title))
        await _record(req, ctx, mode, decision)
        return decision
    opts = options_for(req)
    base = dict(req.frame) if req.frame else _generic_frame(req)
    call_id = base.get("call_id") or uuid.uuid4().hex
    frame = {**base, "call_id": call_id, "title": req.title, "options": opts,
             "always_label": req.always_label if "always" in opts else "",
             "perm_kind": req.kind, "dedupe": f"{req.kind}\x1f{req.target}",
             "expires_at": time.time() + approvals.TIMEOUT_S}
    if req.why and "why" not in frame:
        frame["why"] = req.why[:300]
    started = time.monotonic()
    answer = await asker(frame)
    wait_ms = int((time.monotonic() - started) * 1000)
    note = str(answer.get("note") or "").strip()[:500]
    if answer.get("by") is None:
        decision = Decision(False, "expired", model_text=_EXPIRED.format(title=req.title))
    elif answer.get("approved"):
        scope = answer.get("scope") if answer.get("scope") in opts else opts[0]
        decision = Decision(True, "user", scope)
    else:
        decision = Decision(False, "user", note=note, model_text=_declined_text(req.title, note))
    async with db_session.AsyncSessionLocal() as db:
        rule_id = grant_id = None
        if decision.allowed and decision.scope == "always":
            for kind, target in req.remember_as or ((req.kind, req.target),):
                rule = await permission_store.add_rule(db, kind, target, label=req.always_label,
                                                       created_from=call_id)
                rule_id = rule_id or rule.id
        elif decision.allowed and decision.scope in ("task", "conversation") and ctx.conversation_id:
            task = (ctx.task_id or "") if decision.scope == "task" else ""
            if decision.scope == "task" and not task:
                decision = replace(decision, scope="once")   # no task to remember it for
            else:
                for kind, target in req.grant_as or ((req.kind, req.target),):
                    grant = await permission_store.add_grant(db, ctx.conversation_id, task, kind,
                                                             target, call_id=call_id)
                    grant_id = grant_id or grant.id
        await _record_in(db, req, ctx, mode, decision, wait_ms=wait_ms, rule_id=rule_id,
                         grant_id=grant_id)
        await db.commit()
    return decision


def _generic_frame(req: Request) -> dict:
    from server.ws import protocol
    return protocol.propose_action(uuid.uuid4().hex, req.kind, req.target, req.detail)


def _declined_text(title: str, note: str) -> str:
    if note:
        return f"The user said no to: {title}. They said: {note}"
    return f"The user said no to: {title}. Don't ask for it again in this turn."


def _done(decision: Decision) -> Decision:
    LAST_DECISION.set(decision)
    approvals.LAST_OUTCOME.set("approved" if decision.allowed
                               else "expired" if decision.by == "expired" else "declined")
    return decision


def _filled(ctx: Context) -> Context:
    from server.services import personal_context
    current = personal_context.current()
    if current is None:
        return replace(ctx, task_id=ctx.task_id or ctx.job_id)
    return replace(ctx, task_id=ctx.task_id or ctx.job_id or getattr(current, "task_id", None),
                   run_id=ctx.run_id or getattr(current, "run_id", None),
                   user_request=ctx.user_request or getattr(current, "query", "") or "")


async def _mode() -> str:
    """Standard (sandbox first) or Careful (the old "ask for every command"). PR 7 adds
    Approve for me and Full access, per conversation."""
    from server.services import settings_service
    try:
        async with db_session.AsyncSessionLocal() as db:
            policy = await settings_service.shell_confirm_policy(db)
    except Exception:  # noqa: BLE001 — an unreadable setting is the default
        return "standard"
    return "careful" if policy == "ask_all" else "standard"


async def _record(req: Request, ctx: Context, mode: str, decision: Decision, **ids) -> None:
    try:
        async with db_session.AsyncSessionLocal() as db:
            await _record_in(db, req, ctx, mode, decision, **ids)
            await db.commit()
    except Exception:  # noqa: BLE001 — the ledger never breaks a decision
        logger.warning("approval ledger write failed", exc_info=True)


async def _record_in(db, req: Request, ctx: Context, mode: str, decision: Decision, *,
                     wait_ms: int | None = None, rule_id: int | None = None,
                     grant_id: int | None = None) -> None:
    await permission_store.record(
        db, conversation_id=ctx.conversation_id, job_id=ctx.job_id,
        run_id=str(ctx.run_id) if ctx.run_id is not None else None,
        kind=req.kind, target=req.target[:2000], detail=req.detail[:500], extra=_extra(req.extra),
        mode=mode, decided_by=decision.by,
        decision=("allow" if decision.allowed else "expired" if decision.by == "expired" else "deny"),
        scope=decision.scope, rule_id=rule_id, grant_id=grant_id, wait_ms=wait_ms)


def _extra(extra: dict) -> dict | None:
    if not extra:
        return None
    try:
        text = json.dumps(extra, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return {"unserialisable": True}
    return extra if len(text) <= _EXTRA_MAX else {"truncated": text[:_EXTRA_MAX]}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/server/test_permissions.py tests/server/test_permission_store.py -q`.
Expected: PASS.

- [ ] **Step 5: Mutation check**

On a `cp` backup, make each change one at a time and confirm a test fails:
1. Remove `money` from `_ONCE_ONLY`.
2. Make `options_for` always use "once" first.
3. Make an expired answer `Decision(False, "user")`.
4. Store grants with `task = ctx.task_id` for the conversation scope too.
5. Skip `_record` when there is no asker.

- [ ] **Step 6: Commit**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/.claude/worktrees/wonderful-chandrasekhar-022909/arslan-0161-core && .venv/bin/ruff check server tests && git add server/services/permissions.py tests/server/test_permissions.py && git commit -m "permissions: one decide() — money, rule, grant, card; scopes by kind; no surface means no; one ledger row each (0.1.61 §3, §A11)"
```

---

### Task 3: The card registry v2 — 30 minutes, scope and note, one card for identical requests, the job surface

**Files:**
- Modify: `server/services/approvals.py`
- Test: create `tests/server/test_approvals_v2.py`; update the tests that assert
  `TIMEOUT_S == 300` or a 300 s `expires_at`. Find them with
  `grep -rn "TIMEOUT_S\|300_000\|expires_at" tests/server`.

**Interfaces:**
- Consumes: Task 2's `permissions` (`decide`, `Request`, `Context`, `record_standing`).
- Produces:
  - `approvals.TIMEOUT_S = 1800`.
  - Decision dicts from `close_card`, `answer` and the askers, now
    `{"approved", "remember", "scope", "note", "by"}`.
  - `answer_by_id(call_id, approve, *, source, remember=False, scope=None, note="")`.
  - `decline_pending(call_ids: set[str], note: str, *, source="mac") -> int`.
  - `class BroadcastAsker`, the job surface: `await asker(frame) -> dict`, with the attribute
    `unanswered: bool`.
  - `JobConfirmations.asker`, a `BroadcastAsker`.
  - `JobConfirmations.workspace_write`, `.schedule` and `.command`: rule cards on `decide`,
    outside/retry unchanged.

- [ ] **Step 1: Write the failing tests**

Create `tests/server/test_approvals_v2.py`:

```python
"""0.1.61 §A4: cards wait 30 minutes; an answer carries a scope and a note; identical requests
share one card; the phone and the island answer once only; a job asks like a window."""
from __future__ import annotations

import asyncio

import pytest

from server.services import approvals, run_registry


@pytest.fixture(autouse=True)
def _clean():
    approvals._reset_for_tests()
    yield
    approvals._reset_for_tests()


def frame(call_id="c1", dedupe="app\x1fcom.apple.Notes", options=("task", "conversation", "always")):
    return {"type": "propose_action", "call_id": call_id, "kind": "app", "target": "Notes",
            "detail": "", "options": list(options), "dedupe": dedupe}


def test_cards_wait_thirty_minutes():
    assert approvals.TIMEOUT_S == 1800


async def test_an_answer_carries_a_scope_the_card_offered_and_a_note_on_no(monkeypatch):
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    p = approvals.open_card("conv", frame())
    approvals.answer({"type": "confirm_action", "call_id": "c1", "scope": "conversation"})
    assert approvals.close_card(p)["scope"] == "conversation"
    q = approvals.open_card("conv", frame("c2", dedupe="x"))
    approvals.answer({"type": "confirm_action", "call_id": "c2", "scope": "forever"})
    assert approvals.close_card(q)["scope"] == "task"           # not offered → first option
    r = approvals.open_card("conv", frame("c3", dedupe="y"))
    approvals.answer({"type": "cancel_action", "call_id": "c3", "note": "use Bear instead"})
    d = approvals.close_card(r)
    assert (d["approved"], d["note"]) == (False, "use Bear instead")


async def test_legacy_remember_maps_to_a_scope(monkeypatch):
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    p = approvals.open_card("conv", frame(options=("once", "conversation", "always")))
    approvals.answer({"type": "confirm_action", "call_id": "c1", "remember": True})
    assert approvals.close_card(p)["scope"] == "always"


@pytest.mark.parametrize("source", ["phone", "island"])
async def test_phone_and_island_answers_are_once_only(monkeypatch, source):
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    p = approvals.open_card("conv", frame())
    approvals.answer({"type": "confirm_action", "call_id": "c1", "scope": "always", "source": source})
    assert approvals.close_card(p)["scope"] == "task"


async def test_identical_requests_share_one_card(monkeypatch):
    sent = []
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: sent.append)
    a = approvals.open_card("conv", frame("c1"))
    b = approvals.open_card("conv", frame("c2"))                # same dedupe key
    assert a is b and [f["call_id"] for f in sent] == ["c1"]
    approvals.answer({"type": "confirm_action", "call_id": "c1", "scope": "task"})
    assert approvals.close_card(a)["approved"] and approvals.close_card(b)["approved"]
    assert [f["type"] for f in sent].count("card_resolved") == 1


async def test_one_waiter_expiring_does_not_close_a_shared_card(monkeypatch):
    sent = []
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: sent.append)
    a = approvals.open_card("conv", frame("c1"))
    b = approvals.open_card("conv", frame("c2"))
    assert approvals.close_card(a)["by"] is None                # this waiter gave up
    assert "c1" in approvals.known_ids()                       # the card is still open for b
    approvals.answer({"type": "confirm_action", "call_id": "c1"})
    assert approvals.close_card(b)["approved"] is True
    assert [f["type"] for f in sent].count("card_resolved") == 1


async def test_decline_pending_answers_only_the_named_cards(monkeypatch):
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    mine = approvals.open_card("conv", frame("c1"), broadcast=False)
    other = approvals.open_card("conv", frame("c2", dedupe="z"))
    assert approvals.decline_pending({"c1"}, "actually, open Mail first") == 1
    d = approvals.close_card(mine)
    assert (d["approved"], d["note"], d["by"]) == (False, "actually, open Mail first", "mac")
    assert not other.future.done()


async def test_a_job_asks_like_a_window_and_stops_waiting_after_one_expiry(monkeypatch):
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    monkeypatch.setattr(approvals, "TIMEOUT_S", 0.05)
    asker = approvals.BroadcastAsker("conv")
    first = await asker(frame("c1"))
    assert first["by"] is None and asker.unanswered
    second = await asker(frame("c2", dedupe="other"))           # does not wait again
    assert second["by"] is None
    assert "c2" not in approvals.known_ids()


async def test_a_job_card_shows_its_options_and_records_the_scope(monkeypatch):
    sent = []
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: sent.append)
    asker = approvals.BroadcastAsker("conv")
    task = asyncio.ensure_future(asker(frame("c1")))
    await asyncio.sleep(0)
    assert sent[0]["background"] is True and sent[0]["options"] == ["task", "conversation", "always"]
    approvals.answer({"type": "confirm_action", "call_id": "c1", "scope": "conversation"})
    assert (await task)["scope"] == "conversation"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/server/test_approvals_v2.py -q`.
Expected: FAIL, because `TIMEOUT_S` is 300, decisions carry no scope or note, no card is merged,
and `BroadcastAsker` and `decline_pending` are missing.

- [ ] **Step 3: Implement** (in `server/services/approvals.py`)

1. **The timeout.** Set `TIMEOUT_S = 1800` and update the module docstring's "300 s" sentence:
   "Unanswered cards expire after 30 minutes (0.1.61): expired is never declined — the model is
   told nobody answered."
2. **`Pending`.** Add the field `waiters: int = 1`.
3. **`open_card`.** Before creating a new `Pending`, merge identical requests:

```python
    key = frame.get("dedupe")
    if key:
        for existing in _pending.values():
            if (existing.conversation_id == conversation_id and existing.frame.get("dedupe") == key
                    and not existing.future.done()):
                existing.waiters += 1          # the same question, already on screen: one card
                return existing
```

4. **`close_card`.** Make it waiter-aware and add `scope`/`note` to the expired decision:

```python
def close_card(pending: Pending) -> dict:
    """Unregister a card once its last waiter is done and tell every socket how it ended
    (`card_resolved`, once). Returns the decision: approved, remember, scope, note, by."""
    pending.waiters -= 1
    if pending.future.done() and not pending.future.cancelled():
        decision = pending.future.result()
        outcome = "approved" if decision["approved"] else "declined"
    else:
        decision = {"approved": False, "remember": False, "scope": None, "note": "", "by": None}
        outcome = "expired"
        if pending.waiters > 0:
            return decision                    # another waiter still waits on this card
    if _pending.pop(pending.call_id, None) is not None and not pending.private:
        run_registry.make_emit(pending.conversation_id)(
            protocol.card_resolved(pending.call_id, outcome, decision["by"]))
    return decision
```

5. **`answer`.** The decision carries a scope (validated against the frame's `options`) and, on
   No, a note:

```python
    if not pending.future.done():
        options = [o for o in pending.frame.get("options") or [] if isinstance(o, str)]
        scope = data.get("scope")
        if by in ("phone", "island"):
            scope = options[0] if options else None          # never more than once from there
        elif scope not in options:
            scope = _legacy_scope(options, bool(data.get("remember")))
        decision = {"approved": ANSWERS[kind], "remember": bool(data.get("remember")),
                    "scope": scope if ANSWERS[kind] else None,
                    "note": "" if ANSWERS[kind] else str(data.get("note") or "").strip()[:500],
                    "by": by}
        if pending.frame["type"] in WINDOW_ONLY:
            decision["extras"] = _extras(pending.frame, data) if ANSWERS[kind] else {}
        pending.future.set_result(decision)
```

   Add next to it:

```python
def _legacy_scope(options: list[str], remember: bool) -> str | None:
    """A reply without a scope (the UI before 0.1.61 PR 2b): the old checkbox, mapped."""
    if not options:
        return None
    if remember:
        for preferred in ("always", "conversation"):
            if preferred in options:
                return preferred
    return options[0]
```

6. **`answer_by_id`.** It becomes
   `answer_by_id(call_id, approve, *, source, remember=False, scope=None, note="")`. It passes
   `"scope": scope, "note": note` through in the `answer({...})` dict.
7. **Add `decline_pending`:**

```python
def decline_pending(call_ids: set[str], note: str, *, source: str = "mac") -> int:
    """Answer these waiting cards No, with the user's words as the note — a message typed in
    the window while its card waits (spec §A4). Returns how many were answered."""
    answered = 0
    for call_id in list(call_ids):
        pending = _pending.get(call_id)
        if pending is None or pending.future.done():
            continue
        pending.future.set_result({"approved": False, "remember": False, "scope": None,
                                   "note": note.strip()[:500], "by": source})
        answered += 1
    return answered
```

8. **Add `BroadcastAsker`**, the job surface, above `JobConfirmations`. It moves the "after one
   expiry, stop waiting" rule out of `JobConfirmations._card`:

```python
class BroadcastAsker:
    """A background job's card surface (0.1.61): every window on the conversation, the Inbox,
    the island and the phone see the card. Once one card in the job went unanswered the person
    is away: later cards do not open and wait 30 minutes each; they read as expired at once
    (seen on a device 2026-10-05: a model told "expired" asked again within two seconds)."""

    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id
        self.unanswered = False

    async def __call__(self, frame: dict) -> dict:
        if self.unanswered:
            LAST_OUTCOME.set("expired")
            return {"approved": False, "remember": False, "scope": None, "note": "", "by": None}
        pending = open_card(self.conversation_id, frame | {"background": True})
        try:
            with desktop_status.awaiting_approval(self.conversation_id):
                await asyncio.wait_for(asyncio.shield(pending.future), timeout=TIMEOUT_S)
        except TimeoutError:
            pass
        finally:
            decision = close_card(pending)
        if decision["by"] is None:
            self.unanswered = True
        LAST_OUTCOME.set("approved" if decision["approved"]
                         else "expired" if decision["by"] is None else "declined")
        return decision
```

9. **`JobConfirmations`.**
   - Hold `self.asker = BroadcastAsker(conversation_id)`. `_card(frame)` becomes
     `(await self.asker(frame))["approved"]`, and the `_unanswered` field goes away.
   - Reimplement `workspace_write` and `schedule` on `permissions.decide`. A job's grants are its
     conversation's, so the per-job `_write_granted` flag goes away:

```python
    async def workspace_write(self, action: str, path: str) -> bool:
        from server.db import session as db_session
        from server.services import permissions, settings_service
        async with db_session.AsyncSessionLocal() as db:
            root = await settings_service.workspace_dir(db)
        if root is None:
            return False
        with permissions.asking_with(self.asker):
            decision = await permissions.decide(permissions.Request(
                kind="workspace_write", target=str(root), title=f"Let Arslan write in {root.name}?",
                detail=path, frame=protocol.propose_workspace_write(uuid.uuid4().hex, str(root),
                                                                    action, path)),
                permissions.Context(conversation_id=self.conversation_id, surface="job"))
        return decision.allowed

    async def schedule(self, name: str, when: str) -> bool:
        from server.services import permissions
        with permissions.asking_with(self.asker):
            decision = await permissions.decide(permissions.Request(
                kind="schedule", target="*", title=f"Schedule “{name}”?", detail=when,
                frame=protocol.propose_schedule(uuid.uuid4().hex, name, when)),
                permissions.Context(conversation_id=self.conversation_id, surface="job"))
        return decision.allowed
```

   - In `command`, keep the `sandbox in ("outside", "retry")` branch exactly as it is, using
     `self._ask_with_shadow`. Keep the remote branch as it is (`self._card(frame)` with the remote
     frame). Replace the local rule-card ending, from `frame = protocol.propose_run_command(` to
     the final `return await self._ask_with_shadow(frame, command, verdict)`, with:

```python
        shell = terminal_policy.as_shell(command, argv)
        rules = sorted(terminal_policy.ask_rules(shell))
        if standing:
            from server.services import permissions
            await permissions.record_standing(_command_request(shell, rules, None),
                                              permissions.Context(conversation_id=self.conversation_id,
                                                                  surface="job"))
            return True
        frame = protocol.propose_run_command(
            uuid.uuid4().hex, command, argv, reason=verdict.reason or f"risk: {risk}",
            rule=verdict.rule or None)
        return await self._decide_with_shadow(_command_request(shell, rules, frame), command, verdict)
```

     This applies only on the non-remote path. The `may_skip_card` call above it stays; move the
     `standing` short-cut into the snippet above, so that a standing answer records a ledger row
     before returning.
   - Add the module-level helper `_command_request`. Task 4 reuses it from the window:

```python
def _command_request(shell: str, rules: list[str], frame: dict | None):
    """A rule card as a permission request: "In this conversation" covers this kind of command
    (its rules) here; "Always" stores EVERY rule it matched (spec §A9 — the first rule alone
    could never silence `rm -rf build`, which matches two)."""
    from server.services import permissions, terminal_policy
    return permissions.Request(
        kind="command", target="|".join(rules) or shell, title=f"Run `{shell[:80]}`?", detail=shell,
        always_label=", ".join(terminal_policy.describe(r) for r in rules),
        remember_as=tuple(("legacy_rule", r) for r in rules), frame=frame)
```

   - Add `_decide_with_shadow`, the rule-card twin of `_ask_with_shadow`. It records the shadow
     judgment and the outcome exactly as `_ask_with_shadow` does, but decides through
     `permissions.decide` under `asking_with(self.asker)`:

```python
    async def _decide_with_shadow(self, req, command: str, verdict) -> bool:
        from server.services import judgment, permissions
        judgment.shadow("tool.approval", judgment.approval_state(command, rule=verdict.rule,
                                                                 reason=verdict.reason),
                        ref=req.frame["call_id"], conversation_id=self.conversation_id)
        with permissions.asking_with(self.asker):
            decision = await permissions.decide(req, permissions.Context(
                conversation_id=self.conversation_id, surface="job"))
        judgment.record_outcome_later(req.frame["call_id"], "approved" if decision.allowed else "declined",
                                      point="tool.approval")
        return decision.allowed
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/.claude/worktrees/wonderful-chandrasekhar-022909/arslan-0161-core && .venv/bin/python -m pytest tests/server/test_approvals_v2.py tests/server/test_inbox_approvals.py tests/server/test_island_approvals.py tests/server/test_phone_turn_cards.py tests/server/test_judgment_cards.py tests/server/test_hands_card_in_turn.py tests/server/test_permissions.py -q
```
Expected: PASS. Update assertions that encode 300 s, for example
`listed["expires_at"] - listed["opened_at"] == approvals.TIMEOUT_S`; those keep working. Update
any test that read the removed `JobConfirmations._unanswered`.

- [ ] **Step 5: Mutation check**

On a `cp` backup, make each change one at a time and confirm a test fails:
1. In `close_card`, drop the `waiters > 0` early return.
2. In `open_card`, ignore `dedupe`.
3. In `answer`, let the phone keep its scope.
4. In `BroadcastAsker`, never set `unanswered`.

- [ ] **Step 6: Commit**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/.claude/worktrees/wonderful-chandrasekhar-022909/arslan-0161-core && .venv/bin/ruff check server tests && git add server/services/approvals.py tests/server && git commit -m "approvals: cards wait 30 minutes and carry a scope and a note; identical requests share one card; a job asks like a window (0.1.61 §A4)"
```

---

### Task 4: The window surface, callbacks on `decide`, a typed message answers the card, honest tool results

**Files:**
- Modify: `server/ws/arslan.py`. The changes are in:
  - `_reader` (around lines 296–318);
  - `_ask_everywhere` (around lines 344–390);
  - `run_with_confirm_frames` (around lines 221–245);
  - `confirm_workspace_write` (around lines 410–422);
  - `confirm_schedule` (around lines 424–433);
  - `confirm_command` (around lines 452–516, the local non-sandbox branch).
- Modify: `server/services/background_jobs.py` (`_execute`, around lines 271–300).
- Modify: `server/orchestrator/tool_loop.py` (`_declined`, around lines 884–892).
- Modify: `server/services/scheduler.py`. Correct the stale docstring at around lines 479–486:
  scheduled runs run "run"-level commands and refuse anything that needs a card, at once.
- Test: create `tests/server/test_window_permissions.py`, and extend
  `tests/server/test_run_command_confirm_flow.py` where noted.

**Interfaces:**
- Consumes:
  - from Task 2: `permissions.decide`, `asking_with`, `LAST_DECISION`, `Request`, `Context`,
    `record_standing`;
  - from Task 3: `approvals.decline_pending`, `approvals.BroadcastAsker`,
    `approvals._command_request`, and decision dicts carrying scope and note.
- Produces:
  - Every chat turn runs with the window asker bound. A Hands `decide()` in a chat turn therefore
    shows the window's private card, which the Inbox and island can still answer.
  - Every job runs with its `BroadcastAsker` bound.

- [ ] **Step 1: Write the failing tests**

Create `tests/server/test_window_permissions.py`. Reuse the harness of
`tests/server/test_run_command_confirm_flow.py`: `build_ws_client`, `_enable_shell`,
`_stub_tool_loop_adapter`, `_stub_run_command_executor` and `_collect_until`, together with the
`_clean_registry` autouse fixture from `tests/server/test_inbox_approvals.py`.

```python
"""0.1.61 §A4: the chat window's cards through decide(); a typed message answers the card;
an expired card is not a refusal; grants are kept per conversation."""
from __future__ import annotations

import pytest

from server.services import approvals, run_registry, turn_journal
from tests.server.conftest import build_ws_client
from tests.server.test_run_command_confirm_flow import (
    _collect_until,
    _enable_shell,
    _stub_run_command_executor,
    _stub_tool_loop_adapter,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    for d in (run_registry._tasks, run_registry._by_conversation, run_registry._sinks, run_registry._recorders):
        d.clear()
    turn_journal._active.clear()
    approvals._reset_for_tests()
    yield
    approvals._reset_for_tests()
    for d in (run_registry._tasks, run_registry._by_conversation, run_registry._sinks, run_registry._recorders):
        d.clear()
    turn_journal._active.clear()


@pytest.fixture
def app_client(tmp_path, monkeypatch, portal):
    return build_ws_client(portal, tmp_path, monkeypatch, db_name="window_permissions.db")


def test_a_rule_card_offers_scopes_and_this_conversation_holds_on_a_new_socket(app_client, monkeypatch):
    _enable_shell(app_client, policy="ask_risky")
    _stub_tool_loop_adapter(monkeypatch, "rm", ["-f", "build/out.txt"])
    executor = _stub_run_command_executor(monkeypatch)
    with app_client.websocket_connect("/ws/arslan/conv-a") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "clean the build"})
        card = _collect_until(ws, "propose_run_command")[-1]
        assert card["options"] == ["once", "conversation", "always"]
        assert card["always_label"] and card["title"]
        ws.send_json({"type": "confirm_run_command", "call_id": card["call_id"], "scope": "conversation"})
        _collect_until(ws, "stream_end")
    with app_client.websocket_connect("/ws/arslan/conv-a") as ws2:        # a new socket, same conversation
        ws2.receive_json()
        ws2.send_json({"type": "user_message", "content": "again"})
        frames = _collect_until(ws2, "stream_end")
        assert "propose_run_command" not in [f.get("type") for f in frames]
    assert len(executor.calls) == 2


def test_a_message_typed_while_a_card_waits_answers_it(app_client, monkeypatch):
    _enable_shell(app_client, policy="ask_all")
    _stub_tool_loop_adapter(monkeypatch, "git", ["status"])
    executor = _stub_run_command_executor(monkeypatch)
    with app_client.websocket_connect("/ws/arslan/conv-b") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "check the repo"})
        card = _collect_until(ws, "propose_run_command")[-1]
        ws.send_json({"type": "user_message", "content": "no — look at the other folder"})
        frames = _collect_until(ws, "stream_end")
        assert card["call_id"] not in approvals.known_ids()
        results = [f for f in frames if f.get("type") == "tool_result"]
        assert results and "look at the other folder" in results[0].get("summary", "") + str(results[0])
    assert executor.calls == []


def test_an_expired_window_card_is_reported_as_no_answer(app_client, monkeypatch):
    monkeypatch.setattr(approvals, "TIMEOUT_S", 0.2)
    _enable_shell(app_client, policy="ask_all")
    _stub_tool_loop_adapter(monkeypatch, "git", ["status"])
    _stub_run_command_executor(monkeypatch)
    with app_client.websocket_connect("/ws/arslan/conv-c") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "check the repo"})
        frames = _collect_until(ws, "stream_end")
        results = [f for f in frames if f.get("type") == "tool_result"]
        assert results and "NOT a refusal" in str(results[0])
```

Before finalising the second test's assertion, check how `tool_result` frames carry the error
text: read `protocol.tool_result` and `_record_tool_result`. Assert on the field that carries the
refusal text (the model-facing error). If the frame's `summary` is shortened, assert on the
recorded run step or the adapter's next-turn input instead. The goal is to show that the user's
note reaches the model. Make this test a real check, not a string match on whatever field
happens to be convenient.

In `tests/server/test_run_command_confirm_flow.py`, add one test proving that "Always" now stores
**both** rules of `rm -rf build`, so the next one runs without a card:

```python
def test_always_on_a_two_rule_command_silences_it_next_time(app_client, monkeypatch):
    _enable_shell(app_client, policy="ask_risky")
    _stub_tool_loop_adapter(monkeypatch, "rm", ["-rf", "build"])
    executor = _stub_run_command_executor(monkeypatch)
    with app_client.websocket_connect("/ws/arslan/two-rules") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "clean"})
        card = _collect_until(ws, "propose_run_command")[-1]
        ws.send_json({"type": "confirm_run_command", "call_id": card["call_id"], "scope": "always"})
        _collect_until(ws, "stream_end")
        ws.send_json({"type": "user_message", "content": "clean again"})
        frames = _collect_until(ws, "stream_end")
        assert "propose_run_command" not in [f.get("type") for f in frames]
    assert len(executor.calls) == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/.claude/worktrees/wonderful-chandrasekhar-022909/arslan-0161-core && .venv/bin/python -m pytest tests/server/test_window_permissions.py tests/server/test_run_command_confirm_flow.py -q
```
Expected: FAIL. The cards carry no options, a new socket asks again, a typed message waits behind
the card, and the expired text says "declined".

- [ ] **Step 3: Implement**

In `server/ws/arslan.py`:

1. **`_ask_everywhere`.**
   - Track this window's cards: `my_cards: set[str] = set()` beside `cards_waiting`. Add
     `pending.call_id` when the card opens and discard it in `finally`.
   - At the start, set `permissions.LAST_DECISION.set(None)`.
   - After `close_card`, set
     `approvals.LAST_OUTCOME.set("approved" if decision["approved"] else "expired" if decision["by"] is None else "declined")`.
     This fixes §A9 "an expired chat card is told to the model as declined" for the outside/retry
     cards too.
   - Return `{"approved": ..., "remember": ..., "scope": decision.get("scope"), "note": decision.get("note") or "", "by": decision["by"], "extras": ...}`.
2. **The window asker.** Add:

```python
    async def _window_asker(frame: dict) -> dict:
        """This window's card surface for permissions.decide (0.1.61): private to the window,
        answerable from the Inbox and the island; a turn the iPhone started shows it everywhere."""
        return await _ask_everywhere(frame, broadcast=phone_turn["on"])
```

3. **`run_with_confirm_frames`.** Bind the asker for the turn. Change
   `with desktop_status.working(conversation_id, title=title):` to
   `with desktop_status.working(conversation_id, title=title), permissions.asking_with(_window_asker):`,
   and import `permissions` from `server.services`.
4. **`_reader`.** When a `user_message` arrives while this window's cards wait, answer them No,
   with the text as the note. This comes before the existing queue logic, so the message is still
   queued and runs next:

```python
                if t == "user_message" and my_cards:
                    approvals.decline_pending(set(my_cards), str(data.get("content") or ""))
```

5. **`confirm_workspace_write`.** Reimplement it on `decide`, with
   `kind="workspace_write"`, `target=str(ws_root)`,
   `title=f"Let Arslan write in {ws_root.name}?"`, `detail=path` and
   `frame=protocol.propose_workspace_write(uuid.uuid4().hex, str(ws_root), action, path)`. Delete
   the per-socket `workspace_write_granted` dict: the conversation grant replaces it and survives
   reloads.
6. **`confirm_schedule`.** Reimplement it on `decide`, with `kind="schedule"`, `target="*"`,
   `title=f"Schedule “{name}”?"`, `detail=when` and
   `frame=protocol.propose_schedule(uuid.uuid4().hex, name, when)`. Delete `schedule_granted`.
7. **`confirm_command`** (the local branch; leave the `sandbox in ("outside", "retry")` branch and
   `_sandbox_card` as they are).
   - After the `may_skip_card(...)` check, skip the card with a ledger row when `standing` is
     true: `await permissions.record_standing(approvals._command_request(shell, rules, None), ctx)`.
   - Keep the shadow judgment exactly as today (`judgment.shadow(...)` before the card,
     `record_outcome_later(...)` after).
   - Build the frame as today, `protocol.propose_run_command(call_id, ..., rule=...)`, and decide
     through `permissions.decide(approvals._command_request(shell, rules, frame), ctx)`, with
     `ctx = permissions.Context(conversation_id=conversation_id)`.
   - Delete the `session_cmd_allow` exact-text set and the `may_remember(...)`/`allow_always`
     tail: `decide` stores the grant or rule now.
   - Remote commands keep their current `_ask` path untouched (P3b ruling ③: never remembered).
   - `shell` is `terminal_policy.as_shell(command, argv)`, and `rules` is
     `sorted(terminal_policy.ask_rules(shell))`.

In `server/services/background_jobs.py` `_execute`, add `permissions.asking_with(confirmations.asker)`
to the `with` that binds `personal_context` and `desktop_status.working`.

In `server/orchestrator/tool_loop.py`, replace `_declined`:

```python
def _declined(refused: str, subject: str) -> str:
    """What a "no" from a card tells the model (0.1.61): the decision's own text when there is
    one (the user's note, or "nobody answered — NOT a refusal"), never "declined" for a card
    that simply ran out."""
    from server.services import approvals, permissions
    decision = permissions.LAST_DECISION.get()
    if decision is not None and not decision.allowed and decision.model_text:
        return decision.model_text
    if approvals.LAST_OUTCOME.get() == "expired":
        return (f"Nobody answered the card for {subject} in 30 minutes. This is NOT a refusal. "
                "Don't retry it in this turn. Finish what you can and tell the user what is waiting.")
    return refused
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/.claude/worktrees/wonderful-chandrasekhar-022909/arslan-0161-core && .venv/bin/python -m pytest tests/server/test_window_permissions.py tests/server/test_run_command_confirm_flow.py tests/server/test_inbox_approvals.py tests/server/test_island_approvals.py tests/server/test_phone_turn_cards.py tests/server/test_tool_loop_confirm.py tests/server/test_sandbox_script_cards.py tests/server/test_ws_arslan.py tests/server/test_hands_card_in_turn.py -q
```
Expected: PASS. Some existing tests encode removed behaviour: the per-socket workspace or
schedule grant, or the exact-text "remember" set. Update each to the conversation-grant
behaviour, and name the old expectation and the new one in the commit body.

- [ ] **Step 5: Mutation check**

On a `cp` backup, make each change one at a time and confirm a test fails:
1. Remove `asking_with(_window_asker)` from `run_with_confirm_frames`. Every card turn should fail
   with a policy refusal.
2. Remove the `decline_pending` line.
3. Make `_declined` ignore `LAST_DECISION`.

- [ ] **Step 6: Commit**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/.claude/worktrees/wonderful-chandrasekhar-022909/arslan-0161-core && .venv/bin/ruff check server tests && git add server tests && git commit -m "chat and jobs ask through permissions.decide; a typed message answers a waiting card; expired cards are reported as no answer (0.1.61 §A4, §A9)"
```

---

### Task 5: The API — answers with scope and note, rules, refusals

**Files:**
- Modify: `server/api/approvals.py`
- Create: `server/api/permissions.py`, and register it where `server/main.py` includes the
  approvals router. Find that with `grep -n "approvals" server/main.py` and mirror the line.
- Test: create `tests/server/test_permissions_api.py`.

**Interfaces:**
- `POST /api/v1/approvals/{call_id}/answer` takes the body
  `{approve, source: "inbox"|"island", scope?: "once"|"task"|"conversation"|"always", note?: str}`.
- `GET /api/v1/permissions/rules` returns
  `[{id, kind, target, label, created_at, last_used_at, use_count}]`.
- `DELETE /api/v1/permissions/rules/{id}` returns `{"ok": true}`, or 404.
- `POST /api/v1/permissions/rules` takes `{kind, target, label}`. It returns 400 for a kind that
  is never remembered (Task 2's `_NEVER_ALWAYS`), otherwise the created rule.
- `GET /api/v1/approvals/refused?hours=24` returns
  `[{id, created_at, conversation_id, kind, target, detail}]`, policy refusals only.

- [ ] **Step 1: Write the failing tests**

```python
"""0.1.61 §A4/§A5: the Inbox answers with a scope and a note; standing rules are listed and
withdrawn; what a scheduled run could not ask for is listed, with "Always allow"."""
from __future__ import annotations

import pytest

from server.services import approvals, run_registry
from tests.server.conftest import build_ws_client


@pytest.fixture
def client(tmp_path, monkeypatch, portal):
    return build_ws_client(portal, tmp_path, monkeypatch, db_name="permissions_api.db")


@pytest.fixture(autouse=True)
def _clean():
    approvals._reset_for_tests()
    yield
    approvals._reset_for_tests()


def test_the_inbox_answers_with_a_scope_and_a_note(client, monkeypatch):
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    p = approvals.open_card("c", {"type": "propose_action", "call_id": "k1", "kind": "app",
                                  "target": "Notes", "detail": "", "options": ["task", "conversation"]})
    r = client.post("/api/v1/approvals/k1/answer", json={"approve": True, "scope": "conversation"})
    assert r.status_code == 200 and approvals.close_card(p)["scope"] == "conversation"
    q = approvals.open_card("c", {"type": "propose_action", "call_id": "k2", "kind": "app",
                                  "target": "Mail", "detail": "", "options": ["task"], "dedupe": "m"})
    client.post("/api/v1/approvals/k2/answer", json={"approve": False, "note": "not Mail"})
    assert approvals.close_card(q)["note"] == "not Mail"


def test_rules_are_listed_created_and_withdrawn(client):
    r = client.post("/api/v1/permissions/rules", json={"kind": "app", "target": "com.apple.Notes",
                                                       "label": "Notes"})
    assert r.status_code == 200
    rule_id = r.json()["id"]
    assert [x["target"] for x in client.get("/api/v1/permissions/rules").json()] == ["com.apple.Notes"]
    assert client.delete(f"/api/v1/permissions/rules/{rule_id}").json() == {"ok": True}
    assert client.get("/api/v1/permissions/rules").json() == []
    assert client.delete(f"/api/v1/permissions/rules/{rule_id}").status_code == 404


@pytest.mark.parametrize("kind", ["money", "capability", "other_agent", "destructive", "takeover"])
def test_kinds_that_are_never_remembered_cannot_become_rules(client, kind):
    assert client.post("/api/v1/permissions/rules",
                       json={"kind": kind, "target": "x", "label": "x"}).status_code == 400


async def test_policy_refusals_are_listed_for_the_inbox(client):
    from server.services import permissions
    await permissions.decide(permissions.Request(kind="schedule", target="*", title="Schedule digest?"),
                             permissions.Context(conversation_id="c"))
    rows = client.get("/api/v1/approvals/refused?hours=24").json()
    assert [(r["kind"], r["target"]) for r in rows] == [("schedule", "*")]
```

If the last test cannot share the client's database from an async test, write it as a sync test
that drives the decision through a scheduled-run style call inside `portal.call(...)`. That is
the same mechanism `build_ws_client` uses; check `tests/server/conftest.py`.

- [ ] **Step 2: Run the tests to verify they fail.**

Run: `.venv/bin/python -m pytest tests/server/test_permissions_api.py -q`.
Expected: FAIL with 404 / 422 responses (the routes and fields are missing).

- [ ] **Step 3: Implement**
  - In `server/api/approvals.py`, `Answer` gains
    `scope: Literal["once", "task", "conversation", "always"] | None = None` and
    `note: str = ""`. It calls
    `approvals.answer_by_id(call_id, body.approve, source=body.source, scope=body.scope, note=body.note)`.
  - Add `GET /approvals/refused` there, reading `permission_store.refused_since(db, datetime.utcnow() - timedelta(hours=hours))`
    with `hours` clamped to 1–168.
  - Create `server/api/permissions.py` with the three `/permissions/rules` routes. It uses the
    same `APIRouter(dependencies=[Depends(require_auth)])` and the `get_session` dependency as
    `server/api/settings.py`. `POST` validates `kind not in permissions._NEVER_ALWAYS` and that
    `target` is non-empty, ≤ 2000 characters.

- [ ] **Step 4: Run the tests to verify they pass, plus the approvals suites.**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/.claude/worktrees/wonderful-chandrasekhar-022909/arslan-0161-core && .venv/bin/python -m pytest tests/server/test_permissions_api.py tests/server/test_inbox_approvals.py tests/server/test_island_approvals.py -q
```

- [ ] **Step 5: Commit**

```bash
cd /Users/mirzatghayrat/Documents/aralem_dev/Arslan/.claude/worktrees/wonderful-chandrasekhar-022909/arslan-0161-core && .venv/bin/ruff check server tests && git add server tests && git commit -m "api: answers carry a scope and a note; rules listed, created, withdrawn; what a scheduled run could not ask for (0.1.61 §A4, §A5)"
```

---

### Task 6: Full suite, push, PR (controller)

- [ ] Run the full suite as CI does:
  `ARSLAN_SECRET_KEY=ci-secret .venv/bin/python -m pytest -q -p no:cacheprovider`. Then run
  `.venv/bin/ruff check server tests` and run `gitleaks dir` on every changed file.
- [ ] Push `claude/0161-permissions-core` and open the PR, "0.1.61 PR 2: the permission core".
  - The body covers what changes for the user (scopes on job cards, 30-minute cards, expired ≠
    declined, typed messages answer cards) and what does not change yet (what asks: PR 3; the
    card UI: PR 2b).
  - It includes a "尚无证据、未声称已验" section.
- [ ] `ccd_pr` `get_status` → `bind_pr`. Send ③Hands the PR number and the final interface
  (§A11 plus this plan's rulings 1–3).
