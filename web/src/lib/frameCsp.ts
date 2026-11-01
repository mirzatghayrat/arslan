/**
 * IMG1 C (0.1.64): what a sandbox="" frame shows doesn't reach the web on its own.
 * sandbox="" stops scripts and same-origin access but not loads, so an `<img src="https://…">` in a
 * file or a model's HTML would still reach that server. Two layers:
 * - Every <link> and <meta http-equiv> is removed first. A CSP can't stop resource hints:
 *   `<link rel=preconnect>` / `dns-prefetch` send the host out through DNS and TLS SNI (WebKit and
 *   Chrome), and Chrome's `rel=prerender` sends a full GET. `<meta http-equiv=refresh>` would navigate
 *   the frame. The frame loads no stylesheets anyway, so no <link> is lost.
 * - A CSP meta then goes first. It blocks every subresource (images, CSS, fonts, media, frames);
 *   inline styles and data: images still show. It goes before even a doctype: an iframe srcdoc
 *   document is never in quirks mode.
 * Not covered: navigation by a click inside the frame (a link the user follows on purpose).
 */
export const FRAME_CSP = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">`;

const UNSAFE = "link, meta[http-equiv]";

function strip(html: string): string {
  // DOMParser runs no scripts and loads nothing, and it parses with scripting off, as the
  // sandboxed frame does (so <noscript> content is markup in both).
  const doc = new DOMParser().parseFromString(html, "text/html");
  doc.querySelectorAll(UNSAFE).forEach((el) => el.remove());
  return doc.documentElement.outerHTML;
}

export function withFrameCsp(html: string): string {
  const clean = strip(html);
  // Serialising and parsing again can rebuild markup differently; if anything unsafe came back,
  // show nothing rather than the document.
  const again = new DOMParser().parseFromString(clean, "text/html");
  return FRAME_CSP + (again.querySelector(UNSAFE) ? "" : clean);
}
