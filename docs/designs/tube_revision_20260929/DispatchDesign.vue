<script setup>
import {computed, ref, watch} from 'vue'
import {ElMessage} from 'element-plus'
import {Refresh} from '@element-plus/icons-vue'
import AppWindowDialog from '../../../src/frontend/src/components/common/AppWindowDialog.vue'
import DesignTable from './DesignTable.vue'

// 此文件仅为用户确认图稿的交互原型，不调用业务接口。
const props = defineProps({source: {type: String, default: 'raw'}})
const emit = defineEmits(['navigate'])
const source = ref(props.source)
const labels = {metal: '厂内已加工件', semi: '公共未喷塑半成品', raw: '公共原管材'}
const tasks = [
  {id: 'task-1', number: 'SC20260929001', order: 'DD20260921001', plan: 'PC20260929001', products: [
    {id: 'product-1', name: '组合杯托折叠椅', code: 'CP000128', item: 'HT-806', quantity: 1000, color: '黑色', ready: true},
    {id: 'product-2', name: '便携折叠椅', code: 'CP000129', item: 'HT-807', quantity: 500, color: '深灰色', ready: true},
  ]},
  {id: 'task-2', number: 'SC20260929002', order: 'DD20260921002', plan: '', products: [
    {id: 'product-3', name: '休闲折叠椅', code: 'CP000130', item: 'HT-808', quantity: 800, color: '黑色', ready: false},
  ]},
]
const taskId = ref('task-1'), productId = ref('product-1')
const task = computed(() => tasks.find(t => t.id === taskId.value))
const products = computed(() => task.value?.products || [])
const product = computed(() => products.value.find(p => p.id === productId.value))
const ready = computed(() => Boolean(task.value?.plan && product.value?.ready))
const sendDate = ref('2026-09-29'), returnDate = ref('2026-10-14'), remark = ref('')
const warehouse = ref(source.value === 'semi' ? '半成品管材仓' : '原料管材仓'), zone = ref('一楼 A区')
const rows = ref([]), dialog = ref(''), pendingChange = ref(null)
const factories = ['永盛喷塑厂', '华诚喷塑厂']
const number = value => Number(value).toLocaleString('zh-CN')
const warn = message => ElMessage.warning({message, duration: 3000, grouping: true})
const asText = value => String(value ?? '').trim()
const whole = value => /^\d+$/.test(asText(value)) && Number.isSafeInteger(Number(value))
const entered = computed(() => rows.value.filter(r => whole(r.quantity) && Number(r.quantity) > 0))
const total = computed(() => entered.value.reduce((sum, r) => sum + Number(r.quantity), 0))
const factoryCount = computed(() => new Set(entered.value.map(r => r.factory).filter(Boolean)).size)
function rootCount(row) {
  const value = asText(row.quantity)
  if (value === '' || (whole(value) && Number(value) === 0)) return 0
  if (!whole(value) || Number(value) % row.piecesPerRoot !== 0) return null
  return Number(value) / row.piecesPerRoot
}
const roots = computed(() => rows.value.some(r => rootCount(r) === null) ? null : rows.value.reduce((sum, r) => sum + rootCount(r), 0))
const meters = computed(() => roots.value === null ? null : rows.value.reduce((sum, r) => sum + rootCount(r) * r.rawLength, 0))
const emptyMessage = computed(() => !taskId.value ? '请先选择生产任务单，再选择产品' : !productId.value ? '请选择本次外发的一个产品' : '该产品尚无可用排产或喷塑工艺，请先完善计划')
function loadRows(withExamples = false) {
  warehouse.value = source.value === 'semi' ? '半成品管材仓' : '原料管材仓'
  if (!ready.value) {rows.value = []; return}
  const factor = product.value.quantity / 1000
  const parts = [
    ['front', '前腿管', '圆管 Φ22', '0.8', 650, 3.95, 2000, 420, 800, 500],
    ['rear', '后腿管', '圆管 Φ22', '0.8', 720, 4.37, 2000, 380, 500, 500],
    ['arm', '扶手管', '椭圆管 30×15', '0.9', 520, 3.17, 2000, 350, 240, 400],
    ['join', '连接管', '圆管 Φ16', '0.7', 360, 2.21, 4000, 700, 600, 400],
    ['back', '靠背管', '圆管 Φ19', '0.8', 880, 5.33, 2000, 400, 180, 0],
  ]
  rows.value = parts.map(([key, part, spec, thickness, length, rawLength, demand, rawStock, semiStock, reportRemaining], i) => {
    const orderRequired = demand * factor
    // 设计示例额度；正式页须读取后端冻结总额度减已用/预留，不能对余额重新加余量。
    const rawAllowance = Math.ceil(orderRequired * 1.01 / 6) * 6
    const available = source.value === 'raw' ? Math.min(rawStock * 6, rawAllowance) : source.value === 'semi' ? Math.min(orderRequired, semiStock) : Math.min(orderRequired, reportRemaining)
    return {id: `${product.value.id}-${key}`, part, material: 'Q195', spec, thickness, length, color: '原料本色', orderRequired, rawLength, piecesPerRoot: 6, stock: source.value === 'raw' ? rawStock : semiStock, available,
      quantity: withExamples && i < 2 ? (source.value === 'raw' ? ['600', '300'][i] : ['200', '100'][i]) : '',
      factory: withExamples && i < 2 ? factories[i] : '', sprayColor: product.value.color}
  })
}
loadRows(true)
watch(() => props.source, value => {source.value = value; loadRows(false)})
function applyChange() {
  const change = pendingChange.value
  if (!change) return
  if (change.kind === 'task') {taskId.value = change.value; productId.value = ''}
  if (change.kind === 'product') productId.value = change.value
  if (change.kind === 'source') {source.value = change.value; emit('navigate', `dispatch-${change.value}`)}
  if (change.kind === 'warehouse') warehouse.value = change.value
  if (change.kind === 'zone') zone.value = change.value
  if (['task', 'product', 'source'].includes(change.kind)) loadRows(false)
  else rows.value.forEach(r => {r.quantity = ''; r.factory = ''})
  pendingChange.value = null
  dialog.value = ''
}
function requestChange(kind, value) {
  const current = {task: taskId.value, product: productId.value, source: source.value, warehouse: warehouse.value, zone: zone.value}[kind]
  if (current === value) return
  pendingChange.value = {kind, value}
  if (rows.value.some(r => asText(r.quantity) !== '' || r.factory)) dialog.value = 'change'
  else applyChange()
}
const columns = computed(() => [
  ['part', '部位', 85], ['material', '材质', 58], ['spec', '规格', 104], ['thickness', '厚度 mm', 72], ['length', '切割长度 mm', 96], ['color', '原料颜色', 83],
  ['orderRequired', '订单需求（支）', 102, true],
  ...(source.value === 'metal' ? [] : [['stock', source.value === 'raw' ? '库存（根）' : '库存（支）', 85, true]]),
  ['available', '最多可发（支）', 108, true],
  ...(source.value === 'raw' ? [['piecesPerRoot', '每根切割（支）', 104, true], ['rawLength', '原材长度（米）', 108, true]] : []),
  ['quantity', '本次外发（支）', 124],
  ...(source.value === 'raw' ? [['roots', '扣除（根）', 82, true], ['meters', '扣除（米）', 99, true]] : []),
  ['factory', '加工厂', 160], ['sprayColor', '喷塑颜色', 85],
].map(([key, label, width, num]) => ({key, label, width, num})))
function checkDispatch() {
  if (!ready.value) return warn(emptyMessage.value)
  if (!sendDate.value || !returnDate.value) return warn('请填写计划发出日期和预计回货日期。')
  if (source.value !== 'metal' && (!warehouse.value || !zone.value)) return warn('请选择来源仓库和库区。')
  for (const row of rows.value) {
    const value = asText(row.quantity)
    if (value === '') continue
    if (!whole(value)) return warn(`${row.part}：请填写整数支数，不支持负数、小数或文字。`)
    if (Number(value) === 0) continue
    if (source.value === 'raw' && rootCount(row) === null) return warn(`${row.part}：每根切${row.piecesPerRoot}支，填写支数须能整除为根，请填写${row.piecesPerRoot}的整数倍。`)
    if (Number(value) > row.available) return warn(`${row.part}：本次最多可发${row.available}支，不能超量。`)
    if (!factories.includes(row.factory)) return warn(`${row.part}：请选择一家加工厂。`)
  }
  if (!entered.value.length) return warn('请至少填写一项大于0的外发数量。')
  dialog.value = 'confirm'
}
function saveDemo() {
  dialog.value = ''
  ElMessage.success('设计演示：已完成复核，未创建业务单据或改变库存。')
}
const confirmColumns = computed(() => [
  ['part', '部位', 160], ['factory', '加工厂', 200], ['quantity', '本次外发（支）', 160, true],
  ...(source.value === 'raw' ? [['roots', '扣除（根）', 150, true], ['meters', '扣除（米）', 170, true]] : []),
].map(([key, label, width, num]) => ({key, label, width, num})))
</script>

<template>
  <section class="design-page dispatch-design">
    <header class="page-heading"><div class="title-row"><h1>新建管材外发单</h1><span class="status">{{labels[source]}}</span></div><span class="muted">一个产品 · 每个部位一家加工厂</span></header>
    <section class="panel">
      <div class="field-grid">
        <label class="form-field required"><span>生产任务单</span><ElSelect :model-value="taskId" @update:model-value="requestChange('task', $event)" filterable clearable aria-label="生产任务单" placeholder="先选择生产任务单"><ElOption v-for="item in tasks" :key="item.id" :label="item.number" :value="item.id"/></ElSelect></label>
        <label class="form-field required"><span>产品</span><ElSelect :model-value="productId" @update:model-value="requestChange('product', $event)" :disabled="!taskId" filterable clearable aria-label="产品" placeholder="再选择一个产品"><ElOption v-for="item in products" :key="item.id" :label="`${item.code} · ${item.name}`" :value="item.id"/></ElSelect></label>
        <label class="form-field required"><span>材料来源</span><ElSelect :model-value="source" @update:model-value="requestChange('source', $event)" aria-label="材料来源"><ElOption v-for="(label, value) in labels" :key="value" :label="label" :value="value"/></ElSelect></label>
        <label class="form-field"><span>关联排产</span><ElInput :model-value="productId ? (task?.plan || '暂无可用排产') : '选择产品后自动关联'" readonly/></label>
      </div>
      <div class="dispatch-context info-grid"><div class="info-cell"><span>订单号</span><b>{{task?.order || '—'}}</b></div><div class="info-cell"><span>品号</span><b>{{product?.code || '—'}}</b></div><div class="info-cell"><span>货号</span><b>{{product?.item || '—'}}</b></div><div class="info-cell"><span>订单量</span><b>{{product ? number(product.quantity) + ' 把' : '—'}}</b></div><div class="info-cell"><span>外发工艺</span><b>喷塑</b></div></div>
    </section>
    <section class="panel workspace">
      <div class="field-grid">
        <label class="form-field required"><span>计划发出日期</span><ElDatePicker v-model="sendDate" aria-label="计划发出日期" type="date" format="YYYY-MM-DD" value-format="YYYY-MM-DD" placeholder="选择日期"/></label>
        <label class="form-field required"><span>预计回货日期</span><ElDatePicker v-model="returnDate" aria-label="预计回货日期" type="date" format="YYYY-MM-DD" value-format="YYYY-MM-DD" placeholder="选择日期"/></label>
        <template v-if="source !== 'metal'">
          <label class="form-field required"><span>来源仓库</span><ElSelect :model-value="warehouse" @update:model-value="requestChange('warehouse', $event)" aria-label="来源仓库"><ElOption :label="source === 'semi' ? '半成品管材仓' : '原料管材仓'" :value="source === 'semi' ? '半成品管材仓' : '原料管材仓'"/></ElSelect></label>
          <label class="form-field required"><span>库区</span><ElSelect :model-value="zone" @update:model-value="requestChange('zone', $event)" aria-label="库区"><ElOption label="一楼 A区" value="一楼 A区"/><ElOption label="一楼 B区" value="一楼 B区"/></ElSelect></label>
        </template>
        <template v-else><label class="form-field"><span>金工来源计划</span><ElInput :model-value="task?.plan || '—'" readonly/></label><label class="form-field"><span>数量单位</span><ElInput model-value="已加工短管 · 支" disabled/></label></template>
      </div>
      <div class="section-heading"><div><h2>外发管材</h2><span class="muted">按产品BOM带出部位，填写数量并选择一家加工厂；空白或0不外发</span></div><ElButton :icon="Refresh" @click="warn('设计演示：正式提交前重新核对库存及订单额度。')">刷新额度</ElButton></div>
      <DesignTable :columns="columns" :rows="rows" :empty="emptyMessage">
        <template #cell-orderRequired="{value}">{{number(value)}}</template><template #cell-stock="{value}">{{number(value)}}</template>
        <template #cell-available="{value}"><b :class="value ? 'brand' : 'muted'">{{number(value)}}</b></template>
        <template #cell-rawLength="{value}">{{value.toFixed(2)}}</template>
        <template #cell-quantity="{row}"><ElInput v-model="row.quantity" :aria-label="`${row.part}外发支数`" inputmode="numeric" :disabled="!row.available" :placeholder="row.available ? '0' : '暂无可发'"><template v-if="row.available" #suffix>支</template></ElInput></template>
        <template #cell-roots="{row}"><b :class="rootCount(row) === null ? 'brand' : ''">{{rootCount(row) === null ? '须整根' : number(rootCount(row))}}</b></template>
        <template #cell-meters="{row}">{{rootCount(row) === null ? '—' : (rootCount(row) * row.rawLength).toFixed(2)}}</template>
        <template #cell-factory="{row}"><ElSelect v-model="row.factory" :aria-label="`${row.part}加工厂`" :disabled="!row.available" filterable clearable placeholder="选择加工厂"><ElOption v-for="factory in factories" :key="factory" :label="factory" :value="factory"/></ElSelect></template>
      </DesignTable>
      <div class="table-summary"><span>本次外发 <b>{{entered.length}} 个部位</b></span><span>加工厂 <b>{{factoryCount}} 家</b></span><span>合计 <strong class="brand">{{number(total)}} 支</strong></span><template v-if="source === 'raw'"><span>扣除 <b>{{roots === null ? '待修正' : number(roots) + ' 根'}}</b></span><span>扣除米数 <b>{{meters === null ? '待修正' : meters.toFixed(2) + ' 米'}}</b></span></template></div>
      <div class="notice">{{source === 'metal' ? '最多可发按各工序最低累计报工及剩余额度控制，入库与直接外发共用额度；已领原料不重复扣除。' : source === 'semi' ? '按相同BOM属性匹配公共未喷塑库存，按支外发；不选择采购批次或原入库批次。' : '支数 ÷ 每根切割支数 = 扣除根数，必须整除；扣除米数 = 根数 × 原材料长度。最多可发沿用生产领料的订单备料额度与库存限制。'}}<br>同一管材部位不拆分加工厂；本单所有部位、所有厂家统一一次回货登记。需要分次完成回货时，请分别开单。</div>
      <label class="form-field"><span>外发备注 <span class="muted">选填</span></span><ElInput v-model="remark" type="textarea" :rows="2" placeholder="填写加工、交接或送货说明"/></label>
    </section>
    <footer class="footer-bar"><div>本单计划外发 <strong>{{number(total)}}</strong> 支<small>保存后预留数量，实物尚未发出；确认发出时才交接或扣库。</small></div><ElButton @click="emit('navigate', 'detail')">返回</ElButton><ElButton @click="rows.forEach(r => {r.quantity = ''; r.factory = ''})">重填</ElButton><ElButton type="primary" @click="checkDispatch">保存外发单</ElButton></footer>
  </section>
  <AppWindowDialog :model-value="dialog === 'change'" @update:model-value="dialog = ''; pendingChange = null" title="更换来源信息" :width="700"><p>更换后将清空当前填写的外发数量和加工厂，并重新核对管材及额度。</p><p>更换生产任务单还需要重新选择产品。本次尚未保存，不会改变库存。</p><template #footer><ElButton @click="dialog = ''; pendingChange = null">保留当前填写</ElButton><ElButton type="primary" @click="applyChange">确认更换</ElButton></template></AppWindowDialog>
  <AppWindowDialog :model-value="dialog === 'confirm'" @update:model-value="dialog = ''" title="核对并保存管材外发单" :width="1050"><div class="info-grid"><div class="info-cell"><span>生产任务单</span><b>{{task?.number}}</b></div><div class="info-cell"><span>产品</span><b>{{product?.name}}</b></div><div class="info-cell"><span>材料来源</span><b>{{labels[source]}}</b></div></div><DesignTable :columns="confirmColumns" :rows="entered"><template #cell-roots="{row}">{{number(rootCount(row))}}</template><template #cell-meters="{row}">{{(rootCount(row) * row.rawLength).toFixed(2)}}</template></DesignTable><p>本次 {{entered.length}} 个部位、{{factoryCount}} 家加工厂，共 <b>{{number(total)}} 支</b>。每个部位只对应一家加工厂。</p><div class="notice">保存后预留上述数量，实物尚未发出；请在外发单详情确认发出。<br>本单所有部位、所有厂家须统一一次登记回货并结束。</div><template #footer><ElButton @click="dialog = ''">返回检查</ElButton><ElButton type="primary" @click="saveDemo">确认保存</ElButton></template></AppWindowDialog>
</template>

<style scoped>
.dispatch-context{margin-top:14px;padding-top:14px;border-top:1px solid #eae4da}
.dispatch-design :deep(.el-select){width:100%}
</style>
