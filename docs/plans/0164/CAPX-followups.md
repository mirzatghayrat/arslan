# CAPX: three capability follow-ups (skill framing, one name sanitizer, connection secrets)

⓪Plan, 2026-10-30. The user asked, relayed by ④参谋 (「转给 ⓪Plan」), for the long-term approach over minimal patches, with "no over-defence" (`docs/sessions.md` §12) and mainstream practice weighed in each card. ④参谋 drafted the scope. ⓪Plan re-checked the references at main `b3f31303`. Lane: ⑤CAP for all three. Each card is its own PR, written at effort=max with an independent effort=max review, and the user merges (security surface).

| Card | Tier | Order |
|---|---|---|
| SKF1 skill framing becomes an allowlist | should | first, small |
| UNI1 one name sanitizer; bodies flagged, not stripped | should | after SKF1, small to medium |
| SEC1 secrets in connection URLs and args move to the encrypted store | could (v0.1.65 candidate) | after SKF1 and UNI1 |

## SKF1: skill framing becomes an allowlist

**Today.** `read_skill` frames a skill as outside content only when `row.category in ("imported", AUTHORED_OUTSIDE)` (`server/registry/executors.py:852`). That is a denylist: any other category reads as Arslan's own. The gh- skills (old Discover, distilled from GitHub READMEs) got through exactly that way until #502 (migration 0080) marked them.

**Change.** Invert it. Only an explicit trusted set reads unframed: built-in, the seeded skills and `authored`. Every other value is framed and marks the turn, including an unknown or empty category. Put the trusted set in one place, which `read_skill`, the skill index (outside skills listed by key only) and `list_my_capabilities` all read.

**Effect.** No change on today's data, because #496 and #502 marked every row. A future source can't slip through.

**Four lines** (`docs/sessions.md` §6):
1. **References.** Claude Code and Codex trust skills the user installed and don't frame them. Arslan is stricter on purpose: CAP2a "keep the mark" and CAP2b "split by source", both the user's. A stated limit, not for this card: if user-installed, scan-passed skills cause friction (for example background runs that refuse after reading one), widen the trusted set in that one place, and only by the user's decision. This is the same trade-off as "MCP descriptions from approved servers stay unmarked" (user, 2026-10-29).
2. **Raw material.** `executors.py:852`; the category values the migrations write (0077, 0080); the seeder's keys.
3. **Method.** Red test first: a row with an unknown category reads unframed today. A test pins the trusted set, and each reader is shown to use the one set. Mutants.
4. **External evidence.** A CI run id. The unknown-category test goes red when the allowlist is reverted to the denylist.

## UNI1: one name sanitizer at every entry point; bodies flagged, not stripped

**Today.** The checks are scattered:
- the MCP name rule `breaks_mcp_name_rule` / `_MCP_NAME` (`server/orchestrator/untrusted.py:99-103`, from #495 and #498);
- `outside_label` (`server/services/capability_flow.py:199`);
- `create_skill`'s `_visible` / `_INVISIBLE` (`server/services/skill_forge.py:59`, `:85-89`);
- the web's own isolation in the Capabilities list (#500);
- `skill_import`, which strips nothing (#500's review noted this).

**One finding the card must fix.** `skill_forge._visible` drops every Unicode category-C character from a skill's **body** except `\n` and `\t` (`skill_forge.py:167`). That includes ZWJ U+200D and ZWNJ U+200C, which Arabic-script languages, Uyghur among them, need. So `create_skill` today can corrupt text in those languages.

**Change.**
- **Names and identifiers** (skill names and keys, MCP server labels, tool names) go through one function, in `server/orchestrator/untrusted.py`, built on an allowlist of normal characters. Format and control characters are rejected or removed. `outside_label` and the MCP rule either become this function or call it. A test enumerates the entry points (create_skill, skill_import, the MCP add and install paths, the capability list, and the web), so that a new entry point has to use it.
- **Bodies** (skill text) are not stripped by default. At import and at the save card, invisible characters are surfaced: "this skill contains N invisible characters", as GitHub does. The only automatic removal is Unicode Tag characters (U+E0000–E007F), the main smuggling vector, which have no use in ordinary text. The card decides whether emoji tag sequences, for example subdivision flags, need an exception. Today's `_INVISIBLE` set (variation selectors, Hangul fillers, U+2800 and others) is revisited under the same rule: the PR lists any character that should still be removed from bodies, and why.

**Four lines:**
1. **References.** Pillar Security's "Rules File Backdoor" (March 2025): hidden Unicode in Cursor and Copilot rules files. GitHub answered with a hidden-Unicode warning. Cursor called it the user's responsibility. Pillar recommends stripping. Arslan flags, and strips only Tags.
2. **Raw material.** The sites above, at `file:line`.
3. **Method.** Tests first:
   - Uyghur or Arabic text with ZWJ and ZWNJ, and RTL text, survives a create and an import byte for byte;
   - a Tag-character payload doesn't survive;
   - the count of invisible characters is shown;
   - the entry-point test fails when a new path skips the function.
   Then mutants.
4. **External evidence.** A CI run id, and the ZWJ test going red on today's `_visible`.

## SEC1: secrets in connection URLs and args move to the encrypted store; one display function

**Today.** A connection's `env` is already encrypted at rest and masked on read (`server/services/mcp_service.py:1`, `:29-30`, `:75`). OAuth tokens are encrypted (`server/mcp/oauth_flow.py:51`). Secrets typed into the **URL** or the **command args** are stored in plain text, and the card shows them raw (`mcp_service.py:75` returns `url` as stored). #500's search already uses an allowlist for what it shows.

**Change.**
1. When a connection is added, detect secret-looking parts of the URL and args (query keys like `token`, `key`, `secret`; long high-entropy values; `user:pass@` in a URL). Offer a one-click move into `env` or a header, which is encrypted.
2. One "outside display" function, used by the card, search, logs and export, reusing #500's allowlist logic.
3. Migration path, decided in the card: whether existing connections are only flagged ("this connection has a secret in its URL") or are offered the move. Nothing is moved without the user's click.

**Weight against §12.** Only the user sees this page, so the gain is smaller than SKF1 and UNI1. Keep the card small, and don't build a general secret scanner.

**Four lines:**
1. **References.** Claude Code's `claude mcp add --env/--header`, and `${VAR}` shown by name in `mcp list/get`. VS Code MCP `inputs` with `password: true` go to secret storage. Claude Desktop keeps a plaintext JSON config.
2. **Raw material.** `mcp_service.py:29-30`, `:75`; `oauth_flow.py:51`; #500's search allowlist. Before the card, the author counts read-only how many existing connections have a secret-looking URL or arg: counts only, no values.
3. **Method.** Tests first: a URL with a token is offered the move; after the move the stored URL has no secret and the connection still starts; display, search, logs and export never show the secret. Mutants.
4. **External evidence.** A CI run id, and the user's real-Mac smoke: add a connection with a token in its URL, move it, restart, and the connection still works.
