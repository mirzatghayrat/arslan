# MODEL1: Add model asks for the key first, then offers the live model list

| | |
|---|---|
| Grade | **Must** for v0.1.64 (user, 2026-11-03, relayed by ④参谋: 「第1条也在0.1.64做了呗，3，4可以放到0.1.65」). |
| Lane | ②Main, after ROUTE1. ROUTE1 already carries item 2: the seed's model ids come from `prices.py`. |
| Review | It handles an API key before anything is stored, so it's security surface: an effort=max review from another session, then a self-merge under #644. |
| Mock | A UI reorder, so a small before/after mock goes to the user for an OK **before any code**. |

## Why

- The Add model form suggests from the static seed (`arslan/llm/catalog.py`), which is stale: `claude-opus-4-8`, `claude-haiku-4-5`, `claude-sonnet-5`.
- The live list (`server/services/model_catalog.py`, the provider's models endpoint) is used only after a config is saved, never while adding.
- So a new user is offered last year's models.

## The change

1. **Order:** provider, then API key, then model.
2. **Fetch the live list with the entered key, transiently.**
   - Nothing is stored before Add.
   - The key is never logged, and the same redaction rules apply.
   - The request goes only to that provider's own models endpoint.
3. **If the fetch fails,** fall back to the static seed (from `prices.py`, via ROUTE1) and mark it as such: "Couldn't reach <provider>; showing Arslan's built-in list."
4. **Keep model_catalog's settings-only import rule:** never read from the chat path.

## Method

- **Red tests first:**
  - a typed key fetches once and shows the live list;
  - the key appears in no log line, error or stored row before Add;
  - a failed fetch shows the marked seed;
  - Cancel stores nothing.
- **Mutants** on the redaction and on "nothing stored before Add".

## v0.1.65 (decided, not this card)

- A quiet "newer version, switch?" hint for a saved config, with a one-click switch and never an automatic switch.
- Lists sorted newest first.
