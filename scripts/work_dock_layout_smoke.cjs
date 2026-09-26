// Production dock/reader/CSS in isolated Chromium; synthetic API and no network.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const runtime = fs.realpathSync(process.argv[2]);
const output = fs.realpathSync(process.argv[3]);
if (!/^\/(private\/)?tmp\/arslan-reader-runtime\.[A-Za-z0-9]+$/.test(runtime)) throw new Error('Isolated runtime required');
if (!/^\/(private\/)?tmp\/arslan-dock-layout\.[A-Za-z0-9]+$/.test(output)) throw new Error('Isolated output required');
const web = path.resolve(__dirname, '../web');
const { chromium } = require(path.join(runtime, 'node_modules/playwright'));
const { build } = require(path.join(web, 'node_modules/esbuild'));
const metadata = require(path.join(runtime, 'node_modules/playwright-core/browsers.json'));
const revision = metadata.browsers.find(item => item.name === 'chromium-headless-shell').revision;
const directory = path.join(runtime, 'browsers', `chromium_headless_shell-${revision}`);
const binary = fs.readdirSync(directory, { recursive: true }).find(name => name.endsWith('/chrome-headless-shell'));
const assets = path.join(web, 'dist/assets');
const css = fs.readdirSync(assets).filter(name => name.endsWith('.css')).map(name => fs.readFileSync(path.join(assets, name), 'utf8')).join('\n');
const source = `
import React, {useState} from 'react';
import {createRoot} from 'react-dom/client';
import i18n from './src/i18n';
import WorkDock from './src/components/WorkDock';
import {browserApi} from './src/api/browser';
const [locale,theme] = location.pathname.slice(1).split('/');
document.documentElement.classList.toggle('dark', theme === 'dark');
window.calls=[];
browserApi.createReader=async()=>({session_id:'synthetic-session'});
browserApi.closeReader=async(id)=>{window.calls.push({close:id})};
browserApi.readerAction=async(id,action)=>{
 window.calls.push(action);
 return {session_id:id,conversation_id:'fixture',task_id:null,revision:window.calls.length,
 title:'Synthetic browser title',url:'https://fixture.invalid/page',text:'Synthetic source text. '+ 'long-source-token'.repeat(30),
 screenshot:'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jXX0AAAAASUVORK5CYII=',
 links:[{id:'link-1',label:'Synthetic link',url:'https://fixture.invalid/'+ 'long-path'.repeat(30)}],
 can_back:true,can_forward:true,blocked_connections:0,mode:'isolated_read_only'};
};
function App(){const[open,setOpen]=useState(true);return <div className='flex h-screen w-screen overflow-hidden bg-background text-foreground'>
 <main data-main className='min-w-0 flex-1 p-4'>Synthetic conversation</main>
 <WorkDock open={open} onOpen={()=>setOpen(true)} onClose={()=>setOpen(false)} conversationId='fixture' taskId={null} temporary={false}/>
 </div>}
i18n.changeLanguage(locale).then(()=>{
 window.labels=Object.fromEntries(['dock.newBrowser','dock.close','dock.closeTab','dock.pageText','dock.links','dock.scrollDown','browser.url','browser.open'].map(k=>[k,i18n.t(k,{count:1})]));
 createRoot(document.getElementById('root')).render(<App/>);
});
`;
(async()=>{
 const bundle=await build({stdin:{contents:source,loader:'tsx',resolveDir:web},absWorkingDir:web,bundle:true,write:false,
  format:'iife',platform:'browser',jsx:'automatic',define:{'import.meta.env.VITE_API_BASE':'""','process.env.NODE_ENV':'"production"'}});
 const html=`<!doctype html><html><head><meta charset="utf-8"><style>${css}</style></head><body><div id="root"></div><script>${bundle.outputFiles[0].text.replace(/<\/script/gi,'<\\/script')}</script></body></html>`;
 const browser=await chromium.launch({executablePath:path.join(directory,binary),headless:true,chromiumSandbox:true,
  proxy:{server:'http://127.0.0.1:1',bypass:'<-loopback>'}});
 const results=[];
 try{
  for(const width of [1100,600,360]) for(const theme of ['light','dark']) for(const locale of ['en','zh','ja','es','de','fr']){
   const context=await browser.newContext({viewport:{width,height:720},serviceWorkers:'block',acceptDownloads:false,permissions:[],locale,colorScheme:theme});
   const url=`https://dock-fixture.invalid/${locale}/${theme}`;
   await context.route('**/*',route=>route.request().url()===url && route.request().method()==='GET'
    ?route.fulfill({contentType:'text/html',body:html}):route.abort());
   const page=await context.newPage();const errors=[];page.on('pageerror',error=>errors.push(error.message));
   await page.goto(url);await page.locator('aside').waitFor();
   const labels=await page.evaluate(()=>window.labels);
   await page.getByRole('button',{name:labels['dock.newBrowser'],exact:true}).first().click();
   await page.getByRole('textbox',{name:labels['browser.url']}).fill('https://fixture.invalid/page');
   await page.getByRole('button',{name:labels['browser.open'],exact:true}).click();
   await page.getByRole('tab',{name:'Synthetic browser title'}).waitFor();
   await page.getByText(labels['dock.links'],{exact:true}).click();
   await page.getByText(labels['dock.pageText'],{exact:true}).click();
   await page.locator('pre').evaluate(node=>node.scrollIntoView({block:'end'}));
   await page.evaluate(()=>document.fonts.ready);
   const dimensions=await page.locator('aside').evaluate(node=>({width:node.getBoundingClientRect().width,
    left:node.getBoundingClientRect().left,right:node.getBoundingClientRect().right,client:node.clientWidth,scroll:node.scrollWidth,
    page:document.documentElement.scrollWidth,reader:node.querySelector('[role="tabpanel"]')?.getBoundingClientRect().height}));
   const screenshot=path.join(output,`${locale}-${width}-${theme}.png`);await page.screenshot({path:screenshot});
   assert.equal(errors.length,0,errors.join('\n'));
   assert(dimensions.page<=width && dimensions.right<=width+1,`Page overflow ${locale}/${width}`);
   assert(dimensions.scroll<=dimensions.client+1,`Dock overflow ${locale}/${width}`);
   if(width<768) assert(dimensions.left<1 && dimensions.width>=width-1,`Narrow dock must leave usable full-width content: ${locale}/${width}, got ${JSON.stringify(dimensions)}`);
   assert(dimensions.reader>180,`Reader area too short ${locale}/${width}`);
   const endVisible=await page.locator('pre').evaluate(node=>node.getBoundingClientRect().bottom<=node.closest('aside').querySelector('footer').getBoundingClientRect().top+1);
   assert(endVisible,`Source text end hidden behind footer ${locale}/${width}`);
   await page.getByRole('button',{name:labels['dock.scrollDown'],exact:true}).click();
   await page.getByRole('button',{name:labels['dock.newBrowser'],exact:true}).click();
   const tabs=page.getByRole('tab');await tabs.nth(1).focus();await page.keyboard.press('ArrowLeft');
   assert.equal(await tabs.nth(0).getAttribute('aria-selected'),'true');
   if(width<768){
    assert.equal(await page.locator('aside').getAttribute('aria-modal'),'true');
    await page.locator('aside header button').first().focus();await page.keyboard.press('Shift+Tab');
    assert(await page.locator('aside footer button').evaluate(node=>document.activeElement===node));
   }
   if(width<768 && theme==='dark') await page.keyboard.press('Escape');
   else await page.getByRole('button',{name:labels['dock.close'],exact:true}).click();
   await page.locator('aside').waitFor({state:'detached'});
   assert(await page.locator('[data-main]').isVisible());
   assert((await page.evaluate(()=>window.calls)).some(item=>item.action==='scroll'));
   results.push({locale,width,theme,screenshot});await context.close();
  }
 }finally{await browser.close()}
 console.log(JSON.stringify({synthetic_only:true,network:'blocked',packaged_validation:false,results}));
})().catch(error=>{console.error(error);process.exitCode=1});
