# W21 — six-language consistency (in progress)

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
