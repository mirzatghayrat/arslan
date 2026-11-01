/**
 * IMG1 C (0.1.64): what a sandbox="" frame shows loads nothing from the web.
 * sandbox="" stops scripts and same-origin access but not loads, so an `<img src="https://…">` in a
 * file or a model's HTML would still reach that server. A CSP meta at the start of the srcDoc stops
 * images, styles, fonts and frames from the web; inline styles and data: images still show.
 * The meta goes first even before a doctype: an iframe srcdoc document is never in quirks mode,
 * so the doctype after it changes nothing (checked in Chromium; WebKit follows the same spec).
 */
export const FRAME_CSP = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">`;

export function withFrameCsp(html: string): string {
  return FRAME_CSP + html;
}
