# MCPF1: a switched-off MCP server left `failed` with a session cached (the M-2 fuzz, once on CI)

| | |
|---|---|
| Grade | Should. Found on #662's CI (run 41332678508), a PR that touches no Python. |
| Lane | Whoever owns the MCP supervisor next (`server/mcp/supervisor.py`); ②Main wrote the card and the diagnostics. |
| Status | Not reproduced locally. The fuzz now prints each failing server's timeline, so the next CI failure says which path it took. |

## What failed

`tests/server/test_mcp_supervisor.py::test_user_starts_bursting_over_background_starts_leave_the_row_and_the_process_agreeing[1]`
(the M-2 fuzz: 20 overlapping verbs on six servers, then checks at quiescence):

```
AssertionError: (1, [('ready vs session', 5, 'failed', False)], {'now': 0, 'max': 4})
```

Server 5 ended **switched off** (`host_allowed` False) with state **`failed`**, yet **a session cached**. At
quiescence a switched-off server should be `off` with no session; `ready` exactly when a session is cached.

## Reproduction tried (none failed)

- 300 seeds, `-n 8`, no load; 600 seeds, `-n 16` with 12 CPU hogs; seed 1 alone 300 times, `-n 16`, 12 hogs.
- CI differs: Linux, two cores, the whole suite at `-n auto`.

## Where to look (hypothesis, unconfirmed)

- A `restart` plan (a user's Connect) runs even on a switched-off server (`_attempt`: `switched_off = not
  row.host_allowed and plan != "restart"`), and its session stays cached until a background plan drops it.
- `_attempt` returns `failed` without dropping when the session it listed on was dropped meanwhile
  (`manager.generation(sid) != dropped_at`), and `_settle` writes `failed`. If another open cached a new session
  in between, the row says `failed` over a live session, and an `off` written earlier is overwritten.
- `set_enabled(False)` drops and writes `off` under its generation; a plan that started before it and was not
  cancelled (its cancel swallowed) could still settle after it.

## Method

- The fuzz now records, per server, every op, attempt (plan, generation, result), open, opened and close, and the
  assert prints the failing servers' last 40 events. Read that timeline from the next CI failure.
- Then a red test for that exact interleaving (a deterministic one, with events instead of sleeps), the fix in
  the supervisor, and the fuzz at `M2_SEEDS=300`.

## External evidence

- CI run 41332678508 (#662, backend), the failure above.
