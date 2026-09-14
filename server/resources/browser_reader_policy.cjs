// Shared fixed browser policy. No caller-supplied callbacks or JavaScript.
function validUrl(value) {
  if (typeof value !== 'string' || value.length > 4000 || /[\s\\]/.test(value)) return false;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !url.username && !url.password && (!url.port || url.port === '443');
  } catch { return false; }
}

async function installPolicy(context) {
  await context.route('**/*', async route => {
    const request = route.request();
    if (!validUrl(request.url()) || !['GET', 'HEAD'].includes(request.method())) return route.abort('blockedbyclient');
    return route.continue();
  });
  await context.routeWebSocket('**/*', socket => socket.close({ code: 1008, reason: 'Read-only browser' }));
}

module.exports = { validUrl, installPolicy };
