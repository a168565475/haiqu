// 交互仅在浏览器内演示。无业务请求，无持久化，无实际出入库。
(() => {
 const $=id=>document.getElementById(id);
 const esc=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const fmt=value=>Number(value).toLocaleString('zh-CN');
 const tag=(value,color='brand')=>`<span class="tag ${color}">${esc(value)}</span>`;
 const fields=values=>`<dl class="source-fields">${values.map(([k,v])=>`<div class="source-field"><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl>`;
 function table(headers,rows){return `<div class="table-card"><table><thead><tr>${headers.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(c=>`<td title="${esc(c)}">${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;}
 const open=(title,body)=>window.receiptSourceWindow?.open(title,body);
 let noticeTimer;
 function notice(message){$('notice').textContent=message;$('notice').hidden=false;clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>$('notice').hidden=true,4000);}
 const date='2026-09-29';
 if(document.body.dataset.page==='receipt'){
  function calculate(){
   const q=Number($('quantity').value),raw=$('perBox').value,p=Number(raw),capacity=Number($('location').value);
   let error='';
   if(!Number.isSafeInteger(q)||q<=0)error='入库数量必须为正整数。';
   else if(q>300)error='本单剩余可入库300把，本次数量不能超过300把。';
   else if(raw!==''&&(!Number.isSafeInteger(p)||p<=0))error='每箱数量必须为正整数，或留空。';
   else if(!$('receiptDate').value)error='请选择收货日期。';
   const validQ=Number.isSafeInteger(q)&&q>0;
   const canPack=validQ&&raw!==''&&Number.isSafeInteger(p)&&p>0;
   const boxes=canPack?Math.floor(q/p):null,tail=canPack?q%p:null,slots=canPack?Math.ceil(q/p):null;
   if(!error&&slots!==null&&slots>capacity)error=`当前库位仅余${capacity}箱位，本次需要${slots}箱位，请调整库位或数量。`;
   $('after').value=validQ?fmt(600+q):'—';$('boxes').value=boxes===null?'未计算':fmt(boxes)+' 箱';$('tail').value=tail===null?'未计算':fmt(tail)+' 把';$('slots').value=slots===null?'未计算':fmt(slots)+' 箱位';$('slotsAfter').value=slots===null?'未计算':fmt(Math.max(0,capacity-slots))+' 箱位';
   $('footerQuantity').textContent=validQ?fmt(q):'—';$('footerAfter').textContent=validQ?fmt(600+q):'—';$('footerRemaining').textContent=validQ?fmt(Math.max(0,300-q)):'—';$('formError').textContent=error;$('confirmReceipt').disabled=Boolean(error);
   return {q,slots,error};
  }
  ['quantity','perBox','receiptDate','location'].forEach(id=>$(id).addEventListener('input',calculate));
  $('zone').addEventListener('change',()=>{$('location').innerHTML=$('zone').value==='A区'?'<option value="100">A-01-01 · 剩余100箱位</option><option value="20">A-01-02 · 剩余20箱位</option>':'<option value="80">B-02-01 · 剩余80箱位</option>';calculate();});
  $('confirmReceipt').addEventListener('click',()=>{const {q,slots,error}=calculate();if(error)return;open('成品入库 · 确认结果示意',`<div class="source-overview">${tag('装配入库')}<h2>本次 ${fmt(q)} 把</h2></div>${fields([['生产单号','SC20260929001'],['订单号','DD20260921001'],['装配计划','PC20260929001'],['产品','CP000128 · 组合杯托折叠椅'],['实际颜色',$('color').value],['收货日期',$('receiptDate').value],['成品仓 / 库区','成品仓 / '+$('zone').value],['库位',$('location').selectedOptions[0].textContent.split(' · ')[0]],['入库人','当前仓管']])}<div class="summary-line"><span>累计入库：${fmt(600+q)} 把</span><span>剩余可入：${fmt(300-q)} 把</span><span>本次占用：${slots===null?'未计算':fmt(slots)+' 箱位'}</span></div><p class="draft-note">这是设计演示，未保存单据、未改变库存。开发后确认入库将直接记账，不增加审批环节。</p>`);});
  calculate();return;
 }
 const rows=[
  {id:1,category:'折叠椅',number:'CP000128',name:'组合杯托折叠椅',item:'HT-806',spec:'53 × 53 × 90 cm',color:'黑色',quantity:840,unit:'把',warehouse:'成品仓',zone:'A区',count:4,slots:210,date},
  {id:2,category:'折叠椅',number:'CP000128',name:'组合杯托折叠椅',item:'HT-806',spec:'53 × 53 × 90 cm',color:'蓝色',quantity:320,unit:'把',warehouse:'成品仓',zone:'A区',count:2,slots:80,date:'2026-09-28'},
  {id:3,category:'折叠床',number:'CP000156',name:'加宽折叠床',item:'HT-902',spec:'190 × 70 × 42 cm',color:'灰色',quantity:180,unit:'张',warehouse:'成品仓',zone:'B区',count:2,slots:180,date},
  {id:4,category:'折叠桌',number:'CP000093',name:'便携折叠桌',item:'HT-512',spec:'120 × 60 × 70 cm',color:'木纹色',quantity:240,unit:'张',warehouse:'成品仓',zone:'B区',count:3,slots:120,date:'2026-09-28'},
  {id:5,category:'折叠椅',number:'CP000128',name:'组合杯托折叠椅',item:'HT-806',spec:'53 × 53 × 90 cm',color:'黑色',quantity:160,unit:'把',warehouse:'成品仓',zone:'B区',count:1,slots:40,date:'2026-09-27'},
  {id:6,category:'折叠椅',number:'CP000207',name:'高背休闲椅',item:'HT-818',spec:'62 × 58 × 105 cm',color:'军绿色',quantity:96,unit:'把',warehouse:'成品仓',zone:'A区',count:1,slots:48,date:'2026-09-26'},
 ];
 const receipts=[
  {id:'CPRK20260929002',source:'装配入库',task:'SC20260929001',order:'DD20260921001',plan:'PC20260929001',number:'CP000128',name:'组合杯托折叠椅',spec:'53 × 53 × 90 cm',color:'黑色',quantity:200,unit:'把',warehouse:'成品仓',zone:'A区',location:'A-01-02',date,actor:'当前仓管',perBox:4,before:400,after:600},
  {id:'CPRK20260928003',source:'装配入库',task:'SC20260929001',order:'DD20260921001',plan:'PC20260929001',number:'CP000128',name:'组合杯托折叠椅',spec:'53 × 53 × 90 cm',color:'黑色',quantity:400,unit:'把',warehouse:'成品仓',zone:'A区',location:'A-01-01',date:'2026-09-28',actor:'当前仓管',perBox:4,before:0,after:400},
  {id:'CPRK20260927001',source:'生产入库',task:'SC20260918002',order:'DD20260918002',plan:'—',number:'CP000128',name:'组合杯托折叠椅',spec:'53 × 53 × 90 cm',color:'黑色',quantity:200,unit:'把',warehouse:'成品仓',zone:'A区',location:'A-01-03',date:'2026-09-27',actor:'当前仓管',perBox:4},
  {id:'CPRK20260926001',source:'样品入库',task:'—',order:'—',plan:'YPRK20260926001',number:'CP000128',name:'组合杯托折叠椅',spec:'53 × 53 × 90 cm',color:'黑色',quantity:40,unit:'把',warehouse:'成品仓',zone:'A区',location:'A-02-01',date:'2026-09-26',actor:'当前仓管',perBox:4},
 ];
 let tab=new URLSearchParams(location.search).get('tab')==='records'?'records':'stock';const selected=new Set();
 function matching(r){const q=$('search').value.trim().toLowerCase();return (!q||Object.values(r).join(' ').toLowerCase().includes(q))&&(!$('warehouseFilter').value||r.warehouse===$('warehouseFilter').value)&&(!$('zoneFilter').value||r.zone===$('zoneFilter').value)&&(tab!=='records'||!$('sourceFilter').value||r.source===$('sourceFilter').value);}
 function selection(){ $('selectionText').textContent=`已选 ${selected.size} 条`;$('outboundButton').disabled=!selected.size; }
 function render(){
  const records=tab==='records',filtered=(records?receipts:rows).filter(matching);
  $('stockTableWrap').hidden=records;$('recordTableWrap').hidden=!records;$('sourceFilter').hidden=!records;$('selectionText').hidden=records;$('outboundButton').hidden=records;
  $('stockTab').classList.toggle('active',!records);$('recordsTab').classList.toggle('active',records);$('stockTab').setAttribute('aria-selected',String(!records));$('recordsTab').setAttribute('aria-selected',String(records));
  $('search').placeholder=records?'搜索入库单号、生产单号、品号或品名':'搜索品号、品名、货号、规格或颜色';
  $('tableHint').textContent=records?'按原单逐笔保留来源；点击查看打开详情弹窗':'同产品、颜色、单位及库区汇总；来源和具体库位在详情中查看';
  $('headingCount').textContent=`共 ${filtered.length} 条${records?'入库':'库存'}记录`;$('totalText').textContent=`共 ${filtered.length} 条`;
  const tbody=$(records?'recordsTable':'stockTable').querySelector('tbody');
  tbody.innerHTML=filtered.map(r=>records?`<tr><td title="${r.id}">${r.id}</td><td>${tag(r.source,r.source==='样品入库'?'info':'brand')}</td><td>${r.task}</td><td>${r.number}</td><td class="main">${r.name}</td><td>${r.spec}</td><td>${r.color}</td><td class="number">${fmt(r.quantity)}</td><td>${r.unit}</td><td>${r.warehouse}</td><td>${r.zone}</td><td>${r.location}</td><td>${r.date}</td><td>${tag('已入库','success')}</td><td><button class="link" data-receipt="${r.id}">查看</button></td></tr>`:`<tr class="${selected.has(r.id)?'selected':''}"><td class="center"><input type="checkbox" aria-label="选择${r.number}${r.color}${r.zone}" data-row="${r.id}" ${selected.has(r.id)?'checked':''}></td><td>${r.category}</td><td>${r.number}</td><td class="main">${r.name}</td><td>${r.item}</td><td>${r.spec}</td><td>${r.color}</td><td class="number">${fmt(r.quantity)}</td><td>${r.unit}</td><td>${r.warehouse}</td><td>${r.zone}</td><td class="number">${r.count}</td><td class="number">${r.slots}</td><td>${r.date}</td><td><button class="link" data-stock="${r.id}">库存详情</button></td></tr>`).join('');
  $(records?'recordEmptyState':'emptyState').hidden=filtered.length>0;
  document.querySelectorAll('[data-row]').forEach(el=>el.addEventListener('change',()=>{const id=Number(el.dataset.row);el.checked?selected.add(id):selected.delete(id);el.closest('tr').classList.toggle('selected',el.checked);selection();}));
  document.querySelectorAll('[data-stock]').forEach(el=>el.addEventListener('click',()=>showStock(rows.find(r=>r.id===Number(el.dataset.stock)))));
  document.querySelectorAll('[data-receipt]').forEach(el=>el.addEventListener('click',()=>showReceipt(receipts.find(r=>r.id===el.dataset.receipt))));selection();
 }
 function showStock(r){
  const locations=r.id===1?[['A-01-01','400','把','100'],['A-01-02','200','把','50'],['A-01-03','200','把','50'],['A-02-01','40','把','10']]:[[r.zone==='A区'?'A-03-01':'B-02-01',fmt(r.quantity),r.unit,fmt(r.slots)]];
  open('成品库存 · 库位详情',`<div class="source-overview"><h2>${esc(r.name)}</h2><span class="muted">当前库存 ${fmt(r.quantity)} ${r.unit}</span></div>${fields([['品号',r.number],['货号',r.item],['类别',r.category],['规格',r.spec],['颜色',r.color],['仓库 / 库区',r.warehouse+' / '+r.zone]])}<section class="source-window-section"><h2>存放库位</h2>${table(['库位','当前数量','单位','占用箱位'],locations)}</section><p class="draft-note">库存已按实物汇总；入库记录用于查看生产、装配或样品来源。明细中的入库数量不会因为出库而减少。</p>`);
 }
 function showReceipt(r){open('成品入库 · 来源详情',`<div class="source-overview"><h2>${r.id}</h2>${tag(r.source,r.source==='样品入库'?'info':'brand')}${tag('已入库','success')}</div>${fields([['生产单号',r.task],['订单号',r.order],[r.source==='样品入库'?'样品来源单':'装配计划',r.plan],['收货日期',r.date],['成品仓 / 库区',r.warehouse+' / '+r.zone],['库位',r.location],['入库人',r.actor],['供应商','—'],['备注','分次收货，按实际包装入库']])}<section class="source-window-section"><h2>成品明细</h2>${table(['品号','品名','规格','颜色','数量','单位'],[[r.number,r.name,r.spec,r.color,fmt(r.quantity),r.unit]])}</section><div class="summary-line"><span>每箱数量：${r.perBox} ${r.unit}</span><span>整箱数：${r.quantity/r.perBox} 箱</span><span>尾数：0 ${r.unit}</span><span>占用箱位：${r.quantity/r.perBox}</span></div>${r.after!==undefined?`<p class="draft-note">本单入库前 ${r.before} 把，本次 ${r.quantity} 把，入库后累计 ${r.after} 把；该订单产品上限 1,020 把。</p>`:'<p class="draft-note">历史生产与样品来源按原单保留，不补造装配计划。</p>'}`);}
 function switchTab(value){tab=value;$('search').value='';$('sourceFilter').value='';selected.clear();render();}
 $('stockTab').addEventListener('click',()=>switchTab('stock'));$('recordsTab').addEventListener('click',()=>switchTab('records'));
 $('queryButton').addEventListener('click',render);$('search').addEventListener('keydown',e=>{if(e.key==='Enter')render();});
 ['warehouseFilter','zoneFilter','sourceFilter'].forEach(id=>$(id).addEventListener('change',()=>{selected.clear();render();}));
 ['resetFilters','resetRecordFilters'].forEach(id=>$(id).addEventListener('click',()=>{['search','warehouseFilter','zoneFilter','sourceFilter'].forEach(key=>$(key).value='');render();}));
 $('refreshButton').addEventListener('click',()=>{render();notice('设计示例已刷新，未读取业务库存。');});
 $('selectAll').addEventListener('change',e=>{rows.filter(matching).forEach(r=>e.target.checked?selected.add(r.id):selected.delete(r.id));render();});
 $('configButton').addEventListener('click',()=>open('仓库配置 · 保留现有入口','<p>仓库信息、库区与库位维护沿用现有功能。本次仅审核成品库存与入库页面，不修改仓库配置规则。</p>'));
 $('otherInbound').addEventListener('click',()=>open('其他入库 · 保留现有入口','<p>既有生产入库、批量入库功能继续保留；样品入库仍从样品流程办理。</p><p>装配入库与既有生产入库共用订单累计额度，不能更换入口重复入库。</p>'));
 $('outboundButton').addEventListener('click',()=>open('批量出库 · 保留现有流程',`<p>已选择 ${selected.size} 条库存。此操作沿用现有成品出库流程，本轮未设计或修改出库规则。</p><p class="draft-note">设计预览不会出库，也不会扣减库存。</p>`));
 render();
})();
