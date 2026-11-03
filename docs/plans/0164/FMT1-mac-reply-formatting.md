# FMT1: the Mac's reply formatting catches up with the iPhone mock

| | |
|---|---|
| Grade | **Should** for v0.1.64 (user, 2026-11-03, relayed by ④参谋: 「先让 ②Main 按推荐 A：保持网页，补 3 个 PR」). It goes in if it's done before the tag and doesn't block the tag; whatever isn't done moves to v0.1.65. |
| Lane | ②Main, after its critical-path cards (the model-switch PR B, ROUTE1, MODEL1). |
| Review | High; any part that touches sharing or the Bridge is reviewed at effort=max. |
| Mock | The reference is the iPhone mock the user confirmed (https://claude.ai/artifact/MtEknoVwLtd5bL5vtesNLz). A Mac before/after screenshot goes to the user before the first merge. |

## Decided

- **The Mac stays web,** with React and react-markdown (`web/package.json` already has react-markdown 10 and remark-gfm 4). No SwiftUI rewrite. The reasons, as given to the user:
  - Tauri already uses the system WebKit;
  - the native pieces (Island, Hands, Bridge) are already Swift;
  - the web libraries (KaTeX, a highlighter, remark-gfm) are the most mature;
  - smoothness depends on implementation (re-rendering on every token, virtualization, IME handling).
- **Native is reconsidered only if measured jank remains** after PR 3.

## Three PRs, each off main

1. **Code.** A code-block header with the language and copy; syntax highlighting (pick the lighter of Shiki or a Prism build, measure the bundle and say why); an inline-code background.
2. **Structure.** Formulas (remark-math with KaTeX), nested lists, task checkboxes (read-only), tables.
3. **Actions and speed.**
   - A per-reply copy button. **Share moves to v0.1.65** (user, 2026-11-03: "Copy only for now"); there's no new Tauri IPC in v0.1.64.
   - Streaming performance: measure first. Render once per animation frame instead of per token, and memoize finished blocks.
   - An IME check: composing Chinese while a reply streams must not drop or duplicate characters.

## Method

- Red tests first: a fixture reply with every element, rendered and checked in the web suite.
- A measured frame-time number before and after PR 3, recorded in the PR.
- Licenses checked at the source for every new dependency, with bundle-size deltas in each PR body.
