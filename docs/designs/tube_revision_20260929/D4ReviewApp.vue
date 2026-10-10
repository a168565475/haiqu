<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Menu, Refresh } from '@element-plus/icons-vue'
import Workbench from '@icon-park/vue-next/es/icons/Workbench'
import People from '@icon-park/vue-next/es/icons/People'
import Box from '@icon-park/vue-next/es/icons/Box'
import FactoryBuilding from '@icon-park/vue-next/es/icons/FactoryBuilding'
import ShoppingCart from '@icon-park/vue-next/es/icons/ShoppingCart'
import ConnectionPoint from '@icon-park/vue-next/es/icons/ConnectionPoint'
import Setting from '@icon-park/vue-next/es/icons/Setting'
import Truck from '@icon-park/vue-next/es/icons/Truck'
import Export from '@icon-park/vue-next/es/icons/Export'
import Order from '@icon-park/vue-next/es/icons/Order'
import AppWindowDialog from '../../../src/frontend/src/components/common/AppWindowDialog.vue'
import DesignTable from './DesignTable.vue'

// 本页仅用于图稿确认；全部数据与操作为演示，不调用任何业务接口。
const params = new URLSearchParams(window.location.search)
const sourceOptions = [['RAW_PIPE', '原材料'], ['PUBLIC_SEMI', '未喷塑半成品'], ['METAL', '未入库半成品']]
const stateOptions = [['pending', '待外发'], ['processing', '加工中'], ['cancelled', '已取消']]
const viewOptions = [['normal', '正常详情'], ['long', '多明细滚动'], ['empty', '无明细'], ['loading', '读取中'], ['error', '读取失败'], ['forbidden', '无操作权限'], ['stale', '库存复核失败'], ['result', '提交结果待核对']]
const allowed = (options, value, fallback) => options.some(([key]) => key === value) ? value : fallback
const source = ref(allowed(sourceOptions, params.get('source'), 'RAW_PIPE'))
const state = ref(allowed(stateOptions, params.get('state'), 'pending'))
const stateView = params.get('state') === 'recovery' ? 'result' : params.get('state')
const view = ref(allowed(viewOptions, params.get('view') || stateView, 'normal'))
const dialog = ref(['dispatch', 'cancel'].includes(params.get('dialog')) && state.value === 'pending' && ['normal', 'long'].includes(view.value) ? params.get('dialog') : '')
const dispatchDate = ref('2026-09-30')
const cancellationRemark = ref('')
const selectedPart = ref(null)
const nav = [['工作台', Workbench], ['客户管理', People], ['样品管理', Box], ['产品管理', Box], ['生产管理', FactoryBuilding], ['采购管理', ShoppingCart], ['生产车间', ConnectionPoint]]
const subnav = [['生产配置', Setting], ['计划排产', Workbench], ['内部计划', FactoryBuilding], ['委外加工', Export], ['生产领料', Truck], ['工价方案', Box], ['报工记录', Order]]
const sourceLabel = computed(() => sourceOptions.find(([key]) => key === source.value)?.[1] || '—')
const stateLabel = computed(() => stateOptions.find(([key]) => key === state.value)?.[1] || '—')
const canOperate = computed(() => ['normal', 'long'].includes(view.value) && total.value > 0)
const showDetails = computed(() => !['loading', 'error', 'forbidden'].includes(view.value))
const baseRows = [
  { id: 'front', part: '前腿管', material: 'Q195', spec: '圆管 Φ22', thickness: '0.8', length: '650', color: '原料本色', coating: '黑色', factory: '海丰喷塑厂', pieces: 200, piecesPerBar: 10, materialLength: '6.55', roots: 20, meters: '131.00', operations: [{ name: '弯管', amount: 1400 }, { name: '冲孔', amount: 1200 }] },
  { id: 'rear', part: '后腿管', material: 'Q195', spec: '圆管 Φ22', thickness: '0.8', length: '720', color: '原料本色', coating: '黑色', factory: '海丰喷塑厂', pieces: 300, piecesPerBar: 10, materialLength: '7.25', roots: 30, meters: '217.50', operations: [{ name: '弯管', amount: 1000 }, { name: '冲孔', amount: 1200 }] },
  { id: 'arm', part: '扶手管', material: 'Q195', spec: '椭圆管 30×15', thickness: '0.9', length: '520', color: '原料本色', coating: '黑色', factory: '永兴喷塑厂', pieces: 120, piecesPerBar: 10, materialLength: '5.25', roots: 12, meters: '63.00', operations: [{ name: '弯管', amount: 800 }, { name: '冲孔', amount: 900 }] },
  { id: 'join', part: '连接管', material: 'Q195', spec: '圆管 Φ16', thickness: '0.7', length: '360', color: '原料本色', coating: '黑色', factory: '永兴喷塑厂', pieces: 240, piecesPerBar: 10, materialLength: '3.65', roots: 24, meters: '87.60', operations: [{ name: '冲孔', amount: 1400 }, { name: '焊接', amount: 1200 }] },
  { id: 'back', part: '靠背管', material: 'Q195', spec: '圆管 Φ19', thickness: '0.8', length: '880', color: '原料本色', coating: '黑色', factory: '海丰喷塑厂', pieces: 160, piecesPerBar: 10, materialLength: '8.85', roots: 16, meters: '141.60', operations: [{ name: '弯管', amount: 1000 }, { name: '冲孔', amount: 800 }] },
]
const rows = computed(() => view.value === 'empty' ? [] : view.value === 'long' ? Array.from({ length: 40 }, (_, index) => ({ ...baseRows[index % baseRows.length], id: `part-${index}`, part: `${baseRows[index % baseRows.length].part} ${index + 1}` })) : baseRows)
const total = computed(() => rows.value.reduce((sum, row) => sum + row.pieces, 0))
const totalRoots = computed(() => rows.value.reduce((sum, row) => sum + row.roots, 0))
const totalMeters = computed(() => rows.value.reduce((sum, row) => sum + Number(row.meters), 0).toFixed(2))
const quantityLabel = computed(() => state.value === 'processing' ? '已发支数' : state.value === 'cancelled' ? '原单支数' : '待发支数')
const commonColumns = [
  ['part', '部位', 100], ['material', '材质', 75], ['spec', '规格', 140], ['thickness', '厚度 mm', 85], ['length', '切割长度 mm', 110], ['color', '原料颜色', 100], ['coating', '喷塑颜色', 90], ['factory', '加工厂', 130],
]
const columns = computed(() => {
  const result = [...commonColumns]
  if (source.value === 'RAW_PIPE') result.push(['piecesPerBar', '切割支数 支/根', 115, true], ['materialLength', '原材料长度 m/根', 130, true])
  if (source.value === 'METAL') result.push(['minimum', '当前最低报工（支）', 150, true])
  result.push(['pieces', `${quantityLabel.value}（支）`, 130, true])
  if (source.value === 'RAW_PIPE') result.push(['roots', state.value === 'processing' ? '已扣（根）' : state.value === 'cancelled' ? '原单折算（根）' : '待扣（根）', 105, true], ['meters', state.value === 'processing' ? '已扣（米）' : state.value === 'cancelled' ? '原单折算（米）' : '待扣（米）', 115, true])
  return result.map(([key, label, width, num]) => ({ key, label, width, num }))
})
const dispatchColumns = computed(() => columns.value.filter(col => !['minimum', 'warehouse'].includes(col.key)).map(col => ({ ...col, label: col.key === 'pieces' ? '发出支数（支）' : col.key === 'roots' ? '本次扣（根）' : col.key === 'meters' ? '本次扣（米）' : col.label })))
const operationColumns = [{ key: 'name', label: '必需工序', width: 270 }, { key: 'amount', label: '有效累计报工（支）', width: 240, num: true }, { key: 'basis', label: '完成依据', width: 220 }]
const info = computed(() => [
  ['生产任务单', 'SC20260929001'], ['订单号', 'DD20260921001'], ['排产单号', 'PC20260929001'], ['订单量', '1,000 把'], ['计划发出日', '2026-09-30'], ['预计回货日', '2026-10-15'],
  ['产品名称', '组合杯托折叠椅'], ['品号', 'CP000128'], ['货号', 'HT-806'], ['订单喷塑色', '黑色'], ['建单日期', '2026-09-30'], ['建单人', '刘庆远'],
])
const locationLabel = computed(() => source.value === 'RAW_PIPE' ? '原料管材仓 / 一楼 A区' : source.value === 'PUBLIC_SEMI' ? '半成品管材仓 / 一楼 A区' : '金工车间 · 已报工未入库')
const stockImpact = computed(() => source.value === 'RAW_PIPE' ? '按原单整根换算，扣除原材料根数与米数。' : source.value === 'PUBLIC_SEMI' ? '按发出支数扣除公共未喷塑半成品库存。' : '计入金工已直发数量，不重复扣除原材料库存。')
const statusNote = computed(() => state.value === 'pending' ? '已保存待发 · 实际发出后才扣库存或登记直发' : state.value === 'processing' ? '整单已发出 · 喷塑回货后一次登记入库' : '原单保留 · 已释放待发预留 · 未办理实际发出')
const footerLabel = computed(() => state.value === 'processing' ? '已发出' : state.value === 'cancelled' ? '原单数量' : '待发出')
const format = value => Number(value).toLocaleString('zh-CN')
function minimum(row) { return Math.min(...row.operations.map(item => item.amount)) }
function previewOnly(message) { ElMessage.closeAll(); ElMessage.info({ message: `设计演示：${message}`, duration: 4000 }) }
function resetPreview() { dialog.value = ''; ElMessage.closeAll() }
function openBasis(row) { selectedPart.value = row; dialog.value = 'basis' }
function closeDialog(value) { if (!value) dialog.value = '' }
function dispatch() {
  if (!canOperate.value || state.value !== 'pending') { ElMessage.warning('当前单据不能办理实际发出。'); return }
  if (!dispatchDate.value) { ElMessage.warning('请选择实际发出日期。'); return }
  dialog.value = ''; state.value = 'processing'; previewOnly('整单已发出。此原型未扣库存、未提交业务接口。')
}
function cancel() {
  if (state.value !== 'pending' || (!canOperate.value && view.value !== 'stale')) { ElMessage.warning('当前单据不能取消，请先核对原请求结果。'); return }
  dialog.value = ''; state.value = 'cancelled'; view.value = 'normal'; previewOnly('原单已取消。此原型未变更业务单据或库存。')
}
function refresh() { view.value = 'normal'; previewOnly('重新读取资料并核对原单数量；未办理发出。') }
</script>

<template>
  <div class="shell d4-shell">
    <aside class="sidebar">
      <div class="brand-logo">HiTree</div>
      <div class="nav-list">
        <div v-for="[label, icon] in nav" :key="label" class="nav-item"><component :is="icon" theme="filled" size="20"/><span>{{ label }}</span></div>
        <div v-for="[label, icon] in subnav" :key="label" class="nav-item sub" :class="{ active: label === '委外加工' }"><component :is="icon" theme="filled" size="20"/><span>{{ label }}</span></div>
        <div class="nav-item"><Truck theme="filled" size="20"/><span>仓库管理</span></div>
      </div>
      <div class="nav-bottom"><div class="nav-item"><Setting theme="filled" size="20"/><span>系统配置</span></div></div>
    </aside>
    <header class="topbar d4-topbar">
      <ElIcon><Menu/></ElIcon><span class="crumb">生产车间 / 委外加工 / 管材外发单</span><span class="spacer"/>
      <span class="preview-note">待确认设计 · 示例数据 · 未接入业务</span>
      <ElSelect v-model="source" class="d4-source-picker" aria-label="设计材料来源" @change="resetPreview"><ElOption v-for="[value, label] in sourceOptions" :key="value" :value="value" :label="label"/></ElSelect>
      <ElSelect v-model="state" class="d4-state-picker" aria-label="设计单据状态" @change="resetPreview"><ElOption v-for="[value, label] in stateOptions" :key="value" :value="value" :label="label"/></ElSelect>
      <ElSelect v-model="view" class="d4-view-picker" aria-label="设计显示情况" @change="resetPreview"><ElOption v-for="[value, label] in viewOptions" :key="value" :value="value" :label="label"/></ElSelect>
      <span class="d4-current-user">车间管理员</span>
    </header>
    <main class="main">
      <section class="design-page d4-page">
        <header class="page-heading">
          <div class="title-row"><h1>管材外发单</h1><span class="status" :class="state === 'processing' ? 'info' : state === 'cancelled' ? 'neutral' : 'warning'">{{ stateLabel }}</span><span class="status">{{ sourceLabel }}</span><span class="d4-order-code">WWGC20260930001</span></div>
          <ElButton :icon="ArrowLeft" @click="previewOnly('返回管材外发单列表。')">返回列表</ElButton>
        </header>
        <ElAlert v-if="view === 'result'" type="warning" :closable="false" show-icon title="提交结果尚未确认，请核对原请求结果，避免再次发出或取消。"/>
        <ElAlert v-if="view === 'stale'" type="warning" :closable="false" show-icon title="库存或加工额度复核未通过，尚未发出。可刷新重核原单数量；需要改量、加工厂或库区时，取消后重新创建。"/>
        <template v-if="showDetails">
          <div class="panel d4-context"><div class="info-grid"><div v-for="[label, value] in info" :key="label" class="info-cell"><span>{{ label }}</span><strong>{{ value }}</strong></div></div></div>
          <div class="panel workspace d4-workspace">
            <div class="section-heading d4-section-heading"><div><h2>外发明细</h2><span class="muted">{{ locationLabel }}</span></div><div class="d4-section-actions"><span class="d4-state-note muted">{{ statusNote }}</span><ElButton :icon="Refresh" :disabled="view === 'result'" @click="refresh">刷新</ElButton></div></div>
            <div v-if="state !== 'pending'" class="d4-lifecycle">
              <template v-if="state === 'processing'"><span class="muted">实际发出日期</span><strong>{{ dispatchDate }}</strong><span class="muted">发出经办人</span><strong>刘庆远</strong></template>
              <template v-else><span class="muted">取消日期</span><strong>2026-09-30</strong><span class="muted">取消人</span><strong>刘庆远</strong><span class="muted">取消备注</span><strong class="d4-cancellation-note" :title="cancellationRemark || '—'">{{ cancellationRemark || '—' }}</strong></template>
            </div>
            <DesignTable :columns="columns" :rows="rows" class="d4-lines" empty="此外发单没有可办理的管材明细">
              <template #cell-part="{ row }"><strong>{{ row.part }}</strong></template>
              <template #cell-warehouse><span>半成品管材仓 / 一楼 A区</span></template>
              <template #cell-minimum="{ row }"><ElTooltip content="查看该部位各必需工序的有效累计报工" placement="top"><ElButton link :aria-label="`${row.part}最低报工`" @click="openBasis(row)">{{ format(minimum(row)) }}</ElButton></ElTooltip></template>
              <template #cell-pieces="{ row }"><strong class="brand">{{ format(row.pieces) }}</strong></template>
              <template #cell-roots="{ row }">{{ format(row.roots) }}</template>
            </DesignTable>
            <div class="d4-order-remark d4-remark"><span class="muted">原单备注</span><p>按本单部位明细喷塑，喷塑颜色为订单黑色。各部位分别交至对应加工厂。</p></div>
          </div>
        </template>
        <div v-else class="panel d4-fallback"><ElSkeleton v-if="view === 'loading'" :rows="9" animated/><template v-else><ElEmpty :description="view === 'error' ? '外发单读取失败，请重试' : '当前账号没有查看或办理此单的权限'"/><ElButton v-if="view === 'error'" :icon="Refresh" @click="view = 'normal'">重新加载</ElButton></template></div>
        <footer class="footer-bar d4-footer">
          <div>{{ footerLabel }} <strong>{{ showDetails ? format(total) : '—' }}</strong> 支 <span v-if="showDetails" class="muted"> · {{ rows.length }} 个部位<span v-if="source === 'RAW_PIPE'"> · {{ format(totalRoots) }} 根 / {{ totalMeters }} 米</span></span><small>{{ state === 'cancelled' ? '已取消 · 仓库库存未扣减' : state === 'processing' ? '已按整单数量完成发出' : stockImpact }}</small></div>
          <ElButton v-if="view === 'result'" type="primary" @click="previewOnly('正式页面核对本次原请求结果，不重新提交。')">核对本次提交</ElButton>
          <template v-else-if="state === 'pending'"><ElButton :disabled="!canOperate && view !== 'stale'" @click="dialog = 'cancel'">取消外发单</ElButton><ElButton type="primary" :disabled="!canOperate" @click="dialog = 'dispatch'">确认实际发出</ElButton></template>
          <ElButton v-else-if="state === 'processing'" type="primary" :disabled="!canOperate" @click="previewOnly('后续进入此单喷塑入库页；本轮不包含该页面的设计确认。')">喷塑入库</ElButton>
          <ElButton v-else :disabled="!canOperate" type="primary" @click="previewOnly('以当前任务产品与材料来源重新创建一张外发单；原单保持已取消。')">重新创建外发单</ElButton>
        </footer>
      </section>
    </main>
  </div>

  <AppWindowDialog :model-value="dialog === 'dispatch'" title="确认实际发出" :width="source === 'RAW_PIPE' ? 1480 : 1240" @update:model-value="closeDialog">
    <div class="d4-dispatch">
      <div class="d4-dialog-context"><strong>WWGC20260930001</strong><span>{{ sourceLabel }}</span><span>SC20260929001</span><span>组合杯托折叠椅</span></div>
      <div class="field-grid d4-dispatch-fields">
        <label class="form-field required"><span>实际发出日期</span><ElDatePicker v-model="dispatchDate" type="date" value-format="YYYY-MM-DD" format="YYYY-MM-DD" popper-class="schedule-date-popper" placeholder="选择日期" aria-label="实际发出日期"/></label>
        <label class="form-field"><span>发出经办人</span><ElInput model-value="刘庆远" aria-label="发出经办人" readonly/></label>
        <div class="form-field d4-dispatch-location"><span>材料位置</span><strong>{{ locationLabel }}</strong></div>
      </div>
      <div class="d4-dialog-section"><h2>整单发出明细</h2><span class="muted">按原单已保存数量一次发出 · 数量只读</span></div>
      <DesignTable :columns="dispatchColumns" :rows="rows" class="d4-dispatch-lines">
        <template #cell-part="{ row }"><strong>{{ row.part }}</strong></template>
        <template #cell-pieces="{ row }"><strong class="brand">{{ format(row.pieces) }}</strong></template>
        <template #cell-roots="{ row }">{{ format(row.roots) }}</template>
      </DesignTable>
    </div>
    <template #footer><div class="d4-dispatch-footer"><div><strong>共 {{ format(total) }} 支<span v-if="source === 'RAW_PIPE'"> · {{ format(totalRoots) }} 根 / {{ totalMeters }} 米</span></strong><small class="muted">{{ stockImpact }}</small></div><ElButton @click="dialog = ''">返回核对</ElButton><ElButton type="primary" :disabled="!canOperate" @click="dispatch">确认发出</ElButton></div></template>
  </AppWindowDialog>

  <AppWindowDialog :model-value="dialog === 'cancel'" title="取消待发外发单" :width="720" @update:model-value="closeDialog">
    <div class="d4-cancel">
      <div class="info-grid"><div class="info-cell"><span>外发单号</span><strong>WWGC20260930001</strong></div><div class="info-cell"><span>当前状态</span><strong>待外发</strong></div><div class="info-cell"><span>材料来源</span><strong>{{ sourceLabel }}</strong></div><div class="info-cell"><span>原单数量</span><strong>{{ format(total) }} 支 · {{ rows.length }} 个部位</strong></div></div>
      <p class="d4-cancel-text">确认后释放此单的待发预留，保留已取消原单。仓库库存不发生扣减。</p>
      <label class="form-field"><span>取消备注 <small class="muted">选填</small></span><ElInput v-model="cancellationRemark" type="textarea" :rows="3" maxlength="2000" placeholder="填写取消原因或调整说明" aria-label="取消备注"/></label>
      <p class="d4-cancel-note muted">需要调整数量或加工厂时，取消后重新创建外发单。</p>
    </div>
    <template #footer><ElButton @click="dialog = ''">保留原单</ElButton><ElButton type="primary" @click="cancel">确认取消</ElButton></template>
  </AppWindowDialog>

  <AppWindowDialog :model-value="dialog === 'basis' && Boolean(selectedPart)" :title="`${selectedPart?.part || ''} · 加工完成依据`" :width="860" @update:model-value="closeDialog">
    <div v-if="selectedPart" class="d4-basis"><div class="d4-dialog-context"><span>生产任务 SC20260929001</span><span>工价方案 GJ20260928001 · V2</span><span>当前核算截至 2026-09-30</span></div><DesignTable :columns="operationColumns" :rows="selectedPart.operations" class="d4-operation-lines"><template #cell-amount="{ row }">{{ format(row.amount) }}</template><template #cell-basis="{ row }"><span v-if="row.amount === minimum(selectedPart)" class="status info">最低值</span><span v-else class="muted">已累计</span></template></DesignTable><div class="d4-basis-result"><span>当前最低有效报工</span><strong class="brand">{{ format(minimum(selectedPart)) }}</strong><span>支</span><span class="muted">本单已保存待发 {{ format(selectedPart.pieces) }} 支</span></div><p class="muted">当前报工用于查看依据，不改变原单保存数量。正式发出时重新核对部位额度，按订单需求、实领投入、最低报工及已占用额度检查。</p></div>
    <template #footer><ElButton type="primary" @click="dialog = ''">我知道了</ElButton></template>
  </AppWindowDialog>
</template>
