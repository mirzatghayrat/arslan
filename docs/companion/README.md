# Personal companion implementation

Status: started on 2026-09-14. Approved direction: Arslan preparation/architecture v1.2, with the user's start-of-work additions below. Implementation branch: `codex/companion-v12-2026-09-14`; starting commit: `d3e8081d0fc7a72072731edfaa0ea33acf095724` (desktop 0.1.39).

## Start-of-work amendment (v1.3)

This amendment supersedes the Freehand icon decision and makes browser, side-panel, input coverage, and language consistency explicit release requirements. It does not authorize access to real secrets, paid model calls, account writes, publishing, or replacement of the installed app.

- Use the existing `lucide-react` family consistently. Do not import Streamline assets or add a second navigation icon family. The app logo remains a later design task.
- Preserve all supported product languages: English (`en`), Chinese (`zh`), Japanese (`ja`), Spanish (`es`), German (`de`), French (`fr`). Product-owned labels, errors, notifications, empty/loading states, dates, and generated default names must follow the selected UI language. User-authored material, source quotations, code, proper names, and explicitly requested output languages are not blindly translated.
- Keep and improve Arslan's own browser. The current static screenshot/text preview is a baseline, **not** an interactive-browser implementation. The target includes tabs, navigation, task association, inspection, and bounded interaction, with an isolated browser profile and explicit controls for sensitive actions.
- Provide a persistent, resizable side panel for browsing and inspecting work while keeping the conversation available. Typed tabs should cover browser pages and supported artifacts; support open/close, focus, keyboard navigation, and recovery of safe metadata. No privileged application bridge is exposed to untrusted pages or documents.
- Preserve existing text, PDF, Word, image/OCR, URL, code/file tooling and artifact output. Extend a declared input matrix to common code/text/data formats, spreadsheets, presentations, and video. Preview, extraction, visual understanding, and editing are different capabilities; unsupported codecs, encryption, missing tools, truncation, or missing model support must be explicit.

## Delivery order

W00 baseline/protection → W01 evaluation catalog → W02 typed contracts/runtime decision → W03–W06 project/memory → W07–W10 execution/acceptance → W11–W16 authorized workflows and UI. W17 is the release-candidate gate, and W18 remains the later expanded quality evaluation.

Additional package IDs are identifiers, not a promise to postpone these requirements until after W18:

| Package | Depends on | Required work | Release gate |
| --- | --- | --- | --- |
| W19 Browser and side panel | W02, W07, W11; initial read-only panel can precede interactive actions | Typed dock tabs, isolated browser session, navigation/read/interaction, task ownership, cancellation, permission checks, safe preview origins | Required before W17 |
| W20 File and media input coverage | W02, W05, W10; safe extractors can be delivered earlier | One supported-format registry, bounded extraction, source/page/cell/time locators, artifact previews, video metadata/frames/transcript capability disclosure | Required before W17 |
| W21 Six-language consistency | Starts during W00, continues through every UI/backend change | Resource parity, no product-owned language leakage, structured/localizable service errors, runtime UI checks in all six locales, old data compatibility | Required before W17 |

No feature is removed merely because its new entry is not yet implemented. Existing static browser safety tests stay; the interactive mode gets a separate policy and test suite rather than weakening the old mode's guarantees.

## Product vocabulary

Main navigation: Conversations / Projects / Memory / Capabilities. Chinese: 对话 / 项目 / 记忆 / 能力库. Bottom: Connections & permissions / Settings.

Memory: About me / Library / Knowledge map. Capabilities: Experts / Skills & workflows / Tools / Discover. Stable internal IDs and old deep links remain compatible. Product-owned copy uses localization keys rather than translated literals embedded in components or server messages.

## Package evidence

Each package records the starting commit, changes, protected behavior, tests (including failures/skips), real vs synthetic evidence, side effects/costs, remaining gaps, and next dependency. Tests and a generated schema do not by themselves complete the agent workflows they describe.

See `W00-baseline.md` for the initial environment and protection findings. The implementation plan outside the repository remains the detailed product reference; this directory is the versioned implementation/evidence record.
