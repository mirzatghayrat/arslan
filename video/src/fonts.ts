import mono400 from './fonts/ibm-plex-mono-400.woff2';
import mono500 from './fonts/ibm-plex-mono-500.woff2';
import mono600 from './fonts/ibm-plex-mono-600.woff2';
import interVariable from './fonts/inter-variable.woff2';

/**
 * Fonts are vendored under `src/fonts` (latin subset, OFL — see the README in
 * that directory) and inlined into the bundle as data URIs by the webpack rule
 * in `remotion.config.ts`. Nothing is fetched at render time: no CDN, no
 * render-time static server, no dependency on the render browser trusting a
 * corporate TLS root.
 *
 * Deliberately no `delayRender()` here. Both `new FontFace().load()` and
 * `document.fonts.load()` were observed never settling on a freshly opened
 * render page, and a `delayRender` waiting on either one killed whole runs
 * hundreds of frames in. Racing them against a timeout does not help — Remotion
 * replaces `setTimeout` in the render environment, so a wall-clock budget never
 * fires either.
 *
 * A data URI needs none of that machinery: the bytes are already in the
 * document, so the face resolves during layout with no request and no promise.
 * `font-display: block` keeps text from painting in fallback metrics while it
 * does, and the probe below forces both families into layout on the first
 * frame rather than on first use.
 */

const FACES = [
  {family: 'Inter', weight: '300 700', url: interVariable},
  {family: 'IBM Plex Mono', weight: '400', url: mono400},
  {family: 'IBM Plex Mono', weight: '500', url: mono500},
  {family: 'IBM Plex Mono', weight: '600', url: mono600},
];

if (typeof document !== 'undefined') {
  const style = document.createElement('style');
  style.setAttribute('data-arslan-fonts', '');
  style.textContent = FACES.map(
    (f) => `@font-face{
  font-family:'${f.family}';
  font-style:normal;
  font-weight:${f.weight};
  font-display:block;
  src:url(${f.url}) format('woff2');
}`,
  ).join('\n');
  document.head.appendChild(style);

  // Off-screen probe: gives the engine a reason to realise both families
  // before any scene asks for them.
  const probe = document.createElement('div');
  probe.setAttribute('aria-hidden', 'true');
  probe.style.cssText =
    'position:fixed;left:-9999px;top:0;visibility:hidden;pointer-events:none;';
  probe.innerHTML = FACES.map(
    (f) =>
      `<span style="font-family:'${f.family}';font-weight:${
        f.weight.split(' ')[0]
      }">Arslan</span>`,
  ).join('');
  document.body.appendChild(probe);
}

export {};
