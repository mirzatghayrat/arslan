# S5a: permission modes, per conversation

| | |
|---|---|
| Decided | The user decided (2026-11-14, relayed by ⓪Plan): ASK1's "when to ask" setting merges into the modes; the third tier is named "Ask only when risky"; full access shows no outside-sandbox card; the hard rules hold in every mode; the phone and the Island can't switch modes; sub-sessions inherit and never widen; migration 0098. |
| Version | v0.1.64 (must) |
| Lane | ⑤CAP (README's lane table still names ②Main; ⓪Plan fixes it) |
| Order | After SBX, HR's e rule (HR-1, 1b, 1c, 2a, 2b), S3 undo, ASK1-a, LOOP1 b and a1: all on main. Not after CLS (README §4, corrected chain). |
| PRs | S5a-1 server (this card's code); S5a-2 web, only after the user approves a clickable demo. Each ≤ about 800 product lines. |
| Review | effort=max for S5a-1 (permissions, command policy, a settings migration: `docs/sessions.md` §5). |

## The four modes

Each mode's line in the switcher says what it does on its own and when it asks.

| Mode | Does on its own | Asks |
|---|---|---|
| **Plan** | Reads only: read-only tools and the plan. Writes and commands are refused with a message. | Nothing to ask: leaving is the user's "Start", which restores the mode before Plan (never full access unless that was it). |
| **Ask every step** | Nothing that changes things. | Every command, every write card, as `ask_all` does today. |
| **Ask only when risky** | Today's ask-risky (ASK1-a): sandboxed commands that aren't dangerous; plus edits in the work folder (the write card is answered by the mode). | Leaving the sandbox, a layer ② rule, the network after outside content, and every hard rule. |
| **Full access** | Everything above, plus leaving the sandbox (no outside-sandbox card) and every card `hard_rules.never_auto` lets a mode answer. | The hard rules; the never-auto kinds (send, site, shortcut, money, run_later, git_config, git_include, git_refused, app_data, and the other once-only kinds); a command with any layer ② rule or a run-later write; the network after outside content keeps S2a-1's card until NET. |

- **Migration (0098):** a stored `shell_confirm_policy = ask_all` becomes `default_permission_mode = ask`; everything else (unset, `ask_risky`, any other spelling) becomes `ask_risky`. The old key is deleted with its readers, so it isn't kept in a second place.
- **Per conversation:** `conversation_contexts.permission_mode` (NULL = the default) and `previous_mode` (what Plan's "Start" restores). Conversations have no table of their own; `conversation_contexts` is the per-conversation row.
- **Automatic fallback:** "Ask only when risky" runs as "Ask every step", and the API returns why, when (1) the sandbox is off or can't start, (2) the run's checkpoint couldn't be saved (over the file or size cap, low disk, another volume), or (3) the work folder is the home folder or holds it.
- **Where it widens:** only in `permissions.decide`, after `_check` and money, before `_standing`, and only where a card surface is bound. `_ask` is untouched (S5b's). The command gate reads the same mode where it read the policy.
- **Unattended runs** (nobody to ask) are unchanged: no mode answers for them (`refuse_unattended`).
- **Sub-sessions** take the narrower of their parent's mode and their own; with none of their own, the parent's. They never widen.
- **Phone and Island:** no Bridge call or frame and no Island request sets a mode; only the desktop window's API does.
- **Ledger:** each `approval_events` row records the mode in effect (`plan` / `ask` / `ask_risky` / `full_access`).
- **S5b adds on top:** the "auto" mode and the classifier, and it alone edits `_ask`.

## References

- Claude Code's permission modes (default, acceptEdits, plan, bypassPermissions): [permission modes](https://code.claude.com/docs/en/iam#permission-modes). "Ask only when risky" is close to acceptEdits plus its sandbox auto-allow ([sandboxing](https://code.claude.com/docs/en/sandboxing)).
- Codex's approval modes (read-only, auto, full access): [security](https://developers.openai.com/codex/security).
- Listed for the user to decide, not built: a per-project default; a timer that drops full access after a while.

## Raw material

- `server/services/permissions.py` `decide` (:253), `_mode` (:649), `_standing` (:450), `_ask` (:502).
- `server/services/settings_service.py:433` (`shell_confirm_policy`), its readers: `command_gate.py:22`, `command_confirm.py:153`, `self_status.py:70`, `permissions.py:655`, `api/settings.py:259`, `schemas.py:49,125`, `phone_details.py:39`.
- `server/services/hard_rules.py` `never_auto` and `NEVER_AUTO_KINDS`: the one list of what no mode answers.
- `command_gate._work_folder_holds_home`, `_sandbox_enabled`; `checkpoints._save_root`'s `skipped`.
- `server/db/companion_models.py` `ConversationContext` (`kind`, `parent_id`: SUB's link).

## Method

- **Red tests first:** each mode × each kind (table-driven); hard rules and never-auto kinds still ask in full access; no outside card in full access; the network card still shown; Plan refuses writes and commands, and "Start" restores the previous mode; a sub-session can't widen; unattended runs unchanged; one test per fallback; the migration (ask_all → ask, else → ask_risky, old key gone); the phone and the Island can't switch.
- **Mutants:** money skipped in full access; a never-auto kind skipped in full access; a sub-session widens; "Start" goes to full access; a fallback case removed. Each turns a test red.

## External evidence

- CI run ids on S5a-1's head; the mutants' red tests named in the PR.
- The user's real Mac, after S5a-2: switch modes in a conversation, see Plan refuse a write, see full access run outside the sandbox with no card and still ask for money and a send.
