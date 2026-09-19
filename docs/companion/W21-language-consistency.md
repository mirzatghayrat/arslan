# W21 — six-language consistency (in progress)

## Open defect: settings navigation drops prepared attachments — 2026-09-19

On the current temporary candidate (backend `d21b525a`, web `838533f2`), imported
the synthetic `/tmp/arslan-attachment-partial-fixture.ts` in German/dark.
The composer showed the exact filename and 12,000 partially extracted characters.
Entered `Synthetic unsent draft — keep this text unchanged.`, opened Settings,
selected Chinese/light, and returned to the workspace. The draft text remained
byte-for-byte intact, Chinese UI/native menus and light appearance applied, but
the prepared attachment was gone. No send/model request occurred. The full
locale matrix was not pursued past this data-loss reproduction.

Source cause: App renders OrchestratorChat only in the arslan section, so
settings navigation unmounts it. Text uses the module-scoped `composerDrafts`
map; attachment state is component-local and the attachment hook revokes image
preview URLs on unmount. This is not caused by translation lookup. Fix still
pending: preserve ready attachments as session-only, conversation-isolated
draft state; handle pending extraction, object-URL ownership, send/remove/clear
and temporary-conversation cleanup without persisting media to disk or silently
restarting work. Cover these boundaries before native revalidation; simply
retaining hidden interactive chat components is not yet an accepted solution.

The synthetic text draft was cleared and the temporary app/sidecar exited.
Test profile now remains Chinese/light. Fresh log contains no external model
HTTP request or traceback. No genuine account, installed app or publication
was used. This finding is an open W21/W20 gate, not a completed locale matrix.

## Native video disclosure overflow — after `c5d2d217`, 2026-09-19

Real German/dark native attachment validation exposed a visible defect despite
passing API tests: the long video capability disclosure did not shrink/wrap,
escaped the chip and composer, and collapsed the source filename. The shared
composer chip now groups filename and metadata in a shrinkable details column.
Filename keeps its own ellipsis/title; disclosures wrap independently; icon
and removal button remain outside the shrinkable column. Width is capped by
both 24rem and the available container rather than a fixed 18rem maximum with
unshrinkable metadata. Image/spreadsheet/presentation disclosures use the same
layout without removing any warning text.

Six real-i18n cases verify the video disclosure, separate filename/title and
working removal control. Focused selection: 18 passed. Full frontend:
**252 files / 1,960 passed in 28.21s**; TypeScript and production build pass
(3.57s, existing large-chunk warning). JUnit:
`/tmp/arslan-attachment-layout-regression.xml`, SHA-256
`ce75359ac1cdac74033129edf0ee9a86fb5f7d8a9ca8203157589ce32cd367c7`.

The temporary app's web resources were refreshed/rebundled unsigned. Native
German/dark inspection of the same synthetic MP4 now shows the full filename,
wrapped three-frame/no-transcription/no-full-motion disclosure and removal
button inside the composer at 1171 × 768 and 931 × 768. Width was restored;
attachment was removed without sending, then app/sidecar termination was
verified. Existing synthetic restore HOME only; local codec directory was
explicitly exposed for this test launch. This does not certify normal-launch
codec discovery or the complete six-language/theme/window-size matrix.

Bundled web tree exactly matches `web/dist`. New entry
`index-BhegZmCg.js` SHA-256:
`225f0fb86cbc8b6f0b14ab9652aa1befb11a7b05bd6daed9be3c4ad143ba5f4a`;
`index-B8GyhNfi.css` SHA-256:
`09c7a5c75fd52f1c23dbf5938742998e6c46bb55ee3c86d7e6fa7c818c68962d`.
Backend/native sources unchanged; the independent backend full run completed
with 5,325 passed and 14 skipped (report identity in W20).
No real model, account, formal installation change or publication occurred.

## Packaged partial-copy verification — `a5c62c2e`, 2026-09-19

Only the temporary candidate's web resources were refreshed and rebundled,
unsigned. Source and bundled `index-D9o_5oeC.js` share SHA-256
`14b60db4561b991fee2bbbe2f51300fb9d0751d5782a5f6b7524bd35e9538c84`.
Native/backend binaries are unchanged. In the existing synthetic HOME,
German/dark at 1171 × 768, importing the synthetic 42,490-byte `.ts` fixture
visibly displayed `12000 Zeichen (teilweise extrahiert)`. The status and
remove control fit; only the long filename was visually ellipsized, with its
full name retained in accessibility text. The attachment was removed without
sending, and native app/sidecar termination was verified. No real model,
account, formal install replacement or publication was involved.

This supersedes the pending native refresh below. Six-language component
coverage is not a six-language native/theme/size matrix, and ArtifactPreview's
new distinction still has component rather than comprehensive native evidence.

## Partial-extraction wording — after `247a896b`

Native PDF validation showed the composer labelled an unread-page result as
merely shortened (`gekürzt`). All six `attach.truncated` strings now say the
source was partially extracted, covering missing OCR pages as well as output
length limits without inventing the reason. Existing API/status names remain
compatible; no attachment text or filenames are rewritten.

ArtifactPreview previously used a beginning-only warning for both its raw-text
display cap and partial document extraction. These states are now separate:
raw text capped at 100,000 characters retains the beginning-only message;
incomplete extracted documents use the canonical six-language partial-source
warning. Both states reset when the selected file changes.

Six real-i18n composer component cases verify partial labels and their absence
on complete attachments. Preview cases verify noncontiguous page excerpts,
state reset and the distinct raw-text cap. Focused tests: 11 passed. Complete
frontend: **252 files / 1,954 tests passed in 25.21s**, TypeScript and production
build passed (7.74s; existing large-chunk warning). JUnit:
`/tmp/arslan-partial-copy-regression.xml`, SHA-256
`5c6072d5d8d862f364e44c551c0bedbe1132b2860e539c5aa94f9e4d4c5d34bf`.
This is source/component evidence; current native candidate still contains the
prior wording. Refresh its web resources and verify the changed long labels
before claiming native acceptance. Backend sources did not change this turn;
their current full regression remains independently running.

## Native selection keyboard acceptance — `d8dcedcb`, 2026-09-19

The temporary candidate was refreshed with the current production web build,
without recompiling unchanged backend/native sources. Staged and bundled web
trees exactly match `web/dist`. Web entry `index-DBZwEC1y.js` SHA-256:
`2bc16cc7a8430812c160736cf645ac88a4caca05364651251fb66a535defc591`.
Backend identity remains
`6280d1c6b03c754330a148ed85dd487a72585a723329a669aff95b1200d4923d`.
The app-bundled standard smoke passed again, including six-language refusal
catalogs, offline expert creation/readback, restart and parent-pipe cleanup.

Actual macOS UI observations using the synthetic restore HOME, German/dark:

- Pointer activation followed by Down and Return selected French. Focus stayed
  on the language trigger and the native menu/UI changed to French.
- Return, Up, Escape kept French and focus on the trigger (no commit).
- Return, Up, Tab closed the menu, kept French and focused the OCR-language
  summary immediately after the trigger.
- Shift-Tab returned to the trigger; Return, Up, Shift-Tab dismissed without
  committing and focused the display-name input immediately before it.
- Tab and Return opened the list using only keys; the listbox was observed
  open with trigger focus. Up and Return selected German and closed the list.

The fresh `select-keyboard.stderr` log contains no external model HTTP request
or error/traceback. Native/sidecar PIDs 40539/40553 exited normally. No genuine
account, real model, formal installation or publication was used. This closes
the focused keyboard reproduction, not all controls, assistive-technology
semantics or the full W21 locale/theme/size matrix. The previous source-only
paragraph below is historical; its requested native check is now performed.

## Shared selection keyboard fix — after `e1f8bf81`

The earlier native observation that Down did not visibly advance the language
menu led to checking the shared Select's focus contract. A new component test
activates the trigger without synthetic pointer-to-focus behavior: the panel
opened, but focus stayed on the body, so trigger-bound arrow handling could not
run. A second test proved Tab left the panel open after focus moved away. Both
tests failed before the fix (21 existing tests passed).

Opening now explicitly focuses the trigger with preventScroll; Tab dismisses
without selecting or preventing normal tab traversal. Mouse option selection,
Escape, disabled-state and existing keyboard behavior remain unchanged. This
is a shared control change, not a language-specific workaround. The focused
selection suite passes 23 cases; the full frontend passes **251 files / 1,946
tests in 24.99 seconds**, TypeScript passes and production build passes in
7.38 seconds (existing large-chunk warning). JUnit:
`/tmp/arslan-select-keyboard-regression.xml`, SHA-256
`e3ce7157230602b09cc944606e685b04b81edf7b33678a2e9736888ed62cccc1`.

This is source/component evidence. The temporary native app still contains
`6f0ae897` assets, so native pointer-then-arrow/Enter, Escape and Tab/Shift-Tab
verification must follow a candidate refresh. The full accessibility and
locale/theme/size matrix remains open. No backend or native source changed;
the preceding 5,304-test backend result remains applicable.

## Packaged runtime-error acceptance — `6f0ae897`, 2026-09-19

The source fix below is now in the unsigned temporary app. Complete Python
regression passed **5,304 tests, 14 skipped, 18 warnings in 514.36 seconds**,
exit 0. JUnit `/tmp/arslan-error-locales-regression.aA4g5Z/full.xml`, SHA-256
`cc3241565be3d72e979add2a074aadc4512224050d15d171741df9a4c071b793`.
The existing aiosqlite teardown guard reported 74 closed-loop deliveries; that
known cleanup issue is not claimed fixed. Frontend remains at the source
checkpoint's 1,944 passing tests, with no subsequent product changes.

Fresh frozen output and the app-bundled executable both passed the expanded
smoke, including complete six-language error catalogs and offline expert
creation/readback. Packaged web assets exactly match `web/dist`; the 15-module,
asset/no-secret/no-database/no-AGPL checks passed. The app's bounded browser
reader smoke also passed, with zero owned children and removed reader profiles.
No runtime installation was tested.

Using only `/private/tmp/arslan-native-restore-ui-m1tgzvbv`, one synthetic message
produced a French no-provider error. Without sending another message, native
settings switches changed that same error body to English, Chinese, Japanese,
Spanish and German. The original user message stayed unchanged. French/English
were light; Chinese/Japanese/Spanish/German were dark. Screenshots inspected
English, Chinese and German error wrapping at 1171 × 768. This is a focused
main-chat acceptance, not the complete locale/theme/size/keyboard matrix or a
native direct-chat acceptance. The fresh `runtime-locales.stderr` log contains
no external model HTTP request. Native/sidecar PIDs 38384/38392 exited normally;
the disposable profile is now German/dark.

Temporary bundle:
`/tmp/arslan-native-candidate.xIygc5/target/release/bundle/macos/Arslan.app`.
Frozen output: `/tmp/arslan-candidate-build.BboGj4/dist-runtime-error-locales`.
SHA-256 identities:

- Native executable (unchanged): `fa0d2c37c102e8d0d93125423b2e2b28ecd7e494d11b558d4da1303de2052d30`.
- Backend: `6280d1c6b03c754330a148ed85dd487a72585a723329a669aff95b1200d4923d`.
- Web entry `index-B_sfJxwb.js`: `02c87091930a3172717ddeb70bef4fb08cfa910fd1bd40e6a9ecf68998935274`.

No genuine account, model credential, formal installation, signing or publication
was used. Follow the remaining W17 gates; this does not certify release readiness.

## Runtime-error language-switch source fix — after `0a428cbf`

Model-error frames now preserve their legacy localized `message` and, only for
recognized product-owned notices, carry a complete six-language `message_i18n`
catalog. This reuses the backend's canonical copy rather than maintaining a
second frontend translation table. The no-provider condition is a typed
`ModelNotConfiguredError`, not recognized by matching translated prose.
Existing narrow provider categories and actual-image refusal checks retain
their precedence. Unknown diagnostics have no catalog and remain unchanged.

Both main chat and expert direct chat render the catalog in the current UI
language. The main store clears it on dismiss/reset or a subsequent raw error;
the direct-chat runtime-error echo retains it only for the current session.
Malformed/incomplete/oversized catalogs are ignored. User/model prose and old
history messages are not rewritten or guessed from their wording. No database
migration or model call is needed to switch language.

Evidence: 251 frontend files / 1,944 tests passed in 23.23 seconds; TypeScript
and production build passed (3.19 seconds, existing chunk-size warnings).
Tests rerender an already-visible main-chat error across all six languages
without a new frame; direct-chat checks cover quartz/linear/brutalist layouts
and preserve original model prose. Backend targeted selection passed 90 tests
in 8.30 seconds, including actual direct-chat WebSocket metadata transport,
main/router/answer/delegated error paths, factory refusal and locale catalogs.
The wider vision/error/run-recording selection passed 46 tests. Lint and
whitespace checks passed.

Frontend JUnit: `/tmp/arslan-runtime-error-locale-regression.xml`, SHA-256
`36f409152291549cd4e889ffae0b834913ad14e0ca8a81311690d71cef34f548`.
A fresh complete Python run is active at
`/tmp/arslan-error-locales-regression.aA4g5Z/full.xml`; it is not yet claimed
passing. The existing temporary native app still predates this source fix.
Next: collect full regression, refresh candidate, verify an existing error
actually re-renders after a native settings-language change. The frozen smoke
now asserts all six catalog entries, but awaits that refreshed executable.

## Native attachment-notice language pass — after `1499ee8b`

The refreshed temporary app uses frozen backend
`ab674c374d5f5db7a844e8433e2c6a61fae31a20f5bb90f57fe9cc79b575bd16`
and the unchanged `dd150e9a` web assets. With only synthetic profile
`/private/tmp/arslan-native-restore-ui-m1tgzvbv`, a deliberately invalid PNG
was attached and sent with no provider configured. Its unavailable-image chip
was observed in Chinese/dark, then English/Japanese/Spanish/German/French/light
by switching language through the real settings UI. All six notice texts were
present; the five light-language screenshots showed complete wrapping without
overlap. New requests after each language switch returned the corresponding
localized configuration refusal, with no external model HTTP request in the
fresh app log. The native menu labels also followed each selected language.

The French window was resized from an approximately 1,171×768 screenshot to
986×758; message scrolling, the long error text, composer and attachment notice
remained usable. This is one narrower layout, not the full native minimum-size,
keyboard, every-locale × every-theme matrix. The app and backend were quit
normally (owned PIDs 33442/33456 absent). The disposable profile now retains
French/light; no personal app settings or formal installation was intentionally
changed.

New verified gap: the already-visible server error body is a rendered string
from its original language. Switching language updates its heading and the
attachment notice, but does not retranslate that error body until another
request replaces it. This is product-owned error text, not model/user prose;
it remains a W21 gap. Preserve the distinction when adding structured error
localization: do not translate arbitrary provider diagnostics or historic user
content. The language dropdown also did not visibly advance after a single
Down key in this native test; keyboard acceptance is not claimed by this pass.

## Native menu implementation (2026-09-19, visual acceptance pending)

Product-owned menu labels now have six-language copy. The menu retains Tauri
predefined native roles for undo/redo, cut/copy/paste/select-all, window controls,
Services, hide and quit, and retains the special Window/Help IDs. Translation
updates existing item handles on the main thread rather than replacing actions
or rebuilding the menu. The locale hint remains display-only. Successful
language persistence triggers the existing read-only `update_status` command
to refresh labels; failed writes and unrelated settings do not. No new IPC
permission or model call was introduced. Focus and existing polling remain
fallback refresh paths.

Native tests: 30 passed, including full six-language catalog coverage. Frontend:
242 files / 1,879 tests passed (26.85s), including persistence ordering, failure
and unrelated-setting cases; typecheck and production build passed. Actual
menu text and native edit-action behavior are NOT accepted yet: the Mac was
locked when UI inspection was attempted. The temporary app was stopped after
the attempt; no production application or account was changed. W17 records
the rebuilt package and non-UI checks.

## Native restart follow-up (2026-09-19)

The new durable onboarding flag passed actual quit/relaunch on different
loopback ports using one disposable backend profile. Japanese UI and ja-JP
speech-input hint survived; onboarding did not reappear. Two Settings round
trips and the restart retained a visible greeting in this bounded run, but the
older intermittent rendering finding remains open. Native menu titles still
remain English. W17 records the package and tests; W21 is not fully accepted.

## First-run host-state repair (2026-09-15)

The unlocked, isolated native candidate reproduced a real integration defect:
choosing Chinese in onboarding and dismissing it left the backend and native
locale hint at `zh`, but entering Settings reset the visible UI to English.
Onboarding updated i18next and the server without updating App's settings.

The wizard now synchronously notifies its host of language selections; App merges
that field into its UI state and shared settings store. Onboarding also waits for
the initial settings read to settle, preventing a late startup response from
overwriting a selection. Persistence remains best-effort as before; this does not
claim a failed save survives restart.

Six new tests first failed on the missing host notification, then passed for all
supported languages with persistence deliberately left pending and immediate
dismissal. The focused selection passed 33 tests; the complete frontend suite
passed 239 files / 1,862 tests in 21.92s. TypeScript and production build passed.
Existing jsdom canvas/navigation and large-chunk warnings remain. Native package
revalidation is recorded separately in W17; this is not full W21 sign-off.

The first rebuilt app passed Chinese onboarding → skip → Settings, then exposed
another shared-state defect: choosing Japanese in Settings left the composer's
speech-locale hint at `zh-CN`. Successful Settings saves now update the shared
backend-shaped store as well as the host. Only fields actually sent by that
request are copied from the server's response, so unrelated settings are not
overwritten and edited secrets are represented by the server's masked value.
Failed and superseded responses do not update the store. Four additional tests
cover these boundaries (three reproduced failures before the fix); the focused
selection then passed 37 tests and TypeScript passed. No microphone capture or
real-model speech processing was enabled for this UI inspection.

## Deterministic runtime notices

Seven product-owned notices now have complete six-language copy: stale proposal,
unfinished round, findings header, empty-answer clarification, and three honest
correction templates. `runtime_messages` selects the active task's pinned locale,
or reads only the saved language setting outside a task. Unknown/unavailable
settings fall back to English; cancellation propagates. Legacy language labels
and regional codes use the same normalized language in new task specs and notices.
No secret setting is read to choose language, and concurrent tasks do not share
a mutable locale. Existing resynthesis calls receive the selected notice locale;
this adds no translation model call.

All production fallback call sites pass the selected language, including visual
input failures. User/source text and model-authored prose are not translated.
The direct synchronous legacy helper defaults remain compatible. Findings and
unfinished-message recognition cover all six generated forms and old Chinese /
English markers; none of those labels grants authority or starts another run.

The adjacent run passed 138 tests in 39.90 seconds. Subsequent legacy-task and
storage/cancellation cases brought the focused catalog to 31 tests (5.42 seconds).
The final shared-marker follow-up passed 40 runtime/continuation tests in 5.45
seconds. Targeted lint and whitespace checks pass. Earlier failures were five
tests expecting unconditional Chinese defaults (updated to the new default while
preserving behavioral assertions) and a new incomplete runtime test double
missing `closed` (fixed in the fixture, not by weakening runtime checks).

This is not all runtime localization or a fresh full regression. Known next
items include missing-expert errors, provider-error explanations and image-error
copy. External diagnostics must retain their meaning, not be silently turned
into a guessed local diagnosis. Full release-source regression and packaged UI
acceptance remain outstanding.

## Real-browser settings follow-up

The isolated `companion_smoke_app` harness was run with the production frontend,
real migrations/settings API, temporary HOME/data and a synthetic model. HTTP
outside loopback was disabled in the harness and browser requests were restricted
to its exact origin. No installed browser profile or application data was used.

All six languages passed select language → immediate Back → reload → reopen
settings at 1100/600×800 in explicitly selected light/dark modes (24 cases).
Post-fix departure took 66–140 ms; the real API and reopened selector retained
the chosen language. No page exceptions or document-width overflow occurred.
The first pass changed the browser's color preference without changing Arslan's
saved default-dark choice, so it was not accepted as light-mode evidence; the
corrected run clicks the product's mode control and checks the DOM theme.

Visual review prompted a stronger label-bound check, which failed on the old
English desktop navigation: its 197-pixel button had 202 pixels of scroll width.
Desktop navigation labels now wrap within their buttons; narrow navigation stays
a horizontal chip row. The strengthened 24-case run passed, and all 24 final
screenshots were inspected in `/tmp/arslan-companion-ui-locale.VkcSof/fixed`.
The test driver is `/tmp/arslan-companion-ui-locale.VkcSof/locale.cjs`; it is a
temporary harness, not a tool for modifying production settings.

Complete frontend regression: 237 files / 1,835 tests in 20.68 seconds; typecheck
and build (6.65 seconds) pass. After that run, a responsive-class regression was
added; the focused settings/language selection passed 15 tests in 0.913 seconds.
The class assertion protects the implementation, while real Chromium supplies
layout evidence. Existing warning categories remain. This closes the earlier
browser-level rapid-departure check, not all W21 workflows or packaged desktop
acceptance. Runtime deterministic messages still need six-language work (for
example stale proposal confirmation and fallback corrections).

Starting commit: `3db2f857` (W16 navigation). This is an implementation checkpoint,
not release-candidate sign-off.

## Implemented

- Localized connection registration, permission controls, candidate drafts, MCP
  confirmation stages, legacy chat chrome, diagnostics, loading states and
  attachment/accessibility labels in English, Chinese, Japanese, Spanish,
  German and French. Updated obsolete navigation advice to Connections & permissions.
- Filled inherited English UI copy in Japanese, Spanish, German and French.
  Brand names, protocol identifiers, code, quotations and user content remain
  unchanged. Source diagnostics from unknown external services remain available.
- Dates and times follow the selected UI language; backend naive UTC timestamps
  are interpreted as UTC. Marked generated default conversation titles follow
  language changes without rewriting legacy or user-authored titles. The marker
  has no authority over emptiness, pruning or deletion.
- Language choices flush immediately instead of waiting for the settings debounce.
  A failed save realigns the visible language with the rollback. An unblurred
  secret cannot accompany a language save.
- Registry responses expose a stable `unsandboxed_python` warning code while
  retaining the legacy warning. The UI translates the warning, including tooltip.
- Built-in toolset names and summaries have six-language UI resources. The server
  supplies display keys only for text that still exactly matches the seeded value;
  custom names/descriptions are preserved independently. Stored data and model-facing
  tool schemas are unchanged. Visible search and equipped-capability labels follow
  the translated toolset names; unknown keys retain source text.
- Added static UI-text/key checks, resource/interpolation parity checks, real-i18n
  component tests in all six languages, generated-title persistence tests and
  registry display ownership tests.

## Evidence and limits

- Before the registry display extension: production build and TypeScript passed;
  complete frontend suite passed 230 files / 1,762 tests.
- Registry warning/display extension: 4 backend tests and 22 focused frontend
  tests passed; TypeScript passed. Full frontend rerun passed 231 files / 1,770
  tests in 18.18 seconds; production build passed in 5.19 seconds. Existing
  large-chunk warnings and jsdom canvas/navigation notices remain.
- Real browser inspection earlier found a language reverting after quick departure
  from Settings. The 600 ms unmount-cancelled debounce was confirmed in source;
  the immediate-flush regression test passes. Post-fix browser confirmation is
  still required: the Mac was locked during two subsequent inspection attempts.
- Static text scanning does not prove dynamic/backend text coverage, layout quality
  or all runtime workflows. Unknown diagnostics are not falsely marked translated.
- Tests use a synthetic local database, fake providers and no real credentials.
  No paid model requests, account writes, publication or installed-app replacement.

## Remaining gates

1. Finish structured runtime service error and deterministic chat-message coverage.
   Do not translate user-imported skill text or unknown external diagnostics blindly.
2. Verify all six locales in the live UI, including rapid language change → Back →
   reload, generated titles, narrow/wide layouts, light/dark themes and errors.
3. Complete W20 video understanding evidence, W15 workflow evidence and the W17
   release audit. W21 remains open until the actual scope is verified.

## Built-in skills checkpoint

All 55 seeded skills now have display names and descriptions in all six languages
(660 nonempty fields), with localized labels for the 11 built-in categories.
Brand names, filenames and protocol identifiers remain literal. Permission and
execution caveats are retained in the localized descriptions; capability tiers,
assignability, stored metadata, skill bodies and model-facing identifiers are
unchanged. These descriptions summarize the skill method, not a claim that an
unavailable integration is wired.

The registry emits each skill display key only while its corresponding source
field exactly matches the seed. User-edited fields and unknown/imported entries
retain their text independently. The capability catalog searches localized labels
and summaries while keeping key-based search. Equipped labels update on language
change. The quick picker and expert editor now resolve display hints for both
skills and toolsets, while selection still passes stable keys. Unknown category
labels fall back to their source value.

Evidence:

- Backend coverage compares every language's exact key set against the actual
  `SKILLS` catalog, checks per-field ownership and verifies hints through the API.
- Registry seeding/service/honesty/display regressions: 63 passed, 1 existing
  allowlist skip. Targeted Python lint and whitespace checks passed.
- Real-i18n component coverage renders every translated skill field in all six
  languages, exercises translated-description and stable-key search, preserves
  custom text, verifies picker IDs/disabled selections and in-place equipped-label
  language changes. Focused catalog tests: 20 passed; TypeScript passed.
- Complete frontend regression: 235 files / 1,802 tests passed in 18.46 seconds.
  Production build passed in 2.95 seconds; existing bundle-size warnings remain.
- Actual browser layout checks and the overall six-language release gate remain
  pending; automated rendering alone does not prove visual quality.

## Recommended connectors checkpoint

The ten static MCP presets now provide six-language display names/descriptions and
the two credential prerequisites. REST catalog and chat proposals carry UI-only
keys. Connection commands, arguments, authentication categories, credential names,
links and permission tiers remain unchanged. The catalog returns independent
argument and credential-metadata copies. Chat frames continue to exclude credential
values; only display metadata was added to the existing whitelist.

The recommended list and chat confirmation card resolve those keys with source
fallback for old or unknown data. The generated prerequisite prefix and path errors
follow the current language; arbitrary prerequisite text remains untouched. A failed
catalog read is now visibly unknown/error with a read-only retry, rather than looking
like an empty recommendation list. Missing-runtime hints update on language change
while preserving the original external diagnostic.

Inspection also found that the old installed check used the final argument as a
package fallback. For Playwright, that was `--sandbox`, so an unrelated command with
the same flag could appear as the preset. Matching now requires command, transport,
and the full preset argument prefix, including pinned version and private-browser
flags. This only changes display matching; it never connects or installs a server.

Verification:

- Connector catalog/auth/router/confirmation/protocol regressions: 54 passed.
- Focused frontend connector/confirmation tests: 49 passed before the additional
  prerequisite-prefix assertion. All six languages, immutable action inputs,
  password-field names, three false-positive installed cases, exact matching,
  immediate path-error language change and fetch retry are covered.
- TypeScript, targeted Python lint and whitespace checks passed. No real connector,
  account, model, download or credential was used. Actual UI layout inspection and
  full W21/RC acceptance remain outstanding.
- Final complete frontend rerun: 236 files / 1,820 tests passed in 18.15 seconds;
  production build passed in 2.97 seconds, with the existing bundle-size warning.

## Runtime service-error checkpoint

Recognized context, transport, key-limit, region, balance, authentication and rate
errors now follow the saved UI language on host/expert chat and connection tests.
Image-schema refusal and missing-expert notices use the same six-language policy.
Unknown external diagnostics remain untouched; no model is called to translate.
Classifier precedence, error codes and missing-expert early-return boundaries are
preserved. Expert errors now share the host's recognized provider explanations.

Transport wording no longer asserts that the request never arrived or that the
key cannot be at fault: read timeouts and interrupted connections cannot prove
processing status. Generic key-limit advice points to the provider dashboard,
without inventing an OpenRouter account or directing the user to increase spend.
Keyless 401/403 copy asks about key requirements and permissions, without claiming
every 403 proves that a key is required. No automatic retries were introduced.

The initial combined focused regression passed 117 tests, including all six saved
languages and existing OCR fallback/error-classification contracts. Seven further
guards cover unknown diagnostic passthrough and provider-neutral limit advice.
The final combined rerun passed all 124 tests; targeted lint and whitespace checks
also passed. The only warning was the existing Starlette/httpx deprecation.
This source checkpoint does not complete live-layout or final release acceptance.

## Follow-up to native-window findings

The actual temporary macOS application exposed untranslated service status and
legacy composer vocabulary. Online/offline copy now uses Japanese, Spanish,
German and French phrases; both composer states use the current expert vocabulary
across all six languages. This changes product copy only, not user-authored
conversation content or expert IDs. A real Sidebar component test renders all
three connection states in each locale instead of merely checking key presence.

The bundled splash now receives display-only JSON from the native saved-locale
hint before its page script runs. Starting, longer-wait and generic failure copy
cover all six languages; missing/invalid hints retain English. Raw technical
error details are preserved but encoded with JSON rather than hand-escaped into
JavaScript, and rendered as text, never HTML. No page command or permission is
added. Failure/fade-out cancels the pending wait timer, and failure hides the slow
notice so it cannot overlap the error. The existing clip and transition timings
remain unchanged.

The complete frontend suite passed **239 files / 1,856 tests in 19.20 seconds**,
including execution of the actual bundled splash script in six locales, early
failure timer cancellation and markup-as-text guards. TypeScript and production
build passed (3.07 seconds); existing jsdom canvas/navigation and bundle-size
warnings remain. All **29 native Rust library tests** passed, including JSON
round-trip tests with quotes, slashes and control characters; the backend native
hint/permission selection passed **20 tests**. These new source changes are not
yet in the previously inspected app, and require rebuilt-package/UI validation.
