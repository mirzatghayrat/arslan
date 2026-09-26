// Deterministic renderer double for the actual browser_reader.cjs stdin/stdout
// program. No Chromium, network, application profile or credential is used.
const visits = new Map();
const captures = new Map();
let url = 'about:blank';
const page = {
  setDefaultTimeout() {}, setDefaultNavigationTimeout() {}, on() {},
  url: () => url,
  async goto(target) {
    url = target;
    const count = (visits.get(url) || 0) + 1;
    visits.set(url, count);
    if (url.includes('goto-fails') || (url.includes('history-fails-once') && count === 2)) {
      throw new Error('synthetic navigation failure');
    }
  },
  mouse: { async wheel() { if (url.includes('scroll-fails')) throw new Error('synthetic scroll failure'); } },
  locator(selector) {
    return selector === 'a[href]' ? {
      async evaluateAll() { return [{ label: `Link from ${url}`, url: `${url}/target` }]; },
    } : { async innerText() { return `Body at ${url}`; } };
  },
  async screenshot() {
    const count = (captures.get(url) || 0) + 1;
    captures.set(url, count);
    if (url.includes('capture-fails') && count === 1) throw new Error('synthetic capture failure');
    if (url.includes('oversize')) return Buffer.alloc(2_000_001);
    return Buffer.from('synthetic-image');
  },
  async title() {
    if (url.includes('title-fails')) throw new Error('synthetic title failure');
    return url;
  },
  async evaluate() { return 0; },
};
module.exports = { chromium: { async launch() {
  return { async close() {}, async newContext() {
    return { async route() {}, async routeWebSocket() {}, async newPage() { return page; } };
  } };
} } };
