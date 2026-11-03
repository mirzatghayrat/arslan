# ROUTE1: remove task routing and the provider capability table

| | |
|---|---|
| Grade | **Must** for v0.1.64 (user, 2026-11-03, relayed by ④参谋): 「我同意你的方案要删就直接删 别留遗留/垃圾代码」. |
| Lane | ②Main, after #691 and the model-switch PR B, which both touch the same decision. One cleanup PR. |
| Review | Product code, so a high review from another session, then a self-merge under #644. |
| Mock | Mostly removal, so the user's mock rule is met by a before/after screenshot of Settings in the PR. No new UI. |

## Why

- **It scores providers, not models.** `arslan/llm/routing.py` `select()` scores providers from a hard-coded table (`STRATEGY_WEIGHTS`, `QUALITY_WEIGHTS`), so Haiku and Opus get the same row.
- **It overrides "Main model".** Under Balanced, a chat with no choice of its own runs `build_adapter(role="execute")` (`server/services/llm_factory.py:62`, called from `tool_loop.py:73`), and that call is scored. Settings' "MAIN MODEL: New conversations use it" holds today only because DeepSeek happens to win the score.
- **It's part of the model-switch bug.** In that report (#691), the chip's idea of "default" (the primary) and the server's (the score) disagreed.
- **No mainstream agent does strategy routing.** Claude Code, Codex and OpenClaw use the model the user picked, with explicit fallbacks.

## Raw material (main at the time of writing)

- **Server:**
  - `arslan/llm/routing.py`: `WORKER_ROLES` (documentation only, `:10-14`), `STRATEGY_WEIGHTS` (`:16`), `QUALITY_WEIGHTS` (`:21`), `select` (`:75`), `suggest_primary` (`:94`) and their helpers;
  - `server/services/llm_factory.py:62` (`llm_strategy`);
  - `server/services/provider_config_service.py:228`;
  - `server/api/settings.py:479` (the suggest-primary endpoint);
  - `server/schemas.py:38`, `:119`;
  - `server/services/settings_service.py:23`;
  - the `_0006_provider_configs` migration seeds `llm_strategy`.
- **Web:**
  - `web/src/components/settings/RoutingStrategyCard.tsx`;
  - `ProviderConfigList.tsx` (the 「Suggest primary」 button and the provider capability table);
  - `api/adapters.ts`, `api/client.types.ts`, `hooks/useDebouncedSettingsSave.ts`;
  - the locale keys in all six languages;
  - tests such as `capability-table-disambiguation.test.tsx` and `adapters.test.ts`.

## The change

1. **Remove with their tests, i18n keys (all six languages) and docs mentions:**
   - the routing strategies (single, cost, balanced, performance) and the `llm_strategy` setting;
   - `STRATEGY_WEIGHTS`, `QUALITY_WEIGHTS`, `select`, `suggest_primary`, `WORKER_ROLES`;
   - the 「Suggest primary」 button and the provider capability table UI;
   - any catalog capability scores that only these use.
2. **Migration:** drop the stored `llm_strategy`.
3. **`build_adapter(role)`:** returns the conversation's choice, else the primary. Every role behaves as "single" does today. #691's `effective_choice` then reduces to the same rule.
4. **Model roles:**
   - **Conversation compaction and Final answer:** drop both slots. They follow the conversation's model.
   - **Images:** applies only when the conversation's model can't read images (OpenClaw's imageModel rule). This matches the model-switch PR B: an explicit chat model always wins, and a refusal offers the vision model.
   - **Remembering facts:** stays for now, and defaults to the main model.
   - **No slot is pinned to a config by default.**
5. **Existing pins** (the user's are all config 1, DeepSeek). **Decision (⓪Plan):** the migration **clears** them, and the next Settings visit shows a one-time note: "Model roles now follow each conversation's model; your earlier role choices were cleared." The clear is from the database, never from the user's files. Why clear rather than keep them as choices: the pins were made under the old routing, and every one points at the provider whose outage this bug turned into a dead chat.

## Method

- **Inventory from four angles,** and list every deleted symbol in the PR body:
  - components;
  - an i18n-key reverse lookup;
  - backend settings keys;
  - tests.
- **Red tests first:**
  - with `llm_strategy` gone, a chat with no choice runs on the primary for every role;
  - an image turn on a model that can read images doesn't use the image slot;
  - the migration clears the pins and drops the setting, and re-running it is a no-op.
- **Mutants** on `build_adapter`'s fallback and on the image rule.
- **Test-deletion checks** (repo rules): compare the test-name sets (HEAD minus the expected deletions), plus the five blind spots (autouse fixtures, path strings, dotted imports, mixed tests, indistinguishable new tests).

## External evidence

- CI ids.
- The before/after Settings screenshots in the PR.
- The list of deleted symbols.
- A real-Mac check: switch the main model and confirm that a new chat, a summary and an image turn all follow it.

## v0.1.65 (proposed to the user, not decided; not carded)

- Two tiers, main and fast (e.g. Opus plus Haiku).
- Arslan picks the tier per dispatched job and shows it in the run log.
- A fallback chain.
- Tier choices calibrated from SMART-5.
