# CAPX: three capability follow-ups (skill framing, one name sanitizer, connection secrets)

⓪Plan, 2026-10-30. The user asked, relayed by ④参谋 (「转给 ⓪Plan」), for the long-term approach over minimal patches, with "no over-defence" (`docs/sessions.md` §12) and mainstream practice weighed in each card. ④参谋 drafted the scope. ⓪Plan re-checked the references at main `b3f31303`. Lane: ⑤CAP for all three. Each card is its own PR, written at effort=max with an independent effort=max review, and the user merges (security surface).

| Card | Tier | Order |
|---|---|---|
| SKF1 skill framing becomes an allowlist | should | first, small |
| UNI1 one name sanitizer; bodies flagged, not stripped | should | after SKF1, small to medium |
| SEC1 secrets in connection URLs and args move to the encrypted store | could (v0.1.65 candidate) | after SKF1 and UNI1 |

## SKF1: skill framing becomes an allowlist

**Today.** `read_skill` frames a skill as outside content only when `row.category in ("imported", AUTHORED_OUTSIDE)` (`server/registry/executors.py:852`). That is a denylist: any other category reads as Arslan's own. The gh- skills (old Discover, distilled from GitHub READMEs) got through exactly that way until #502 (migration 0080) marked them.

**Change.** Invert it. Only an explicit trusted set reads unframed; every other value is framed and marks the turn, including an unknown or empty category.
- **The trusted set** can't be a list of category values, because seed rows carry the catalog's free-form categories ("creative", "meta"). It is:
  - a key in `seed_catalog.SKILLS` with none of D7's user marks (not `seeder._USERS_SKILL`, `seeder.py:92`);
  - plus category `authored`.

  For skills, "built-in" and "seeded" are the same set.
- **One function** holds the set. The readers that decide a skill's framing or origin all call it:
  - `read_skill` (`executors.py:852`). Its `references/` gate at `:860` is already an allowlist (only `imported`).
  - The skill index (`server/orchestrator/arslan.py:1060`, a hot file), which lists outside skills by key only.
  - `capability_list._skill_origin` (`capability_list.py:211-221`). Its last line, `return "builtin"`, has the same denylist shape: an unknown category reads as built-in.
  - MCPOUT1's `list_capabilities` (`server/mcp_server/tools.py:67`), if that card lands with it.

(`list_my_capabilities` lists MCP servers only, not skills.)

**Effect.** No change on today's data. Only three writers create skill rows (`seeder.py:136`, `skill_forge.py:150`, `skill_import.py:328`), and #496 and #502 marked every row they wrote. A future source can't slip through.

**Four lines** (`docs/sessions.md` §6):
1. **References.** Claude Code and Codex trust skills the user installed and don't frame them. Arslan is stricter on purpose: CAP2a "keep the mark" and CAP2b "split by source", both the user's. A stated limit, not for this card: if user-installed, scan-passed skills cause friction (for example background runs that refuse after reading one), widen the trusted set in that one place, and only by the user's decision. This is the same trade-off as "MCP descriptions from approved servers stay unmarked" (user, 2026-10-29).
2. **Raw material.** `executors.py:852`, `:860`; `capability_list.py:211-221`; `arslan.py:1060`; the three writers; the category values the migrations write (0077, 0080); `seed_catalog.SKILLS`.
3. **Method.** Red test first: a row with an unknown category reads unframed today. A test pins the trusted set, and each reader is shown to use the one set. Mutants.
4. **External evidence.** A CI run id. The unknown-category test goes red when the allowlist is reverted to the denylist.

## UNI1: one name sanitizer at every entry point; bodies flagged, not stripped

**Today.** The checks are scattered:
- the MCP name rule `breaks_mcp_name_rule` / `_MCP_NAME` (`server/orchestrator/untrusted.py:99-103`, from #495 and #498);
- `outside_label` (`server/services/capability_flow.py:199`);
- `create_skill`'s `_visible` / `_INVISIBLE` (`server/services/skill_forge.py:59`, `:85-89`);
- the web's own isolation in the Capabilities list (#500);
- `skill_import`, which strips nothing (#500's review noted this).

**One finding the card must fix.** `skill_forge._visible` drops every Unicode category-C character from a skill's **body** except `\n` and `\t` (`skill_forge.py:167`). That includes ZWNJ U+200C, which is part of Persian's standard spelling; ZWJ U+200D, which emoji sequences and some Arabic-script text use; and LRM/RLM U+200E/U+200F, which RTL text uses. `_INVISIBLE` (`:59`) also drops VS16 U+FE0F, which breaks ❤️. So `create_skill` today can corrupt ordinary text in those cases.

**Change.**
- **Names and identifiers** (skill names and keys, MCP server labels, tool names) go through one function in `server/orchestrator/untrusted.py`, built on an allowlist of normal characters. Format and control characters are rejected or removed. `outside_label` becomes this function or calls it. `breaks_mcp_name_rule` stays a separate predicate, because it is MCP's ASCII protocol rule, even if it shares character classes. Two tests enumerate the entry points, so that a new entry point has to use the function. A backend test covers create_skill, skill_import, the MCP add and install paths and the capability list; a web test covers the web side.
- **Bodies** (skill text) are not stripped by default.
  - **Kept as they are:** ZWJ, ZWNJ, LRM, RLM, and the variation selectors.
  - **Removed:** Unicode Tag characters (U+E0000–E007F), the main smuggling vector, which have no use in ordinary text. The one exception is a tag sequence that forms an emoji subdivision flag (🏴 followed by tags and U+E007F), which is kept whole.
  - **Bidi override and isolate controls** (U+202A–202E, U+2066–2069) are kept in the stored text. The save card and the import card show them escaped, as visible markers, so the card still shows exactly what is stored (#472 F4's rule; the save card is the user's approval). This is ⓪Plan's call, and the user can choose removal instead.
  - **At import and on the save card**, invisible characters are counted: "this skill contains N invisible characters", as GitHub does. That notice is UI, so it needs a clickable mock first (the user's rule), in all six languages.

**Four lines:**
1. **References.** Pillar Security's "Rules File Backdoor" (March 2025): hidden Unicode in Cursor and Copilot rules files. GitHub answered with a hidden-Unicode warning. Cursor called it the user's responsibility. Pillar recommends stripping. Arslan flags, and strips only Tags.
2. **Raw material.** The sites above, at `file:line`.
3. **Method.** Tests first:
   - Persian text with ZWNJ, an emoji ZWJ sequence, ❤️ (VS16), and RTL text with LRM/RLM survive a create and an import byte for byte;
   - a subdivision flag survives, and a bidi override shows escaped on the card;
   - a Tag-character payload doesn't survive;
   - the count of invisible characters is shown;
   - the entry-point test fails when a new path skips the function.
   Then mutants.
4. **External evidence.** A CI run id; the ZWNJ test going red on today's `_visible`; the user's OK on the notice mock.

## SEC1: secrets in connection URLs and args move to the encrypted store; one display function

**Today.** A connection's `env` is already encrypted at rest and masked on read (`server/services/mcp_service.py:1`, `:29-30`, `:75`). OAuth tokens are encrypted (`server/mcp/oauth_flow.py:51`). Secrets typed into the **URL** or the **command args** are stored in plain text and shown raw: `mcp_service.py:74` returns args and `:75` the URL, as stored.

**Why "move into env" doesn't work.** For an HTTP connection, `env` is its header map (`server/mcp/session.py:319`, `:397`). A secret moved there would be sent as an extra header, and a query-string token only works if the server also accepts it as a header. A stdio flag value only works if the server also reads an env var. And nothing in `server/mcp/` or `mcp_service.py` substitutes `${VAR}` today.

**Change.**
1. When a connection is added, detect secret-looking parts of the URL and args: query keys like `token`, `key` or `secret`; long high-entropy values; `user:pass@` in a URL. Offer a one-click move that replaces the value with a placeholder in the stored URL or args (`${NAME}`, as in Claude Code). The value goes into a separate encrypted store, **not `env`**, and is filled in at connect or spawn time. That likely means a new column, so the card asks ②Main for a migration number.
2. One display function, used by the card, logs and export, which never shows a stored secret. Today both `args` and `url` are returned raw (`mcp_service.py:74`, `:75`). #500's search `reach` is searched, never shown, so it isn't a display path.
3. Migration path, decided in the card: whether existing connections are only flagged ("this connection has a secret in its URL") or are offered the move. Nothing is moved without the user's click.

**Weight against §12.** Only the user sees this page, so the gain is smaller than SKF1 and UNI1. Keep the card small, and don't build a general secret scanner.

**Four lines:**
1. **References.** Claude Code's `claude mcp add --env/--header`, and `${VAR}` shown by name in `mcp list/get`. VS Code MCP `inputs` with `password: true` go to secret storage. Claude Desktop keeps a plaintext JSON config.
2. **Raw material.** `mcp_service.py:29-30`, `:74-75`; `oauth_flow.py:51`; `session.py:319`, `:397`. A session can't count existing connections with a secret-looking URL, because the probe rule says never open `~/.arslan`. The user runs a small read-only counting script that the card provides (counts only, no values), or the count is dropped.
3. **Method.** Tests first: a URL with a token is offered the move; after the move the stored URL has no secret and the connection still starts; display, search, logs and export never show the secret. Mutants.
4. **External evidence.** A CI run id, and the user's real-Mac smoke: add a connection with a token in its URL, move it, restart, and the connection still works.
