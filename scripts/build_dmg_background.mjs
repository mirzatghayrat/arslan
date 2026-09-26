// Native vector artwork; export both Finder point sizes for Retina displays.
import {createRequire} from 'node:module';
import {readFileSync, writeFileSync} from 'node:fs';
import {dirname, resolve, join} from 'node:path';
import {fileURLToPath} from 'node:url';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const {Resvg} = createRequire(join(root, 'web/package.json'))('@resvg/resvg-js');
const dir = join(root, 'packaging/dmg');
const svg = readFileSync(join(dir, 'background.svg'));
for (const scale of [1, 2]) {
 const result = new Resvg(svg, {fitTo: {mode: 'width', value: 720 * scale}, font: {loadSystemFonts: true}});
 writeFileSync(join(dir, `background${scale === 2 ? '@2x' : ''}.png`), result.render().asPng());
}
