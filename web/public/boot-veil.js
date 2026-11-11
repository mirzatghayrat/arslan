// Runs during parse, before the veil has ever painted, so a browser tab
// sees no dark frame at all. Only the packaged shell asks for the fade —
// it sets this flag from an initialization script (desktop/src-tauri/src/lib.rs)
// that runs before any page script. In dev, and in a plain browser, there
// is no splash to hand off from, so there is nothing to fade up from.
//
// A file rather than inline text in index.html since IMG1-B (v0.1.64): the main
// window's CSP (server/main.py) is script-src 'self' with no hash. index.html
// loads it with a classic, parser-blocking <script src> right after #boot-veil.
// It isn't content-hashed and only index.html is no-store, so index.html names it
// with ?v=<date>: change that date whenever this file changes.
if (!window.__ARSLAN_SHELL_FADE_IN__) {
  var v = document.getElementById("boot-veil");
  if (v) v.remove();
}
