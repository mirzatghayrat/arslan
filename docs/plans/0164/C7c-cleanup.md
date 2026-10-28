# C7c plan: expert-era tables, memory v1 tables, `router_decisions`, expert REST

②Main, 2026-10-29. Read from main `3759f57b` (inventory by a read-only agent, spot-checked by ②Main). v0.1.64 plan §3.3, §6; `R63-verdict.md` "Deletion deadlines" row 2; `docs/plans/0162/README.md` §8 (C7 step 3).

## What the inventory changed

1. **Removing a model breaks fresh installs.** Boot runs `create_all` from the models, then every migration 0006–0070 (`storage_boot.py:13-19`, `runner.py:204-218`). Several of them still touch tables C7c removes:
   - 0025 alters `user_facts`;
   - 0032 is another;
   - 0047 goes through `memory_migration.py`, which reads `spawns`, `feedback`, `user_facts` and `learnings`;
   - `activate_sync` renames the v1 tables and puts triggers on `spawns`;
   - 0046, 0048 and 0052 import models.

   Every code PR that removes a model must also guard these steps (skip when the table is absent) or inline what they import. A fresh-install test covers it: create_all, then the whole chain.
2. **A model left in place recreates its table at the next boot.** So the model goes in the code PR, and the table drop comes in a later PR, as §6 already says.
3. **Foreign keys are on** (`server/db/session.py:22,41`). Dropping `spawns` either fails on rows that still point at it (`arslan_messages.spawn_id`, `chat_messages`, `feedback`, `conversation_spawns`) or cascades into user data. Most importantly, `knowledge_chunks.spawn_id` holds **private knowledge per expert**. Children are re-homed or cleared, explicitly, before any drop.
4. **`memory_proposals` stays.** Memory v2 writes its proposals there (`kind="memory_v2"`). Only the v1 rows and the `/brain/proposals*` endpoints are expert-era.
5. **Two cards disagree with "delete in v0.1.64":**
   - the Brain page still reads the `user_facts` / `learnings` views and `memory_legacy_map`, and its deletion is v0.1.65 (`C2a-memory-v1.md:141`);
   - INB2 keeps the v1 suggestions from `/brain/proposals` in 待整理 until v0.1.65 (`INB-inbox-progress.md:176-186`), while `brain.py:616` says v0.1.64.

## Proposed PRs (each small, in this order)

| PR | What | Migration |
|---|---|---|
| **C7c-1** | `router_decisions`: model, its three tests, the stale smoke script. Nothing writes or reads it. | — |
| **C7c-2** | `router_decisions` drop. | next free number |
| **C7c-3** | Expert code, part 1 (no user-visible change): the REST endpoints with no web caller (`GET/DELETE /spawns/{id}`, `PUT …/config`, `…/preferences`; knowledge `GET`/`DELETE`; collections bind/unbind). Also: the `GET /spawns/{id}/knowledge` web test; dead `spawnIntro`; `_active_toolset_keys` and its two test assertions; `HERMETIC_FETCH_BUDGET` / `replay_safety`; `task_service` still accepting `{"kind":"expert"}` (its leftover tasks get marked ended in C7c-5's migration). Every remaining expert-era file gets a `DELETE-BY: v0.1.64` (R63-verdict.md:86). | — |
| **C7c-4** | Expert code, part 2 (user-visible): replace the two live callers first: the repo card's `POST /spawns/{id}/knowledge` and the release check's `GET /spawns` login probe. Then remove: the equip popover (`PUT /spawns/{id}/equipment`, `GET /spawns`); the LegacyExperts page and `/experts/{id}/to-skill`; the MCP tool `list_spawns`; `run_eval_service`'s roster and persona; the `spawn_summary` branches. Removes the models, with the fresh-install guards from point 1. | — |
| **C7c-5** | Data migration, then the drops. Converts every leftover expert into a skill (bulk, what `to-skill` does one at a time; see Q1). Re-homes private knowledge (see Q2). Turns `spawn_summary` rows into plain `arslan` replies and NULLs `spawn_id`. Marks leftover expert tasks ended. Moves the quarantined `scope_kind=expert` memory entries into 待整理 (below). Clears children in foreign-key order, then drops the expert tables plus the orphans (`recipe_*`, `evolution_*`, `synthetic_tasks`). | next free number |
| **C7c-6** | Memory v1, to the extent this version may (see Q3): `/facts` CRUD, `/facts/dedup`, `/facts/classify`, `is_active`, the legacy branches in delete/restore. Drops `legacy_user_facts` / `legacy_learnings` and their guard triggers. The views, `memory_legacy_map`, `/brain/proposals*` and `/brain/undo-supersede` stay if Q3 says v0.1.65, with `DELETE-BY: v0.1.65`. | next free number |

Code PRs merge before their drop PRs. C7c-1/2 can go first and alone.

## The 30 quarantined `scope_kind=expert` entries (the user's 10-28 ask: decide and say which)

- **Decision: moved, not deleted.** Default agreed with ⓪Plan on 2026-10-29; the user can overrule.
- **What C7c-5's migration does to each entry:**
  - sets `scope_kind='global'`, `scope_id=NULL` (the CHECK needs both) and `status='proposed'`;
  - bumps the version and adds a revision;
  - adds a `MemoryProposal(kind='memory_v2', target_entry_id, target_version, candidate=None, status='pending')`. `candidate` must be None: accepting a candidate in a different scope would fail (`resolve_proposal` → `revise` without `confirm_scope_change`).
- **Where they show up:** in 待整理 (INB2), one by one, never auto-accepted.
- **Restricted rows** (secret, `content=NULL`) can only be deleted. The PR reports how many there were, without content.
- **New expert-scope writes** (`memory_tools_v2.py:59`, the editor's scope picker) are removed in C7c-4. `ck_memory_scope` keeps allowing `expert` until the rows are moved, then C7c-5 rebuilds the CHECK without it.

## Answers (user, 2026-10-29; relayed by ④参谋)

④参谋 looked at the user's database read-only and counted 6 leftover experts in `spawns` and 1 `knowledge_chunks` row with a `spawn_id`. The counts are given here, not the rows.

- **Q1:** in the migration, every leftover expert becomes a skill automatically, with nothing for the user to click. The user deletes any they don't want on the skills page. CAP2a (#472) removes the candidate table, so `convert` writes `SkillPack` directly.
- **Q2:** expert-private knowledge moves into the general knowledge base: `spawn_id=NULL`, and the source expert is kept as a label. Nothing is ever cascade-deleted.
- **Q3:** the v1 views, `memory_legacy_map`, `/brain/proposals*` and `/brain/undo-supersede` go in v0.1.65, with the Brain page. Write `DELETE-BY: v0.1.65` on each of them, including `brain.py:616`, which says v0.1.64 today.
- **Q4:** in the user's words, 「这一版直接删，没必要拖着」. `list_spawns` is removed in v0.1.64, with no empty-list stub.
- **Q5 (⓪Plan):** agreed: the `task_workers` drop stays in SUB6, one drop per PR.

## Questions for ⓪Plan (the user, where marked)

- **Q1 (user):** convert every leftover expert into a skill automatically in the migration (nothing to click), or keep the LegacyExperts page one more version?
  - My default: convert automatically, as the C7 card's "一次迁移把旧专家数据转好" reads.
  - That needs CAP2a's answer: `convert` writes `SkillPack` directly if CAP2a removes the candidate table first (`CAP-capabilities.md:86,171`).
- **Q2 (user):** private knowledge kept per expert (`knowledge_chunks.spawn_id`):
  - move it into the general knowledge base (`spawn_id=NULL`, the source kept as a label);
  - or move it into one collection per converted expert;
  - or something else.

  Never cascade-deleted.
- **Q3:** the v1 views, `memory_legacy_map`, `/brain/proposals*` and `/brain/undo-supersede`: v0.1.64 (C7c-6, which means INB2's 待整理 drops the v1 suggestions) or v0.1.65 with the Brain page (C2a's date)? I'd go with v0.1.65 for those four and write the DELETE-BY dates, since two cards already plan around them.
- **Q4 (user):** the MCP tool `list_spawns` is part of the tool set outside clients see. Remove it in v0.1.64 (it lists experts that no longer exist), or keep it returning an empty list for one version?
- **Q5:** SUB proposes folding the `task_workers` drop into C7c's migration (`SUB-sub-sessions.md:14`). I'd keep it in SUB6: one drop per PR (§6).
