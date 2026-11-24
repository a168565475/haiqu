/** 生产 Dashboard：已有 Session 或普通 CSRF 登录，真实 API，业务只读，headless。 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('../src/frontend/node_modules/playwright-core');
const root = path.resolve(__dirname, '..');
const evidence = path.join(root, 'docs/designs/production_dashboards_20261017');
const runtime = path.join(root, 'qa/_tmp/production-dashboard-readonly-runtime-20261017');
const base = new URL(process.env.PRODUCTION_DASHBOARD_QA_BASE_URL || 'http://localhost:8080');
const apiPath = '/api/v1/production-dashboard/';
const stamp = new Date().toISOString().replace(/[:.]/g, '-') + '-' + process.pid;
const reportPath = path.join(evidence, 'implementation-' + stamp + '.json');
const routes = [
  { key:'owner',path:'/workbench/production',title:'生产负责人' },
  { key:'executive',path:'/workbench/production-overview',title:'生产总览' },
  { key:'workshop',path:'/workbench/workshop',title:'车间' },
];
const report = { startedAt:new Date().toISOString(),status:'RUNNING',mode:'real-api-read-only',checks:[],unknown:[],apiReads:[],apiSummaries:[],blockedWrites:[],errors:[],pages:[],screenshots:[],resources:{runtime,created:false,browserClosed:false,removed:false,verifiedAbsent:false} };
const pending = new Set();
let browser, context, page, ownsRuntime = false, stage = 'preconditions', cfg, lastPayload;
const digest = value => crypto.createHash('sha256').update(String(value)).digest('hex').slice(0,16);
const samePath = (a,b) => path.resolve(a).toLowerCase() === path.resolve(b).toLowerCase();
const safePath = value => new URL(value,base).pathname.replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/gi,':id');
const safeError = error => ({name:error.name,digest:digest(error.message),timeout:/timeout/i.test(error.message)});
function requireValue(value,message,blocked=false) { if(!value)throw Object.assign(new Error(message),{safe:true,blocked}); }
function check(id,passed,detail) { report.checks.push({route:cfg?.key,stage,id,passed:!!passed,...(detail===undefined?{}:{detail})}); }
function unknown(id,reason) { report.unknown.push({route:cfg?.key,stage,id,reason}); }
function save() { fs.writeFileSync(reportPath,JSON.stringify(report,null,2)); }
function authConfig(restricted=false) {
  return restricted ? { state:process.env.QA_RESTRICTED_STORAGE_STATE } : {
    state:process.env.PRODUCTION_DASHBOARD_QA_STORAGE_STATE || process.env.QA_STORAGE_STATE,
    username:process.env.PRODUCTION_DASHBOARD_QA_USERNAME || process.env.QA_USERNAME,
    password:process.env.PRODUCTION_DASHBOARD_QA_PASSWORD || process.env.QA_PASSWORD,
  };
}
async function get(ctx,relative,label) {
  const url=new URL(relative,base);requireValue(url.origin===base.origin,'拒绝跨来源API请求。');
  const response=await ctx.request.get(url.href,{maxRedirects:0});report.apiReads.push({stage,label,path:safePath(url.href),status:response.status()});return response;
}
async function readJson(response) { try{return await response.json();}catch{throw Object.assign(new Error('API未返回有效JSON。'),{safe:true});} }
async function authenticate(ctx,auth) {
  const response=await get(ctx,'/api/auth/me/','authentication');requireValue(response.status()===200,'认证状态接口不可用。',true);
  let me=await readJson(response);
  if(!me.authenticated && auth.state)throw Object.assign(new Error('提供的已有Session已失效。'),{safe:true,blocked:true});
  if(!me.authenticated) {
    requireValue(auth.username&&auth.password,'缺少已授权的真实测试账号或有效Session。',true);
    const csrf=(await ctx.cookies(base.origin)).find(c=>c.name==='csrftoken')?.value;requireValue(csrf,'正常登录前未取得CSRF Cookie。',true);
    const login=await ctx.request.post(new URL('/api/auth/login/',base).href,{data:{username:auth.username,password:auth.password},headers:{'X-CSRFToken':csrf,Referer:base.origin+'/'},maxRedirects:0});
    report.authentication={method:'normal-session-csrf-login',status:login.status()};requireValue(login.status()===200,'已授权测试账号正常登录失败。',true);
    me=await readJson(await get(ctx,'/api/auth/me/','authenticated-state'));
  } else report.authentication={method:'existing-session'};
  requireValue(me.authenticated===true,'没有可用真实登录态。',true);
}
async function newContext(auth={}) {
  const storageState=auth.state ? JSON.parse(fs.readFileSync(path.resolve(auth.state),'utf8')) : undefined;
  const ctx=await browser.newContext({storageState,viewport:{width:1920,height:1080},deviceScaleFactor:1,locale:'zh-CN',timezoneId:'Asia/Shanghai',serviceWorkers:'block',acceptDownloads:false});
  await ctx.addInitScript(()=>localStorage.setItem('haiqu:theme:v2','blue-gray'));
  await ctx.route('**/*',async route=>{
    const request=route.request();if(!['GET','HEAD','OPTIONS'].includes(request.method())){report.blockedWrites.push({stage,path:safePath(request.url()),method:request.method()});await route.abort('blockedbyclient');return;}
    await route.continue();
  });
  await ctx.routeWebSocket('**/*',socket=>socket.close());return ctx;
}
function summarize(payload) {
  const data=payload.data || payload;
  return {generated_at:data.generated_at,filters:data.filters,read_only:payload.meta?.read_only??data.meta?.read_only,sections:Object.fromEntries(Object.entries(data.sections||{}).map(([key,value])=>[key,{state:value.state,dataNull:value.data===null,reasonPresent:typeof value.reason==='string'&&value.reason.length>0,dataKeys:value.data&&typeof value.data==='object'?Object.keys(value.data):[],arrayLengths:value.data&&typeof value.data==='object'?Object.fromEntries(Object.entries(value.data).filter(([,v])=>Array.isArray(v)).map(([k,v])=>[k,v.length])):{}}]))};
}
function apiContracts(payload,label) {
  const summary=summarize(payload);report.apiSummaries.push({stage,label,...summary});
  check(label+'-read-only-contract',summary.read_only===true);
  check(label+'-generated-at',Number.isFinite(Date.parse(summary.generated_at)));
  check(label+'-five-explicit-sections',['tasks','outsourcing','receipts','workshop','reports'].every(k=>summary.sections[k]));
  for(const [key,section] of Object.entries(summary.sections)) {
    check(label+'-'+key+'-state',['READY','EMPTY','FORBIDDEN','UNKNOWN'].includes(section.state));
    if(['FORBIDDEN','UNKNOWN'].includes(section.state)) {
      check(label+'-'+key+'-not-fake-zero',section.dataNull&&section.reasonPresent);
      unknown(label+'-'+key,section.state==='FORBIDDEN'?'当前账号无该节权限；未伪造零值。':'当前真实数据/口径不可用，保留接口UNKNOWN。');
    }
  }
  const tasks=payload.data?.sections.tasks?.data;
  if(tasks) {
    check(label+'-natural-day-series',tasks.due_series.length===payload.data.filters.days);
    check(label+'-bounded-task-page',tasks.items.length<=20&&tasks.total>=tasks.items.length);
    check(label+'-task-progress-keeps-unknown',tasks.items.every(task=>Object.values(task.stages).every(value=>value.state==='READY'?Number.isFinite(value.percent)&&value.percent>=0&&value.percent<=100:value.percent===null)));
  }
  const receipts=payload.data?.sections.receipts?.data;
  if(receipts?.pending_state==='FORBIDDEN')check(label+'-receipt-gap-no-task-leak',receipts.pending_products.length===0);
  if(receipts?.pending_state==='UNKNOWN')unknown(label+'-receipt-gap-unit','真实入库差额存在单位口径待核实项；不将UNKNOWN当成零。');
}
function observe(target) {
  target.setDefaultTimeout(15000);target.setDefaultNavigationTimeout(60000);
  target.on('request',request=>{if(new URL(request.url()).pathname.startsWith('/api/'))pending.add(request);});
  target.on('requestfinished',request=>pending.delete(request));target.on('requestfailed',request=>pending.delete(request));
  target.on('pageerror',error=>report.errors.push({stage,...safeError(error)}));
  target.on('response',response=>{
    const pathname=safePath(response.url());
    if(response.status()>=400)report.errors.push({stage,path:pathname,status:response.status()});
    if(new URL(response.url()).pathname===apiPath){const work=response.json().then(payload=>{lastPayload=payload;report.apiReads.push({stage,label:'page-dashboard',path:apiPath,status:response.status()});}).catch(error=>report.errors.push({stage,...safeError(error)})).finally(()=>pending.delete(work));pending.add(work);}
  });
}
async function settle() {
  await page.waitForFunction(()=>document.querySelector('[data-testid="production-dashboard"]')||location.pathname==='/login',null,{timeout:60000});
  requireValue(new URL(page.url()).pathname===cfg.path,'目标页面未保持已登录路由：'+cfg.key,true);
  await page.waitForFunction(()=>{const el=document.querySelector('[data-testid="production-dashboard"]');return el&&el.dataset.state!=='loading'&&el.getAttribute('aria-busy')!=='true';},null,{timeout:30000});
  const end=Date.now()+30000;while(pending.size&&Date.now()<end)await page.waitForTimeout(100);requireValue(!pending.size,'真实API读取超时。');
  await page.evaluate(()=>document.fonts.ready);await page.waitForTimeout(350);
}
async function screenshot(label) { const file='implementation-'+stamp+'-'+cfg.key+'-'+label+'.png';await page.screenshot({path:path.join(evidence,file)});report.screenshots.push(file); }
async function measure() {
  return page.evaluate(()=>{
    const root=document.querySelector('[data-testid="production-dashboard"]');
    const box=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return {x:r.x,y:r.y,width:r.width,height:r.height,clientWidth:el.clientWidth,scrollWidth:el.scrollWidth,clientHeight:el.clientHeight,scrollHeight:el.scrollHeight,font:s.fontSize,line:s.lineHeight,opacity:s.opacity,color:s.color,bg:s.backgroundColor,radius:s.borderRadius,backdrop:s.backdropFilter,border:['Top','Right','Bottom','Left'].map(side=>s['border'+side+'Width'])};};
    const visible=el=>el.getBoundingClientRect().width>0&&el.getBoundingClientRect().height>0;
    const cards=[...root.querySelectorAll('.pd-glass')].filter(visible);
    return {role:root.dataset.role,state:root.dataset.state,root:box(root),document:box(document.documentElement),shell:document.querySelector('.erp-layout__main')?box(document.querySelector('.erp-layout__main')):null,heading:[...root.querySelectorAll('h1')].map(box),cards:cards.map(box),demoLabel:/演示数据|模拟数据|设计占位|示意数据/.test(root.textContent),buttons:[...root.querySelectorAll('button')].filter(visible).map(el=>{const r=el.getBoundingClientRect(),x=r.x+r.width/2,y=r.y+r.height/2;return {disabled:el.disabled,inViewport:x>=0&&x<innerWidth&&y>=0&&y<innerHeight,hit:el.contains(document.elementFromPoint(x,y)),height:r.height};}),links:[...root.querySelectorAll('a[href]')].map(el=>({href:el.getAttribute('href')}))};
  });
}
function layoutContracts(m) {
  check('correct-role',m.role===cfg.key,{actual:m.role});check('no-demo-label',!m.demoLabel);
  check('loaded-real-page',!['loading','error'].includes(m.state),{state:m.state});
  check('no-extra-horizontal-scroll',[m.document,m.root,m.shell].filter(Boolean).every(b=>b.scrollWidth<=b.clientWidth+1));
  check('visible-buttons-receive-pointer',m.buttons.filter(b=>b.inViewport).every(b=>b.hit));
  check('metric-glass-style',m.cards.length>0&&m.cards.every(c=>c.radius==='16px'&&c.backdrop.includes('blur(28px)')&&c.backdrop.includes('saturate(1.4)')&&c.border.every(v=>v==='1px')&&c.opacity==='1'),m.cards);
  if(['forbidden','empty','stale'].includes(m.state))unknown('page-'+m.state,'真实页面处于'+m.state+'；非空完整交互不能据此推定通过。');
}
async function choose(label,value) {
  const control=page.getByLabel(label,{exact:true}).first();
  if(!await control.count()){unknown('filter-'+label,'当前实现未找到该筛选控件。');return false;}
  if(await control.evaluate(el=>el.tagName)==='SELECT')await control.selectOption(value);
  else{await control.click();await page.getByRole('option',{name:value,exact:true}).click();}
  return true;
}
async function dateDialogContracts() {
  if(cfg.key!=='executive')return;
  stage='executive-date-dialog';
  const bars=page.locator('.pd-chart__bar');
  if(!await bars.count()){unknown('date-dialog','真实任务范围无可用交期图；不生成模拟图表。');return;}
  const before=await page.locator('.pd-summary').innerText();
  const labels=await bars.evaluateAll(elements=>elements.map(el=>el.getAttribute('aria-label')));
  const index=Math.max(0,labels.findIndex(label=>!label.includes('，0 单'))),date=labels[index].slice(0,10);
  await bars.nth(index).click();
  const dialog=page.getByTestId('production-due-dialog');
  await dialog.waitFor({state:'visible'});
  await page.waitForFunction(()=>{const el=document.querySelector('[data-testid="production-due-dialog"]');return el&&el.dataset.state!=='loading';});
  await settle();
  const datePayload=lastPayload,dateTasks=datePayload?.data?.sections.tasks?.data,state=await dialog.getAttribute('data-state');
  check('date-dialog-real-api-query',datePayload?.data?.filters.task_date===date&&datePayload?.data?.filters.task_page===1);
  check('date-dialog-main-summary-unchanged',await page.locator('.pd-summary').innerText()===before);
  if(dateTasks) {
    check('date-dialog-only-selected-date',dateTasks.items.every(task=>task.delivery_date===date&&task.status!=='COMPLETED'));
    check('date-dialog-row-count',await dialog.locator('.pd-date-row').count()===dateTasks.items.length);
    const next=page.getByTestId('production-due-next');
    check('date-dialog-next-availability',await next.isEnabled()===(dateTasks.total>20));
    if(dateTasks.total>20){const ids=new Set(dateTasks.items.map(task=>task.id));await next.click();await page.waitForFunction(()=>document.querySelector('[data-testid="production-due-dialog"]')?.dataset.state!=='loading');await settle();const nextRows=lastPayload?.data?.sections.tasks?.data?.items||[];check('date-dialog-page-two-real-api',lastPayload?.data?.filters.task_page===2&&nextRows.every(task=>!ids.has(task.id)&&task.delivery_date===date));}
    else unknown('date-dialog-page-two','该日真实任务不足21单，第二页覆盖不足；未补造数据。');
  }else unknown('date-dialog-readable-data','真实日期明细状态为'+state+'。');
  await screenshot('date-dialog');
  await page.locator('.production-dashboard-dialog').getByRole('button',{name:'关闭',exact:true}).click();
  await dialog.waitFor({state:'hidden'});check('date-dialog-closed',!await dialog.isVisible());
}
async function interactionContracts(result) {
  stage=cfg.key+'-filters';
  const apply=page.getByRole('button',{name:'应用筛选',exact:true}),reset=page.getByRole('button',{name:'重置',exact:true});
  if(await apply.count()&&await reset.count()) {
    await choose('交期范围','3');await choose('任务状态','IN_PRODUCTION');
    await apply.click();await settle();check('apply-real-filter-no-error',(await measure()).state!=='error');
    check('applied-filter-api-echo',lastPayload?.data?.filters.days===3&&lastPayload?.data?.filters.status==='IN_PRODUCTION',{filters:lastPayload?.data?.filters});
    const search=page.getByLabel('查找任务',{exact:true});await search.fill('__QA_READONLY_NO_MATCH_20261017__');await apply.click();await settle();
    const taskSection=lastPayload?.data?.sections.tasks;
    if(taskSection&&['READY','EMPTY'].includes(taskSection.state))check('real-search-empty-results',taskSection.data?.total===0&&await page.locator('[data-testid="production-task-list"] tbody tr').count()===0);
    else unknown('real-search-empty-results','没有任务读取权限或任务节不可用。');
    await reset.click();await settle();check('reset-real-filter-no-error',(await measure()).state!=='error');
    check('reset-filter-api-echo',lastPayload?.data?.filters.days===7&&lastPayload?.data?.filters.status==='ALL'&&lastPayload?.data?.filters.q==='');
  }else unknown('filter-controls','未找到应用筛选/重置入口，等待实现契约确认。');
  const refresh=page.getByRole('button',{name:'刷新',exact:true});
  if(await refresh.count()){await refresh.click();await settle();check('refresh-real-api-no-error',(await measure()).state!=='error');}
  await dateDialogContracts();
  const source=await measure();const detail=source.links.find(l=>/^\/production-tasks\/[0-9a-f-]+$/i.test(l.href));
  stage=cfg.key+'-detail';
  if(detail){const expectedApi='/api/v1'+detail.href+'/';const response=page.waitForResponse(value=>new URL(value.url()).pathname===expectedApi&&value.request().method()==='GET');await page.locator('[data-testid="production-dashboard"] a[href="'+detail.href+'"]').first().click();const loaded=await response;await page.waitForURL(url=>url.pathname===detail.href);check('real-detail-route',new URL(page.url()).pathname===detail.href);check('real-detail-api-readable',loaded.status()===200,{status:loaded.status()});await page.goto(new URL(cfg.path,base).href,{waitUntil:'domcontentloaded'});await settle();}
  else unknown('real-task-detail','当前真实范围未发现可访问的任务详情链接；不补造记录。');
  if(cfg.key==='workshop') {
    stage='workshop-process-tabs';
    let populatedCategory=null;
    for(const [name,category] of [['金工','METAL'],['缝纫','SEWING'],['装配','ASSEMBLY']]){const button=page.getByRole('button',{name,exact:true});if(await button.count()){await button.click();await settle();check('workshop-'+name+'-real-scope',(await measure()).state!=='error'&&lastPayload?.data?.filters.workshop===category);if(lastPayload?.data?.sections.workshop?.data?.items?.length)populatedCategory=category;else unknown('workshop-'+category+'-populated','当前真实筛选范围没有可展示工序记录或该节不可用。');}else unknown('workshop-'+name,'当前页面没有该工序入口。');}
    if(populatedCategory){await page.getByTestId('production-process-'+populatedCategory).click();await settle();}
    stage='workshop-fullscreen';const enter=page.getByRole('button',{name:'现场全屏',exact:true});
    if(await enter.count()){await enter.click();await page.waitForTimeout(400);result.fullscreen=await page.evaluate(()=>({active:!!document.fullscreenElement,width:innerWidth,height:innerHeight,headingFont:getComputedStyle(document.querySelector('.pd-heading h1')).fontSize,jobNumberFonts:[...document.querySelectorAll('.pd-job__progress b')].map(el=>getComputedStyle(el).fontSize),cards:[...document.querySelectorAll('.pd-glass')].map(el=>({transform:getComputedStyle(el).transform,before:getComputedStyle(el,'::before').display,after:getComputedStyle(el,'::after').display}))}));check('fullscreen-entered',result.fullscreen.active);check('fullscreen-stops-card-motion',result.fullscreen.cards.every(c=>c.transform==='none'&&c.before==='none'&&c.after==='none'));if(result.fullscreen.jobNumberFonts.length)check('fullscreen-job-numbers-readable',result.fullscreen.jobNumberFonts.every(font=>parseFloat(font)>=48),{fonts:result.fullscreen.jobNumberFonts});else unknown('fullscreen-populated-jobs','真实工序任务为空，无法验证有数据时数字字号。');await screenshot('fullscreen');const exit=page.getByRole('button',{name:'退出全屏',exact:true});if(await exit.count())await exit.click();else await page.keyboard.press('Escape');await page.waitForTimeout(300);check('fullscreen-exited',await page.evaluate(()=>!document.fullscreenElement));}
    else unknown('fullscreen','车间现场全屏入口未找到。');
  }
}
async function main() {
  requireValue(['localhost','127.0.0.1'].includes(base.hostname),'此脚本仅用于本地明确开发入口。',true);
  requireValue(fs.existsSync(path.join(evidence,'implementation-qa.md')),'缺少资源登记。');requireValue(!fs.existsSync(runtime),'独占临时目录已存在，拒绝接管。',true);
  const auth=authConfig();requireValue(auth.state||(auth.username&&auth.password),'缺少显式有效Session或已授权测试账号；未启动浏览器。',true);
  const executablePath=['C:/Program Files/Google/Chrome/Application/chrome.exe','C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(fs.existsSync);requireValue(executablePath,'Chrome/Edge不可用。',true);
  save();fs.mkdirSync(runtime);ownsRuntime=true;report.resources.created=true;
  browser=await chromium.launch({executablePath,headless:true,env:{...process.env,TEMP:runtime,TMP:runtime,TMPDIR:runtime}});
  context=await newContext(auth);await authenticate(context,auth);
  stage='api-contract';const response=await get(context,apiPath,'initial-dashboard');requireValue(response.status()===200,'聚合API未返回200，页面验收尚不可执行。',true);apiContracts(await readJson(response),'initial');
  for(const [name,query] of [['invalid-days','days=999'],['invalid-status','status=INVALID'],['invalid-date','production_date=not-a-date'],['invalid-workshop','workshop=CUTTING'],['invalid-focus','focus=INVALID'],['invalid-search-length','q='+'x'.repeat(121)],['invalid-task-page','task_page=0']]){const invalid=await get(context,apiPath+'?'+query,name);check(name+'-rejected',invalid.status()===400,{status:invalid.status()});}
  page=await context.newPage();observe(page);
  for(cfg of routes) {
    stage=cfg.key+'-load';lastPayload=undefined;await page.goto(new URL(cfg.path,base).href,{waitUntil:'domcontentloaded'});await settle();
    const result={route:cfg.key,measurements:[]};report.pages.push(result);
    for(const viewport of [{width:1920,height:1080},{width:1440,height:1000},{width:390,height:844}]){stage=cfg.key+'-'+viewport.width;await page.setViewportSize(viewport);await page.mouse.move(2,2);await settle();const m=await measure();result.measurements.push({viewport,...m});layoutContracts(m);await screenshot(String(viewport.width));}
    await page.setViewportSize({width:1440,height:1000});await settle();
    if(lastPayload){apiContracts(lastPayload,cfg.key);if(cfg.key==='owner'){const s=lastPayload.data.sections;for(const [key,value] of [['overdue',s.tasks.data?.counts.overdue],['due-soon',s.tasks.data?.counts.due_soon],['unscheduled',s.tasks.data?.counts.unscheduled],['outsourcing',s.outsourcing.data?.pending_count]]){const metric=page.locator('[data-testid="production-metric-'+key+'"] b');if(!await metric.count()){unknown('real-metric-'+key,'真实页面为空或无权，当前未渲染指标。');continue;}const shown=await metric.innerText();const expected=value==null?'—':new Intl.NumberFormat('zh-CN',{maximumFractionDigits:6}).format(value);check('real-metric-'+key,shown.trim()===expected,{expected,shown:shown.trim()});}}}else unknown('page-api-observation','未观察到该页真实聚合API响应。');
    await interactionContracts(result);save();console.log(JSON.stringify({route:cfg.key,checks:report.checks.filter(c=>c.route===cfg.key).length,failed:report.checks.filter(c=>c.route===cfg.key&&!c.passed).map(c=>c.id)}));
  }
  stage='anonymous-permission';const anonymous=await newContext();try{const denied=await get(anonymous,apiPath,'anonymous-dashboard');check('anonymous-api-denied',[401,403].includes(denied.status()),{status:denied.status()});}finally{await anonymous.close();}
  const restricted=authConfig(true);if(restricted.state){stage='restricted-permission';const low=await newContext(restricted);try{await authenticate(low,restricted);const r=await get(low,apiPath,'restricted-dashboard');if(r.status()===200)apiContracts(await readJson(r),'restricted');else check('restricted-api-denied',[401,403].includes(r.status()));}finally{await low.close();}}else unknown('restricted-role-permission','没有已有低权限真实Session，未创建账号或变更授权。');
  check('no-business-write-attempts',report.blockedWrites.length===0);check('no-runtime-or-http-errors',report.errors.length===0,report.errors);
  report.status=report.checks.every(c=>c.passed)?report.unknown.length?'PASS_WITH_UNKNOWNS':'PASS':'FAIL';
}
(async()=>{
  try{await main();}catch(error){report.status=error.blocked?'BLOCKED':'FAIL';report.failure={stage,...safeError(error),...(error.safe?{message:error.message}:{})};}
  finally{
    let closed=!browser;
    try{if(context)await context.close();if(browser){await browser.close();closed=true;}report.resources.browserClosed=closed;}catch(error){report.resources.closeError=safeError(error);report.status='FAIL';}
    if(ownsRuntime&&closed){try{requireValue(samePath(path.dirname(runtime),path.join(root,'qa/_tmp'))&&samePath(fs.realpathSync(runtime),runtime)&&!fs.lstatSync(runtime).isSymbolicLink(),'临时资源路径归属核验失败。');fs.rmSync(runtime,{recursive:true,force:false});report.resources.removed=true;}catch(error){report.resources.cleanupError=safeError(error);report.status='FAIL';}}
    report.resources.verifiedAbsent=!fs.existsSync(runtime);report.finishedAt=new Date().toISOString();save();
    if(['FAIL','BLOCKED'].includes(report.status)||!report.resources.verifiedAbsent)process.exitCode=1;
    console.log(JSON.stringify({status:report.status,report:reportPath,checks:report.checks.length,failed:report.checks.filter(c=>!c.passed).map(c=>c.id),unknown:report.unknown.length,cleanup:report.resources.verifiedAbsent,...(report.failure?.message?{failure:report.failure.message}:{})}));
  }
})();
