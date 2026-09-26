// Run against installed Playwright/WebKit, without real user data or network.
// node scripts/artwork_layout_smoke.cjs /path/to/playwright /path/to/evidence
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const { webkit } = require(path.resolve(process.argv[2]));
const output = path.resolve(process.argv[3]);
const root = path.resolve(__dirname, '..');
fs.mkdirSync(output, { recursive: true });
const server = http.createServer((req, res) => {
  const video = req.url === '/arslan-splash.mp4';
  if (!video && req.url !== '/') { res.writeHead(404); return res.end(); }
  res.setHeader('Content-Type', video ? 'video/mp4' : 'text/html');
  res.end(fs.readFileSync(path.join(root, 'desktop/splash', video ? 'arslan-splash.mp4' : 'index.html')));
});
const alpha = file => execFileSync('magick', [file, '-format', '%[fx:p{0,0}.a],%[fx:p{w-1,0}.a],%[fx:p{0,h-1}.a],%[fx:p{w-1,h-1}.a],%[fx:p{w/2,h/2}.a]', 'info:'], { encoding: 'utf8' }).trim();
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await webkit.launch();
  try {
    const origin = `http://127.0.0.1:${server.address().port}`;
    const page = await browser.newPage({ viewport: { width: 1280, height: 840 } });
    await page.route('**/*', route => (route.request().url().startsWith(origin + '/') || route.request().url().startsWith('blob:' + origin + '/')) ? route.continue() : route.abort());
    await page.goto(origin);
    await page.waitForFunction(() => document.querySelector('video').readyState >= 2);
    await page.evaluate(() => { const video = document.querySelector('video'); video.pause(); video.currentTime = 1.5; });
    await page.waitForFunction(() => !document.querySelector('video').seeking);
    const results = [];
    for (const state of ['video', 'failure', 'fade']) {
      if (state === 'failure') await page.evaluate(() => window.__arslanBootError('Synthetic startup failure'));
      if (state === 'fade') await page.evaluate(() => window.__arslanFadeOut());
      const screenshot = path.join(output, `splash-${state}.png`);
      await page.screenshot({ path: screenshot, omitBackground: true });
      const pixels = alpha(screenshot);
      // Regression: body background propagation used to return 1,1,1,1,1.
      assert.equal(pixels, '0,0,0,0,1', `Opaque splash corners in ${state}: ${pixels}`);
      results.push({ state, pixels, screenshot });
    }
    for (const asset of ['brand/frosted.png', 'brand/monochrome.png', 'arslan-mark.png']) {
      const pixels = alpha(path.join(root, 'web/public', asset)).split(',').map(Number);
      assert.deepEqual(pixels.slice(0, 4), [0, 0, 0, 0], asset);
      assert(pixels[4] > 0.95, `${asset}: missing artwork at center`);
    }
    fs.writeFileSync(path.join(output, 'splash-results.json'), JSON.stringify(results, null, 2));
    console.log('WebKit: video, failure and fade all have transparent corners and an opaque center; icon alpha verified.');
  } finally { await browser.close(); server.close(); }
})().catch(error => { server.close(); console.error(error); process.exitCode = 1; });
