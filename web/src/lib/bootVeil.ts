/**
 * Boot veil dismissal — the SPA's half of the desktop launch hand-off.
 *
 * The packaged shell plays a launch clip in a separate window that ends on
 * #17150F, then swaps this window in on top of it. `web/index.html` paints a
 * full-screen div of that same colour before React exists, so the swap lands on
 * an identical frame; this module fades it away once React has actually
 * painted. See desktop/splash/index.html for the other side.
 *
 * The fade lives here rather than in a component because it has to run after
 * the first paint of whatever the app decided to render — a component that
 * removed its own cover would be racing its siblings' first render.
 */

export const BOOT_VEIL_ID = "boot-veil";

/**
 * How long the veil takes to fade out.
 *
 * Deliberately shorter than the splash window's 400ms clip fade: by the time
 * this runs the shell has already faded the clip and swapped windows, so this
 * is the tail of the transition, not a second full one.
 */
export const BOOT_VEIL_FADE_MS = 350;

/**
 * Fade the boot veil out and remove it.
 *
 * Removal matters as much as the fade. A veil left in the DOM at opacity 0 is
 * invisible but real, and `pointer-events: none` is the only thing standing
 * between it and a window that swallows every click — one CSS edit away from a
 * bug whose symptom is "the app does not respond" with nothing on screen to
 * explain it. So it goes away entirely.
 *
 * Safe to call when there is no veil (a browser tab removes it during parse)
 * and safe to call twice.
 */
export function dismissBootVeil(doc: Document = document): void {
  const veil = doc.getElementById(BOOT_VEIL_ID);
  if (!veil) return;

  // Cancel the dead-man's-switch animation in index.html before setting
  // opacity: while that animation is running with `forwards`, it wins over
  // inline styles, and the element would sit visible until 2.5s no matter what
  // we set here.
  veil.style.animation = "none";
  veil.style.opacity = "0";

  const view = doc.defaultView ?? window;
  view.setTimeout(() => veil.remove(), BOOT_VEIL_FADE_MS);
}
