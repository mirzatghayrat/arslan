# BRG1: the Bridge's Mailbox state is touched from several tasks at once

| | |
|---|---|
| Grade | Should (found by the effort=max review of #652, 2026-11-01; ⓪Plan asked for this card). Bridge internals, no frame change: self-merges after an effort=max review from another session. |
| Lane | ②Main. |
| Size | Small to medium: one Bridge file's state, plus StatusReporter's `unread`; tests. |

## Why

The Bridge runs four loops at the same time (`desktop/bridge/Sources/ArslanBridge/main.swift:121-155`): the store poll
(`runtime.poll()` → `Mailbox.receive`), the held progress lines (`links.flush()` → `Mailbox.send`), the status snapshot
(`status.tick()` → `Mailbox.send`), and the daily sweep. A phone's hello also posts a snapshot from the poll's task
(`ConversationLinks.swift:541`). `Mailbox` is a plain class, so these run its methods concurrently. Under TSan
(#652 review) the production shape flags:

- `Mailbox.nextSeq` (`Mailbox.swift:214-215`): two sends can read the same value. **A duplicated `seq` is dropped by
  the phone as a replay (protocol §4.8)**, so a chat event, a job update or a snapshot can silently never arrive.
- `sentAwaitingAck` (`:232`, also `:180`, `:202`, `:278`, `:306`, `:325`): a dictionary mutated from a send and a
  receive at once can corrupt or crash, which drops the phone link until the Supervisor restarts the Bridge.
- `StatusReporter.unread` (`StatusReporter.swift:21`, written in `post`): tick and a hello can post at once.

`MacState` had the same shape and was fixed in #652 with a lock (its review: 3 crashes in 8 two-task runs before).

## Reference

- Swift's own answer for shared mutable state reached from several tasks is an **actor** (The Swift Programming
  Language, "Concurrency › Actors"); a lock held across an `await` is not allowed, and `Mailbox.send` awaits
  `store.save` between taking a `seq` and recording the send.
- The protocol's replay window (§4.8) makes `seq` the one value that must never repeat per sender.

## Raw material (on main at `0095d523`)

- `Mailbox.swift:108-125` (the state), `:211-236` (`send`: `seq` taken, `remember()`, `store.save`, then
  `sentAwaitingAck`), `:244-330` (`receive`, `process`, `deleteAcknowledged`, `sweep`).
- `StatusReporter.swift:21`, `:41-44` (`post` replaces a phone's unread snapshot).
- `main.swift:121-155` (the four loops).

## Method

- **Red first:** a test that runs `send` from two tasks against a `MemoryStore` many times and asserts every
  record's `seq` is unique; a TSan run of the Bridge suite (`swift test --sanitize=thread`) with the races above as
  the failing evidence.
- **Fix, smallest that holds:** take `seq` and update the in-memory sets under one short `NSLock` that is never
  held across an `await` (allocate `seq` and persist the counter, unlock, seal and save, lock again to record the
  send). If that leaves an ordering gap a test can show, make `Mailbox` an actor instead and update its callers.
  `StatusReporter.unread` gets the same lock.
- **Mutation:** remove each lock in turn; the unique-`seq` test (or TSan with `halt_on_error=1`) must fail.

## External evidence

- `swift test --sanitize=thread` on the whole Bridge suite: no data-race warning.
- CI ids of the PR, and the commit that turns the unique-`seq` test red.

## Rollback

Reverting restores the races; no data format changes (the persisted `MailboxMemory` keeps its fields).
