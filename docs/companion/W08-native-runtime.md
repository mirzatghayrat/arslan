# W08 — one budget-governed native runtime

## Implemented

- Host, expert, recipe and scheduled entry points share the native model/tool loop and the enclosing durable task budget. Plain streaming remains available without tools, with the same cancellation/time limits.
- The production default is no longer eight tool rounds. Total model/tool/token/time admission and a structural no-progress policy bound execution. Provider opaque content and matching responses remain paired during history compaction.
- Known transient model transport failures get at most one delayed retry. Budget and durable-task control errors propagate through answer salvage. Tool writes are not automatically retried by this policy.
- Expert and immutable recipe drivers are saved for explicit resumption. Resume reuses the original task goal, spent budget and privacy ceiling. Headless saved text cannot confer fresh remember authority.
- Recipe approval pauses and scheduled no-progress results are not recorded as successful task completion. Budget exhaustion is a resumable review state, not an ordinary execution failure.
- Chinese/English findings labels remain readable but never trigger recursive dispatch. The old prompt/text-JSON execution loop and unused protocol exports were removed after migrating their useful tests to the native path. The spawn wrapper remains for compatibility.
- Migrated tests exposed missing guards for unverified search/chart/deck claims. These now run before final display in the native loop. Bounded correction never accepts a repeated unsupported claim merely to finish. Arbitrary non-protocol JSON remains valid user output.

## Verification so far

- 95 task/runtime/recipe/scheduler focused tests passed before legacy-loop removal.
- 87 native/dispatch/task API/repository/compatibility tests passed, plus 25 fetch/cancellation tests.
- 55 migrated native safety and active entry tests passed; a subsequent 46-test runtime/entry/fetch/conformance group passed after the goal-preservation fix.
- TypeScript type checking passed. Full immutable-snapshot Python and frontend regression results are recorded after their completion.
- Frontend full regression: 1,715 tests across 220 files passed.
- First immutable Python run: 4,230 passed, 14 skipped; 45 failures and 8 setup errors came from omitting the synthetic encryption key in the detached checkout. One obsolete auto-continuation expectation also failed and was migrated to explicit user continuation. The corrected environment and expectation are rerun, not counted as a green full suite.
- All fixtures are synthetic and isolated from real credentials, accounts and installed app data. These tests do not establish live paid-model quality or external-service availability.

## Boundaries

The no-progress fingerprint is a conservative evidence heuristic, not an acceptance validator. Artifact validation and ephemeral-worker ownership arrive in W10/W09. Runtime limits remain hard even if history cannot be compacted without damaging a provider's opaque block. Explicit resume cannot replenish spent budget or authorize a completed/uncertain write to replay.
