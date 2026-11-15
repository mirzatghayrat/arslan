# CAP11: capability cards on the phone (view-only now, phone approval later)

| | |
|---|---|
| Decided | The user decided (2026-11-15, relayed by ⓪Plan and ④参谋): step a in v0.1.64; step b deferred. Shapes confirmed by ①iOS the same day. |
| Version | Step a: v0.1.64 (must). Step b: the Mac-side opening after the rest of tier 1, not blocking the v0.1.64 tag; phone approval itself is iPhone 1.1 / v0.1.65 unless the user moves it. |
| Lane | ⑤CAP (Mac and Bridge); ①iOS builds the phone side in its own repo (one PR in build 34, no 1.0 delay). |
| PRs | Step a: CAP11a (server product fix, high review) and one Bridge frame PR (the user merges; it also carries SUB5f's read-only sub-session frames, after #929). Step b: 2 PRs, effort=max. |

## Step a

### CAP11a: product fix (this card's first PR)

- **A decline's reason reaches the model.** A "No" typed on a capability card carries its note; the window's capability
  asker now returns it, and `capability_flow.propose` adds "They said: …" to the declined result, bounded as every card's
  "No" note is (stripped, at most 500 characters), so the model reads why in the same turn.
- **A plain decline from any surface.** A no to a capability card (the `propose_capability` type, or any card with
  `perm_kind: "capability"`) is accepted from the window, the Inbox, the island and the phone, and keeps its note. A yes
  from anywhere but the asking window is still swallowed (phone) or "open in Arslan" (Inbox, island). Pinned by tests;
  `window_only` and the hard rule are not changed.

### Bridge frame PR (the user merges)

- Capability cards reach the phone **view-only**, with one "don't install" decline. Today the Bridge drops every card with
  `perm_kind: "capability"` (`FrameMapper.phoneMessages`), and the Mac skips the phone for window-only cards while a phone
  turn runs (`mac_only` in the window socket).
- `approval.request` gains a Mac-set **`phone_can_approve`** (bool). In v0.1.64 it is false for capability cards, pinned by
  vectors. The server refuses a phone yes whenever the card isn't phone-approvable, and never trusts this field from the phone.
- Three **optional** fields, additive within v1 (spec §5.5); the Mac fills them now, iPhone 1.0 ignores them:
  - `source`: string, at most 200 characters;
  - `abilities`: string[], at most 8 items of at most 120 characters;
  - `checks`: `[{name, result, detail?}]`, `result` ∈ pass | warn | fail | not_run, `detail` at most 160 characters.
- The same PR carries SUB5f's read-only sub-session frames (shape agreed with ②Main; backend in #929).

### The six frozen rules

1. `checks[].result` is an **open** set in the spec: receivers keep a value they don't know. `risk` stays **closed**:
   capability cards use the existing "install" value, no new risk value.
2. The limits (`source` ≤200, `abilities` ≤8×120, `detail` ≤160) are Mac guarantees: the Mac truncates; the phone only
   clamps what it displays.
3. Absent rule: `phone_can_approve` absent **and** `perm_kind == "capability"` → not approvable; any other absent case →
   approvable (as today).
4. The Mac folds `status.high_risk_mac_only` into `phone_can_approve`; the phone ANDs both.
5. The Mac accepts a phone **deny** on capability cards; the swallow in `approvals.answer` keeps refusing only a yes.
6. Empty arrays ≡ absent.

### The four vectors (`spec/mobile-bridge/vectors/messages.json`)

- (a) a capability card with all three fields, `phone_can_approve: false`;
- (b) the same card with `phone_can_approve: true`;
- (c) an old Mac's card: no field, `perm_kind: "capability"`;
- (d) a phone deny answer on a capability card.

## Step b (deferred)

The Mac-side opening that would let a phone yes approve a capability card: relax `window_only` where it is read
(`server/services/approvals.py`: the definition, the swallow in `answer`, `island_may_answer`, `answer_by_id`) and the
`capability` hard rule (`server/services/hard_rules.py`, the row held by `approvals:window_only`). Two PRs, effort=max,
after the rest of tier 1; it does not block the v0.1.64 tag. Phone approval itself ships with iPhone 1.1 / v0.1.65 unless
the user moves it. Nothing in step a reads or sets a "phone may approve" switch beyond the frame field.

## References

- 0.1.57 / 0.1.61 §A4: installing code wants the whole card, so only the asking window approves it; saying no is allowed
  from anywhere (`window_only`'s docstring).
- Spec §5.5 (additive optional fields within v1) and the existing `approval.request` / `approval.answer` vectors.

## Raw material

- `server/services/approvals.py:66-73` `window_only`; `:219` the swallow (`ANSWERS[kind] and window_only(...)`: a yes
  only); `:236` the "No" note, stripped and at most 500 characters; `:309` `island_may_answer`; `:356` `answer_by_id`.
- `server/services/capability_flow.py`, the declined return after `ask(card)`: it read no note before CAP11a.
- `server/ws/arslan.py`, `confirm_capability`: returned approved/keys/folders/kept, dropping the decision's note before CAP11a.
- `server/services/permissions.py`, `_declined_text`: the "They said: …" pattern CAP11a reuses.
- `server/services/hard_rules.py`, the `capability` row (held by `approvals:window_only`): untouched in step a.
- `desktop/bridge/Sources/BridgeCore/FrameMapper.swift`, `phoneMessages`: the `perm_kind == "capability"` drop.

## Method

- Red tests first, seen red: the declined result carries the reason, is bounded, and reads as before without one; through
  the real window socket the model's tool answer holds the typed reason; a phone no declines the install card with its
  reason; a phone yes is still swallowed.
- Mutation: revert each fix (and the swallow rule both ways) and see the matching test go red; restore.
- Frame PR: vectors (a)–(d) in both the Python reference and the Swift tests; a red test that a phone yes on a card that
  isn't phone-approvable is refused, whatever `phone_can_approve` the phone sends.

## External evidence

- CAP11a: its PR's CI run id and conclusion, and the targeted test counts in its body.
- Frame PR: CI run ids (backend and Bridge), and a build-34 phone showing a capability card view-only with the decline.
