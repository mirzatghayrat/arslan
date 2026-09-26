// Whole production app + real isolated settings/browser APIs. No browser setup.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const runtime=fs.realpathSync(process.argv[2]),output=fs.realpathSync(process.argv[3]),origin=process.argv[4];
if(!/^\/(private\/)?tmp\/arslan-reader-runtime\.[A-Za-z0-9]+$/.test(runtime))throw new Error('Isolated runtime required');
if(!/^\/(private\/)?tmp\/arslan-companion-ui-dock\.[A-Za-z0-9]+\/screens$/.test(output))throw new Error('Isolated output required');
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(origin))throw new Error('Explicit loopback origin required');
const web=path.resolve(__dirname,'../web');
const {dockMessages}=require(path.join(web,'src/locales/dock.ts'));
const resources=Object.fromEntries(['en','zh','ja','es','de','fr'].map(locale=>[locale,require(path.join(web,`src/locales/${locale}.json`))]));
const {chromium}=require(path.join(runtime,'node_modules/playwright'));
const metadata=require(path.join(runtime,'node_modules/playwright-core/browsers.json'));
const revision=metadata.browsers.find(item=>item.name==='chromium-headless-shell').revision;
const directory=path.join(runtime,'browsers',`chromium_headless_shell-${revision}`);
const binary=fs.readdirSync(directory,{recursive:true}).find(name=>name.endsWith('/chrome-headless-shell'));
(async()=>{
 const configs=await(await fetch(origin+'/api/v1/settings/provider-configs')).json();
 assert(configs.length===1 && configs[0].label==='Offline synthetic adapter' && configs[0].model==='offline-test','Synthetic harness required');
 assert.equal((await(await fetch(origin+'/api/v1/browser/status')).json()).ready,false,'Do not launch or configure a browser in this matrix');
 const browser=await chromium.launch({executablePath:path.join(directory,binary),chromiumSandbox:true,headless:true});
 const results=[];
 try{
  for(const width of [1100,600,360])for(const theme of ['light','dark'])for(const locale of Object.keys(resources)){
   assert((await fetch(origin+'/api/v1/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({language:locale})})).ok);
   const context=await browser.newContext({viewport:{width,height:800},serviceWorkers:'block',acceptDownloads:false,permissions:[],locale,colorScheme:theme});
   await context.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());
   const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
   await page.goto(origin);
   await page.getByRole('button',{name:resources[locale].nav.settings,exact:true}).click();
   await page.getByRole('button',{name:resources[locale].settings.navAppearance,exact:true}).click();
   await page.getByRole('radio',{name:resources[locale].settings[theme==='light'?'modeLight':'modeDark'],exact:true}).click();
   await page.getByRole('button',{name:resources[locale].settings.backToWorkspace,exact:true}).click();
   const opener=page.getByTestId('browser-indicator');await opener.click();
   const dock=page.locator('aside:has(> [role="tablist"])');await dock.waitFor();
   await dock.locator(':scope > header button').first().click();
   await dock.getByRole('textbox',{name:resources[locale].browser.url}).fill('https://fixture.invalid/page');
   const refusal=page.waitForResponse(response=>response.url()===origin+'/api/v1/browser/sessions' && response.request().method()==='POST');
   await dock.getByRole('button',{name:resources[locale].browser.open,exact:true}).click();
   const response=await refusal;assert.equal(response.status(),409);
   assert.equal((await response.json()).detail.code,'browser.setup_required');
   const alert=dock.getByRole('alert');await alert.waitFor();
   assert.equal(await alert.innerText(),dockMessages[locale].setupRequired);
   assert.equal(await dock.getAttribute('aria-label'),dockMessages[locale].title);
   assert.equal(await dock.locator(':scope > header button').first().getAttribute('aria-label'),dockMessages[locale].newBrowser);
   await page.evaluate(()=>document.fonts.ready);
   const dimensions=await dock.evaluate(node=>({left:node.getBoundingClientRect().left,right:node.getBoundingClientRect().right,
    width:node.getBoundingClientRect().width,client:node.clientWidth,scroll:node.scrollWidth,page:document.documentElement.scrollWidth}));
   await page.screenshot({path:path.join(output,`${locale}-${width}-${theme}.png`)});
   assert(dimensions.right<=width+1 && dimensions.page<=width+1 && dimensions.scroll<=dimensions.client+1,JSON.stringify({locale,width,dimensions}));
   if(width<768)assert(dimensions.left<1 && dimensions.width>=width-1,'Whole-app narrow overlay must reach both edges');
   assert.equal(await page.evaluate(()=>document.documentElement.classList.contains('dark')),theme==='dark');
   assert.equal(errors.length,0,errors.join('\n'));
   if(width<768){await dock.locator(':scope > header button').first().focus();await page.keyboard.press('Escape');}
   else await dock.locator(':scope > header button').last().click();
   await dock.waitFor({state:'detached'});
   if(width<768)assert(await opener.evaluate(node=>document.activeElement===node),'Restore focus to real opener');
   results.push({locale,width,theme,setup_refusal:true,overlay_bounds:true,focus_restored:width<768});
   await context.close();
  }
 }finally{await browser.close()}
 console.log(JSON.stringify({syntheticModel:true,realSettingsAndBrowserAPI:true,externalNavigation:false,desktopValidation:false,results}));
})().catch(error=>{console.error(error);process.exitCode=1});
