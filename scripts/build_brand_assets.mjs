// Deterministic exports from approved raster artwork and native vector masks.
// Requires ImageMagick and (on macOS) iconutil. Never edits the source artwork.
import { createRequire } from 'node:module';
import { readFileSync, writeFileSync, mkdirSync, mkdtempSync, rmSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const { Resvg } = createRequire(join(root, 'web/package.json'))('@resvg/resvg-js');
const render = (doc, path) => writeFileSync(path, new Resvg(doc).render().asPng());
const art = join(root, 'desktop/artwork');
const out = join(root, 'web/public/brand');
const icons = join(root, 'desktop/src-tauri/icons');
const tmp = mkdtempSync(join(tmpdir(), 'arslan-brand-'));
mkdirSync(out, { recursive: true });
const svg = (body) => `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1280" height="1280" viewBox="0 0 1254 1254">${body}</svg>`;
function clipped(source, shape, name) {
  const data = readFileSync(join(art, source)).toString('base64');
  const doc = svg(`<defs><clipPath id="edge">${shape}</clipPath></defs><image width="1254" height="1254" clip-path="url(#edge)" xlink:href="data:image/png;base64,${data}"/>`);
  writeFileSync(join(tmp, `${name}.svg`), doc);
  render(doc, join(out, `${name}.png`));
}
// One smooth vector boundary excludes the generated alpha fringe and speckles.
clipped('frosted-source.png', '<path d="M320 88H932C1068 88 1140 161 1140 310V907C1140 1056 1069 1120 928 1120H322C178 1120 109 1055 109 909V310C109 160 179 88 320 88Z"/>', 'frosted');
clipped('mark-source.png', '<path d="M194 570C181 490 179 269 180 198C180 110 249 86 303 139L457 294Q625 232 794 294L944 143C1001 88 1074 106 1074 199L1070 474Q1066 531 1056 570C1100 665 1078 722 1026 800L870 1014C788 1126 718 1165 625 1165C526 1165 449 1122 370 1015L222 807C168 729 151 668 194 570Z"/>', 'mark-frosted');
// The selected flat face, traced as editable geometry; black is exactly #000.
const face = 'M286 517L283 287C283 231 320 208 358 237L494 332Q626 280 758 332L894 237C932 208 969 231 969 287L966 517C966 562 982 603 963 651C944 694 909 731 880 777L811 890C758 974 698 1006 626 1006C554 1006 494 974 441 890L372 777C343 731 308 694 289 651C270 603 286 562 286 517Z';
const head = `<path fill="#fff" d="${face}"/><path fill="#999" d="M310 496L307 286Q307 236 349 259L465 343Q376 404 310 496ZM942 496L945 286Q945 236 903 259L787 343Q876 404 942 496Z"/><path fill="#000" d="M386 518C478 501 558 551 552 650C449 654 387 604 386 518ZM866 518C774 501 694 551 700 650C803 654 865 604 866 518Z"/><path fill="none" stroke="#000" stroke-width="10" stroke-linecap="round" d="M626 696L495 813M626 696L757 813M626 696V893"/><g fill="#000"><circle cx="626" cy="696" r="29"/><circle cx="495" cy="813" r="25"/><circle cx="757" cy="813" r="25"/><circle cx="626" cy="893" r="30"/></g>`;
writeFileSync(join(out, 'monochrome.svg'), svg(`<rect x="109" y="88" width="1031" height="1032" rx="210" fill="#000"/>${head}`));
writeFileSync(join(out, 'mark-monochrome.svg'), svg(`<g transform="translate(-130 -170) scale(1.21)">${head}</g>`));
render(readFileSync(join(out, 'monochrome.svg')), join(out, 'monochrome.png'));
for (const [size, name] of [[32, '32x32.png'], [64, '64x64.png'], [128, '128x128.png'], [256, '128x128@2x.png'], [512, 'icon.png']]) {
  execFileSync('magick', [join(out, 'frosted.png'), '-resize', `${size}x${size}`, join(icons, name)]);
}
execFileSync('magick', [join(out, 'frosted.png'), '-resize', '1024x1024', join(root, 'desktop/appicon-source.png')]);
execFileSync('magick', [join(out, 'mark-frosted.png'), '-resize', '256x256', join(root, 'web/public/arslan-mark.png')]);
execFileSync('magick', [join(out, 'frosted.png'), '-resize', '32x32', join(root, 'web/public/favicon-32.png')]);
execFileSync('magick', [join(out, 'frosted.png'), '-resize', '180x180', join(root, 'web/public/apple-touch-icon.png')]);
execFileSync('magick', [join(out, 'frosted.png'), '-define', 'icon:auto-resize=256,128,64,48,32,16', join(icons, 'icon.ico')]);
if (process.platform === 'darwin') {
  const set = join(tmp, 'Arslan.iconset'); mkdirSync(set);
  for (const n of [16, 32, 128, 256, 512]) for (const scale of [1, 2]) {
    execFileSync('magick', [join(out, 'frosted.png'), '-resize', `${n * scale}x${n * scale}`, join(set, `icon_${n}x${n}${scale === 2 ? '@2x' : ''}.png`)]);
  }
  execFileSync('iconutil', ['-c', 'icns', set, '-o', join(icons, 'icon.icns')]);
}
rmSync(tmp, {recursive:true, force:true});
console.log(`Brand assets exported to ${out}`);
