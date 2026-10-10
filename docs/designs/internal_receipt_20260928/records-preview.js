// 仅用于可审阅的页面原型。示例数据保存在内存中，不访问库存或业务接口。
(() => {
  const records = window.receiptPreviewRecords || [];
  const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const tag = (value, color) => `<span class="tag ${color}">${escape(value)}</span>`;
  let selected = '';
  function detail(row) {
    if (!row || !window.receiptSourceWindow) return;
    const external = row.source === '外发入库';
    const fields = [
      [external ? '来源外发单' : '来源计划', row.plan],
      ['生产订单', row.order], ['产品', '折叠椅'],
      ['工序', row.craft], ['订单数量', '1000 把'],
      [external ? '加工厂' : '生产车间', external ? '演示喷塑厂' : `${row.craft}车间`],
      ['入库单号', row.id], ['收货日期', '2026-09-28'], ['入库人', '当前仓管'],
      ['材料仓', '半成品仓'], ['库区', '一楼'], ['入库状态', '已入库'],
    ];
    const body = `<div class="source-overview">${tag(row.source,row.kind)}<h2>${external?'外发回货来源':'厂内加工来源'}</h2><span class="muted">设计预览 · 示例数据</span></div>
      <dl class="source-fields">${fields.map(([key,value])=>`<div class="source-field"><dt>${key}</dt><dd>${escape(value)}</dd></div>`).join('')}</dl>
      <section class="source-section"><h2>本次入库明细</h2><div class="table-card"><table><colgroup><col style="width:150px"><col style="width:300px"><col style="width:100px"><col style="width:160px"><col style="width:80px"><col style="width:calc(100% - 790px)"></colgroup><thead><tr><th>部位</th><th>材质 / 规格</th><th>颜色</th><th>加工阶段</th><th>单位</th><th class="number">本次入库</th></tr></thead><tbody><tr><td class="main">${escape(row.part)}</td><td>${escape(row.spec)}</td><td>${escape(row.color || '—')}</td><td>${escape(row.stage)}</td><td>${escape(row.unit)}</td><td class="number">${row.qty.toLocaleString('zh-CN')}</td></tr></tbody></table></div></section>
      <section class="source-section"><h2>本次入库时的数量</h2><dl class="source-snapshot">${[['应入库',row.demand],['入库前已入',row.before],['入库后已入',row.before+row.qty],['当时剩余',row.demand-row.before-row.qty]].map(([key,value])=>`<div><dt>${key}</dt><dd>${value.toLocaleString('zh-CN')} ${escape(row.unit)}</dd></div>`).join('')}</dl></section>
      <div class="source-note"><span>备注</span>分批收货</div>`;
    window.receiptSourceWindow.open(external ? '外发入库来源详情' : '厂内入库来源详情', body);
  }
  function render() {
    const keyword = document.getElementById('search').value.trim();
    const source = document.getElementById('source').value;
    const dates = [...document.querySelectorAll('.filters input[type=date]')].map(e=>e.value);
    const visible = records.filter(row => (!keyword || Object.values(row).join(' ').includes(keyword) || '折叠椅'.includes(keyword)) && (!source || row.source===source) && (!dates[0] || dates[0]<='2026-09-28') && (!dates[1] || dates[1]>='2026-09-28'));
    document.getElementById('count').textContent=visible.length;
    document.getElementById('pagerCount').textContent=visible.length;
    document.getElementById('recordRows').innerHTML=visible.map(row=>`<tr class="${row.id===selected?'selected':''}"><td>${escape(row.id)}</td><td>${tag(row.source,row.kind)}</td><td title="${escape(row.order)}">${escape(row.order)}</td><td class="main">折叠椅</td><td class="main">${escape(row.part)}</td>${[row.category,row.material,row.size,row.color,row.thickness,row.stage].map(value=>`<td title="${escape(value || '—')}">${escape(value || '—')}</td>`).join('')}<td class="number">${row.qty.toLocaleString('zh-CN')}</td><td>${escape(row.unit)}</td><td class="date-cell">2026-09-28</td><td>${tag('已入库','success')}</td><td class="action-cell"><button class="link" data-id="${escape(row.id)}">查看</button></td></tr>`).join('') || '<tr><td colspan="16">没有符合条件的记录，请调整筛选条件。</td></tr>';
    document.querySelectorAll('[data-id]').forEach(button=>button.onclick=()=>{
      selected=button.dataset.id;
      document.querySelectorAll('#recordRows tr').forEach(row=>row.classList.toggle('selected',row.contains(button)));
      detail(records.find(row=>row.id===selected));
    });
  }
  document.getElementById('filters').onsubmit=event=>{event.preventDefault();render();};
  document.getElementById('source').onchange=render;
  document.getElementById('filters').onreset=()=>setTimeout(render,0);
  document.getElementById('refresh').onclick=render;
  render();
})();
