<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElButton, ElCheckbox, ElDatePicker, ElInput, ElOption, ElSelect, ElTooltip } from 'element-plus'
import AppWindowDialog from '../../../src/frontend/src/components/common/AppWindowDialog.vue'
import DesignTable from './DesignTable.vue'

const props = defineProps<{ page: string }>()
const emit = defineEmits<{ navigate: [view: string] }>()
const detailState = ref('processing')
const keyword = ref('')
const stageFilter = ref('')
const sourceFilter = ref('')
const dateRange = ref<string[]>(['2026-09-01', '2026-09-29'])
const sourceVisible = ref(false)
const issuePickerVisible = ref(false)
const issueConfirmVisible = ref(false)
const cancelVisible = ref(false)
const dispatchVisible = ref(false)
const dispatchDate = ref('2026-09-29')
const selectedRecord = ref('r-a')
const selectedStages = ref(['COATED', 'UNCOATED'])
const coatedQuantity = ref('60')
const uncoatedQuantity = ref('40')
const designMessage = ref('')

watch(() => props.page, () => {
  keyword.value = ''
  stageFilter.value = ''
  sourceFilter.value = ''
  sourceVisible.value = false
  designMessage.value = ''
})

const columns = (entries: Array<[string, string, number, boolean?]>) => entries.map(([key, label, width, num]) => ({ key, label, width, num }))
const detailColumnsBase = columns([
  ['factory', '加工厂', 148], ['product', '订单产品', 120], ['part', '部位', 82], ['material', '材质', 82],
  ['spec', '规格', 82], ['thickness', '厚度', 74], ['length', '长度', 84], ['original', '原状态', 92],
  ['color', '喷塑颜色', 92], ['sent', '实际发出', 94, true], ['received', '实际回货', 94, true],
  ['difference', '少回差额', 94, true], ['reason', '差额原因', 154], ['zone', '目标库区', 130],
])
const detailColumns = computed(() => detailColumnsBase.filter(column => detailState.value === 'ended' || !['received', 'difference', 'reason', 'zone'].includes(column.key)))
const allocations = [
  { id: 'a', factory: '永盛喷塑厂', product: '组合杯托折叠椅', part: '前腿管', material: 'Q195', spec: '圆管 Φ22', thickness: '0.8 mm', length: '650 mm', original: '未喷塑', color: '黑色', sent: 600, received: 590, difference: 10, reason: '表面涂层不均，少回10支', zone: '一楼 A区' },
  { id: 'b', factory: '华诚喷塑厂', product: '组合杯托折叠椅', part: '前腿管', material: 'Q195', spec: '圆管 Φ22', thickness: '0.8 mm', length: '650 mm', original: '未喷塑', color: '黑色', sent: 400, received: 400, difference: 0, reason: '—', zone: '一楼 A区' },
  { id: 'c', factory: '永盛喷塑厂', product: '组合杯托折叠椅', part: '后腿管', material: 'Q195', spec: '圆管 Φ22', thickness: '0.8 mm', length: '720 mm', original: '未喷塑', color: '黑色', sent: 300, received: 280, difference: 20, reason: '外观划伤，少回20支', zone: '一楼 A区' },
  { id: 'd', factory: '华诚喷塑厂', product: '组合杯托折叠椅', part: '扶手管', material: 'Q195', spec: '椭圆管 30×15', thickness: '0.9 mm', length: '520 mm', original: '未喷塑', color: '黑色', sent: 200, received: 0, difference: 200, reason: '本项无合格件回货', zone: '—' },
  { id: 'e', factory: '永盛喷塑厂', product: '组合杯托折叠椅', part: '连接管', material: 'Q195', spec: '圆管 Φ16', thickness: '0.7 mm', length: '360 mm', original: '未喷塑', color: '黑色', sent: 100, received: 100, difference: 0, reason: '—', zone: '一楼 A区' },
]
const detailRows = computed(() => allocations.map(row => ({ ...row,
  sent: detailState.value === 'pending' ? '—' : `${row.sent} 支`,
  received: detailState.value === 'ended' ? `${row.received} 支` : '—',
  difference: detailState.value === 'ended' ? `${row.difference} 支` : '—',
  reason: detailState.value === 'ended' ? row.reason : '—',
  zone: detailState.value === 'ended' ? row.zone : '—',
})))
const detailStatus = computed(() => ({ pending: '待外发', processing: '加工中', ended: '已结束' }[detailState.value] || '加工中'))
const detailTone = computed(() => detailState.value === 'ended' ? 'success' : detailState.value === 'pending' ? 'warning' : 'info')

const stockColumns = columns([
  ['part', '部位', 116], ['material', '材质', 100], ['spec', '规格', 100], ['thickness', '厚度', 90], ['length', '长度', 100],
  ['stage', '加工状态', 116], ['color', '实物颜色', 112], ['quantity', '当前库存', 116, true], ['unit', '单位', 64],
  ['warehouse', '材料仓', 116], ['zone', '库区', 96], ['date', '最近入库', 120], ['action', '操作', 96],
])
const stocks = [
  { id: 's1', part: '前腿管', material: 'Q195', spec: '圆管 Φ22', thickness: '0.8 mm', length: '650 mm', stage: '已喷塑', stageKey: 'COATED', color: '黑色', quantity: '1,800', unit: '支', warehouse: '半成品管材仓', zone: '一楼 A区', date: '2026-09-29' },
  { id: 's2', part: '前腿管', material: 'Q195', spec: '圆管 Φ22', thickness: '0.8 mm', length: '650 mm', stage: '未喷塑', stageKey: 'UNCOATED', color: '原料本色', quantity: '3,600', unit: '支', warehouse: '半成品管材仓', zone: '一楼 B区', date: '2026-09-29' },
  { id: 's3', part: '后腿管', material: 'Q195', spec: '圆管 Φ22', thickness: '0.8 mm', length: '720 mm', stage: '已喷塑', stageKey: 'COATED', color: '黑色', quantity: '990', unit: '支', warehouse: '半成品管材仓', zone: '一楼 A区', date: '2026-09-29' },
  { id: 's4', part: '后腿管', material: 'Q195', spec: '圆管 Φ22', thickness: '0.8 mm', length: '720 mm', stage: '未喷塑', stageKey: 'UNCOATED', color: '原料本色', quantity: '2,200', unit: '支', warehouse: '半成品管材仓', zone: '一楼 B区', date: '2026-09-28' },
  { id: 's5', part: '连接管', material: 'Q195', spec: '圆管 Φ16', thickness: '0.7 mm', length: '360 mm', stage: '已喷塑', stageKey: 'COATED', color: '黑色', quantity: '720', unit: '支', warehouse: '半成品管材仓', zone: '一楼 A区', date: '2026-09-29' },
]
const stockRows = computed(() => stocks.filter(row => (!stageFilter.value || row.stageKey === stageFilter.value) && (!keyword.value || `${row.part}${row.material}${row.spec}${row.color}`.includes(keyword.value))))

const recordColumns = columns([
  ['number', '入库单号', 164], ['source', '入库来源', 108], ['order', '生产订单', 148], ['product', '产品', 136], ['part', '部位', 90],
  ['material', '材质', 74], ['spec', '规格', 98], ['thickness', '厚度', 84], ['length', '长度', 94], ['color', '颜色', 94], ['stage', '加工状态', 104],
  ['quantity', '入库数量', 100, true], ['date', '入库日期', 114], ['action', '操作', 76],
])
const records = [
  ...allocations.filter(row => row.received > 0).map(row => ({ ...row, id: `r-${row.id}`, number: 'RS20260929001', source: '外发入库', order: 'SC20260929001', stage: '已喷塑', quantity: `${row.received} 支`, date: '2026-09-29', original: 'WF20260929001', warehouse: '半成品管材仓 / 一楼 A区' })),
  { id: 'r3', number: 'RI20260929003', source: '厂内入库', order: 'SC20260929001', product: '组合杯托折叠椅', part: '前腿管', material: 'Q195', spec: '圆管 Φ22', thickness: '0.8 mm', length: '650 mm', color: '原料本色', stage: '未喷塑', quantity: '200 支', date: '2026-09-29', factory: '金工车间', original: 'PC20260929001', warehouse: '半成品管材仓 / 一楼 B区', sent: 0, difference: 0 },
  { id: 'r6', number: 'RI20260929004', source: '厂内入库', order: 'SC20260929001', product: '组合杯托折叠椅', part: '后腿管', material: 'Q195', spec: '圆管 Φ22', thickness: '0.8 mm', length: '720 mm', color: '原料本色', stage: '未喷塑', quantity: '200 支', date: '2026-09-29', factory: '金工车间', original: 'PC20260929001', warehouse: '半成品管材仓 / 一楼 B区', sent: 0, difference: 0 },
]
const recordRows = computed(() => records.filter(row =>
  (!sourceFilter.value || row.source === sourceFilter.value)
  && (!keyword.value || `${row.number}${row.order}${row.part}`.includes(keyword.value))
  && (!dateRange.value?.length || (row.date >= dateRange.value[0]! && row.date <= dateRange.value[1]!)),
))
const activeRecord = computed(() => records.find(row => row.id === selectedRecord.value) || records[0]!)
function openSource(id = 'r-a') { selectedRecord.value = id; sourceVisible.value = true }
function openStockSource(id: string) { const recordId: Record<string, string> = { s1: 'r-a', s2: 'r3', s3: 'r-c', s4: 'r6', s5: 'r-e' }; openSource(recordId[id] || 'r-a') }

const issueColumns = columns([
  ['part', '部位', 116], ['material', '材质', 90], ['spec', '规格', 88], ['thickness', '厚度', 90], ['length', '长度', 100],
  ['stage', '加工状态', 112], ['color', '实物颜色', 116], ['zone', '库区', 110], ['stock', '公共可用', 112, true],
  ['quantity', '本次申请（支）', 176, true], ['remaining', '预计库存结余', 140, true],
])
const issueRows = computed(() => stocks.slice(0, 2).filter(row => selectedStages.value.includes(row.stageKey)).map(row => ({ ...row, stock: row.stageKey === 'COATED' ? 1800 : 3600 })))
const issueTotal = computed(() => (selectedStages.value.includes('COATED') ? Number(coatedQuantity.value || 0) : 0) + (selectedStages.value.includes('UNCOATED') ? Number(uncoatedQuantity.value || 0) : 0))
const issueError = computed(() => {
  const values = issueRows.value.map(row => row.stageKey === 'COATED' ? coatedQuantity.value : uncoatedQuantity.value)
  if (!values.length) return '请先选择本次领用的半成品。'
  if (values.some(value => !/^\d+$/.test(value) || Number(value) <= 0)) return '每个已选状态须填写正整数支数。'
  if (issueTotal.value > 100) return `两种状态共用100支额度，当前合计${issueTotal.value}支，超出${issueTotal.value - 100}支。`
  return ''
})
function issueQuantity(stage: string) { return stage === 'COATED' ? coatedQuantity.value : uncoatedQuantity.value }
function setIssueQuantity(stage: string, value: string) { if (stage === 'COATED') coatedQuantity.value = value; else uncoatedQuantity.value = value }
function stockRemainder(stock: number, stage: string) { const quantity = Number(issueQuantity(stage)); return Number.isFinite(quantity) && quantity >= 0 ? `${Math.max(0, stock - quantity).toLocaleString('zh-CN')} 支` : '—' }
function showDesignResult(message: string) { designMessage.value = message; issueConfirmVisible.value = false; cancelVisible.value = false }
function confirmDispatchPreview() { dispatchVisible.value = false; detailState.value = 'processing'; showDesignResult('已切换至加工中设计状态；没有发出业务单据、扣减库存或改变预留。') }

const historyColumns = columns([['date', '记录日期', 130], ['kind', '历史操作', 138], ['number', '原单据', 208], ['part', '部位', 110], ['quantity', '数量', 104, true], ['result', '原结果 / 原说明', 526]])
const historyRows = [
  { id: 'h1', date: '2026-09-18', kind: '原料发出', number: 'FL-历史示意-01', part: '前腿管', quantity: '100 支', result: '原发料凭证保留，根数、米数见原单；接续不重复扣原料' },
  { id: 'h2', date: '2026-09-20', kind: '分批回货', number: 'RH-历史示意-01', part: '前腿管', quantity: '60 支', result: '历史有效入库保留，不通过新入口重复入库' },
  { id: 'h3', date: '2026-09-22', kind: '分批回货', number: 'RH-历史示意-02', part: '前腿管', quantity: '30 支', result: '历史有效入库保留' },
  { id: 'h4', date: '2026-09-23', kind: '备注结清', number: 'JQ-历史示意-01', part: '前腿管', quantity: '10 支', result: '原少回说明：加工损坏；保留原差额，不恢复额度' },
]
</script>

<template>
  <div class="design-page review-stock-page">
    <template v-if="page === 'detail'">
      <header class="page-heading"><div class="title-row"><h1>外发单详情</h1><span class="status" :class="detailTone">{{ detailStatus }}</span></div><div class="actions"><span class="muted">评审状态</span><ElSelect v-model="detailState" style="width:120px"><ElOption label="待外发" value="pending" /><ElOption label="加工中" value="processing" /><ElOption label="已结束" value="ended" /></ElSelect><ElButton @click="emit('navigate', 'history')">历史单示例</ElButton><ElButton v-if="detailState === 'pending'" @click="cancelVisible = true">取消待发计划</ElButton><ElButton v-if="detailState === 'pending'" type="primary" @click="dispatchVisible = true">确认发出</ElButton><ElButton v-if="detailState === 'processing'" type="primary" @click="emit('navigate', 'receipt')">喷塑入库</ElButton><ElButton v-if="detailState === 'ended'" @click="emit('navigate', 'records')">查看入库记录</ElButton></div></header>
      <section class="panel"><div class="section-heading"><h2>单据信息</h2><span class="muted">WF20260929001</span></div><div class="info-grid review-info-grid"><div class="info-cell"><span>生产订单</span><strong>SC20260929001</strong></div><div class="info-cell"><span>排产计划</span><strong>PC20260929001</strong></div><div class="info-cell"><span>订单产品</span><strong>组合杯托折叠椅 · 1,000 把</strong></div><div class="info-cell"><span>加工工艺</span><strong>喷塑</strong></div><div class="info-cell"><span>发出来源</span><strong>厂内已加工件</strong></div><div class="info-cell"><span>来源实物</span><strong>未喷塑 · 原料本色</strong></div><div class="info-cell"><span>要求回货日期</span><strong>2026-10-14</strong></div><div class="info-cell"><span>创建人</span><strong>仓管员（设计示例）</strong></div></div></section>
      <div v-if="detailState === 'pending'" class="notice">已预留 1,600 支金工完成额度；确认发出时记实际交接，取消待发计划释放预留。原料已领，不重复扣库。</div>
      <div v-else-if="detailState === 'processing'" class="notice">已按支记录金工直接交接，原料不重复扣库。整单准备好后统一登记一次回货；本单共 2 个加工厂、5 条明细。</div>
      <div v-else class="notice">本单已完成一次回货登记，现为只读。实收 1,370 支已入已喷塑公共库存；少回 230 支保留在原单，不恢复原料或已用额度。</div>
      <section class="review-summary-strip"><div><span>{{ detailState === 'pending' ? '计划发出' : '实际发出' }}</span><strong>1,600 <small>支</small></strong></div><div><span>实际回货</span><strong>{{ detailState === 'ended' ? '1,370' : '—' }} <small v-if="detailState === 'ended'">支</small></strong></div><div v-if="detailState === 'ended'"><span>少回差额</span><strong :class="{ 'review-warning': detailState === 'ended' }">{{ detailState === 'ended' ? '230' : '—' }} <small v-if="detailState === 'ended'">支</small></strong></div><div v-else><span>回货方式</span><strong class="review-summary-text">整单一次</strong></div><div><span>办理结果</span><strong class="review-summary-text">{{ detailState === 'ended' ? '已结束 · 全单只读' : detailState === 'pending' ? '待确认发出' : '待整单一次回货' }}</strong></div></section>
      <div class="section-heading"><h2>分厂与部位明细</h2><span class="muted">各行独立核对，不能跨厂或跨部位抵消差额</span></div>
      <DesignTable class="fill-table" :columns="detailColumns" :rows="detailRows"><template #cell-original="{ value }"><span class="status neutral">{{ value }}</span></template><template #cell-difference="{ value }"><span :class="value !== '0 支' && detailState === 'ended' ? 'review-warning' : ''">{{ value }}</span></template></DesignTable>
      <footer class="footer-bar"><span class="muted">{{ detailState === 'ended' ? '回货登记：2026-09-29 · 操作人：仓管员 · 结果单 RS20260929001' : '发出与回货分别记录真实流水；半成品喷塑转换不重复计算金工首次产出。' }}</span><ElButton v-if="detailState === 'ended'" @click="openSource()">查看来源与流水</ElButton><ElButton v-else @click="emit('navigate', 'metal')">查看加工来源</ElButton></footer>
    </template>

    <template v-else-if="page === 'history'">
      <header class="page-heading"><div class="title-row"><h1>历史外发单详情</h1><span class="status neutral">历史只读</span><span class="status success">已结清</span></div><div class="actions"><ElButton @click="emit('navigate', 'detail')">返回新单示例</ElButton></div></header>
      <div class="notice">以下为历史展示设计示例。原分批回货、返工及备注结清记录保留查询；已结束历史单不重新开放补登记，不自动清零差额。</div>
      <section class="panel"><div class="section-heading"><h2>原单信息</h2><span class="muted">WF-历史示意-01</span></div><div class="info-grid review-info-grid"><div class="info-cell"><span>原生产订单</span><strong>SC-历史示意-01</strong></div><div class="info-cell"><span>原来源</span><strong>原管材外发</strong></div><div class="info-cell"><span>原加工厂</span><strong>永盛喷塑厂</strong></div><div class="info-cell"><span>原结束方式</span><strong>备注结清</strong></div></div></section>
      <section class="review-summary-strip"><div><span>原实际发出</span><strong>100 <small>支</small></strong></div><div><span>历史累计回货</span><strong>90 <small>支</small></strong></div><div><span>原结清差额</span><strong class="review-warning">10 <small>支</small></strong></div><div><span>新入口可办理</span><strong class="review-summary-text">已结束，不再办理</strong></div></section>
      <div class="section-heading"><h2>原单操作记录</h2><span class="muted">原单号、时间、数量与说明按历史凭证保留</span></div><DesignTable class="fill-table" :columns="historyColumns" :rows="historyRows" />
      <section class="panel"><div class="section-heading"><h2>历史返工记录</h2><span class="muted">本示例单无返工记录</span></div><p class="muted">存在返工历史的原单在此展示原返工单、关联回货与处理记录；只提供查看。</p></section>
      <footer class="footer-bar"><span class="muted">旧在途单另按核准接续清单办理：可登记余额须扣除历史已收及已实际处置数量。</span><ElButton @click="showDesignResult('历史原始凭证仅作查询；此处为设计演示。')">查看原始凭证</ElButton></footer>
    </template>

    <template v-else-if="page === 'stock'">
      <header class="page-heading"><div class="title-row"><h1>材料库存</h1><ElRadioGroup model-value="SEMI" aria-label="库存性质"><ElRadioButton value="RAW" @click="showDesignResult('原材料区域沿用现有ERP，此处展示半成品设计。')">原材料</ElRadioButton><ElRadioButton value="SEMI">半成品</ElRadioButton></ElRadioGroup><span class="muted">共 {{ stockRows.length }} 条</span></div><div class="actions"><ElButton @click="emit('navigate', 'records')">入库记录</ElButton><ElButton @click="emit('navigate', 'metal-picker')">金工入库</ElButton><ElButton type="primary" @click="emit('navigate', 'receipt-picker')">喷塑入库</ElButton></div></header>
      <div class="filterbar"><ElInput v-model="keyword" clearable placeholder="搜索部位、材质、规格或颜色" style="width:350px" /><ElSelect model-value="管材" style="width:142px"><ElOption label="材料分类：管材" value="管材" /></ElSelect><ElSelect model-value="半成品管材仓" style="width:160px"><ElOption label="半成品管材仓" value="半成品管材仓" /></ElSelect><ElSelect placeholder="库区：全部" clearable style="width:150px"><ElOption label="一楼 A区" value="A"/><ElOption label="一楼 B区" value="B"/></ElSelect><ElButton @click="keyword = ''; stageFilter = ''">重置</ElButton><span class="muted">同属性、同加工状态的实物跨订单共用</span></div>
      <div class="toolbar"><ElSelect v-model="stageFilter" clearable placeholder="加工状态：全部" style="width:166px"><ElOption label="未喷塑" value="UNCOATED" /><ElOption label="已喷塑" value="COATED" /></ElSelect><span class="muted">未喷塑匹配原料本色；已喷塑按目标喷塑色匹配。</span><ElButton @click="emit('navigate', 'dispatch-semi')">未喷塑半成品外发</ElButton></div>
      <DesignTable class="fill-table" :columns="stockColumns" :rows="stockRows"><template #cell-stage="{ row, value }"><span class="status" :class="row.stageKey === 'COATED' ? 'success' : 'neutral'">{{ value }}</span></template><template #cell-action="{ row }"><ElButton link type="primary" @click="openStockSource(row.id)">来源记录</ElButton></template></DesignTable>
      <footer class="footer-bar"><span class="muted">按实物属性、加工状态和库区汇总；这里显示库存，不要求选择原采购或回货批次。</span><span>共 {{ stockRows.length }} 条 · 50 条/页</span></footer>
    </template>

    <template v-else-if="page === 'records'">
      <header class="page-heading"><div class="title-row"><h1>半成品入库记录</h1><span class="muted">共 {{ recordRows.length }} 条明细</span></div><div class="actions"><ElButton @click="emit('navigate', 'stock')">公共半成品库存</ElButton><ElButton type="primary" @click="emit('navigate', 'receipt-picker')">喷塑入库</ElButton></div></header>
      <div class="filterbar"><ElInput v-model="keyword" clearable placeholder="搜索入库单号、生产订单或部位" style="width:330px" /><ElSelect v-model="sourceFilter" clearable placeholder="入库来源：全部" style="width:165px"><ElOption label="厂内入库" value="厂内入库" /><ElOption label="外发入库" value="外发入库" /></ElSelect><ElDatePicker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" style="width:280px" /><ElButton @click="keyword = ''; sourceFilter = ''">重置</ElButton></div>
      <div class="toolbar"><span class="muted">按实际入库明细展示；整单零回货在外发单保留结果，不产生零数量入库记录。</span></div>
      <DesignTable class="fill-table" :columns="recordColumns" :rows="recordRows"><template #cell-source="{ value }"><span class="status" :class="value === '外发入库' ? 'info' : 'neutral'">{{ value }}</span></template><template #cell-stage="{ value }"><span class="status" :class="value === '已喷塑' ? 'success' : 'neutral'">{{ value }}</span></template><template #cell-action="{ row }"><ElButton link type="primary" @click="openSource(row.id)">查看</ElButton></template></DesignTable>
      <footer class="footer-bar"><span class="muted">入库明细保留订单用途与原单据；公共实物库存合并累计。</span><span>共 {{ recordRows.length }} 条 · 50 条/页</span></footer>
    </template>

    <template v-else-if="page === 'issue'">
      <header class="page-heading"><div class="title-row"><h1>生产领料</h1><span class="status info">装配领用</span><span class="muted">半成品分区</span></div><div class="actions"><ElButton @click="emit('navigate', 'stock')">查看公共库存</ElButton></div></header>
      <section class="panel"><div class="info-grid review-info-grid"><div class="info-cell"><span>生产订单</span><strong>SC20260929001</strong></div><div class="info-cell"><span>订单产品</span><strong>组合杯托折叠椅 · 1,000 把</strong></div><div class="info-cell"><span>本次部位</span><strong>前腿 · 2 支/把</strong></div><div class="info-cell"><span>目标喷塑色</span><strong>黑色</strong></div></div></section>
      <section class="review-summary-strip"><div><span>部位净需求</span><strong>2,000 <small>支</small></strong></div><div><span>累计已领取</span><strong>1,860 <small>支</small></strong></div><div><span>待审核占用</span><strong>40 <small>支</small></strong></div><div><span>两种状态共用可领</span><strong class="brand">100 <small>支</small></strong></div></section>
      <div class="section-heading"><h2>本次领用明细</h2><span class="muted">允许未喷塑、已喷塑混领；合计不超过同部位剩余需求</span><ElButton @click="issuePickerVisible = true">选择公共半成品</ElButton></div>
      <DesignTable class="fill-table" :columns="issueColumns" :rows="issueRows"><template #cell-stage="{ row, value }"><span class="status" :class="row.stageKey === 'COATED' ? 'success' : 'neutral'">{{ value }}</span></template><template #cell-quantity="{ row }"><ElTooltip :disabled="!issueError" :content="issueError" placement="top" effect="light"><ElInput :model-value="issueQuantity(row.stageKey)" inputmode="numeric" :aria-label="`${row.stage}申请支数`" :class="{ 'review-input-error': !!issueError }" @update:model-value="value => setIssueQuantity(row.stageKey, value)" /></ElTooltip></template><template #cell-remaining="{ row }">{{ stockRemainder(row.stock, row.stageKey) }}</template></DesignTable>
      <div class="notice">公共库存仅匹配相同材质、规格、厚度、长度和合法颜色；喷塑转换出库不计入这里的装配已领数量。</div>
      <footer class="footer-bar"><div><strong :class="issueError ? 'review-warning' : 'brand'">本次合计 {{ Number.isFinite(issueTotal) ? issueTotal : '—' }} / 100 支</strong><span class="muted" style="margin-left:18px">{{ issueError || `提交后剩余可申请 ${100 - issueTotal} 支` }}</span></div><div class="actions"><ElButton @click="emit('navigate', 'stock')">返回</ElButton><ElButton type="primary" :disabled="!!issueError" @click="issueConfirmVisible = true">提交领料申请</ElButton></div></footer>
    </template>

    <div v-if="designMessage" class="notice">{{ designMessage }}</div>

    <AppWindowDialog v-model="sourceVisible" :title="`${activeRecord.source} · 来源详情`" :width="1280" :height="670" :close-on-click-modal="false" class="tube-review-source-dialog">
      <div class="review-dialog-content"><div class="section-heading"><h2>{{ activeRecord.number }}</h2><span class="status success">已入库</span><span class="muted">设计示例</span></div><div class="info-grid review-info-grid"><div class="info-cell"><span>原始单据</span><strong>{{ activeRecord.original }}</strong></div><div class="info-cell"><span>生产订单</span><strong>{{ activeRecord.order }}</strong></div><div class="info-cell"><span>加工厂 / 车间</span><strong>{{ activeRecord.factory }}</strong></div><div class="info-cell"><span>目标仓库 / 库区</span><strong>{{ activeRecord.warehouse }}</strong></div><div class="info-cell"><span>入库日期</span><strong>{{ activeRecord.date }}</strong></div><div class="info-cell"><span>入库人</span><strong>仓管员（设计示例）</strong></div></div>
        <h2>本条入库明细</h2><DesignTable :columns="columns([['part','部位',110],['material','材质',90],['spec','规格',90],['thickness','厚度',100],['length','长度',110],['color','实物颜色',130],['stage','加工状态',130],['quantity','本次入库',130,true]])" :rows="[activeRecord]" />
        <template v-if="activeRecord.source === '外发入库'"><h2>一次回货结果</h2><div class="review-summary-strip"><div><span>本行实际发出</span><strong>{{ activeRecord.sent }} <small>支</small></strong></div><div><span>本行实际回货</span><strong>{{ activeRecord.quantity }}</strong></div><div><span>本行少回差额</span><strong class="review-warning">{{ activeRecord.difference }} <small>支</small></strong></div><div><span>外发单状态</span><strong class="review-summary-text">已结束</strong></div></div><p class="muted">发出来源：厂内已加工件；原交接不重复扣原料，本次仅增加实际收到的已喷塑库存。</p></template>
        <template v-else><h2>入库时冻结的加工依据</h2><div class="info-grid review-info-grid"><div class="info-cell"><span>切管累计报工</span><strong>800 支</strong></div><div class="info-cell"><span>弯管累计报工</span><strong>700 支</strong></div><div class="info-cell"><span>最低有效完成量</span><strong>700 支</strong></div><div class="info-cell"><span>本次首次入库</span><strong>200 支</strong></div></div><p class="muted">保留当时工序版本与报工依据；后续领走库存不会恢复首次加工额度。</p></template>
      </div><template #footer><ElButton @click="sourceVisible = false">关闭</ElButton><ElButton v-if="activeRecord.source === '外发入库'" type="primary" @click="sourceVisible = false; detailState = 'ended'; emit('navigate', 'detail')">查看原外发单</ElButton></template>
    </AppWindowDialog>

    <AppWindowDialog v-model="issuePickerVisible" title="选择公共半成品 · 前腿" :width="1120" :height="410" :close-on-click-modal="false">
      <div class="review-dialog-content"><div class="notice">本订单目标色：黑色。原料本色未喷塑件可混领；已喷塑件须为黑色，不选择来源订单或采购批次。</div><DesignTable :columns="columns([['select','选择',70],['part','部位',100],['spec','规格',90],['thickness','厚度',95],['length','长度',105],['stage','状态',115],['color','颜色',115],['quantity','可用库存',120,true],['zone','库区',100]])" :rows="stocks.slice(0,2)"><template #cell-select="{ row }"><ElCheckbox :model-value="selectedStages.includes(row.stageKey)" :aria-label="`选择${row.stage}`" @change="checked => selectedStages = checked ? [...new Set([...selectedStages, row.stageKey])] : selectedStages.filter(stage => stage !== row.stageKey)" /></template><template #cell-stage="{ row, value }"><span class="status" :class="row.stageKey === 'COATED' ? 'success' : 'neutral'">{{ value }}</span></template></DesignTable></div><template #footer><span class="muted" style="margin-right:auto">已选 {{ selectedStages.length }} 种状态 · 共用100支可领额度</span><ElButton type="primary" @click="issuePickerVisible = false">完成选择</ElButton></template>
    </AppWindowDialog>

    <AppWindowDialog v-model="issueConfirmVisible" title="复核本次领料申请" :width="600" :height="330" :close-on-click-modal="false"><div class="review-dialog-content"><p>订单 SC20260929001 · 组合杯托折叠椅 · 前腿</p><div class="review-confirm-line"><span>已喷塑 · 黑色</span><strong>{{ selectedStages.includes('COATED') ? coatedQuantity : 0 }} 支</strong></div><div class="review-confirm-line"><span>未喷塑 · 原料本色</span><strong>{{ selectedStages.includes('UNCOATED') ? uncoatedQuantity : 0 }} 支</strong></div><div class="review-confirm-line"><span>本次合计 / 共用上限</span><strong class="brand">{{ issueTotal }} / 100 支</strong></div><p class="muted">仅为设计交互示例；正式提交后进入现有领料审核流程。</p></div><template #footer><ElButton @click="issueConfirmVisible = false">返回修改</ElButton><ElButton type="primary" @click="showDesignResult('已演示领料申请复核；没有向业务系统提交申请或改动库存。')">确认申请</ElButton></template></AppWindowDialog>
    <AppWindowDialog v-model="dispatchVisible" title="确认发出 · 厂内已加工件" :width="1120" :height="540" :close-on-click-modal="false"><div class="review-dialog-content"><div class="info-grid review-info-grid"><div class="info-cell"><span>外发单号</span><strong>WF20260929001</strong></div><div class="info-cell"><span>来源计划</span><strong>PC20260929001</strong></div><div class="info-cell"><span>发出状态</span><strong>未喷塑 · 原料本色</strong></div></div><div class="form-field" style="width:230px"><span>实际发出日期</span><ElDatePicker v-model="dispatchDate" type="date" value-format="YYYY-MM-DD" :clearable="false" /></div><DesignTable :columns="columns([['factory','加工厂',210],['product','订单产品',170],['part','部位',110],['original','原状态',120],['color','目标喷塑色',130],['sent','本次发出（支）',170,true]])" :rows="allocations" /><div class="notice">本次合计 1,600 支。确认后记金工实际交接，将预留转为已交接；原料已领，不重复扣原管材根数或米数。</div></div><template #footer><ElButton @click="dispatchVisible = false">返回核对</ElButton><ElButton type="primary" :disabled="!dispatchDate" @click="confirmDispatchPreview">确认交接并发出</ElButton></template></AppWindowDialog>
    <AppWindowDialog v-model="cancelVisible" title="取消待发计划" :width="560" :height="280" :close-on-click-modal="false"><div class="review-dialog-content"><p>WF20260929001 尚未实际发出。</p><p>取消后释放本单 1,600 支金工完成额度预留，不生成实物退库流水。</p><p class="muted">仅演示取消复核；已发出的单据不提供本入口。</p></div><template #footer><ElButton @click="cancelVisible = false">保留计划</ElButton><ElButton type="primary" @click="showDesignResult('已演示待发取消确认；没有取消业务单据或更改预留。')">确认取消</ElButton></template></AppWindowDialog>
  </div>
</template>

<style scoped lang="scss">
.review-info-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px 24px; }
.review-summary-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border: 1px solid #ddd6c9; border-radius: 5px; background: #fcfbf7; }
.review-summary-strip > div { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 46px; padding: 10px 16px; }
.review-summary-strip > div + div { border-left: 1px solid #eae4da; }
.review-summary-strip span { color: #6f6a61; font-size: 12px; }
.review-summary-strip strong { color: #1f1d18; font-size: 16px; font-weight: 600; white-space: nowrap; }
.review-summary-strip small { font-size: 12px; font-weight: 400; }
.review-summary-strip .review-summary-text { font-size: 14px; }
.review-summary-strip strong.brand { color: #c84e28; }
.review-warning, .review-summary-strip strong.review-warning { color: #b8781e; }
.review-dialog-content { display: grid; gap: 18px; color: #4d4c48; font-size: 13px; }
.review-dialog-content p, .review-dialog-content h2 { margin: 0; }
.review-dialog-content .info-cell { grid-template-columns: 116px minmax(0, 1fr); }
.review-dialog-content .info-cell > span:first-child { white-space: nowrap; }
.review-dialog-content h2 { font-size: 16px; color: #1f1d18; }
.review-confirm-line { display: flex; justify-content: space-between; gap: 20px; }
.review-input-error :deep(.el-input__wrapper) { box-shadow: 0 0 0 1px #b53333 inset !important; }
.review-stock-page > .section-heading > .el-button { margin-left: auto; }
</style>
