// Actual Chromium, synthetic page; no public site or real account writes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { installPolicy, validUrl } = require('../server/resources/browser_reader_policy.cjs');
const root = fs.realpathSync(process.argv[2]);
if (!/^\/(private\/)?tmp\/arslan-reader-runtime\.[A-Za-z0-9]+$/.test(root)) throw new Error('Temporary runtime required');
const { chromium } = require(path.join(root, 'node_modules/playwright'));
const metadata = require(path.join(root, 'node_modules/playwright-core/browsers.json'));
const revision = metadata.browsers.find(item => item.name === 'chromium-headless-shell').revision;
const directory = path.join(root, 'browsers', `chromium_headless_shell-${revision}`);
const binary = fs.readdirSync(directory, { recursive: true }).find(name => name.endsWith('/chrome-headless-shell'));
(async () => {
  const browser = await chromium.launch({ executablePath: path.join(directory, binary), chromiumSandbox: true, headless: true,
    proxy: { server: 'http://127.0.0.1:1', bypass: '<-loopback>' } });
  try {
    const context = await browser.newContext({ serviceWorkers: 'block', acceptDownloads: false, permissions: [], viewport: { width: 1000, height: 700 } });
    await installPolicy(context);
    // Only this exact initial GET is fulfilled by the trusted fixture. All
    // script requests go through production policy and the dead-end proxy.
    await context.route('https://example.com/fixture', route => {
      if (route.request().method() !== 'GET') return route.abort();
      return route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>Fixture</title><body style="height:4000px">Synthetic page</body>' });
    });
    const page = await context.newPage();
    await page.goto('https://example.com/fixture');
    assert.equal(await page.evaluate(() => typeof window.__TAURI_INTERNALS__), 'undefined');
    assert.equal(await page.evaluate(() => typeof require), 'undefined');
    const denied = await page.evaluate(async () => {
      const outcome = {};
      for (const method of ['POST', 'PATCH', 'DELETE', 'PUT']) {
        try { await fetch('https://example.com/write', { method, body: 'synthetic-canary' }); outcome[method] = false; }
        catch { outcome[method] = true; }
      }
      return outcome;
    });
    assert.deepEqual(denied, { POST: true, PATCH: true, DELETE: true, PUT: true });
    const socketClosed = await page.evaluate(() => new Promise(resolve => {
      const ws = new WebSocket('wss://example.com/socket');
      ws.onclose = () => resolve(true); setTimeout(() => resolve(false), 1000);
    }));
    assert.equal(socketClosed, true);
    await page.mouse.wheel(0, 560);
    await page.waitForFunction(() => window.scrollY > 0);
    const scrollY = await page.evaluate(() => window.scrollY);
    assert(scrollY > 0);
    for (const url of ['file:///etc/passwd', 'http://127.0.0.1', 'https://user:pass@example.com', 'javascript:alert(1)']) assert.equal(validUrl(url), false);
    console.log(JSON.stringify({ real_browser: true, synthetic_page: true, writes: denied, websocket_closed: socketClosed,
      scroll_y: scrollY, app_bridge: 'absent', require: 'absent', public_network: 'not_used' }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
