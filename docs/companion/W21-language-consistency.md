# W21 — six-language consistency (in progress)

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

1. Finish remaining product-owned recommended-connector descriptions and structured
   runtime service error coverage. Do not translate user-imported skill text blindly.
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
