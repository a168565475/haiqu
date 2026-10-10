// 仅生成独立设计预览，不修改产品代码、不连接业务接口。
const fs=require('node:fs'),path=require('node:path');
const base=__dirname,previous=path.resolve(base,'../internal_receipt_20260928');
const old=fs.readFileSync(path.join(previous,'entry-standard.html'),'utf8');
const receiptSidebar=old.match(/<aside[\s\S]*?<\/aside>/)[0];
const stockSource=fs.readFileSync(path.join(previous,'records-standard.html'),'utf8');
const stockSidebar=stockSource.match(/<aside[\s\S]*?<\/aside>/)[0].replace(/<div class="navitem([^"]*)"[\s\S]*?<\/div>/g,markup=>{
 const cleared=markup.replace('sub active','sub ');
 return cleared.includes('<span class="label">成品库存</span>')?cleared.replace(/navitem sub\s*/, 'navitem sub active'):cleared;
});
// 原型复用已确认的菜单图标与窗口组件，不另造图标体系。
fs.copyFileSync(path.join(previous,'preview.css'),path.join(base,'base.css'));
fs.mkdirSync(path.join(base,'assets'),{recursive:true});
for(const file of ['window.js','window.css'])fs.copyFileSync(path.join(previous,'source_assets',file),path.join(base,'assets',file));
function shell(title,crumb,content,page){return `<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${title} · 待确认设计</title><link rel="stylesheet" href="/fonts/sans/index.css"><link rel="stylesheet" href="/fonts/serif/index.css"><link rel="stylesheet" href="assets/window.css"><link rel="stylesheet" href="base.css"><link rel="stylesheet" href="design.css"></head><body data-page="${page}"><div class="shell">${page==='receipt'?receiptSidebar:stockSidebar}<header class="topbar"><span>${crumb}</span><span class="preview-note">设计预览 · 示例数据 · 未接入业务</span><span class="spacer"></span><input class="global-search" placeholder="搜索客户、联系人、询盘" aria-label="全局搜索示意" readonly><span>仓库管理员</span></header><main class="content">${content}</main></div><div id="sourceWindowMount"></div><div id="notice" role="status" hidden></div><script type="module" src="assets/window.js"></script><script defer src="preview.js"></script></body></html>`;}
const info=(label,value)=>`<div class="info-field"><span>${label}</span><b>${value}</b></div>`;
const field=(label,control,required=false)=>`<label class="field"><span>${required?'<i>*</i> ':''}${label}</span>${control}</label>`;
const receipt=`<div class="page-heading"><h1>成品入库</h1><span class="tag brand">装配入库</span><span class="muted">由内部装配计划带入</span><a class="button" href="stock.html?tab=records">入库记录</a></div>
<div class="form-scroll">
 <section class="summary"><div class="context-grid">${info('生产单号','SC20260929001')}${info('订单号','DD20260921001')}${info('装配计划','PC20260929001')}${info('入库人','当前仓管')}</div>
 <div class="identity-grid">${info('品号','CP000128')}${info('品名','组合杯托折叠椅')}${info('货号','HT-806')}${info('规格','53 × 53 × 90 cm')}</div></section>
 <section class="form-section quota-section"><div class="section-heading"><h2>订单入库额度</h2><span class="muted">按此订单产品累计，分次入库共用额度</span></div>
 <div class="quota-line">${info('订单数量','1,000 <small>把</small>')}${info('订单允许偏差','2%')}${info('累计入库上限','1,020 <small>把</small>')}${info('累计已入库','600 <small>把</small>')}${info('剩余可入库','420 <small>把</small>')}</div>
 <p class="helper">本单上限：1,000 ×（1 + 2%）= 1,020 把。偏差比例读取订单设置；已出库数量不会恢复入库额度。</p></section>
 <section class="form-section"><div class="section-heading"><h2>本次收货</h2><span class="muted">仓库按实际收到的成品数量确认</span></div>
 <div class="receipt-grid">${field('收货日期','<input id="receiptDate" aria-label="收货日期" type="date" value="2026-09-29">',true)}${field('入库数量（把）','<input id="quantity" aria-label="本次入库数量" type="number" min="1" max="420" step="1" value="200">',true)}${field('单位','<input aria-label="入库单位" value="把 · 跟随生产订单" readonly>')}${field('实际颜色','<select id="color" aria-label="实际颜色"><option>黑色</option><option>蓝色</option><option>军绿色</option></select>',true)}</div>
 <div class="receipt-grid location-grid">${field('成品仓','<input aria-label="成品仓" value="CK007 · 成品仓" readonly>',true)}${field('库区','<select id="zone" aria-label="库区"><option>A区</option><option>B区</option></select>',true)}${field('库位','<select id="location" aria-label="库位"><option value="100">A-01-01 · 剩余100箱位</option><option value="20">A-01-02 · 剩余20箱位</option></select>',true)}${field('入库后累计（把）','<input id="after" aria-label="入库后累计" value="800" readonly>')}</div>
 <p class="helper">单位不可修改；实际颜色从生产资料带入。仅可选择正常的成品仓、库区和库位。</p></section>
 <section class="form-section"><div class="section-heading"><h2>包装信息</h2><span class="muted">选填 · 填写后自动计算箱数、尾数和占用箱位</span></div>
 <div class="receipt-grid five">${field('每箱数量（把／箱）','<input id="perBox" aria-label="每箱数量" type="number" min="1" step="1" value="4" placeholder="选填">')}${field('整箱数','<input id="boxes" aria-label="整箱数" value="50 箱" readonly>')}${field('尾数','<input id="tail" aria-label="尾数" value="0 把" readonly>')}${field('本次占用箱位','<input id="slots" aria-label="本次占用箱位" value="50 箱位" readonly>')}${field('入库后剩余箱位','<input id="slotsAfter" aria-label="入库后剩余箱位" value="50 箱位" readonly>')}</div>
 <p class="helper">存在尾数时，另占1个箱位；不填每箱数量时不计算箱位，并保留“未计算”标识。</p></section>
 <section class="form-section remark-section"><label for="remark">备注</label><textarea id="remark" placeholder="填写本次收货、包装或存放说明" maxlength="3000">本次装配完成200把，按每箱4把收货。</textarea></section>
 <div id="formError" class="feedback" role="alert"></div>
</div>
<footer class="form-footer"><div class="totals">本次入库 <strong id="footerQuantity">200</strong> 把 <span class="footer-sep">·</span> 确认后累计 <b id="footerAfter">800</b> 把 <span class="footer-sep">·</span> 剩余可入 <b id="footerRemaining">220</b> 把<p class="muted">确认入库后增加成品库存，已领用的半成品不重复扣减。</p></div><a class="button cancel" href="stock.html">返回</a><button class="primary" id="confirmReceipt">确认入库</button></footer>`;
const table=(cols,id)=>`<div class="table-scroll"><table id="${id}"><colgroup>${cols.map(c=>`<col style="width:${c[1]}px">`).join('')}</colgroup><thead><tr>${cols.map(c=>`<th${c[2]?` class="${c[2]}"`:''}>${c[0]}</th>`).join('')}</tr></thead><tbody></tbody></table><div id="emptyState" hidden>暂无符合条件的记录<button class="link" id="resetFilters">清空筛选</button></div></div>`;
const stockcols=[['<input type="checkbox" id="selectAll" aria-label="全选库存">',50,'center'],['类别',80],['品号',120],['品名',160],['货号',95],['规格',165],['颜色',90],['当前库存',95,'number'],['单位',65],['仓库',105],['库区',75],['在库记录',90,'number'],['占用箱位',95,'number'],['最近入库日期',135],['操作',120]];
const recordscols=[['入库单号',155],['入库来源',105],['生产单号',150],['品号',105],['品名',150],['规格',160],['颜色',80],['入库数量',90,'number'],['单位',60],['仓库',90],['库区',65],['库位',90],['入库日期',105],['状态',90],['操作',95]];
const stock=`<div class="page-heading"><h1>成品库存</h1><span class="muted" id="headingCount">共 6 条库存记录</span><div class="heading-actions"><button id="configButton">仓库配置</button><button id="otherInbound">其他入库</button><a class="button primary" href="receipt.html">装配入库</a></div></div>
<nav class="tabs" aria-label="成品库存视图"><button id="stockTab" class="active" role="tab" aria-selected="true">库存汇总</button><button id="recordsTab" role="tab" aria-selected="false">入库记录</button></nav>
<div class="filters"><input class="search" id="search" placeholder="搜索品号、品名、货号、规格或颜色" aria-label="搜索库存"><select id="warehouseFilter" aria-label="仓库筛选"><option value="">全部仓库</option><option>成品仓</option></select><select id="zoneFilter" aria-label="库区筛选"><option value="">全部库区</option><option>A区</option><option>B区</option></select><select id="sourceFilter" aria-label="来源筛选" hidden><option value="">全部来源</option><option>装配入库</option><option>生产入库</option><option>样品入库</option></select><button id="queryButton">查询</button></div>
<div class="toolbar"><span id="selectionText" class="muted">已选 0 条</span><button id="outboundButton" disabled>批量出库</button><span id="tableHint" class="muted">同产品、颜色、单位及库区汇总；来源和具体库位在详情中查看</span><button class="refresh" id="refreshButton">刷新</button></div>
<section class="table-card stock-card"><div id="stockTableWrap">${table(stockcols,'stockTable')}</div><div id="recordTableWrap" hidden>${table(recordscols,'recordsTable').replace('id="emptyState"','id="recordEmptyState"').replace('id="resetFilters"','id="resetRecordFilters"')}</div><footer class="pager"><span id="totalText">共 6 条</span><select aria-label="每页条数"><option>50 条／页</option></select><button disabled aria-label="上一页">‹</button><button class="current" aria-label="第1页">1</button><button disabled aria-label="下一页">›</button></footer></section>`;
fs.writeFileSync(path.join(base,'receipt.html'),shell('成品入库','生产车间 / 内部计划 / 装配 / 成品入库',receipt,'receipt'));
fs.writeFileSync(path.join(base,'stock.html'),shell('成品库存','仓库管理 / 成品库存',stock,'stock'));
console.log('两页设计预览已生成，仅限docs/designs目录');
