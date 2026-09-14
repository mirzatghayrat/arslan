// Real headless Chromium + production component/CSS; synthetic API responses.
// No existing browser profile, app installation, downloads or external network.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = fs.realpathSync(process.argv[2]);
const output = fs.realpathSync(process.argv[3]);
if (!/^\/(private\/)?tmp\/arslan-reader-runtime\.[A-Za-z0-9]+$/.test(root)) throw new Error('Isolated runtime required');
if (!/^\/(private\/)?tmp\/arslan-memory-layout\.[A-Za-z0-9]+$/.test(output)) throw new Error('Isolated output required');
const web = path.resolve(__dirname, '../web');
const { chromium } = require(path.join(root, 'node_modules/playwright'));
const { build } = require(path.join(web, 'node_modules/esbuild'));
const metadata = require(path.join(root, 'node_modules/playwright-core/browsers.json'));
const revision = metadata.browsers.find(item => item.name === 'chromium-headless-shell').revision;
const directory = path.join(root, 'browsers', `chromium_headless_shell-${revision}`);
const binary = fs.readdirSync(directory, { recursive: true }).find(name => name.endsWith('/chrome-headless-shell'));
const assets = path.join(web, 'dist/assets');
const css = fs.readdirSync(assets).filter(name => name.endsWith('.css')).map(name => fs.readFileSync(path.join(assets, name), 'utf8')).join('\n');
const source = `
import React from 'react';
import { createRoot } from 'react-dom/client';
import { createInstance } from 'i18next';
import { initReactI18next, I18nextProvider } from 'react-i18next';
import MemoryEvidence from './src/components/companion/MemoryEvidence';
import CompanionDialog from './src/components/companion/CompanionDialog';
import { companionApi } from './src/api/companion';
import { companionMessages } from './src/locales/companion';
import { memoryEvidenceMessages } from './src/locales/memoryEvidence';
const locale = location.pathname.slice(1);
const language = createInstance();
companionApi.contextReceipts = async () => [{id:'fixture',created_at:'2026-01-01T10:00:00Z',receipt:{
 id:'fixture',task_id:'fixture-task',run_id:'run:1',memory_mode:'normal',used:[{id:'memory',kind:'memory',revision:1}],
 filter_reasons:['irrelevant','permission','budget'],estimated_tokens:1200,cloud_use:'approved',local_only_used:false}}];
companionApi.contextMemory = async () => ({id:'memory',recorded_version:1,current_version:2,entry_status:'active',
 status:'available',content:'Synthetic historical preference — no real personal information. '.repeat(8)});
async function start(){
 await language.use(initReactI18next).init({lng:locale,fallbackLng:false,resources:{[locale]:{translation:{
  companion:companionMessages[locale],memoryEvidence:memoryEvidenceMessages[locale]}}},interpolation:{escapeValue:false}});
 createRoot(document.getElementById('root')).render(<I18nextProvider i18n={language}>
 <CompanionDialog title={memoryEvidenceMessages[locale].title} onClose={()=>{}}>
 <MemoryEvidence conversationId='fixture-conversation' taskId='fixture-task'/>
 </CompanionDialog></I18nextProvider>);
}
start().catch(error=>{setTimeout(()=>{throw error})});
`;
(async () => {
  const bundle = await build({ stdin: { contents: source, loader: 'tsx', resolveDir: web }, absWorkingDir: web,
    bundle: true, write: false, format: 'iife', platform: 'browser', jsx: 'automatic',
    define: { 'import.meta.env.VITE_API_BASE': '""', 'process.env.NODE_ENV': '"production"' } });
  const html = `<!doctype html><html><head><meta charset="utf-8"><style>${css}</style></head><body><div id="root"></div><script>${bundle.outputFiles[0].text.replace(/<\/script/gi, '<\\/script')}</script></body></html>`;
  const browser = await chromium.launch({ executablePath: path.join(directory, binary), chromiumSandbox: true, headless: true,
    proxy: { server: 'http://127.0.0.1:1', bypass: '<-loopback>' } });
  const results = [];
  try {
    for (const width of [900, 480]) for (const locale of ['en', 'zh', 'ja', 'es', 'de', 'fr']) {
      const context = await browser.newContext({ serviceWorkers: 'block', acceptDownloads: false, permissions: [],
        viewport: { width, height: 720 }, locale, colorScheme: 'light' });
      await context.route('**/*', route => route.request().url() === `https://memory-fixture.invalid/${locale}`
        && route.request().method() === 'GET' ? route.fulfill({ contentType: 'text/html', body: html }) : route.abort());
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(`https://memory-fixture.invalid/${locale}`);
      await page.locator('section').getByRole('button').first().click();
      await page.locator('[data-receipt-id="fixture"]').getByRole('button').click();
      await page.getByText(/^Synthetic historical preference/).waitFor();
      await page.evaluate(() => document.fonts.ready);
      const dimensions = await page.getByRole('dialog').evaluate(node => ({
        client: node.clientWidth, scroll: node.scrollWidth, height: node.clientHeight,
        scrollHeight: node.scrollHeight, text: node.textContent,
        pageWidth: document.documentElement.scrollWidth,
      }));
      assert.equal(errors.length, 0, errors.join('\n'));
      assert(dimensions.scroll <= dimensions.client + 1, `Dialog overflow ${locale}/${width}`);
      assert(dimensions.pageWidth <= width, `Page overflow ${locale}/${width}`);
      assert(!dimensions.text.includes('memoryEvidence.'), 'Untranslated key');
      const screenshot = path.join(output, `${locale}-${width}.png`);
      await page.screenshot({ path: screenshot });
      await page.getByRole('dialog').evaluate(node => { node.scrollTop = node.scrollHeight; });
      const endVisible = await page.getByText(/^Synthetic historical preference/).evaluate(node => {
        const dialog = node.closest('[role="dialog"]').getBoundingClientRect();
        return node.getBoundingClientRect().bottom <= dialog.bottom;
      });
      assert(endVisible, `Historical text end unreachable ${locale}/${width}`);
      results.push({ locale, width, horizontal_overflow: false, dialog_scrollable: dimensions.scrollHeight > dimensions.height, screenshot });
      await context.close();
    }
  } finally { await browser.close(); }
  console.log(JSON.stringify({ synthetic_only: true, network: 'blocked', desktop_validation: false, results }));
})().catch(error => { console.error(error); process.exitCode = 1; });
