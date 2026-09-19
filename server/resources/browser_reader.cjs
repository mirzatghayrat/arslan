// Fixed host program, never a user-supplied script or application webview.
// Remote pages receive no Tauri bridge, browser debugging port, host callbacks,
// credentials, existing profile, clipboard, file chooser, or upload capability.
const readline = require('node:readline');
const { chromium } = require(process.argv[2]);
const { validUrl, installPolicy } = require('./browser_reader_policy.cjs');

(async () => {
  const browser = await chromium.launch({ executablePath: process.argv[3], headless: true,
    chromiumSandbox: true, proxy: { server: process.argv[4], bypass: '<-loopback>' },
    args: ['--disable-quic', '--disable-extensions', '--disable-sync', '--disable-background-networking',
      '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1',
      '--force-webrtc-ip-handling-policy=disable_non_proxied_udp'] });
  const context = await browser.newContext({ acceptDownloads: false, ignoreHTTPSErrors: false,
    serviceWorkers: 'block', permissions: [], viewport: { width: 1000, height: 700 } });
  process.once('SIGTERM', async () => { await browser.close().catch(() => {}); process.exit(0); });
  await installPolicy(context);
  const page = await context.newPage();
  page.setDefaultTimeout(5000);
  page.setDefaultNavigationTimeout(15000);
  page.on('popup', popup => popup.close().catch(() => {}));
  page.on('dialog', dialog => dialog.dismiss().catch(() => {}));
  page.on('download', download => download.cancel().catch(() => {}));
  page.on('filechooser', () => {}); // No file input is ever filled.
  let revision = 0;
  let frameValid = false;
  let links = [];
  let history = [];
  let historyIndex = -1;
  const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
  process.stdout.write(JSON.stringify({ ready: true }) + '\n');
  for await (const line of input) {
    try {
      const request = JSON.parse(line);
      let target;
      let nextHistoryIndex = historyIndex;
      if (request.action === 'navigate') target = request.url;
      else if (request.action === 'link') {
        if (!frameValid || request.revision !== revision) throw new Error('browser.stale_view');
        target = links.find(link => link.id === request.link_id)?.url;
      } else if (request.action === 'back' || request.action === 'forward') {
        const next = historyIndex + (request.action === 'back' ? -1 : 1);
        if (next < 0 || next >= history.length) throw new Error('browser.history_unavailable');
        nextHistoryIndex = next;
        target = history[next];
      } else if (request.action === 'scroll') {
        if (![-1, 1].includes(request.direction)) throw new Error('browser.invalid_request');
        frameValid = false;
        await page.mouse.wheel(0, request.direction * 560);
      } else if (request.action === 'refresh') {
        target = page.url();
      } else throw new Error('browser.action_not_supported');
      if (target !== undefined) {
        if (!validUrl(target)) throw new Error('browser.invalid_url');
        // From this point the page may change even if navigation or capture
        // later fails. Previously displayed link IDs must no longer authorize
        // a target from this new, unpublished document.
        frameValid = false;
        await page.goto(target, { waitUntil: 'domcontentloaded' });
      } else if (request.action === 'link') throw new Error('browser.stale_view');
      if (!validUrl(page.url())) throw new Error('browser.invalid_url');
      const candidates = await page.locator('a[href]').evaluateAll(nodes => nodes.slice(0, 200).map(node => ({
        label: (node.textContent || node.getAttribute('aria-label') || '').trim().slice(0, 200), url: node.href,
      })));
      const nextLinks = candidates.filter(link => validUrl(link.url)).slice(0, 100)
        .map((link, index) => ({ ...link, id: `link-${index}` }));
      const text = (await page.locator('body').innerText()).slice(0, 32000);
      const screenshot = await page.screenshot({ type: 'jpeg', quality: 70, timeout: 5000 });
      if (screenshot.length > 2_000_000) throw new Error('browser.frame_too_large');
      const title = (await page.title()).slice(0, 240);
      const scrollY = await page.evaluate(() => window.scrollY);
      const currentUrl = page.url();
      if (!validUrl(currentUrl)) throw new Error('browser.invalid_url');
      // Publish the history cursor and link map only after the whole frame is
      // available. Failed back/forward must not consume a history step. Refresh
      // after a partial navigation (or a redirect) records the actual location.
      if (request.action === 'navigate' || request.action === 'link'
          || currentUrl !== history[nextHistoryIndex]) {
        history = history.slice(0, nextHistoryIndex + 1);
        history.push(currentUrl);
        if (history.length > 100) history.shift();
        nextHistoryIndex = history.length - 1;
      }
      historyIndex = nextHistoryIndex;
      links = nextLinks;
      revision += 1;
      frameValid = true;
      process.stdout.write(JSON.stringify({ ok: true, revision, url: currentUrl,
        title, text, links, screenshot: screenshot.toString('base64'),
        can_back: historyIndex > 0, can_forward: historyIndex < history.length - 1,
        scroll_y: scrollY,
        mode: 'isolated_read_only', scripts: 'enabled', non_get_requests: 'blocked', credentials: 'unavailable' }) + '\n');
    } catch (error) {
      const code = typeof error?.message === 'string' && /^browser\.[a-z_]+$/.test(error.message)
        ? error.message : 'browser.navigation_failed';
      process.stdout.write(JSON.stringify({ ok: false, code }) + '\n');
    }
  }
  await browser.close();
})().catch(() => { process.stderr.write('browser.runtime_failed\n'); process.exitCode = 1; });
