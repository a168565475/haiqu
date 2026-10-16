const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium, request } = require('../src/frontend/node_modules/playwright-core');
const root = path.resolve(__dirname, '..');
const out = path.join(root, 'output/playwright/production-management-20261015');
const config = path.join(root, 'output/production-management');
const base = process.env.TASK_MGMT_BASE_URL || 'http://127.0.0.1:18216';
assert.equal(base, 'http://127.0.0.1:18216', '拒绝对正式环境运行写入验收');
const password = process.env.TASK_MGMT_SECRET;
assert.ok(password, '缺少隔离验收凭证');
fs.mkdirSync(out, {recursive:true});
const mode = process.argv[2] || 'api';
const seed = JSON.parse(fs.readFileSync(path.join(config,'seed.json'),'utf8').replace(/^\uFEFF/,''));
const records = [];
const runPrefix = `HT26981${Date.now().toString().slice(-6)}`;
const imageBuffer = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j9l8AAAAASUVORK5CYII=', 'base64');
async function csrf(context) {
  const state = await context.storageState();
  return state.cookies.find(c => c.name === 'csrftoken')?.value || '';
}
async function call(context, method, url, data, etag, expected=200, files) {
  const headers = {'X-CSRFToken':await csrf(context),Referer:base};
  if (etag) headers['If-Match'] = etag;
  const response = await context.fetch(base+url, {method,headers,...(files ? {multipart:{payload:JSON.stringify(data),...files}} : data === undefined ? {} : {data})});
  const raw = await response.text();
  let body; try {body = raw ? JSON.parse(raw) : null;} catch {body = raw.slice(0,500);}
  records.push({method,url,status:response.status(),expected});
  assert.equal(response.status(), expected, `${method} ${url}: ${JSON.stringify(body)}`);
  return {data:body?.data,body,etag:response.headers().etag || ''};
}
async function login(username='admin') {
  const context = await request.newContext({baseURL:base});
  await context.get('/api/auth/me/');
  await call(context,'POST','/api/auth/login/',{username,password});
  return context;
}
const endpoint = id => `/api/v1/production-tasks/${id}/`;
function productPayload(row, changes={}) {
  return {client_key:row.id,product_id:row.product_id,product_category_id:row.product_category_id,product_color_id:row.product_color_id,color_code:row.color_code || '',customer_product_name:row.customer_product_name || row.product_name,customer_specification:row.customer_specification || row.specification,customer_color:row.customer_color || '',material:row.material || '',quantity:row.quantity,unit_id:row.unit_id,currency_id:row.currency_id,unit_price:row.unit_price,exchange_rate:row.exchange_rate,special_requirements:row.special_requirements || '',packaging_method:row.packaging_method || '',retained_image_ids:row.images.map(image=>image.id),details:row.details.map(detail=>({client_key:detail.id,template_key:detail.template_key,detail_type:detail.detail_type,category_label:detail.category_label,is_selected:detail.is_selected,description:detail.description,retained_image_id:detail.image?.id || null})),...changes};
}
async function api() {
  const context = await login();
  let viewer;
  try {
    const options = (await call(context,'GET','/api/v1/production-tasks/options/')).data;
    const currency = options.currencies.find(row=>row.code==='CNY');
    const product = options.products[0];
    assert.ok(product && currency);
    const unit = options.units.find(row=>row.id===product.default_unit_id);
    const otherUnit = options.units.find(row=>row.id!==unit.id);
    const lines = [
      {client_key:'linked',product_id:product.id,product_color_id:null,color_code:'',customer_product_name:product.product_name,customer_specification:product.specification || '标准规格',customer_color:'验收蓝',material:'尼龙',quantity:'100',unit_id:unit.id,currency_id:currency.id,unit_price:'12.5000',exchange_rate:'1.00000000',special_requirements:'验收生产要求',packaging_method:'验收包装',retained_image_ids:[],details:[{client_key:'detail-linked',template_key:'fabric',detail_type:'面料',category_label:'主体',is_selected:true,description:'验收面料'}]},
      {client_key:'custom',product_id:null,product_category_id:product.product_category_id || product.category_id,customer_product_name:'定制验收产品',customer_specification:'40×50×60cm',customer_color:'红色',color_code:'',material:'钢',quantity:'2',unit_id:otherUnit.id,currency_id:currency.id,unit_price:'20.0000',exchange_rate:'1.00000000',special_requirements:'',packaging_method:'',retained_image_ids:[],details:[{client_key:'detail-custom',template_key:'fabric',detail_type:'面料',category_label:'主体',is_selected:false,description:''}]},
    ];
    lines[0].details = options.detail_template.map((row,index)=>({client_key:`detail-linked-${index}`,template_key:row.key,detail_type:row.type,category_label:row.category,is_selected:index===0,description:index===0?'验收面料':''}));
    async function create(number, products=lines) {
      const reserved=(await call(context,'POST','/api/v1/production-tasks/reserve-contract-number/',{order_date:'2026-10-15'})).data;
      return call(context,'POST','/api/v1/production-tasks/',{task_number:number,contract_number:reserved.contract_number,contract_number_token:reserved.token,order_source:'NEW',order_date:'2026-10-15',delivery_date:'2026-10-31',salesperson_id:seed.actor,follower_ids:[seed.follower],currency_id:currency.id,includes_tax:false,tax_rate:null,order_tolerance_percent:'3.00',is_repeat_order:false,preproduction_sample_required:false,delivery_method:'SINGLE',planned_start_date:'2026-10-16',planned_end_date:'2026-10-29',production_priority:'NORMAL',production_batch_number:'QA-MGMT',planner_id:seed.actor,products,delivery_batches:[]},undefined,201);
    }
    let manual=await create(runPrefix+'1');
    assert.equal(manual.data.sales_order_id,null);
    const manualId=manual.data.id;
    await call(context,'DELETE',endpoint(manualId),undefined,manual.etag,409);
    await call(context,'PATCH',endpoint(manualId),{task_number:'HT2698999'},manual.etag,400);
    await call(context,'PATCH',endpoint(manualId),{follower_ids:[]},manual.etag,400);
    await call(context,'PATCH',endpoint(manualId),{includes_tax:true},manual.etag,400);
    const oldTag=manual.etag;
    manual=await call(context,'PATCH',endpoint(manualId),{includes_tax:true,tax_rate:5,order_tolerance_percent:'2.00',is_repeat_order:true,delivery_method:'SPLIT',production_priority:'HIGH',production_batch_number:'QA-MGMT-EDIT',planned_start_date:'2026-10-17',planned_end_date:'2026-10-30'},manual.etag);
    assert.equal(manual.data.tax_rate,5);
    await call(context,'PATCH',endpoint(manualId),{delivery_date:'2026-11-01'},oldTag,412);
    const products=manual.data.products.map(row=>productPayload(row,row.product_id?{quantity:120,unit_price:'15.0000',material:'牛津布'}:{}));
    manual=await call(context,'PATCH',endpoint(manualId),{products,bom_sync_mode:'KEEP'},manual.etag);
    assert.equal(Number(manual.data.products.find(row=>row.product_id).local_unit_price),15);
    assert.equal(manual.data.products.find(row=>row.product_id).material,'牛津布');
    let linked = manual.data.products.find(row=>row.product_id);
    manual=await call(context,'PATCH',endpoint(manualId),{products:manual.data.products.map(row=>productPayload(row)),bom_sync_mode:'KEEP'},manual.etag,200,{
      [`product_image_${linked.id}`]:{name:'验收主图A.png',mimeType:'image/png',buffer:imageBuffer},
      [`detail_image_${linked.details[0].id}`]:{name:'验收明细图.png',mimeType:'image/png',buffer:imageBuffer},
    });
    linked=manual.data.products.find(row=>row.product_id);
    manual=await call(context,'PATCH',endpoint(manualId),{products:manual.data.products.map(row=>productPayload(row)),bom_sync_mode:'KEEP'},manual.etag,200,{
      [`product_image_${linked.id}`]:{name:'验收附图B.png',mimeType:'image/png',buffer:imageBuffer},
    });
    assert.equal(manual.data.products.find(row=>row.product_id).images.length,2);
    assert.equal(manual.data.products.find(row=>row.product_id).details.length,options.detail_template.length);
    const salesPayload={source_type:'DIRECT',source_quotation_version_id:null,customer_account_id:seed.customer,transaction_entity_id:seed.entity,buyer_address_id:seed.address,salesperson_id:seed.actor,merchandiser_id:seed.actor,customer_po_number:'QA-MGMT-PO',contract_number:'QA-MGMT-SO',order_date:'2026-10-15',direct_order_reason:'隔离验收客户直接下单',currency_code:'CNY',exchange_rate:'1.000000',payment_terms:'验收付款条款',deposit_required:false,includes_tax:false,tax_basis:'不含税',order_tolerance_percent:'3.00',preproduction_sample_required:false,seller_snapshot:{template_config:{seller_company_name:'隔离验收卖方'}},confirmation_method:'CUSTOMER_PO',customer_confirmer:'验收客户',customer_confirmed_at:new Date().toISOString(),confirmation_summary:'隔离验收订单确认',evidence_file_ids:[seed.evidence],lines:[{client_key:'source-line',product_id:product.id,quantity:'100.0000',unit_price:'25.0000',quality_requirements:'按确认样',packaging_requirements:'纸箱',shipping_mark_requirements:'验收唛头'}],delivery_batches:[{planned_delivery_date:'2026-10-31',notes:'验收批次',lines:[{sales_order_line_client_key:'source-line',quantity:'100.0000'}]}]};
    let sales=await call(context,'POST','/api/v1/sales-orders/',salesPayload,undefined,201);
    sales=await call(context,'POST',`/api/v1/sales-orders/${sales.data.id}/confirm/`,{},sales.etag);
    const source=(await call(context,'GET',`/api/v1/production-tasks/sales-order-sources/?sales_order_id=${sales.data.id}`)).data;
    const sourceLine=source.delivery_batches[0].lines[0];
    async function createSource(number,quantity) {
      return call(context,'POST','/api/v1/production-tasks/create-from-sales-order/',{task_number:number,follower_ids:[seed.follower],delivery_date:'2026-10-31',includes_tax:false,tax_rate:null,order_tolerance_percent:'3.00',is_repeat_order:false,delivery_method:'SINGLE',delivery_batch_line_id:sourceLine.id,quantity,product_color_id:null},undefined,201);
    }
    let sourced=await createSource(runPrefix+'2',40);
    const second=await createSource(runPrefix+'3',30);
    sourced=await call(context,'GET',endpoint(sourced.data.id));
    assert.equal(Number(sourced.data.products[0].max_production_quantity),70);
    const sourcePatch=quantity=>({products:[productPayload(sourced.data.products[0],{quantity})]});
    await call(context,'PATCH',endpoint(sourced.data.id),sourcePatch(71),sourced.etag,400);
    await call(context,'PATCH',endpoint(sourced.data.id),{products:[productPayload(sourced.data.products[0],{unit_price:'99.0000'})]},sourced.etag,400);
    sourced=await call(context,'PATCH',endpoint(sourced.data.id),sourcePatch(70),sourced.etag);
    assert.equal(Number(sourced.data.products[0].local_total_amount),1750);
    assert.equal(sourced.data.products[0].details.length,0,'真实来源任务保留空明细契约');
    sourced=await call(context,'POST',endpoint(sourced.data.id)+'submit/',{},sourced.etag);
    let cancelled=await create(runPrefix+'4',[lines[0]]);
    cancelled=await call(context,'POST',endpoint(cancelled.data.id)+'cancel/',{reason:'隔离验收删除'},cancelled.etag);
    viewer=await login('task_mgmt_viewer');
    await call(viewer,'DELETE',endpoint(cancelled.data.id),undefined,cancelled.etag,403);
    await call(context,'DELETE',endpoint(cancelled.data.id),undefined,'"stale"',412);
    await call(context,'DELETE',endpoint(cancelled.data.id),undefined,cancelled.etag,204);
    await call(context,'GET',endpoint(cancelled.data.id),undefined,undefined,404);
    let uiDelete=await create(runPrefix+'5',[lines[0]]);
    uiDelete=await call(context,'POST',endpoint(uiDelete.data.id)+'cancel/',{reason:'隔离页面删除验收'},uiDelete.etag);
    fs.writeFileSync(path.join(out,'state.json'),JSON.stringify({manualId,manualNumber:manual.data.task_number,salesId:sales.data.id,sourceId:sourced.data.id,secondSourceId:second.data.id,deleteId:uiDelete.data.id,deleteNumber:uiDelete.data.task_number,unitName:unit.unit_name,otherUnitName:otherUnit.unit_name},null,2));
    fs.writeFileSync(path.join(out,'api-report.json'),JSON.stringify({passed:true,checks:records},null,2));
  } finally {await context.dispose(); if(viewer) await viewer.dispose();}
}

async function pages() {
  const state=JSON.parse(fs.readFileSync(path.join(out,'state.json'),'utf8'));
  const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  const errors=[]; const checks=[];
  try {
    const context=await browser.newContext({viewport:{width:1101,height:884}});
    await context.request.get(base+'/api/auth/me/');
    await call(context.request,'POST','/api/auth/login/',{username:'admin',password});
    const page=await context.newPage();
    page.on('pageerror',e=>{errors.push(e.message); console.error('PAGE_ERROR',e.message); fs.writeFileSync(path.join(out,'page-errors.json'),JSON.stringify(errors,null,2));});
    const routes=[['list','/production-tasks'],['detail',`/production-tasks/${state.manualId}`],['edit',`/production-tasks/${state.manualId}/edit`]];
    for(const width of [1101,1920]) {
      await page.setViewportSize({width,height:width===1101?884:1080});
      for(const [view,url] of routes) {
        await page.goto(base+url); await page.waitForLoadState('networkidle');
        await page.getByRole('heading',{name:view==='list'?'生产任务单':view==='detail'?'生产任务单详情':'编辑生产任务单',exact:true}).waitFor();
        const geometry=await page.evaluate(()=>{
          const pageRoot=document.querySelector('.production-list-page,.task-list-page,.task-detail-page,.production-edit-page');
          const main=document.querySelector('.erp-layout__main');
          const tables=[...document.querySelectorAll('table')].filter(e=>e.getBoundingClientRect().width>0);
          return {viewport:innerWidth,documentWidth:document.documentElement.scrollWidth,main:main?{width:main.clientWidth,scrollWidth:main.scrollWidth}:null,root:pageRoot?{width:pageRoot.getBoundingClientRect().width,minWidth:getComputedStyle(pageRoot).minWidth}:null,tables:tables.map(t=>({width:t.getBoundingClientRect().width,headers:[...t.querySelectorAll('th')].map(h=>({text:h.textContent.trim(),width:h.getBoundingClientRect().width,height:h.getBoundingClientRect().height,color:getComputedStyle(h).backgroundColor})),firstRowHeight:t.querySelector('tbody tr')?.getBoundingClientRect().height}))};
        });
        assert.ok(geometry.documentWidth<=width+1,`${view} document overflow`);
        assert.ok(!geometry.main || geometry.main.scrollWidth<=geometry.main.width+1,`${view} main overflow ${JSON.stringify(geometry.main)}`);
        const visibleText=await page.locator('body').innerText();
        assert.ok(!/\b(?:USD|EUR|GBP)\b/.test(visibleText),'生产页面出现外币');
        const visual=await page.evaluate(view=>{
          const container=document.querySelector(view==='list'?'.table-card':view==='detail'?'.products-card .table-wrap':'.product-table-wrap');
          const style=getComputedStyle(container);
          const table=container.querySelector('table');
          const cell=table.querySelector('th');
          const lastCell=container.querySelector('tbody tr:last-child td:last-child');
          const main=document.querySelector('.erp-layout__main');
          const input=document.querySelector('.info-grid .el-input__wrapper');
          const heading=document.querySelector('.detail-heading,.page-heading');
          return {borders:['Top','Right','Bottom','Left'].map(side=>({side,width:style[`border${side}Width`],color:style[`border${side}Color`]})),radius:style.borderRadius,headerHeight:cell.getBoundingClientRect().height,headerColor:getComputedStyle(cell).backgroundColor,headerRightBorder:getComputedStyle(cell).borderRightWidth,lastBottomBorder:lastCell?getComputedStyle(lastCell).borderBottomWidth:null,inputHeight:input?.getBoundingClientRect().height,headingHeight:heading?.getBoundingClientRect().height,mainHeight:main.clientHeight,mainScrollHeight:main.scrollHeight,tableWidth:table.getBoundingClientRect().width,containerWidth:container.clientWidth,innerBefore:view==='list'?getComputedStyle(container.querySelector('.el-table__inner-wrapper'),'::before').display:null};
        },view);
        for(const border of visual.borders) {assert.equal(border.width,'1px');assert.equal(border.color,'rgb(221, 214, 201)');}
        assert.equal(visual.radius,'5px'); assert.equal(visual.headerHeight,44);
        assert.equal(visual.headerColor,'rgb(240, 234, 223)'); assert.equal(visual.headerRightBorder,'0px');
        if(view==='list') {assert.equal(visual.innerBefore,'none');assert.equal(visual.lastBottomBorder,'0px');}
        const dataRows=page.locator(view==='list'?'.el-table__body-wrapper tbody tr':view==='detail'?'.products-card tbody tr:not(.total-row)':'.product-table tbody tr');
        const rowHeights=await dataRows.evaluateAll((rows,view)=>rows.map(row=>({height:row.getBoundingClientRect().height,products:view==='list'?row.querySelector('.product-summary')?.children.length:1})),view);
        for(const row of rowHeights) if(row.products===1) assert.equal(row.height,view==='edit'?44:34,`${view} row height`);
        await dataRows.first().locator('td').first().hover();
        if(view!=='edit') await page.waitForFunction(selector=>getComputedStyle(document.querySelector(selector)).backgroundColor==='rgb(255, 246, 234)',view==='list'?'.el-table__body-wrapper tbody tr td':'.products-card tbody tr td',{timeout:3000});
        const hoverColor=await dataRows.first().locator('td').first().evaluate(el=>getComputedStyle(el).backgroundColor);
        if(view!=='edit') assert.equal(hoverColor,'rgb(255, 246, 234)');
        await page.mouse.move(15,20);
        if(visual.inputHeight) assert.equal(visual.inputHeight,32);
        if(view==='detail') assert.ok(visual.headingHeight<=50,'详情标题仍有额外留白');
        await page.screenshot({path:path.join(out,`${view}-${width}.png`),fullPage:true});
        if(view!=='list' && visual.mainScrollHeight>visual.mainHeight+1) {
          await page.mouse.move(width-100,500); await page.mouse.wheel(0,10000);
          await page.waitForFunction(()=>{const main=document.querySelector('.erp-layout__main');return main.scrollTop+main.clientHeight>=main.scrollHeight-2;});
          await page.screenshot({path:path.join(out,`${view}-bottom-${width}.png`)});
          if(view==='edit') assert.ok(await page.locator('.edit-footer').isVisible());
        }
        if(view==='detail') {
          const wrap=page.locator('.products-card .table-wrap'); await wrap.scrollIntoViewIfNeeded();
          await wrap.evaluate(el=>{el.scrollLeft=el.scrollWidth;});
          const scroll=await wrap.evaluate(el=>({left:el.scrollLeft,width:el.clientWidth,total:el.scrollWidth}));
          if(scroll.total>scroll.width+1) assert.ok(scroll.left+scroll.width>=scroll.total-2);
          await page.screenshot({path:path.join(out,`detail-table-end-${width}.png`)});
        }
        checks.push({view,width,geometry,visual,rowHeights,hoverColor});
      }
    }
    if(process.env.TASK_MGMT_VISUAL_ONLY==='1') {
      fs.writeFileSync(path.join(out,'visual-report.json'),JSON.stringify({passed:errors.length===0,checks,errors},null,2));
      assert.deepEqual(errors,[]); return;
    }
    await page.setViewportSize({width:1101,height:884});
    await page.goto(base+`/production-tasks/${state.manualId}/edit`);
    await page.getByRole('button',{name:'保存修改',exact:true}).waitFor();
    await page.waitForLoadState('networkidle');
    let before=(await call(context.request,'GET',endpoint(state.manualId))).data;
    const originalLinked=before.products.find(row=>row.product_id);
    assert.equal(originalLinked.images.length,2);
    for(const name of ['验收主图C.png','验收主图D.png']) {
      await page.getByRole('button',{name:'编辑产品',exact:true}).first().click();
      const dialog=page.getByRole('dialog',{name:'编辑生产产品'});
      await dialog.getByLabel('上传产品图片').setInputFiles({name,mimeType:'image/png',buffer:imageBuffer});
      await dialog.locator('.product-detail-editor tbody tr').first().locator('input[type="text"]').fill('页面修改明细且保留图片');
      await dialog.getByRole('button',{name:'保存产品信息',exact:true}).click();
      await dialog.waitFor({state:'hidden'});
    }
    await page.locator('.info-grid > label').filter({hasText:'生产批号'}).locator('input').fill('QA-PAGE-SAVED');
    await page.locator('.product-table tbody tr').first().getByRole('textbox',{name:/本次生产量/}).fill('125');
    await page.locator('.product-table tbody tr').first().getByRole('textbox',{name:'人民币单价',exact:true}).fill('16');
    await page.getByRole('button',{name:'保存修改',exact:true}).click();
    try { await page.getByRole('button',{name:'确认保存',exact:true}).waitFor({timeout:3000}); }
    catch(error) { await page.screenshot({path:path.join(out,'edit-save-blocked.png')}); throw new Error(await page.locator('body').innerText(),{cause:error}); }
    const savedResponse=page.waitForResponse(r=>r.url().endsWith(endpoint(state.manualId)) && r.request().method()==='PATCH');
    await page.getByRole('button',{name:'确认保存',exact:true}).click();
    const saved=await savedResponse;
    assert.equal(saved.status(),200,await saved.text());
    await page.waitForLoadState('networkidle');
    const after=(await call(context.request,'GET',endpoint(state.manualId))).data;
    const linked=after.products.find(row=>row.id===originalLinked.id);
    assert.equal(Number(linked.quantity),125); assert.equal(Number(linked.local_unit_price),16);
    assert.equal(after.production_batch_number,'QA-PAGE-SAVED');
    assert.equal(linked.images[0].name,'验收主图D.png');
    assert.ok(linked.images.some(row=>row.id===originalLinked.images[1].id),'附图B未保留');
    assert.equal(linked.details.length,originalLinked.details.length);
    assert.equal(linked.details[0].image_name,originalLinked.details[0].image_name);
    assert.equal(linked.details[0].description,'页面修改明细且保留图片');
    checks.push({flow:'manual-edit-images-details',passed:true,quantity:linked.quantity,amount:linked.local_total_amount,images:linked.images.map(row=>row.name)});
    await page.goto(base+`/production-tasks/${state.sourceId}/edit`); await page.waitForLoadState('networkidle');
    await page.locator('.product-table tbody tr').first().getByRole('textbox',{name:/本次生产量/}).fill('65');
    await page.getByRole('button',{name:'保存修改',exact:true}).click();
    await page.getByRole('button',{name:'确认保存',exact:true}).waitFor();
    const sourceSave=page.waitForResponse(r=>r.url().endsWith(endpoint(state.sourceId)) && r.request().method()==='PATCH');
    await page.getByRole('button',{name:'确认保存',exact:true}).click();
    const sourceResponse=await sourceSave; assert.equal(sourceResponse.status(),200,await sourceResponse.text());
    await page.waitForLoadState('networkidle');
    const sourceAfter=await call(context.request,'GET',endpoint(state.sourceId));
    assert.equal(Number(sourceAfter.data.products[0].quantity),65);
    assert.equal(Number(sourceAfter.data.products[0].local_total_amount),1625);
    await call(context.request,'POST',endpoint(state.sourceId)+'submit/',{},sourceAfter.etag);
    checks.push({flow:'sales-quantity-edit-and-resubmit',passed:true});
    await page.goto(base+'/production-tasks'); await page.waitForLoadState('networkidle');
    const listHeaders=await page.locator('.el-table__header-wrapper th').allTextContents();
    for(const label of ['人民币金额合计','业务员','跟单员']) assert.ok(listHeaders.some(text=>text.trim()===label));
    const manualRow=page.locator('.el-table__body-wrapper tr').filter({hasText:state.manualNumber});
    await manualRow.locator('.product-summary').hover();
    await page.locator('.production-product-tooltip:visible').first().waitFor();
    assert.match(await page.locator('.production-product-tooltip:visible').first().innerText(),/规格.*颜色.*材质/s);
    await page.screenshot({path:path.join(out,'list-product-tooltip-1101.png'),fullPage:true});
    const remove=page.getByRole('button',{name:`打开生产任务 ${state.deleteNumber} 操作菜单`,exact:true});
    await remove.click(); await page.getByRole('menuitem',{name:'删除生产任务单',exact:true}).click();
    const box=page.locator('.el-message-box'); await box.waitFor();
    await page.screenshot({path:path.join(out,'delete-confirm-1101.png')});
    const deletion=page.waitForResponse(r=>r.url().endsWith(endpoint(state.deleteId)) && r.request().method()==='DELETE');
    await box.getByRole('button',{name:/删除/}).click();
    assert.equal((await deletion).status(),204);
    await call(context.request,'GET',endpoint(state.deleteId),undefined,undefined,404);
    checks.push({flow:'cancelled-ui-delete',passed:true});
    const search=page.getByPlaceholder('搜索任务单号、订单号或产品');
    await search.fill('NO-SUCH-TASK-MGMT'); await search.press('Enter');
    await page.getByText('暂无生产任务单',{exact:true}).waitFor();
    await page.screenshot({path:path.join(out,'list-empty-1101.png')});
    checks.push({flow:'empty',passed:true});
    await context.setOffline(true);
    await page.getByRole('button',{name:'刷新',exact:true}).click();
    await page.locator('.list-error').waitFor();
    await page.screenshot({path:path.join(out,'list-error-1101.png')});
    await context.setOffline(false);
    checks.push({flow:'network-error',passed:true});
    await context.close();
    const viewerContext=await browser.newContext({viewport:{width:1101,height:884}});
    await viewerContext.request.get(base+'/api/auth/me/');
    await call(viewerContext.request,'POST','/api/auth/login/',{username:'task_mgmt_viewer',password});
    const viewerPage=await viewerContext.newPage();
    await viewerPage.goto(base+'/production-tasks'); await viewerPage.waitForLoadState('networkidle');
    await viewerPage.getByRole('button',{name:`打开生产任务 ${state.manualNumber} 操作菜单`,exact:true}).click();
    assert.equal(await viewerPage.getByRole('menuitem',{name:/删除生产任务单/}).count(),0);
    assert.equal(await viewerPage.getByRole('menuitem',{name:'编辑',exact:true}).count(),0);
    await viewerPage.screenshot({path:path.join(out,'list-readonly-permission-1101.png')});
    checks.push({flow:'read-only-permission',passed:true});
    fs.writeFileSync(path.join(out,'pages-report.json'),JSON.stringify({passed:errors.length===0,checks,errors},null,2));
    assert.deepEqual(errors,[]);
  } finally {await browser.close();}
}
(async()=>{try{if(mode==='api')await api();else if(mode==='pages')await pages();else throw new Error('Unknown mode');console.log(JSON.stringify({mode,passed:true,requests:records.length}));}catch(error){fs.writeFileSync(path.join(out,`${mode}-failure.json`),JSON.stringify({error:error.stack,requests:records},null,2));throw error;}})().catch(error=>{console.error(error);process.exitCode=1;});
