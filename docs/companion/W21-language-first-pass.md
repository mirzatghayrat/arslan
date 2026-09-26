# W21 — first language correction pass

2026-09-14. The product still supports en/zh/ja/es/de/fr. Locale detection is limited to those languages and resolves regional variants to the base language.

The skill contract now accepts English `Decision Rules` and the legacy Chinese heading. Newly scaffolded skills use English protocol headings; existing skill bodies are not rewritten. English, German, Spanish, French, and Japanese skill-form instructions no longer require a Chinese heading. Chinese UI examples remain compatible.

PPTX cards now use localized generation/count text and accessible download labels. The four previously untranslated generation strings were translated. User filenames are preserved without forced translation.

Tests: 32 Python skill compatibility/service tests; 16 locale/content tests (including all six deck-card locales); TypeScript check passed. Locale guards reject Han script in en/de/es/fr product resources. This is a narrow useful guard, not a complete language detector: shared English strings, backend-owned dynamic copy, notifications, dates and runtime screens still need the W21 audit.

No claim of complete six-language visual/runtime acceptance is made by this first pass.

Final full frontend regression: **1,697 passed, 0 failed, 0 skipped**; TypeScript passed. The first full run exposed 17 failures from the old mandatory-Chinese-heading assertions, an untranslated standalone card test, and duplicated deck completion wording. Updated compatibility assertions, initialized the real translation instance in the download test, and separated localized slide-count copy from completion copy. All original download/Blob checks remain. Existing jsdom canvas/navigation warnings persist.
