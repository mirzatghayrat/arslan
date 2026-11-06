# HPW: Hands refuses to paste only when it knows a password field is taking input

| | |
|---|---|
| Decided | The user, 2026-11-03, relayed by ④参谋. The user had called the refusal over-defensive (「是不是过度防御了」), approved the change below, and passed it to ⓪Plan. |
| Version | v0.1.64 |
| Lane | ③Hands, after its SBX items |
| Review | effort=max (Hands' policy is security surface, `docs/sessions.md` §5) |
| Size | One PR: about +60 product lines in `desktop/hands/src/`, plus tests |

## The problem

Hands refuses ordinary typing in apps that don't report keyboard focus, such as WeChat, and tells the user and Arslan that it's a password field. It isn't.

- **What happened (two runs on the user's installed 0.1.63, read only):**
  - The task was to send a short greeting to a WeChat group.
  - `desktop_look {role: textfield}` found nothing: WeChat exposes almost no accessibility tree.
  - The `type` step failed with `bad_ref`.
  - The fallback, `pbcopy` then `desktop_press cmd+v`, was refused with code `password_field`: "Arslan never types into password fields. Ask the user to fill it in themselves."
- **Why:** `policy::press_refusal` (`desktop/hands/src/policy.rs:204`) refuses any key chord that may type (`keys_may_type`, `:183`) when `focused_secure` is `None`, that is, unknown. `macos::focused_secure` (`desktop/hands/src/macos.rs:187`) returns `None` because WeChat leaves `AXFocusedUIElement` unanswered.
- **The text hides which branch fired,** so both the user and Arslan read "unknown" as "a password field".

## The change

1. **Keep the hard refusal** when macOS says the focused element is a secure text field: role or subrole `AXSecureTextField`, or the `secure` state. Computer-use agents never type passwords for the user.
2. **Replace "unknown → refuse".** When accessibility can't say, ask the system-wide secure-input state (`IsSecureEventInputEnabled()`, Carbon/HIToolbox):
   - **off:** no secure field is taking input anywhere, so allow;
   - **on:** refuse, as today.
3. **Honest refusal text, in two codes:**
   - `password_field` stays for (1): "this is a password field".
   - A new code for (2): "couldn't tell what has focus, and secure input is on". The text names the known cause, an app holding secure input on (Terminal's Secure Keyboard Entry, some password managers).
   - Each gives a SMART-3-style next step: the place and the action.
   - The new code needs its Bridge/phone mapping checked, and FrameMapper's if it surfaces there. It must not change a Bridge frame without ①iOS and ②Main.
4. **The same rule for `menu_refusal`** (`policy.rs:231`, the paste menu items).
5. **Unchanged:** `looks_like_password` (`desktop/hands/src/server.rs:696`) and `PASSWORD_WORDS` (`policy.rs:35`) in the type/set_value path. Their false-positive risk goes under "Not covered".

## References

- Claude computer use and Codex refuse to enter credentials for the user. None of them blocks every app that doesn't report focus.
- macOS signals a secure field taking keystrokes system-wide through secure event input (`EnableSecureEventInput`/`IsSecureEventInputEnabled`). That's the same signal password fields and Terminal's Secure Keyboard Entry use.

## Raw material

- `desktop/hands/src/policy.rs:183` (`keys_may_type`), `:204` (`press_refusal`), `:231` (`menu_refusal`), and the tests at `:254` and `:297` that pin "unknown refuses".
- `desktop/hands/src/macos.rs:187` (`focused_secure`).
- `desktop/hands/src/server.rs:714` (`focused_password_field`), and the refusals at `:939`, `:972`, `:1046` and `:1349`.
- The two runs above, in the user's database, read only: tool steps and error codes, no message content.

## Method

- **Red tests first:**
  - focus unknown with secure input off: `cmd+v` is allowed;
  - focus unknown with secure input on: refused with the new code;
  - `AXSecureTextField` focused: always refused as `password_field`, whatever secure input says.
  - The same three for `menu_refusal`.
  - The existing tests at `policy.rs:254` and `:297` are rewritten to match, and the PR body says so.
- **Mutants on both branches:** the secure-input check, the unknown case, and the secure-field case.
- The secure-input query sits behind a function the tests can replace. No test depends on the machine's real secure-input state.

## External evidence

- **A real-Mac check by the user, before the tag:**
  - send a WeChat message by paste;
  - confirm that a real password field (a login sheet) is still refused.
- **CI:** the `macos` job runs the Hands tests.

## Not covered

- `looks_like_password`'s label words can still refuse a field whose name only mentions a password.
- An app that holds secure input on blocks pasting into apps that don't report focus until it lets go. The refusal names the cause.
